"""Compute routes — job submission, status, results.

# FIX(M2): 가짜 resolver 삭제, structure_resolver.resolve() 교체,
#          이온쌍 감지 → ion_pair_handler 위임, LRU 캐시, 이중 언어 에러
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, Header, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner
from qcviz_mcp.llm.normalizer import (
    analyze_query_routing,
    analyze_structure_input,
    build_structure_hypotheses,
    extract_structure_candidate,
    normalize_user_text,
)
from qcviz_mcp.observability import metrics, track_operation
from qcviz_mcp.web.auth_store import get_auth_user
from qcviz_mcp.web.job_backend import build_job_manager, get_job_backend_runtime
from qcviz_mcp.web.conversation_state import load_conversation_state, update_conversation_state_from_execution
from qcviz_mcp.web.session_auth import bootstrap_or_validate_session, validate_session_token
from qcviz_mcp.web.result_explainer import build_result_explanation
from qcviz_mcp.web.runtime_info import runtime_debug_info

# FIX(M2): 새 서비스 모듈 import
try:
    from qcviz_mcp.services.structure_resolver import StructureResolver, StructureResult
    from qcviz_mcp.services.ion_pair_handler import is_ion_pair, resolve_ion_pair, IonPairResult, expand_alias
    from qcviz_mcp.services.molchat_client import MolChatClient
    from qcviz_mcp.services.pubchem_client import PubChemClient
    from qcviz_mcp.services.ko_aliases import translate as ko_translate
except ImportError as _imp_err:
    logging.getLogger(__name__).warning("services import failed: %s", _imp_err)
    StructureResolver = None  # type: ignore
    StructureResult = None  # type: ignore

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:
    QCVizAgent = None  # type: ignore

try:
    from qcviz_mcp.web.advisor_flow import (
        apply_preset_to_runner_kwargs,
        enrich_result_with_advisor,
        prepare_advisor_plan_from_geometry,
        summarize_advisor_payload,
    )
except Exception as _advisor_imp_err:
    logging.getLogger(__name__).warning("advisor integration import failed: %s", _advisor_imp_err)
    apply_preset_to_runner_kwargs = None  # type: ignore
    enrich_result_with_advisor = None  # type: ignore
    prepare_advisor_plan_from_geometry = None  # type: ignore
    summarize_advisor_payload = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])

# ── Intent / job type mappings ────────────────────────────────

INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "analyze": "analyze",
    "full_analysis": "analyze",
    "single_point": "single_point",
    "energy": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "optimize": "geometry_optimization",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_ALIASES: Dict[str, str] = {
    "analyze": "analyze", "analysis": "analyze", "full_analysis": "analyze",
    "singlepoint": "single_point", "single_point": "single_point", "sp": "single_point",
    "geometry": "geometry_analysis", "geometry_analysis": "geometry_analysis", "geom": "geometry_analysis",
    "charge": "partial_charges", "charges": "partial_charges", "partial_charges": "partial_charges",
    "mulliken": "partial_charges",
    "orbital": "orbital_preview", "orbital_preview": "orbital_preview", "mo": "orbital_preview",
    "esp": "esp_map", "esp_map": "esp_map", "electrostatic_potential": "esp_map",
    "opt": "geometry_optimization", "optimize": "geometry_optimization",
    "optimization": "geometry_optimization", "geometry_optimization": "geometry_optimization",
    "resolve": "resolve_structure", "resolve_structure": "resolve_structure", "structure": "resolve_structure",
}

JOB_TYPE_TO_RUNNER: Dict[str, str] = {
    "analyze": "run_analyze",
    "single_point": "run_single_point",
    "geometry_analysis": "run_geometry_analysis",
    "partial_charges": "run_partial_charges",
    "orbital_preview": "run_orbital_preview",
    "esp_map": "run_esp_map",
    "geometry_optimization": "run_geometry_optimization",
    "resolve_structure": "run_resolve_structure",
}

TERMINAL_SUCCESS = {"completed"}
TERMINAL_FAILURE = {"failed", "error"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE

DEFAULT_POLL_SECONDS = float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25"))
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "1"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

# FIX(M2): LRU structure resolution cache
_STRUCTURE_CACHE: OrderedDict[str, Any] = OrderedDict()
_STRUCTURE_CACHE_LOCK = threading.Lock()
_STRUCTURE_CACHE_MAX = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))

# FIX(M2): Singleton resolver instances
_resolver_instance: Optional[Any] = None
_resolver_lock = threading.Lock()


def _quota_limit_from_env(name: str, default: int) -> int:
    raw = _safe_str(os.getenv(name, str(default)))
    try:
        value = int(raw)
    except Exception:
        return default
    return max(0, value)


def _max_active_jobs_per_session() -> int:
    return _quota_limit_from_env("QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION", 2)


def _max_active_jobs_per_user() -> int:
    return _quota_limit_from_env("QCVIZ_MAX_ACTIVE_JOBS_PER_USER", 3)


def _get_resolver() -> Any:
    """Get or create singleton StructureResolver."""
    global _resolver_instance
    if _resolver_instance is not None:
        return _resolver_instance
    with _resolver_lock:
        if _resolver_instance is None and StructureResolver is not None:
            _resolver_instance = StructureResolver()
    return _resolver_instance


def _structure_cache_get(key: str) -> Optional[Any]:
    with _STRUCTURE_CACHE_LOCK:
        if key in _STRUCTURE_CACHE:
            _STRUCTURE_CACHE.move_to_end(key)
            return _STRUCTURE_CACHE[key]
    return None


def _structure_cache_put(key: str, value: Any) -> None:
    with _STRUCTURE_CACHE_LOCK:
        if key in _STRUCTURE_CACHE:
            _STRUCTURE_CACHE.move_to_end(key)
        _STRUCTURE_CACHE[key] = value
        while len(_STRUCTURE_CACHE) > _STRUCTURE_CACHE_MAX:
            _STRUCTURE_CACHE.popitem(last=False)


# ── Regex patterns for heuristic extraction ───────────────────

_METHOD_PAT = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|bp86|blyp|mp2|ccsd)\b",
    re.IGNORECASE,
)
_BASIS_PAT = re.compile(
    r"\b(sto-?3g|3-21g|6-31g\*{0,2}|6-31g\(d(?:,p)?\)|6-311g\*{0,2}|def2-?svp|def2-?tzvp|cc-pv[dt]z|aug-cc-pv[dt]z)\b",
    re.IGNORECASE,
)
_CHARGE_PAT = re.compile(r"(?:charge|전하)\s*[:=]?\s*([+-]?\d+)", re.IGNORECASE)
_MULT_PAT = re.compile(r"(?:multiplicity|spin multiplicity|다중도)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_ORBITAL_PAT = re.compile(
    r"\b(homo(?:\s*-\s*\d+)?|lumo(?:\s*\+\s*\d+)?|mo\s*\d+)\b",
    re.IGNORECASE,
)
_ESP_PRESET_PAT = re.compile(
    r"\b(acs|rsc|nature|spectral|inferno|viridis|rwb|bwr|greyscale|grayscale|high[_ -]?contrast)\b",
    re.IGNORECASE,
)
_BASIS_UPGRADE_ORDER = [
    "sto-3g",
    "3-21g",
    "6-31g",
    "6-31g*",
    "6-31g**",
    "6-311g",
    "6-311g*",
    "6-311g**",
    "def2-svp",
    "def2-tzvp",
    "cc-pvdz",
    "cc-pvtz",
    "aug-cc-pvdz",
]
_FOLLOW_UP_PLACEHOLDER_QUERY_RE = re.compile(
    r"^(?:this|that|it|same structure|same molecule|basis(?:\s+만\s+더\s+키워봐)?|"
    r"이걸|그걸|이거|저거|같은 구조|동일 구조)$",
    re.IGNORECASE,
)
_FOLLOW_UP_ACTION_CUE_RE = re.compile(
    r"궁금|알려줘|뭐야|보여줘|해줘|그려줘|추가|다시|"
    r"also|too|again|more|next|ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자|도\b",
    re.IGNORECASE,
)


# ── Utility functions ────────────────────────────────────────

def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default


def _job_session_id(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str(_extract_session_id(payload or {}))


def _job_session_token(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str(_extract_session_token(payload or {}))


def _job_owner_username(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str((payload or {}).get("owner_username"))


def _new_session_id() -> str:
    return f"qcviz-{uuid.uuid4().hex}"


def _ensure_payload_session_id(payload: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    out = dict(payload or {})
    session_id = _job_session_id(out)
    if not session_id:
        session_id = _new_session_id()
        out["session_id"] = session_id
    return out


def _resolve_request_session_token(
    session_token: Optional[str] = None,
    header_session_token: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> str:
    return (
        _safe_str(session_token)
        or _safe_str(header_session_token)
        or _job_session_token(payload)
    )


def _resolve_request_auth_token(
    auth_token: Optional[str] = None,
    header_auth_token: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> str:
    return (
        _safe_str(auth_token)
        or _safe_str(header_auth_token)
        or _extract_auth_token(payload or {})
    )


def _resolve_request_auth_user(
    auth_token: Optional[str] = None,
    header_auth_token: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    token = _resolve_request_auth_token(auth_token, header_auth_token, payload)
    if not token:
        return None
    user = get_auth_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid auth token.")
    return user


def _bootstrap_payload_session(
    payload: Optional[Mapping[str, Any]],
    *,
    header_session_id: Optional[str] = None,
    header_session_token: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    out = dict(payload or {})
    requested_session_id = _resolve_request_session_id(out.get("session_id"), header_session_id, out)
    requested_session_token = _resolve_request_session_token(
        out.get("session_token"),
        header_session_token,
        out,
    )
    session_meta = bootstrap_or_validate_session(
        requested_session_id or None,
        requested_session_token or None,
        allow_new=True,
    )
    out["session_id"] = session_meta["session_id"]
    out.pop("session_token", None)
    return out, session_meta


def _resolve_request_session_id(
    session_id: Optional[str] = None,
    header_session_id: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> str:
    return (
        _safe_str(session_id)
        or _safe_str(header_session_id)
        or _job_session_id(payload)
    )


def _assert_session_access(snap: Optional[Mapping[str, Any]], request_session_id: str) -> Dict[str, Any]:
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    owner_session_id = _safe_str(snap.get("session_id"))
    if not request_session_id:
        raise HTTPException(status_code=403, detail="session_id is required for this job.")
    if owner_session_id and owner_session_id != request_session_id:
        raise HTTPException(status_code=403, detail="This job belongs to a different session.")
    return dict(snap)


def _assert_session_token_access(
    snap: Optional[Mapping[str, Any]],
    request_session_id: str,
    request_session_token: str,
) -> Dict[str, Any]:
    job = _assert_session_access(snap, request_session_id)
    validate_session_token(request_session_id, request_session_token)
    return job


def _assert_job_access(
    snap: Optional[Mapping[str, Any]],
    *,
    request_session_id: str,
    request_session_token: str,
    auth_user: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    owner_username = _safe_str(snap.get("owner_username"))
    if auth_user and owner_username and _safe_str(auth_user.get("username")) == owner_username:
        return dict(snap)
    return _assert_session_token_access(snap, request_session_id, request_session_token)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    try:
        import numpy as np
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            return None if not math.isfinite(v) else v
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, np.ndarray):
            return _json_safe(value.tolist())
    except ImportError:
        pass
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _public_plan_dict(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    return {
        "normalized_text": out.get("normalized_text"),
        "intent": out.get("intent"),
        "job_type": out.get("job_type"),
        "query_kind": out.get("query_kind"),
        "semantic_grounding_needed": out.get("semantic_grounding_needed"),
        "unknown_acronyms": out.get("unknown_acronyms"),
        "confidence": out.get("confidence"),
        "confidence_band": out.get("confidence_band"),
        "provider": out.get("provider"),
        "fallback_reason": out.get("fallback_reason"),
        "notes": out.get("notes"),
        "reasoning_notes": out.get("reasoning_notes"),
        "structure_query": out.get("structure_query"),
        "structure_query_candidates": out.get("structure_query_candidates"),
        "formula_mentions": out.get("formula_mentions"),
        "alias_mentions": out.get("alias_mentions"),
        "canonical_candidates": out.get("canonical_candidates"),
        "raw_input": out.get("raw_input"),
        "mixed_input": out.get("mixed_input"),
        "composition_kind": out.get("composition_kind"),
        "charge_hint": out.get("charge_hint"),
        "structures": out.get("structures"),
        "mentioned_molecules": out.get("mentioned_molecules"),
        "target_scope": out.get("target_scope"),
        "selection_mode": out.get("selection_mode"),
        "selection_hint": out.get("selection_hint"),
        "selected_molecules": out.get("selected_molecules"),
        "analysis_bundle": out.get("analysis_bundle"),
        "batch_request": out.get("batch_request"),
        "batch_size": out.get("batch_size"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
        "follow_up_mode": out.get("follow_up_mode"),
        "clarification_kind": out.get("clarification_kind"),
        "missing_slots": out.get("missing_slots"),
        "needs_clarification": out.get("needs_clarification"),
        "chat_response": out.get("chat_response"),
    }


def _normalize_text_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s가-힣+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "user_message", "text", "prompt", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_session_id(payload: Mapping[str, Any]) -> str:
    for key in ("session_id", "conversation_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_session_token(payload: Mapping[str, Any]) -> str:
    for key in ("session_token", "client_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_auth_token(payload: Mapping[str, Any]) -> str:
    for key in ("auth_token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_job_type(job_type: Optional[str], intent: Optional[str] = None) -> str:
    jt = _normalize_text_token(job_type).replace(" ", "_")
    if jt in JOB_TYPE_ALIASES:
        return JOB_TYPE_ALIASES[jt]
    intent_key = _normalize_text_token(intent).replace(" ", "_")
    if intent_key in INTENT_TO_JOB_TYPE:
        return INTENT_TO_JOB_TYPE[intent_key]
    return "analyze"


def _normalize_esp_preset(preset: Optional[str]) -> str:
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    if token == "grayscale":
        token = "greyscale"
    if token == "high-contrast":
        token = "high_contrast"
    if token in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}):
        return token
    for key, meta in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}).items():
        aliases = [_normalize_text_token(x).replace(" ", "_") for x in meta.get("aliases", [])]
        if token == key or token in aliases:
            return key
    return "acs"


def _multiplicity_to_spin(multiplicity: Any) -> int:
    mult = _safe_int(multiplicity, 1) or 1
    return max(0, mult - 1)


def _advisor_intent_name(payload: Mapping[str, Any]) -> str:
    job_type = _safe_str(payload.get("job_type") or payload.get("planner_intent") or payload.get("intent")).lower()
    mapping = {
        "geometry_optimization": "geometry_opt",
        "single_point": "single_point",
        "esp_map": "esp",
        "partial_charges": "partial_charges",
        "orbital_preview": "orbital",
        "geometry_analysis": "validate",
        "resolve_structure": "resolve",
        "analyze": "analyze",
    }
    return mapping.get(job_type, "single_point")


def _apply_advisor_enrichment(
    result: Mapping[str, Any],
    prepared: Mapping[str, Any],
    *,
    advisor_plan: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    out = dict(result or {})
    query = _safe_str(
        prepared.get("structure_query")
        or out.get("structure_query")
        or out.get("structure_name")
        or _extract_message(prepared)
        or "molecule"
    )
    intent_name = _advisor_intent_name(prepared)
    advisor_enabled = bool(prepared.get("advisor", True))

    with track_operation("web.advisor_enrichment", parameters={"intent_name": intent_name, "advisor_enabled": advisor_enabled}) as obs:
        if advisor_enabled and callable(enrich_result_with_advisor):
            try:
                advisor_payload = enrich_result_with_advisor(
                    query=query,
                    intent_name=intent_name,
                    result=out,
                    preset_bundle=dict(advisor_plan or {}) if advisor_plan else None,
                )
                out["advisor"] = _json_safe(advisor_payload)
                if callable(summarize_advisor_payload):
                    out["advisor_summary"] = _json_safe(summarize_advisor_payload(advisor_payload))
                obs.metrics.update({"advisor_status": "success"})
            except Exception as exc:
                obs.metrics.update({"advisor_status": "error"})
                logger.warning("Advisor enrichment failed: %s", exc)
                warnings = list(out.get("warnings") or [])
                warnings.append(f"Advisor enrichment failed: {exc}")
                out["warnings"] = warnings

        try:
            out["explanation"] = _json_safe(
                build_result_explanation(
                    query=query,
                    intent_name=intent_name,
                    result=out,
                    advisor=out.get("advisor") if isinstance(out.get("advisor"), Mapping) else None,
                )
            )
            if isinstance(out.get("explanation"), Mapping):
                out.setdefault("human_summary", _safe_str(out["explanation"].get("summary")))
            obs.metrics.update({"has_explanation": bool(out.get("explanation"))})
        except Exception as exc:
            obs.metrics.update({"has_explanation": False})
            logger.warning("Result explanation failed: %s", exc)
            warnings = list(out.get("warnings") or [])
            warnings.append(f"Result explanation failed: {exc}")
            out["warnings"] = warnings

    return _json_safe(out)


def _build_structure_preview_result(
    prepared: Mapping[str, Any],
    *,
    extra_warnings: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    xyz = _safe_str(prepared.get("xyz"))
    if not xyz:
        return None

    atom_spec = _safe_str(prepared.get("atom_spec")) or _safe_str(pyscf_runner._strip_xyz_header(xyz))
    preview = {
        "success": True,
        "preview": True,
        "job_type": _normalize_job_type(prepared.get("job_type"), prepared.get("planner_intent")),
        "structure_query": prepared.get("structure_query") or prepared.get("structure_name") or "custom",
        "structure_name": prepared.get("structure_query") or prepared.get("structure_name") or "custom",
        "atom_spec": atom_spec,
        "xyz": xyz,
        "method": prepared.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        "basis": prepared.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        "charge": _safe_int(prepared.get("charge"), 0) or 0,
        "multiplicity": _safe_int(prepared.get("multiplicity"), 1) or 1,
        "warnings": list(extra_warnings or []),
        "advisor_focus_tab": "summary",
        "visualization": {
            "xyz": xyz,
            "molecule_xyz": xyz,
            "defaults": {
                "style": "stick",
                "labels": False,
                "orbital_iso": 0.050,
                "orbital_opacity": 0.85,
                "esp_density_iso": 0.001,
                "esp_opacity": 0.90,
                "focus_tab": "summary",
            },
        },
    }
    return _normalize_result_contract(preview, prepared)


def _web_metrics_summary() -> Dict[str, Any]:
    summary = metrics.get_summary()
    counters = dict(summary.get("counters") or {})

    def _counter(name: str, status: str) -> int:
        return int(counters.get(f"{name}.{status}", 0) or 0)

    planner_success = _counter("web.plan_message", "success")
    planner_error = _counter("web.plan_message", "error")
    compute_success = _counter("web.compute", "success")
    compute_error = _counter("web.compute", "error")
    resolver_success = _counter("web.resolve_structure", "success")
    resolver_error = _counter("web.resolve_structure", "error")
    advisor_success = _counter("web.advisor_enrichment", "success")
    advisor_error = _counter("web.advisor_enrichment", "error")

    def _ratio(ok: int, fail: int) -> Optional[float]:
        total = ok + fail
        return round(ok / total, 4) if total else None

    summary["web"] = {
        "planner_success_ratio": _ratio(planner_success, planner_error),
        "compute_success_ratio": _ratio(compute_success, compute_error),
        "resolver_success_ratio": _ratio(resolver_success, resolver_error),
        "advisor_success_ratio": _ratio(advisor_success, advisor_error),
        "fallback_ratio_estimate": (
            round(planner_error / (planner_success + planner_error), 4)
            if (planner_success + planner_error) else None
        ),
    }
    return summary


def _extract_xyz_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    raw = str(text).strip()
    fence = re.search(r"```(?:xyz)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fence:
        block = fence.group(1).strip()
        if block:
            return block
    if "\n" not in raw:
        return None
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    atom_line = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
    if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 3:
        candidate = "\n".join(lines)
        body = lines[2:]
        if body and all(atom_line.match(x.strip()) for x in body):
            return candidate
    atom_lines = [ln for ln in lines if atom_line.match(ln.strip())]
    if len(atom_lines) >= 1 and len(atom_lines) == len(lines):
        return "\n".join(lines)
    return None


# FIX(M2): async structure resolution via new resolver
async def _resolve_structure_async(query: str) -> Dict[str, Any]:
    """Resolve structure query using the new StructureResolver pipeline.

    Returns dict with keys: xyz, smiles, cid, name, source, sdf, molecular_weight.
    """
    cache_key = query.strip().lower()
    cached = _structure_cache_get(cache_key)
    if cached:
        with track_operation("web.resolve_structure", parameters={"query": query, "cache_hit": True}) as obs:
            obs.metrics.update({"source": cached.get("source"), "used_cache": True})
            return cached

    resolver = _get_resolver()
    if resolver is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "구조 해석 서비스를 초기화할 수 없습니다 / "
                "Structure resolver service unavailable"
            ),
        )

    with track_operation("web.resolve_structure", parameters={"query": query}) as obs:
        try:
            result = await resolver.resolve(query)
            out = {
                "xyz": result.xyz,
                "smiles": result.smiles,
                "cid": result.cid,
                "name": result.name or query,
                "source": result.source,
                "sdf": result.sdf,
                "molecular_weight": result.molecular_weight,
                "query_plan": getattr(result, "query_plan", None),
            }
            obs.metrics.update({"source": out.get("source"), "used_cache": False})
            _structure_cache_put(cache_key, out)
            return out
        except ValueError as e:
            obs.metrics.update({"status_code": 400})
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )
        except Exception as e:
            obs.metrics.update({"status_code": 502})
            logger.exception("Structure resolution failed for: %s", query)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"구조 해석 중 오류 발생: {e} / "
                    f"Error during structure resolution: {e}"
                ),
            )


# FIX(M2): async ion pair resolution
async def _resolve_ion_pair_async(structures: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve ion pair via ion_pair_handler."""
    resolver = _get_resolver()
    if resolver is None:
        raise HTTPException(status_code=500, detail="Structure resolver unavailable")

    try:
        ion_result = await resolve_ion_pair(
            structures=structures,
            molchat=resolver.molchat,
            pubchem=resolver.pubchem,
            offset=float(os.getenv("ION_OFFSET_ANGSTROM", "5.0")),
        )
        return {
            "xyz": ion_result.xyz,
            "total_charge": ion_result.total_charge,
            "smiles_list": ion_result.smiles_list,
            "names": ion_result.names,
            "source": ion_result.source,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Ion pair resolution failed")
        raise HTTPException(
            status_code=502,
            detail=f"이온쌍 해석 실패: {e} / Ion pair resolution failed: {e}",
        )


def _heuristic_plan(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Heuristic fallback planner (no LLM)."""
    payload = payload or {}
    text = message or _extract_message(payload)
    normalization = normalize_user_text(text)
    normalized = _normalize_text_token(normalization.get("normalized_text") or text)
    routing = analyze_query_routing(
        text,
        structure_analysis=analyze_structure_input(text),
    )

    intent = "analyze"
    focus = "summary"

    if routing.get("query_kind") == "chat_only":
        acronyms = [str(item).strip() for item in list(routing.get("unknown_acronyms") or []) if _safe_str(item)]
        if acronyms:
            token = acronyms[0]
            chat_response = (
                f"`{token}` looks like an abbreviation, and abbreviations can be ambiguous in chemistry.\n\n"
                f"- If you want a calculation, tell me the full compound name or SMILES.\n"
                f"- If you want an explanation, tell me which compound you mean."
            )
        else:
            chat_response = (
                "This looks more like a chemistry question than an explicit calculation request.\n\n"
                "If you want a calculation, tell me the molecule and the task together."
            )
        return {
            "intent": "chat",
            "job_type": "chat",
            "query_kind": routing.get("query_kind"),
            "semantic_grounding_needed": bool(routing.get("semantic_grounding_needed")),
            "unknown_acronyms": list(routing.get("unknown_acronyms") or []),
            "confidence": 0.82,
            "confidence_band": "high",
            "provider": "heuristic",
            "notes": "Heuristic chat-only planner.",
            "reasoning_notes": list(routing.get("reasoning_notes") or []),
            "normalized_text": normalization.get("normalized_text", text),
            "chat_response": chat_response,
            "needs_clarification": False,
            "missing_slots": [],
            "structure_query": None,
            "structure_query_candidates": [],
            "canonical_candidates": [],
        }

    if re.search(r"\b(homo|lumo|orbital|mo)\b|오비탈", normalized, re.IGNORECASE):
        intent = "orbital"
        focus = "orbital"
    elif re.search(r"\b(esp|electrostatic)\b|정전기|전위", normalized, re.IGNORECASE):
        intent = "esp"
        focus = "esp"
    elif re.search(r"\b(charge|charges|mulliken)\b|전하", normalized, re.IGNORECASE):
        intent = "charges"
        focus = "charges"
    elif re.search(r"\b(opt|optimize|optimization)\b|최적화", normalized, re.IGNORECASE):
        intent = "optimization"
        focus = "geometry"
    elif re.search(r"\b(geometry|bond|angle|dihedral)\b|구조|결합", normalized, re.IGNORECASE):
        intent = "geometry"
        focus = "geometry"
    elif re.search(r"\b(energy|single point|singlepoint)\b|에너지", normalized, re.IGNORECASE):
        intent = "single_point"
        focus = "summary"

    method = None
    basis = None
    charge = None
    multiplicity = None
    orbital = None
    esp_preset = None

    m_method = _METHOD_PAT.search(text)
    if m_method:
        method = m_method.group(1)
    m_basis = _BASIS_PAT.search(text)
    if m_basis:
        basis = m_basis.group(1)
    m_charge = _CHARGE_PAT.search(text)
    if m_charge:
        charge = _safe_int(m_charge.group(1))
    m_mult = _MULT_PAT.search(text)
    if m_mult:
        multiplicity = _safe_int(m_mult.group(1))
    m_orb = _ORBITAL_PAT.search(text)
    if m_orb:
        orbital = m_orb.group(1).upper().replace(" ", "")
    m_preset = _ESP_PRESET_PAT.search(text)
    if m_preset:
        esp_preset = _normalize_esp_preset(m_preset.group(1))

    job_type = _normalize_job_type(payload.get("job_type"), intent)
    structure_query = extract_structure_candidate(text)
    if normalization.get("semantic_descriptor"):
        raw_variants = {
            str(item).strip().lower()
            for item in (
                text,
                normalization.get("normalized_text"),
                normalization.get("translated_text"),
            )
            if str(item or "").strip()
        }
        if not structure_query or structure_query.strip().lower() in raw_variants:
            structure_query = None
    if routing.get("query_kind") == "grounding_required" and routing.get("unknown_acronyms"):
        structure_query = None
    structure_candidates = list(normalization.get("canonical_candidates") or normalization.get("candidate_queries") or [])
    mentioned_molecules = list(normalization.get("mentioned_molecules") or [])
    selected_molecules = [str(item).strip() for item in (normalization.get("selected_molecules") or []) if _safe_str(item)]
    analysis_bundle = [str(item).strip() for item in (normalization.get("analysis_bundle") or []) if _safe_str(item)]
    target_scope = _safe_str(normalization.get("target_scope")) or None
    selection_mode = _safe_str(normalization.get("selection_mode")) or None
    selection_hint = _safe_str(normalization.get("selection_hint")) or None
    inferred_batch_size = len(selected_molecules) or len(mentioned_molecules)
    batch_request = bool(normalization.get("batch_request")) or len(selected_molecules) > 1
    structures = list(normalization.get("structures") or []) or None
    composition_kind = normalization.get("composition_kind")
    charge_hint = normalization.get("charge_hint")
    if charge is None and charge_hint is not None:
        charge = _safe_int(charge_hint)
    follow_up_mode = normalization.get("follow_up_mode")
    clarification_kind = None
    if normalization.get("follow_up_job_type"):
        job_type = _normalize_job_type(normalization.get("follow_up_job_type"), normalization.get("follow_up_job_type"))
    if not orbital and normalization.get("follow_up_orbital"):
        orbital = _safe_str(normalization.get("follow_up_orbital"))
    missing_slots: List[str] = []
    needs_clarification = False

    if job_type != "resolve_structure" and not structure_query and not structures:
        missing_slots.append("structure_query")
        needs_clarification = True
        if routing.get("query_kind") == "grounding_required" or normalization.get("semantic_descriptor"):
            clarification_kind = "semantic_grounding"
        else:
            clarification_kind = "continuation_targeting" if normalization.get("follow_up_requires_context") else "discovery"
    if job_type == "orbital_preview" and not orbital:
        missing_slots.append("orbital")
        needs_clarification = True
        clarification_kind = clarification_kind or "parameter_completion"

    return {
        "intent": intent,
        "confidence": 0.55,
        "confidence_band": "medium",
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "query_kind": routing.get("query_kind"),
        "semantic_grounding_needed": bool(routing.get("semantic_grounding_needed")),
        "unknown_acronyms": list(routing.get("unknown_acronyms") or []),
        "normalized_text": normalization.get("normalized_text", text),
        "structure_query": structure_query,
        "structure_query_candidates": structure_candidates,
        "formula_mentions": list(normalization.get("formula_mentions") or []),
        "alias_mentions": list(normalization.get("alias_mentions") or []),
        "canonical_candidates": list(normalization.get("canonical_candidates") or []),
        "raw_input": normalization.get("raw_input"),
        "mixed_input": bool(normalization.get("mixed_input")),
        "mentioned_molecules": mentioned_molecules,
        "target_scope": target_scope,
        "selection_mode": selection_mode,
        "selection_hint": selection_hint,
        "selected_molecules": selected_molecules,
        "analysis_bundle": analysis_bundle,
        "batch_request": batch_request,
        "batch_size": inferred_batch_size,
        "composition_kind": composition_kind,
        "charge_hint": charge_hint,
        "structures": structures,
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
        "follow_up_mode": follow_up_mode,
        "clarification_kind": clarification_kind,
        "missing_slots": missing_slots,
        "needs_clarification": needs_clarification,
    }


@lru_cache(maxsize=1)
def get_qcviz_agent():
    if QCVizAgent is None:
        return None
    try:
        return QCVizAgent()
    except Exception as exc:
        logger.warning("QCVizAgent initialization failed: %s", exc)
        return None


def _coerce_plan_to_dict(plan_obj: Any) -> Dict[str, Any]:
    if plan_obj is None:
        return {}
    if isinstance(plan_obj, Mapping):
        return dict(plan_obj)
    out: Dict[str, Any] = {}
    for key in (
        "normalized_text", "intent", "confidence", "confidence_band", "provider",
        "fallback_reason", "notes", "reasoning_notes", "job_type",
        "query_kind", "semantic_grounding_needed", "unknown_acronyms", "chat_response",
        "structure_query", "structure_query_candidates", "formula_mentions",
        "alias_mentions", "canonical_candidates", "raw_input", "mixed_input",
        "composition_kind", "charge_hint", "follow_up_mode", "clarification_kind",
        "structures", "method", "basis", "charge",
        "multiplicity", "orbital", "esp_preset", "advisor_focus_tab",
        "missing_slots", "needs_clarification",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out


def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    message_normalization = normalize_user_text(message or "")

    def _enrich_plan(plan_dict: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(plan_dict, dict):
            return {}
        enriched = dict(plan_dict)
        for key in (
            "query_kind",
            "chat_only",
            "semantic_grounding_needed",
            "question_like",
            "explicit_compute_action",
            "unknown_acronyms",
            "structure_query_candidates",
            "formula_mentions",
            "alias_mentions",
            "canonical_candidates",
            "raw_input",
            "mixed_input",
            "structures",
            "composition_kind",
            "charge_hint",
            "follow_up_mode",
            "mentioned_molecules",
            "target_scope",
            "selection_mode",
            "selection_hint",
            "selected_molecules",
            "analysis_bundle",
            "batch_request",
            "batch_size",
        ):
            if key not in enriched and message_normalization.get(key) not in (None, [], ""):
                enriched[key] = message_normalization.get(key)
        if "clarification_kind" not in enriched and message_normalization.get("follow_up_requires_context"):
            enriched["clarification_kind"] = "continuation_targeting"
        if message_normalization.get("query_kind") == "chat_only":
            enriched["intent"] = "chat"
            enriched["job_type"] = "chat"
            enriched["structure_query"] = None
            enriched["structure_query_candidates"] = [
                item
                for item in list(enriched.get("structure_query_candidates") or [])
                if _safe_str(item) and _safe_str(item).lower() != _safe_str(message_normalization.get("raw_input")).lower()
            ]
            enriched["canonical_candidates"] = [
                item
                for item in list(enriched.get("canonical_candidates") or [])
                if _safe_str(item) and _safe_str(item).lower() != _safe_str(message_normalization.get("raw_input")).lower()
            ]
            enriched["missing_slots"] = []
            enriched["needs_clarification"] = False
            enriched["clarification_kind"] = None
        if message_normalization.get("query_kind") == "grounding_required":
            raw_variants = {
                _safe_str(item).lower()
                for item in (
                    message,
                    message_normalization.get("raw_input"),
                    message_normalization.get("normalized_text"),
                )
                if _safe_str(item)
            }
            structure_query = _safe_str(enriched.get("structure_query"))
            if structure_query and structure_query.lower() in raw_variants:
                enriched["structure_query"] = None
            if not _safe_str(enriched.get("clarification_kind")):
                enriched["clarification_kind"] = "semantic_grounding"
            if not _safe_str(enriched.get("structure_query")):
                missing_slots = [str(item).strip() for item in list(enriched.get("missing_slots") or []) if str(item).strip()]
                if "structure_query" not in missing_slots:
                    missing_slots.append("structure_query")
                enriched["missing_slots"] = missing_slots
                enriched["needs_clarification"] = True
        if message_normalization.get("mixed_input") and message_normalization.get("canonical_candidates"):
            primary = _safe_str((message_normalization.get("canonical_candidates") or [None])[0])
            if primary and _safe_str(enriched.get("structure_query")) in {
                _safe_str(message_normalization.get("raw_input")),
                "",
            }:
                enriched["structure_query"] = primary
        return enriched

    agent = get_qcviz_agent()
    with track_operation("web.plan_message", parameters={"message": message[:120] if message else ""}) as obs:
        if agent is not None:
            try:
                if hasattr(agent, "plan") and callable(agent.plan):
                    planned = _enrich_plan(_coerce_plan_to_dict(agent.plan(message)))
                    obs.metrics.update(
                        {
                            "provider": planned.get("provider"),
                            "needs_clarification": bool(planned.get("needs_clarification")),
                            "fallback_reason": planned.get("fallback_reason"),
                        }
                    )
                    return planned
            except Exception as exc:
                obs.metrics.update({"fallback_reason": str(exc)})
                logger.warning("Planner invocation failed; heuristic fallback: %s", exc)
        planned = _enrich_plan(_heuristic_plan(message, payload=payload))
        obs.metrics.update(
            {
                "provider": planned.get("provider"),
                "needs_clarification": bool(planned.get("needs_clarification")),
                "fallback_reason": planned.get("fallback_reason"),
            }
        )
        return planned


def _upgrade_basis(basis: Optional[str]) -> Optional[str]:
    token = _safe_str(basis).lower()
    if not token:
        return None
    if token in _BASIS_UPGRADE_ORDER:
        idx = _BASIS_UPGRADE_ORDER.index(token)
        return _BASIS_UPGRADE_ORDER[min(idx + 1, len(_BASIS_UPGRADE_ORDER) - 1)]
    if token == "def2svp":
        return "def2-tzvp"
    if token == "def2tzvp":
        return "def2-tzvp"
    return "def2-tzvp"


def _explicit_structure_from_text(text: str) -> Optional[str]:
    raw = _safe_str(text)
    if not raw:
        return None
    normalization = normalize_user_text(raw)
    if normalization.get("query_kind") == "chat_only":
        return None
    if normalization.get("query_kind") == "grounding_required":
        return None
    structure_hypotheses = build_structure_hypotheses(raw)
    normalized_candidates = [
        _safe_str(item)
        for item in list(normalization.get("canonical_candidates") or normalization.get("candidate_queries") or [])
        if _safe_str(item)
    ]
    if normalization.get("follow_up_requires_context") and not normalized_candidates and not normalization.get("structures"):
        return None
    hint = _safe_str(normalization.get("maybe_structure_hint") or structure_hypotheses.get("primary_candidate"))
    if hint and not _is_follow_up_placeholder_query(hint):
        return hint
    canonical_candidates = normalized_candidates
    if normalization.get("maybe_task_hint") and not canonical_candidates and not normalization.get("structures"):
        return None
    for candidate in canonical_candidates:
        token = _safe_str(candidate)
        if token and not _is_follow_up_placeholder_query(token):
            return token
    analysis = analyze_structure_input(raw)
    for candidate in list(analysis.get("canonical_candidates") or []):
        token = _safe_str(candidate)
        if token and not _is_follow_up_placeholder_query(token):
            return token
    fallback = extract_structure_candidate(raw)
    if fallback and not _is_follow_up_placeholder_query(fallback):
        if normalization.get("structure_needs_clarification") and _safe_str(fallback).lower() == raw.lower():
            return None
        return fallback
    return None


def _matches_session_structure(query: str, state: Mapping[str, Any]) -> bool:
    current = _safe_str(query).lower()
    if not current:
        return False
    candidates = [
        _safe_str(state.get("last_structure_query")).lower(),
        _safe_str(state.get("last_resolved_name")).lower(),
        _safe_str((state.get("last_resolved_artifact") or {}).get("structure_query")).lower(),
        _safe_str((state.get("last_resolved_artifact") or {}).get("structure_name")).lower(),
    ]
    return current in {token for token in candidates if token}


def _is_follow_up_placeholder_query(query: str) -> bool:
    token = _safe_str(query)
    if not token:
        return False
    if _FOLLOW_UP_PLACEHOLDER_QUERY_RE.fullmatch(token):
        return True
    analysis_hits = set(
        re.findall(
            r"homo|lumo|esp|orbital|charge|charges|basis|optimize|optimization|"
            r"전하|오비탈|전위|정전기|기저|최적화",
            token,
            re.IGNORECASE,
        )
    )
    if len(analysis_hits) >= 2:
        return True
    if analysis_hits and _FOLLOW_UP_ACTION_CUE_RE.search(token):
        return True
    if analysis_hits and re.search(r"ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자", token, re.IGNORECASE):
        return True
    if re.search(r"\b(basis|esp|homo|lumo|orbital|charge|charges|optimize|optimization)\b", token, re.IGNORECASE):
        korean_chars = sum(1 for char in token if "\uac00" <= char <= "\ud7a3")
        if korean_chars > 0:
            return True
    return False


def _apply_session_continuation(out: Dict[str, Any], *, source_text: str = "") -> Dict[str, Any]:
    session_id = _extract_session_id(out)
    if not session_id:
        return out

    message = _safe_str(source_text or _extract_message(out))
    normalization = normalize_user_text(message or _safe_str(out.get("structure_query")))
    explicit_from_text = _explicit_structure_from_text(message)
    has_explicit_structure_input = bool(
        out.get("structure_query") or out.get("xyz") or out.get("atom_spec") or out.get("structures")
    )
    if explicit_from_text:
        out["structure_query"] = explicit_from_text
        out["structure_source"] = "user_input"
        has_explicit_structure_input = True

    for key in ("structures", "composition_kind", "charge_hint", "follow_up_mode"):
        if key not in out and normalization.get(key) not in (None, [], ""):
            out[key] = normalization.get(key)
    if out.get("charge") is None and normalization.get("charge_hint") is not None:
        out["charge"] = normalization.get("charge_hint")

    if normalization.get("query_kind") == "grounding_required":
        raw_variants = {
            _safe_str(item).lower()
            for item in (
                message,
                normalization.get("raw_input"),
                normalization.get("normalized_text"),
                *(normalization.get("unknown_acronyms") or []),
            )
            if _safe_str(item)
        }
        structure_query = _safe_str(out.get("structure_query"))
        if structure_query and structure_query.lower() in raw_variants:
            out.pop("structure_query", None)
            has_explicit_structure_input = False
        out.pop("follow_up_mode", None)
        if not has_explicit_structure_input:
            out["clarification_kind"] = "semantic_grounding"
            missing_slots = [str(item).strip() for item in list(out.get("missing_slots") or []) if str(item).strip()]
            if "structure_query" not in missing_slots:
                missing_slots.append("structure_query")
            out["missing_slots"] = missing_slots
            out["needs_clarification"] = True
            return out

    follow_up_mode = _safe_str(out.get("follow_up_mode") or normalization.get("follow_up_mode"))
    state: Dict[str, Any] = {}
    task_requested = bool(
        _safe_str(out.get("job_type")) not in {"", "resolve_structure"}
        or _safe_str(normalization.get("follow_up_job_type"))
        or list(normalization.get("analysis_bundle") or [])
        or normalization.get("maybe_task_hint")
    )
    if not follow_up_mode:
        analysis_bundle = {str(item).upper() for item in (normalization.get("analysis_bundle") or []) if _safe_str(item)}
        analysis_hits = analysis_bundle.intersection({"HOMO", "LUMO", "ESP"})
        strong_follow_up = bool(
            (len(analysis_hits) >= 2)
            or (
                analysis_hits
                and _FOLLOW_UP_ACTION_CUE_RE.search(message)
            )
        )
        if strong_follow_up and not explicit_from_text:
            follow_up_mode = "add_analysis"
            out["follow_up_mode"] = follow_up_mode
    if not follow_up_mode and task_requested and not explicit_from_text and not has_explicit_structure_input:
        state = load_conversation_state(session_id, manager=get_job_manager())
        if state:
            follow_up_mode = "reuse_last_structure"
            out["follow_up_mode"] = follow_up_mode
    if not follow_up_mode:
        return out

    current_query = _safe_str(out.get("structure_query"))
    if current_query and _is_follow_up_placeholder_query(current_query):
        out.pop("structure_query", None)
        current_query = ""

    if not state:
        state = load_conversation_state(session_id, manager=get_job_manager())
    if not state:
        out.setdefault("clarification_kind", "continuation_targeting")
        return out

    artifact = dict(state.get("last_resolved_artifact") or {})
    can_inherit_structure = not explicit_from_text and not (
        out.get("structure_query") or out.get("xyz") or out.get("atom_spec") or out.get("structures")
    )
    if task_requested and not explicit_from_text and not (
        out.get("structure_query") or out.get("xyz") or out.get("atom_spec") or out.get("structures")
    ):
        can_inherit_structure = True
    if current_query and _matches_session_structure(current_query, state):
        can_inherit_structure = True

    if can_inherit_structure:
        inherited_query = current_query or _safe_str(state.get("last_structure_query") or state.get("last_resolved_name"))
        if inherited_query and not out.get("structure_query"):
            out["structure_query"] = inherited_query
            out["structure_source"] = "continuation"
        if artifact.get("xyz") and not out.get("xyz"):
            out["xyz"] = artifact.get("xyz")
        if artifact.get("atom_spec") and not out.get("atom_spec"):
            out["atom_spec"] = artifact.get("atom_spec")
        if inherited_query or artifact.get("xyz") or artifact.get("atom_spec"):
            out["continuation_context_used"] = True

    if not out.get("method") and state.get("last_method"):
        out["method"] = state.get("last_method")
    if not out.get("basis") and state.get("last_basis"):
        out["basis"] = state.get("last_basis")

    if follow_up_mode == "modify_parameters":
        if _safe_str(out.get("job_type")) in {"", "analyze"} and state.get("last_job_type"):
            out["job_type"] = state.get("last_job_type")
        explicit_basis = _safe_str(normalization.get("follow_up_basis_hint"))
        if explicit_basis:
            out["basis"] = explicit_basis
        elif state.get("last_basis"):
            upgraded = _upgrade_basis(state.get("last_basis"))
            if upgraded:
                out["basis"] = upgraded
    elif follow_up_mode == "reuse_last_job":
        if _safe_str(out.get("job_type")) in {"", "analyze"} and state.get("last_job_type"):
            out["job_type"] = state.get("last_job_type")
    elif follow_up_mode == "reuse_last_structure":
        if _safe_str(out.get("job_type")) in {"", "analyze"} and state.get("last_job_type"):
            out["job_type"] = state.get("last_job_type")
    elif follow_up_mode == "optimize_same_structure":
        if _safe_str(out.get("job_type")) in {"", "analyze"}:
            out["job_type"] = "geometry_optimization"

    if normalization.get("follow_up_orbital") and not out.get("orbital"):
        out["orbital"] = normalization.get("follow_up_orbital")
    if normalization.get("follow_up_job_type") and _safe_str(out.get("job_type")) in {"", "analyze"}:
        out["job_type"] = normalization.get("follow_up_job_type")

    return out


def _preserve_structure_decomposition(out: Dict[str, Any], *, source_text: str = "") -> Dict[str, Any]:
    query = _safe_str(out.get("structure_query")) or _safe_str(source_text)
    if not query:
        return out

    analysis = analyze_structure_input(query)
    if not analysis.get("canonical_candidates"):
        return out

    out.setdefault("structure_query_candidates", list(analysis.get("canonical_candidates") or []))
    out.setdefault("formula_mentions", list(analysis.get("formula_mentions") or []))
    out.setdefault("alias_mentions", list(analysis.get("alias_mentions") or []))
    out.setdefault("canonical_candidates", list(analysis.get("canonical_candidates") or []))
    out.setdefault("raw_input", analysis.get("raw_input"))
    out.setdefault("mixed_input", bool(analysis.get("mixed_input")))
    if "composition_kind" not in out:
        normalization = normalize_user_text(query)
        if normalization.get("composition_kind"):
            out["composition_kind"] = normalization.get("composition_kind")
        if normalization.get("structures") and not out.get("structures"):
            out["structures"] = normalization.get("structures")
        if out.get("charge") is None and normalization.get("charge_hint") is not None:
            out["charge"] = normalization.get("charge_hint")
        if normalization.get("follow_up_mode") and not out.get("follow_up_mode"):
            out["follow_up_mode"] = normalization.get("follow_up_mode")

    if analysis.get("mixed_input") and analysis.get("primary_candidate"):
        current = _safe_str(out.get("structure_query"))
        primary = _safe_str(analysis.get("primary_candidate"))
        if current and current != primary:
            out.setdefault("structure_query_raw", current)
        out["structure_query"] = primary
    return out


def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})
    if out.get("structure_query") and not out.get("structure_source"):
        out["structure_source"] = "user_input"

    intent = _safe_str(plan.get("intent"))
    if not out.get("job_type"):
        out["job_type"] = _normalize_job_type(plan.get("job_type"), intent)

    for key in ("method", "basis", "orbital", "advisor_focus_tab"):
        if not out.get(key) and plan.get(key):
            out[key] = plan.get(key)

    for key in ("charge", "multiplicity"):
        if out.get(key) is None and plan.get(key) is not None:
            out[key] = plan.get(key)

    if not out.get("esp_preset") and plan.get("esp_preset"):
        out["esp_preset"] = _normalize_esp_preset(plan.get("esp_preset"))

    # planner structure should override continuation or placeholder values
    plan_structure = _safe_str(plan.get("structure_query"))
    current_structure = _safe_str(out.get("structure_query"))
    current_source = _safe_str(out.get("structure_source"))
    should_take_plan_structure = bool(
        plan_structure
        and (
            not current_structure
            or current_source in {"continuation", "fallback"}
            or _is_follow_up_placeholder_query(current_structure)
            or (current_source != "user_input" and current_structure.lower() != plan_structure.lower())
        )
    )
    if should_take_plan_structure:
        out["structure_query"] = plan_structure
        out["structure_source"] = "planner"
    if not out.get("structures") and plan.get("structures"):
        out["structures"] = plan.get("structures")
    for key in (
        "structure_query_candidates",
        "formula_mentions",
        "alias_mentions",
        "canonical_candidates",
        "raw_input",
        "mixed_input",
        "composition_kind",
        "charge_hint",
        "component_names",
        "mentioned_molecules",
        "target_scope",
        "selection_mode",
        "selection_hint",
        "selected_molecules",
        "analysis_bundle",
        "batch_request",
        "batch_size",
    ):
        if key not in out and plan.get(key) not in (None, [], ""):
            out[key] = plan.get(key)

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    message_normalization = normalize_user_text(raw_message or _extract_message(out))
    if message_normalization.get("semantic_descriptor") and out.get("structure_query") and not out.get("structures"):
        raw_variants = {
            str(item).strip().lower()
            for item in (
                raw_message,
                message_normalization.get("normalized_text"),
                message_normalization.get("translated_text"),
            )
            if str(item or "").strip()
        }
        if str(out.get("structure_query") or "").strip().lower() in raw_variants:
            out.pop("structure_query", None)
            if out.get("structure_source") == "planner":
                out.pop("structure_source", None)

    # FIX(M2): If still no structure, use raw message as query (resolver will handle it)
    planner_requires_structure_clarification = bool(
        plan.get("needs_clarification")
        or "structure_query" in list(plan.get("missing_slots") or [])
    )
    if (
        not planner_requires_structure_clarification
        and not out.get("structure_query")
        and not out.get("xyz")
        and not out.get("atom_spec")
        and not out.get("structures")
        and not message_normalization.get("semantic_descriptor")
    ):
        raw = raw_message or _extract_message(out)
        candidate = _fallback_extract_structure_query(raw) if raw else None
        if candidate and len(candidate.strip()) >= 2:
            out["structure_query"] = candidate.strip()
            out["structure_source"] = "fallback"

    _preserve_structure_decomposition(out, source_text=raw_message or _extract_message(out))
    if not out.get("_continuation_applied"):
        _apply_session_continuation(out, source_text=raw_message or _extract_message(out))
        out["_continuation_applied"] = True

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    out["planner_missing_slots"] = plan.get("missing_slots")
    out["planner_needs_clarification"] = plan.get("needs_clarification")
    if plan.get("clarification_kind") and not out.get("clarification_kind"):
        out["clarification_kind"] = plan.get("clarification_kind")
    elif message_normalization.get("semantic_descriptor") and not out.get("clarification_kind"):
        out["clarification_kind"] = "semantic_grounding"
    if plan.get("follow_up_mode") and not out.get("follow_up_mode"):
        out["follow_up_mode"] = plan.get("follow_up_mode")
    if plan.get("normalized_text") and not out.get("normalized_text"):
        out["normalized_text"] = plan.get("normalized_text")
    return out


def _fallback_extract_structure_query(message: str) -> Optional[str]:
    return extract_structure_candidate(message)


def _focus_tab_from_result(result: Mapping[str, Any]) -> str:
    for key in ("advisor_focus_tab", "focus_tab", "default_tab"):
        value = _safe_str(result.get(key))
        if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
            return value
    vis = result.get("visualization") or {}
    if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
        vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
    ):
        return "esp"
    if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"


def _normalize_result_contract(result: Any, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    if isinstance(result, Mapping):
        out = dict(result)
    else:
        out = {"success": True, "result": _json_safe(result)}

    out.setdefault("success", True)
    out.setdefault("job_type", _normalize_job_type(payload.get("job_type"), payload.get("planner_intent")))
    out.setdefault("structure_query", payload.get("structure_query"))
    out.setdefault("structure_name", payload.get("structure_query") or payload.get("structure_name"))
    out.setdefault("method", payload.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"))
    out.setdefault("basis", payload.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"))
    out.setdefault("charge", _safe_int(payload.get("charge"), 0) or 0)
    out.setdefault("multiplicity", _safe_int(payload.get("multiplicity"), 1) or 1)

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    if out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(out.get("esp_preset") or payload.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_from_result(out))

    if out.get("xyz"):
        vis.setdefault("xyz", out.get("xyz"))
        vis.setdefault("molecule_xyz", out.get("xyz"))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    warnings = out.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [warnings]
    out["warnings"] = [_safe_str(x) for x in warnings if _safe_str(x)]

    H2EV = getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
    if out.get("orbital_gap_hartree") is None and out.get("orbital_gap_ev") is not None:
        try:
            out["orbital_gap_hartree"] = float(out["orbital_gap_ev"]) / H2EV
        except Exception:
            pass
    if out.get("orbital_gap_ev") is None and out.get("orbital_gap_hartree") is not None:
        try:
            out["orbital_gap_ev"] = float(out["orbital_gap_hartree"]) * H2EV
        except Exception:
            pass

    out["advisor_focus_tab"] = _focus_tab_from_result(out)
    out["default_tab"] = out["advisor_focus_tab"]
    return _json_safe(out)


# FIX(M2): _prepare_payload now uses structure_resolver
def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    _preserve_structure_decomposition(data, source_text=raw_message)
    if not data.get("_continuation_applied"):
        _apply_session_continuation(data, source_text=raw_message)
        data["_continuation_applied"] = True

    data["_method_user_supplied"] = bool(_safe_str(data.get("method")))
    data["_basis_user_supplied"] = bool(_safe_str(data.get("basis")))
    if "advisor" not in data:
        data["advisor"] = True

    data["job_type"] = _normalize_job_type(data.get("job_type"), data.get("planner_intent"))
    data["method"] = _safe_str(
        data.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
    )
    data["basis"] = _safe_str(
        data.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
    )
    data["charge"] = _safe_int(data.get("charge"), 0) or 0
    data["multiplicity"] = _safe_int(data.get("multiplicity"), 1) or 1

    if data.get("esp_preset"):
        data["esp_preset"] = _normalize_esp_preset(data.get("esp_preset"))

    if not data.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message)
        if xyz_block:
            data["xyz"] = xyz_block

    # FIX(M2): No more inline structure extraction — resolver will handle it
    planner_requires_structure_clarification = bool(
        data.get("planner_needs_clarification")
        or "structure_query" in list(data.get("planner_missing_slots") or [])
    )
    raw_normalization = normalize_user_text(raw_message or "")
    if (
        not planner_requires_structure_clarification
        and not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures"))
        and not raw_normalization.get("semantic_descriptor")
    ):
        candidate = _fallback_extract_structure_query(raw_message) if raw_message else None
        if candidate and len(candidate.strip()) >= 2:
            data["structure_query"] = candidate.strip()
            _preserve_structure_decomposition(data, source_text=raw_message)

    selected_molecules = [item for item in (data.get("selected_molecules") or []) if _safe_str(item)]
    if selected_molecules:
        data["selected_molecules"] = selected_molecules
        data["batch_request"] = True
        data["batch_size"] = len(selected_molecules)
    has_batch = data.get("batch_request") and len(data.get("selected_molecules") or []) > 0
    if data["job_type"] not in {"resolve_structure"}:
        if not has_batch and not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
            raise HTTPException(
                status_code=400,
                detail=(
                    "구조를 인식할 수 없습니다. 분자 이름, XYZ 좌표 또는 atom-spec을 제공해 주세요. / "
                    "Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text."
                ),
            )

    return data


def _build_kwargs_for_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    sig = inspect.signature(func)
    kwargs: Dict[str, Any] = {}
    candidate_map = {
        "structure_query": payload.get("structure_query") or payload.get("query"),
        "xyz": payload.get("xyz"),
        "atom_spec": payload.get("atom_spec"),
        "method": payload.get("method"),
        "basis": payload.get("basis"),
        "charge": payload.get("charge"),
        "multiplicity": payload.get("multiplicity"),
        "orbital": payload.get("orbital"),
        "esp_preset": payload.get("esp_preset"),
        "advisor_focus_tab": payload.get("advisor_focus_tab"),
        "user_message": _extract_message(payload),
        "message": _extract_message(payload),
        "progress_callback": progress_callback,
    }
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    for name, param in sig.parameters.items():
        if name in candidate_map and candidate_map[name] is not None:
            kwargs[name] = candidate_map[name]
    if accepts_var_kw:
        for key, value in payload.items():
            if key not in kwargs and value is not None:
                kwargs[key] = value
        if progress_callback is not None and "progress_callback" not in kwargs:
            kwargs["progress_callback"] = progress_callback
    return kwargs


def _invoke_callable_adaptive_sync(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Any:
    kwargs = _build_kwargs_for_callable(func, payload, progress_callback=progress_callback)
    return func(**kwargs)


# helper runner map for analysis bundle to runner names and orbital overrides
_ANALYSIS_RUNNER_MAP = {
    "HOMO": ("run_orbital_preview", "HOMO"),
    "LUMO": ("run_orbital_preview", "LUMO"),
    "ESP": ("run_esp_map", None),
}


async def _run_batch_compute_async(
    prepared: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    selected = [str(item).strip() for item in (prepared.get("selected_molecules") or []) if _safe_str(item)]
    bundle = list(dict.fromkeys(prepared.get("analysis_bundle") or ["structure"]))
    molecule_results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for idx, molecule in enumerate(selected, start=1):
        if callable(progress_callback):
            progress_callback(
                {
                    "progress": min(0.1 + idx / max(len(selected), 1) * 0.4, 0.5),
                    "step": "batch_resolution",
                    "message": f"Resolving structure for '{molecule}'",
                }
            )
        try:
            resolved = await _resolve_structure_async(molecule)
            structure_entry = {
                "success": True,
                "structure_query": molecule,
                "structure_name": resolved.get("name") or molecule,
                "xyz": resolved.get("xyz"),
                "source": resolved.get("source"),
            }

            result_entry: Dict[str, Any] = {
                "molecule_name": structure_entry["structure_name"],
                "structure_result": structure_entry,
                "homo_result": None,
                "lumo_result": None,
                "esp_result": None,
                "errors": [],
            }

            child_payload = dict(prepared)
            child_payload["structure_query"] = structure_entry["structure_name"]
            child_payload["xyz"] = structure_entry["xyz"]
            child_payload["atom_spec"] = resolved.get("atom_spec")
            child_payload["batch_request"] = False
            child_payload["selected_molecules"] = [molecule]
            for analysis in bundle:
                if analysis.lower() == "structure":
                    continue
                runner_info = _ANALYSIS_RUNNER_MAP.get(analysis.upper())
                runner_name = runner_info[0] if runner_info else "run_orbital_preview"
                runner = getattr(pyscf_runner, runner_name, None)
                if not callable(runner):
                    result_entry["errors"].append({"analysis": analysis, "error": f"Runner {runner_name} unavailable"})
                    failures.append({"molecule": molecule, "analysis": analysis, "error": f"Runner {runner_name} unavailable"})
                    continue
                if runner_info and runner_info[1]:
                    child_payload["orbital"] = runner_info[1]
                child_payload["job_type"] = "orbital_preview" if "orbital" in runner_name else "esp_map"
                try:
                    analysis_result = _invoke_callable_adaptive_sync(runner, child_payload)
                    normalized = _normalize_result_contract(analysis_result, child_payload)
                    if analysis.upper() == "HOMO":
                        result_entry["homo_result"] = normalized
                    elif analysis.upper() == "LUMO":
                        result_entry["lumo_result"] = normalized
                    elif analysis.upper() == "ESP":
                        result_entry["esp_result"] = normalized
                except Exception as exc:
                    error_msg = str(exc)
                    result_entry["errors"].append({"analysis": analysis, "error": error_msg})
                    failures.append({"molecule": molecule, "analysis": analysis, "error": error_msg})
            molecule_results.append(result_entry)
        except Exception as exc:
            failures.append({"molecule": molecule, "error": str(exc)})

    success = len(failures) == 0
    return {
        "success": success,
        "batch_request": True,
        "analysis_bundle": bundle,
        "molecule_results": molecule_results,
        "partial_failures": failures,
        "completed_count": len(molecule_results),
        "failed_count": len(failures),
        "structure_query": selected[0] if selected else None,
        "job_type": prepared.get("job_type"),
        "method": prepared.get("method"),
        "basis": prepared.get("basis"),
        "selected_molecules": selected,
    }


# FIX(M2): _run_direct_compute with async structure resolution
async def _run_direct_compute_async(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Resolve structure asynchronously, then run PySCF synchronously."""
    with track_operation("web.compute", parameters={"job_type": payload.get("job_type"), "has_xyz": bool(payload.get("xyz"))}) as obs:
        prepared = _prepare_payload(payload)
        advisor_plan: Optional[Dict[str, Any]] = None
        batch_selected = bool(prepared.get("batch_request") and len(prepared.get("selected_molecules") or []) > 1)
        if batch_selected:
            return await _run_batch_compute_async(prepared, progress_callback=progress_callback)

        # Check for ion pair
        structures = prepared.get("structures")
        if structures and is_ion_pair(structures):
            ion_data = await _resolve_ion_pair_async(structures)
            prepared["xyz"] = ion_data["xyz"]
            prepared["charge"] = ion_data.get("total_charge", prepared.get("charge", 0))
            prepared["structure_query"] = " + ".join(ion_data.get("names", []))
        elif not prepared.get("xyz") and not prepared.get("atom_spec"):
            query = prepared.get("structure_query", "")
            if query:
                # FIX: Detect ion pair pattern from structure_query string
                # e.g. "EMIM+ TFSI-", "Li+ PF6-"
                import re as _re
                _ion_parts = _re.findall(r'[\w]+[+\-]', query)
                if len(_ion_parts) >= 2:
                    # Treat as ion pair — build structures list and resolve
                    _structs = []
                    for part in _ion_parts:
                        _charge = 1 if part.endswith('+') else (-1 if part.endswith('-') else 0)
                        _structs.append({"name": part.strip(), "charge": _charge})
                    try:
                        ion_data = await _resolve_ion_pair_async(_structs)
                        prepared["xyz"] = ion_data["xyz"]
                        prepared["charge"] = ion_data.get("total_charge", prepared.get("charge", 0))
                        prepared["structure_query"] = " + ".join(ion_data.get("names", []))
                    except Exception as _ion_exc:
                        logger.warning("Ion pair resolution failed, trying as single: %s", _ion_exc)
                        resolved = await _resolve_structure_async(query)
                        prepared["xyz"] = resolved["xyz"]
                        if not prepared.get("structure_query") or prepared["structure_query"] == query:
                            prepared["structure_query"] = resolved.get("name", query)
                else:
                    resolved = await _resolve_structure_async(query)
                    prepared["xyz"] = resolved["xyz"]
                    if not prepared.get("structure_query") or prepared["structure_query"] == query:
                        prepared["structure_query"] = resolved.get("name", query)

        mult_warning = None
        try:
            effective_mult, mult_warning = pyscf_runner.coerce_multiplicity_for_structure(
                xyz=prepared.get("xyz"),
                atom_spec=prepared.get("atom_spec"),
                charge=_safe_int(prepared.get("charge"), 0) or 0,
                multiplicity=_safe_int(prepared.get("multiplicity"), 1) or 1,
            )
            prepared["multiplicity"] = effective_mult
        except Exception as exc:
            logger.debug("Multiplicity coercion skipped: %s", exc)

        preview_result = _build_structure_preview_result(
            prepared,
            extra_warnings=[mult_warning] if mult_warning else None,
        )
        if preview_result and callable(progress_callback):
            progress_callback(
                {
                    "progress": 0.14,
                    "step": "structure_ready",
                    "message": "Structure ready for preview",
                    "preview_result": preview_result,
                }
            )

        if bool(prepared.get("advisor", True)) and callable(prepare_advisor_plan_from_geometry):
            try:
                advisor_plan = prepare_advisor_plan_from_geometry(
                    intent_name=_advisor_intent_name(prepared),
                    xyz_text=prepared.get("xyz"),
                    atom_spec=prepared.get("atom_spec"),
                    charge=_safe_int(prepared.get("charge"), 0) or 0,
                    spin=_multiplicity_to_spin(prepared.get("multiplicity")),
                )
                if callable(apply_preset_to_runner_kwargs):
                    prepared = apply_preset_to_runner_kwargs(prepared, advisor_plan)
            except Exception as exc:
                logger.warning("Advisor preset application failed: %s", exc)

        job_type = _normalize_job_type(prepared.get("job_type"), prepared.get("planner_intent"))
        runner_name = JOB_TYPE_TO_RUNNER.get(job_type)
        if not runner_name:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 job_type: {job_type} / Unsupported job_type: {job_type}",
            )

        runner = getattr(pyscf_runner, runner_name, None)
        if not callable(runner):
            raise RuntimeError(f"Runner not available: {runner_name}")

        result = _invoke_callable_adaptive_sync(runner, prepared, progress_callback=progress_callback)
        normalized = _normalize_result_contract(result, prepared)
        obs.metrics.update(
            {
                "job_type": normalized.get("job_type"),
                "advisor_enabled": bool(prepared.get("advisor", True)),
                "scf_converged": bool(normalized.get("scf_converged")),
            }
        )
        return _apply_advisor_enrichment(normalized, prepared, advisor_plan=advisor_plan)


def _run_direct_compute(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Sync wrapper for _run_direct_compute_async.

    FIX(M2): Worker threads (qcviz-job_*) have no event loop.
    Use asyncio.run() which creates+destroys a new loop automatically.
    Only use run_coroutine_threadsafe if we detect a running loop (rare).
    """
    try:
        # First try: see if there's already a running loop (e.g. Jupyter, nested async)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside a running loop — schedule on it from this thread
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                _run_direct_compute_async(payload, progress_callback),
                loop,
            )
            return future.result(timeout=300)
        else:
            # Normal case: no running loop — create one via asyncio.run()
            return asyncio.run(
                _run_direct_compute_async(payload, progress_callback)
            )
    except HTTPException:
        raise
    except Exception as e:
        if "HTTPException" in type(e).__name__:
            raise
        raise HTTPException(
            status_code=500,
            detail=f"계산 실행 중 오류: {e} / Computation error: {e}",
        )


# ── Job Record & Manager ─────────────────────────────────────

@dataclass
class JobRecord:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    step: str = "queued"
    message: str = "Queued"
    user_query: str = ""
    created_at: float = field(default_factory=_now_ts)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    updated_at: float = field(default_factory=_now_ts)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    future: Optional[Future] = None
    event_seq: int = 0


class InMemoryJobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.max_workers = max(1, int(max_workers or 1))
        self.default_max_retries = _quota_limit_from_env("QCVIZ_MAX_JOB_RETRIES", 1)
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        # FIX(M2): atomic file write for disk persistence
        self.cache_dir = os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache")
        self.cache_file = os.path.join(self.cache_dir, "job_history.json")
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", self.max_workers)
        self._load_from_disk()

    def _job_order_key(self, job: JobRecord) -> Tuple[float, str]:
        return (float(job.created_at or 0.0), job.job_id)

    def _active_jobs_for_session_locked(self, session_id: str) -> List[JobRecord]:
        wanted = _safe_str(session_id)
        if not wanted:
            return []
        return [
            job
            for job in self.jobs.values()
            if job.status in {"queued", "running"} and _job_session_id(job.payload) == wanted
        ]

    def _active_jobs_for_owner_locked(self, owner_username: str) -> List[JobRecord]:
        wanted = _safe_str(owner_username)
        if not wanted:
            return []
        return [
            job
            for job in self.jobs.values()
            if job.status in {"queued", "running"} and _job_owner_username(job.payload) == wanted
        ]

    def _quota_summary_locked(
        self,
        *,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        owner = _safe_str(owner_username)
        session = _safe_str(session_id)
        per_session_limit = _max_active_jobs_per_session()
        per_user_limit = _max_active_jobs_per_user()
        active_for_session = self._active_jobs_for_session_locked(session)
        active_for_owner = self._active_jobs_for_owner_locked(owner)
        return {
            "session_id": session,
            "owner_username": owner,
            "active_for_session": len(active_for_session),
            "active_for_owner": len(active_for_owner),
            "max_active_per_session": per_session_limit,
            "max_active_per_user": per_user_limit,
            "session_limited": bool(session and per_session_limit > 0),
            "user_limited": bool(owner and per_user_limit > 0),
            "session_remaining": None if not session or per_session_limit <= 0 else max(0, per_session_limit - len(active_for_session)),
            "user_remaining": None if not owner or per_user_limit <= 0 else max(0, per_user_limit - len(active_for_owner)),
        }

    def _enforce_quota_locked(self, payload: Mapping[str, Any]) -> None:
        session_id = _job_session_id(payload)
        owner_username = _job_owner_username(payload)
        quota = self._quota_summary_locked(session_id=session_id, owner_username=owner_username)

        if quota["user_limited"] and quota["active_for_owner"] >= quota["max_active_per_user"]:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Active job quota exceeded for user '{owner_username}' "
                    f"({quota['active_for_owner']}/{quota['max_active_per_user']}). "
                    "Wait for an existing job to finish before submitting another."
                ),
            )

        if quota["session_limited"] and quota["active_for_session"] >= quota["max_active_per_session"]:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Active job quota exceeded for this session "
                    f"({quota['active_for_session']}/{quota['max_active_per_session']}). "
                    "Wait for an existing job to finish before submitting another."
                ),
            )

    def _completed_durations_locked(self, *, job_type: Optional[str] = None, limit: int = 25) -> List[float]:
        wanted_job_type = _safe_str(job_type)
        durations: List[float] = []
        completed = [
            job for job in sorted(self.jobs.values(), key=lambda item: float(item.ended_at or 0.0), reverse=True)
            if job.status == "completed"
        ]
        for job in completed:
            if wanted_job_type and _safe_str(job.payload.get("job_type")) != wanted_job_type:
                continue
            if job.started_at and job.ended_at and job.ended_at > job.started_at:
                durations.append(float(job.ended_at - job.started_at))
            if len(durations) >= max(1, int(limit)):
                break
        return durations

    def _average_runtime_seconds_locked(self, *, job_type: Optional[str] = None) -> float:
        samples = sorted(self._completed_durations_locked(job_type=job_type))
        if not samples and _safe_str(job_type):
            samples = sorted(self._completed_durations_locked(job_type=None))
        if not samples:
            return 75.0
        mid = len(samples) // 2
        if len(samples) % 2 == 1:
            return float(samples[mid])
        return float((samples[mid - 1] + samples[mid]) / 2.0)

    def _prepare_payload_for_submit(self, payload: Mapping[str, Any], *, job_id: Optional[str] = None) -> Dict[str, Any]:
        prepared = dict(payload or {})
        prepared["retry_count"] = max(0, int(prepared.get("retry_count") or 0))
        prepared["max_retries"] = max(0, int(prepared.get("max_retries") or self.default_max_retries))
        if job_id and not _safe_str(prepared.get("retry_origin_job_id")):
            prepared["retry_origin_job_id"] = job_id
        return prepared

    def _build_retry_payload(self, payload: Mapping[str, Any], *, parent_job_id: str, reason: str, actor: str) -> Dict[str, Any]:
        prepared = dict(payload or {})
        prepared["retry_count"] = max(0, int(prepared.get("retry_count") or 0)) + 1
        prepared["max_retries"] = max(0, int(prepared.get("max_retries") or self.default_max_retries))
        prepared["retry_origin_job_id"] = _safe_str(prepared.get("retry_origin_job_id") or parent_job_id)
        prepared["retry_parent_job_id"] = parent_job_id
        prepared["retry_reason"] = _safe_str(reason, "retry")
        prepared["retry_actor"] = _safe_str(actor, "system")
        return prepared

    def _queue_summary_locked(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        jobs = sorted(self.jobs.values(), key=self._job_order_key)
        running_jobs = [job for job in jobs if job.status == "running"]
        queued_jobs = [job for job in jobs if job.status == "queued"]
        active_jobs = [job for job in jobs if job.status in {"queued", "running"}]
        queue: Dict[str, Any] = {
            "max_workers": self.max_workers,
            "total_count": len(jobs),
            "active_count": len(active_jobs),
            "running_count": len(running_jobs),
            "queued_count": len(queued_jobs),
            "available_workers": max(0, self.max_workers - len(running_jobs)),
            "is_saturated": len(running_jobs) >= self.max_workers,
            "avg_runtime_seconds": self._average_runtime_seconds_locked(),
            "estimated_queue_drain_seconds": int(math.ceil(float(len(queued_jobs)) / float(max(1, self.max_workers))) * self._average_runtime_seconds_locked()) if queued_jobs else 0,
        }
        if not job_id:
            return queue

        target = self.jobs.get(job_id)
        if target is None:
            queue.update(
                {
                    "job_id": job_id,
                    "job_status": None,
                    "queued_ahead": None,
                    "queue_position": None,
                    "active_ahead": None,
                    "active_position": None,
                    "will_wait": None,
                }
            )
            return queue

        queue["job_id"] = target.job_id
        queue["job_status"] = target.status
        target_key = self._job_order_key(target)

        if target.status in {"queued", "running"}:
            active_ahead = sum(1 for job in active_jobs if self._job_order_key(job) < target_key)
            queue["active_ahead"] = active_ahead
            queue["active_position"] = active_ahead + 1
        else:
            queue["active_ahead"] = None
            queue["active_position"] = None

        if target.status == "queued":
            queued_ahead = sum(1 for job in queued_jobs if self._job_order_key(job) < target_key)
            queue["queued_ahead"] = queued_ahead
            queue["queue_position"] = queued_ahead + 1
            queue["will_wait"] = len(running_jobs) >= self.max_workers
            avg_runtime_seconds = self._average_runtime_seconds_locked(job_type=_safe_str(target.payload.get("job_type")))
            available_now = max(0, self.max_workers - len(running_jobs))
            if queued_ahead < available_now:
                queue["estimated_start_in_seconds"] = 0
            else:
                remaining_ahead = max(0, queued_ahead - available_now + 1)
                queue["estimated_start_in_seconds"] = int(math.ceil(float(remaining_ahead) / float(max(1, self.max_workers))) * avg_runtime_seconds)
            queue["estimated_finish_in_seconds"] = int(queue["estimated_start_in_seconds"] + avg_runtime_seconds)
            queue["estimated_remaining_seconds"] = None
        elif target.status == "running":
            queue["queued_ahead"] = 0
            queue["queue_position"] = 0
            queue["will_wait"] = False
            avg_runtime_seconds = self._average_runtime_seconds_locked(job_type=_safe_str(target.payload.get("job_type")))
            queue["estimated_start_in_seconds"] = 0
            queue["estimated_remaining_seconds"] = int(max(0.0, avg_runtime_seconds * (1.0 - float(target.progress or 0.0))))
            queue["estimated_finish_in_seconds"] = int(queue["estimated_remaining_seconds"])
        else:
            queue["queued_ahead"] = None
            queue["queue_position"] = None
            queue["will_wait"] = False
            queue["estimated_start_in_seconds"] = None
            queue["estimated_finish_in_seconds"] = None
            queue["estimated_remaining_seconds"] = None
        return queue

    def queue_summary(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            return self._queue_summary_locked(job_id)

    def quota_summary(
        self,
        *,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            return self._quota_summary_locked(session_id=session_id, owner_username=owner_username)

    def _save_to_disk(self) -> None:
        # FIX(M5): atomic file write (tmp → rename)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            dump_data = {}
            with self.lock:
                for k, v in self.jobs.items():
                    dump_data[k] = {
                        "job_id": v.job_id, "status": v.status,
                        "user_query": v.user_query, "payload": v.payload,
                        "progress": v.progress, "step": v.step,
                        "message": v.message, "created_at": v.created_at,
                        "started_at": v.started_at, "ended_at": v.ended_at,
                        "error": v.error, "result": v.result,
                        "events": v.events,
                    }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_dir,
                prefix="job_history.",
                suffix=".tmp",
                delete=False,
            ) as f:
                json.dump(dump_data, f)
                tmp_file = f.name
            os.replace(tmp_file, self.cache_file)
        except Exception as e:
            logger.warning("Failed to save job history: %s", e)

    def _load_from_disk(self) -> None:
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    rec = JobRecord(job_id=v["job_id"], user_query=v.get("user_query", ""), payload=v.get("payload", {}))
                    restored_status = v.get("status", "unknown")
                    if restored_status in {"queued", "running"}:
                        restored_status = "failed"
                        rec.error = {
                            "message": "Server restarted before this job completed.",
                            "type": "stale_job_recovered",
                        }
                        rec.message = "Server restarted before completion"
                        rec.step = "error"
                    rec.status = restored_status
                    rec.progress = v.get("progress", 0)
                    rec.step = rec.step or v.get("step", "")
                    rec.message = rec.message or v.get("message", "")
                    rec.created_at = v.get("created_at", 0)
                    rec.started_at = v.get("started_at")
                    rec.ended_at = v.get("ended_at")
                    rec.error = rec.error or v.get("error")
                    rec.result = v.get("result")
                    rec.events = v.get("events", [])
                    self.jobs[k] = rec
        except Exception as e:
            logger.warning("Failed to load job history: %s", e)

    def _prune(self) -> None:
        with self.lock:
            if len(self.jobs) <= MAX_JOBS:
                return
            ordered = sorted(self.jobs.values(), key=lambda x: x.created_at)
            removable = [j.job_id for j in ordered if j.status in TERMINAL_STATES]
            while len(self.jobs) > MAX_JOBS and removable:
                jid = removable.pop(0)
                self.jobs.pop(jid, None)

    def _append_event(self, job: JobRecord, event_type: str, message: str, data: Optional[Mapping[str, Any]] = None) -> None:
        job.event_seq += 1
        event = {
            "event_id": job.event_seq,
            "ts": _now_ts(),
            "type": _safe_str(event_type),
            "message": _safe_str(message),
            "data": _json_safe(dict(data or {})),
        }
        job.events.append(event)
        if len(job.events) > MAX_JOB_EVENTS:
            job.events = job.events[-MAX_JOB_EVENTS:]

    def _snapshot(
        self, job: JobRecord, *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Dict[str, Any]:
        # FIX(M5): shallow copy for thread safety
        snap = {
            "job_id": job.job_id,
            "session_id": _job_session_id(job.payload),
            "owner_username": _job_owner_username(job.payload),
            "owner_display_name": _safe_str(job.payload.get("owner_display_name")),
            "status": job.status,
            "user_query": job.user_query,
            "job_type": job.payload.get("job_type", ""),
            "retry_count": max(0, int(job.payload.get("retry_count") or 0)),
            "max_retries": max(0, int(job.payload.get("max_retries") or self.default_max_retries)),
            "retry_origin_job_id": _safe_str(job.payload.get("retry_origin_job_id")),
            "retry_parent_job_id": _safe_str(job.payload.get("retry_parent_job_id")),
            "molecule_name": job.payload.get("structure_query", ""),
            "method": job.payload.get("method", ""),
            "basis_set": job.payload.get("basis", ""),
            "progress": float(job.progress),
            "step": job.step,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "updated_at": job.updated_at,
            "queue": self._queue_summary_locked(job.job_id),
            "quota": self._quota_summary_locked(
                session_id=_job_session_id(job.payload),
                owner_username=_job_owner_username(job.payload),
            ),
        }
        if include_payload:
            snap["payload"] = _json_safe(dict(job.payload))
        if include_result:
            snap["result"] = _json_safe(job.result) if job.result else None
            snap["error"] = _json_safe(job.error) if job.error else None
        if include_events:
            snap["events"] = _json_safe(list(job.events))
        return snap

    def _submit_locked(self, payload: Mapping[str, Any], *, enforce_quota: bool = True) -> Dict[str, Any]:
        prepared = dict(payload or {})
        job_id = uuid.uuid4().hex
        prepared = self._prepare_payload_for_submit(prepared, job_id=job_id)
        user_message = _extract_message(prepared)
        record = JobRecord(job_id=job_id, payload=prepared, user_query=user_message)
        if enforce_quota:
            self._enforce_quota_locked(prepared)
        self.jobs[job_id] = record
        self._append_event(record, "job_submitted", "Job submitted", {"job_type": prepared.get("job_type"), "retry_count": prepared.get("retry_count"), "max_retries": prepared.get("max_retries")})
        record.future = self.executor.submit(self._run_job, job_id)
        self._prune()
        return self._snapshot(record)

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            return self._submit_locked(payload, enforce_quota=True)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = _now_ts()
            job.updated_at = job.started_at
            job.step = "starting"
            job.message = "Starting job"
            self._append_event(job, "job_started", "Job started")
            payload_copy = dict(job.payload)
            payload_copy["job_id"] = job_id

        def progress_callback(*args: Any, **kwargs: Any) -> None:
            cb_payload: Dict[str, Any] = {}
            if args and isinstance(args[0], Mapping):
                cb_payload.update(dict(args[0]))
            else:
                if len(args) >= 1:
                    cb_payload["progress"] = args[0]
                if len(args) >= 2:
                    cb_payload["step"] = args[1]
                if len(args) >= 3:
                    cb_payload["message"] = args[2]
            cb_payload.update(kwargs)

            with self.lock:
                record = self.jobs.get(job_id)
                if record is None:
                    return
                record.progress = max(0.0, min(1.0, float(_safe_float(cb_payload.get("progress"), record.progress) or 0.0)))
                record.step = _safe_str(cb_payload.get("step"), record.step or "running")
                record.message = _safe_str(cb_payload.get("message"), record.message or record.step or "Running")
                record.updated_at = _now_ts()
                # Store SCF convergence data for WebSocket relay
                scf_extra = {}
                for k in ("scf_history", "scf_dE", "scf_cycle", "scf_energy", "scf_max_cycle", "preview_result"):
                    if k in cb_payload:
                        scf_extra[k] = cb_payload[k]
                self._append_event(record, "job_progress", record.message, {"progress": record.progress, "step": record.step, **scf_extra})

        try:
            result = _run_direct_compute(payload_copy, progress_callback=progress_callback)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "completed"
                job.progress = 1.0
                job.step = "done"
                job.message = "Completed"
                job.result = result
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_completed", "Job completed")
                update_conversation_state_from_execution(payload_copy, result, job_id=job_id, manager=self)
            self._save_to_disk()
        except HTTPException as exc:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = _safe_str(exc.detail, "Request failed")
                job.error = {"message": _safe_str(exc.detail, "Request failed"), "status_code": exc.status_code}
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)
            self._save_to_disk()
        except Exception as exc:
            logger.exception("Direct compute failed for job %s", job_id)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = str(exc)
                job.error = {"message": str(exc), "type": exc.__class__.__name__}
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)
            self._save_to_disk()

    def get(self, job_id: str, *, include_payload: bool = False, include_result: bool = False, include_events: bool = False) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot(job, include_payload=include_payload, include_result=include_result, include_events=include_events)

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
            wanted_session = _safe_str(session_id)
            if wanted_session:
                jobs = [job for job in jobs if _job_session_id(job.payload) == wanted_session]
            wanted_owner = _safe_str(owner_username)
            if wanted_owner:
                jobs = [job for job in jobs if _job_owner_username(job.payload) == wanted_owner]
            return [self._snapshot(job, include_payload=include_payload, include_result=include_result, include_events=include_events) for job in jobs]

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status not in TERMINAL_STATES:
                raise HTTPException(status_code=409, detail="Cannot delete a running job.")
            self.jobs.pop(job_id, None)
            return True

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return {"ok": False, "job_id": job_id, "status": "missing", "message": "job not found"}
            if job.status == "queued":
                job.status = "cancelled"
                job.step = "cancelled"
                job.message = "Cancelled before execution"
                job.ended_at = _now_ts()
                job.updated_at = job.ended_at
                self._append_event(job, "job_cancelled", job.message, {"detail": job.message})
                return {"ok": True, "job_id": job_id, "status": "cancelled", "message": job.message}
            if job.status == "running":
                from qcviz_mcp.compute.pyscf_runner import _CANCEL_FLAGS

                _CANCEL_FLAGS[job_id] = True
                job.message = "Cancellation requested"
                job.updated_at = _now_ts()
                self._append_event(job, "job_cancel_requested", job.message, {"detail": job.message})
                return {"ok": True, "job_id": job_id, "status": "cancellation_requested", "message": job.message}
            return {"ok": True, "job_id": job_id, "status": job.status, "message": "Job is already terminal"}

    def requeue(self, job_id: str, *, reason: str = "manual_retry", actor: str = "system", force: bool = False) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found.")
            if job.status in {"queued", "running"} and not force:
                raise HTTPException(status_code=409, detail="Cannot requeue an active job without force.")
            payload = self._build_retry_payload(job.payload, parent_job_id=job_id, reason=reason, actor=actor)
            return self._submit_locked(payload, enforce_quota=not force)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = _now_ts() + timeout if timeout else None
        while True:
            snap = self.get(job_id, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in TERMINAL_STATES:
                return snap
            if deadline is not None and _now_ts() >= deadline:
                return snap
            time.sleep(DEFAULT_POLL_SECONDS)


JOB_MANAGER = build_job_manager(
    max_workers=MAX_WORKERS,
    inmemory_factory=lambda max_workers: InMemoryJobManager(max_workers=max_workers),
)


def get_job_manager() -> InMemoryJobManager:
    return JOB_MANAGER


# ── HTTP Endpoints ──────────────────────────────────────────

@router.get("/health")
def compute_health() -> Dict[str, Any]:
    agent = get_qcviz_agent()
    provider = None
    if agent is not None:
        provider = getattr(agent, "provider", None)
    operational = {}
    if hasattr(JOB_MANAGER, "operational_summary"):
        try:
            operational = JOB_MANAGER.operational_summary()
        except Exception:
            operational = {}
    queue = dict((operational or {}).get("queue") or JOB_MANAGER.queue_summary())
    return {
        "ok": True,
        "route": "/compute",
        "planner_provider": provider or "heuristic",
        "runtime": runtime_debug_info(),
        "job_count": queue.get("total_count", 0),
        "max_workers": JOB_MANAGER.max_workers,
        "job_backend": get_job_backend_runtime(JOB_MANAGER, fallback_max_workers=JOB_MANAGER.max_workers),
        "queue": queue,
        "recovery": dict((operational or {}).get("recovery") or {}),
        "workers": list((operational or {}).get("workers") or [])[:20],
        "quota_config": {
            "max_active_per_session": _max_active_jobs_per_session(),
            "max_active_per_user": _max_active_jobs_per_user(),
        },
        "metrics_summary": _web_metrics_summary(),
        "timestamp": _now_ts(),
    }


@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    body, session_meta = _bootstrap_payload_session(
        payload,
        header_session_id=x_qcviz_session_id,
        header_session_token=x_qcviz_session_token,
    )
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token, payload=body)
    if auth_user:
        body["owner_username"] = auth_user["username"]
        body["owner_display_name"] = auth_user.get("display_name") or auth_user["username"]
    should_wait = bool(sync or wait or wait_for_result or body.get("sync") or body.get("wait") or body.get("wait_for_result"))
    snapshot = JOB_MANAGER.submit(body)
    if should_wait:
        terminal = JOB_MANAGER.wait(snapshot["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {**terminal, "session_token": session_meta["session_token"]}
    return {**snapshot, "session_token": session_meta["session_token"]}


@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    wanted_session = _resolve_request_session_id(session_id, x_qcviz_session_id)
    wanted_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    if wanted_session and not auth_user:
        validate_session_token(wanted_session, wanted_token)
    wanted_owner = _safe_str(auth_user.get("username")) if auth_user else ""
    quota = JOB_MANAGER.quota_summary(session_id=wanted_session, owner_username=wanted_owner)
    items = JOB_MANAGER.list(
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
        session_id=wanted_session,
        owner_username=wanted_owner,
    )
    if not wanted_session and not wanted_owner:
        items = []
    return {
        "items": items,
        "count": len(items),
        "queue": JOB_MANAGER.queue_summary(),
        "quota": quota,
        "session_id": wanted_session,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_payload=include_payload, include_result=include_result, include_events=include_events)
    request_session_id = _resolve_request_session_id(session_id, x_qcviz_session_id)
    request_session_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    return _assert_job_access(
        snap,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )


@router.get("/jobs/{job_id}/result")
def get_job_result(
    job_id: str,
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_result=True)
    request_session_id = _resolve_request_session_id(session_id, x_qcviz_session_id)
    request_session_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    snap = _assert_job_access(
        snap,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )
    return {
        "job_id": job_id,
        "session_id": snap.get("session_id"),
        "status": snap["status"],
        "result": snap.get("result"),
        "error": snap.get("error"),
    }


@router.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str,
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_events=True)
    request_session_id = _resolve_request_session_id(session_id, x_qcviz_session_id)
    request_session_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    snap = _assert_job_access(
        snap,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )
    return {"job_id": job_id, "session_id": snap.get("session_id"), "status": snap["status"], "events": snap.get("events", [])}


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id)
    request_session_id = _resolve_request_session_id(session_id, x_qcviz_session_id)
    request_session_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    _assert_job_access(
        snap,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )
    ok = JOB_MANAGER.delete(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True, "job_id": job_id, "session_id": request_session_id}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    session_id: Optional[str] = Query(default=None),
    session_token: Optional[str] = Query(default=None),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    """Cancel a running job by setting its cancel flag."""
    job = JOB_MANAGER.get(job_id)
    request_session_id = _resolve_request_session_id(session_id, x_qcviz_session_id)
    request_session_token = _resolve_request_session_token(session_token, x_qcviz_session_token)
    auth_user = _resolve_request_auth_user(header_auth_token=x_qcviz_auth_token)
    job = _assert_job_access(
        job,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )
    cancel_method = getattr(JOB_MANAGER, "cancel", None)
    if callable(cancel_method):
        response = cancel_method(job_id)
        if isinstance(response, Mapping):
            out = dict(response)
            out.setdefault("session_id", job.get("session_id"))
            return out
    from qcviz_mcp.compute.pyscf_runner import _CANCEL_FLAGS
    _CANCEL_FLAGS[job_id] = True
    logger.info("Cancel requested for job %s", job_id)
    return {"ok": True, "job_id": job_id, "session_id": job.get("session_id"), "message": "Cancellation requested"}


@router.post("/jobs/{job_id}/orbital_cube")
def get_orbital_cube(
    job_id: str,
    body: Dict[str, Any] = Body(...),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
    """Generate cube data for a specific orbital index on demand."""
    from qcviz_mcp.compute.pyscf_runner import generate_orbital_cube_b64, _get_cache_key
    job = JOB_MANAGER.get(job_id, include_result=True)
    request_session_id = _resolve_request_session_id(body.get("session_id"), x_qcviz_session_id, body)
    request_session_token = _resolve_request_session_token(body.get("session_token"), x_qcviz_session_token, body)
    auth_user = _resolve_request_auth_user(body.get("auth_token"), x_qcviz_auth_token, body)
    job = _assert_job_access(
        job,
        request_session_id=request_session_id,
        request_session_token=request_session_token,
        auth_user=auth_user,
    )
    result = job.get("result") or {}
    orbital_index = int(body.get("orbital_index", 0))

    # Reconstruct cache key from job result
    xyz = result.get("xyz", "")
    method = result.get("method", "B3LYP")
    basis = result.get("basis", "def2-SVP")
    charge = int(result.get("charge", 0))
    multiplicity = int(result.get("multiplicity", 1))
    cache_key = _get_cache_key(xyz, method, basis, charge, multiplicity)

    cube_b64 = generate_orbital_cube_b64(cache_key, orbital_index)
    if cube_b64 is None:
        raise HTTPException(status_code=404, detail="SCF cache expired or orbital index out of range. Re-run the calculation.")
    return {"ok": True, "cube_b64": cube_b64, "orbital_index": orbital_index}

__all__ = [
    "router",
    "JOB_MANAGER",
    "get_job_manager",
    "_extract_message",
    "_extract_session_id",
    "_extract_session_token",
    "_fallback_extract_structure_query",
    "_merge_plan_into_payload",
    "_normalize_result_contract",
    "_prepare_payload",
    "_public_plan_dict",
    "_safe_plan_message",
    "TERMINAL_STATES",
    "TERMINAL_FAILURE",
]
