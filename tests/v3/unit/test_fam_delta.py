from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qcviz_mcp.llm.pipeline import QCVizPromptPipeline
from qcviz_mcp.llm.trace import PipelineTrace
from qcviz_mcp.web.conversation_state import (
    build_canonical_result_key,
    build_execution_state,
    clear_result_index,
    find_previous_result,
    index_completed_result,
    load_conversation_state,
    save_conversation_state,
)
from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route
from qcviz_mcp.web.session_auth import validate_session_token


def _bootstrap_session(client, seed: str = "fam-delta") -> dict:
    resp = client.post("/api/session/bootstrap", json={"session_id": f"{seed}-{int(time.time() * 1000)}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["session_token"]
    return data


def test_pipeline_trace_to_log_dict_includes_failure_class():
    trace = PipelineTrace(trace_id="trace-1", failure_class="planner_error")
    payload = trace.to_log_dict()
    assert payload["failure_class"] == "planner_error"


def test_pipeline_detailed_no_provider_reason(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    pipeline = QCVizPromptPipeline(provider="auto", openai_api_key="", gemini_api_key="")
    assert pipeline._detailed_no_provider_reason() == "no_gemini_key_and_no_openai_key"

    disabled = QCVizPromptPipeline(provider="none", openai_api_key="", gemini_api_key="")
    assert disabled._detailed_no_provider_reason() == "provider_set_to_none"


def test_clarification_session_ttl_prunes_expired_entry():
    session_id = f"clarify-ttl-{time.time_ns()}"
    chat_route._session_put(session_id, {"pending_payload": {"structure_query": "benzene"}})
    with chat_route._CLARIFICATION_SESSION_LOCK:
        chat_route._CLARIFICATION_SESSIONS[session_id]["created_at"] = (
            time.time() - chat_route._CLARIFICATION_TTL_SECONDS - 5
        )

    assert chat_route._session_get(session_id) is None


def test_conversation_state_builds_and_indexes_canonical_result_key():
    session_id = f"state-{time.time_ns()}"
    payload = {
        "session_id": session_id,
        "structure_query": "benzene",
        "method": "B3LYP",
        "basis": "def2-SVP",
        "job_type": "analyze",
        "charge": 0,
        "multiplicity": 1,
    }
    result = {
        "structure_name": "benzene",
        "method": "B3LYP",
        "basis": "def2-SVP",
        "job_type": "analyze",
        "charge": 0,
        "multiplicity": 1,
    }
    state = build_execution_state(payload, result, job_id="job-1")
    expected = build_canonical_result_key("benzene", "B3LYP", "def2-SVP", "analyze", 0, 1)
    assert state["canonical_result_key"] == expected

    index_completed_result(session_id, expected, "job-1")
    assert find_previous_result(session_id, expected) == "job-1"
    clear_result_index(session_id)
    assert find_previous_result(session_id, expected) is None


def test_submit_or_reuse_job_reuses_completed_same_session_result():
    session_id = f"reuse-{time.time_ns()}"
    payload = {
        "session_id": session_id,
        "structure_query": "benzene",
        "method": "B3LYP",
        "basis": "def2-SVP",
        "job_type": "analyze",
        "charge": 0,
        "multiplicity": 1,
    }
    key = build_canonical_result_key("benzene", "B3LYP", "def2-SVP", "analyze", 0, 1)
    index_completed_result(session_id, key, "job-prev")

    class DummyManager:
        def __init__(self) -> None:
            self.submit_calls = 0

        def get(self, job_id: str, **kwargs):
            assert job_id == "job-prev"
            return {
                "job_id": job_id,
                "status": "completed",
                "result": {"structure_name": "benzene", "job_type": "analyze"},
                "events": [],
            }

        def submit(self, payload):
            self.submit_calls += 1
            return {"job_id": "job-new", "status": "queued"}

    manager = DummyManager()
    reused = compute_route._submit_or_reuse_job(payload, manager=manager)
    assert reused["reused"] is True
    assert reused["job_id"] == "job-prev"
    assert manager.submit_calls == 0
    clear_result_index(session_id)


@pytest.mark.asyncio
async def test_prepare_or_clarify_auto_promotes_single_verified_typo_candidate(monkeypatch):
    fake_resolver = SimpleNamespace(
        molchat=SimpleNamespace(
            search=AsyncMock(return_value={"results": [{"name": "methylethylamine"}]})
        ),
        pubchem=SimpleNamespace(
            name_exists=AsyncMock(side_effect=lambda name: name == "methylethylamine")
        ),
    )

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: fake_resolver)
    monkeypatch.setattr(
        chat_route,
        "_build_validated_plan",
        lambda raw_message, payload: {
            "intent": "analyze",
            "query_kind": "compute_ready",
            "job_type": "analyze",
            "structure_query": "Methyl Ethyl aminje",
            "confidence": 0.65,
            "needs_clarification": True,
            "clarification_kind": "typo_suspicion",
            "missing_slots": ["structure_query"],
            "typo_candidates": ["methylethylamine"],
        },
    )

    state = await chat_route._prepare_or_clarify(
        {"session_id": "session-1", "message": "Methyl Ethyl aminje"},
        raw_message="Methyl Ethyl aminje",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert state["requires_clarification"] is False
    assert state["prepared"]["structure_query"] == "methylethylamine"
    assert state["plan"]["clarification_kind"] is None


def test_session_clear_state_endpoint_clears_auth_conversation_and_indexes(client):
    session = _bootstrap_session(client, "clear-state")
    session_id = session["session_id"]
    session_token = session["session_token"]
    key = build_canonical_result_key("benzene", "B3LYP", "def2-SVP", "analyze", 0, 1)

    save_conversation_state(session_id, {"last_structure_query": "benzene"})
    index_completed_result(session_id, key, "job-clear")
    chat_route._session_put(session_id, {"pending_payload": {"structure_query": "benzene"}})

    resp = client.post(
        "/api/session/clear_state",
        json={
            "previous_session_id": session_id,
            "previous_session_token": session_token,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["cleared_session"] == session_id

    with pytest.raises(HTTPException):
        validate_session_token(session_id, session_token)
    assert load_conversation_state(session_id) == {}
    assert find_previous_result(session_id, key) is None
    assert chat_route._session_get(session_id) is None
