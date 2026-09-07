import csv
import hashlib
import io
import os
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select

from app.core.api import (CurrentUser, DB, Page, attachment_out, audit, audit_out, fail, job_out,
                          notification_out, owned_scope, paginated, require, require_store, serialize,
                          serialize_user, store_filter, store_out)
from app.core.security import ROLES, digest, hash_password, has_permission, token, verify_password
from app.models import Approval, Attachment, AuditLog, Job, LoginAttempt, Notification, Session, Store, User, new_id, now
from app.schemas import JobCreate, Login, StoreCreate, StoreUpdate, UserCreate, UserUpdate

router = APIRouter(prefix="/api/v1")
# Match the normal hash cost when an email is unknown, without a default usable password.
DUMMY_HASH = hash_password(token())


@router.post("/auth/login")
def login(payload: Login, request: Request, response: Response, db: DB):
    settings = request.app.state.settings
    identity = digest(payload.email)
    address = digest(request.client.host if request.client else "unknown")
    cutoff = now() - timedelta(seconds=settings.login_window_seconds)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    attempts = db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.created_at >= cutoff, or_(LoginAttempt.identity == identity, LoginAttempt.address == address)))
    if attempts >= settings.login_limit:
        db.commit()
        fail(429, "login_rate_limited", "尝试次数过多，请稍后再试")
    user = db.scalar(select(User).where(User.email == payload.email))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, payload.password)
    if not valid or not user or not user.is_active:
        db.add(LoginAttempt(identity=identity, address=address))
        db.commit()
        fail(401, "invalid_credentials", "邮箱或密码错误，或账号已停用")
    # Lock the account, recheck it after the expensive hash, then issue the session.
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not user.is_active or not verify_password(user.password_hash, payload.password):
        fail(401, "invalid_credentials", "邮箱或密码错误，或账号已停用")
    raw_token, csrf_token = token(), token()
    db.add(Session(id=digest(raw_token), user_id=user.id, csrf_token=csrf_token,
                   expires_at=now() + timedelta(hours=settings.session_hours)))
    db.execute(delete(LoginAttempt).where(LoginAttempt.identity == identity))
    old = request.cookies.get("sjlerp_session")
    if old:
        db.execute(delete(Session).where(Session.id == digest(old)))
    audit(db, user, "auth.login", "user", user.id, "登录系统")
    db.commit()
    response.set_cookie("sjlerp_session", raw_token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", path="/", max_age=settings.session_hours * 3600)
    return {"user": serialize_user(user), "csrf_token": csrf_token}


@router.get("/auth/me")
def me(request: Request, user: CurrentUser):
    return {"user": serialize_user(user), "csrf_token": request.state.session.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB, user: CurrentUser):
    db.delete(request.state.session)
    audit(db, user, "auth.logout", "user", user.id, "退出系统")
    db.commit()
    response.delete_cookie("sjlerp_session", path="/", secure=request.app.state.settings.cookie_secure, httponly=True, samesite="lax")


@router.get("/roles")
def roles(user: CurrentUser):
    return {"items": [{"key": key, **value} for key, value in ROLES.items()], "total": len(ROLES)}


@router.get("/stores")
def stores(db: DB, page: Page, user: Annotated[User, Depends(require("stores.view"))]):
    statement = select(Store).order_by(Store.created_at.desc())
    if user.role != "admin":
        statement = statement.where(store_filter(user, Store.id))
    return paginated(db, statement, page, store_out)


def csv_safe(value):
    text = str(value)
    dangerous = text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@"))
    return "'" + text if dangerous else text


@router.get("/stores/export")
def export_stores(db: DB, user: Annotated[User, Depends(require("stores.export"))]):
    statement = select(Store).order_by(Store.created_at)
    if user.role != "admin":
        statement = statement.where(store_filter(user, Store.id))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["店铺名称", "店铺代码", "经营主体", "品牌", "站点", "币种", "状态"])
    for store in db.scalars(statement):
        writer.writerow([csv_safe(x) for x in [store.name, store.code, store.legal_entity, store.brand,
                                              store.marketplace, store.currency, "启用" if store.is_active else "停用"]])
    audit(db, user, "stores.export", "store", None, "导出权限范围内的店铺档案")
    db.commit()
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="stores.csv"'})


@router.get("/stores/{store_id}")
def store_detail(store_id: str, db: DB, user: Annotated[User, Depends(require("stores.view"))]):
    return store_out(require_store(db, user, store_id))


@router.post("/stores", status_code=201)
def create_store(payload: StoreCreate, db: DB, user: Annotated[User, Depends(require("stores.manage"))]):
    store = Store(**payload.model_dump())
    db.add(store)
    db.flush()
    audit(db, user, "stores.create", "store", store.id, "创建店铺档案", store.id)
    db.commit()
    return store_out(store)


