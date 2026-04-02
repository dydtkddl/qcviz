from __future__ import annotations

import pytest

from qcviz_mcp.llm.execution_guard import ExecutionGuardViolation, execution_guard
from qcviz_mcp.llm.grounding_merge import (
    SEMANTIC_OUTCOME_COMPUTE_READY,
    SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
    SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER,
    SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
    grounding_merge,
)
from qcviz_mcp.llm.lane_lock import LaneLock, LaneLockViolation
from qcviz_mcp.llm.pipeline import (
    PipelineStageError,
    QCVizPromptPipeline,
    action_plan_to_legacy_plan,
    build_action_plan,
    build_grounding_outcome,
    coerce_action_plan,
)
from qcviz_mcp.llm.schemas import GroundingOutcome, IngressRewriteResult


def _heuristic_stub(message: str, context, normalized_hint):
    return {
        "intent": "chat",
        "job_type": "chat",
        "query_kind": normalized_hint.get("query_kind") or "chat_only",
        "planner_lane": normalized_hint.get("query_kind") or "chat_only",
        "semantic_grounding_needed": normalized_hint.get("semantic_grounding_needed", False),
        "unknown_acronyms": list(normalized_hint.get("unknown_acronyms") or []),
        "normalized_text": normalized_hint.get("normalized_text") or message,
        "chat_response": "heuristic fallback",
        "provider": "heuristic",
    }


class _BaseStubPipeline(QCVizPromptPipeline):
    def __init__(self, **kwargs):
        super().__init__(
            provider="openai",
            openai_api_key="dummy",
            enabled=True,
            force_heuristic=False,
            stage1_enabled=True,
            stage2_enabled=False,
            stage3_enabled=True,
            repair_max=1,
            **kwargs,
        )

    def _has_llm_provider(self) -> bool:
        return True


class _Stage1FailurePipeline(_BaseStubPipeline):
    def _run_ingress_rewrite(self, raw_text, normalized_hint, context):
        raise PipelineStageError("stage1", "preserve_token_lost:MEA")


class _LaneViolationPipeline(_BaseStubPipeline):
    def _run_ingress_rewrite(self, raw_text, normalized_hint, context):
        return IngressRewriteResult(
            original_text=raw_text,
            cleaned_text=normalized_hint.get("normalized_text") or raw_text,
            language_hint="ko",
            preserved_tokens=["MEA"],
            rewrite_confidence=0.91,
        )

    def _run_action_planner(self, raw_text, rewrite, normalized_hint, context, llm_planner):
        return {
            "lane": "compute_ready",
            "confidence": 0.9,
            "reasoning": "incorrectly promoted",
            "molecule_name": None,
            "computation_type": "homo",
        }


class _ValidChatPipeline(_BaseStubPipeline):
    def _run_ingress_rewrite(self, raw_text, normalized_hint, context):
        return IngressRewriteResult(
            original_text=raw_text,
            cleaned_text=normalized_hint.get("normalized_text") or raw_text,
            language_hint="ko",
            preserved_tokens=["MEA"],
            rewrite_confidence=0.91,
        )

    def _run_action_planner(self, raw_text, rewrite, normalized_hint, context, llm_planner):
        return {
            "lane": "chat_only",
            "confidence": 0.91,
            "reasoning": "The input asks what MEA is.",
            "molecule_name": "MEA",
            "computation_type": None,
            "unknown_acronyms": ["MEA"],
            "chat_response": "Ethanolamine is a common interpretation of MEA.",
        }


class _ShadowModePipeline(_ValidChatPipeline):
    def __init__(self, **kwargs):
        super().__init__(shadow_mode=True, serve_llm=False, canary_percent=0, **kwargs)


def test_lane_lock_rejects_lane_flip():
    lock = LaneLock()
    lock.set("chat_only")
    with pytest.raises(LaneLockViolation):
        lock.set("compute_ready")


def test_pipeline_falls_back_immediately_after_stage1_failure():
    pipeline = _Stage1FailurePipeline()
    result = pipeline.execute(
        "MEA?쇰뒗 臾쇱쭏??萸먯빞?",
        {},
        heuristic_planner=_heuristic_stub,
    )
    assert result["provider"] == "heuristic"
    assert result["pipeline_fallback_stage"] == "stage1"
    assert result["chat_response"] == "heuristic fallback"


def test_pipeline_rejects_compute_ready_without_structure_and_falls_back():
    pipeline = _LaneViolationPipeline()
    result = pipeline.execute(
        "MEA?쇰뒗 臾쇱쭏??萸먯빞?",
        {},
        heuristic_planner=_heuristic_stub,
    )
    assert result["provider"] == "heuristic"
    assert result["planner_lane"] == "chat_only"
    assert result["compute_intent"] is False
    assert result["pipeline_fallback_stage"] == "stage2"


def test_pipeline_accepts_valid_chat_lane_and_locks_it():
    pipeline = _ValidChatPipeline()
    result = pipeline.execute(
        "MEA?쇰뒗 臾쇱쭏??萸먯빞?",
        {},
        heuristic_planner=_heuristic_stub,
    )
    assert result["provider"] == "openai"
    assert result["planner_lane"] == "chat_only"
    assert result["lane_locked"] is True
    assert result["locked_lane"] == "chat_only"
    assert result["question_like"] is True
    assert result["explanation_intent"] is True
    assert result["compute_intent"] is False
    assert result["pipeline_fallback_stage"] is None


