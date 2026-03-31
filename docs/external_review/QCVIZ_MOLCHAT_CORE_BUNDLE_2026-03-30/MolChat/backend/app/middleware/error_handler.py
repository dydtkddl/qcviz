"""
Global error handler middleware.
Catches all exceptions and returns a consistent JSON error response.
"""
from __future__ import annotations

import traceback
import uuid

import structlog
from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = structlog.get_logger(__name__)


class MolChatError(Exception):
    def __init__(self, message="Internal server error",
                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                 error_code="INTERNAL_ERROR", details=None):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class MoleculeNotFoundError(MolChatError):
    def __init__(self, query: str):
        super().__init__(
            message=f"Molecule not found: {query}",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="MOLECULE_NOT_FOUND",
            details={"query": query},
        )


class ExternalServiceError(MolChatError):
    def __init__(self, service: str, reason: str = ""):
        super().__init__(
            message=f"External service error: {service}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service, "reason": reason},
        )


class RateLimitError(MolChatError):
    def __init__(self):
        super().__init__(
            message="Rate limit exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="RATE_LIMIT_EXCEEDED",
        )




class LLMError(MolChatError):
    def __init__(self, reason: str = "LLM service error"):
        super().__init__(
            message=reason,
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code="LLM_ERROR",
            details={"reason": reason},
        )


class RateLimitError(MolChatError):
    def __init__(self):
        super().__init__(
            message="Rate limit exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="RATE_LIMIT_EXCEEDED",
        )


class ValidationError(MolChatError):
    def __init__(self, message: str = "Validation error", details: dict = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            details=details or {},
        )


class AuthenticationError(MolChatError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTHENTICATION_ERROR",
        )


class CalculationError(MolChatError):
    def __init__(self, reason: str = "Calculation failed"):
        super().__init__(
            message=reason,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="CALCULATION_ERROR",
            details={"reason": reason},
        )

def _add_cors_headers(response: Response) -> Response:
    """Ensure CORS headers on ALL responses including errors."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        try:
            response = await call_next(request)
            _add_cors_headers(response)
            return response

        except MolChatError as exc:
            logger.warning("domain_error",
                           error_code=exc.error_code,
                           message=exc.message,
                           request_id=request_id)
            resp = JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": exc.error_code,
                    "message": exc.message,
                    "status": exc.status_code,
                    "request_id": request_id,
                    **exc.details,
                },
            )
            return _add_cors_headers(resp)

        except Exception as exc:
            logger.error("unhandled_error",
                         error=str(exc),
                         request_id=request_id,
                         traceback=traceback.format_exc() if settings.APP_DEBUG else None)
            resp = JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_ERROR",
                    "message": "Internal server error" if not settings.APP_DEBUG else str(exc),
                    "status": 500,
                    "request_id": request_id,
                },
            )
            return _add_cors_headers(resp)
