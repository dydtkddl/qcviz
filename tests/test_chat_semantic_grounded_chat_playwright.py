from __future__ import annotations

import contextlib
import socket
import threading
import time

import pytest
import uvicorn

from tests.semantic_benchmark import (
    benchmark_param_id,
    expected_candidate_names,
    install_semantic_case_stub,
    iter_case_variants,
    load_semantic_benchmark,
)

pytestmark = [pytest.mark.e2e]

_EXPLANATION_DATASET = load_semantic_benchmark("semantic_explanation_benchmark")
_PLAYWRIGHT_CASE_IDS = {
    "semantic_explanation_mea_direct_answer",
    "semantic_explanation_dma_requires_clarification",
}
_PLAYWRIGHT_PARAMS = [
    pytest.param(case, text, id=benchmark_param_id(case, text))
    for case, text in iter_case_variants(_EXPLANATION_DATASET)
    if case["id"] in _PLAYWRIGHT_CASE_IDS and text == case["input"]
]


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def semantic_case(request):
    return request.param


@pytest.fixture()
def semantic_chat_stub(monkeypatch, semantic_case):
    install_semantic_case_stub(monkeypatch, semantic_case)
    return semantic_case


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


@pytest.mark.parametrize(("semantic_case", "message"), _PLAYWRIGHT_PARAMS, indirect=("semantic_case",))
def test_playwright_semantic_benchmark_behavior_contract(live_semantic_chat_server, semantic_case, message):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_semantic_chat_server, wait_until="domcontentloaded")
        page.wait_for_selector("#chatInput")
        page.locator("#chatInput").fill(message)
        page.wait_for_function("() => { const btn = document.querySelector('#chatSend'); return btn && !btn.disabled; }")
        page.locator("#chatSend").click()
        page.wait_for_timeout(1000)
        clarify_count = page.locator(".chat-msg--clarify").count()
        all_text = page.locator("#chatMessages").text_content() or ""
        browser.close()

    expected_outcome = semantic_case["expected_outcome"]
    candidate_names = expected_candidate_names(semantic_case)
    if expected_outcome == "grounded_direct_answer":
        assert clarify_count == 0
        assert any(name in all_text for name in candidate_names)
        assert "plan:" not in all_text.lower()
        return

    assert expected_outcome == "grounding_clarification"
    assert clarify_count >= 1
    assert all(name in all_text for name in candidate_names)
