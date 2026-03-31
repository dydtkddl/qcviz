from __future__ import annotations

import threading
import pytest
from qcviz_mcp.web.routes import compute as compute_route

pytestmark = [pytest.mark.api]


def _register(client, username: str, password: str, display_name: str = "User"):
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 200
    return resp.json()


def _login(client, username: str, password: str):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()


def test_auth_register_login_me_logout_roundtrip(client):
    reg = _register(client, "alice", "supersecret1", "Alice")
    assert reg["ok"] is True
    assert reg["user"]["username"] == "alice"
    assert reg["user"]["role"] == "user"
    assert reg["auth_token"]

    me = client.get("/api/auth/me", headers={"X-QCViz-Auth-Token": reg["auth_token"]})
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["authenticated"] is True
    assert me_data["user"]["username"] == "alice"
    assert me_data["user"]["role"] == "user"

    login = _login(client, "alice", "supersecret1")
    assert login["user"]["display_name"] == "Alice"
    assert login["user"]["role"] == "user"
    assert login["auth_token"]

    logout = client.post("/api/auth/logout", headers={"X-QCViz-Auth-Token": login["auth_token"]})
    assert logout.status_code == 200
    me2 = client.get("/api/auth/me", headers={"X-QCViz-Auth-Token": login["auth_token"]})
    assert me2.status_code == 200
    assert me2.json()["authenticated"] is False


def test_auth_rejects_duplicate_username(client):
    _register(client, "bob", "supersecret1", "Bob")
    dup = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "supersecret1", "display_name": "Bobby"},
    )
    assert dup.status_code == 409


def test_authenticated_user_can_list_and_access_own_jobs_across_sessions(client, patch_fake_runners):
    reg = _register(client, "carol", "supersecret1", "Carol")
    auth_headers = {"X-QCViz-Auth-Token": reg["auth_token"]}

    session_a = client.post("/api/session/bootstrap", json={}).json()
    session_b = client.post("/api/session/bootstrap", json={}).json()

    submit = client.post(
        "/api/compute/jobs",
        headers={
            **auth_headers,
            "X-QCViz-Session-Id": session_a["session_id"],
            "X-QCViz-Session-Token": session_a["session_token"],
        },
        json={"message": "water HOMO", "session_id": session_a["session_id"]},
    )
    assert submit.status_code == 200
    job = submit.json()
    assert job["owner_username"] == "carol"

    listing = client.get("/api/compute/jobs?include_result=true", headers=auth_headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["job_id"] == job["job_id"] for item in items)

    cross_session = client.get(
        f"/api/compute/jobs/{job['job_id']}",
        headers={
            **auth_headers,
            "X-QCViz-Session-Id": session_b["session_id"],
            "X-QCViz-Session-Token": session_b["session_token"],
        },
    )
    assert cross_session.status_code == 200
    assert cross_session.json()["owner_username"] == "carol"


def test_authenticated_user_quota_applies_across_sessions(client, monkeypatch):
    reg = _register(client, "dave", "supersecret1", "Dave")
    auth_headers = {"X-QCViz-Auth-Token": reg["auth_token"]}
    session_a = client.post("/api/session/bootstrap", json={}).json()
    session_b = client.post("/api/session/bootstrap", json={}).json()
    gate = threading.Event()

    def slow_run(payload, progress_callback=None):
        gate.wait(0.5)
        return {
            "success": True,
            "job_type": payload.get("job_type", "single_point"),
            "structure_query": payload.get("structure_query", "water"),
            "visualization": {},
        }

    monkeypatch.setenv("QCVIZ_MAX_ACTIVE_JOBS_PER_USER", "1")
    monkeypatch.setattr(compute_route, "_run_direct_compute", slow_run)

    first = client.post(
        "/api/compute/jobs",
        headers={
            **auth_headers,
            "X-QCViz-Session-Id": session_a["session_id"],
            "X-QCViz-Session-Token": session_a["session_token"],
        },
        json={"message": "water HOMO", "session_id": session_a["session_id"]},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/compute/jobs",
        headers={
            **auth_headers,
            "X-QCViz-Session-Id": session_b["session_id"],
            "X-QCViz-Session-Token": session_b["session_token"],
        },
        json={"message": "acetone ESP", "session_id": session_b["session_id"]},
    )
    gate.set()
    assert second.status_code == 429
    assert "Active job quota exceeded for user 'dave'" in second.json()["detail"]
