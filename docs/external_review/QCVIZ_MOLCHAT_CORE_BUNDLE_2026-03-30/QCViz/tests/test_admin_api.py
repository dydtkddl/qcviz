from __future__ import annotations

import threading
import time
import uuid

import pytest

from qcviz_mcp.web import auth_store
from qcviz_mcp.web.routes import compute as compute_route

pytestmark = [pytest.mark.api]


def _register(client, username: str, password: str, display_name: str = "User"):
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 200
    return resp.json()


def _bootstrap_session(client, prefix: str = "admin"):
    resp = client.post("/api/session/bootstrap", json={"session_id": f"{prefix}-{uuid.uuid4().hex[:8]}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["session_token"]
    return data


def _login_admin(client, monkeypatch):
    monkeypatch.setenv("QCVIZ_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("QCVIZ_ADMIN_PASSWORD", "supersecret1")
    auth_store.init_auth_db()
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "supersecret1"},
    )
    assert admin_login.status_code == 200
    admin = admin_login.json()
    assert admin["user"]["role"] == "admin"
    return admin


def test_admin_overview_requires_admin(client):
    user = _register(client, "eve", "supersecret1", "Eve")
    forbidden = client.get(
        "/api/admin/overview",
        headers={"X-QCViz-Auth-Token": user["auth_token"]},
    )
    assert forbidden.status_code == 403


def test_admin_overview_exposes_users_jobs_queue_and_quota(client, monkeypatch, patch_fake_runners):
    admin = _login_admin(client, monkeypatch)

    session = client.post("/api/session/bootstrap", json={"session_id": "admin-overview"}).json()
    submit = client.post(
        "/api/compute/jobs",
        headers={
            "X-QCViz-Auth-Token": admin["auth_token"],
            "X-QCViz-Session-Id": session["session_id"],
            "X-QCViz-Session-Token": session["session_token"],
        },
        json={"message": "water HOMO", "session_id": session["session_id"]},
    )
    assert submit.status_code == 200

    overview = client.get(
        "/api/admin/overview",
        headers={"X-QCViz-Auth-Token": admin["auth_token"]},
    )
    assert overview.status_code == 200
    data = overview.json()
    assert data["ok"] is True
    assert data["admin_user"]["username"] == "admin"
    assert data["overview"]["queue"]["max_workers"] >= 1
    assert data["overview"]["job_backend"]["name"] == "inmemory-threadpool"
    assert "quota_config" in data["overview"]
    assert "recovery" in data["overview"]
    assert "workers" in data["overview"]
    assert data["overview"]["counts"]["registered_users"] >= 1
    assert any(item["username"] == "admin" for item in data["overview"]["users"])
    assert any(item["job_id"] == submit.json()["job_id"] for item in data["overview"]["recent_jobs"])


def test_admin_cancel_endpoint_can_cancel_queued_job(client, monkeypatch):
    admin = _login_admin(client, monkeypatch)
    gate = threading.Event()

    def slow_run(payload, progress_callback=None):
        deadline = time.time() + 0.75
        while time.time() < deadline:
            if gate.wait(0.02):
                break
        return {
            "success": True,
            "job_type": payload.get("job_type", "single_point"),
            "structure_query": payload.get("structure_query", "water"),
            "visualization": {},
        }

    monkeypatch.setattr(compute_route, "_run_direct_compute", slow_run)
    session_a = _bootstrap_session(client, "admin-cancel-a")
    session_b = _bootstrap_session(client, "admin-cancel-b")

    first = client.post(
        "/api/compute/jobs",
        headers={
            "X-QCViz-Session-Id": session_a["session_id"],
            "X-QCViz-Session-Token": session_a["session_token"],
        },
        json={"message": "water HOMO", "session_id": session_a["session_id"]},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/compute/jobs",
        headers={
            "X-QCViz-Session-Id": session_b["session_id"],
            "X-QCViz-Session-Token": session_b["session_token"],
        },
        json={"message": "acetone ESP", "session_id": session_b["session_id"]},
    )
    assert second.status_code == 200
    queued_job_id = second.json()["job_id"]

    cancel = client.post(
        f"/api/admin/jobs/{queued_job_id}/cancel",
        headers={"X-QCViz-Auth-Token": admin["auth_token"]},
    )
    gate.set()
    assert cancel.status_code == 200
    data = cancel.json()
    assert data["ok"] is True
    assert data["status"] == "cancelled"
    assert data["job_id"] == queued_job_id
    assert data["admin_user"] == "admin"


def test_admin_requeue_endpoint_returns_retry_metadata(client, monkeypatch, patch_fake_runners):
    admin = _login_admin(client, monkeypatch)
    session = _bootstrap_session(client, "admin-requeue")
    submit = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={
            "X-QCViz-Session-Id": session["session_id"],
            "X-QCViz-Session-Token": session["session_token"],
        },
        json={"message": "water HOMO", "session_id": session["session_id"]},
    )
    assert submit.status_code == 200
    source_job = submit.json()
    assert source_job["status"] == "completed"

    requeue = client.post(
        f"/api/admin/jobs/{source_job['job_id']}/requeue",
        headers={"X-QCViz-Auth-Token": admin["auth_token"]},
        json={"force": True, "reason": "admin_dashboard"},
    )
    assert requeue.status_code == 200
    data = requeue.json()
    assert data["ok"] is True
    assert data["admin_user"] == "admin"
    assert data["source_job_id"] == source_job["job_id"]
    job = data["job"]
    assert job["retry_count"] == 1
    assert job["retry_parent_job_id"] == source_job["job_id"]
    assert job["retry_origin_job_id"] == source_job["job_id"]
