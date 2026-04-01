"""Session-scoped continuation state for chat/compute follow-up handling."""
from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Mapping, Optional

_STATE_MAX_SESSIONS = 1024
_STATE_TTL_SECONDS = 3600 * 4
_RESULT_INDEX_MAX = 2048
_EVICTION_SCAN_LIMIT = 64

_STATE_LOCK = Lock()
_INMEMORY_STATE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_RESULT_INDEX_LOCK = Lock()
_RESULT_INDEX: "OrderedDict[str, Dict[str, str]]" = OrderedDict()


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


def _evict_expired_state() -> int:
    """Remove expired state entries from the front of the LRU store."""
    now = time.time()
    expired: list[str] = []
    for session_id, state in _INMEMORY_STATE.items():
        if len(expired) >= _EVICTION_SCAN_LIMIT:
            break
        updated = float(state.get("updated_at") or state.get("created_at") or 0.0)
        if updated and (now - updated) > _STATE_TTL_SECONDS:
            expired.append(session_id)
            continue
        break
    for session_id in expired:
        _INMEMORY_STATE.pop(session_id, None)
    return len(expired)


def _enforce_state_max_size() -> int:
    evicted = 0
    while len(_INMEMORY_STATE) > _STATE_MAX_SESSIONS:
        _INMEMORY_STATE.popitem(last=False)
        evicted += 1
    return evicted


def _enforce_result_index_max_size() -> int:
    evicted = 0
    while len(_RESULT_INDEX) > _RESULT_INDEX_MAX:
        _RESULT_INDEX.popitem(last=False)
        evicted += 1
    return evicted


def build_canonical_result_key(
    structure_name: str,
    method: str = "",
    basis: str = "",
    job_type: str = "",
    charge: Any = 0,
    multiplicity: Any = 1,
) -> str:
    structure_token = _safe_str(structure_name).lower()
    if not structure_token:
        return ""

    default_method = "b3lyp"
    default_basis = "def2-svp"
    try:
        from qcviz_mcp.compute.pyscf_runner import DEFAULT_BASIS, DEFAULT_METHOD

        default_method = _safe_str(DEFAULT_METHOD).lower() or default_method
        default_basis = _safe_str(DEFAULT_BASIS).lower() or default_basis
    except Exception:
        pass

    try:
        charge_value = int(charge if charge not in (None, "") else 0)
    except Exception:
        charge_value = 0
    try:
        multiplicity_value = int(multiplicity if multiplicity not in (None, "") else 1)
    except Exception:
        multiplicity_value = 1
    parts = [
        structure_token,
        _safe_str(method).lower() or default_method,
        _safe_str(basis).lower() or default_basis,
        _safe_str(job_type).lower() or "analyze",
        str(charge_value),
        str(multiplicity_value),
    ]
    return ":".join(parts)


def index_completed_result(session_id: str, canonical_result_key: str, job_id: str) -> None:
    wanted_session = _safe_str(session_id)
    wanted_key = _safe_str(canonical_result_key)
    wanted_job = _safe_str(job_id)
    if not wanted_session or not wanted_key or not wanted_job:
        return
    with _RESULT_INDEX_LOCK:
        _enforce_result_index_max_size()
        session_index = _RESULT_INDEX.setdefault(wanted_session, {})
        session_index[wanted_key] = wanted_job
        _RESULT_INDEX.move_to_end(wanted_session)


def find_previous_result(session_id: str, canonical_result_key: str) -> Optional[str]:
    wanted_session = _safe_str(session_id)
    wanted_key = _safe_str(canonical_result_key)
    if not wanted_session or not wanted_key:
        return None
    with _RESULT_INDEX_LOCK:
        session_index = _RESULT_INDEX.get(wanted_session)
        if session_index is None:
            return None
        _RESULT_INDEX.move_to_end(wanted_session)
        return session_index.get(wanted_key)


