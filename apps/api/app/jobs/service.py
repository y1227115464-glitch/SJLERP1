import logging
from datetime import timedelta

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.job import Job as RQJob
from rq.exceptions import NoSuchJobError
from sqlalchemy import func, select, update

from app.core.api import audit, owned_scope, store_filter
from app.core.config import Settings
from app.core.database import Database
from app.core.security import can_access_store, has_permission
from app.models import Attachment, Job, Notification, Store, User, now

logger = logging.getLogger(__name__)


def queue_for(settings):
    connection = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=3)
    return Queue(settings.queue_name, connection=connection, default_timeout=settings.job_timeout_seconds)


def dispatch_job(job_id: str, settings: Settings | None = None) -> bool:
    settings = settings or Settings()
    database = Database(settings)
    try:
        with database.session() as db:
            job = db.get(Job, job_id)
            if not job or job.status != "queued":
                return False
            queue = queue_for(settings)
            # Attempts increase only when the database task is claimed by the worker.
            queue_id = f"sjl-{job.id}-{job.attempts + 1}"
            try:
                try:
                    queued = RQJob.fetch(queue_id, connection=queue.connection)
                    if queued.get_status() in {"queued", "started", "deferred", "scheduled"}:
                        return True
                    queued.delete()
                except NoSuchJobError:
                    pass
                queue.enqueue("app.jobs.service.execute_job", job.id, job_id=queue_id,
                              job_timeout=settings.job_timeout_seconds, result_ttl=3600, failure_ttl=86400)
                db.execute(update(Job).where(Job.id == job.id, Job.status == "queued").values(error_message=None))
                db.commit()
                return True
            except RedisError:
                db.execute(update(Job).where(Job.id == job.id, Job.status == "queued").values(
                    error_message="队列暂不可用；任务已保存，后台服务恢复后将重新调度。"))
                db.commit()
                return False
    finally:
        database.engine.dispose()


def check_workspace(db, user, store_id):
    stores = select(Store.id)
    files = select(func.count()).select_from(Attachment).where(owned_scope(user, Attachment, Attachment.owner_id))
    if store_id:
        stores = stores.where(Store.id == store_id)
        files = files.where(Attachment.store_id == store_id)
    elif user.role != "admin":
        stores = stores.where(store_filter(user, Store.id))
    store_ids = list(db.scalars(stores))
    return {"checked_at": now().isoformat(), "store_count": len(store_ids), "attachment_count": db.scalar(files),
            "_scope_store_ids": store_ids,
            "data_status": {"orders": None, "advertising": None, "inventory": None},
            "message": "基础资料与附件可访问性检查完成。订单、广告和库存报表尚未导入。"}


def execute_job(job_id: str, settings: Settings | None = None):
    settings = settings or Settings()
    database = Database(settings)
    try:
        with database.session() as db:
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if not job or job.status != "queued":
                return
            job.status, job.started_at = "running", now()
            job.attempts += 1
            job.error_message = None
            db.commit()
        with database.session() as db:
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            try:
                # Lock the requesting account so permission changes serialize against execution.
                user = db.scalar(select(User).where(User.id == job.owner_id).with_for_update())
                if not user or not has_permission(user, "jobs.run") or (job.store_id and not can_access_store(user, job.store_id)):
                    raise PermissionError("任务发起人的账号或店铺权限已变化，请管理员检查授权。")
                if job.kind != "workspace_check":
                    raise ValueError("不支持的任务类型，请联系管理员。")
                result = check_workspace(db, user, job.store_id)
                job.status, job.result, job.finished_at = "succeeded", result, now()
                db.add(Notification(user_id=job.owner_id, title="工作空间检查完成", message=result["message"]))
                audit(db, user, "jobs.succeeded", "job", job.id, "工作空间检查已完成", job.store_id)
                db.commit()
            except Exception as error:
                db.rollback()
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                job.status, job.finished_at = "failed", now()
                job.result = None
                job.error_message = str(error) if isinstance(error, (PermissionError, ValueError)) else "任务执行失败，请检查服务后重试。"
                db.add(Notification(user_id=job.owner_id, title="后台任务失败", message=job.error_message))
                audit(db, None, "jobs.failed", "job", job.id, "后台任务执行失败，详见任务状态", job.store_id)
                db.commit()
                logger.warning("Business job %s failed: %s", job.id, type(error).__name__)
    finally:
        database.engine.dispose()


def recover_jobs(settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    database = Database(settings)
    failed = 0
    try:
        with database.session() as db:
            stale = db.scalars(select(Job).where(Job.status == "running",
                              Job.started_at < now() - timedelta(seconds=settings.job_timeout_seconds + 60)).with_for_update(skip_locked=True)).all()
            for job in stale:
                job.status, job.finished_at = "failed", now()
                job.error_message = "后台执行超时或进程中断，请确认服务恢复后重试。"
                db.add(Notification(user_id=job.owner_id, title="后台任务中断", message=job.error_message))
                failed += 1
            db.commit()
            queued_ids = list(db.scalars(select(Job.id).where(Job.status == "queued")))
        dispatched = sum(dispatch_job(job_id, settings) for job_id in queued_ids)
        return {"dispatched": dispatched, "failed": failed}
    finally:
        database.engine.dispose()
