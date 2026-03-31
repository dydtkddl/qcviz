"""
Feedback ORM model – user ratings & comments on assistant responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.molecule import Base


class Feedback(Base):
    """User feedback on a specific chat message."""

    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False  # 1-5 scale
    )
    category: Mapped[str | None] = mapped_column(
        String(50)  # accuracy, helpfulness, speed, hallucination, other
    )
    comment: Mapped[str | None] = mapped_column(Text)
    user_identifier: Mapped[str | None] = mapped_column(String(256))
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_feedback_session_rating", "session_id", "rating"),
        Index("ix_feedback_category", "category"),
    )

    def __repr__(self) -> str:
        return f"<Feedback(id={self.id}, rating={self.rating})>"