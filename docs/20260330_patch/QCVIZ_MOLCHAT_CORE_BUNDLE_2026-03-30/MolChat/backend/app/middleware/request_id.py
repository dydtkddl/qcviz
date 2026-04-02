"""
Request-ID middleware.

Ensures every request carries a unique identifier for tracing.

Behaviour:
  - If the client sends ``X-Request-ID``, it is reused (max 128 chars).
  - Otherwise a UUID-4 is generated.
  - The ID is stored on ``request.state.request_id`` **and** bound to
    structlog's context vars so every log line includes it automatically.
  - The response always echoes the ID back via ``X-Request-ID``.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

_MAX_ID_LENGTH = 128


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Injects and propagates a unique request ID."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # ── Resolve request ID ──
        incoming_id = request.headers.get("x-request-id")

        if incoming_id and len(incoming_id) <= _MAX_ID_LENGTH:
            request_id = incoming_id
        else:
            request_id = str(uuid.uuid4())

        # ── Attach to request state ──
        request.state.request_id = request_id

        # ── Bind to structlog context ──
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # ── Log request start ──
        logger.info(
            "request_started",
            client=request.client.host if request.client else "unknown",
        )

        # ── Process request ──
        response = await call_next(request)

        # ── Attach ID to response ──
        response.headers["X-Request-ID"] = request_id

        # ── Log request end ──
        logger.info(
            "request_completed",
            status_code=response.status_code,
        )

        return response