def clear_result_index(session_id: str) -> None:
    wanted = _safe_str(session_id)
    if not wanted:
        return
    with _RESULT_INDEX_LOCK:
        _RESULT_INDEX.pop(wanted, None)


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
                    _evict_expired_state()
                    _INMEMORY_STATE[wanted] = dict(state)
                    _INMEMORY_STATE.move_to_end(wanted)
                    _enforce_state_max_size()
                return dict(state)
        except Exception:
            pass
    with _STATE_LOCK:
        _evict_expired_state()
        saved = _INMEMORY_STATE.get(wanted)
        if saved is not None:
            _INMEMORY_STATE.move_to_end(wanted)
        return dict(saved) if saved else {}


def save_conversation_state(session_id: str, state: Mapping[str, Any], *, manager: Optional[Any] = None) -> Dict[str, Any]:
    wanted = _safe_str(session_id)
    if not wanted:
        return {}
    payload = dict(_json_safe(dict(state or {})))
    payload["session_id"] = wanted
    payload["updated_at"] = float(payload.get("updated_at") or time.time())
    with _STATE_LOCK:
        _evict_expired_state()
        _INMEMORY_STATE[wanted] = dict(payload)
        _INMEMORY_STATE.move_to_end(wanted)
        _enforce_state_max_size()
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


def clear_conversation_state(session_id: str, *, manager: Optional[Any] = None) -> None:
    wanted = _safe_str(session_id)
    if not wanted:
        return
    with _STATE_LOCK:
        _INMEMORY_STATE.pop(wanted, None)
    clear_result_index(wanted)
    store = _manager_store(manager)
    if store is not None and hasattr(store, "clear_session_state"):
        try:
            store.clear_session_state(wanted)
        except Exception:
            pass


def state_store_stats() -> Dict[str, Any]:
    with _STATE_LOCK:
        state_count = len(_INMEMORY_STATE)
    with _RESULT_INDEX_LOCK:
        result_index_count = len(_RESULT_INDEX)
    return {
        "state_sessions": state_count,
        "state_max": _STATE_MAX_SESSIONS,
        "state_ttl_s": _STATE_TTL_SECONDS,
        "result_index_sessions": result_index_count,
        "result_index_max": _RESULT_INDEX_MAX,
    }


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
    charge = result.get("charge", payload.get("charge", 0))
    multiplicity = result.get("multiplicity", payload.get("multiplicity", 1))
    orbital = _safe_str(result.get("selected_orbital", {}).get("label") if isinstance(result.get("selected_orbital"), Mapping) else result.get("orbital"))
    vis = dict(result.get("visualization") or {})
    available = dict(vis.get("available") or {})

    analysis_history = []
    if job_type:
        analysis_history.append(job_type)
    if job_type == "orbital_preview" and orbital:
        analysis_history.append(f"orbital:{orbital}")

    canonical_result_key = build_canonical_result_key(
        structure_name=structure_name,
        method=method,
        basis=basis,
        job_type=job_type,
        charge=charge,
        multiplicity=multiplicity,
    )

    return {
        "session_id": session_id,
        "last_job_id": _safe_str(job_id),
        "last_structure_query": structure_query,
        "last_resolved_name": structure_name,
        "last_job_type": job_type,
        "last_method": method,
        "last_basis": basis,
        "last_orbital": orbital,
        "last_charge": charge,
        "last_multiplicity": multiplicity,
        "canonical_result_key": canonical_result_key,
        "available_result_tabs": [key for key, enabled in available.items() if enabled],
        "analysis_history": analysis_history,
        "last_resolved_artifact": {
            "structure_query": structure_query,
            "structure_name": structure_name,
            "xyz": result.get("xyz") or payload.get("xyz"),
            "atom_spec": result.get("atom_spec") or payload.get("atom_spec"),
            "formula": result.get("formula"),
            "smiles": result.get("smiles"),
            "charge": charge,
            "multiplicity": multiplicity,
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
    canonical_result_key = _safe_str(execution_state.get("canonical_result_key"))
    if canonical_result_key and _safe_str(job_id):
        index_completed_result(session_id, canonical_result_key, _safe_str(job_id))
    return update_conversation_state(session_id, execution_state, manager=manager)
