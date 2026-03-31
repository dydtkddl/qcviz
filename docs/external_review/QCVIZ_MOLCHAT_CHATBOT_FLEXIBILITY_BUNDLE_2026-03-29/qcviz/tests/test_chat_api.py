from __future__ import annotations
import asyncio
import time
import uuid
import pytest
from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route
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
    turn_events = [e for e in events if e["type"] in {"ack", "assistant", "job_submitted", "result"}]
    assert all(e.get("turn_id") == turn_id for e in turn_events)
    result_event = events[-1]
    assert result_event["result"]["job_type"] == "esp_map"
    assert result_event["result"]["visualization"]["available"]["esp"] is True
    assert result_event["session_id"] == session["session_id"]

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
    assert data["ok"] is False
    assert data["clarification_kind"] == "semantic_grounding"
    structure_field = next((f for f in data["clarification"]["fields"] if f.get("id") == "structure_choice"), None)
    assert structure_field is not None
    option_values = [str(opt.get("value", "")).strip() for opt in structure_field.get("options", [])]
    assert "2,4,6-TRINITROTOLUENE" in option_values
    assert "water" not in option_values
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

    first = client.post("/api/chat", json={"message": "main component of TNT"})
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
    assert dummy_agent.calls == ["TNT 에들어가는주물질"]
