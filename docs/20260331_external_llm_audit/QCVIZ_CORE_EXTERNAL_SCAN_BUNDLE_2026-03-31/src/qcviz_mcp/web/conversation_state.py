"""Session-scoped continuation state for chat/compute follow-up handling."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, Mapping, Optional

_STATE_LOCK = Lock()
_INMEMORY_STATE: Dict[str, Dict[str, Any]] = {}


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


def _manager_store(manager: Optional[Any]) -> Optional[Any]:
    return getattr(manager, "store", None) if manager is not None else None


def load_conversation_state(session_id: str, *, manager: Optional[Any] = None) -> Dict[str, Any]:
    wanted = _safe_str(session_id)
    if not wanted:
        return {}
    store = _manager_store(manager)
    if store is not None and hasattr(store, "load_session_state"):
        try:
            state = store.load_session_state(wanted)
            if isinstance(state, dict):
                with _STATE_LOCK:
                    _INMEMORY_STATE[wanted] = dict(state)
                return dict(state)
        except Exception:
            pass
    with _STATE_LOCK:
        saved = _INMEMORY_STATE.get(wanted)
        return dict(saved) if saved else {}


def save_conversation_state(session_id: str, state: Mapping[str, Any], *, manager: Optional[Any] = None) -> Dict[str, Any]:
    wanted = _safe_str(session_id)
    if not wanted:
        return {}
    payload = dict(_json_safe(dict(state or {})))
    payload["session_id"] = wanted
    payload["updated_at"] = float(payload.get("updated_at") or time.time())
    with _STATE_LOCK:
        _INMEMORY_STATE[wanted] = dict(payload)
    store = _manager_store(manager)
    if store is not None and hasattr(store, "save_session_state"):
        try:
            store.save_session_state(wanted, payload)
        except Exception:
            pass
    return dict(payload)


def update_conversation_state(session_id: str, updates: Mapping[str, Any], *, manager: Optional[Any] = None) -> Dict[str, Any]:
    current = load_conversation_state(session_id, manager=manager)
    merged = dict(current)
    update_dict = dict(_json_safe(dict(updates or {})))
    for key, value in update_dict.items():
        if value in (None, "", [], {}):
            continue
        if key == "analysis_history":
            merged[key] = list(dict.fromkeys(list(merged.get(key) or []) + list(value or [])))
            continue
        merged[key] = value
    merged["session_id"] = _safe_str(session_id)
    merged["updated_at"] = time.time()
    return save_conversation_state(session_id, merged, manager=manager)


def build_execution_state(
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    job_id: str = "",
) -> Dict[str, Any]:
    payload = dict(payload or {})
    result = dict(result or {})
    session_id = _safe_str(payload.get("session_id"))
    structure_query = _safe_str(result.get("structure_query") or payload.get("structure_query") or result.get("structure_name"))
    structure_name = _safe_str(result.get("structure_name") or structure_query)
    job_type = _safe_str(result.get("job_type") or payload.get("job_type"))
    method = _safe_str(result.get("method") or payload.get("method"))
    basis = _safe_str(result.get("basis") or payload.get("basis"))
    orbital = _safe_str(result.get("selected_orbital", {}).get("label") if isinstance(result.get("selected_orbital"), Mapping) else result.get("orbital"))
    vis = dict(result.get("visualization") or {})
    available = dict(vis.get("available") or {})

    analysis_history = []
    if job_type:
        analysis_history.append(job_type)
    if job_type == "orbital_preview" and orbital:
        analysis_history.append(f"orbital:{orbital}")

    return {
        "session_id": session_id,
        "last_job_id": _safe_str(job_id),
        "last_structure_query": structure_query,
        "last_resolved_name": structure_name,
        "last_job_type": job_type,
        "last_method": method,
        "last_basis": basis,
        "last_orbital": orbital,
        "last_charge": result.get("charge", payload.get("charge")),
        "last_multiplicity": result.get("multiplicity", payload.get("multiplicity")),
        "available_result_tabs": [key for key, enabled in available.items() if enabled],
        "analysis_history": analysis_history,
        "last_resolved_artifact": {
            "structure_query": structure_query,
            "structure_name": structure_name,
            "xyz": result.get("xyz") or payload.get("xyz"),
            "atom_spec": result.get("atom_spec") or payload.get("atom_spec"),
            "formula": result.get("formula"),
            "smiles": result.get("smiles"),
            "charge": result.get("charge", payload.get("charge")),
            "multiplicity": result.get("multiplicity", payload.get("multiplicity")),
            "orbital": orbital,
        },
    }


def update_conversation_state_from_execution(
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    job_id: str = "",
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    session_id = _safe_str((payload or {}).get("session_id"))
    if not session_id:
        return {}
    execution_state = build_execution_state(payload, result, job_id=job_id)
    return update_conversation_state(session_id, execution_state, manager=manager)
