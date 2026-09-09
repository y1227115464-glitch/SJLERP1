import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import Settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.database import Database
from app.routes import router
from app.catalog_routes import router as catalog_router
from app.supply.inventory import router as inventory_router
from app.supply.purchases import router as purchase_router
from app.supply.shipments import router as shipment_router
from app.reports.routes import router as reports_router
from app.tasks.routes import router as tasks_router
from app.tasks.rules import router as task_rules_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="书剑录 ERP API", version="0.1.0", docs_url="/api/docs" if settings.environment != "production" else None,
                  redoc_url=None)
    app.state.settings = settings
    app.state.database = Database(settings)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "X-Requested-With"])

    @app.middleware("http")
    async def safety_headers(request: Request, call_next):
        request_id = str(uuid4())
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin", "").rstrip("/")
            if origin not in settings.origins or request.headers.get("x-requested-with") != "SJLERP":
                return JSONResponse(status_code=403, content={"error": {"code": "origin_rejected", "message": "请求来源校验失败"}},
                                    headers={"X-Request-ID": request_id})
            content_length = request.headers.get("content-length")
            if content_length and (not content_length.isdigit() or int(content_length) > settings.max_upload_bytes + 1024 * 1024):
                return JSONResponse(status_code=413, content={"error": {"code": "request_too_large", "message": "请求超过大小限制"}})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exception):
        error = exception.detail if isinstance(exception.detail, dict) else {"code": "http_error", "message": str(exception.detail)}
        return JSONResponse(status_code=exception.status_code, content={"error": error})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exception):
        # Do not echo submitted passwords, form values or uploaded data in errors.
        details = [{"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]} for error in exception.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "请检查输入字段", "details": details}})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exception):
        return JSONResponse(status_code=409, content={"error": {"code": "conflict", "message": "记录重复或关联资料已变化，请刷新后重试"}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exception):
        logger.error("Database operation failed: %s", type(exception).__name__)
        return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable", "message": "数据服务暂不可用，请稍后重试"}})

    @app.get("/health/live")
    def liveness():
        return {"status": "ok"}

    @app.get("/health/ready")
    @app.get("/health")
    def health():
        checks = {"database": "unavailable", "redis": "unavailable"}
        try:
            with app.state.database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except SQLAlchemyError:
            pass
        try:
            from redis import Redis
            Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception:
            pass
        good = all(value == "ok" for value in checks.values())
        return JSONResponse(status_code=200 if good else 503, content={"status": "ok" if good else "degraded", **checks})

    app.include_router(router)
    app.include_router(catalog_router)
    app.include_router(inventory_router)
    app.include_router(purchase_router)
    app.include_router(shipment_router)
    app.include_router(reports_router)
    app.include_router(task_rules_router)
    app.include_router(tasks_router)
    return app


app = create_app()
