from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


_INIT_LOCK = threading.RLock()
PASSWORD_ITERATIONS = int(os.getenv("QCVIZ_PASSWORD_HASH_ITERATIONS", "240000"))
TOKEN_TTL_SECONDS = int(os.getenv("QCVIZ_AUTH_TOKEN_TTL_SECONDS", str(30 * 24 * 60 * 60)))


def _db_path() -> str:
    return os.getenv("QCVIZ_AUTH_DB", "/tmp/qcviz_auth.sqlite3")


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _normalize_username(username: str) -> str:
    value = _safe_str(username).lower()
    if not value:
        raise HTTPException(status_code=400, detail="username is required.")
    if len(value) < 3 or len(value) > 32:
        raise HTTPException(status_code=400, detail="username must be 3-32 characters.")
    if not all(ch.isalnum() or ch in {"_", "-", "."} for ch in value):
        raise HTTPException(status_code=400, detail="username may contain only letters, numbers, ., _, -")
    return value


def _normalize_display_name(display_name: Optional[str], username: str) -> str:
    value = _safe_str(display_name) or username
    return value[:64]


def _validate_password(password: str) -> str:
    value = _safe_str(password)
    if len(value) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters.")
    return value


def _connect() -> sqlite3.Connection:
    path = _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row["name"]) for row in rows}


def init_auth_db() -> None:
    with _INIT_LOCK:
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at REAL NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(username) REFERENCES users(username)
                )
                """
            )
            columns = _table_columns(conn, "users")
            if "role" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_username ON auth_tokens(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at)")
            conn.commit()
        _seed_default_admin()


def _seed_default_admin() -> None:
    username = _safe_str(os.getenv("QCVIZ_ADMIN_USERNAME"))
    password = _safe_str(os.getenv("QCVIZ_ADMIN_PASSWORD"))
    if not username or not password:
        return
    normalized = _normalize_username(username)
    existing = _find_user_row(normalized)
    if existing:
        with _connect() as conn:
            conn.execute("UPDATE users SET role = 'admin', disabled = 0 WHERE username = ?", (normalized,))
            conn.commit()
        return
    _create_user(normalized, password, display_name=normalized, allow_existing=False, role="admin", ensure_init=False)


def _hash_password(password: str, salt_hex: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PASSWORD_ITERATIONS,
    )
    return digest.hex()


def _user_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
        "disabled": bool(row["disabled"]) if "disabled" in row.keys() else False,
    }


def _find_user_row(username: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, display_name, password_hash, salt, role, created_at, disabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def _find_user(username: str) -> Optional[Dict[str, Any]]:
    init_auth_db()
    return _find_user_row(username)


def _create_user(
    username: str,
    password: str,
    *,
    display_name: Optional[str],
    allow_existing: bool = False,
    role: str = "user",
    ensure_init: bool = True,
) -> Dict[str, Any]:
    if ensure_init:
        init_auth_db()
    normalized = _normalize_username(username)
    secret = _validate_password(password)
    display = _normalize_display_name(display_name, normalized)
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(secret, salt_hex)
    created_at = _now_ts()
    normalized_role = "admin" if _safe_str(role).lower() == "admin" else "user"
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, salt, role, created_at, disabled)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (normalized, display, password_hash, salt_hex, normalized_role, created_at),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        if allow_existing:
            existing = _find_user(normalized)
            if existing is None:
                raise
            return {
                "username": existing["username"],
                "display_name": existing["display_name"],
                "role": existing.get("role", "user"),
                "created_at": existing["created_at"],
            }
        raise HTTPException(status_code=409, detail="username already exists.")
    return {"username": normalized, "display_name": display, "role": normalized_role, "created_at": created_at}


def register_user(username: str, password: str, display_name: Optional[str] = None) -> Dict[str, Any]:
    return _create_user(username, password, display_name=display_name, allow_existing=False, role="user")


def _issue_token(username: str) -> Dict[str, Any]:
    init_auth_db()
    token = secrets.token_urlsafe(32)
    now = _now_ts()
    expires_at = now + TOKEN_TTL_SECONDS
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, username, now, expires_at),
        )
        conn.commit()
    return {"auth_token": token, "expires_at": expires_at}


def login_user(username: str, password: str) -> Dict[str, Any]:
    normalized = _normalize_username(username)
    secret = _validate_password(password)
    row = _find_user(normalized)
    if row is None or int(row.get("disabled") or 0):
        raise HTTPException(status_code=401, detail="invalid username or password.")
    expected = row["password_hash"]
    actual = _hash_password(secret, row["salt"])
    if not secrets.compare_digest(actual, expected):
        raise HTTPException(status_code=401, detail="invalid username or password.")
    token = _issue_token(normalized)
    return {
        "user": {
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row.get("role", "user"),
            "created_at": row["created_at"],
        },
        **token,
    }


def get_auth_user(auth_token: Optional[str]) -> Optional[Dict[str, Any]]:
    token = _safe_str(auth_token)
    if not token:
        return None
    init_auth_db()
    now = _now_ts()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))
        row = conn.execute(
            """
            SELECT u.username, u.display_name, u.role, u.created_at, t.expires_at
            FROM auth_tokens t
            JOIN users u ON u.username = t.username
            WHERE t.token = ? AND t.expires_at >= ? AND u.disabled = 0
            """,
            (token, now),
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def require_auth_user(auth_token: Optional[str]) -> Dict[str, Any]:
    user = get_auth_user(auth_token)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required.")
    return user


def is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user and _safe_str(user.get("role")).lower() == "admin")


def require_admin_user(auth_token: Optional[str]) -> Dict[str, Any]:
    user = require_auth_user(auth_token)
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="admin access required.")
    return user


def revoke_auth_token(auth_token: Optional[str]) -> None:
    token = _safe_str(auth_token)
    if not token:
        return
    init_auth_db()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()


def list_users(limit: int = 200) -> List[Dict[str, Any]]:
    init_auth_db()
    capped = max(1, min(int(limit or 200), 1000))
    now = _now_ts()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))
        rows = conn.execute(
            """
            SELECT
                u.username,
                u.display_name,
                u.role,
                u.created_at,
                u.disabled,
                COALESCE(COUNT(t.token), 0) AS active_tokens
            FROM users u
            LEFT JOIN auth_tokens t ON t.username = u.username AND t.expires_at >= ?
            GROUP BY u.username, u.display_name, u.role, u.created_at, u.disabled
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            (now, capped),
        ).fetchall()
        conn.commit()
    return [
        {
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "created_at": row["created_at"],
            "disabled": bool(row["disabled"]),
            "active_tokens": int(row["active_tokens"] or 0),
        }
        for row in rows
    ]


def auth_health() -> Dict[str, Any]:
    init_auth_db()
    now = _now_ts()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
        token_count = conn.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0]
        conn.commit()
    return {
        "db_path": _db_path(),
        "user_count": int(user_count),
        "admin_count": int(admin_count),
        "active_token_count": int(token_count),
        "token_ttl_seconds": TOKEN_TTL_SECONDS,
    }


__all__ = [
    "auth_health",
    "get_auth_user",
    "init_auth_db",
    "is_admin_user",
    "list_users",
    "login_user",
    "register_user",
    "require_admin_user",
    "require_auth_user",
    "revoke_auth_token",
]
