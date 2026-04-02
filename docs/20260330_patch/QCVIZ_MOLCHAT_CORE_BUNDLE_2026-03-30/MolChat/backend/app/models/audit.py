"""
AuditLog and ApiKey ORM models.
audit_logs is designed for RANGE partitioning on created_at.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.molecule import Base


class AuditLog(Base):
    """Immutable audit trail for security-sensitive operations."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False  # e.g., api_key.created, molecule.searched
    )
    actor: Mapped[str | None] = mapped_column(
        String(256)  # user_id, api_key name, or "system"
    )
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(256))
    details: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_action", "action"),
        Index("ix_audit_actor", "actor"),
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_details_gin", "details", postgresql_using="gin"),
        # NOTE: Partitioning DDL applied via migration.
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action='{self.action}')>"


class ApiKey(Base):
    """Hashed API keys for client authentication."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit: Mapped[int] = mapped_column(Integer, default=60)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_apikey_active", "is_active", postgresql_where=(is_active.is_(True))),
    )

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, name='{self.name}', active={self.is_active})>"
