## 파일 11/21: `src/qcviz_mcp/web/routes/compute.py` (수정)

````python
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
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner

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
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "4"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

# FIX(M2): LRU structure resolution cache
_STRUCTURE_CACHE: OrderedDict[str, Any] = OrderedDict()
_STRUCTURE_CACHE_LOCK = threading.Lock()
_STRUCTURE_CACHE_MAX = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))

# FIX(M2): Singleton resolver instances
_resolver_instance: Optional[Any] = None
_resolver_lock = threading.Lock()


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
        "intent": out.get("intent"),
        "confidence": out.get("confidence"),
        "provider": out.get("provider"),
        "notes": out.get("notes"),
        "job_type": out.get("job_type"),
        "structure_query": out.get("structure_query"),
        "structures": out.get("structures"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
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
        }
        _structure_cache_put(cache_key, out)
        return out
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
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
    normalized = _normalize_text_token(text)

    intent = "analyze"
    focus = "summary"

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

    return {
        "intent": intent,
        "confidence": 0.55,
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "structure_query": None,  # FIX(M2): resolver handles extraction
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
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
        "intent", "confidence", "provider", "notes", "job_type",
        "structure_query", "structures", "method", "basis", "charge",
        "multiplicity", "orbital", "esp_preset", "advisor_focus_tab",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out


def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message))
        except Exception as exc:
            logger.warning("Planner invocation failed; heuristic fallback: %s", exc)
    return _heuristic_plan(message, payload=payload)


def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})

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

    # FIX(M2): structure_query and structures from plan
    if not out.get("structure_query") and plan.get("structure_query"):
        out["structure_query"] = plan.get("structure_query")
    if not out.get("structures") and plan.get("structures"):
        out["structures"] = plan.get("structures")

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    # FIX(M2): If still no structure, use raw message as query (resolver will handle it)
    if not out.get("structure_query") and not out.get("xyz") and not out.get("atom_spec") and not out.get("structures"):
        raw = raw_message or _extract_message(out)
        if raw and len(raw.strip()) >= 2:
            out["structure_query"] = raw.strip()

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    return out


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
    if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
        if raw_message and len(raw_message.strip()) >= 2:
            data["structure_query"] = raw_message.strip()

    if data["job_type"] not in {"resolve_structure"}:
        if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
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


