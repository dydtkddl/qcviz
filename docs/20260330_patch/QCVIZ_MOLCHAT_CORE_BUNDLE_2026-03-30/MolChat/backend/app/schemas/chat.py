"""
Pydantic schemas for chat / session API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════


class SessionCreate(BaseModel):
    """Request body to create a new chat session."""

    title: str | None = Field(
        default=None, max_length=512, description="Optional session title"
    )
    model_preference: str | None = Field(
        default=None, description="Preferred LLM model name"
    )


class SessionResponse(BaseModel):
    """Single session representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    model_used: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Paginated list of sessions."""

    total: int
    limit: int
    offset: int
    sessions: list[SessionResponse]


# ═══════════════════════════════════════════════
# Chat Message
# ═══════════════════════════════════════════════


class ChatRequest(BaseModel):
    """User message sent to the chat endpoint."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User's question or instruction",
    )
    session_id: uuid.UUID | None = Field(
        default=None, description="Existing session ID; omit to auto-create"
    )
    context: dict[str, Any] | None = Field(
        default=None, description="Optional context (e.g., selected molecule CID)"
    )
    stream: bool = Field(
        default=False, description="Enable streaming response via SSE"
    )


class ChatMessageResponse(BaseModel):
    """Single chat message in a response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str  # user, assistant, system, tool
    content: str
    token_count: int | None = None
    model_used: str | None = None
    tool_calls: dict[str, Any] | None = None
    metadata_extra: dict[str, Any] | None = None
    created_at: datetime


class ChatResponse(BaseModel):
    """Response to a chat request."""

    session_id: uuid.UUID
    message: ChatMessageResponse
    molecules_referenced: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="LLM confidence score"
    )
    hallucination_flags: list[str] = Field(default_factory=list)
    elapsed_ms: float

class SessionUpdate(BaseModel):
    """Request body to update a session."""
    title: str | None = Field(default=None, max_length=512)
