from __future__ import annotations

import pytest

from tests.semantic_benchmark import (
    GENERIC_FALLBACK_NAMES,
    benchmark_param_id,
    expected_candidate_names,
    install_semantic_case_stub,
    iter_case_variants,
    load_semantic_benchmark,
)

_EXPLANATION_DATASET = load_semantic_benchmark("semantic_explanation_benchmark")
_COMPUTE_DATASET = load_semantic_benchmark("semantic_compute_benchmark")

_EXPLANATION_PARAMS = [
    pytest.param(case, text, id=benchmark_param_id(case, text))
    for case, text in iter_case_variants(_EXPLANATION_DATASET)
]
_COMPUTE_PARAMS = [
    pytest.param(case, text, id=benchmark_param_id(case, text))
    for case, text in iter_case_variants(_COMPUTE_DATASET)
]


def _structure_choice_values(data: dict) -> list[str]:
    clarification = data.get("clarification") or {}
    fields = clarification.get("fields") or []
    structure_field = next((field for field in fields if field.get("id") == "structure_choice"), None)
    assert structure_field is not None
    return [str(opt.get("value", "")).strip() for opt in list(structure_field.get("options") or [])]


def _assert_no_generic_or_raw_phrase(values: list[str], raw_text: str) -> None:
    lowered_values = {value.lower() for value in values}
    assert raw_text.strip() not in values
    assert not lowered_values.intersection(GENERIC_FALLBACK_NAMES)


@pytest.mark.parametrize(("case", "message"), _EXPLANATION_PARAMS)
def test_chat_rest_semantic_explanation_benchmark_contract(
    client, patch_fake_runners, monkeypatch, case, message
):
    install_semantic_case_stub(monkeypatch, case)

    resp = client.post("/api/chat", json={"message": message})
    assert resp.status_code == 200
    data = resp.json()
    expected_outcome = case["expected_outcome"]
    candidate_names = expected_candidate_names(case)

    if expected_outcome == "grounded_direct_answer":
        assert data["ok"] is True
        assert data["chat_only"] is True
        assert data["job"] is None
        assert data["plan"]["intent"] == "chat"
        assert data["plan"]["query_kind"] == "chat_only"
        assert data["plan"]["semantic_grounding_needed"] is True
        assert "requires_clarification" not in data
        assert any(name in data["message"] for name in candidate_names)
        return

    assert data["ok"] is False
    assert data["requires_clarification"] is True
    assert data["clarification_kind"] == "semantic_grounding"
    assert data["plan"]["intent"] == "chat"
    assert data["plan"]["query_kind"] == "chat_only"
    assert data["pending_payload"]["semantic_grounding_needed"] is True

    option_values = _structure_choice_values(data)
    _assert_no_generic_or_raw_phrase(option_values, message)

    if expected_outcome == "grounding_clarification":
        assert all(name in option_values for name in candidate_names)
    elif expected_outcome == "custom_only_clarification":
        assert option_values == ["custom"]
    else:
        raise AssertionError(f"Unexpected explanation outcome: {expected_outcome}")


@pytest.mark.parametrize(("case", "message"), _COMPUTE_PARAMS)
def test_chat_rest_semantic_compute_benchmark_contract(
    client, patch_fake_runners, monkeypatch, case, message
):
    install_semantic_case_stub(monkeypatch, case)

    first = client.post("/api/chat", json={"message": message})
    assert first.status_code == 200
    first_data = first.json()
    expected_outcome = case["expected_outcome"]
    candidate_names = expected_candidate_names(case)

    assert first_data["ok"] is False
    assert first_data["requires_clarification"] is True
    assert first_data["clarification_kind"] == "semantic_grounding"
    assert first_data["plan"]["query_kind"] == "grounding_required"
    assert first_data["plan"]["semantic_grounding_needed"] is True
    assert first_data.get("job") in (None, {})
    assert "result" not in first_data

    option_values = _structure_choice_values(first_data)
    _assert_no_generic_or_raw_phrase(option_values, message)

    if expected_outcome == "grounding_clarification":
        assert all(name in option_values for name in candidate_names)
    elif expected_outcome == "custom_only_clarification":
        assert option_values == ["custom"]
        return
    else:
        raise AssertionError(f"Unexpected compute outcome: {expected_outcome}")

    selected_candidate = str(case.get("selected_candidate") or "").strip()
    if not selected_candidate:
        return

    second = client.post(
        "/api/chat?wait_for_result=true",
        json={
            "type": "clarify_response",
            "session_id": first_data["session_id"],
            "session_token": first_data["session_token"],
            "answers": {"structure_choice": selected_candidate},
        },
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["ok"] is True
    assert "requires_clarification" not in second_data
    assert second_data["result"]["job_type"] == case["expected_job_type"]
    assert second_data["result"]["structure_query"] == case["expected_structure_query"]
    assert second_data["plan"]["structure_query"] == case["expected_structure_query"]
