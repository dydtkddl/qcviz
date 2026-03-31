"""
Chat API routes.

Endpoints:
  POST /api/v1/chat              – send a message and receive AI response
  POST /api/v1/chat/stream       – SSE streaming response
  GET  /api/v1/chat/{session_id}/history – get conversation history
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import ChatMessage, Session
from app.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdate,
)
from app.schemas.common import ErrorResponse
from app.services.intelligence.agent import (
    AgentResponse,
    ConversationMessage,
    MolChatAgent,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat")


# ── Dependency ──

def _get_agent() -> MolChatAgent:
    return MolChatAgent()


# ═══════════════════════════════════════════════
# Chat (non-streaming)
# ═══════════════════════════════════════════════


@router.post(
    "",
    response_model=ChatResponse,
    summary="Send a chat message",
    description="Send a message to MolChat AI and receive a response with tool results.",
    responses={502: {"model": ErrorResponse}},
)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    agent: MolChatAgent = Depends(_get_agent),
) -> ChatResponse:
    log = logger.bind(session_id=str(request.session_id))
    log.info("chat_request", message_preview=request.message[:80])

    # ── Resolve or create session ──
    session = await _resolve_session(db, request.session_id, request.message)

    # ── Load conversation history ──
    history = await _load_history(db, session.id, limit=20)

    # ── Run agent ──
    agent_response: AgentResponse = await agent.chat(
        user_message=request.message,
        history=history,
        session_id=session.id,
        context=request.context,
    )

    # ── Persist messages ──
    user_msg = await _save_message(
        db,
        session_id=session.id,
        role="user",
        content=request.message,
    )
    assistant_msg = await _save_message(
        db,
        session_id=session.id,
        role="assistant",
        content=agent_response.content,
        model_used=agent_response.model_used,
        token_count=agent_response.token_count,
        tool_calls={
            "calls": [
                {
                    "tool": tc.tool_name,
                    "args": tc.arguments,
                    "success": tc.success,
                }
                for tc in agent_response.tool_calls
            ]
        } if agent_response.tool_calls else None,
    )

    # Update session message count & auto-title
    session.message_count += 2
    await _generate_title(db, session, request.message)
    await db.flush()

    return ChatResponse(
        session_id=session.id,
        message=ChatMessageResponse.model_validate(assistant_msg),
        molecules_referenced=agent_response.molecules_referenced,
        tool_results=[
            {
                "tool": tc.tool_name,
                "success": tc.success,
                "result_preview": str(tc.result)[:300],
                "elapsed_ms": tc.elapsed_ms,
            }
            for tc in agent_response.tool_calls
        ],
        confidence=agent_response.confidence,
        hallucination_flags=agent_response.hallucination_flags,
        elapsed_ms=agent_response.elapsed_ms,
    )


# ═══════════════════════════════════════════════
# Streaming
# ═══════════════════════════════════════════════


@router.post(
    "/stream",
    summary="Stream a chat response (SSE)",
    description="Server-Sent Events stream of tokens and tool results.",
)
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    agent: MolChatAgent = Depends(_get_agent),
) -> StreamingResponse:
    session = await _resolve_session(db, request.session_id, request.message)
    history = await _load_history(db, session.id, limit=20)

    # Save user message immediately
    await _save_message(db, session_id=session.id, role="user", content=request.message)

    async def event_generator():
        import json

        full_content = ""

        async for event in agent.chat_stream(
            user_message=request.message,
            history=history,
            session_id=session.id,
            context=request.context,
        ):
            event_type = event.get("type", "token")
            data = event.get("data", "")

            if event_type == "token":
                full_content += data

            payload = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {payload}\n\n"

        # Save full assistant response
        await _save_message(
            db, session_id=session.id, role="assistant", content=full_content
        )
        session.message_count += 2
        await db.flush()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════
# History
# ═══════════════════════════════════════════════


@router.get(
    "/{session_id}/history",
    response_model=list[ChatMessageResponse],
    summary="Get conversation history",
)
async def get_history(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageResponse]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        ChatMessageResponse.model_validate(m) for m in reversed(messages)
    ]




# ═══════════════════════════════════════════════
# Session CRUD
# ═══════════════════════════════════════════════


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List chat sessions",
    description="List all sessions with optional full-text search, sorted by most recent.",
)
async def list_sessions(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Return sessions ordered by updated_at desc.
    If `q` is provided, search session titles and message content.
    """
    from sqlalchemy import or_, func as sqlfunc, distinct

    base = select(Session)

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        # Search in session title OR in any message content
        msg_session_ids = (
            select(distinct(ChatMessage.session_id))
            .where(ChatMessage.content.ilike(search_term))
            .scalar_subquery()
        )
        base = base.where(
            or_(
                Session.title.ilike(search_term),
                Session.id.in_(msg_session_ids),
            )
        )

    # Count
    count_stmt = select(sqlfunc.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch
    stmt = base.order_by(Session.updated_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return SessionListResponse(
        total=total,
        limit=limit,
        offset=offset,
        sessions=[SessionResponse.model_validate(s) for s in sessions],
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Get session details",
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.model_validate(session)


@router.put(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Update session title",
)
async def update_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.title is not None:
        session.title = body.title
    await db.flush()
    return SessionResponse.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete a session and all its messages",
)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(Session).where(Session.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.flush()


# ═══════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════




async def _generate_title(db: AsyncSession, session: Session, user_message: str) -> None:
    """Generate a concise title for the session from the first message."""
    if session.message_count > 0 and session.title and not session.title.startswith(user_message[:20]):
        return  # Already has a real title from a previous turn

    # Simple heuristic: use first 60 chars, cleaned up
    import re
    title = user_message.strip()
    # Remove markdown
    title = re.sub(r'[#*_`~]', '', title)
    # Truncate smartly
    if len(title) > 60:
        # Try to break at word boundary
        title = title[:60].rsplit(' ', 1)[0] + '…'
    session.title = title or "New Chat"
    await db.flush()

async def _resolve_session(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    first_message: str,
) -> Session:
    """Find an existing session or create a new one."""
    if session_id:
        stmt = select(Session).where(Session.id == session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            return session

    # Auto-create
    title = first_message[:100].strip() or "New Chat"
    session = Session(
        id=uuid.uuid4(),
        title=title,
        message_count=0,
    )
    db.add(session)
    await db.flush()
    return session


async def _load_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    limit: int = 20,
) -> list[ConversationMessage]:
    """Load recent messages and convert to ConversationMessage."""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit * 2)  # user+assistant pairs
    )
    result = await db.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    return [
        ConversationMessage(
            role=m.role,
            content=m.content,
        )
        for m in messages
    ]


async def _save_message(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    model_used: str | None = None,
    token_count: int | None = None,
    tool_calls: dict | None = None,
) -> ChatMessage:
    """Persist a chat message to the database."""
    msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        model_used=model_used,
        token_count=token_count,
        tool_calls=tool_calls,
    )
    db.add(msg)
    await db.flush()
    return msg