# FIX(M2): _run_direct_compute with async structure resolution
async def _run_direct_compute_async(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Resolve structure asynchronously, then run PySCF synchronously."""
    prepared = _prepare_payload(payload)

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
            resolved = await _resolve_structure_async(query)
            prepared["xyz"] = resolved["xyz"]
            if not prepared.get("structure_query") or prepared["structure_query"] == query:
                prepared["structure_query"] = resolved.get("name", query)

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
    return _normalize_result_contract(result, prepared)


def _run_direct_compute(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Sync wrapper for _run_direct_compute_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    _run_direct_compute_async(payload, progress_callback),
                )
                return future.result(timeout=300)
        else:
            return asyncio.run(_run_direct_compute_async(payload, progress_callback))
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
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        # FIX(M2): atomic file write for disk persistence
        self.cache_dir = os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache")
        self.cache_file = os.path.join(self.cache_dir, "job_history.json")
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", max_workers)
        self._load_from_disk()

    def _save_to_disk(self) -> None:
        # FIX(M5): atomic file write (tmp → rename)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp_file = self.cache_file + ".tmp"
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
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(dump_data, f)
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
                    rec.status = v.get("status", "unknown")
                    rec.progress = v.get("progress", 0)
                    rec.step = v.get("step", "")
                    rec.message = v.get("message", "")
                    rec.created_at = v.get("created_at", 0)
                    rec.started_at = v.get("started_at")
                    rec.ended_at = v.get("ended_at")
                    rec.error = v.get("error")
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
            "status": job.status,
            "user_query": job.user_query,
            "job_type": job.payload.get("job_type", ""),
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
        }
        if include_payload:
            snap["payload"] = _json_safe(dict(job.payload))
        if include_result:
            snap["result"] = _json_safe(job.result) if job.result else None
            snap["error"] = _json_safe(job.error) if job.error else None
        if include_events:
            snap["events"] = _json_safe(list(job.events))
        return snap

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = dict(payload or {})
        job_id = uuid.uuid4().hex
        user_message = _extract_message(prepared)
        record = JobRecord(job_id=job_id, payload=prepared, user_query=user_message)

        with self.lock:
            self.jobs[job_id] = record
            self._append_event(record, "job_submitted", "Job submitted", {"job_type": prepared.get("job_type")})
            record.future = self.executor.submit(self._run_job, job_id)

        self._prune()
        return self._snapshot(record)

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
                self._append_event(record, "job_progress", record.message, {"progress": record.progress, "step": record.step})

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

    def list(self, *, include_payload: bool = False, include_result: bool = False, include_events: bool = False) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
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


JOB_MANAGER = InMemoryJobManager(max_workers=MAX_WORKERS)


def get_job_manager() -> InMemoryJobManager:
    return JOB_MANAGER


# ── HTTP Endpoints ──────────────────────────────────────────

@router.get("/health")
def compute_health() -> Dict[str, Any]:
    agent = get_qcviz_agent()
    provider = None
    if agent is not None:
        provider = getattr(agent, "provider", None)
    return {
        "ok": True,
        "route": "/compute",
        "planner_provider": provider or "heuristic",
        "job_count": len(JOB_MANAGER.list()),
        "max_workers": MAX_WORKERS,
        "timestamp": _now_ts(),
    }


@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    should_wait = bool(sync or wait or wait_for_result or body.get("sync") or body.get("wait") or body.get("wait_for_result"))
    snapshot = JOB_MANAGER.submit(body)
    if should_wait:
        terminal = JOB_MANAGER.wait(snapshot["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return terminal
    return snapshot


@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    items = JOB_MANAGER.list(include_payload=include_payload, include_result=include_result, include_events=include_events)
    return {"items": items, "count": len(items)}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_payload=include_payload, include_result=include_result, include_events=include_events)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return snap


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_result=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "status": snap["status"], "result": snap.get("result"), "error": snap.get("error")}


@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_events=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "status": snap["status"], "events": snap.get("events", [])}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    ok = JOB_MANAGER.delete(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True, "job_id": job_id}


__all__ = [
    "router",
    "JOB_MANAGER",
    "get_job_manager",
    "_extract_message",
    "_extract_session_id",
    "_merge_plan_into_payload",
    "_normalize_result_contract",
    "_prepare_payload",
    "_public_plan_dict",
    "_safe_plan_message",
    "TERMINAL_STATES",
    "TERMINAL_FAILURE",
]
````

---

## 파일 12/21: `src/qcviz_mcp/web/routes/chat.py` (수정)

```python
"""Chat routes — HTTP POST + WebSocket with Gemini agent integration.

# FIX(M3): Gemini agent 연동, keepalive (25s ping, 60s timeout), cleanup
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect

from qcviz_mcp.web.routes.compute import (
    TERMINAL_FAILURE,
    TERMINAL_STATES,
    _extract_message,
    _extract_session_id,
    _merge_plan_into_payload,
    _prepare_payload,
    _public_plan_dict,
    _safe_plan_message,
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
    structure = _safe_str(payload.get("structure_query") or plan.get("structure_query"))
    method = _safe_str(payload.get("method") or plan.get("method"))
    basis = _safe_str(payload.get("basis") or plan.get("basis"))
    orbital = _safe_str(payload.get("orbital") or plan.get("orbital"))
    esp_preset = _safe_str(payload.get("esp_preset") or plan.get("esp_preset"))
    confidence = plan.get("confidence")
    provider = plan.get("provider", "")

    parts = [f"Plan: {job_type}"]
    if structure:
        parts.append(f"structure={structure}")
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


# FIX(M3): Detect follow-up molecule queries
def _detect_follow_up_molecule(message: str) -> Optional[str]:
    """Check if message references a molecule from Korean aliases or common names."""
    if not message:
        return None
    # Try Korean alias lookup
    mol = find_molecule_name(message)
    if mol:
        return mol
    # Check for common English molecule names
    common = [
        "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
        "formaldehyde", "caffeine", "aspirin", "glucose", "urea",
    ]
    lower = message.lower()
    for name in common:
        if name in lower:
            return name
    return None


async def _ws_send(websocket: WebSocket, event_type: str, **payload: Any) -> None:
    body = {"type": event_type, **_json_safe(payload)}
    await websocket.send_json(body)


async def _ws_send_error(
    websocket: WebSocket, *,
    message: str, detail: Optional[Any] = None,
    status_code: int = 400, session_id: Optional[str] = None,
) -> None:
    error_obj = {
        "message": _safe_str(message, "Request failed"),
        "detail": _json_safe(detail),
        "status_code": status_code,
        "timestamp": _now_ts(),
    }
    await _ws_send(websocket, "error", session_id=session_id, error=error_obj)


async def _stream_backend_job_until_terminal(
    websocket: WebSocket, *, job_id: str, session_id: str,
) -> None:
    manager = get_job_manager()
    seen_event_ids: set = set()
    last_state = None

    while True:
        snap = manager.get(job_id, include_result=False, include_events=True)
        if snap is None:
            await _ws_send_error(websocket, message="Job not found while streaming.", status_code=404, session_id=session_id)
            return

        state_key = (snap.get("status"), snap.get("progress"), snap.get("step"), snap.get("message"))
        if state_key != last_state:
            await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                           status=snap.get("status"), progress=snap.get("progress"),
                           step=snap.get("step"), message=snap.get("message"), job=snap)
            last_state = state_key

        for event in snap.get("events", []) or []:
            event_id = event.get("event_id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            event_type = event.get("type", "")

            if event_type == "job_progress":
                data = event.get("data") or {}
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running", progress=data.get("progress", 0.0),
                               step=data.get("step", ""), message=event.get("message", ""))
                continue
            if event_type in ("job_started", "job_completed"):
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running" if event_type == "job_started" else "completed",
                               step=event_type, message=event.get("message", ""))
                continue
            await _ws_send(websocket, "job_event", session_id=session_id, job_id=job_id, event=event)

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
                )
                return
            result = terminal.get("result") or {}
            await _ws_send(websocket, "result", session_id=session_id, job=terminal,
                           result=result, summary=_result_summary(result))
            return

        await asyncio.sleep(WS_POLL_SECONDS)


