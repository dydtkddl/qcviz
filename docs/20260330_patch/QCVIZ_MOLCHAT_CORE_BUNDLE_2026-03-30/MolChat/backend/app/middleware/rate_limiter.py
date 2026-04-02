"""
Sliding-window rate limiter backed by Redis.

Algorithm:
  - Uses a sorted set per client key (IP or API-key name).
  - Each request adds the current timestamp as score+member.
  - Expired entries (outside the window) are pruned.
  - If the remaining cardinality exceeds the limit → 429.

Falls back to a no-op if Redis is unavailable so the app
does not hard-fail on cache outages.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Paths that are never rate-limited
_EXEMPT_PATHS: set[str] = {
    "/api/v1/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}


def _client_key(request: Request) -> str:
    """Derive a rate-limit bucket key from the request.

    Priority:
      1. Authenticated API-key name (set by AuthMiddleware)
      2. X-Forwarded-For first IP
      3. client.host
    """
    api_key_name: str | None = request.state.__dict__.get("api_key_name")
    if api_key_name:
        return f"rl:key:{api_key_name}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"rl:ip:{ip}"


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter middleware."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip exempt paths
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # Determine limits — per-key override or global default
        max_requests: int = getattr(
            request.state, "rate_limit", settings.RATE_LIMIT_REQUESTS
        )
        window: int = settings.RATE_LIMIT_WINDOW  # seconds

        key = _client_key(request)

        # Attempt Redis-based sliding window
        allowed, remaining, retry_after = await self._check_redis(
            key, max_requests, window
        )

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                limit=max_requests,
                window=window,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit of {max_requests} requests per {window}s exceeded",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        response = await call_next(request)

        # Attach rate-limit headers
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window)

        return response

    # ── Redis sliding window ──

    async def _check_redis(
        self,
        key: str,
        max_requests: int,
        window: int,
    ) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds).

        On Redis failure, defaults to allowed=True (fail-open).
        """
        try:
            from app.core.redis import get_redis_client

            client = get_redis_client()

            now = time.time()
            window_start = now - window

            pipe = client.pipeline(transaction=True)
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {f"{now}": now})
            # Count requests in window
            pipe.zcard(key)
            # Set TTL so stale keys expire
            pipe.expire(key, window + 1)

            results: list[Any] = await pipe.execute()
            current_count: int = results[2]

            remaining = max(0, max_requests - current_count)
            allowed = current_count <= max_requests

            # Compute retry_after from oldest entry
            retry_after = window
            if not allowed:
                oldest = await client.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_ts = oldest[0][1]
                    retry_after = max(1, int(oldest_ts + window - now))

            await client.aclose()
            return allowed, remaining, retry_after

        except Exception as exc:
            logger.warning("rate_limiter_redis_error", error=str(exc))
            # Fail-open: allow the request
            return True, max_requests, 0