import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DBSession

from app.core.security import aware, can_access_store, digest, has_permission, permissions
from app.models import AuditLog, Session, Store, User, now


def fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def get_db(request: Request):
    with request.app.state.database.session() as db:
        yield db


DB = Annotated[DBSession, Depends(get_db)]


def current_user(request: Request, db: DB) -> User:
    raw = request.cookies.get("sjlerp_session")
    session = db.get(Session, digest(raw)) if raw else None
    if not session or aware(session.expires_at) <= now():
        fail(401, "unauthenticated", "请先登录或重新登录")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        fail(401, "unauthenticated", "账号已停用，请联系管理员")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not csrf.isascii() or not secrets.compare_digest(csrf, session.csrf_token):
            fail(403, "csrf_invalid", "页面会话校验失败，请刷新后重试")
    request.state.session = session
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(permission: str):
    def check(user: CurrentUser):
        if not has_permission(user, permission):
            fail(403, "permission_denied", "当前账号无权执行此操作")
        return user
    return check


def require_store(db: DBSession, user: User, store_id: str) -> Store:
    store = db.get(Store, store_id)
    if not store or not can_access_store(user, store_id):
        fail(404, "not_found", "店铺不存在或无权访问")
    return store


def store_filter(user: User, column):
    return column.in_([store.id for store in user.stores])


def owned_scope(user: User, model, owner_column):
    if user.role == "admin":
        return True
    return or_(store_filter(user, model.store_id), (model.store_id.is_(None) & (owner_column == user.id)))


class Pagination:
    def __init__(self, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset


Page = Annotated[Pagination, Depends()]


def paginated(db, statement, page, serializer):
    count = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    items = db.scalars(statement.limit(page.limit).offset(page.offset)).all()
    return {"items": [serializer(item) for item in items], "total": count}


def serialize_user(user: User):
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role,
            "is_active": user.is_active, "store_ids": [store.id for store in user.stores], "permissions": permissions(user)}


def serialize(model, fields):
    result = {field: getattr(model, field) for field in fields.split()}
    for key, value in result.items():
        if hasattr(value, "isoformat"):
            result[key] = aware(value).isoformat()
    return result


def store_out(store):
    return serialize(store, "id name code legal_entity brand marketplace currency is_active created_at")


def audit_out(item):
    return serialize(item, "id action resource_type resource_id actor_name summary created_at")


def job_out(item, user):
    output = serialize(item, "id kind status store_id created_at started_at finished_at attempts error_message result")
    if item.result is not None:
        result = dict(item.result)
        recorded_scope = result.pop("_scope_store_ids", None)
        current_scope = {store.id for store in user.stores}
        if user.role != "admin" and (recorded_scope is None or not set(recorded_scope).issubset(current_scope)):
            # Historical aggregate results must not survive a reduction in store access.
            output["result"] = None
        else:
            output["result"] = result
    return output


def notification_out(item):
    return serialize(item, "id title message is_read created_at task_id")


def attachment_out(item):
    return serialize(item, "id filename content_type size_bytes store_id created_at")


def audit(db, user, action, resource_type, resource_id, summary, store_id=None):
    db.add(AuditLog(actor_id=user.id if user else None, actor_name=user.display_name if user else "系统",
                    action=action, resource_type=resource_type, resource_id=resource_id, summary=summary, store_id=store_id))
