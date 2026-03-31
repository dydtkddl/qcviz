from __future__ import annotations

from qcviz_mcp.llm.normalizer import normalize_user_text
from qcviz_mcp.web.routes import chat as chat_route


def test_semantic_chat_outcome_direct_answer_from_single_high_confidence_candidate():
    outcome = chat_route._determine_semantic_chat_outcome(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [
            {
                "name": "Example Molecule",
                "query_mode": "semantic_descriptor",
                "resolution_method": "llm",
                "source": "llm",
                "confidence": 0.91,
            }
        ],
    )
    assert outcome == chat_route.SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER


def test_semantic_chat_outcome_single_candidate_confirm_when_confidence_is_not_yet_decisive():
    outcome = chat_route._determine_semantic_chat_outcome(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [
            {
                "name": "Example Molecule",
                "query_mode": "semantic_descriptor",
                "resolution_method": "llm",
                "source": "llm",
                "confidence": 0.42,
            }
        ],
    )
    assert outcome == chat_route.SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM


def test_semantic_chat_outcome_uses_clarification_for_multiple_candidates():
    outcome = chat_route._determine_semantic_chat_outcome(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [
            {"name": "Candidate A", "query_mode": "semantic_descriptor", "resolution_method": "llm", "source": "llm", "confidence": 0.61},
            {"name": "Candidate B", "query_mode": "semantic_descriptor", "resolution_method": "llm", "source": "llm", "confidence": 0.57},
        ],
    )
    assert outcome == chat_route.SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION


def test_semantic_chat_outcome_uses_custom_only_when_grounding_returns_nothing():
    outcome = chat_route._determine_semantic_chat_outcome(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [],
    )
    assert outcome == chat_route.SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION


def test_policy_unknown_acronym_compute_routes_to_grounding_required():
    normalized = normalize_user_text("MEA HOMO 보여줘")
    assert normalized["query_kind"] == "grounding_required"
    assert normalized["semantic_grounding_needed"] is True
    assert "MEA" in list(normalized.get("unknown_acronyms") or [])


def test_policy_direct_molecule_compute_routes_to_compute_ready():
    normalized = normalize_user_text("benzene HOMO 보여줘")
    assert normalized["query_kind"] == "compute_ready"
    assert normalized["semantic_grounding_needed"] is False
    assert "benzene" in list(normalized.get("canonical_candidates") or normalized.get("candidate_queries") or [])


def test_policy_parameter_only_followup_stays_in_continuation_lane():
    normalized = normalize_user_text("basis만 더 키워봐")
    assert normalized["follow_up_mode"] == "modify_parameters"
    assert normalized["semantic_grounding_needed"] is False
