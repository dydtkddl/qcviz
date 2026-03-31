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
def semantic_grounding_stub(monkeypatch):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "direct_name",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.70,
                        "source": "autocomplete",
                        "rationale": "resolved from alias, translation, or typo correction",
                    }
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    class _DummyAgent:
        def suggest_molecules(self, description: str, *, allow_generic_fallback: bool = True):
            return [
                {"name": "water", "formula": "H2O", "atoms": 3, "description": "water"},
                {"name": "methane", "formula": "CH4", "atoms": 5, "description": "methane"},
                {"name": "ethanol", "formula": "C2H6O", "atoms": 9, "description": "ethanol"},
                {"name": "methanol", "formula": "CH4O", "atoms": 6, "description": "methanol"},
                {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "benzene"},
            ]

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: _DummyAgent(), raising=False)
    return True


@pytest.fixture()
def live_server_url(app, patch_fake_runners, semantic_grounding_stub):
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
            raise AssertionError("Timed out waiting for Playwright test server.")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def test_playwright_semantic_dropdown_uses_grounded_candidate_not_water(live_server_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server_url, wait_until="domcontentloaded")
        page.wait_for_selector("#chatInput")
        page.locator("#chatInput").fill("TNT에 들어가는 주물질")
        page.wait_for_function("() => { const btn = document.querySelector('#chatSend'); return btn && !btn.disabled; }")
        page.locator("#chatSend").click()
        page.wait_for_selector(".clarify-select")
        option_values = page.locator(".clarify-select option").evaluate_all(
            "(els) => els.map((el) => (el.value || '').trim())"
        )
        option_texts = page.locator(".clarify-select option").all_text_contents()
        browser.close()

    assert "2,4,6-TRINITROTOLUENE" in option_values
    assert all("water" not in text.lower() for text in option_texts)


def test_playwright_semantic_selection_completes_without_second_composition_prompt(live_server_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server_url, wait_until="domcontentloaded")
        page.wait_for_selector("#chatInput")
        page.locator("#chatInput").fill("main component of TNT")
        page.wait_for_function("() => { const btn = document.querySelector('#chatSend'); return btn && !btn.disabled; }")
        page.locator("#chatSend").click()
        page.wait_for_selector(".clarify-select")
        page.locator(".chat-msg--clarify .clarify-btn--primary").click()

        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('.chat-msg')).some((el) => (el.textContent || '').includes('2,4,6-TRINITROTOLUENE'))"
        )
        page.wait_for_timeout(500)
        clarify_texts = page.locator(".chat-msg--clarify").all_text_contents()
        browser.close()

    assert all("How should this input be interpreted?" not in text for text in clarify_texts)
    assert len(clarify_texts) <= 1
