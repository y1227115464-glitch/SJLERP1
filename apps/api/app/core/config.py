from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SJL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://127.0.0.1:5432/sjlerp"
    redis_url: str = "redis://127.0.0.1:6379/0"
    storage_path: Path = Path("../../.local/storage")
    allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    cookie_secure: bool = True
    environment: str = "development"
    session_hours: int = 12
    max_upload_bytes: int = 20 * 1024 * 1024
    job_timeout_seconds: int = 120
    queue_name: str = "sjlerp"
    login_limit: int = 10
    login_window_seconds: int = 900

    @field_validator("session_hours", "max_upload_bytes", "job_timeout_seconds", "login_limit", "login_window_seconds")
    @classmethod
    def positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("配置值必须为正数")
        return value

    @model_validator(mode="after")
    def valid_environment(self):
        if self.database_url.startswith("sqlite") and self.environment not in {"local", "test"}:
            raise ValueError("SQLite 仅允许显式 SJL_ENVIRONMENT=local 或 test")
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("生产环境必须开启安全 Cookie")
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.allowed_origins.split(",") if origin.strip()]
