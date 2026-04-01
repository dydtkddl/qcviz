from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from qcviz_mcp.llm.lane_lock import LaneLock
from qcviz_mcp.llm.routing_config import GROUNDING_AUTO_ACCEPT_THRESHOLD
from qcviz_mcp.llm.schemas import GroundingCandidate, GroundingOutcome, PlanResult


SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER = "grounded_direct_answer"
SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM = "single_candidate_confirm"
SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION = "grounding_clarification"
SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION = "custom_only_clarification"
SEMANTIC_OUTCOME_COMPUTE_READY = "compute_ready"
SEMANTIC_OUTCOME_CHAT_ONLY = "chat_only"


@dataclass(frozen=True)
class GroundingConfig:
    auto_accept_threshold: float = 0.85

    @classmethod
    def from_env(cls) -> "GroundingConfig":
        return cls(auto_accept_threshold=GROUNDING_AUTO_ACCEPT_THRESHOLD)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _plan_lane(plan: Any) -> str:
    if isinstance(plan, PlanResult):
        return plan.lane
    if isinstance(plan, Mapping):
        return _coerce_text(plan.get("planner_lane") or plan.get("query_kind") or plan.get("lane")) or "compute_ready"
    return "compute_ready"


def _plan_flag(plan: Any, key: str) -> bool:
    if isinstance(plan, PlanResult):
        if key == "is_follow_up":
            return bool(plan.is_follow_up)
        return False
    if isinstance(plan, Mapping):
        value = plan.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _plan_molecule_name(plan: Any) -> Optional[str]:
    if isinstance(plan, PlanResult):
        return plan.molecule_name or plan.molecule_from_context
    if isinstance(plan, Mapping):
        return _coerce_text(
            plan.get("molecule_name")
            or plan.get("structure_query")
            or plan.get("molecule_from_context")
        ) or None
    return None


def _normalize_candidates(candidates: Iterable[Any]) -> list[GroundingCandidate]:
    out: list[GroundingCandidate] = []
    for candidate in candidates:
        try:
            out.append(GroundingCandidate.model_validate(candidate))
        except Exception:
            continue
    return out


def _synthetic_candidate(name: Optional[str], source: str = "plan") -> Optional[GroundingCandidate]:
    token = _coerce_text(name)
    if not token:
        return None
    return GroundingCandidate(name=token, source=source, confidence=1.0 if source == "context" else 0.7)


def _supports_direct_answer(candidate: Optional[GroundingCandidate], config: GroundingConfig) -> bool:
    if candidate is None:
        return False
    query_mode = _coerce_text(candidate.query_mode).lower()
    resolution_method = _coerce_text(candidate.resolution_method).lower()
    source = _coerce_text(candidate.source).lower()
    if query_mode == "direct_name":
        return True
    if candidate.confidence >= config.auto_accept_threshold:
        return True
    if resolution_method in {"autocomplete", "alias", "translation"} and source != "molchat_search_fallback":
        return True
    return False


def grounding_merge(
    plan: Any,
    molchat_candidates: Iterable[Any],
    *,
    lane_lock: Optional[LaneLock] = None,
    structure_locked: bool = False,
    config: Optional[GroundingConfig] = None,
) -> GroundingOutcome:
    config = config or GroundingConfig.from_env()
    lane_lock = lane_lock or LaneLock()
    lane = _plan_lane(plan)
    lane_lock.set(lane)

    candidates = _normalize_candidates(molchat_candidates)
    primary = candidates[0] if candidates else None
    semantic_grounding_needed = _plan_flag(plan, "semantic_grounding_needed")
    explicit_compute_action = _plan_flag(plan, "explicit_compute_action") or lane == "compute_ready"
    is_follow_up = _plan_flag(plan, "is_follow_up")
    structure_name = _plan_molecule_name(plan)
    synthetic = _synthetic_candidate(structure_name, source="context" if is_follow_up else "plan")

    if lane == "chat_only":
        if not semantic_grounding_needed:
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_CHAT_ONLY,
                resolved_structure=synthetic,
                candidates=[synthetic] if synthetic else [],
            )
        if not candidates:
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
                clarification_message="No grounded candidates available for the explanation query.",
            )
        if len(candidates) == 1 and _supports_direct_answer(primary, config):
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER,
                resolved_structure=primary,
                candidates=candidates,
            )
        if len(candidates) == 1:
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
                candidates=candidates,
            )
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION,
            candidates=candidates,
        )

    if lane == "grounding_required":
        if not candidates:
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
                clarification_message="Grounding did not return any candidates.",
            )
        if len(candidates) == 1:
            if not explicit_compute_action and _supports_direct_answer(primary, config):
                return GroundingOutcome(
                    semantic_outcome=SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER,
                    resolved_structure=primary,
                    candidates=candidates,
                )
            return GroundingOutcome(
                semantic_outcome=SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
                candidates=candidates,
            )
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION,
            candidates=candidates,
        )

    if structure_locked and synthetic is not None:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_COMPUTE_READY,
            resolved_structure=primary or synthetic,
            candidates=candidates or [synthetic],
        )

    if is_follow_up and synthetic is not None:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_COMPUTE_READY,
            resolved_structure=synthetic,
            candidates=candidates or [synthetic],
        )

    if primary is not None and primary.confidence >= config.auto_accept_threshold:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_COMPUTE_READY,
            resolved_structure=primary,
            candidates=candidates,
        )

    if synthetic is not None and not semantic_grounding_needed:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_COMPUTE_READY,
            resolved_structure=synthetic,
            candidates=candidates or [synthetic],
        )

    if not candidates:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
            clarification_message="A structure must be selected or resolved before compute submission.",
        )

    if len(candidates) == 1:
        return GroundingOutcome(
            semantic_outcome=SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
            candidates=candidates,
        )

    return GroundingOutcome(
        semantic_outcome=SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION,
        candidates=candidates,
    )
