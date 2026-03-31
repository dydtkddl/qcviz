from __future__ import annotations

import contextlib
import socket
import threading
import time

import httpx
import pytest
import uvicorn


pytestmark = [pytest.mark.e2e]


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def live_server_url(app, patch_fake_runners):
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", ws="wsproto")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    client = httpx.Client(base_url=base_url, timeout=5.0)
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                resp = client.get("/health")
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("Timed out waiting for live uvicorn test server.")

        yield base_url
    finally:
        client.close()
        server.should_exit = True
        thread.join(timeout=5.0)


def test_live_http_server_serves_index_and_assets(live_server_url):
    with httpx.Client(base_url=live_server_url, timeout=5.0) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "text/html" in (index.headers.get("content-type") or "").lower()

        script = client.get("/static/chat.js")
        assert script.status_code == 200
        assert "javascript" in (script.headers.get("content-type") or "").lower()
        assert "clarify" in script.text.lower()


def test_live_http_server_chat_roundtrip(live_server_url):
    with httpx.Client(base_url=live_server_url, timeout=5.0) as client:
        resp = client.post("/api/chat?wait_for_result=true", json={"message": "water HOMO"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["job"]["status"] == "completed"
        assert data["result"]["job_type"] == "orbital_preview"
        assert data["result"]["explanation"]["summary"]