@router.patch("/stores/{store_id}")
def update_store(store_id: str, payload: StoreUpdate, db: DB, user: Annotated[User, Depends(require("stores.manage"))]):
    store = require_store(db, user, store_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        fail(422, "invalid_input", "店铺字段不能设为空值")
    for key, value in changes.items():
        setattr(store, key, value)
    audit(db, user, "stores.update", "store", store.id, "更新店铺档案", store.id)
    db.commit()
    return store_out(store)


def resolve_stores(db, store_ids):
    if len(set(store_ids)) != len(store_ids):
        fail(422, "duplicate_store", "店铺授权列表包含重复项目")
    stores = db.scalars(select(Store).where(Store.id.in_(store_ids))).all()
    if len(stores) != len(store_ids):
        fail(422, "invalid_store", "授权列表包含不存在的店铺")
    return stores


@router.get("/users")
def users(db: DB, page: Page, user: Annotated[User, Depends(require("users.manage"))]):
    return paginated(db, select(User).order_by(User.created_at.desc()), page, serialize_user)


@router.post("/users", status_code=201)
def create_user(payload: UserCreate, db: DB, user: Annotated[User, Depends(require("users.manage"))]):
    record = User(email=payload.email, display_name=payload.display_name, password_hash=hash_password(payload.password),
                  role=payload.role, stores=resolve_stores(db, payload.store_ids))
    db.add(record)
    db.flush()
    audit(db, user, "users.create", "user", record.id, "创建员工账号")
    db.add(Notification(user_id=record.id, title="欢迎使用书剑录 ERP", message="账号已创建，请核对个人资料和店铺授权范围。"))
    db.commit()
    return serialize_user(record)


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UserUpdate, db: DB, user: Annotated[User, Depends(require("users.manage"))]):
    # Serializing all administrator updates protects the last-admin invariant in PostgreSQL.
    admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id).with_for_update()).all()
    record = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not record:
        fail(404, "not_found", "账号不存在")
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        fail(422, "invalid_input", "账号字段不能设为空值")
    if record.id == user.id and changes.get("is_active") is False:
        fail(409, "self_deactivation", "不能停用当前登录账号")
    removes_admin = changes.get("role", record.role) != "admin" or changes.get("is_active", record.is_active) is False
    if record.role == "admin" and record.is_active and removes_admin and len(admins) <= 1:
        fail(409, "last_admin", "必须保留至少一个有效管理员")
    if "store_ids" in changes:
        record.stores = resolve_stores(db, changes.pop("store_ids"))
    if "password" in changes:
        record.password_hash = hash_password(changes.pop("password"))
    for key, value in changes.items():
        setattr(record, key, value)
    if {"role", "store_ids", "password", "is_active"} & payload.model_fields_set:
        db.execute(delete(Session).where(Session.user_id == record.id))
    audit(db, user, "users.update", "user", record.id, "更新员工账号或授权；安全变更会撤销已有会话")
    db.commit()
    return serialize_user(record)


def audits_for(user, store_id=None):
    statement = select(AuditLog)
    if user.role != "admin":
        statement = statement.where(owned_scope(user, AuditLog, AuditLog.actor_id))
    if store_id:
        statement = statement.where(AuditLog.store_id == store_id)
    return statement.order_by(AuditLog.created_at.desc())


@router.get("/workspace")
def workspace(request: Request, db: DB, user: Annotated[User, Depends(require("workspace.view"))], store_id: str | None = None):
    if store_id:
        require_store(db, user, store_id)
    store_statement = select(func.count()).select_from(Store)
    if user.role != "admin":
        store_statement = store_statement.where(store_filter(user, Store.id))
    if store_id:
        store_statement = store_statement.where(Store.id == store_id)
    jobs_statement = select(func.count()).select_from(Job).where(owned_scope(user, Job, Job.owner_id), Job.status.in_(["queued", "running"]))
    if store_id:
        jobs_statement = jobs_statement.where(Job.store_id == store_id)
    pending = db.scalar(jobs_statement)
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)))
    return {"store_count": db.scalar(store_statement),
            "user_count": db.scalar(select(func.count()).select_from(User)) if user.role == "admin" else None,
            "pending_jobs": pending, "unread_notifications": unread,
            "recent_activity": [audit_out(item) for item in db.scalars(audits_for(user, store_id).limit(8))] if has_permission(user, "audit.view") else [],
            "data_status": {"orders": None, "advertising": None, "inventory": None},
            "environment": request.app.state.settings.environment}


@router.get("/audit-logs")
def audit_logs(db: DB, page: Page, user: Annotated[User, Depends(require("audit.view"))], store_id: str | None = None):
    if store_id:
        require_store(db, user, store_id)
    return paginated(db, audits_for(user, store_id), page, audit_out)


@router.get("/notifications")
def notifications(db: DB, page: Page, user: Annotated[User, Depends(require("notifications.view"))]):
    return paginated(db, select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()), page, notification_out)


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str, db: DB, user: Annotated[User, Depends(require("notifications.view"))]):
    record = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not record:
        fail(404, "not_found", "通知不存在或无权访问")
    record.is_read = True
    db.commit()
    return notification_out(record)