def test_pipeline_shadow_mode_can_serve_heuristic_primary_without_losing_llm_result():
    pipeline = _ShadowModePipeline()
    result = pipeline.execute(
        "MEA?쇰뒗 臾쇱쭏??萸먯빞?",
        {"session_id": "shadow-session"},
        heuristic_planner=_heuristic_stub,
    )
    assert result["provider"] == "heuristic"
    assert result["planner_lane"] == "chat_only"
    assert result["shadow_primary"] is True
    assert result["shadow_llm_lane"] == "chat_only"


def test_grounding_merge_returns_direct_answer_for_chat_only_single_high_confidence_candidate():
    outcome = grounding_merge(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [{"name": "Ethanolamine", "confidence": 0.93}],
        lane_lock=LaneLock(),
    )
    assert outcome.semantic_outcome == SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER
    assert outcome.supports_direct_answer is True


def test_grounding_merge_returns_custom_only_when_no_candidates_exist():
    outcome = grounding_merge(
        {"query_kind": "grounding_required", "semantic_grounding_needed": True},
        [],
        lane_lock=LaneLock(),
    )
    assert outcome.semantic_outcome == SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION
    assert outcome.allow_compute_submit is False


def test_grounding_merge_can_report_compute_ready_once_structure_is_locked():
    outcome = grounding_merge(
        {"query_kind": "compute_ready", "structure_query": "benzene"},
        [{"name": "benzene", "confidence": 0.99}],
        lane_lock=LaneLock(),
        structure_locked=True,
    )
    assert outcome.semantic_outcome == SEMANTIC_OUTCOME_COMPUTE_READY
    assert outcome.allow_compute_submit is True


def test_grounding_outcome_wrapper_preserves_compatibility_shape():
    outcome = build_grounding_outcome(
        {"query_kind": "chat_only", "semantic_grounding_needed": True},
        [{"name": "Ethanolamine", "confidence": 0.93}],
    )
    assert outcome.outcome == SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER
    assert outcome.selected_candidate == "Ethanolamine"
    assert outcome.candidate_count == 1


def test_execution_guard_returns_clarification_for_single_candidate_confirm():
    outcome = GroundingOutcome(semantic_outcome=SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM)
    decision = execution_guard(outcome, {"structure_query": None})
    assert decision.action == "clarification"


def test_execution_guard_raises_when_compute_ready_has_no_structure():
    outcome = GroundingOutcome(semantic_outcome=SEMANTIC_OUTCOME_COMPUTE_READY)
    with pytest.raises(ExecutionGuardViolation):
        execution_guard(outcome, {})


def test_coerce_action_plan_resolves_follow_up_target_from_context():
    action_plan = coerce_action_plan(
        {
            "intent": "orbital_preview",
            "job_type": "orbital_preview",
            "query_kind": "compute_ready",
            "planner_lane": "compute_ready",
            "follow_up_mode": "add_analysis",
            "orbital": "HOMO",
            "confidence": 0.88,
        },
        raw_text="이번엔 HOMO",
        conversation_state={"last_structure_query": "water", "last_resolved_name": "water"},
        normalized_hint={
            "normalized_text": "이번엔 HOMO",
            "follow_up_mode": "add_analysis",
            "follow_up_requires_context": True,
            "analysis_bundle": ["HOMO"],
            "explicit_compute_action": True,
            "query_kind": "compute_ready",
        },
    )

    assert action_plan.mode == "compute"
    assert action_plan.target.molecule_text == "water"
    assert action_plan.target.from_context is True
    assert action_plan.follow_up.enabled is True
    assert action_plan.parameters.orbital == "HOMO"


def test_build_action_plan_detects_optimize_then_esp_workflow():
    def _workflow_heuristic(message, context, normalized_hint):
        return {
            "intent": "geometry_optimization",
            "job_type": "geometry_optimization",
            "query_kind": "compute_ready",
            "planner_lane": "compute_ready",
            "structure_query": "methanol",
            "confidence": 0.9,
            "provider": "heuristic",
        }

    action_plan = build_action_plan(
        "메탄올 최적화하고 그 결과로 ESP",
        {},
        {},
        heuristic_planner=_workflow_heuristic,
        pipeline=QCVizPromptPipeline(enabled=False),
    )

    assert action_plan.mode == "workflow"
    assert action_plan.workflow.enabled is True
    assert [step.action for step in action_plan.workflow.steps] == [
        "geometry_optimization",
        "esp_map",
    ]
    assert action_plan.workflow.steps[0].target == "methanol"
    assert action_plan.workflow.steps[1].input_from == "s1"


def test_action_plan_to_legacy_plan_keeps_discovery_clarification_compute_shaped():
    action_plan = coerce_action_plan(
        {
            "intent": "orbital_preview",
            "job_type": "orbital_preview",
            "query_kind": "compute_ready",
            "planner_lane": "compute_ready",
            "needs_clarification": True,
            "clarification_kind": "discovery",
            "confidence": 0.41,
        },
        raw_text="HOMO 보여줘",
        normalized_hint={
            "normalized_text": "HOMO 보여줘",
            "analysis_bundle": ["HOMO"],
            "explicit_compute_action": True,
            "query_kind": "compute_ready",
        },
    )
    legacy = action_plan_to_legacy_plan(action_plan, legacy_plan={"job_type": "orbital_preview"})

    assert legacy["query_kind"] == "compute_ready"
    assert legacy["needs_clarification"] is True
    assert legacy["clarification_kind"] == "discovery"
