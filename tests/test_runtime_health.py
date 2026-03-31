from __future__ import annotations


def test_health_endpoints_expose_runtime_fingerprint(client, patch_fake_runners):
    app_health = client.get("/api/health")
    assert app_health.status_code == 200
    app_data = app_health.json()
    assert "runtime" in app_data
    assert app_data["runtime"]["boot_fingerprint"]
    assert app_data["runtime"]["current_disk_fingerprint"]
    assert app_data["runtime"]["boot_matches_current_disk"] is True

    chat_health = client.get("/api/chat/health")
    assert chat_health.status_code == 200
    chat_data = chat_health.json()
    assert chat_data["runtime"]["boot_fingerprint"] == app_data["runtime"]["boot_fingerprint"]
    assert chat_data["runtime"]["boot_matches_current_disk"] is True

    compute_health = client.get("/api/compute/health")
    assert compute_health.status_code == 200
    compute_data = compute_health.json()
    assert compute_data["runtime"]["boot_fingerprint"] == app_data["runtime"]["boot_fingerprint"]
    assert compute_data["runtime"]["boot_matches_current_disk"] is True
