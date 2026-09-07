import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app
from app.models import Store, User

PASSWORD = "Only-Test-Password-2026!"
HEADERS = {"Origin": "http://127.0.0.1:5173", "X-Requested-With": "SJLERP"}


@pytest.fixture
def system(tmp_path, monkeypatch):
    base_url = os.environ.get("SJL_TEST_DATABASE_URL")
    cleanup_engine = None
    schema = None
    if base_url:
        schema = "sjltest_" + uuid4().hex
        cleanup_engine = create_engine(base_url)
        with cleanup_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        url = make_url(base_url)
        database_url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    else:
        database_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SJL_DATABASE_URL", database_url)
    monkeypatch.setenv("SJL_ENVIRONMENT", "test")
    settings = Settings(database_url=database_url, environment="test", cookie_secure=False,
                        storage_path=tmp_path / "storage", redis_url="redis://127.0.0.1:1/0")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    app = create_app(settings)
    with app.state.database.session() as db:
        a, b = Store(name="测试甲店", code="TEST_A"), Store(name="测试乙店", code="TEST_B")
        db.add_all([a, b])
        db.flush()
        password_hash = hash_password(PASSWORD)
        admin = User(email="admin@example.test", display_name="测试管理员", role="admin", password_hash=password_hash)
        operator = User(email="operator@example.test", display_name="测试运营", role="operator", password_hash=password_hash, stores=[a])
        finance = User(email="finance@example.test", display_name="测试财务", role="finance", password_hash=password_hash, stores=[b])
        db.add_all([admin, operator, finance])
        db.commit()
        ids = {"admin": admin.id, "operator": operator.id, "finance": finance.id, "a": a.id, "b": b.id}
    monkeypatch.setattr("app.jobs.service.dispatch_job", lambda *args, **kwargs: False)
    with TestClient(app) as client:
        yield {"app": app, "client": client, "settings": settings, "ids": ids}
    app.state.database.engine.dispose()
    if cleanup_engine:
        with cleanup_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        cleanup_engine.dispose()


def login(client, role="admin"):
    response = client.post("/api/v1/auth/login", json={"email": f"{role}@example.test", "password": PASSWORD}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return {**HEADERS, "X-CSRF-Token": response.json()["csrf_token"]}
