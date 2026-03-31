"""
Local PostgreSQL full-text search provider.

Searches the ``molecules`` table using:
  1. tsvector ``search_vector`` for general text queries.
  2. Direct column match for SMILES, InChIKey, CID.
  3. Trigram similarity on ``name`` for fuzzy matching.

This provider is the fastest (no network round-trip) and acts
as the last-resort fallback when all remote APIs are down.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.molecule import Molecule
from app.services.molecule_engine.layer0_search.base import (
    BaseSearchProvider,
    RawSearchResult,
    SearchType,
)

logger = structlog.get_logger(__name__)


class LocalDBProvider(BaseSearchProvider):
    """PostgreSQL-backed search adapter."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def source_name(self) -> str:
        return "local"

    @property
    def priority(self) -> int:
        return 5  # Highest priority (fastest)

    @property
    def timeout(self) -> float:
        return 5.0

    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        try:
            stmt = self._build_query(query, search_type, limit)
            result = await self._db.execute(stmt)
            rows = result.scalars().all()
            return [self._row_to_result(row) for row in rows]
        except Exception as exc:
            logger.warning("local_db_search_error", query=query, error=str(exc))
            return []

    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        results = await self.search(identifier, id_type, limit=1)
        return results[0] if results else None

    async def health_check(self) -> bool:
        try:
            result = await self._db.execute(text("SELECT 1"))
            return result.scalar() == 1
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # Query builder
    # ═══════════════════════════════════════════

    def _build_query(self, query: str, search_type: SearchType, limit: int):
        """Build a SQLAlchemy select based on query type."""
        base = select(Molecule).where(Molecule.is_deleted.is_(False))

        if search_type == SearchType.CID:
            try:
                cid_val = int(query)
                return base.where(Molecule.cid == cid_val).limit(limit)
            except ValueError:
                pass

        if search_type == SearchType.INCHIKEY:
            return base.where(Molecule.inchikey == query.strip()).limit(limit)

        if search_type == SearchType.SMILES:
            return base.where(
                Molecule.canonical_smiles == query.strip()
            ).limit(limit)

        if search_type == SearchType.FORMULA:
            return base.where(
                Molecule.molecular_formula == query.strip()
            ).limit(limit)

        # NAME / CAS / default → full-text + trigram
        tsquery = func.plainto_tsquery("english", query)
        return (
            base.where(
                or_(
                    Molecule.search_vector.op("@@")(tsquery),
                    Molecule.name.ilike(f"%{query}%"),
                )
            )
            .order_by(
                func.ts_rank(Molecule.search_vector, tsquery).desc()
            )
            .limit(limit)
        )

    def _row_to_result(self, mol: Molecule) -> RawSearchResult:
        return RawSearchResult(
            name=mol.name,
            canonical_smiles=mol.canonical_smiles or "",
            inchi=mol.inchi,
            inchikey=mol.inchikey,
            cid=mol.cid,
            molecular_formula=mol.molecular_formula,
            molecular_weight=mol.molecular_weight,
            source=self.source_name,
            source_id=str(mol.id),
            source_url="",
            confidence=1.0,
            properties=mol.properties or {},
        )