from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import HTTPException


SESSION_TTL_SECONDS = int(os.getenv("QCVIZ_SESSION_TTL_SECONDS", str(7 * 24 * 60 * 60)))
MAX_SESSIONS = int(os.getenv("QCVIZ_MAX_SESSIONS", "5000"))


@dataclass
class SessionRecord:
    session_id: str
    session_token: str
    created_at: float
    last_seen_at: float


_SESSIONS: Dict[str, SessionRecord] = {}
_LOCK = threading.Lock()


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _new_session_id() -> str:
    return f"qcviz-{uuid.uuid4().hex}"


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _dump(record: SessionRecord, *, issued: bool) -> Dict[str, Any]:
    return {
        "session_id": record.session_id,
        "session_token": record.session_token,
        "created_at": record.created_at,
        "last_seen_at": record.last_seen_at,
        "issued": issued,
        "ttl_seconds": SESSION_TTL_SECONDS,
    }


def _prune_locked(now: Optional[float] = None) -> None:
    ts = now if now is not None else _now_ts()
    expired = [
        sid
        for sid, record in _SESSIONS.items()
        if (ts - record.last_seen_at) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _SESSIONS.pop(sid, None)

    if len(_SESSIONS) <= MAX_SESSIONS:
        return

    overflow = len(_SESSIONS) - MAX_SESSIONS
    oldest = sorted(_SESSIONS.values(), key=lambda item: item.last_seen_at)[:overflow]
    for record in oldest:
        _SESSIONS.pop(record.session_id, None)


def bootstrap_or_validate_session(
    session_id: Optional[str] = None,
    session_token: Optional[str] = None,
    *,
    allow_new: bool = True,
) -> Dict[str, Any]:
    sid = _safe_str(session_id)
    token = _safe_str(session_token)
    now = _now_ts()

    if token and not sid:
        raise HTTPException(status_code=403, detail="session_id is required when session_token is provided.")

    with _LOCK:
        _prune_locked(now)
        existing = _SESSIONS.get(sid) if sid else None

        if existing is not None:
            if not token:
                raise HTTPException(
                    status_code=403,
                    detail="This session already exists and requires the matching session_token.",
                )
            if token != existing.session_token:
                raise HTTPException(status_code=403, detail="Invalid session_token for this session.")
            existing.last_seen_at = now
            return _dump(existing, issued=False)

        if not allow_new:
            raise HTTPException(status_code=403, detail="Unknown session. Bootstrap a new session first.")

        if not sid:
            sid = _new_session_id()
        record = SessionRecord(
            session_id=sid,
            session_token=token or _new_session_token(),
            created_at=now,
            last_seen_at=now,
        )
        _SESSIONS[sid] = record
        _prune_locked(now)
        return _dump(record, issued=True)


def validate_session_token(session_id: Optional[str], session_token: Optional[str]) -> Dict[str, Any]:
    sid = _safe_str(session_id)
    token = _safe_str(session_token)
    if not sid or not token:
        raise HTTPException(status_code=403, detail="session_id and session_token are required.")
    return bootstrap_or_validate_session(sid, token, allow_new=False)


def invalidate_session(session_id: Optional[str], session_token: Optional[str] = None) -> bool:
    sid = _safe_str(session_id)
    token = _safe_str(session_token)
    if not sid:
        return False
    with _LOCK:
        record = _SESSIONS.get(sid)
        if record is None:
            return False
        if token and token != record.session_token:
            return False
        _SESSIONS.pop(sid, None)
        return True


def session_auth_health() -> Dict[str, Any]:
    with _LOCK:
        _prune_locked()
        return {
            "session_count": len(_SESSIONS),
            "ttl_seconds": SESSION_TTL_SECONDS,
            "max_sessions": MAX_SESSIONS,
        }


__all__ = [
    "bootstrap_or_validate_session",
    "invalidate_session",
    "session_auth_health",
    "validate_session_token",
]
