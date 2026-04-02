"""
Authentication & authorization utilities.
API-key hashing, JWT creation/verification, dependency guards.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# ── Schemes ──
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


# ═══════════════════════════════════════════════
# API Key
# ═══════════════════════════════════════════════


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of an API key (one-way)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "mc") -> str:
    """Generate a secure random API key with prefix."""
    token = secrets.token_urlsafe(32)
    return f"{prefix}-{token}"


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dependency — validate the X-API-Key header against the database."""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    key_hash = hash_api_key(api_key)

    # Import here to avoid circular imports
    from app.models.audit import ApiKey

    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active.is_(True),
    )
    result = await db.execute(stmt)
    db_key = result.scalar_one_or_none()

    if db_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return {
        "key_id": str(db_key.id),
        "name": db_key.name,
        "rate_limit": db_key.rate_limit,
    }


# ═══════════════════════════════════════════════
# JWT
# ═══════════════════════════════════════════════


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def get_current_user(
    credentials: Any = Security(bearer_scheme),
) -> dict[str, Any]:
    """Dependency — extract user info from the Bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    return decode_access_token(credentials.credentials)

def create_api_key(prefix: str = "mc") -> tuple[str, str]:
    """Generate a new API key and return (raw_key, hashed_key) tuple."""
    raw_key = generate_api_key(prefix)
    hashed_key = hash_api_key(raw_key)
    return raw_key, hashed_key