@router.get("/chat/health")
def chat_health() -> Dict[str, Any]:
    manager = get_job_manager()
    return {"ok": True, "route": "/chat", "ws_route": "/ws/chat",
            "job_backend": manager.__class__.__name__, "timestamp": _now_ts()}


@router.post("/chat")
def post_chat(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    raw_message = _extract_message(body)

    plan = _safe_plan_message(raw_message, body) if raw_message else {}
    merged = _merge_plan_into_payload(body, plan, raw_message=raw_message)
    prepared = _prepare_payload(merged)
    plan_message = _plan_status_message(plan, prepared)

    manager = get_job_manager()
    submitted = manager.submit(prepared)

    should_wait = bool(wait or wait_for_result or body.get("wait") or body.get("wait_for_result") or body.get("sync"))
    if should_wait:
        terminal = manager.wait(submitted["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        ok = terminal.get("status") not in TERMINAL_FAILURE
        return {
            "ok": ok, "message": plan_message, "plan": _public_plan_dict(plan),
            "job": terminal, "result": terminal.get("result"), "error": terminal.get("error"),
            "summary": _result_summary(terminal.get("result") or {}),
        }

    return {"ok": True, "message": plan_message, "plan": _public_plan_dict(plan), "job": submitted}


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    default_session_id = f"ws-{int(_now_ts() * 1000)}"
    session_state: Dict[str, Any] = {"last_molecule": None}

    await _ws_send(websocket, "ready", session_id=default_session_id,
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
            msg_type = str(incoming.get("type", "")).lower().strip()

            if msg_type in ("hello", "ping", "pong", "ack"):
                await _ws_send(websocket, "ack", session_id=session_id, status="connected", timestamp=_now_ts())
                continue

            user_message = _extract_message(incoming)

            await _ws_send(websocket, "ack", session_id=session_id,
                           message=user_message or "Request received.", payload=incoming, timestamp=_now_ts())

            # FIX(M3): follow-up detection with ko_aliases
            message_lower = user_message.lower() if user_message else ""
            follow_up_keywords = [
                "homo", "lumo", "orbital", "esp", "charges", "dipole",
                "energy level", "에너지", "오비탈", "전하", "최적화", "구조",
            ]
            is_follow_up = any(kw in message_lower for kw in follow_up_keywords)
            has_molecule = _detect_follow_up_molecule(user_message) is not None

            if is_follow_up and not has_molecule and not incoming.get("structure_query") and not incoming.get("xyz") and not incoming.get("atom_spec"):
                if session_state.get("last_molecule"):
                    incoming["structure_query"] = session_state["last_molecule"]
                else:
                    await _ws_send(websocket, "assistant", session_id=session_id,
                                   message="어떤 분자를 분석할까요? 분자 이름이나 구조를 먼저 알려주세요. / Which molecule would you like to analyze?",
                                   timestamp=_now_ts())
                    continue

            plan = _safe_plan_message(user_message, incoming) if user_message else {}
            merged = _merge_plan_into_payload(incoming, plan, raw_message=user_message)

            try:
                prepared = _prepare_payload(merged)
            except HTTPException as exc:
                msg = _safe_str(exc.detail, "Invalid request.")
                await _ws_send_error(websocket, message=msg, detail={"payload": merged},
                                     status_code=exc.status_code, session_id=session_id)
                continue

            if prepared.get("structure_query") or prepared.get("structure_name"):
                session_state["last_molecule"] = prepared.get("structure_query") or prepared.get("structure_name")

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
                           timestamp=_now_ts())

            manager = get_job_manager()
            try:
                submitted = manager.submit(prepared)
            except Exception as exc:
                logger.exception("Job submission failed.")
                await _ws_send_error(websocket, message="Job submission failed.",
                                     detail={"type": exc.__class__.__name__, "message": str(exc)},
                                     status_code=500, session_id=session_id)
                continue

            await _ws_send(websocket, "job_submitted", session_id=session_id, job=submitted, timestamp=_now_ts())
            await _stream_backend_job_until_terminal(websocket, job_id=submitted["job_id"], session_id=session_id)

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
```

---

이 메시지에서 파일 11(compute.py)과 12(chat.py)를 출력했습니다. 13번(pyscf_runner.py)부터 이어서 출력하겠습니다. "이어서"라고 입력해 주세요.
