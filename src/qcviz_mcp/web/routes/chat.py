"""Chat routes — HTTP POST + WebSocket with Gemini agent integration.

# FIX(M3): Gemini agent 연동, keepalive (25s ping, 60s timeout), cleanup
"""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import logging
import os
import time
from threading import Lock
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from qcviz_mcp.llm.grounding_merge import (
    SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
    SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER,
    SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION,
    SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
    grounding_merge,
)
from qcviz_mcp.llm.lane_lock import LaneLock
from qcviz_mcp.llm.normalizer import (
    _looks_like_locant_structure_name,
    analyze_semantic_structure_query,
    analyze_structure_input,
    build_structure_hypotheses,
    detect_task_hint,
    extract_structure_candidate,
    is_condensed_structural_formula,
    normalize_user_text,
    _structure_text_signature,
)
from qcviz_mcp.llm.schemas import ClarificationField, ClarificationForm, ClarificationOption, SlotMergeResult
from qcviz_mcp.web.auth_store import get_auth_user
from qcviz_mcp.web.conversation_state import load_conversation_state, update_conversation_state
from qcviz_mcp.web.runtime_info import runtime_debug_info, runtime_fingerprint
from qcviz_mcp.web.session_auth import bootstrap_or_validate_session, validate_session_token

from qcviz_mcp.web.routes.compute import (
    TERMINAL_FAILURE,
    TERMINAL_STATES,
    _extract_message,
    _extract_auth_token,
    _get_resolver,
    _extract_session_id,
    _extract_session_token,
    _web_metrics_summary,
    _merge_plan_into_payload,
    _prepare_payload,
    _public_plan_dict,
    _safe_plan_message,
    _submit_or_reuse_job,
    get_job_manager,
)

# FIX(M3): ko_aliases for follow-up structure detection
try:
    from qcviz_mcp.services.ko_aliases import translate as ko_translate, find_molecule_name
except ImportError:
    def ko_translate(t: str) -> str: return t  # type: ignore
    def find_molecule_name(t: str) -> Optional[str]: return None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter()

WS_POLL_SECONDS = float(os.getenv("QCVIZ_WS_POLL_SECONDS", "0.25"))
# FIX(M3): keepalive settings
WS_PING_INTERVAL = float(os.getenv("QCVIZ_WS_PING_INTERVAL", "25"))
WS_TIMEOUT = float(os.getenv("QCVIZ_WS_TIMEOUT", "60"))
_CLARIFICATION_SESSION_LOCK = Lock()
_CLARIFICATION_SESSIONS: Dict[str, Dict[str, Any]] = {}
_GENERIC_AGENT_SUGGESTION_NAMES = {"water", "methane", "ethanol", "methanol", "benzene"}
_STRUCTURE_SUGGESTION_CATALOG: List[Dict[str, Any]] = [
    {"name": "methylamine", "formula": "CH5N", "atoms": 7, "description": "메틸아민 — simplest primary amine"},
    {"name": "ethylamine", "formula": "C2H7N", "atoms": 10, "description": "에틸아민 — small alkyl amine"},
    {"name": "dimethylamine", "formula": "C2H7N", "atoms": 10, "description": "디메틸아민 — secondary amine"},
    {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "벤젠 — aromatic reference"},
    {"name": "toluene", "formula": "C7H8", "atoms": 15, "description": "톨루엔 — methyl-substituted benzene"},
    {"name": "phenol", "formula": "C6H6O", "atoms": 13, "description": "페놀 — aromatic OH system"},
    {"name": "aniline", "formula": "C6H7N", "atoms": 14, "description": "아닐린 — aromatic amine"},
    {"name": "biphenyl", "formula": "C12H10", "atoms": 22, "description": "비페닐 — two phenyl rings"},
    {"name": "naphthalene", "formula": "C10H8", "atoms": 18, "description": "나프탈렌 — fused aromatic rings"},
    {"name": "styrene", "formula": "C8H8", "atoms": 16, "description": "스타이렌 — vinyl-substituted benzene"},
    {"name": "pyridine", "formula": "C5H5N", "atoms": 11, "description": "피리딘 — aromatic N heterocycle"},
    {"name": "fluorobenzene", "formula": "C6H5F", "atoms": 12, "description": "플루오로벤젠 — halogenated aromatic"},
    {"name": "benzoic acid", "formula": "C7H6O2", "atoms": 15, "description": "벤조산 — aromatic carboxylic acid"},
]
_LOCAL_SEMANTIC_ALIAS_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "MEA": {
        "name": "Ethanolamine",
        "formula": "C2H7NO",
        "cid": 700,
        "confidence": 0.99,
        "rationale": "resolved from local alias preference for monoethanolamine",
        "description": "Local alias preference / CID 700 / common shorthand for monoethanolamine",
    },
    "TNT": {
        "name": "2,4,6-TRINITROTOLUENE",
        "formula": "C7H5N3O6",
        "cid": 8376,
        "confidence": 0.99,
        "rationale": "resolved from local alias preference for TNT",
        "description": "Local alias preference / CID 8376 / common shorthand for 2,4,6-trinitrotoluene",
    },
}
_HEAVY_WS_RESULT_FIELDS = {
    "events",
    "orbital_cubes",
    "orbital_cube_b64",
    "density_cube_b64",
    "esp_cube_b64",
}


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _local_semantic_alias_candidates(query: str) -> List[Dict[str, Any]]:
    cleaned = _safe_str(query)
    if not cleaned:
        return []
    candidates: List[Dict[str, Any]] = []
    for alias, payload in _LOCAL_SEMANTIC_ALIAS_OVERRIDES.items():
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", cleaned, re.IGNORECASE):
            continue
        candidate = dict(payload)
        candidate.setdefault("source", "local_alias_override")
        candidate.setdefault("query_mode", "local_alias")
        candidate.setdefault("resolution_method", "local_alias_override")
        candidate.setdefault(
            "label",
            _pretty_candidate_name(_safe_str(candidate.get("name"))) + (
                f" · CID {candidate.get('cid')}" if candidate.get("cid") else ""
            ),
        )
        candidates.append(candidate)
    return candidates


def _semantic_candidate_relevance_rank(query: str, candidate: Mapping[str, Any]) -> tuple[int, int, float, str]:
    cleaned = _safe_str(query)
    name = _safe_str(candidate.get("name"))
    label = _safe_str(candidate.get("label"))
    description = _safe_str(candidate.get("description"))
    formula = _safe_str(candidate.get("formula") or candidate.get("molecular_formula"))
    cid = candidate.get("cid")
    confidence = _semantic_candidate_confidence(candidate) or 0.0

    haystack = " ".join(part for part in (name, label, description, formula) if part).lower()
    score = 0
    exact_bonus = 0

    if re.search(r"(?<![A-Za-z0-9])TNT(?![A-Za-z0-9])", cleaned, re.IGNORECASE):
        if "trinitrotoluene" in haystack or "2,4,6-trinitrotoluene" in haystack or cid == 8376:
            score += 100
            exact_bonus = 1
        elif "toluene" in haystack:
            score += 10
        elif "nitric acid" in haystack:
            score += 5
        else:
            score -= 25

    return (-score, -exact_bonus, -confidence, name.lower())


