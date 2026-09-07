from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, LoginAttempt, Session, User, now
from conftest import HEADERS, PASSWORD, login


def test_login_requires_origin_and_ajax_and_session_is_http_only(system):
    client = system["client"]
    credentials = {"email": "admin@example.test", "password": PASSWORD}
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 403
    assert client.post("/api/v1/auth/login", json=credentials, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
    response = client.post("/api/v1/auth/login", json=credentials, headers=HEADERS)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert "password" not in response.text
    assert client.get("/api/v1/auth/me").status_code == 200
    with system["app"].state.database.session() as db:
        session = db.scalar(select(Session))
        assert session.id != client.cookies["sjlerp_session"]


def test_csrf_logout_and_expiry(system):
    client = system["client"]
    headers = login(client)
    assert client.post("/api/v1/stores", json={"name": "安全测试", "code": "NEW"}, headers=HEADERS).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**headers, "X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client)
    with system["app"].state.database.session() as db:
        db.scalar(select(Session)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_non_ascii_csrf_is_rejected_and_password_whitespace_is_preserved(system):
    client = system["client"]
    headers = login(client)
    raw_headers = [(key.encode(), value.encode()) for key, value in headers.items() if key != "X-CSRF-Token"]
    raw_headers.append((b"X-CSRF-Token", b"\xff"))
    assert client.post("/api/v1/auth/logout", headers=raw_headers).status_code == 403
    password = "  Spaces-Are-Part-Of-Password!  "
    response = client.post("/api/v1/users", json={"email": "spaces@example.test", "display_name": "空格密码测试",
                           "password": password, "role": "operator"}, headers=headers)
    assert response.status_code == 201
    assert client.post("/api/v1/auth/login", json={"email": "spaces@example.test", "password": password.strip()}, headers=HEADERS).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "spaces@example.test", "password": password}, headers=HEADERS).status_code == 200


def test_scope_export_sensitive_fields_and_audit_permission(system):
    client, ids = system["client"], system["ids"]
    with system["app"].state.database.session() as db:
        db.add(AuditLog(actor_id=ids["admin"], actor_name="敏感同事", store_id=ids["a"], action="security.test",
                        resource_type="user", summary="不应向运营展示的审计"))
        db.commit()
    headers = login(client, "operator")
    response = client.get("/api/v1/stores").json()
    assert response["total"] == 1
    assert response["items"][0]["id"] == ids["a"]
    assert client.get(f"/api/v1/stores/{ids['b']}").status_code == 404
    exported = client.get("/api/v1/stores/export")
    assert "TEST_A" in exported.text and "TEST_B" not in exported.text
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/audit-logs").status_code == 403
    workspace = client.get("/api/v1/workspace").json()
    assert workspace["user_count"] is None
    assert workspace["recent_activity"] == []
    assert workspace["data_status"] == {"orders": None, "advertising": None, "inventory": None}
    me = client.get("/api/v1/auth/me").json()["user"]
    assert "costs.view" not in me["permissions"] and "finance.view" not in me["permissions"]
    assert client.post("/api/v1/stores", json={"name": "不允许", "code": "DENIED"}, headers=headers).status_code == 403


def test_account_deactivation_revoke_and_last_admin(system):
    client, ids = system["client"], system["ids"]
    login(client, "operator")
    old_cookie = client.cookies["sjlerp_session"]
    headers = login(client)
    response = client.patch(f"/api/v1/users/{ids['operator']}", json={"is_active": False}, headers=headers)
    assert response.status_code == 200
    assert "password_hash" not in response.text
    assert client.patch(f"/api/v1/users/{ids['admin']}", json={"is_active": False}, headers=headers).status_code == 409
    assert client.patch(f"/api/v1/users/{ids['admin']}", json={"role": "operator"}, headers=headers).status_code == 409
    client.cookies.set("sjlerp_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    denied = client.post("/api/v1/auth/login", json={"email": "operator@example.test", "password": PASSWORD}, headers=HEADERS)
    assert denied.status_code == 401


def test_role_or_store_change_revokes_sessions_and_empty_scope_is_empty(system):
    client, ids = system["client"], system["ids"]
    login(client, "operator")
    old_cookie = client.cookies["sjlerp_session"]
    headers = login(client)
    assert client.patch(f"/api/v1/users/{ids['operator']}", json={"store_ids": []}, headers=headers).status_code == 200
    client.cookies.set("sjlerp_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    login(client, "operator")
    assert client.get("/api/v1/stores").json() == {"items": [], "total": 0}


def test_validation_does_not_echo_password_and_rate_limit_persists(system):
    client = system["client"]
    headers = login(client)
    response = client.post("/api/v1/users", json={"email": "bad", "display_name": "用户", "password": "secret", "role": "admin"}, headers=headers)
    assert response.status_code == 422 and "secret" not in response.text
    for _ in range(system["settings"].login_limit):
        response = client.post("/api/v1/auth/login", json={"email": "missing@example.test", "password": "wrong"}, headers=HEADERS)
        assert response.status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PASSWORD}, headers=HEADERS).status_code == 429
    with system["app"].state.database.session() as db:
        assert len(db.scalars(select(LoginAttempt)).all()) == system["settings"].login_limit


def test_store_and_user_crud_unique_constraints_and_audit(system):
    client = system["client"]
    headers = login(client)
    created = client.post("/api/v1/stores", json={"name": "新增测试店", "code": "NEW_TEST"}, headers=headers)
    assert created.status_code == 201
    store_id = created.json()["id"]
    assert client.post("/api/v1/stores", json={"name": "重复代码", "code": "NEW_TEST"}, headers=headers).status_code == 409
    assert client.patch(f"/api/v1/stores/{store_id}", json={"brand": "测试品牌"}, headers=headers).json()["brand"] == "测试品牌"
    created_user = client.post("/api/v1/users", json={"email": "new@example.test", "display_name": "新用户", "password": PASSWORD,
                                                    "role": "warehouse", "store_ids": [store_id]}, headers=headers)
    assert created_user.status_code == 201
    assert "users.manage" not in created_user.json()["permissions"]
    audit = client.get("/api/v1/audit-logs").text
    assert "stores.create" in audit and "users.create" in audit
    assert PASSWORD not in audit and "password_hash" not in audit


def test_csv_formula_neutralization_does_not_change_business_values(system):
    import csv
    import io
    from app.routes import csv_safe

    client = system["client"]
    headers = login(client)
    formula = '=HYPERLINK("https://example.test", "测试")'
    created = client.post("/api/v1/stores", json={"name": formula, "code": "FORMULA_TEST", "brand": "@SUM(1,1)"}, headers=headers)
    assert created.status_code == 201 and created.json()["name"] == formula
    rows = list(csv.reader(io.StringIO(client.get("/api/v1/stores/export").text.lstrip("\ufeff"))))
    row = next(row for row in rows if len(row) > 1 and row[1] == "FORMULA_TEST")
    assert row[0] == "'" + formula and row[3] == "'@SUM(1,1)"
    for value in ["+1", "-1", "=1", "@SUM(1)", "\t1", "\r1", "\n1", "   =1"]:
        assert csv_safe(value) == "'" + value