@router.get("/jobs")
def jobs(db: DB, page: Page, user: Annotated[User, Depends(require("jobs.view"))], store_id: str | None = None):
    statement = select(Job).where(owned_scope(user, Job, Job.owner_id))
    if store_id:
        require_store(db, user, store_id)
        statement = statement.where(Job.store_id == store_id)
    return paginated(db, statement.order_by(Job.created_at.desc()), page, lambda item: job_out(item, user))


@router.post("/jobs", status_code=202)
def create_job(payload: JobCreate, request: Request, db: DB, user: Annotated[User, Depends(require("jobs.run"))]):
    if payload.store_id:
        require_store(db, user, payload.store_id)
    job = Job(owner_id=user.id, store_id=payload.store_id, kind=payload.kind)
    db.add(job)
    db.flush()
    audit(db, user, "jobs.create", "job", job.id, "提交工作空间检查任务", job.store_id)
    db.commit()
    from app.jobs.service import dispatch_job
    dispatch_job(job.id, request.app.state.settings)
    db.refresh(job)
    return job_out(job, user)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request, db: DB, user: Annotated[User, Depends(require("jobs.run"))]):
    job = db.scalar(select(Job).where(Job.id == job_id, owned_scope(user, Job, Job.owner_id)).with_for_update())
    if not job:
        fail(404, "not_found", "任务不存在或无权访问")
    if user.role != "admin" and job.owner_id != user.id:
        fail(403, "permission_denied", "仅任务发起人或管理员可以重试")
    if job.status != "failed":
        fail(409, "job_not_failed", "只有失败任务可以重试")
    job.status, job.error_message, job.result = "queued", None, None
    job.started_at, job.finished_at = None, None
    audit(db, user, "jobs.retry", "job", job.id, "重试失败任务", job.store_id)
    db.commit()
    from app.jobs.service import dispatch_job
    dispatch_job(job.id, request.app.state.settings)
    db.refresh(job)
    return job_out(job, user)


@router.get("/attachments")
def attachments(db: DB, page: Page, user: Annotated[User, Depends(require("files.view"))], store_id: str | None = None):
    statement = select(Attachment).where(owned_scope(user, Attachment, Attachment.owner_id))
    if store_id:
        require_store(db, user, store_id)
        statement = statement.where(Attachment.store_id == store_id)
    return paginated(db, statement.order_by(Attachment.created_at.desc()), page, attachment_out)


@router.post("/attachments", status_code=201)
def upload_attachment(request: Request, db: DB, user: Annotated[User, Depends(require("files.upload"))],
                      file: Annotated[UploadFile, File()], store_id: Annotated[str | None, Form()] = None):
    if store_id:
        require_store(db, user, store_id)
    settings = request.app.state.settings
    filename = Path((file.filename or "未命名附件").replace("\\", "/")).name
    filename = "".join(char for char in filename if ord(char) >= 32 and char != "\x7f")[:255]
    if filename in {"", ".", ".."}:
        fail(422, "invalid_filename", "文件名无效")
    root = settings.storage_path.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_key = new_id()
    path = root / storage_key
    size = 0
    checksum = hashlib.sha256()
    try:
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    fail(413, "file_too_large", "附件超过上传大小限制")
                checksum.update(chunk)
                output.write(chunk)
        if size == 0:
            fail(422, "empty_file", "不能上传空文件")
        record = Attachment(owner_id=user.id, store_id=store_id, filename=filename,
                            storage_key=storage_key, content_type="application/octet-stream",
                            size_bytes=size, sha256=checksum.hexdigest())
        db.add(record)
        db.flush()
        audit(db, user, "files.upload", "attachment", record.id, "上传私有附件", store_id)
        db.commit()
        return attachment_out(record)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: str, request: Request, db: DB, user: Annotated[User, Depends(require("files.view"))]):
    record = db.scalar(select(Attachment).where(Attachment.id == attachment_id, owned_scope(user, Attachment, Attachment.owner_id)))
    if not record:
        fail(404, "not_found", "附件不存在或无权访问")
    root = request.app.state.settings.storage_path.resolve()
    path = (root / record.storage_key).resolve()
    if path.parent != root or not path.is_file():
        fail(404, "file_missing", "附件文件缺失，请联系管理员恢复备份")
    audit(db, user, "files.download", "attachment", record.id, "下载私有附件", record.store_id)
    db.commit()
    return FileResponse(path, filename=record.filename, media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/approvals")
def approvals(db: DB, page: Page, user: Annotated[User, Depends(require("approvals.view"))], store_id: str | None = None):
    statement = select(Approval).where(owned_scope(user, Approval, Approval.requester_id)).order_by(Approval.created_at.desc())
    if store_id:
        require_store(db, user, store_id)
        statement = statement.where(Approval.store_id == store_id)
    return paginated(db, statement, page, lambda item: serialize(item, "id title resource_type resource_id status store_id created_at"))
