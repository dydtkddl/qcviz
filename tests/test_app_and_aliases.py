from __future__ import annotations
import pytest
pytestmark = [pytest.mark.api]

def test_health_routes_exist_on_primary_and_api_alias(client):
    for path in ["/health", "/api/health", "/chat/health", "/api/chat/health", "/compute/health", "/api/compute/health"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.json()["ok"] is True

def test_api_root_exposes_route_table(client):
    resp = client.get("/api")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "routes" in data
    assert data["routes"]["http"]["chat_rest"] == "/chat"
    assert data["routes"]["http"]["session_bootstrap"] == "/session/bootstrap"
    assert data["routes"]["api_alias"]["chat_rest"] == "/api/chat"
    assert data["routes"]["api_alias"]["session_bootstrap"] == "/api/session/bootstrap"
    assert data["routes"]["websocket"]["chat"] == "/ws/chat"
    assert data["routes"]["websocket"]["chat_api_alias"] == "/api/ws/chat"

def test_session_bootstrap_exists_on_both_paths(client):
    for path in ["/session/bootstrap", "/api/session/bootstrap"]:
        resp = client.post(path, json={})
        assert resp.status_code == 200, path
        data = resp.json()
        assert data["ok"] is True
        assert data["session_id"]
        assert data["session_token"]

def test_compute_jobs_list_exists_on_both_paths(client):
    for path in ["/compute/jobs", "/api/compute/jobs"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "items" in resp.json()
        assert "count" in resp.json()

def test_static_alias_serves_frontend_assets(client):
    for path in ["/static/chat.js", "/api/static/chat.js", "/static/results.js", "/api/static/results.js", "/static/viewer.js", "/api/static/viewer.js"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "javascript" in (resp.headers.get("content-type") or "").lower()
        assert len(resp.text) > 100


def test_index_exposes_quota_and_admin_ui_shell(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="quotaChip"' in html
    assert 'id="quotaStatusText"' in html
    assert 'id="btnAdminOpen"' in html
    assert 'id="modalAdmin"' in html