def _rerank_semantic_candidates(query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(candidates) <= 1:
        return list(candidates)
    return sorted(list(candidates), key=lambda item: _semantic_candidate_relevance_rank(query, item))


def _compact_result_for_ws(result: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw = dict(result or {})
    if not raw:
        return {}

    compact: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _HEAVY_WS_RESULT_FIELDS:
            continue
        compact[key] = value

    viz = dict(raw.get("visualization") or {})
    available = dict(viz.get("available") or {})
    viz_out: Dict[str, Any] = {}

    for key in ("xyz", "xyz_block", "molecule_xyz", "source", "surface_mode"):
        if key in viz and viz.get(key) not in (None, ""):
            viz_out[key] = viz.get(key)

    orbital = dict(viz.get("orbital") or {})
    if orbital:
        orbital_out = {k: v for k, v in orbital.items() if k != "cube_b64"}
        if orbital.get("cube_b64"):
            orbital_out["cube_b64"] = orbital.get("cube_b64")
        viz_out["orbital"] = orbital_out

    esp = dict(viz.get("esp") or {})
    if esp:
        esp_out = {k: v for k, v in esp.items() if k != "cube_b64"}
        if esp.get("cube_b64"):
            esp_out["cube_b64"] = esp.get("cube_b64")
        viz_out["esp"] = esp_out

    density = dict(viz.get("density") or {})
    if density:
        density_out = {k: v for k, v in density.items() if k != "cube_b64"}
        if density_out:
            viz_out["density"] = density_out
        if "density" in available:
            available["density"] = False

    if available:
        viz_out["available"] = available
    if viz_out:
        compact["visualization"] = viz_out

    compact["ws_payload_compacted"] = True
    return compact


def _resolve_session_auth(
    payload: Optional[Mapping[str, Any]] = None,
    *,
    header_session_id: Optional[str] = None,
    header_session_token: Optional[str] = None,
    allow_new: bool = True,
) -> Dict[str, Any]:
    body = dict(payload or {})
    requested_session_id = _safe_str(body.get("session_id")) or _safe_str(header_session_id) or _extract_session_id(body)
    requested_session_token = (
        _safe_str(body.get("session_token"))
        or _safe_str(header_session_token)
        or _extract_session_token(body)
    )
    return bootstrap_or_validate_session(
        requested_session_id or None,
        requested_session_token or None,
        allow_new=allow_new,
    )


def _resolve_auth_user(
    payload: Optional[Mapping[str, Any]] = None,
    *,
    header_auth_token: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    token = _safe_str(auth_token) or _safe_str(header_auth_token) or _extract_auth_token(dict(payload or {}))
    if not token:
        return None
    user = get_auth_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid auth token.")
    return user


def _parse_client_message(text: str) -> Dict[str, Any]:
    raw = _safe_str(text)
    if not raw:
        return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"message": raw}


def _plan_status_message(plan: Optional[Mapping[str, Any]], payload: Optional[Mapping[str, Any]] = None) -> str:
    plan = dict(plan or {})
    payload = dict(payload or {})
    job_type = _safe_str(payload.get("job_type") or plan.get("job_type") or "analyze")
    planner_structure = _safe_str(plan.get("structure_query"))
    final_structure = _safe_str(payload.get("structure_query") or planner_structure)
    raw_structure = _safe_str(payload.get("structure_query_raw") or plan.get("structure_query_raw"))
    resolved_structure = _safe_str(payload.get("resolved_structure_name") or final_structure)
    method = _safe_str(payload.get("method") or plan.get("method"))
    basis = _safe_str(payload.get("basis") or plan.get("basis"))
    orbital = _safe_str(payload.get("orbital") or plan.get("orbital"))
    esp_preset = _safe_str(payload.get("esp_preset") or plan.get("esp_preset"))
    confidence = plan.get("confidence")
    provider = plan.get("provider", "")

    parts = [f"Plan: {job_type}"]
    if final_structure:
        parts.append(f"structure={final_structure}")
    if raw_structure and resolved_structure and raw_structure.lower() != resolved_structure.lower():
        parts.append(f"input={raw_structure}")
        parts.append(f"resolved={resolved_structure}")
    if planner_structure and final_structure and planner_structure.lower() != final_structure.lower():
        parts.append(f"planner_structure={planner_structure}")
    if method:
        parts.append(f"method={method}")
    if basis:
        parts.append(f"basis={basis}")
    if orbital and job_type in {"orbital_preview", "analyze"}:
        parts.append(f"orbital={orbital}")
    if esp_preset and job_type in {"esp_map", "analyze"}:
        parts.append(f"esp_preset={esp_preset}")
    if confidence is not None:
        try:
            parts.append(f"confidence={float(confidence):.2f}")
        except Exception:
            parts.append(f"confidence={confidence}")
    if provider:
        parts.append(f"via={provider}")
    return " | ".join(parts)


def _result_summary(result: Optional[Mapping[str, Any]]) -> str:
    if not result:
        return "Job completed."
    explanation = result.get("explanation") or {}
    if isinstance(explanation, Mapping):
        expl_summary = _safe_str(explanation.get("summary"))
        if expl_summary:
            return expl_summary
    human_summary = _safe_str(result.get("human_summary"))
    if human_summary:
        return human_summary
    structure = _safe_str(result.get("structure_name") or result.get("structure_query") or "molecule")
    job_type = _safe_str(result.get("job_type") or "calculation")
    energy = result.get("total_energy_hartree")
    gap = result.get("orbital_gap_ev")
    parts = [f"{job_type} completed for {structure}"]
    if energy is not None:
        try:
            parts.append(f"E={float(energy):.8f} Ha")
        except Exception:
            pass
    if gap is not None:
        try:
            parts.append(f"gap={float(gap):.3f} eV")
        except Exception:
            pass
    return " | ".join(parts)


def _plan_is_chat_only(plan: Optional[Mapping[str, Any]]) -> bool:
    if not plan:
        return False
    intent = _safe_str(plan.get("intent")).lower()
    query_kind = _safe_str(plan.get("query_kind")).lower()
    explanation_intent = bool(plan.get("explanation_intent"))
    compute_intent = bool(plan.get("compute_intent"))
    if intent == "chat" or query_kind == "chat_only":
        return True
    if explanation_intent and not compute_intent:
        return True
    return False


def _resolve_chat_response(plan: Optional[Mapping[str, Any]], message: str, *, history: Optional[List[Dict[str, str]]] = None) -> str:
    chat_response = _safe_str((plan or {}).get("chat_response"))
    if chat_response:
        return chat_response

    from qcviz_mcp.web.routes.compute import get_qcviz_agent

    agent = get_qcviz_agent()
    if agent and hasattr(agent, "chat_direct"):
        try:
            direct = _safe_str(agent.chat_direct(message or "", context=history))
            if direct:
                return direct
        except Exception:
            logger.exception("Direct chat fallback failed for %r", message)

    acronyms = [str(item).strip() for item in list((plan or {}).get("unknown_acronyms") or []) if str(item).strip()]
    if acronyms:
        token = acronyms[0]
        return (
            f"`{token}` looks like an abbreviation, and chemistry abbreviations can be ambiguous.\n\n"
            f"- If you want a calculation, tell me the full compound name or SMILES.\n"
            f"- If you want an explanation, tell me which compound you mean."
        )
    return "This looks more like a chemistry question than an explicit calculation request."


def _format_grounded_candidate(candidate: Mapping[str, Any]) -> str:
    name = _safe_str(candidate.get("name")) or "unknown candidate"
    formula = _safe_str(candidate.get("formula"))
    cid = candidate.get("cid")
    parts = [name]
    if formula:
        parts.append(formula)
    if cid:
        parts.append(f"CID {cid}")
    return " / ".join(parts)


def _semantic_candidate_confidence(candidate: Mapping[str, Any]) -> Optional[float]:
    value = candidate.get("confidence")
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _semantic_candidate_supports_direct_answer(candidate: Mapping[str, Any]) -> bool:
    query_mode = _safe_str(candidate.get("query_mode")).lower()
    resolution_method = _safe_str(candidate.get("resolution_method")).lower()
    source = _safe_str(candidate.get("source")).lower()
    confidence = _semantic_candidate_confidence(candidate)
    if query_mode == "direct_name":
        return True
    if confidence is not None and confidence >= 0.85:
        return True
    if resolution_method in {"autocomplete", "alias", "translation"} and source != "molchat_search_fallback":
        return True
    return False


def _determine_semantic_chat_outcome(
    plan: Optional[Mapping[str, Any]],
    candidates: List[Mapping[str, Any]],
) -> str:
    outcome = _determine_semantic_grounding_outcome(plan, candidates)
    return outcome.semantic_outcome


def _determine_semantic_grounding_outcome(
    plan: Optional[Mapping[str, Any]],
    candidates: List[Mapping[str, Any]],
):
    lane_lock = LaneLock()
    return grounding_merge(plan or {}, candidates, lane_lock=lane_lock, structure_locked=False)


def _build_semantic_unresolved_chat_response(
    message: str,
    plan: Optional[Mapping[str, Any]],
) -> str:
    acronyms = [str(item).strip() for item in list((plan or {}).get("unknown_acronyms") or []) if str(item).strip()]
    if acronyms:
        token = acronyms[0]
        return (
            f"`{token}`는 화학에서 여러 물질을 가리킬 수 있는 약어입니다.\n\n"
            f"- 설명을 원하시면 어떤 물질을 뜻하는지 전체 이름을 알려주세요.\n"
            f"- 계산을 원하시면 분자 이름이나 SMILES를 함께 적어 주세요."
        )
    if _safe_str((plan or {}).get("query_kind")).lower() == "grounding_required":
        return (
            "입력하신 표현만으로는 계산에 바로 들어갈 만큼 분자를 확정하기 어렵습니다.\n\n"
            "분자 이름이나 SMILES를 더 구체적으로 알려 주시면 그 기준으로 이어서 진행하겠습니다."
        )
    return (
        "입력하신 설명만으로는 하나의 분자를 자신 있게 확정하기 어렵습니다.\n\n"
        "조금 더 구체적인 분자 이름이나 SMILES를 알려 주시면 바로 이어서 도와드리겠습니다."
    )


def _build_semantic_clarification_form(
    *,
    candidates: List[Dict[str, Any]],
) -> ClarificationForm:
    options: List[ClarificationOption] = []
    default_value: Optional[str] = None
    for candidate in candidates:
        name = _safe_str(candidate.get("name"))
        if not name:
            continue
        formula = _safe_str(candidate.get("formula"))
        cid = candidate.get("cid")
        label = _pretty_candidate_name(name)
        meta: List[str] = []
        if cid:
            meta.append(f"CID {cid}")
        if formula:
            meta.append(formula)
        if meta:
            label = f"{label} -- {' '.join(meta)}"
        options.append(ClarificationOption(value=name, label=label))
        if default_value is None:
            default_value = name
    options.append(ClarificationOption(value="custom", label="직접 입력 / Custom molecule name or SMILES"))

    if candidates:
        title = "설명 기반 후보를 확인해 주세요 / Confirm candidates from the description"
        message = "입력하신 설명을 바탕으로 MolChat에서 구조화한 후보를 정리했습니다."
    else:
        title = "분자 이름을 조금 더 구체적으로 알려주세요 / Clarify the molecule"
        message = "현재 입력만으로는 하나의 분자를 확정하지 못했습니다. 분자 이름이나 SMILES를 직접 입력해 주세요."

    return ClarificationForm(
        mode="semantic_grounding",
        title=title,
        message=message,
        fields=[
            ClarificationField(
                id="structure_choice",
                type="select",
                label="분자를 선택해 주세요 / Choose a molecule",
                required=True,
                options=options,
                default=default_value or "custom",
                help_text="추천 목록에서 고르거나 custom을 선택해 직접 입력할 수 있습니다.",
            ),
            ClarificationField(
                id="structure_custom",
                type="text",
                label="직접 입력 / Custom molecule name or SMILES",
                placeholder="예: acetone, water, CC(=O)C",
                help_text="custom을 선택한 경우에만 사용됩니다.",
            ),
        ],
    )


def _build_typo_clarification_form(
    *,
    original_query: str,
    typo_candidates: List[str],
) -> ClarificationForm:
    options: List[ClarificationOption] = []
    for candidate in typo_candidates:
        token = _safe_str(candidate)
        if not token:
            continue
        options.append(ClarificationOption(value=token, label=token))

    original_token = _safe_str(original_query)
    if original_token:
        options.append(
            ClarificationOption(
                value=original_token,
                label=f"원래 입력 그대로: {original_token}",
            )
        )
    options.append(ClarificationOption(value="custom", label="직접 입력 / Custom"))

    default_value = _safe_str(typo_candidates[0]) if typo_candidates else original_token
    return ClarificationForm(
        mode="typo_rescue",
        title="분자 이름을 확인해 주세요 / Confirm molecule name",
        message=f"'{original_token or original_query}'와 비슷한 분자를 찾았습니다. 의도한 분자를 선택해 주세요.",
        fields=[
            ClarificationField(
                id="structure_choice",
                type="select",
                label="분자를 선택해 주세요 / Choose a molecule",
                required=True,
                options=options,
                default=default_value or None,
                help_text="오타가 의심되어 가까운 이름의 분자를 추천합니다.",
            ),
            ClarificationField(
                id="structure_custom",
                type="text",
                label="직접 입력 / Custom molecule name or SMILES",
                placeholder="예: methylethylamine, CC(=O)C",
                help_text="custom을 선택한 경우에만 사용됩니다.",
            ),
        ],
    )


def _candidate_binding_key(candidate: Mapping[str, Any]) -> str:
    return _safe_str(candidate.get("name") or candidate.get("structure_query") or candidate.get("label"))


def _build_candidate_bindings_from_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    bindings: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        key = _candidate_binding_key(candidate)
        if not key:
            continue
        bindings[key] = _json_safe(dict(candidate))
    return bindings


def _build_candidate_bindings_from_form(form: Optional[ClarificationForm]) -> Dict[str, Dict[str, Any]]:
    if form is None:
        return {}
    bindings: Dict[str, Dict[str, Any]] = {}
    for field in list(form.fields or []):
        if _safe_str(field.id) != "structure_choice":
            continue
        for option in list(field.options or []):
            value = _safe_str(option.value)
            if not value or value == "custom":
                continue
            bindings[value] = {
                "name": value,
                "label": _safe_str(option.label) or value,
                "source": "clarification_option",
            }
    return bindings


async def _resolve_semantic_chat_mode(
    plan: Optional[Mapping[str, Any]],
    *,
    body: Optional[Mapping[str, Any]],
    raw_message: str,
    session_id: str,
    turn_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not _plan_is_chat_only(plan):
        return None
    if not bool((plan or {}).get("semantic_grounding_needed")):
        return None

    query = _safe_str(raw_message) or _safe_str((plan or {}).get("normalized_text")) or _safe_str((plan or {}).get("structure_query"))
    candidates = await _molchat_interpret_candidates(query)
    outcome = _determine_semantic_grounding_outcome(plan, candidates)
    direct_response = _build_semantic_chat_response(query, plan, candidates, semantic_outcome=outcome.semantic_outcome)
    if direct_response:
        state_update = _build_semantic_chat_continuation_state(candidates)
        if state_update:
            update_conversation_state(
                session_id,
                state_update,
                manager=get_job_manager(),
            )
        return {
            "kind": "chat",
            "message": direct_response,
            "plan": dict(plan or {}),
            "candidates": candidates,
            "semantic_outcome": outcome.semantic_outcome,
        }

    pending = _merge_plan_into_payload(dict(body or {}), plan or {}, raw_message=raw_message)
    pending["clarification_kind"] = "semantic_grounding"
    pending["semantic_grounding_needed"] = True
    form = _build_semantic_clarification_form(candidates=candidates)
    _session_put(
        session_id,
        {
            "pending_payload": pending,
            "plan": dict(plan or {}),
            "raw_message": raw_message,
            "asked_fields": [field.id for field in form.fields],
            "candidate_bindings": _build_candidate_bindings_from_candidates(candidates),
            "turn_id": _safe_str(turn_id),
        },
    )
    return {
        "kind": "clarify",
        "plan": dict(plan or {}),
        "pending": pending,
        "clarification": form,
        "turn_id": _safe_str(turn_id),
        "candidates": candidates,
        "semantic_outcome": outcome.semantic_outcome,
    }


def _build_semantic_chat_continuation_state(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {}
    candidate = candidates[0]
    if not _semantic_candidate_supports_direct_answer(candidate):
        return {}

    name = _safe_str(candidate.get("name"))
    formula = _safe_str(candidate.get("formula") or candidate.get("molecular_formula"))
    if not name:
        return {}

    return {
        "last_structure_query": name,
        "last_resolved_name": name,
        "analysis_history": ["semantic_chat_grounding"],
        "last_resolved_artifact": {
            "structure_query": name,
            "structure_name": name,
            "formula": formula,
        },
    }


def _build_semantic_chat_response(
    message: str,
    plan: Optional[Mapping[str, Any]],
    candidates: List[Dict[str, Any]],
    *,
    semantic_outcome: Optional[str] = None,
) -> Optional[str]:
    cleaned = _safe_str(message)
    outcome = semantic_outcome or _determine_semantic_chat_outcome(plan, candidates)
    if outcome != SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER:
        return None

    acronyms = [str(item).strip() for item in list((plan or {}).get("unknown_acronyms") or []) if str(item).strip()]
    lead_token = acronyms[0] if acronyms else ""
    question_like = bool(re.search(r"알아|뭐야|뭔지|무엇|설명|뜻|의미|what is|what's|tell me about|explain", cleaned, re.IGNORECASE))

    candidate = candidates[0]
    if not _semantic_candidate_supports_direct_answer(candidate):
        return None

    name = _safe_str(candidate.get("name")) or "unknown candidate"
    formula = _safe_str(candidate.get("formula") or candidate.get("molecular_formula"))
    cid = candidate.get("cid")
    rationale = _safe_str(candidate.get("rationale"))
    if lead_token:
        first = f"`{lead_token}`는 보통 **{name}**를 의미합니다."
    elif question_like:
        first = f"입력하신 표현은 보통 **{name}**를 뜻합니다."
    else:
        first = f"가장 가까운 후보는 **{name}**입니다."

    details: List[str] = []
    if formula:
        details.append(f"분자식: {formula}")
    if cid:
        details.append(f"CID: {cid}")
    if rationale:
        details.append(f"근거: {rationale}")

    tail = "원하시면 이 분자를 기준으로 HOMO/LUMO, ESP, 구조 최적화 같은 계산을 바로 이어서 진행할 수 있습니다."
    if details:
        return first + "\n\n- " + "\n- ".join(details) + "\n\n" + tail
    return first + "\n\n" + tail


async def _resolve_chat_response_async(
    plan: Optional[Mapping[str, Any]],
    message: str,
    *,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    if plan and bool(plan.get("semantic_grounding_needed")):
        query = _safe_str(message) or _safe_str(plan.get("normalized_text")) or _safe_str(plan.get("structure_query"))
        try:
            candidates = await _molchat_interpret_candidates(query)
        except Exception:
            logger.exception("Semantic chat grounding failed for %r", query)
            candidates = []
        response = _build_semantic_chat_response(query, plan, candidates)
        if response:
            return response
        return _build_semantic_unresolved_chat_response(query, plan)
    return _resolve_chat_response(plan, message, history=history)


# FIX(M3): Detect follow-up molecule queries
def _detect_follow_up_molecule(message: str) -> Optional[str]:
    """Extract explicit molecule mention from message when present."""
    if not message:
        return None
    normalized = normalize_user_text(message)
    for candidate in list(normalized.get("canonical_candidates") or []):
        token = _safe_str(candidate)
        if (
            token
            and token.lower() not in {"structure", "geometry", "homo", "lumo", "esp"}
            and not detect_task_hint(token)
            and not re.search(r"ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자|궁금|알려줘|뭐야|보여줘|해줘|그려줘", token, re.IGNORECASE)
            and _looks_like_molecule(token)
        ):
            return token
    structure_analysis = analyze_structure_input(message)
    for candidate in list(structure_analysis.get("canonical_candidates") or []):
        token = _safe_str(candidate)
        if (
            token
            and not detect_task_hint(token)
            and not re.search(r"ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자|궁금|알려줘|뭐야|보여줘|해줘|그려줘", token, re.IGNORECASE)
            and _looks_like_molecule(token)
        ):
            return token
    # Try Korean alias lookup as fallback
    mol = find_molecule_name(message)
    if mol:
        return mol
    compact = re.sub(r"\s+", "", _safe_str(message))
    if compact and compact != _safe_str(message):
        compact_mol = find_molecule_name(compact)
        if compact_mol:
            return compact_mol
    # Check for common English molecule names
    common = [
        "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
        "formaldehyde", "caffeine", "aspirin", "glucose", "urea",
        "methylamine", "ethylamine", "dimethylamine", "trimethylamine", "aniline",
    ]
    lower = message.lower()
    for name in common:
        if name in lower:
            return name
    return None


# ─── Clarification Flow helpers ────────────────────────
CONFIDENCE_THRESHOLD = float(os.getenv("QCVIZ_CONFIDENCE_THRESHOLD", "0.75"))
_CLARIFICATION_TTL_SECONDS = int(os.getenv("QCVIZ_CLARIFICATION_TTL_SECONDS", str(30 * 60)))
ALLOWED_FIELD_TYPES = {"text", "textarea", "radio", "select", "number", "checkbox"}
_DISCOVERY_HINT_RE = re.compile(
    r"\b(suggest|recommend|example|examples|candidate|candidates|list)\b|"
    r"추천|예시|후보|대표적인|대표적|뭐가 있어|어떤 분자",
    re.IGNORECASE,
)
_COMPOSITE_HINT_RE = re.compile(
    r"[,;/]|"
    r"\b(and|plus|vs|versus|with)\b|"
    r"와|과|및|랑|하고",
    re.IGNORECASE,
)


def _postvalidate_plan_confidence(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Downshift overconfident compute plans for typo-like structure strings."""
    from qcviz_mcp.services.structure_resolver import (
        CHEM_ABBREVIATIONS,
        _KNOWN_MOLECULE_NAMES,
        _fuzzy_rescue_candidates,
    )

    adjusted = dict(plan or {})
    structure_query = _safe_str(adjusted.get("structure_query"))
    confidence = float(adjusted.get("confidence", 0.0) or 0.0)
    query_kind = _safe_str(adjusted.get("query_kind"))
    if query_kind == "chat_only" or not structure_query:
        return adjusted

    sq_lower = structure_query.lower()
    known_lower = {name.lower() for name in _KNOWN_MOLECULE_NAMES}
    abbrev_lower = {name.lower() for name in CHEM_ABBREVIATIONS.keys()}
    auto_accept_local_aliases = {"aminobutylic acid", "aminobutyric acid"}

    if sq_lower in known_lower or sq_lower in abbrev_lower or sq_lower in auto_accept_local_aliases:
        return adjusted

    fuzzy_candidates = _fuzzy_rescue_candidates(structure_query, cutoff=0.7, n=3)
    if fuzzy_candidates:
        if confidence > CONFIDENCE_THRESHOLD:
            adjusted["confidence"] = 0.65
            adjusted["confidence_band"] = "medium"
            adjusted["needs_clarification"] = True
            adjusted["clarification_kind"] = "typo_suspicion"
            adjusted["typo_candidates"] = fuzzy_candidates
            missing_slots = list(adjusted.get("missing_slots") or [])
            if "structure_query" not in missing_slots:
                missing_slots.append("structure_query")
            adjusted["missing_slots"] = missing_slots
            logger.info(
                "FAM-02: confidence downgraded %.2f -> 0.65 for %r with typo candidates %s",
                confidence,
                structure_query,
                fuzzy_candidates,
            )
        return adjusted

    if confidence > CONFIDENCE_THRESHOLD:
        adjusted["confidence"] = 0.45
        adjusted["confidence_band"] = "low"
        adjusted["needs_clarification"] = True
        adjusted["clarification_kind"] = "unknown_molecule"
        missing_slots = list(adjusted.get("missing_slots") or [])
        if "structure_query" not in missing_slots:
            missing_slots.append("structure_query")
        adjusted["missing_slots"] = missing_slots
        logger.info(
            "FAM-02: confidence downgraded %.2f -> 0.45 for %r with no fuzzy rescue",
            confidence,
            structure_query,
        )
    return adjusted


def _build_validated_plan(raw_message: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    plan = _safe_plan_message(raw_message, payload) if raw_message else {}
    if not plan:
        return {}
    return _postvalidate_plan_confidence(plan)


async def _probe_verified_typo_candidates(
    structure_query: str,
    candidates: List[str],
) -> List[str]:
    query = _safe_str(structure_query)
    candidate_list = _dedupe_strings([_safe_str(item) for item in list(candidates or []) if _safe_str(item)])
    if not query or not candidate_list:
        return []

    resolver = _get_resolver()
    if resolver is None:
        return []

    molchat_hits = set()
    try:
        search_payload = await resolver.molchat.search(query, limit=max(5, len(candidate_list) * 2))
        for row in list((search_payload or {}).get("results") or []):
            name = _safe_str((row or {}).get("name")).lower()
            if not name:
                continue
            molchat_hits.add(name)
            molchat_hits.add(name.replace(" ", ""))
    except Exception as exc:
        logger.info("Typo-candidate MolChat probe failed for %s: %s", query, exc)

    verified: List[str] = []
    for candidate in candidate_list:
        lowered = candidate.lower()
        compact = lowered.replace(" ", "")
        is_verified = lowered in molchat_hits or compact in molchat_hits
        if not is_verified:
            try:
                is_verified = bool(await resolver.pubchem.name_exists(candidate))
            except Exception as exc:
                logger.info("Typo-candidate PubChem probe failed for %s -> %s", candidate, exc)
                is_verified = False
        if is_verified:
            verified.append(candidate)
    return _dedupe_strings(verified)


def _dedupe_strings(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        token = _safe_str(item)
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _session_get(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    now = _now_ts()
    with _CLARIFICATION_SESSION_LOCK:
        expired_keys = [
            sid
            for sid, state in _CLARIFICATION_SESSIONS.items()
            if (now - float(state.get("created_at") or 0.0)) > _CLARIFICATION_TTL_SECONDS
        ]
        for sid in expired_keys:
            _CLARIFICATION_SESSIONS.pop(sid, None)
        saved = _CLARIFICATION_SESSIONS.get(session_id)
        return dict(saved) if saved else None


def _session_put(session_id: str, state: Mapping[str, Any]) -> None:
    if not session_id:
        return
    with _CLARIFICATION_SESSION_LOCK:
        entry = dict(state)
        entry["created_at"] = _now_ts()
        _CLARIFICATION_SESSIONS[session_id] = entry


def _session_pop(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    with _CLARIFICATION_SESSION_LOCK:
        saved = _CLARIFICATION_SESSIONS.pop(session_id, None)
        return dict(saved) if saved else None


def _current_missing_slots(plan: Mapping[str, Any], payload: Mapping[str, Any]) -> List[str]:
    batch_ready = bool(payload.get("batch_request") and list(payload.get("selected_molecules") or []))
    missing = [
        slot
        for slot in list(plan.get("missing_slots") or payload.get("planner_missing_slots") or [])
        if _safe_str(slot) not in {"structure_query", "orbital"}
    ]
    if not batch_ready and not (
        payload.get("structure_query") or payload.get("xyz") or payload.get("atom_spec") or payload.get("structures")
    ):
        missing.append("structure_query")

    job_type = _safe_str(payload.get("job_type") or plan.get("job_type") or plan.get("intent"))
    if job_type == "orbital_preview" and not payload.get("orbital"):
        missing.append("orbital")

    return _dedupe_strings(missing)

def _detect_ambiguity(plan: Dict[str, Any], prepared: Dict[str, Any], raw_message: str) -> List[str]:
    """Return list of ambiguity reasons, or empty if plan is clear."""
    reasons: List[str] = []
    confidence = float(plan.get("confidence", 0.0))
    query = _safe_str(prepared.get("structure_query"))
    batch_ready = bool(prepared.get("batch_request") and list(prepared.get("selected_molecules") or []))
    normalized = normalize_user_text(raw_message or query)
    continuation_context_used = bool(prepared.get("continuation_context_used"))
    condensed_formula = bool(prepared.get("condensed_formula")) or is_condensed_structural_formula(
        _safe_str(prepared.get("structure_query_raw")) or raw_message or query
    )
    missing_slots = _current_missing_slots(plan, prepared)
    composite_structure_ready = bool(
        prepared.get("structures") and prepared.get("composition_kind") in {"ion_pair", "salt"}
    )
    if composite_structure_ready:
        missing_slots = [slot for slot in missing_slots if slot != "structure_query"]

    # Explicitly recognized ion pairs / salts should bypass single-molecule
    # disambiguation. Once we have charged components, the raw composite label
    # may not look like a plain molecule name, but the structure intent is clear.
    if composite_structure_ready or batch_ready:
        if "orbital" in missing_slots:
            reasons.append("missing_orbital")
        return _dedupe_strings(reasons)

    if prepared.get("structure_locked"):
        missing_slots = [slot for slot in missing_slots if slot != "structure_query"]

    # Low confidence
    if confidence < CONFIDENCE_THRESHOLD and not missing_slots:
        reasons.append("low_confidence")

    if (
        query
        and "structure_query" not in missing_slots
        and not prepared.get("structures")
        and not prepared.get("structure_locked")
        and not condensed_formula
        and _looks_like_composite_query(query, raw_message)
    ):
        reasons.append("multiple_molecules")

    # Ion indicators without explicit charge
    if query and not prepared.get("structures") and not condensed_formula and re.search(r'[A-Za-z]\+|[A-Za-z]-', query):
        if prepared.get("charge") is None:
            reasons.append("ion_charge_unclear")

    # No structure detected or structure_query is not a valid molecule name
    if "structure_query" in missing_slots:
        reasons.append("no_structure")
    elif query and (
        not _looks_like_molecule(query)
        or (
            not continuation_context_used
            and not prepared.get("xyz")
            and not prepared.get("atom_spec")
            and
            bool(normalized.get("structure_needs_clarification"))
            and _safe_str(normalized.get("maybe_structure_hint")).lower() != query.lower()
        )
    ):
        reasons.append("no_structure")

    if "orbital" in missing_slots:
        reasons.append("missing_orbital")

    return _dedupe_strings(reasons)


def _looks_like_molecule(query: str) -> bool:
    """Check if the query looks like a valid molecule name (vs Korean task text)."""
    if not query:
        return False
    normalized = normalize_user_text(query)
    if normalized.get("semantic_descriptor"):
        return False
    lowered = query.strip().lower()
    if detect_task_hint(query):
        return False
    if re.search(
        r"\b(homo|lumo|esp|orbital|charge|charges|basis|optimize|optimization|analysis)\b|"
        r"궁금|알려줘|뭐야|보여줘|해줘|그려줘",
        lowered,
        re.IGNORECASE,
    ):
        return False
    # Contains significant Korean text → probably not a molecule name
    korean_chars = sum(1 for c in query if '\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163')
    if korean_chars > len(query) * 0.3:
        return False
    # Formula-like patterns (fullmatch only, prevent partial sentence matches)
    compact = query.strip()
    if re.fullmatch(r"(?:[A-Z][a-z]?\d*){2,}(?:[+\-]\d*|\d*[+\-])?", compact) and (
        re.search(r"\d", compact) or re.search(r"[a-z]", compact)
    ):
        return True
    if _looks_like_locant_structure_name(compact):
        return True
    # Known molecule patterns: single English word or SMILES-like token
    if re.match(r'^[A-Za-z][A-Za-z0-9()\[\]\-+.,\s#=\\/]*$', query.strip()):
        return True
    return False


def _canonical_entry_name(entry: Any) -> str:
    if isinstance(entry, Mapping):
        return _safe_str(entry.get("canonical_name") or entry.get("name") or entry.get("alias") or entry.get("raw_text"))
    return _safe_str(entry)


def _looks_like_composite_query(query: str, raw_message: str = "") -> bool:
    text = _safe_str(query) or _safe_str(raw_message)
    if not text:
        return False
    if re.match(r"^\s*\d+(?:,\d+)+(?:-[A-Za-z]|\s+[A-Za-z])", text):
        return False
    if len(re.findall(r"\b[\w\(\)]+[+\-]\b", text)) >= 2:
        return True
    if re.search(r"\b[\w\(\)]+\s*\+\s*[\w\(\)]+\b", text):
        return True
    if _COMPOSITE_HINT_RE.search(text):
        return True
    return False


def _explicit_structure_attempt(plan: Mapping[str, Any], prepared: Mapping[str, Any], raw_message: str) -> Optional[str]:
    normalized = normalize_user_text(raw_message or "")
    if normalized.get("semantic_descriptor"):
        return None
    normalized_hint = _safe_str(normalized.get("maybe_structure_hint"))
    normalized_candidates = {
        str(item).strip().lower()
        for item in list(normalized.get("candidate_queries") or [])
        if str(item).strip()
    }
    candidates = [
        _safe_str(prepared.get("structure_query")),
        _safe_str(plan.get("structure_query")),
        normalized_hint,
        *[_safe_str(item) for item in list(normalized.get("candidate_queries") or [])[:5]],
        extract_structure_candidate(raw_message) or "",
        _safe_str(raw_message),
    ]
    for candidate in candidates:
        token = _safe_str(candidate)
        if not token or detect_task_hint(token):
            continue
        if re.search(
            r"\b(homo|lumo|esp|orbital|charge|charges|basis|optimize|optimization|analysis)\b|"
            r"궁금|알려줘|뭐야|보여줘|해줘|그려줘|ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자",
            token,
            re.IGNORECASE,
        ):
            continue
        if token and (
            _looks_like_molecule(token)
            or (normalized_hint and token.lower() == normalized_hint.lower())
            or (
                token.lower() in normalized_candidates
                and token.lower() != _safe_str(raw_message).lower()
            )
            ):
            return token
    return None


def _plausible_structure_seed(text: str) -> str:
    cleaned = _safe_str(text)
    if not cleaned:
        return ""
    normalized = normalize_user_text(cleaned)
    if normalized.get("semantic_descriptor"):
        return _safe_str(normalized.get("maybe_structure_hint"))
    hypotheses = build_structure_hypotheses(cleaned)
    candidates = [
        _safe_str(hypotheses.get("primary_candidate")),
        _safe_str(normalized.get("maybe_structure_hint")),
        *[_safe_str(item) for item in list(hypotheses.get("candidate_queries") or [])[:5]],
        *[_safe_str(item) for item in list(normalized.get("candidate_queries") or [])[:5]],
    ]
    for candidate in candidates:
        token = _safe_str(candidate)
        if not token or detect_task_hint(token):
            continue
        if _looks_like_molecule(token):
            return token
    return ""


def _is_semantic_structure_descriptor(text: str) -> bool:
    normalized = normalize_user_text(text or "")
    return bool(normalized.get("semantic_descriptor"))


def _looks_like_generic_agent_suggestion_list(suggestions: List[Dict[str, Any]]) -> bool:
    names = [
        _safe_str(item.get("name")).lower()
        for item in list(suggestions or [])
        if _safe_str(item.get("name"))
    ]
    if not names:
        return False
    return set(names).issubset(_GENERIC_AGENT_SUGGESTION_NAMES)


def _semantic_runtime_log_context() -> Dict[str, Any]:
    return {"runtime_fingerprint": runtime_fingerprint()}


def _pretty_candidate_name(name: str) -> str:
    token = _safe_str(name)
    if not token:
        return ""
    if token.upper() == token and re.search(r"[A-Z]", token):
        return token.title()
    return token


def _agent_semantic_suggestions(agent: Any, description: str, *, allow_generic_fallback: bool) -> List[Dict[str, Any]]:
    if not agent or not hasattr(agent, "suggest_molecules"):
        return []
    try:
        suggestions = list(
            agent.suggest_molecules(
                description,
                allow_generic_fallback=allow_generic_fallback,
            )
            or []
        )
    except TypeError:
        suggestions = list(agent.suggest_molecules(description) or [])
    if not allow_generic_fallback and _looks_like_generic_agent_suggestion_list(suggestions):
        logger.info(
            "Discarded generic semantic fallback suggestions for %r: %s",
            description,
            [item.get("name") for item in suggestions],
            extra=_semantic_runtime_log_context(),
        )
        return []
    return suggestions


async def _molchat_interpret_candidates(query: str) -> List[Dict[str, Any]]:
    cleaned = _safe_str(query)
    if not cleaned:
        return []
    local_alias_candidates = _local_semantic_alias_candidates(cleaned)
    if local_alias_candidates:
        logger.info(
            "Semantic interpretation for %r will prefer local alias candidates: %s",
            cleaned,
            [item.get("name") for item in local_alias_candidates],
            extra=_semantic_runtime_log_context(),
        )
        return local_alias_candidates
    resolver = _get_resolver()
    molchat = getattr(resolver, "molchat", None) if resolver is not None else None
    if molchat is None or not hasattr(molchat, "interpret_candidates"):
        return []

    async def _llm_grounded_semantic_candidates() -> List[Dict[str, Any]]:
        from qcviz_mcp.web.routes.compute import get_qcviz_agent

        agent = get_qcviz_agent()
        try:
            suggested = _agent_semantic_suggestions(
                agent,
                cleaned,
                allow_generic_fallback=False,
            )
        except Exception:
            logger.exception("Local semantic candidate generation failed for %r", cleaned)
            return []

        if not suggested:
            logger.info(
                "No LLM-grounded semantic candidates available for %r",
                cleaned,
                extra=_semantic_runtime_log_context(),
            )
            return []

        grounded: List[Dict[str, Any]] = []
        seen = set()
        for suggestion in suggested[:8]:
            requested_name = _safe_str(suggestion.get("name"))
            if not requested_name:
                continue
            rows: List[Dict[str, Any]] = []
            if hasattr(molchat, "search"):
                try:
                    search_payload = await molchat.search(requested_name, limit=3)
                    rows = list(search_payload.get("results") or [])
                except Exception:
                    logger.exception("Failed to ground LLM semantic candidate %r via MolChat search", requested_name)
                    rows = []
            if not rows:
                continue
            row = rows[0]
            grounded_name = _safe_str(row.get("name")) or requested_name
            key = grounded_name.lower()
            if key in seen:
                continue
            seen.add(key)
            description = _safe_str(suggestion.get("description")) or "LLM-grounded semantic candidate"
            cid = row.get("cid")
            formula = _safe_str(row.get("molecular_formula") or suggestion.get("formula"))
            if cid:
                description = f"{description} / CID {cid}"
            grounded.append(
                {
                    "name": grounded_name,
                    "formula": formula,
                    "atoms": suggestion.get("atoms"),
                    "description": description,
                    "source": "qcviz_llm_grounded",
                }
            )
        return grounded

    try:
        interpreted = await molchat.interpret_candidates(cleaned, limit=5)
    except Exception:
        logger.exception("MolChat semantic interpretation failed for %r", cleaned)
        return await _llm_grounded_semantic_candidates()

    logger.info(
        "MolChat semantic interpretation resolved %r -> mode=%s method=%s candidates=%d",
        cleaned,
        _safe_str(interpreted.get("query_mode")),
        _safe_str(interpreted.get("resolution_method")),
        len(list(interpreted.get("candidates") or [])),
        extra=_semantic_runtime_log_context(),
    )

    out: List[Dict[str, Any]] = []
    seen = set()
    for item in list(interpreted.get("candidates") or []):
        name = _safe_str(item.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        formula = _safe_str(item.get("molecular_formula"))
        cid = item.get("cid")
        confidence = item.get("confidence")
        rationale = _safe_str(item.get("rationale"))
        description_bits: List[str] = []
        if rationale:
            description_bits.append(rationale)
        if cid:
            description_bits.append(f"CID {cid}")
        if confidence is not None:
            try:
                description_bits.append(f"confidence {float(confidence):.2f}")
            except Exception:
                pass
        out.append(
            {
                "name": name,
                "formula": formula,
                "atoms": None,
                "cid": cid,
                "confidence": confidence,
                "rationale": rationale,
                "label": _pretty_candidate_name(name) + (f" — CID {cid}" if cid else ""),
                "description": " / ".join(description_bits) if description_bits else _pretty_candidate_name(name),
                "source": _safe_str(item.get("source") or interpreted.get("resolution_method")),
                "query_mode": _safe_str(interpreted.get("query_mode")),
                "resolution_method": _safe_str(interpreted.get("resolution_method")),
            }
        )
    interpreted_sources = {_safe_str(item.get("source")) for item in out if _safe_str(item.get("source"))}
    if not out or interpreted_sources == {"molchat_search_fallback"}:
        logger.info(
            "Semantic interpretation for %r requires LLM grounding fallback: out=%d sources=%s",
            cleaned,
            len(out),
            sorted(interpreted_sources),
            extra=_semantic_runtime_log_context(),
        )
        llm_grounded = await _llm_grounded_semantic_candidates()
        if llm_grounded:
            merged = _merge_structure_suggestions(llm_grounded, out)
            reranked = _rerank_semantic_candidates(cleaned, merged)
            logger.info(
                "Semantic interpretation for %r reranked merged candidates: %s",
                cleaned,
                [item.get("name") for item in reranked],
                extra=_semantic_runtime_log_context(),
            )
            return reranked
    else:
        logger.info(
            "Semantic interpretation for %r will use grounded MolChat candidates directly: %s",
            cleaned,
            [item.get("name") for item in out],
            extra=_semantic_runtime_log_context(),
        )
    reranked = _rerank_semantic_candidates(cleaned, out)
    if reranked != out:
        logger.info(
            "Semantic interpretation for %r reranked candidates: %s",
            cleaned,
            [item.get("name") for item in reranked],
            extra=_semantic_runtime_log_context(),
        )
    return reranked


def _clarification_mode(plan: Mapping[str, Any], prepared: Mapping[str, Any], raw_message: str, reasons: List[str]) -> str:
    normalized = normalize_user_text(raw_message or _safe_str(prepared.get("structure_query")))
    proposed_mode = _safe_str(prepared.get("clarification_kind")) or _safe_str(plan.get("clarification_kind"))
    analysis_bundle = {
        str(item).upper()
        for item in (normalized.get("analysis_bundle") or plan.get("analysis_bundle") or [])
        if _safe_str(item)
    }
    job_type = _safe_str(prepared.get("job_type") or plan.get("job_type") or plan.get("intent"))
    if "missing_orbital" in reasons and "no_structure" not in reasons:
        return "parameter_completion"
    if "no_structure" in reasons:
        session_id = _safe_str(prepared.get("session_id"))
        has_session_state = bool(session_id and load_conversation_state(session_id, manager=get_job_manager()))
        if (
            _safe_str(prepared.get("query_kind") or plan.get("query_kind")) == "grounding_required"
            or bool(prepared.get("semantic_grounding_needed") or plan.get("semantic_grounding_needed"))
            or normalized.get("semantic_descriptor")
        ):
            return "semantic_grounding"
        orbital_only_without_context = bool(
            job_type == "orbital_preview"
            and analysis_bundle
            and analysis_bundle.issubset({"HOMO", "LUMO"})
            and not has_session_state
            and not prepared.get("continuation_context_used")
            and not _explicit_structure_attempt(plan, prepared, raw_message)
        )
        if orbital_only_without_context:
            return "discovery"
        if proposed_mode:
            return proposed_mode
        follow_up_signal = _safe_str(prepared.get("follow_up_mode") or plan.get("follow_up_mode"))
        if not follow_up_signal and normalized.get("follow_up_requires_context"):
            follow_up_signal = "add_analysis"
        if follow_up_signal:
            return "continuation_targeting"
        if _explicit_structure_attempt(plan, prepared, raw_message):
            return "disambiguation"
        return "discovery"
    return "clarification"


def _merge_structure_suggestions(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for group in groups:
        for item in group or []:
            name = _safe_str(item.get("name"))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _structure_suggestion_default_rank(preferred_query: str, suggestion: Mapping[str, Any]) -> tuple[int, int, str]:
    preferred_sig = _structure_text_signature(_safe_str(preferred_query))
    name = _safe_str(suggestion.get("name"))
    name_sig = _structure_text_signature(name)
    match_kind = _safe_str(suggestion.get("match_kind"))
    exact_tier = 0
    if preferred_sig and name_sig and name_sig == preferred_sig:
        exact_tier = 5
    elif match_kind == "raw_exact":
        exact_tier = 4
    elif match_kind == "translated":
        exact_tier = 3
    elif match_kind == "normalized_exact":
        exact_tier = 2
    elif match_kind == "query_variant":
        exact_tier = 1
    similarity = 0
    if preferred_sig and name_sig:
        similarity = int(difflib.SequenceMatcher(None, name_sig, preferred_sig).ratio() * 1000)
    return (
        -exact_tier,
        -similarity,
        -int(bool(suggestion.get("resolver_success"))),
        name.lower(),
    )


def _local_structure_suggestions(query: str) -> List[Dict[str, Any]]:
    cleaned = _plausible_structure_seed(query)
    if not cleaned:
        return []
    normalized = normalize_user_text(cleaned)
    hypothesis_bundle = build_structure_hypotheses(cleaned)
    lower = _safe_str(
        hypothesis_bundle.get("primary_candidate")
        or normalized.get("maybe_structure_hint")
        or cleaned
    ).lower()
    names = [entry["name"] for entry in _STRUCTURE_SUGGESTION_CATALOG]
    similar_names = difflib.get_close_matches(lower, names, n=5, cutoff=0.35)

    out: List[Dict[str, Any]] = []
    seen = set()

    for candidate in list(hypothesis_bundle.get("candidate_queries") or []) + list(normalized.get("candidate_queries") or []):
        token = _safe_str(candidate)
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": token,
                "formula": "",
                "atoms": None,
                "description": f"{token} — 입력 후보",
            }
        )

    for name in similar_names:
        for entry in _STRUCTURE_SUGGESTION_CATALOG:
            if entry["name"] == name:
                if entry["name"].lower() in seen:
                    break
                seen.add(entry["name"].lower())
                out.append(dict(entry))
                break
    if cleaned and _looks_like_molecule(cleaned) and cleaned.lower() not in seen:
        out.insert(0, {"name": cleaned, "formula": "", "atoms": None, "description": f"{cleaned} — 입력한 이름 그대로 사용"})
    return out[:5]


def _resolver_backed_structure_suggestions(query: str) -> List[Dict[str, Any]]:
    cleaned = _safe_str(query)
    if not cleaned:
        return []
    if _is_semantic_structure_descriptor(cleaned):
        return []
    out: List[Dict[str, Any]] = []
    resolver = _get_resolver()
    if resolver is not None and hasattr(resolver, "suggest_candidate_queries"):
        try:
            suggested = resolver.suggest_candidate_queries(cleaned, limit=5) or []
            for item in suggested:
                name = _safe_str(item.get("name"))
                if not name:
                    continue
                match_kind = _safe_str(item.get("match_kind"))
                source = _safe_str(item.get("source"))
                expected_charge = item.get("expected_charge")
                parts = [name]
                meta_bits: List[str] = []
                if match_kind == "raw_exact":
                    meta_bits.append("입력한 이름 그대로 사용")
                elif match_kind == "translated":
                    meta_bits.append("번역/별칭 후보")
                elif match_kind == "normalized_exact":
                    meta_bits.append("정규화 후보")
                elif match_kind == "query_variant":
                    meta_bits.append("유사 질의 후보")
                if source and source not in {"user_input", "resolver_query_plan"}:
                    meta_bits.append(source)
                if expected_charge is not None:
                    meta_bits.append(f"expected charge {expected_charge:+d}")
                out.append(
                    {
                        "name": name,
                        "description": " — ".join(parts + ([" / ".join(meta_bits)] if meta_bits else [])),
                        "formula": "",
                        "atoms": None,
                        "match_kind": match_kind,
                        "source": source,
                        "expected_charge": expected_charge,
                        "resolver_success": bool(item.get("resolver_success")),
                    }
                )
        except Exception:
            logger.exception("Failed to build resolver-backed structure suggestions for %r", cleaned)
    return out


async def _discovery_structure_suggestions(raw_message: str, query: str) -> List[Dict[str, Any]]:
    from qcviz_mcp.web.routes.compute import get_qcviz_agent

    normalized = normalize_user_text(raw_message or query or "")
    if normalized.get("semantic_descriptor"):
        semantic_suggestions = await _molchat_interpret_candidates(raw_message or query)
        logger.info(
            "Discovery semantic suggestions for %r -> %s",
            raw_message or query,
            [item.get("name") for item in semantic_suggestions],
            extra=_semantic_runtime_log_context(),
        )
        return semantic_suggestions
    suggestion_seed = (
        _plausible_structure_seed(raw_message)
        or _plausible_structure_seed(query)
        or _safe_str(normalized.get("maybe_structure_hint"))
    )
    if suggestion_seed and not _looks_like_molecule(suggestion_seed):
        suggestion_seed = ""
    local_suggestions = _local_structure_suggestions(suggestion_seed)
    resolver_suggestions = _resolver_backed_structure_suggestions(suggestion_seed)
    gemini_suggestions: List[Dict[str, Any]] = []
    agent = get_qcviz_agent()
    if agent and hasattr(agent, "suggest_molecules") and not suggestion_seed:
        try:
            gemini_suggestions = _agent_semantic_suggestions(
                agent,
                raw_message,
                allow_generic_fallback=True,
            )
        except Exception:
            logger.exception("Gemini molecule suggestion failed for %r", raw_message)
    suggestions = _merge_structure_suggestions(resolver_suggestions, local_suggestions, gemini_suggestions)
    if suggestions:
        return suggestions
    return [
        {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "벤젠 — aromatic reference"},
        {"name": "acetone", "formula": "C3H6O", "atoms": 10, "description": "아세톤 — common carbonyl example"},
        {"name": "ethanol", "formula": "C2H6O", "atoms": 9, "description": "에탄올 — common organic solvent"},
    ]


async def _build_clarification_fields(
    reasons: List[str],
    plan: Dict[str, Any],
    prepared: Dict[str, Any],
    raw_message: str,
    *,
    asked_fields: Optional[List[str]] = None,
) -> List[ClarificationField]:
    """Build minimal clarification fields using a fixed field skeleton."""
    fields: List[ClarificationField] = []
    asked = set(asked_fields or [])
    query = _safe_str(prepared.get("structure_query")) or raw_message or ""
    mode = _clarification_mode(plan, prepared, raw_message, reasons)

    mentioned: List[Dict[str, Any]] = list(prepared.get("mentioned_molecules") or plan.get("mentioned_molecules") or [])
    mentioned_names = [
        _canonical_entry_name(item)
        for item in mentioned
        if _canonical_entry_name(item)
    ]
    multi_candidates = len(mentioned_names) > 1
    selection_pending = not prepared.get("selected_molecules")
    if multi_candidates and selection_pending and "target_selection" not in asked:
        subset_options = [
            ClarificationOption(value=name, label=name) for name in mentioned_names
        ]
        fields.append(
            ClarificationField(
                id="target_selection",
                type="radio",
                label="추출된 분자를 어떻게 계산할까요? / Which molecules should we compute?",
                required=True,
                options=[
                    ClarificationOption(value="all_mentioned", label="전부 다 계산"),
                    ClarificationOption(value="select_subset", label="일부만 선택"),
                    ClarificationOption(value="custom", label="직접 입력"),
                ],
                default="all_mentioned",
            )
        )
        fields.append(
            ClarificationField(
                id="target_subset",
                type="multiselect",
                label="계산할 분자를 선택해 주세요 / Select molecules",
                options=subset_options,
                default=mentioned_names,
                help_text="여러 항목을 선택하려면 Shift/Ctrl을 누르세요.",
            )
        )
        if "structure_custom" not in asked:
            fields.append(
                ClarificationField(
                    id="structure_custom",
                    type="text",
                    label="직접 입력 / Custom molecule name or SMILES",
                    placeholder="예: acetone, water, CC(=O)C",
                    help_text="custom을 선택한 경우에만 사용됩니다.",
                )
            )
        return fields

    if "no_structure" in reasons and "structure_choice" not in asked:
        suggestion_seed = _explicit_structure_attempt(plan, prepared, raw_message) or query or raw_message
        if mode == "semantic_grounding":
            suggestions = await _molchat_interpret_candidates(suggestion_seed)
        elif mode == "disambiguation":
            suggestions = _merge_structure_suggestions(
                _resolver_backed_structure_suggestions(suggestion_seed),
                _local_structure_suggestions(suggestion_seed),
            )
            preferred_query = (
                extract_structure_candidate(raw_message)
                or _safe_str(normalize_user_text(raw_message or "").get("maybe_structure_hint"))
                or suggestion_seed
            )
            suggestions = sorted(
                suggestions,
                key=lambda item: _structure_suggestion_default_rank(preferred_query, item),
            )
        else:
            suggestions = await _discovery_structure_suggestions(raw_message, query)

        logger.info(
            "Clarification suggestions built for mode=%s query=%r options=%s",
            mode,
            suggestion_seed,
            [item.get("name") for item in suggestions],
            extra=_semantic_runtime_log_context(),
        )

        options: List[ClarificationOption] = []
        default_val = None
        for s in suggestions:
            name = s.get("name", "")
            desc = s.get("label") or s.get("description", name)
            formula = s.get("formula", "")
            label = f"{desc} ({formula})" if formula else desc
            options.append(ClarificationOption(value=name, label=label))
            if default_val is None:
                default_val = name

        if not options and suggestion_seed and mode == "disambiguation":
            options = [
                ClarificationOption(value=suggestion_seed, label=f"{suggestion_seed} — 입력한 이름 그대로 사용"),
            ]
            default_val = suggestion_seed

        options.append(ClarificationOption(value="custom", label="직접 입력 (Custom)"))
        fields.append(
            ClarificationField(
                id="structure_choice",
                type="select",
                label=(
                    "혹시 아래 후보 중 어떤 분자인가요? / Which molecule did you mean?"
                    if mode == "disambiguation"
                    else "분자를 선택해 주세요 / Choose a molecule"
                ),
                required=True,
                options=options,
                default=default_val,
                help_text=(
                    "입력하신 이름과 가장 가까운 후보를 정리했습니다. custom을 선택해 직접 수정할 수도 있습니다."
                    if mode == "disambiguation"
                    else "추천 목록에서 고르거나 custom을 선택해 직접 입력할 수 있습니다."
                ),
            )
        )
        if "structure_custom" not in asked:
            fields.append(
                ClarificationField(
                    id="structure_custom",
                    type="text",
                    label="직접 입력 / Custom molecule name or SMILES",
                    placeholder="예: acetone, water, CC(=O)C",
                    help_text="custom을 선택한 경우에만 사용됩니다.",
                )
            )

    if "missing_orbital" in reasons and "orbital" not in asked:
        fields.append(
            ClarificationField(
                id="orbital",
                type="radio",
                label="어떤 오비탈을 볼까요? / Which orbital do you want?",
                required=True,
                options=[
                    ClarificationOption(value="HOMO", label="HOMO"),
                    ClarificationOption(value="LUMO", label="LUMO"),
                    ClarificationOption(value="both", label="둘 다 (Both)"),
                ],
                default=prepared.get("orbital") or "HOMO",
            )
        )

    if "multiple_molecules" in reasons and query and "composition_mode" not in asked:
        fields.append(
            ClarificationField(
                id="composition_mode",
                type="radio",
                label=f"'{query}'을(를) 어떻게 해석할까요? / How should this input be interpreted?",
                required=True,
                options=[
                    ClarificationOption(value="ion_pair", label="이온쌍 (Ion pair)"),
                    ClarificationOption(value="single", label="단일/그대로 사용"),
                    ClarificationOption(value="separate", label="각각 따로 계산"),
                ],
                default="ion_pair",
            )
        )

    if "ion_charge_unclear" in reasons and "charge" not in asked:
        fields.append(
            ClarificationField(
                id="charge",
                type="number",
                label="전체 전하 / Total charge",
                default=prepared.get("charge", 0),
                help_text="명시하지 않으면 기본값 0을 사용합니다.",
            )
        )

    return fields


async def _build_clarification_form(
    plan: Dict[str, Any],
    prepared: Dict[str, Any],
    raw_message: str,
    *,
    asked_fields: Optional[List[str]] = None,
) -> Optional[ClarificationForm]:
    typo_candidates = [str(item).strip() for item in list(plan.get("typo_candidates") or []) if str(item).strip()]
    clarification_kind = _safe_str(prepared.get("clarification_kind") or plan.get("clarification_kind"))
    if clarification_kind == "typo_suspicion" and typo_candidates:
        return _build_typo_clarification_form(
            original_query=_safe_str(plan.get("structure_query") or raw_message),
            typo_candidates=typo_candidates,
        )

    reasons = _detect_ambiguity(plan, prepared, raw_message)
    fields = await _build_clarification_fields(
        reasons,
        plan,
        prepared,
        raw_message,
        asked_fields=asked_fields,
    )
    if not fields:
        return None
    mode = _clarification_mode(plan, prepared, raw_message, reasons)
    title = "추가 정보가 필요합니다 / More information needed"
    message = "필요한 항목만 확인하면 바로 계산을 이어서 진행합니다."
    if mode == "disambiguation":
        title = "분자 후보를 확인해 주세요 / Confirm the molecule"
        message = "입력하신 이름을 기준으로 가장 가까운 후보를 정리했습니다."
    elif mode == "semantic_grounding":
        title = "설명 기반 후보를 확인해 주세요 / Confirm candidates from the description"
        message = "입력하신 설명을 기반으로 MolChat에서 구조화한 후보를 정리했습니다."
    elif mode == "discovery":
        title = "계산할 분자를 골라 주세요 / Choose a molecule to compute"
        message = "입력 내용만으로는 분자가 특정되지 않아 먼저 후보를 제안합니다."
    elif mode == "parameter_completion":
        title = "계산 파라미터를 확인해 주세요 / Confirm the missing parameter"
        message = "구조는 파악됐고, 필요한 계산 항목만 더 확인하면 바로 진행합니다."
    elif mode == "continuation_targeting":
        title = "이전 계산 대상을 확인해 주세요 / Confirm what to continue"
        message = "후속 요청으로 보이지만 이어받을 이전 구조가 없어 계산 대상을 먼저 확인해야 합니다."
    return ClarificationForm(
        mode=mode,
        title=title,
        message=message,
        fields=fields,
    )


def _apply_clarification_answers(
    pending_payload: Mapping[str, Any],
    answers: Mapping[str, Any],
    *,
    raw_message: str,
    session_id: Optional[str] = None,
    candidate_bindings: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> SlotMergeResult:
    merged = dict(pending_payload or {})
    answers = dict(answers or {})
    candidate_bindings = dict(candidate_bindings or {})

    target_selection = _safe_str(answers.get("target_selection"))
    if target_selection:
        if target_selection == "all_mentioned":
            merged["target_scope"] = "all_mentioned"
            merged["selection_mode"] = "explicit_all"
            mentioned_entries = merged.get("mentioned_molecules") or []
            mentioned_names = [
                _canonical_entry_name(entry)
                for entry in mentioned_entries
                if _canonical_entry_name(entry)
            ]
            selected_candidates = mentioned_names or list(answers.get("target_subset") or [])
            merged["selected_molecules"] = selected_candidates
            merged["batch_request"] = len(selected_candidates) > 1
            merged.pop("structure_query", None)
        elif target_selection == "select_subset":
            selected_candidates = [str(item) for item in (answers.get("target_subset") or []) if _safe_str(item)]
            merged["target_scope"] = "subset"
            merged["selection_mode"] = "subset_picker"
            merged["selected_molecules"] = selected_candidates
            merged["batch_request"] = len(selected_candidates) > 1
            merged.pop("structure_query", None)
        elif target_selection == "custom":
            custom = _safe_str(answers.get("structure_custom"))
            if custom:
                merged["structure_query"] = custom
        merged["planner_applied"] = True
        still_missing = _current_missing_slots(merged, merged)
        return SlotMergeResult(
            session_id=session_id,
            prior_plan=dict(pending_payload or {}),
            user_answers=_json_safe(answers),
            merged_plan=_json_safe(merged),
            still_missing_slots=still_missing,
            ready_to_execute=not still_missing,
        )

    structure_choice = _safe_str(answers.get("structure_choice"))
    structure_custom = _safe_str(answers.get("structure_custom"))
    if structure_choice:
        if structure_choice == "custom" and structure_custom:
            merged["structure_query"] = structure_custom
            merged["structure_locked"] = False
        elif structure_choice != "custom":
            bound_candidate = dict(candidate_bindings.get(structure_choice) or {})
            merged["structure_query"] = _safe_str(
                bound_candidate.get("name")
                or bound_candidate.get("structure_query")
                or structure_choice
            )
            if bound_candidate:
                merged["selected_candidate_record"] = _json_safe(bound_candidate)
            merged["structure_locked"] = True
            merged["composition_mode"] = "single"
            merged.pop("structures", None)
    elif structure_custom and not merged.get("structure_query"):
        merged["structure_query"] = structure_custom
        merged["structure_locked"] = False

    orbital = _safe_str(answers.get("orbital"))
    if orbital:
        merged["orbital"] = "HOMO" if orbital.lower() == "both" else orbital.upper()
        if orbital.lower() == "both":
            notes = list(merged.get("planner_notes") or [])
            notes.append("User requested both orbitals; defaulting first render to HOMO.")
            merged["planner_notes"] = notes

    if answers.get("charge") not in (None, ""):
        try:
            merged["charge"] = int(answers.get("charge"))
        except Exception:
            pass
    if answers.get("multiplicity") not in (None, ""):
        try:
            merged["multiplicity"] = int(answers.get("multiplicity"))
        except Exception:
            pass

    composition_mode = _safe_str(answers.get("composition_mode"))
    if composition_mode:
        merged["composition_mode"] = composition_mode
        if composition_mode == "ion_pair":
            query = _safe_str(merged.get("structure_query") or raw_message)
            ion_tokens = re.findall(r"[\w]+[+\-]", query)
            if len(ion_tokens) >= 2:
                merged["structures"] = [
                    {"name": token, "charge": 1 if token.endswith("+") else -1}
                    for token in ion_tokens
                ]
            else:
                neutral_tokens = [token for token in re.split(r"[\s,;/]+", query) if len(token) > 1]
                if len(neutral_tokens) >= 2:
                    merged["structures"] = [{"name": token, "charge": 0} for token in neutral_tokens[:2]]

    merged["planner_applied"] = True
    still_missing = _current_missing_slots(merged, merged)
    return SlotMergeResult(
        session_id=session_id,
        prior_plan=dict(pending_payload or {}),
        user_answers=_json_safe(answers),
        merged_plan=_json_safe(merged),
        still_missing_slots=still_missing,
        ready_to_execute=not still_missing,
    )


def _summarize_plan_for_confirm(prepared: Dict[str, Any]) -> str:
    """Human-readable summary of computation plan."""
    parts = []
    q = prepared.get("structure_query") or prepared.get("structure_name") or "unknown"
    jt = prepared.get("job_type", "single_point")
    m = prepared.get("method", "B3LYP")
    b = prepared.get("basis", "def2-SVP")
    ch = prepared.get("charge", 0)
    mult = prepared.get("multiplicity", 1)

    jt_labels = {
        "single_point": "에너지 계산",
        "geometry_optimization": "구조 최적화",
        "orbital_preview": "오비탈 시각화",
        "esp_map": "ESP 맵",
        "partial_charges": "부분 전하",
    }
    jt_label = jt_labels.get(jt, jt)

    parts.append(f"🧪 **{q}**")
    parts.append(f"📐 {jt_label} | {m}/{b}")
    parts.append(f"⚡ charge={ch}, multiplicity={mult}")
    return "\n".join(parts)


async def _prepare_or_clarify(
    body: Mapping[str, Any],
    *,
    raw_message: str,
    session_id: str,
    turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    plan = _build_validated_plan(raw_message, body) if raw_message else {}
    pending = _merge_plan_into_payload(dict(body or {}), plan, raw_message=raw_message)
    if plan.get("clarification_kind") == "typo_suspicion":
        typo_candidates = list(plan.get("verified_typo_candidates") or plan.get("typo_candidates") or [])
        verified_candidates = await _probe_verified_typo_candidates(
            _safe_str(plan.get("structure_query") or pending.get("structure_query") or raw_message),
            typo_candidates,
        )
        if verified_candidates:
            plan["verified_typo_candidates"] = verified_candidates
            plan["typo_candidates"] = verified_candidates
        if len(verified_candidates) == 1:
            promoted = _safe_str(verified_candidates[0])
            original_query = _safe_str(plan.get("structure_query") or pending.get("structure_query") or raw_message)
            pending["structure_query"] = promoted
            plan["structure_query"] = promoted
            plan["confidence"] = max(float(plan.get("confidence") or 0.0), 0.85)
            plan["confidence_band"] = "high"
            plan["needs_clarification"] = False
            plan["clarification_kind"] = None
            plan["missing_slots"] = [
                slot for slot in list(plan.get("missing_slots") or [])
                if _safe_str(slot) != "structure_query"
            ]
            notes = list(plan.get("reasoning_notes") or [])
            notes.append(f"verified typo rescue auto-promoted: {original_query} -> {promoted}")
            plan["reasoning_notes"] = _dedupe_strings([_safe_str(item) for item in notes if _safe_str(item)])
            pending["typo_autocorrected_from"] = original_query
            pending["verified_typo_candidate"] = promoted
            prepared = _prepare_payload(pending)
            return {
                "requires_clarification": False,
                "plan": plan,
                "pending": pending,
                "prepared": prepared,
                "turn_id": _safe_str(turn_id),
            }
    form = await _build_clarification_form(plan, pending, raw_message)
    if form is not None:
        asked_fields = [field.id for field in form.fields]
        _session_put(
            session_id,
            {
                "pending_payload": pending,
                "plan": plan,
                "raw_message": raw_message,
                "asked_fields": asked_fields,
                "candidate_bindings": _build_candidate_bindings_from_form(form),
                "turn_id": _safe_str(turn_id),
            },
        )
        return {
            "requires_clarification": True,
            "plan": plan,
            "pending": pending,
            "clarification": form,
            "turn_id": _safe_str(turn_id),
        }

    prepared = _prepare_payload(pending)
    return {
        "requires_clarification": False,
        "plan": plan,
        "pending": pending,
        "prepared": prepared,
        "turn_id": _safe_str(turn_id),
    }


async def _handle_clarification_response(
    *,
    session_id: str,
    answers: Mapping[str, Any],
) -> Dict[str, Any]:
    state = _session_get(session_id)
    if not state:
        raise HTTPException(status_code=400, detail="Clarification session not found or expired.")

    pending_payload = dict(state.get("pending_payload") or {})
    raw_message = _safe_str(state.get("raw_message"))
    asked_fields = list(state.get("asked_fields") or [])
    plan = dict(state.get("plan") or {})
    candidate_bindings = dict(state.get("candidate_bindings") or {})
    turn_id = _safe_str(state.get("turn_id"))

    merge_result = _apply_clarification_answers(
        pending_payload,
        answers,
        raw_message=raw_message,
        session_id=session_id,
        candidate_bindings=candidate_bindings,
    )
    merged_plan = dict(merge_result.merged_plan or {})
    updated_asked = _dedupe_strings(asked_fields + list((answers or {}).keys()))
    form = await _build_clarification_form(plan, merged_plan, raw_message, asked_fields=updated_asked)

    if form is not None:
        _session_put(
            session_id,
            {
                "pending_payload": merged_plan,
                "plan": plan,
                "raw_message": raw_message,
                "asked_fields": updated_asked + [field.id for field in form.fields],
                "candidate_bindings": candidate_bindings or _build_candidate_bindings_from_form(form),
                "turn_id": turn_id,
            },
        )
        return {
            "requires_clarification": True,
            "merge_result": merge_result,
            "clarification": form,
            "plan": merged_plan,
            "turn_id": turn_id,
        }

    _session_pop(session_id)
    prepared = _prepare_payload(merged_plan)
    return {
        "requires_clarification": False,
        "merge_result": merge_result,
        "prepared": prepared,
        "plan": merged_plan,
        "turn_id": turn_id,
    }


async def _ws_send(websocket: WebSocket, event_type: str, **payload: Any) -> None:
    body = {"type": event_type, **_json_safe(payload)}
    await websocket.send_json(body)


async def _ws_send_error(
    websocket: WebSocket, *,
    message: str, detail: Optional[Any] = None,
    status_code: int = 400, session_id: Optional[str] = None,
    **extra: Any,
) -> None:
    error_obj = {
        "message": _safe_str(message, "Request failed"),
        "detail": _json_safe(detail),
        "status_code": status_code,
        "timestamp": _now_ts(),
    }
    await _ws_send(websocket, "error", session_id=session_id, error=error_obj, **extra)


async def _stream_backend_job_until_terminal(
    websocket: WebSocket, *, job_id: str, session_id: str, turn_id: Optional[str] = None,
) -> None:
    manager = get_job_manager()
    seen_event_ids: set = set()
    last_state = None

    while True:
        snap = manager.get(job_id, include_result=False, include_events=True)
        if snap is None:
            await _ws_send_error(websocket, message="Job not found while streaming.", status_code=404, session_id=session_id)
            return

        queue = snap.get("queue") or {}
        state_key = (
            snap.get("status"),
            snap.get("progress"),
            snap.get("step"),
            snap.get("message"),
            queue.get("running_count"),
            queue.get("queued_count"),
            queue.get("queued_ahead"),
            queue.get("queue_position"),
        )
        if snap.get("status") not in TERMINAL_STATES and state_key != last_state:
            await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                           status=snap.get("status"), progress=snap.get("progress"),
                           step=snap.get("step"), message=snap.get("message"), queue=queue, job=snap, turn_id=turn_id)
            last_state = state_key

        for event in snap.get("events", []) or []:
            event_id = event.get("event_id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            event_type = event.get("type", "")

            if event_type == "job_progress":
                data = event.get("data") or {}
                # Include SCF convergence data if present
                scf_kwargs = {}
                for k in ("scf_history", "scf_dE", "scf_cycle", "scf_energy", "scf_max_cycle", "preview_result"):
                    if k in data:
                        scf_kwargs[k] = data[k]
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running", progress=data.get("progress", 0.0),
                               step=data.get("step", ""), message=event.get("message", ""),
                               queue=queue, turn_id=turn_id, **scf_kwargs)
                continue
            if event_type == "job_started":
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running",
                               step=event_type, message=event.get("message", ""), queue=queue, job=snap, turn_id=turn_id)
                continue
            if event_type == "job_completed":
                continue
            await _ws_send(websocket, "job_event", session_id=session_id, job_id=job_id, event=event, turn_id=turn_id)

        if snap.get("status") in TERMINAL_STATES:
            terminal = manager.get(job_id, include_result=True, include_events=True)
            if terminal is None:
                await _ws_send_error(websocket, message="Job disappeared.", status_code=404, session_id=session_id)
                return
            if terminal.get("status") in TERMINAL_FAILURE:
                await _ws_send_error(
                    websocket,
                    message=((terminal.get("error") or {}).get("message") or terminal.get("message") or "Job failed."),
                    detail=terminal.get("error"),
                    status_code=int(((terminal.get("error") or {}).get("status_code")) or 500),
                    session_id=session_id,
                    turn_id=turn_id,
                )
                return
            result = terminal.get("result") or {}
            ws_result = _compact_result_for_ws(result)
            ws_job = {k: v for k, v in terminal.items() if k != "result"}
            ws_job["result"] = ws_result
            await _ws_send(
                websocket,
                "job_update",
                session_id=session_id,
                job_id=job_id,
                status="completed",
                progress=1.0,
                step="job_completed",
                message=terminal.get("message") or "Job completed.",
                queue=terminal.get("queue") or {},
                job=ws_job,
                result=ws_result,
                turn_id=turn_id,
            )
            await _ws_send(
                websocket,
                "result",
                session_id=session_id,
                job=ws_job,
                result=ws_result,
                summary=_result_summary(result),
                turn_id=turn_id,
            )
            return

        await asyncio.sleep(WS_POLL_SECONDS)


@router.get("/chat/health")
def chat_health() -> Dict[str, Any]:
    manager = get_job_manager()
    return {"ok": True, "route": "/chat", "ws_route": "/ws/chat",
            "job_backend": manager.__class__.__name__, "runtime": runtime_debug_info(),
            "metrics_summary": _web_metrics_summary(), "timestamp": _now_ts()}


@router.post("/chat")
async def post_chat(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    body = dict(payload or {})
    auth_user = _resolve_auth_user(body, header_auth_token=x_qcviz_auth_token)
    session_meta = _resolve_session_auth(
        body,
        header_session_id=x_qcviz_session_id,
        header_session_token=x_qcviz_session_token,
        allow_new=True,
    )
    body["session_id"] = session_meta["session_id"]
    body.pop("session_token", None)
    raw_message = _extract_message(body)
    session_id = _extract_session_id(body) or session_meta["session_id"]
    body.setdefault("session_id", session_id)
    msg_type = _safe_str(body.get("type")).lower()

    if msg_type == "clarify_response" or body.get("answers"):
        merge_state = await _handle_clarification_response(
            session_id=session_id,
            answers=body.get("answers") or {},
        )
        if merge_state["requires_clarification"]:
            clarification = merge_state["clarification"]
            return {
                "ok": False,
                "requires_clarification": True,
                "session_id": session_id,
                "session_token": session_meta["session_token"],
                "plan": _public_plan_dict(merge_state.get("plan") or {}),
                "clarification_kind": clarification.mode,
                "clarification": clarification.model_dump(),
                "slot_merge": merge_state["merge_result"].model_dump(),
            }
        prepared = merge_state["prepared"]
        plan = merge_state.get("plan") or {}
    else:
        plan = _build_validated_plan(raw_message, body) if raw_message else {}
        semantic_chat = await _resolve_semantic_chat_mode(
            plan,
            body=body,
            raw_message=raw_message,
            session_id=session_id,
        )
        if semantic_chat and semantic_chat.get("kind") == "clarify":
            clarification = semantic_chat["clarification"]
            return {
                "ok": False,
                "requires_clarification": True,
                "session_id": session_id,
                "session_token": session_meta["session_token"],
                "plan": _public_plan_dict(semantic_chat.get("plan") or plan),
                "clarification_kind": clarification.mode,
                "clarification": clarification.model_dump(),
                "pending_payload": _json_safe(semantic_chat.get("pending") or {}),
            }
        if semantic_chat and semantic_chat.get("kind") == "chat":
            return {
                "ok": True,
                "chat_only": True,
                "session_id": session_id,
                "session_token": session_meta["session_token"],
                "message": semantic_chat["message"],
                "plan": _public_plan_dict(semantic_chat.get("plan") or plan),
                "job": None,
            }
        if _plan_is_chat_only(plan):
            return {
                "ok": True,
                "chat_only": True,
                "session_id": session_id,
                "session_token": session_meta["session_token"],
                "message": await _resolve_chat_response_async(plan, raw_message),
                "plan": _public_plan_dict(plan),
                "job": None,
            }
        preflight = await _prepare_or_clarify(body, raw_message=raw_message, session_id=session_id)
        plan = preflight.get("plan") or plan
        if preflight["requires_clarification"]:
            clarification = preflight["clarification"]
            return {
                "ok": False,
                "requires_clarification": True,
                "session_id": session_id,
                "session_token": session_meta["session_token"],
                "plan": _public_plan_dict(plan),
                "clarification_kind": clarification.mode,
                "clarification": clarification.model_dump(),
                "pending_payload": _json_safe(preflight["pending"]),
            }
        prepared = preflight["prepared"]

    if auth_user:
        prepared["owner_username"] = auth_user["username"]
        prepared["owner_display_name"] = auth_user.get("display_name") or auth_user["username"]

    plan_message = _plan_status_message(plan, prepared)

    manager = get_job_manager()
    submitted = _submit_or_reuse_job(prepared, manager=manager)

    should_wait = bool(wait or wait_for_result or body.get("wait") or body.get("wait_for_result") or body.get("sync"))
    if should_wait:
        terminal = manager.wait(submitted["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        ok = terminal.get("status") not in TERMINAL_FAILURE
        terminal["reused"] = bool(submitted.get("reused"))
        if submitted.get("original_job_id"):
            terminal["original_job_id"] = submitted.get("original_job_id")
        if submitted.get("canonical_result_key"):
            terminal["canonical_result_key"] = submitted.get("canonical_result_key")
        return {
            "ok": ok, "session_id": session_id, "session_token": session_meta["session_token"], "message": plan_message, "plan": _public_plan_dict(plan),
            "job": terminal, "result": terminal.get("result"), "error": terminal.get("error"),
            "summary": _result_summary(terminal.get("result") or {}),
        }

    return {
        "ok": True,
        "session_id": session_id,
        "session_token": session_meta["session_token"],
        "message": plan_message,
        "plan": _public_plan_dict(plan),
        "job": submitted,
    }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    query_session_id = _safe_str(websocket.query_params.get("session_id"))
    query_session_token = _safe_str(websocket.query_params.get("session_token"))
    query_auth_token = _safe_str(websocket.query_params.get("auth_token"))
    auth_user: Optional[Dict[str, Any]] = None
    if query_auth_token:
        auth_user = get_auth_user(query_auth_token)
        if auth_user is None:
            await websocket.accept()
            await _ws_send_error(
                websocket,
                message="Invalid auth token.",
                status_code=401,
                session_id=query_session_id or "",
            )
            await websocket.close(code=4401)
            return
    try:
        session_meta = bootstrap_or_validate_session(
            query_session_id or None,
            query_session_token or None,
            allow_new=True,
        )
    except HTTPException as exc:
        await websocket.accept()
        await _ws_send_error(
            websocket,
            message=_safe_str(exc.detail, "Session bootstrap failed."),
            status_code=exc.status_code,
            session_id=query_session_id or "",
        )
        await websocket.close(code=4403)
        return

    await websocket.accept()

    default_session_id = session_meta["session_id"]
    default_session_token = session_meta["session_token"]
    session_state: Dict[str, Any] = {"chat_history": []}

    await _ws_send(websocket, "ready", session_id=default_session_id,
                   session_token=default_session_token,
                   auth_user=auth_user,
                   message="QCViz chat websocket connected.", timestamp=_now_ts())

    # FIX(M3): keepalive ping task
    async def _keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(WS_PING_INTERVAL)
                try:
                    await websocket.send_json({"type": "ping", "ts": _now_ts()})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_keepalive())

    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # FIX(M3): send ping on timeout, don't disconnect
                try:
                    await websocket.send_json({"type": "ping", "ts": _now_ts()})
                except Exception:
                    break
                continue

            incoming = _parse_client_message(raw_text)
            session_id = _extract_session_id(incoming) or default_session_id
            session_token = _extract_session_token(incoming) or default_session_token
            incoming_auth_user = _resolve_auth_user(incoming, auth_token=query_auth_token)
            auth_user = incoming_auth_user or auth_user
            if session_id != default_session_id:
                await _ws_send_error(
                    websocket,
                    message="This websocket is bound to a different session.",
                    status_code=403,
                    session_id=default_session_id,
                )
                await websocket.close(code=4403)
                break
            try:
                validate_session_token(session_id, session_token)
            except HTTPException as exc:
                await _ws_send_error(
                    websocket,
                    message=_safe_str(exc.detail, "Invalid session token."),
                    status_code=exc.status_code,
                    session_id=session_id,
                )
                await websocket.close(code=4403)
                break
            incoming.setdefault("session_id", session_id)
            incoming.setdefault("session_token", session_token)
            turn_id = _safe_str(incoming.get("turn_id"))
            msg_type = str(incoming.get("type", "")).lower().strip()

            if msg_type in ("hello", "ping", "pong", "ack"):
                await _ws_send(websocket, "ack", session_id=session_id, status="connected", turn_id=turn_id, timestamp=_now_ts())
                continue

            # ── Handle clarification response ──
            if msg_type == "clarify_response":
                try:
                    merge_state = await _handle_clarification_response(
                        session_id=session_id,
                        answers=incoming.get("answers") or {},
                    )
                except HTTPException as exc:
                    await _ws_send_error(
                        websocket,
                        message=_safe_str(exc.detail, "Clarification failed."),
                        detail={"session_id": session_id},
                        status_code=exc.status_code,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    continue

                if merge_state["requires_clarification"]:
                    clarification = merge_state["clarification"]
                    await _ws_send(
                        websocket,
                        "clarify",
                        session_id=session_id,
                        message=clarification.message,
                        clarification_kind=clarification.mode,
                        form=clarification.model_dump(),
                        fields=[field.model_dump() for field in clarification.fields],
                        slot_merge=merge_state["merge_result"].model_dump(),
                        turn_id=merge_state.get("turn_id") or turn_id,
                        timestamp=_now_ts(),
                    )
                    continue

                prepared = merge_state["prepared"]
                if auth_user:
                    prepared["owner_username"] = auth_user["username"]
                    prepared["owner_display_name"] = auth_user.get("display_name") or auth_user["username"]

                await _ws_send(
                    websocket,
                    "assistant",
                    session_id=session_id,
                    message=_plan_status_message(merge_state.get("plan"), prepared),
                    plan=_public_plan_dict(merge_state.get("plan") or {}),
                    payload_preview={
                        "job_type": prepared.get("job_type"),
                        "structure_query": prepared.get("structure_query"),
                        "method": prepared.get("method"),
                        "basis": prepared.get("basis"),
                        "orbital": prepared.get("orbital"),
                    },
                    turn_id=merge_state.get("turn_id") or turn_id,
                    timestamp=_now_ts(),
                )
                manager = get_job_manager()
                try:
                    submitted = _submit_or_reuse_job(prepared, manager=manager)
                except HTTPException as exc:
                    quota = manager.quota_summary(
                        session_id=session_id,
                        owner_username=_safe_str((auth_user or {}).get("username")),
                    )
                    await _ws_send_error(
                        websocket,
                        message=_safe_str(exc.detail, "Job submission failed."),
                        detail={"payload_preview": {"job_type": prepared.get("job_type"), "structure_query": prepared.get("structure_query")}},
                        status_code=exc.status_code,
                        session_id=session_id,
                        quota=quota,
                        turn_id=merge_state.get("turn_id") or turn_id,
                    )
                    continue
                except Exception as exc:
                    logger.exception("Job submission failed.")
                    await _ws_send_error(websocket, message="Job submission failed.",
                                         detail={"type": exc.__class__.__name__, "message": str(exc)},
                                         status_code=500, session_id=session_id, turn_id=merge_state.get("turn_id") or turn_id)
                    continue
                await _ws_send(websocket, "job_submitted", session_id=session_id, job=submitted, turn_id=merge_state.get("turn_id") or turn_id, timestamp=_now_ts())
                await _stream_backend_job_until_terminal(websocket, job_id=submitted["job_id"], session_id=session_id, turn_id=merge_state.get("turn_id") or turn_id)
                continue

            user_message = _extract_message(incoming)

            await _ws_send(websocket, "ack", session_id=session_id,
                           message=user_message or "Request received.", payload=incoming, turn_id=turn_id, timestamp=_now_ts())

            try:
                preliminary_plan = _build_validated_plan(user_message, incoming) if user_message else {}
            except Exception as exc:
                logger.warning("Preliminary chat plan generation failed: %s", exc)
                preliminary_plan = {}

            semantic_chat = await _resolve_semantic_chat_mode(
                preliminary_plan,
                body=incoming,
                raw_message=user_message or "",
                session_id=session_id,
                turn_id=turn_id,
            )
            if semantic_chat and semantic_chat.get("kind") == "clarify":
                clarification = semantic_chat["clarification"]
                await _ws_send(
                    websocket,
                    "clarify",
                    session_id=session_id,
                    message=clarification.message,
                    clarification_kind=clarification.mode,
                    form=clarification.model_dump(),
                    fields=[field.model_dump() for field in clarification.fields],
                    pending_payload=_json_safe(semantic_chat.get("pending") or {}),
                    turn_id=semantic_chat.get("turn_id") or turn_id,
                    timestamp=_now_ts(),
                )
                continue

            if semantic_chat and semantic_chat.get("kind") == "chat":
                chat_response = semantic_chat["message"]
                session_state.setdefault("chat_history", []).append(
                    {"role": "user", "content": user_message or ""}
                )
                session_state["chat_history"].append(
                    {"role": "assistant", "content": chat_response}
                )
                if len(session_state["chat_history"]) > 20:
                    session_state["chat_history"] = session_state["chat_history"][-20:]
                await _ws_send(
                    websocket,
                    "assistant",
                    session_id=session_id,
                    message=chat_response,
                    plan=_public_plan_dict(semantic_chat.get("plan") or preliminary_plan),
                    turn_id=turn_id,
                    timestamp=_now_ts(),
                )
                continue

            if _plan_is_chat_only(preliminary_plan):
                chat_response = await _resolve_chat_response_async(
                    preliminary_plan,
                    user_message or "",
                    history=session_state.get("chat_history", []),
                )
                session_state.setdefault("chat_history", []).append(
                    {"role": "user", "content": user_message or ""}
                )
                session_state["chat_history"].append(
                    {"role": "assistant", "content": chat_response}
                )
                if len(session_state["chat_history"]) > 20:
                    session_state["chat_history"] = session_state["chat_history"][-20:]
                await _ws_send(websocket, "assistant", session_id=session_id,
                               message=chat_response,
                               plan=_public_plan_dict(preliminary_plan),
                               turn_id=turn_id,
                               timestamp=_now_ts())
                continue

            # FIX(M3): follow-up detection with ko_aliases
            message_lower = user_message.lower() if user_message else ""
            follow_up_keywords = [
                "homo", "lumo", "orbital", "esp", "charges", "dipole",
                "energy level", "에너지", "오비탈", "전하", "최적화", "같은 구조", "동일 구조",
            ]
            is_follow_up = any(kw in message_lower for kw in follow_up_keywords)
            detected_molecule = _detect_follow_up_molecule(user_message)
            has_molecule = detected_molecule is not None
            if has_molecule and not incoming.get("structure_query"):
                incoming["structure_query"] = detected_molecule
                incoming["structure_source"] = "user_input"

            if is_follow_up and not has_molecule and not incoming.get("structure_query") and not incoming.get("xyz") and not incoming.get("atom_spec"):
                continuation_state = load_conversation_state(session_id, manager=get_job_manager())
                last_structure = _safe_str(continuation_state.get("last_structure_query") or continuation_state.get("last_resolved_name"))
                last_artifact = dict(continuation_state.get("last_resolved_artifact") or {})
                if last_structure:
                    incoming["structure_query"] = last_structure
                    incoming["structure_source"] = "continuation"
                    if last_artifact.get("xyz") and not incoming.get("xyz"):
                        incoming["xyz"] = last_artifact.get("xyz")
                else:
                    stripped = user_message.strip() if user_message else ""
                    pure_keyword = stripped.lower() in {"homo", "lumo", "orbital", "esp", "charges", "dipole",
                                                         "에너지", "오비탈", "전하", "최적화", "구조", "energy"}
                    if pure_keyword:
                        await _ws_send(websocket, "assistant", session_id=session_id,
                                       message="어떤 분자를 분석할까요? 분자 이름이나 구조를 먼저 알려주세요. / Which molecule would you like to analyze?",
                                       turn_id=turn_id, timestamp=_now_ts())
                        continue

            try:
                plan = _build_validated_plan(user_message, incoming) if user_message else {}
            except Exception as exc:
                logger.warning("Plan generation failed: %s", exc)
                plan = {}

            # ── Chat intent: Gemini responded conversationally, no computation needed ──
            try:
                preflight = await _prepare_or_clarify(incoming, raw_message=user_message, session_id=session_id, turn_id=turn_id)
            except HTTPException as exc:
                msg = _safe_str(exc.detail, "Invalid request.")
                await _ws_send_error(websocket, message=msg, detail={"payload": incoming},
                                     status_code=exc.status_code, session_id=session_id, turn_id=turn_id)
                continue
            except Exception as exc:
                logger.warning("Payload preparation failed: %s", exc)
                await _ws_send_error(websocket, message=f"Structure resolution failed: {exc}",
                                     detail={"type": exc.__class__.__name__, "message": str(exc)},
                                     status_code=400, session_id=session_id, turn_id=turn_id)
                continue

            if preflight["requires_clarification"]:
                clarification = preflight["clarification"]
                await _ws_send(
                    websocket,
                    "clarify",
                    session_id=session_id,
                    message=clarification.message,
                    clarification_kind=clarification.mode,
                    form=clarification.model_dump(),
                    fields=[field.model_dump() for field in clarification.fields],
                    plan=_public_plan_dict(preflight.get("plan") or {}),
                    turn_id=preflight.get("turn_id") or turn_id,
                    timestamp=_now_ts(),
                )
                continue

            plan = preflight.get("plan") or plan
            prepared = preflight["prepared"]
            if auth_user:
                prepared["owner_username"] = auth_user["username"]
                prepared["owner_display_name"] = auth_user.get("display_name") or auth_user["username"]

            await _ws_send(websocket, "assistant", session_id=session_id,
                           message=_plan_status_message(plan, prepared),
                           plan=_public_plan_dict(plan),
                           payload_preview={
                               "job_type": prepared.get("job_type"),
                               "structure_query": prepared.get("structure_query"),
                               "method": prepared.get("method"),
                               "basis": prepared.get("basis"),
                               "orbital": prepared.get("orbital"),
                               "esp_preset": prepared.get("esp_preset"),
                               "advisor_focus_tab": prepared.get("advisor_focus_tab"),
                           },
                           turn_id=preflight.get("turn_id") or turn_id,
                           timestamp=_now_ts())

            manager = get_job_manager()
            try:
                submitted = _submit_or_reuse_job(prepared, manager=manager)
            except HTTPException as exc:
                quota = manager.quota_summary(
                    session_id=session_id,
                    owner_username=_safe_str((auth_user or {}).get("username")),
                )
                await _ws_send_error(
                    websocket,
                    message=_safe_str(exc.detail, "Job submission failed."),
                    detail={"payload_preview": {"job_type": prepared.get("job_type"), "structure_query": prepared.get("structure_query")}},
                    status_code=exc.status_code,
                    session_id=session_id,
                    quota=quota,
                    turn_id=preflight.get("turn_id") or turn_id,
                )
                continue
            except Exception as exc:
                logger.exception("Job submission failed.")
                await _ws_send_error(websocket, message="Job submission failed.",
                                     detail={"type": exc.__class__.__name__, "message": str(exc)},
                                     status_code=500, session_id=session_id, turn_id=preflight.get("turn_id") or turn_id)
                continue

            await _ws_send(websocket, "job_submitted", session_id=session_id, job=submitted, turn_id=preflight.get("turn_id") or turn_id, timestamp=_now_ts())
            try:
                await _stream_backend_job_until_terminal(websocket, job_id=submitted["job_id"], session_id=session_id, turn_id=preflight.get("turn_id") or turn_id)
            except Exception as exc:
                logger.warning("Job streaming failed: %s", exc)
                await _ws_send_error(websocket, message=f"Job execution failed: {exc}",
                                     detail={"type": exc.__class__.__name__, "message": str(exc)},
                                     status_code=500, session_id=session_id, turn_id=preflight.get("turn_id") or turn_id)

            # ── Multi-intent: detect additional intents and submit extra jobs ──
            primary_jt = _safe_str(prepared.get("job_type"))
            msg_lower = (user_message or "").lower()
            extra_intents = []
            has_orbital_kw = bool(re.search(r"\b(homo|lumo|orbital|mo)\b|오비탈", msg_lower, re.IGNORECASE))
            has_esp_kw = bool(re.search(r"\b(esp|electrostatic)\b|정전기|전위", msg_lower, re.IGNORECASE))
            has_opt_kw = bool(re.search(r"\b(opt|optimize|optimization)\b|최적화", msg_lower, re.IGNORECASE))

            if has_orbital_kw and primary_jt not in ("orbital_preview", "analyze"):
                extra_intents.append(("orbital_preview", "orbital"))
            if has_esp_kw and primary_jt not in ("esp_map", "analyze"):
                extra_intents.append(("esp_map", "esp"))
            if has_opt_kw and primary_jt not in ("geometry_optimization", "analyze"):
                extra_intents.append(("geometry_optimization", "geometry"))

            for extra_jt, extra_tab in extra_intents:
                extra_payload = dict(prepared)
                extra_payload["job_type"] = extra_jt
                extra_payload["advisor_focus_tab"] = extra_tab
                extra_payload.pop("job_id", None)
                try:
                    extra_sub = _submit_or_reuse_job(extra_payload, manager=manager)
                    await _ws_send(websocket, "job_submitted", session_id=session_id,
                                   job=extra_sub, turn_id=preflight.get("turn_id") or turn_id, timestamp=_now_ts())
                    await _stream_backend_job_until_terminal(
                        websocket, job_id=extra_sub["job_id"], session_id=session_id, turn_id=preflight.get("turn_id") or turn_id)
                except Exception as exc:
                    logger.warning("Extra job (%s) failed: %s", extra_jt, exc)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as exc:
        logger.exception("Unhandled websocket error.")
        try:
            await _ws_send_error(websocket, message="Unhandled websocket error.",
                                 detail={"type": exc.__class__.__name__, "message": str(exc)},
                                 status_code=500, session_id=default_session_id)
        except Exception:
            pass
    finally:
        # FIX(M3): cleanup keepalive task
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass


__all__ = ["router"]
