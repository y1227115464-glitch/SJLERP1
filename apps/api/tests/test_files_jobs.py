from datetime import timedelta

from sqlalchemy import select

from app.jobs.service import execute_job, recover_jobs
from app.models import Approval, Attachment, Job, Notification, User, now
from conftest import login


def test_attachments_sanitize_and_protect_list_download_upload(system):
    client, ids = system["client"], system["ids"]
    headers = login(client, "operator")
    created = client.post("/api/v1/attachments", files={"file": ("../../safe.txt", b"private content", "text/plain")},
                          data={"store_id": ids["a"]}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["filename"] == "safe.txt"
    assert "storage_key" not in created.text
    attachment_id = created.json()["id"]
    downloaded = client.get(f"/api/v1/attachments/{attachment_id}/download")
    assert downloaded.content == b"private content"
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert "attachment;" in downloaded.headers["content-disposition"]
    assert client.post("/api/v1/attachments", files={"file": ("file.txt", b"bad")}, data={"store_id": ids["b"]}, headers=headers).status_code == 404
    login(client, "finance")
    assert client.get("/api/v1/attachments").json()["total"] == 0
    assert client.get(f"/api/v1/attachments/{attachment_id}/download").status_code == 404


def test_attachment_empty_large_and_streaming_limits(system):
    client = system["client"]
    headers = login(client)
    system["settings"].max_upload_bytes = 10
    assert client.post("/api/v1/attachments", files={"file": ("empty.txt", b"")}, headers=headers).status_code == 422
    assert client.post("/api/v1/attachments", files={"file": ("large.txt", b"01234567890")}, headers=headers).status_code == 413
    with system["app"].state.database.session() as db:
        assert list(db.scalars(select(Attachment))) == []
    assert list(system["settings"].storage_path.iterdir()) == []
    # Force transfer encoding without a Content-Length so the ASGI stream limiter is exercised.
    body = (b"x" * 1024 * 1024 for _ in range(22))
    assert client.post("/api/v1/attachments", content=body, headers={**headers, "Content-Type": "application/octet-stream"}).status_code == 413


def test_job_execution_is_persistent_idempotent_and_scoped(system):
    client, ids = system["client"], system["ids"]
    headers = login(client, "operator")
    assert client.post("/api/v1/jobs", json={"kind": "workspace_check", "store_id": ids["b"]}, headers=headers).status_code == 404
    assert client.post("/api/v1/jobs", json={"kind": "os.system"}, headers=headers).status_code == 422
    created = client.post("/api/v1/jobs", json={"kind": "workspace_check", "store_id": ids["a"]}, headers=headers)
    assert created.status_code == 202 and created.json()["status"] == "queued"
    job_id = created.json()["id"]
    execute_job(job_id, system["settings"])
    execute_job(job_id, system["settings"])
    record = client.get("/api/v1/jobs").json()["items"][0]
    assert record["status"] == "succeeded" and record["attempts"] == 1
    assert record["result"]["store_count"] == 1
    notifications = client.get("/api/v1/notifications").json()["items"]
    assert len(notifications) == 1
    notification_id = notifications[0]["id"]
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers).json()["is_read"] is True
    headers = login(client, "finance")
    assert client.get("/api/v1/jobs").json()["total"] == 0
    assert client.post(f"/api/v1/jobs/{job_id}/retry", headers=headers).status_code == 404
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers).status_code == 404


