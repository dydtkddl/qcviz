"""Tests for conversation state eviction and canonical key defaults."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import qcviz_mcp.web.conversation_state as cs


@pytest.fixture(autouse=True)
def _clean_state():
    with cs._STATE_LOCK:
        cs._INMEMORY_STATE.clear()
    with cs._RESULT_INDEX_LOCK:
        cs._RESULT_INDEX.clear()
    yield
    with cs._STATE_LOCK:
        cs._INMEMORY_STATE.clear()
    with cs._RESULT_INDEX_LOCK:
        cs._RESULT_INDEX.clear()


class TestEviction:
    def test_ttl_eviction_on_load(self):
        old_time = time.time() - cs._STATE_TTL_SECONDS - 100
        cs.save_conversation_state("old-session", {"data": "stale", "updated_at": old_time})
        with cs._STATE_LOCK:
            cs._INMEMORY_STATE["old-session"]["updated_at"] = old_time

        cs.save_conversation_state("new-session", {"data": "fresh"})

        assert cs.load_conversation_state("old-session") == {}
        assert cs.load_conversation_state("new-session").get("data") == "fresh"

    def test_max_size_eviction(self):
        with patch("qcviz_mcp.web.conversation_state._STATE_MAX_SESSIONS", 3):
            cs.save_conversation_state("s1", {"v": 1})
            cs.save_conversation_state("s2", {"v": 2})
            cs.save_conversation_state("s3", {"v": 3})
            cs.save_conversation_state("s4", {"v": 4})

            assert cs.load_conversation_state("s1") == {}
            assert cs.load_conversation_state("s4").get("v") == 4

    def test_lru_access_updates_order(self):
        with patch("qcviz_mcp.web.conversation_state._STATE_MAX_SESSIONS", 3):
            cs.save_conversation_state("s1", {"v": 1})
            cs.save_conversation_state("s2", {"v": 2})
            cs.save_conversation_state("s3", {"v": 3})
            cs.load_conversation_state("s1")
            cs.save_conversation_state("s4", {"v": 4})

            assert cs.load_conversation_state("s1").get("v") == 1
            assert cs.load_conversation_state("s2") == {}

    def test_stats(self):
        cs.save_conversation_state("s1", {"v": 1})
        stats = cs.state_store_stats()
        assert stats["state_sessions"] == 1
        assert stats["result_index_sessions"] == 0


class TestCanonicalResultKey:
    def test_default_method_from_pyscf_runner(self):
        key = cs.build_canonical_result_key("water")
        parts = key.split(":")
        assert parts[1] == "b3lyp"
        assert parts[2] == "def2-svp"

    def test_explicit_method_overrides_default(self):
        key = cs.build_canonical_result_key("water", method="HF", basis="STO-3G")
        parts = key.split(":")
        assert parts[1] == "hf"
        assert parts[2] == "sto-3g"

    def test_empty_structure_returns_empty(self):
        assert cs.build_canonical_result_key("") == ""
        assert cs.build_canonical_result_key("  ") == ""
