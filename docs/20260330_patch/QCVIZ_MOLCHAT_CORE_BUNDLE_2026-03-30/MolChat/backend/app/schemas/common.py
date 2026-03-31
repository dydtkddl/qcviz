"""
Common Pydantic schemas shared across all API endpoints.

Provides:
  • SuccessResponse   – generic success acknowledgement
  • ErrorResponse     – RFC 7807 Problem Details error
  • HealthResponse    – structured health check output
  • PaginatedResponse – generic pagination wrapper
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool = True
    message: str = "OK"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details style error response.

    Matches the format produced by ``ErrorHandlerMiddleware``.
    """

    error: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    status: int = Field(..., description="HTTP status code")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional error context"
    )
    request_id: str | None = Field(
        default=None, description="Request trace ID"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": "MOLECULE_NOT_FOUND",
                "message": "Molecule not found: aspirin123",
                "status": 404,
                "details": {"query": "aspirin123"},
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }


class HealthResponse(BaseModel):
    """Structured health check response."""

    status: str = Field(..., description="Overall status: healthy, degraded, unhealthy")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Runtime environment")
    checks: dict[str, Any] = Field(
        default_factory=dict,
        description="Individual dependency health checks",
    )
    elapsed_ms: float = Field(
        default=0.0, description="Health check execution time"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "environment": "production",
                "checks": {
                    "database": {"status": "healthy", "type": "postgresql"},
                    "cache": {"status": "healthy", "type": "redis"},
                    "ollama": {"status": "healthy", "primary_ready": True},
                },
                "elapsed_ms": 45.2,
            }
        }


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list response."""

    total: int = Field(..., description="Total number of items")
    limit: int = Field(..., description="Items per page")
    offset: int = Field(..., description="Current offset")
    items: list[Any] = Field(default_factory=list, description="Page items")

    @property
    def has_next(self) -> bool:
        return self.offset + self.limit < self.total

    @property
    def has_prev(self) -> bool:
        return self.offset > 0

    @property
    def page(self) -> int:
        return (self.offset // max(self.limit, 1)) + 1

    @property
    def total_pages(self) -> int:
        if self.limit <= 0:
            return 0
        return (self.total + self.limit - 1) // self.limit