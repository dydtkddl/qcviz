from __future__ import annotations

import contextlib
import socket
import threading
import time

import pytest
import uvicorn

from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route

pytestmark = [pytest.mark.e2e]


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def semantic_chat_stub(monkeypatch):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            lowered = str(query or "").lower()
            if "tnt" in lowered:
                return {
                    "query": query,
                    "query_mode": "semantic_descriptor",
                    "resolution_method": "llm",
                    "candidates": [
                        {
                            "name": "2,4,6-TRINITROTOLUENE",
                            "cid": 8376,
                            "molecular_formula": "C7H5N3O6",
                            "confidence": 0.99,
                            "source": "llm",
                            "rationale": "The main component of TNT is trinitrotoluene.",
                        }
                    ],
                    "notes": [],
                }
            if "mea" in lowered:
                return {
                    "query": query,
                    "query_mode": "semantic_descriptor",
                    "resolution_method": "llm",
                    "candidates": [
                        {
                            "name": "Ethanolamine",
                            "cid": 7003,
                            "molecular_formula": "C2H7NO",
                            "confidence": 0.93,
                            "source": "llm",
                            "rationale": "MEA is commonly used as an abbreviation for monoethanolamine / ethanolamine.",
                        }
                    ],
                    "notes": [],
                }
            return {"query": query, "query_mode": "semantic_descriptor", "resolution_method": "llm", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    return True


@pytest.fixture()
def live_semantic_chat_server(app, patch_fake_runners, semantic_chat_stub):
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", ws="wsproto")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            with contextlib.suppress(Exception):
                import httpx

                resp = httpx.get(f"{base_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    break
            time.sleep(0.1)
        else:
            raise AssertionError("Timed out waiting for Playwright semantic chat test server.")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def test_playwright_semantic_question_returns_direct_answer_without_picker(live_semantic_chat_server):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_semantic_chat_server, wait_until="domcontentloaded")
        page.wait_for_selector("#chatInput")
        page.locator("#chatInput").fill("TNT에 들어가는 주물질이 뭐지?")
        page.wait_for_function("() => { const btn = document.querySelector('#chatSend'); return btn && !btn.disabled; }")
        page.locator("#chatSend").click()
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('.chat-msg')).some((el) => (el.textContent || '').includes('2,4,6-TRINITROTOLUENE'))"
        )
        page.wait_for_timeout(500)
        clarify_count = page.locator(".chat-msg--clarify").count()
        all_text = page.locator("#chatMessages").text_content() or ""
        browser.close()

    assert clarify_count == 0
    assert "2,4,6-TRINITROTOLUENE" in all_text
    assert "plan:" not in all_text.lower()
