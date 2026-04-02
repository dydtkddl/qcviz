"""
Session & ChatMessage ORM models.
chat_messages is range-partitioned by month on created_at.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.molecule import Base


class Session(Base):
    """A chat session (conversation thread)."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String(512))
    user_identifier: Mapped[str | None] = mapped_column(
        String(256), index=True
    )
    model_used: Mapped[str | None] = mapped_column(String(100))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, title='{self.title}')>"


class ChatMessage(Base):
    """Individual chat message within a session.

    Designed for monthly RANGE partitioning on created_at.
    Partition management via pg_partman or manual DDL.
    """

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False  # user, assistant, system, tool
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    model_used: Mapped[str | None] = mapped_column(String(100))
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="messages")

    __table_args__ = (
        Index("ix_chatmsg_session_created", "session_id", "created_at"),
        Index("ix_chatmsg_role", "role"),
        Index("ix_chatmsg_tool_calls_gin", "tool_calls", postgresql_using="gin"),
        # NOTE: Partitioning DDL is applied via Alembic migration, not here.
        # {"postgresql_partition_by": "RANGE (created_at)"}
    )

    def __repr__(self) -> str:
        return (
            f"<ChatMessage(id={self.id}, role='{self.role}', "
            f"session={self.session_id})>"
        )