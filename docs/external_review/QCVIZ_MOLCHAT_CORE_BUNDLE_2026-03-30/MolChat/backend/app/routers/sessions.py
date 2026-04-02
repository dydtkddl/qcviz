"""
Session management API routes.

Endpoints:
  POST /api/v1/sessions                 – create a new session
  GET  /api/v1/sessions                 – list sessions
  GET  /api/v1/sessions/{session_id}    – get session detail
  PATCH /api/v1/sessions/{session_id}   – update session (rename)
  DELETE /api/v1/sessions/{session_id}  – delete session and its messages
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import ChatMessage, Session
from app.schemas.chat import (
    SessionCreate,
    SessionListResponse,
    SessionResponse,
)
from app.schemas.common import SuccessResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions")


# ═══════════════════════════════════════════════
# Create
# ═══════════════════════════════════════════════


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat session",
)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    session = Session(
        id=uuid.uuid4(),
        title=body.title or "New Chat",
        model_used=body.model_preference,
        message_count=0,
    )
    db.add(session)
    await db.flush()

    logger.info("session_created", session_id=str(session.id))
    return SessionResponse.model_validate(session)


# ═══════════════════════════════════════════════
# List
# ═══════════════════════════════════════════════


@router.get(
    "",
    response_model=SessionListResponse,
    summary="List chat sessions",
)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    # Total count
    count_stmt = select(func.count()).select_from(Session)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginated query
    stmt = (
        select(Session)
        .order_by(Session.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return SessionListResponse(
        total=total,
        limit=limit,
        offset=offset,
        sessions=[SessionResponse.model_validate(s) for s in sessions],
    )


# ═══════════════════════════════════════════════
# Detail
# ═══════════════════════════════════════════════


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session detail",
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return SessionResponse.model_validate(session)


# ═══════════════════════════════════════════════
# Update
# ═══════════════════════════════════════════════


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Update session title",
)
async def update_session(
    session_id: uuid.UUID,
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    if body.title is not None:
        session.title = body.title
    if body.model_preference is not None:
        session.model_used = body.model_preference

    await db.flush()
    logger.info("session_updated", session_id=str(session_id))
    return SessionResponse.model_validate(session)


# ═══════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════


@router.delete(
    "/{session_id}",
    response_model=SuccessResponse,
    summary="Delete session and all messages",
)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    # Check existence
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    # Delete messages first (cascade should handle, but explicit is clearer)
    await db.execute(
        delete(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    await db.delete(session)
    await db.flush()

    logger.info("session_deleted", session_id=str(session_id))
    return SuccessResponse(message="Session deleted successfully")