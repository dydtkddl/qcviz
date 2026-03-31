import pytest

pytestmark = [pytest.mark.api]


def test_health_endpoints(client):
    for path in ["/health", "/api/health", "/chat/health", "/api/chat/health", "/compute/health", "/api/compute/health"]:
        resp = client.get(path)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        if path.endswith("/chat/health") or path.endswith("/compute/health"):
            assert "metrics_summary" in data
            assert "counters" in data["metrics_summary"]


def test_jobs_list(client):
    for path in ["/compute/jobs", "/api/compute/jobs"]:
        resp = client.get(path)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)


def test_chat_rest_simple(client, patch_fake_runners):
    resp = client.post("/api/chat", json={"message": "water homo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "job" in data
    assert data["job"]["status"] == "queued"


def test_chat_rest_sync(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "water"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "result" in data
    assert data["result"]["success"] is True
