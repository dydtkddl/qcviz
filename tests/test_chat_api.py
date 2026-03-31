from __future__ import annotations
import asyncio
import time
import uuid
import pytest
from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route
from qcviz_mcp.web.conversation_state import load_conversation_state
pytestmark = [pytest.mark.api]


def _bootstrap_session(client, session_id: str | None = None):
    payload = {}
    if session_id:
        payload["session_id"] = f"{session_id}-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/session/bootstrap", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["session_token"]
    return data


def _collect_ws_events(ws, limit=20, terminal=("result", "error", "clarify")):
    events = []
    for _ in range(limit):
        msg = ws.receive_json()
        events.append(msg)
        if msg.get("type") in terminal:
            break
    return events


def test_chat_rest_wait_for_result_returns_plan_and_result(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-rest-1")
    resp = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "벤젠의 HOMO 보여줘", "session_id": session["session_id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["plan"]["job_type"] == "orbital_preview"
    assert data["job"]["status"] == "completed"
    assert data["job"]["session_id"] == session["session_id"]
    assert data["result"]["structure_query"].lower() == "benzene"
    assert data["result"]["visualization"]["available"]["orbital"] is True


def test_chat_rest_bare_english_aromatic_name_does_not_fall_back_to_generic_suggestions(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "Biphenyl HOMO"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["plan"]["job_type"] == "orbital_preview"
    assert data["result"]["structure_query"].lower() == "biphenyl"


def test_chat_rest_bare_english_name_runs_without_generic_structure_picker(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "Biphenyl"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["result"]["structure_query"].lower() == "biphenyl"


def test_chat_rest_korean_methylamine_alias_runs_without_custom_picker(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "메틸아민"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["structure_query"].lower() == "methylamine"
    assert data["result"]["structure_query"].lower() == "methylamine"


def test_chat_rest_formula_alias_mixed_input_runs_without_clarification(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "CH3COOH (acetic acid)"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["structure_query"].lower() == "acetic acid"
    assert data["result"]["structure_query"].lower() == "acetic acid"


def test_chat_rest_korean_acetic_acid_alias_runs_without_generic_picker(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "아세트산"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["result"]["structure_query"].lower() == "acetic acid"


def test_chat_rest_spaced_korean_benzene_noise_runs_without_generic_picker(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "베 ㄴ젠 HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["structure_query"].lower() == "benzene"
    assert data["result"]["structure_query"].lower() == "benzene"


def test_chat_rest_korean_nitrobenzene_phrase_reconstructs_canonical_name(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "니트로 벤젠 ESP 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["job_type"] == "esp_map"
    assert data["plan"]["structure_query"].lower() == "nitrobenzene"
    assert data["result"]["structure_query"].lower() == "nitrobenzene"


def test_chat_rest_compact_korean_nitrobenzene_reconstructs_canonical_name(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "니트로벤젠 ESP 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["job_type"] == "esp_map"
    assert data["plan"]["structure_query"].lower() == "nitrobenzene"
    assert data["result"]["structure_query"].lower() == "nitrobenzene"


def test_chat_rest_multiword_single_molecule_name_is_not_treated_as_composite(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "benzoic acid HOMO"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["plan"]["job_type"] == "orbital_preview"
    assert data["result"]["structure_query"].lower() == "benzoic acid"


def test_chat_rest_true_composite_query_requests_composition_mode(client, patch_fake_runners):
    resp = client.post("/api/chat", json={"message": "benzene and toluene HOMO"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    field_ids = [field["id"] for field in data["clarification"]["fields"]]
    assert "composition_mode" in field_ids


def test_chat_rest_batch_multi_molecule_computation(client, patch_fake_runners):
    paragraph = """
    (a) 아민 CH3NH2 (methylamine) ...
    (b) CH3COOH (acetic acid) ...
    (c) CH2=CH-CH=CH2 (1,3-뷰타다이엔) ...
    (d) CH3CHO (acetaldehyde) ...
    여기에 나오는 물질들 싹다 구조구하고 homo lumo esp다 구해
    """
    resp = client.post("/api/chat?wait_for_result=true", json={"message": paragraph})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["batch_request"] is True
    assert len(data["result"]["molecule_results"]) == 4
    assert set(data["result"]["analysis_bundle"]) == {"structure", "HOMO", "LUMO", "ESP"}
    assert data["result"]["partial_failures"] == []

def test_chat_rest_primary_alias_also_works(client, patch_fake_runners):
    resp = client.post("/chat?wait_for_result=true", json={"message": "아세톤 ESP 맵 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["job"]["status"] == "completed"
    assert data["result"]["job_type"] == "esp_map"
    assert data["result"]["visualization"]["available"]["esp"] is True

def test_chat_rest_returns_clarification_for_missing_structure(client, patch_fake_runners):
    resp = client.post("/api/chat", json={"message": "HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["session_id"]
    assert data["plan"]["job_type"] == "orbital_preview"
    assert data["plan"]["missing_slots"] == ["structure_query"]
    assert data["clarification"]["mode"] == "discovery"
    field_ids = [field["id"] for field in data["clarification"]["fields"]]
    assert "structure_choice" in field_ids
    assert "composition_mode" not in field_ids


def test_chat_rest_follow_up_without_prior_context_returns_continuation_targeting_clarification(client, patch_fake_runners):
    resp = client.post("/api/chat", json={"message": "ESP도 그려줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "continuation_targeting"
    assert data["clarification"]["mode"] == "continuation_targeting"


def test_chat_rest_analysis_only_followup_without_context_uses_continuation_targeting_and_no_raw_sentence_option(
    client, patch_fake_runners
):
    message = "HOMO LUMO ESP가 궁금"
    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "continuation_targeting"
    assert data["clarification"]["mode"] == "continuation_targeting"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert message not in option_values


def test_chat_rest_short_esp_followup_without_context_uses_continuation_targeting(client, patch_fake_runners):
    message = "ESP ㄱㄱ"
    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "continuation_targeting"
    assert data["clarification"]["mode"] == "continuation_targeting"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert message not in option_values


def test_chat_rest_question_like_acronym_routes_to_chat_without_job_submission(
    client, patch_fake_runners, monkeypatch
):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    resp = client.post("/api/chat", json={"message": "MEA알아?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"]["intent"] == "chat"
    assert data["plan"]["query_kind"] == "chat_only"
    assert data.get("job") in (None, {})
    assert "result" not in data
    assert data.get("chat_only") is True or data.get("requires_clarification") is True
    if data.get("chat_only"):
        assert "Ethanolamine" in data["message"] or "abbreviation" in data["message"].lower()
    else:
        assert data["clarification_kind"] == "semantic_grounding"


def test_chat_rest_concept_question_about_homo_routes_to_chat(client, patch_fake_runners, monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    resp = client.post("/api/chat", json={"message": "HOMO가 뭐야?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert data["job"] is None
    assert data["plan"]["intent"] == "chat"
    assert data["plan"]["query_kind"] == "chat_only"


def test_chat_rest_unknown_acronym_compute_request_requires_semantic_grounding(
    client, patch_fake_runners, monkeypatch
):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    resp = client.post("/api/chat", json={"message": "MEA HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "semantic_grounding"
    assert data["plan"]["query_kind"] == "grounding_required"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert "MEA" not in option_values


def test_clarification_form_uses_disambiguation_mode_for_explicit_structure_attempt(monkeypatch):
    class DummyResolver:
        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return [
                {"name": "Biphenyl", "match_kind": "raw_exact", "source": "user_input", "resolver_success": False},
                {"name": "biphenyl", "match_kind": "normalized_exact", "source": "resolver_query_plan", "resolver_success": False},
                {"name": "benzene", "match_kind": "query_variant", "source": "resolver_query_plan", "resolver_success": False},
            ][:limit]

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: DummyResolver(), raising=False)
    form = asyncio.run(
        chat_route._build_clarification_form(
            {"missing_slots": ["structure_query"], "confidence": 0.95},
            {"job_type": "single_point"},
            "Biphenyl",
        )
    )
    assert form is not None
    assert form.mode == "disambiguation"
    assert form.fields[0].id == "structure_choice"
    assert form.fields[0].options[0].value == "Biphenyl"
    assert "입력한 이름 그대로 사용" in (form.fields[0].options[0].label or "")


def test_chat_rest_clarification_roundtrip_executes_job(client, patch_fake_runners):
    first = client.post("/api/chat", json={"message": "HOMO 보여줘"})
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["requires_clarification"] is True

    second = client.post(
        "/api/chat?wait_for_result=true",
        json={
            "type": "clarify_response",
            "session_id": first_data["session_id"],
            "session_token": first_data["session_token"],
            "answers": {"structure_choice": "water"},
        },
    )
    assert second.status_code == 200
    data = second.json()
    assert data["ok"] is True
    assert data["plan"]["job_type"] == "orbital_preview"
    assert data["job"]["status"] == "completed"
    assert data["result"]["structure_query"].lower() == "water"
    assert data["result"]["visualization"]["available"]["orbital"] is True
    assert data["job"]["queue"]["max_workers"] >= 1


def test_chat_rest_follow_up_reuses_same_session_structure_without_clarification(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-1")
    first = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "벤젠의 HOMO 오비탈을 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["structure_query"].lower() == "benzene"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "ESP도 그려줘", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] in {"reuse_last_structure", "add_analysis"}
    assert second_data["result"]["job_type"] == "esp_map"
    assert second_data["result"]["structure_query"].lower() == "benzene"


def test_chat_rest_short_esp_go_go_followup_reuses_last_structure_without_clarification(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-go-go")
    first = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "벤젠의 HOMO 오비탈을 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["structure_query"].lower() == "benzene"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "ESP ㄱㄱ", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] == "add_analysis"
    assert second_data["result"]["job_type"] == "esp_map"
    assert second_data["result"]["structure_query"].lower() == "benzene"


def test_chat_rest_ion_pair_query_runs_without_generic_picker_and_preserves_components(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "EMIM+ TFSI- ESP 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["job_type"] == "esp_map"
    assert data["plan"]["composition_kind"] == "ion_pair"
    assert data["plan"]["structures"] == [
        {"name": "EMIM", "charge": 1},
        {"name": "TFSI", "charge": -1},
    ]
    structure_query = data["result"]["structure_query"].lower()
    assert "emim" in structure_query
    assert "tfsi" in structure_query
    assert data["result"]["job_type"] == "esp_map"


def test_chat_rest_analysis_only_followup_reuses_last_structure_without_clarification(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-analysis-only")
    first = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "뷰타다이엔 구조가궁금", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "HOMO LUMO ESP가 궁금", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] == "add_analysis"
    assert second_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}


def test_chat_rest_semantic_direct_answer_persists_context_for_korean_pronoun_followup(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            if "MEA" in query.upper():
                return {
                    "query": query,
                    "query_mode": "direct_name",
                    "resolution_method": "autocomplete",
                    "candidates": [
                        {
                            "name": "Ethanolamine",
                            "cid": 700,
                            "molecular_formula": "C2H7NO",
                            "confidence": 0.97,
                            "source": "autocomplete",
                            "rationale": "resolved from alias, translation, or typo correction",
                        }
                    ],
                    "notes": [],
                }
            return {"query": query, "query_mode": "direct_name", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    session = _bootstrap_session(client, "chat-semantic-pronoun")
    headers = {
        "X-QCViz-Session-Id": session["session_id"],
        "X-QCViz-Session-Token": session["session_token"],
    }

    first = client.post(
        "/api/chat",
        headers=headers,
        json={"message": "MEA 알아?", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["chat_only"] is True
    assert "Ethanolamine" in first_data["message"]

    state = load_conversation_state(session["session_id"], manager=chat_route.get_job_manager())
    assert state["last_structure_query"] == "Ethanolamine"
    assert state["last_resolved_name"] == "Ethanolamine"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "ㅇㅇ 그거 HOMO 보여줘", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] in {"reuse_last_structure", "add_analysis"}
    assert second_data["result"]["structure_query"] == "Ethanolamine"


def test_chat_rest_korean_pronoun_without_session_does_not_surface_raw_pronoun_candidate(
    client, patch_fake_runners
):
    resp = client.post("/api/chat", json={"message": "그거 HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert "그거" not in option_values


def test_chat_rest_explicit_molecule_overrides_previous_session_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-override")
    first = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "methylamine HOMO 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["structure_query"].lower() == "methylamine"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "뷰타 다이엔 구조만 보여줘", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert second_data["plan"]["job_type"] == "geometry_analysis"
    assert second_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}

@pytest.mark.ws
@pytest.mark.parametrize("ws_path", ["/ws/chat", "/api/ws/chat"])
def test_chat_websocket_contract_success(ws_path, client, patch_fake_runners):
    session = _bootstrap_session(client, "ws-test-1")
    turn_id = "turn-ws-contract"
    with client.websocket_connect(
        f"{ws_path}?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json({
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "message": "Render ESP map for acetone using ACS preset",
            "turn_id": turn_id,
        })
        events = _collect_ws_events(ws, terminal=("result", "error"))
    event_types = [e["type"] for e in events]
    assert event_types[0] == "ack"
    assert "assistant" in event_types
    assert "job_submitted" in event_types
    assert "job_update" in event_types or "job_event" in event_types
    assert event_types[-1] == "result"
    submitted_event = next(e for e in events if e["type"] == "job_submitted")
    assert submitted_event["job"]["queue"]["max_workers"] >= 1
    preview_events = [e for e in events if e.get("type") == "job_update" and e.get("preview_result")]
    assert preview_events
    assert all("queue" in e for e in preview_events)
    assert preview_events[0]["preview_result"]["visualization"]["molecule_xyz"]
    completed_updates = [e for e in events if e.get("type") == "job_update" and e.get("status") == "completed"]
    assert completed_updates
    assert len(completed_updates) == 1
    assert completed_updates[0]["result"]["visualization"]["available"]["esp"] is True
    assert completed_updates[-1]["result"]["visualization"]["available"]["esp"] is True
    turn_events = [e for e in events if e["type"] in {"ack", "assistant", "job_submitted", "result"}]
    assert all(e.get("turn_id") == turn_id for e in turn_events)
    result_event = events[-1]
    assert result_event["result"]["job_type"] == "esp_map"
    assert result_event["result"]["visualization"]["available"]["esp"] is True
    assert result_event["session_id"] == session["session_id"]


@pytest.mark.ws
@pytest.mark.parametrize("ws_path", ["/ws/chat", "/api/ws/chat"])
def test_chat_websocket_semantic_direct_answer_reuses_context_for_korean_pronoun_followup(
    ws_path, client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            if "MEA" in query.upper():
                return {
                    "query": query,
                    "query_mode": "direct_name",
                    "resolution_method": "autocomplete",
                    "candidates": [
                        {
                            "name": "Ethanolamine",
                            "cid": 700,
                            "molecular_formula": "C2H7NO",
                            "confidence": 0.97,
                            "source": "autocomplete",
                            "rationale": "resolved from alias, translation, or typo correction",
                        }
                    ],
                    "notes": [],
                }
            return {"query": query, "query_mode": "direct_name", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    session = _bootstrap_session(client, "ws-semantic-pronoun")
    with client.websocket_connect(
        f"{ws_path}?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        ws.send_json(
            {
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "message": "MEA 알아?",
            }
        )
        first_events = _collect_ws_events(ws, terminal=("assistant", "clarify", "error"))
        assert first_events[-1]["type"] == "assistant"
        assert "Ethanolamine" in first_events[-1]["message"]

        ws.send_json(
            {
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "message": "그거 ESP도",
            }
        )
        second_events = _collect_ws_events(ws, terminal=("result", "error", "clarify"))

    assert all(event["type"] != "clarify" for event in second_events)
    assert second_events[-1]["type"] == "result"
    assert second_events[-1]["result"]["structure_query"] == "Ethanolamine"
    assert second_events[-1]["result"]["job_type"] == "esp_map"


@pytest.mark.ws
def test_chat_websocket_clarification_on_missing_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "ws-test-err")
    with client.websocket_connect(
        f"/api/ws/chat?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json({
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "message": "HOMO 보여줘",
        })
        events = _collect_ws_events(ws)
    event_types = [e["type"] for e in events]
    assert event_types[0] == "ack"
    assert event_types[-1] == "clarify"
    clarify = events[-1]
    assert clarify["session_id"] == session["session_id"]
    assert clarify["form"]["mode"] == "discovery"
    field_ids = [field["id"] for field in clarify["form"]["fields"]]
    assert "structure_choice" in field_ids
    assert "composition_mode" not in field_ids


@pytest.mark.ws
def test_chat_websocket_clarification_roundtrip_executes_job(client, patch_fake_runners):
    session = _bootstrap_session(client, "ws-clarify-1")
    with client.websocket_connect(
        f"/api/ws/chat?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        ws.send_json({
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "message": "HOMO 보여줘",
        })
        first_events = _collect_ws_events(ws)
        clarify = first_events[-1]
        assert clarify["type"] == "clarify"

        ws.send_json(
            {
                "type": "clarify_response",
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "answers": {"structure_choice": "water"},
            }
        )
        second_events = _collect_ws_events(ws, terminal=("result", "error"))

    event_types = [e["type"] for e in second_events]
    assert event_types[0] == "assistant"
    assert "job_submitted" in event_types
    assert "job_update" in event_types or "job_event" in event_types
    assert event_types[-1] == "result"
    submitted_event = next(e for e in second_events if e["type"] == "job_submitted")
    assert submitted_event["job"]["queue"]["max_workers"] >= 1
    result_event = second_events[-1]
    assert result_event["session_id"] == session["session_id"]
    assert result_event["result"]["structure_query"].lower() == "water"
    assert result_event["result"]["visualization"]["available"]["orbital"] is True


@pytest.mark.ws
def test_chat_websocket_question_like_acronym_routes_to_chat_without_job_submission(
    client, patch_fake_runners, monkeypatch
):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    session = _bootstrap_session(client, "ws-chat-only")
    with client.websocket_connect(
        f"/api/ws/chat?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json(
            {
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "message": "MEA알아?",
            }
        )
        events = _collect_ws_events(ws, terminal=("assistant", "clarify", "result", "error"))
    event_types = [event["type"] for event in events]
    assert event_types[0] == "ack"
    assert "job_submitted" not in event_types
    assert event_types[-1] in {"assistant", "clarify"}
    if event_types[-1] == "assistant":
        assert "Ethanolamine" in events[-1]["message"] or "abbreviation" in events[-1]["message"].lower()
    else:
        assert events[-1]["form"]["mode"] == "semantic_grounding"


@pytest.mark.ws
def test_chat_websocket_explicit_molecule_overrides_previous_session_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "ws-followup-override")
    with client.websocket_connect(
        f"/api/ws/chat?session_id={session['session_id']}&session_token={session['session_token']}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        ws.send_json(
            {
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "message": "methylamine HOMO 보여줘",
            }
        )
        first_events = _collect_ws_events(ws, terminal=("result", "error"))
        assert first_events[-1]["type"] == "result"
        assert first_events[-1]["result"]["structure_query"].lower() == "methylamine"

        ws.send_json(
            {
                "session_id": session["session_id"],
                "session_token": session["session_token"],
                "message": "뷰타 다이엔 구조만 보여줘",
            }
        )
        second_events = _collect_ws_events(ws, terminal=("result", "error"))

    assert second_events[-1]["type"] == "result"
    assert second_events[-1]["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}


def test_chat_rest_semantic_descriptor_uses_molchat_grounded_dropdown_and_not_raw_phrase(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "candidates": [
                    {
                        "name": "nitrobenzene",
                        "cid": 7416,
                        "molecular_formula": "C6H5NO2",
                        "confidence": 0.82,
                        "source": "semantic_llm",
                        "rationale": "common nitration-related aromatic precursor candidate",
                    },
                    {
                        "name": "toluene",
                        "cid": 1140,
                        "molecular_formula": "C7H8",
                        "confidence": 0.55,
                        "source": "semantic_llm",
                        "rationale": "common TNT synthesis precursor family candidate",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    message = "TNT에 들어가는 주물질"
    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "semantic_grounding"
    assert data["clarification"]["mode"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert "nitrobenzene" in option_values
    assert "toluene" in option_values
    assert message not in option_values
    assert "water" not in option_values


def test_chat_rest_semantic_descriptor_never_falls_back_to_generic_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)

    message = "TNT에 들어가는 주물질"
    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    assert data["clarification_kind"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values == ["custom"]


def test_chat_rest_semantic_descriptor_does_not_invoke_llm_generic_grounding_when_molchat_already_resolved(
    client, patch_fake_runners, monkeypatch
):
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
        def __init__(self):
            self.calls = []

        def suggest_molecules(self, description: str, *, allow_generic_fallback: bool = True):
            self.calls.append({"description": description, "allow_generic_fallback": allow_generic_fallback})
            return [
                {"name": "water", "formula": "H2O", "atoms": 3, "description": "water"},
                {"name": "methane", "formula": "CH4", "atoms": 5, "description": "methane"},
            ]

    dummy_agent = _DummyAgent()
    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: dummy_agent, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert data["job"] is None
    assert "2,4,6-TRINITROTOLUENE" in data["message"]
    assert "water" not in data["message"].lower()
    assert dummy_agent.calls == []


def test_chat_rest_semantic_descriptor_selected_canonical_candidate_executes_without_second_composition_clarification(
    client, patch_fake_runners, monkeypatch
):
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
                        "confidence": 1.0,
                        "source": "autocomplete",
                        "rationale": "resolved TNT main component",
                    }
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    first = client.post("/api/chat", json={"message": "main component of TNT HOMO 보여줘"})
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is False
    assert first_data["requires_clarification"] is True
    assert first_data["clarification_kind"] == "semantic_grounding"

    second = client.post(
        "/api/chat?wait_for_result=true",
        json={
            "type": "clarify_response",
            "session_id": first_data["session_id"],
            "session_token": first_data["session_token"],
            "answers": {"structure_choice": "2,4,6-TRINITROTOLUENE"},
        },
    )
    assert second.status_code == 200
    data = second.json()
    assert data["ok"] is True
    assert data["result"]["structure_query"] in {"2,4,6-TRINITROTOLUENE", "TNT"}
    assert data["plan"]["structure_query"] in {"2,4,6-TRINITROTOLUENE", "TNT"}
    assert not data["result"].get("structures")
    assert data["result"].get("composition_kind") in {None, "", "single"}
    assert "requires_clarification" not in data


def test_chat_rest_tnt_clarification_defaults_to_trinitrotoluene_when_remote_order_is_wrong(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "Eprinomectin component B1a",
                        "cid": 6444397,
                        "molecular_formula": "C50H75NO14",
                        "confidence": 0.96,
                        "source": "autocomplete",
                        "rationale": "remote ordering glitch",
                    },
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.82,
                        "source": "autocomplete",
                        "rationale": "resolved TNT main component",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    first = client.post("/api/chat", json={"message": "main component of TNT HOMO 보여줘"})
    assert first.status_code == 200
    data = first.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values[:2] == ["2,4,6-TRINITROTOLUENE", "Eprinomectin component B1a"]
    assert structure_field["default"] == "2,4,6-TRINITROTOLUENE"


def test_chat_rest_explicit_tnt_exact_name_executes_without_disambiguation(
    client, patch_fake_runners, monkeypatch
):
    class _DummyResolver:
        molchat = None

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return [
                {
                    "name": "toluene",
                    "match_kind": "query_variant",
                    "source": "resolver_query_plan",
                    "resolver_success": True,
                },
                {
                    "name": "2,4,6-TRINITROTOLUENE",
                    "match_kind": "raw_exact",
                    "source": "user_input",
                    "resolver_success": False,
                },
                {
                    "name": "6-TRINITROTOLUENE",
                    "match_kind": "query_variant",
                    "source": "resolver_query_plan",
                    "resolver_success": False,
                },
            ]

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    resp = client.post("/api/chat?wait_for_result=true", json={"message": "2,4,6-TRINITROTOLUENE HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["structure_query"] == "2,4,6-TRINITROTOLUENE"
    assert data["result"]["structure_query"] == "2,4,6-TRINITROTOLUENE"
    assert data["result"]["visualization"]["available"]["orbital"] is True


def test_chat_rest_explicit_tnt_keeps_full_structure_name_through_execution(
    client, patch_fake_runners, monkeypatch
):
    class _Resolved:
        def __init__(self, name: str):
            self.xyz = "3\n2,4,6-TRINITROTOLUENE\nC 0 0 0\nH 0 0 1\nH 0 1 0"
            self.smiles = "CC1=C(C=C(C=C1[N+](=O)[O-])[N+](=O)[O-])[N+](=O)[O-]"
            self.cid = 8376
            self.name = name
            self.source = "dummy"
            self.sdf = None
            self.molecular_weight = None
            self.query_plan = None

    class _DummyResolver:
        molchat = None

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return [
                {
                    "name": "toluene",
                    "match_kind": "query_variant",
                    "source": "resolver_query_plan",
                    "resolver_success": True,
                },
                {
                    "name": "2,4,6-TRINITROTOLUENE",
                    "match_kind": "raw_exact",
                    "source": "user_input",
                    "resolver_success": False,
                },
                {
                    "name": "6-TRINITROTOLUENE",
                    "match_kind": "query_variant",
                    "source": "resolver_query_plan",
                    "resolver_success": False,
                },
            ]

        async def resolve(self, query: str):
            return _Resolved("2,4,6-TRINITROTOLUENE")

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    resp = client.post("/api/chat?wait_for_result=true", json={"message": "2,4,6-TRINITROTOLUENE HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["plan"]["structure_query"] == "2,4,6-TRINITROTOLUENE"
    assert data["result"]["structure_query"] == "2,4,6-TRINITROTOLUENE"


def test_chat_rest_semantic_descriptor_discards_generic_llm_fallback_even_when_agent_returns_default_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    class _DummyAgent:
        def __init__(self):
            self.calls = []

        def suggest_molecules(self, description: str):
            self.calls.append(description)
            return [
                {"name": "water", "formula": "H2O", "atoms": 3, "description": "water"},
                {"name": "methane", "formula": "CH4", "atoms": 5, "description": "methane"},
                {"name": "ethanol", "formula": "C2H6O", "atoms": 9, "description": "ethanol"},
                {"name": "methanol", "formula": "CH4O", "atoms": 6, "description": "methanol"},
                {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "benzene"},
            ]

    dummy_agent = _DummyAgent()
    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: dummy_agent, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["clarification_kind"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values == ["custom"]
    assert dummy_agent.calls == ["TNT에 들어가는 주물질"]


def test_safe_plan_message_backfills_semantic_chat_routing_when_agent_returns_null_fields(
    monkeypatch,
):
    class _DummyAgent:
        def plan(self, message: str):
            return {
                "intent": "analyze",
                "job_type": "analyze",
                "query_kind": None,
                "semantic_grounding_needed": None,
                "unknown_acronyms": None,
                "structure_query": "MEA",
                "chat_response": None,
            }

    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: _DummyAgent(), raising=False)
    plan = compute_route._safe_plan_message("MEA라는 물질이뭐야?")
    assert plan["intent"] == "chat"
    assert plan["job_type"] == "chat"
    assert plan["query_kind"] == "chat_only"
    assert plan["semantic_grounding_needed"] is True
    assert "MEA" in list(plan.get("unknown_acronyms") or [])


def test_safe_plan_message_overrides_authoritative_chat_only_for_semantic_grounding_and_followups(
    monkeypatch,
):
    class _AuthoritativeChatAgent:
        def plan(self, message: str):
            return {
                "intent": "chat",
                "job_type": "chat",
                "query_kind": "chat_only",
                "planner_lane": "chat_only",
                "lane_locked": True,
                "semantic_grounding_needed": False,
                "unknown_acronyms": [],
            }

    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: _AuthoritativeChatAgent(), raising=False)

    semantic_chat_plan = compute_route._safe_plan_message("MEA \uc54c\uc544?")
    assert semantic_chat_plan["query_kind"] == "chat_only"
    assert semantic_chat_plan["semantic_grounding_needed"] is True
    assert "MEA" in list(semantic_chat_plan.get("unknown_acronyms") or [])

    semantic_compute_plan = compute_route._safe_plan_message("MEA HOMO \ubcf4\uc5ec\uc918")
    assert semantic_compute_plan["query_kind"] == "grounding_required"
    assert semantic_compute_plan["semantic_grounding_needed"] is True
    assert semantic_compute_plan["job_type"] == "orbital_preview"
    assert semantic_compute_plan["chat_only"] is False

    follow_up_plan = compute_route._safe_plan_message("\u3147\u3147 \uadf8\uac70 HOMO \ubcf4\uc5ec\uc918")
    assert follow_up_plan["query_kind"] == "compute_ready"
    assert follow_up_plan["follow_up_mode"] == "add_analysis"
    assert follow_up_plan["job_type"] == "orbital_preview"
    assert follow_up_plan["chat_only"] is False


def test_chat_rest_parameter_only_basis_followup_reuses_last_structure_without_clarification(
    client, patch_fake_runners
):
    session = _bootstrap_session(client, "chat-followup-basis-upgrade")
    headers = {
        "X-QCViz-Session-Id": session["session_id"],
        "X-QCViz-Session-Token": session["session_token"],
    }

    first = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "benzene HOMO 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["basis"] == "def2-SVP"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "basis\ub9cc \ub354 \ud0a4\uc6cc\ubd10", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] == "modify_parameters"
    assert second_data["result"]["structure_query"].lower() == "benzene"
    assert second_data["result"]["basis"] == "def2-tzvp"


def test_chat_rest_parameter_only_method_followup_reuses_last_structure_without_clarification(
    client, patch_fake_runners
):
    session = _bootstrap_session(client, "chat-followup-method-upgrade")
    headers = {
        "X-QCViz-Session-Id": session["session_id"],
        "X-QCViz-Session-Token": session["session_token"],
    }

    first = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "benzene HOMO 보여줘", "method": "HF", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ok"] is True
    assert first_data["result"]["method"].upper() == "HF"

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "method\ub97c B3LYP\ub85c \ubc14\uafd4", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["plan"]["follow_up_mode"] == "modify_parameters"
    assert second_data["result"]["structure_query"].lower() == "benzene"
    assert second_data["result"]["method"].upper() == "B3LYP"


def test_chat_rest_explicit_structure_optimize_geometry_runs_directly_without_continuation_clarification(
    client, patch_fake_runners
):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "water optimize geometry"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["job_type"] == "geometry_optimization"
    assert data["result"]["structure_query"].lower() == "water"


def test_chat_rest_typo_like_aminobutylic_name_autocorrects_before_compute(
    client, patch_fake_runners, monkeypatch
):
    from qcviz_mcp.services.structure_resolver import StructureResolver

    async def _realish_resolve_structure_async(query: str):
        resolved = await StructureResolver().resolve(query)
        return {
            "xyz": resolved.xyz,
            "smiles": resolved.smiles,
            "cid": resolved.cid,
            "name": resolved.name,
            "source": resolved.source,
            "sdf": resolved.sdf,
            "molecular_weight": resolved.molecular_weight,
            "query_plan": resolved.query_plan,
        }

    monkeypatch.setattr(compute_route, "_resolve_structure_async", _realish_resolve_structure_async)
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "Aminobutylic acid HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["result"]["structure_query"].lower() == "gamma-aminobutyric acid"
    assert data["result"]["visualization"]["available"]["orbital"] is True


def test_molchat_interpret_candidates_prefers_local_mea_alias_over_remote_guess(monkeypatch):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "direct_name",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "mearnsetin",
                        "cid": 10359384,
                        "molecular_formula": "C16H12O8",
                        "confidence": 0.91,
                        "source": "autocomplete",
                        "rationale": "remote autocomplete guess",
                    }
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    candidates = asyncio.run(chat_route._molchat_interpret_candidates("MEA 알아?"))
    assert candidates
    assert candidates[0]["name"] == "Ethanolamine"
    assert candidates[0]["cid"] == 700
    assert candidates[0]["source"] == "local_alias_override"


def test_molchat_interpret_candidates_reranks_tnt_candidate_ahead_of_unrelated_remote_match(monkeypatch):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "Eprinomectin component B1a",
                        "cid": 6444397,
                        "molecular_formula": "C50H75NO14",
                        "confidence": 0.96,
                        "source": "autocomplete",
                        "rationale": "remote ordering glitch",
                    },
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.82,
                        "source": "autocomplete",
                        "rationale": "resolved TNT main component",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    candidates = asyncio.run(chat_route._molchat_interpret_candidates("main component of TNT HOMO 보여줘"))
    assert candidates
    assert candidates[0]["name"] == "2,4,6-TRINITROTOLUENE"
    assert candidates[1]["name"] == "Eprinomectin component B1a"


def test_compact_ws_result_keeps_selected_cube_but_strips_heavy_duplicate_payloads():
    result = {
        "job_type": "orbital_preview",
        "structure_query": "benzene",
        "selected_orbital": {"label": "HOMO", "index": 21},
        "orbitals": [{"label": "HOMO", "index": 21}],
        "orbital_cube_b64": "top-level-orbital",
        "density_cube_b64": "top-level-density",
        "esp_cube_b64": "top-level-esp",
        "orbital_cubes": {"21": "huge-cube-list-entry"},
        "events": [{"kind": "debug"}],
        "visualization": {
            "available": {"orbital": True, "density": True, "esp": True},
            "xyz_block": "3\nbenzene\n...",
            "orbital": {"cube_b64": "orbital-cube", "label": "HOMO"},
            "density": {"cube_b64": "density-cube", "label": "density"},
            "esp": {"cube_b64": "esp-cube", "label": "esp"},
        },
    }
    compact = chat_route._compact_result_for_ws(result)
    assert compact["ws_payload_compacted"] is True
    assert "orbital_cubes" not in compact
    assert "orbital_cube_b64" not in compact
    assert "density_cube_b64" not in compact
    assert "esp_cube_b64" not in compact
    assert "events" not in compact
    assert compact["visualization"]["orbital"]["cube_b64"] == "orbital-cube"
    assert compact["visualization"]["esp"]["cube_b64"] == "esp-cube"
    assert "cube_b64" not in compact["visualization"].get("density", {})
    assert compact["visualization"]["available"]["density"] is False


def test_chat_rest_semantic_descriptor_never_falls_back_to_generic_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["clarification_kind"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values[0] == "2,4,6-TRINITROTOLUENE"
    assert "water" not in option_values


def test_chat_rest_semantic_descriptor_discards_generic_llm_fallback_even_when_agent_returns_default_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    class _DummyAgent:
        def __init__(self):
            self.calls = []

        def suggest_molecules(self, description: str):
            self.calls.append(description)
            return [
                {"name": "water", "formula": "H2O", "atoms": 3, "description": "water"},
                {"name": "methane", "formula": "CH4", "atoms": 5, "description": "methane"},
                {"name": "ethanol", "formula": "C2H6O", "atoms": 9, "description": "ethanol"},
            ]

    dummy_agent = _DummyAgent()
    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: dummy_agent, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["clarification_kind"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values[0] == "2,4,6-TRINITROTOLUENE"
    assert "water" not in option_values
    assert dummy_agent.calls == []


def test_molchat_interpret_candidates_reranks_tnt_candidate_ahead_of_unrelated_remote_match(monkeypatch):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "Eprinomectin component B1a",
                        "cid": 6444397,
                        "molecular_formula": "C50H75NO14",
                        "confidence": 0.96,
                        "source": "autocomplete",
                        "rationale": "remote ordering glitch",
                    },
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.82,
                        "source": "autocomplete",
                        "rationale": "resolved TNT main component",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    candidates = asyncio.run(chat_route._molchat_interpret_candidates("main component of TNT HOMO 보여줘"))
    assert candidates
    assert candidates[0]["name"] == "2,4,6-TRINITROTOLUENE"
    assert all(item["name"] != "Eprinomectin component B1a" for item in candidates[:1])


def test_chat_rest_semantic_descriptor_never_falls_back_to_generic_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert "2,4,6-TRINITROTOLUENE" in data["message"]
    assert "water" not in data["message"].lower()


def test_chat_rest_tnt_clarification_defaults_to_trinitrotoluene_when_remote_order_is_wrong(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "autocomplete",
                "candidates": [
                    {
                        "name": "Eprinomectin component B1a",
                        "cid": 6444397,
                        "molecular_formula": "C50H75NO14",
                        "confidence": 0.96,
                        "source": "autocomplete",
                        "rationale": "remote ordering glitch",
                    },
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.82,
                        "source": "autocomplete",
                        "rationale": "resolved TNT main component",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    first = client.post("/api/chat", json={"message": "main component of TNT HOMO 보여줘"})
    assert first.status_code == 200
    data = first.json()
    assert data["ok"] is False
    assert data["requires_clarification"] is True
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert option_values[0] == "2,4,6-TRINITROTOLUENE"
    assert "Eprinomectin component B1a" not in option_values


def test_chat_rest_semantic_descriptor_discards_generic_llm_fallback_even_when_agent_returns_default_examples(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {"query": query, "query_mode": "semantic_descriptor", "candidates": [], "notes": []}

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    class _DummyAgent:
        def __init__(self):
            self.calls = []

        def suggest_molecules(self, description: str):
            self.calls.append(description)
            return [
                {"name": "water", "formula": "H2O", "atoms": 3, "description": "water"},
                {"name": "methane", "formula": "CH4", "atoms": 5, "description": "methane"},
            ]

    dummy_agent = _DummyAgent()
    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: dummy_agent, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert "2,4,6-TRINITROTOLUENE" in data["message"]
    assert "water" not in data["message"].lower()
    assert dummy_agent.calls == []


def test_chat_rest_glycine_optimize_geometry_runs_as_direct_compute(client, patch_fake_runners):
    resp = client.post("/api/chat?wait_for_result=true", json={"message": "glycine optimize geometry"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["job_type"] == "geometry_optimization"
    assert data["plan"].get("follow_up_mode") in (None, "")
    assert data["result"]["structure_query"].lower() == "glycine"
    assert data["result"]["job_type"] == "geometry_optimization"


def test_chat_rest_basis_set_question_stays_chat_only(client, patch_fake_runners, monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    resp = client.post("/api/chat", json={"message": "What is a basis set?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert data["plan"]["query_kind"] == "chat_only"
    assert data.get("job") is None


def test_chat_rest_optimize_it_too_reuses_last_structure_without_clarification(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-optimize-it-too")
    headers = {
        "X-QCViz-Session-Id": session["session_id"],
        "X-QCViz-Session-Token": session["session_token"],
    }

    first = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "analyze glycine geometry", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    assert first.json()["ok"] is True

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "Optimize it too", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    data = second.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["follow_up_mode"] == "optimize_same_structure"
    assert data["result"]["structure_query"].lower() == "glycine"
    assert data["result"]["job_type"] == "geometry_optimization"


def test_chat_rest_korean_pbe0_method_followup_reuses_last_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "chat-followup-pbe0")
    headers = {
        "X-QCViz-Session-Id": session["session_id"],
        "X-QCViz-Session-Token": session["session_token"],
    }

    first = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "benzene HOMO 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    assert first.json()["ok"] is True

    second = client.post(
        "/api/chat?wait_for_result=true",
        headers=headers,
        json={"message": "method를 PBE0로 바꿔", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    data = second.json()
    assert data["ok"] is True
    assert "requires_clarification" not in data
    assert data["plan"]["follow_up_mode"] == "modify_parameters"
    assert data["result"]["structure_query"].lower() == "benzene"
    assert (data["result"]["method"] or "").upper() == "PBE0"


def test_chat_rest_semantic_descriptor_uses_molchat_grounded_dropdown_and_not_raw_phrase(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "semantic_llm",
                "candidates": [
                    {
                        "name": "nitrobenzene",
                        "cid": 7416,
                        "molecular_formula": "C6H5NO2",
                        "confidence": 0.81,
                        "source": "semantic_llm",
                    },
                    {
                        "name": "toluene",
                        "cid": 1140,
                        "molecular_formula": "C7H8",
                        "confidence": 0.55,
                        "source": "semantic_llm",
                    },
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)

    message = "TNT에 들어가는 주물질"
    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert "2,4,6-TRINITROTOLUENE" in data["message"]
    assert message not in data["message"]
    assert "water" not in data["message"].lower()