def test_worker_rechecks_permission_failure_retry_and_recovery(system):
    client, ids = system["client"], system["ids"]
    headers = login(client, "operator")
    job_id = client.post("/api/v1/jobs", json={"kind": "workspace_check", "store_id": ids["a"]}, headers=headers).json()["id"]
    with system["app"].state.database.session() as db:
        db.get(User, ids["operator"]).is_active = False
        db.commit()
    execute_job(job_id, system["settings"])
    headers = login(client)
    record = client.get("/api/v1/jobs").json()["items"][0]
    assert record["status"] == "failed" and "权限" in record["error_message"]
    with system["app"].state.database.session() as db:
        db.get(User, ids["operator"]).is_active = True
        db.commit()
    assert client.post(f"/api/v1/jobs/{job_id}/retry", headers=headers).status_code == 202
    execute_job(job_id, system["settings"])
    record = client.get("/api/v1/jobs").json()["items"][0]
    assert record["status"] == "succeeded" and record["attempts"] == 2
    assert client.post(f"/api/v1/jobs/{job_id}/retry", headers=headers).status_code == 409
    with system["app"].state.database.session() as db:
        interrupted = Job(owner_id=ids["operator"], kind="workspace_check", status="running", attempts=1,
                          started_at=now() - timedelta(minutes=10))
        db.add(interrupted)
        db.commit()
        interrupted_id = interrupted.id
    assert recover_jobs(system["settings"])["failed"] == 1
    with system["app"].state.database.session() as db:
        assert db.get(Job, interrupted_id).status == "failed"


def test_approval_query_inherits_store_scope(system):
    client, ids = system["client"], system["ids"]
    with system["app"].state.database.session() as db:
        db.add_all([Approval(requester_id=ids["admin"], store_id=ids["a"], title="甲店采购", resource_type="purchase", resource_id="A"),
                    Approval(requester_id=ids["admin"], store_id=ids["b"], title="乙店采购", resource_type="purchase", resource_id="B")])
        db.commit()
    login(client, "operator")
    approvals = client.get("/api/v1/approvals").json()
    assert approvals["total"] == 1 and approvals["items"][0]["title"] == "甲店采购"


def test_historical_job_aggregate_hidden_after_scope_reduction(system):
    client, ids = system["client"], system["ids"]
    headers = login(client)
    job_id = client.post("/api/v1/jobs", json={"kind": "workspace_check"}, headers=headers).json()["id"]
    execute_job(job_id, system["settings"])
    response = client.get("/api/v1/jobs").json()["items"][0]
    assert response["result"]["store_count"] == 2
    assert "_scope_store_ids" not in response["result"]
    with system["app"].state.database.session() as db:
        user = db.get(User, ids["admin"])
        user.role = "operator"
        db.commit()
    assert client.get("/api/v1/jobs").json()["items"][0]["result"] is None


def test_queue_dispatch_does_not_overwrite_worker_failure(system, monkeypatch):
    import importlib
    from rq.exceptions import NoSuchJobError
    from app.jobs import service
    # Restore the actual dispatcher replaced by the fixture; queue I/O is isolated below.
    dispatch_job = importlib.reload(service).dispatch_job
    with system["app"].state.database.session() as db:
        job = Job(owner_id=system["ids"]["operator"], kind="workspace_check", store_id=system["ids"]["b"],
                  error_message="队列暂不可用")
        db.add(job)
        db.commit()
        job_id = job.id

    class ImmediateQueue:
        connection = None

        def enqueue(self, function, identifier, **kwargs):
            execute_job(identifier, system["settings"])

    def missing(*args, **kwargs):
        raise NoSuchJobError("isolated test")

    monkeypatch.setattr(service, "queue_for", lambda settings: ImmediateQueue())
    monkeypatch.setattr(service.RQJob, "fetch", missing)
    assert dispatch_job(job_id, system["settings"]) is True
    with system["app"].state.database.session() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed"
        assert "权限" in job.error_message


def test_filter_store_is_enforced_on_all_scope_endpoints(system):
    client, ids = system["client"], system["ids"]
    login(client, "finance")
    for path in ["workspace", "jobs", "attachments", "audit-logs", "approvals"]:
        assert client.get(f"/api/v1/{path}", params={"store_id": ids["a"]}).status_code == 404
        assert client.get(f"/api/v1/{path}", params={"store_id": ids["b"]}).status_code == 200
