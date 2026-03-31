"""
Feedback API routes.

Endpoints:
  POST /api/v1/feedback              – submit feedback on a message
  GET  /api/v1/feedback/stats        – aggregated feedback statistics
  GET  /api/v1/feedback/{session_id} – feedback for a session
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.feedback import Feedback
from app.models.session import ChatMessage
from app.schemas.common import SuccessResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/feedback")


# ── Request / Response schemas ──


class FeedbackCreate(BaseModel):
    message_id: uuid.UUID = Field(..., description="The chat message being rated")
    session_id: uuid.UUID = Field(..., description="Session the message belongs to")
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    category: str | None = Field(
        default=None,
        description="Category: accuracy, helpfulness, speed, hallucination, other",
    )
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    session_id: uuid.UUID
    rating: int
    category: str | None
    comment: str | None
    created_at: str

    class Config:
        from_attributes = True


class FeedbackStats(BaseModel):
    total_feedbacks: int
    average_rating: float | None
    rating_distribution: dict[int, int]
    category_distribution: dict[str, int]
    recent_comments: list[dict[str, Any]]


# ═══════════════════════════════════════════════
# Submit
# ═══════════════════════════════════════════════


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback on a message",
)
async def submit_feedback(
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    # Verify message exists
    msg_stmt = select(ChatMessage).where(ChatMessage.id == body.message_id)
    msg_result = await db.execute(msg_stmt)
    if msg_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    feedback = Feedback(
        id=uuid.uuid4(),
        message_id=body.message_id,
        session_id=body.session_id,
        rating=body.rating,
        category=body.category,
        comment=body.comment,
    )
    db.add(feedback)
    await db.flush()

    logger.info(
        "feedback_submitted",
        feedback_id=str(feedback.id),
        rating=body.rating,
        category=body.category,
    )
    return SuccessResponse(message="Feedback submitted successfully")


# ═══════════════════════════════════════════════
# Statistics
# ═══════════════════════════════════════════════


@router.get(
    "/stats",
    response_model=FeedbackStats,
    summary="Aggregated feedback statistics",
)
async def get_feedback_stats(
    db: AsyncSession = Depends(get_db),
) -> FeedbackStats:
    # Total & average
    total_stmt = select(func.count()).select_from(Feedback)
    total = (await db.execute(total_stmt)).scalar() or 0

    avg_stmt = select(func.avg(Feedback.rating))
    avg_rating = (await db.execute(avg_stmt)).scalar()

    # Rating distribution
    rating_dist_stmt = (
        select(Feedback.rating, func.count())
        .group_by(Feedback.rating)
        .order_by(Feedback.rating)
    )
    rating_rows = (await db.execute(rating_dist_stmt)).fetchall()
    rating_distribution = {row[0]: row[1] for row in rating_rows}

    # Category distribution
    cat_stmt = (
        select(Feedback.category, func.count())
        .where(Feedback.category.is_not(None))
        .group_by(Feedback.category)
        .order_by(func.count().desc())
    )
    cat_rows = (await db.execute(cat_stmt)).fetchall()
    category_distribution = {row[0]: row[1] for row in cat_rows}

    # Recent comments
    recent_stmt = (
        select(Feedback)
        .where(Feedback.comment.is_not(None), Feedback.comment != "")
        .order_by(Feedback.created_at.desc())
        .limit(10)
    )
    recent_result = await db.execute(recent_stmt)
    recent = [
        {
            "rating": f.rating,
            "category": f.category,
            "comment": f.comment,
            "created_at": str(f.created_at),
        }
        for f in recent_result.scalars().all()
    ]

    return FeedbackStats(
        total_feedbacks=total,
        average_rating=round(float(avg_rating), 2) if avg_rating else None,
        rating_distribution=rating_distribution,
        category_distribution=category_distribution,
        recent_comments=recent,
    )


# ═══════════════════════════════════════════════
# Per-session feedback
# ═══════════════════════════════════════════════


@router.get(
    "/{session_id}",
    response_model=list[FeedbackResponse],
    summary="Feedback for a session",
)
async def get_session_feedback(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackResponse]:
    stmt = (
        select(Feedback)
        .where(Feedback.session_id == session_id)
        .order_by(Feedback.created_at.desc())
    )
    result = await db.execute(stmt)
    feedbacks = result.scalars().all()

    return [
        FeedbackResponse(
            id=f.id,
            message_id=f.message_id,
            session_id=f.session_id,
            rating=f.rating,
            category=f.category,
            comment=f.comment,
            created_at=str(f.created_at),
        )
        for f in feedbacks
    ]