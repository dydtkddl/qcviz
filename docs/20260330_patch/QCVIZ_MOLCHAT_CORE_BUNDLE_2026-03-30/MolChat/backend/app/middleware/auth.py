"""
Authentication middleware.

Strategy:
  1. Public paths bypass authentication entirely.
  2. If ``X-API-Key`` header is present → validate against DB.
  3. If ``Authorization: Bearer <token>`` → validate JWT.
  4. If neither is provided and the path is protected → 401.

Validated identity is attached to ``request.state`` so downstream
handlers and middleware (e.g., rate limiter) can use it.
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ── Paths that do not require authentication ──
PUBLIC_PATHS: set[str] = {
    "/api/v1/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}

PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/v1/molecules/search",
)


def _is_public(path: str) -> bool:
    """Check if the request path is publicly accessible."""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _unauthorized(message: str = "Authentication required") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error": "UNAUTHORIZED",
            "message": message,
            "status": 401,
        },
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Lightweight authentication middleware."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Initialize auth state
        request.state.authenticated = False
        request.state.auth_method = None
        request.state.api_key_name = None
        request.state.user_info = None
        request.state.rate_limit = settings.RATE_LIMIT_REQUESTS

        path = request.url.path

        # Skip auth for public paths
        if _is_public(path):
            return await call_next(request)

        # Skip auth for WebSocket upgrade (handled at router level)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # ── Try API Key ──
        api_key = request.headers.get("x-api-key")
        if api_key:
            key_info = await self._validate_api_key(api_key)
            if key_info is not None:
                request.state.authenticated = True
                request.state.auth_method = "api_key"
                request.state.api_key_name = key_info.get("name")
                request.state.rate_limit = key_info.get(
                    "rate_limit", settings.RATE_LIMIT_REQUESTS
                )
                return await call_next(request)
            return _unauthorized("Invalid API key")

        # ── Try Bearer JWT ──
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_info = self._validate_jwt(token)
            if user_info is not None:
                request.state.authenticated = True
                request.state.auth_method = "jwt"
                request.state.user_info = user_info
                return await call_next(request)
            return _unauthorized("Invalid or expired token")

        # ── No credentials provided ──
        # In development mode, allow unauthenticated access
        if settings.is_development:
            logger.debug("dev_mode_no_auth", path=path)
            return await call_next(request)

        return _unauthorized()

    async def _validate_api_key(self, raw_key: str) -> dict[str, Any] | None:
        """Validate an API key against the database.

        Returns key metadata dict or None on failure.
        """
        try:
            from app.core.database import async_session_factory
            from app.models.audit import ApiKey
            from sqlalchemy import select, update
            from datetime import datetime, timezone

            key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

            async with async_session_factory() as session:
                stmt = select(ApiKey).where(
                    ApiKey.key_hash == key_hash,
                    ApiKey.is_active.is_(True),
                )
                result = await session.execute(stmt)
                db_key = result.scalar_one_or_none()

                if db_key is None:
                    return None

                # Update last_used_at
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.id == db_key.id)
                    .values(last_used_at=datetime.now(timezone.utc))
                )
                await session.commit()

                return {
                    "key_id": str(db_key.id),
                    "name": db_key.name,
                    "rate_limit": db_key.rate_limit,
                }

        except Exception as exc:
            logger.error("api_key_validation_error", error=str(exc))
            return None

    def _validate_jwt(self, token: str) -> dict[str, Any] | None:
        """Validate a JWT token and return the payload."""
        try:
            from app.core.security import decode_access_token

            return decode_access_token(token)
        except Exception:
            return None