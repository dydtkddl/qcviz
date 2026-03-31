"""
Middleware stack for MolChat FastAPI application.

Provides a single ``register_middleware(app)`` entry-point
that attaches every middleware in the correct order.
Order matters – outermost middleware executes first on request
and last on response.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.middleware.auth import AuthMiddleware
from app.middleware.cors import setup_cors
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.request_id import RequestIdMiddleware


def register_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI application.

    Execution order (request → response):
      1. RequestIdMiddleware   – inject X-Request-ID
      2. ErrorHandlerMiddleware – catch & format all errors
      3. RateLimiterMiddleware  – enforce per-client rate limits
      4. AuthMiddleware         – validate API key / JWT
      5. CORS                   – handled by Starlette CORSMiddleware (last added = first executed)

    Because Starlette processes middleware as a stack (LIFO),
    we add them in *reverse* execution order.
    """

    # 5. CORS (added first → outermost)
    setup_cors(app)

    # 4. Auth
    app.add_middleware(AuthMiddleware)

    # 3. Rate Limiter
    app.add_middleware(RateLimiterMiddleware)

    # 2. Error Handler
    app.add_middleware(ErrorHandlerMiddleware)

    # 1. Request ID (added last → innermost on add, but outermost on execution)
    app.add_middleware(RequestIdMiddleware)


__all__ = [
    "register_middleware",
    "RequestIdMiddleware",
    "ErrorHandlerMiddleware",
    "RateLimiterMiddleware",
    "AuthMiddleware",
    "setup_cors",
]