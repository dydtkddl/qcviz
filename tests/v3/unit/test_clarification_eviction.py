"""Tests for clarification session passive eviction."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import qcviz_mcp.web.routes.chat as chat_route


@pytest.fixture(autouse=True)
def _clean_sessions():
    with chat_route._CLARIFICATION_SESSION_LOCK:
        chat_route._CLARIFICATION_SESSIONS.clear()
    yield
    with chat_route._CLARIFICATION_SESSION_LOCK:
        chat_route._CLARIFICATION_SESSIONS.clear()


class TestClarificationEviction:
    def test_ttl_eviction(self):
        chat_route._session_put("old", {"data": "stale"})
        with chat_route._CLARIFICATION_SESSION_LOCK:
            chat_route._CLARIFICATION_SESSIONS["old"]["created_at"] = time.time() - (
                chat_route._CLARIFICATION_TTL_SECONDS + 60
            )

        assert chat_route._session_get("old") is None

    def test_max_size_eviction(self):
        with patch("qcviz_mcp.web.routes.chat._CLARIFICATION_MAX_SESSIONS", 2):
            chat_route._session_put("s1", {"v": 1})
            chat_route._session_put("s2", {"v": 2})
            chat_route._session_put("s3", {"v": 3})

            assert chat_route._session_get("s1") is None
            assert chat_route._session_get("s3") is not None

    def test_pop_cleans(self):
        chat_route._session_put("x", {"v": 1})
        assert chat_route._session_pop("x") is not None
        assert chat_route._session_get("x") is None

    def test_put_triggers_passive_eviction_without_prior_access(self):
        with patch("qcviz_mcp.web.routes.chat._CLARIFICATION_MAX_SESSIONS", 2):
            chat_route._session_put("leak1", {"v": 1})
            chat_route._session_put("leak2", {"v": 2})
            chat_route._session_put("leak3", {"v": 3})

            assert chat_route._session_get("leak1") is None
