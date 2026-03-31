"""
MoleculeCard DB model — permanent cache for card API results.

Redis = hot cache (24h TTL), DB = permanent storage.
Flow: check Redis → check DB → build card → save both.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, String, Integer, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class MoleculeCardCache(Base):
    __tablename__ = "molecule_card_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    cid = Column(Integer, unique=True, index=True, nullable=True)
    name = Column(String(500), index=True, nullable=False)
    query = Column(String(500), nullable=False)  # original query that created this
    card_json = Column(JSONB, nullable=False)     # full card response
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_molcard_name_lower", "name"),
        Index("ix_molcard_cid", "cid"),
    )

    def __repr__(self) -> str:
        return f"<MoleculeCardCache name={self.name!r} cid={self.cid}>"
