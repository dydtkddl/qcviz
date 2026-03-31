"""
ZINC-22 search provider.

Uses the ZINC REST API for commercially-available compounds.
Free, no API key. Useful for drug-like / lead-like screening sets.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.services.molecule_engine.layer0_search.base import (
    BaseSearchProvider,
    RawSearchResult,
    SearchType,
)

logger = structlog.get_logger(__name__)

_BASE = "https://zinc22api.docking.org"
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
_SEMAPHORE = asyncio.Semaphore(5)


class ZINCProvider(BaseSearchProvider):
    """ZINC-22 REST API adapter."""

    @property
    def source_name(self) -> str:
        return "zinc"

    @property
    def priority(self) -> int:
        return 40

    @property
    def timeout(self) -> float:
        return 20.0

    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        try:
            if search_type == SearchType.SMILES:
                return await self._search_by_smiles(query, limit)
            elif search_type == SearchType.NAME:
                return await self._search_by_name(query, limit)
            else:
                # ZINC mainly supports SMILES and zinc_id searches
                return await self._search_by_name(query, limit)
        except Exception as exc:
            logger.warning("zinc_search_error", query=query, error=str(exc))
            return []

    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        results = await self.search(identifier, id_type, limit=1)
        return results[0] if results else None

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE}/substances/search", params={"q": "aspirin"})
                return resp.status_code in (200, 404)
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════

    async def _search_by_name(self, name: str, limit: int) -> list[RawSearchResult]:
        url = f"{_BASE}/substances/search"
        params = {"q": name, "count": limit}
        data = await self._request(url, params)
        return self._parse_results(data)

    async def _search_by_smiles(self, smiles: str, limit: int) -> list[RawSearchResult]:
        url = f"{_BASE}/substances/search"
        params = {"q": smiles, "count": limit}
        data = await self._request(url, params)
        return self._parse_results(data)

    async def _request(
        self, url: str, params: dict | None = None
    ) -> list[dict[str, Any]] | None:
        async with _SEMAPHORE:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return None
                body = resp.json()
                # ZINC may return a list or a dict with a "substances" key
                if isinstance(body, list):
                    return body
                if isinstance(body, dict):
                    return body.get("substances", [])
                return None

    def _parse_results(
        self, data: list[dict[str, Any]] | None
    ) -> list[RawSearchResult]:
        if not data:
            return []

        results: list[RawSearchResult] = []
        for entry in data:
            zinc_id = entry.get("zinc_id", entry.get("sub_id", ""))
            smiles = entry.get("smiles", "")

            result = RawSearchResult(
                name=entry.get("name", zinc_id),
                canonical_smiles=smiles,
                inchi=entry.get("inchi"),
                inchikey=entry.get("inchikey"),
                molecular_formula=entry.get("mf"),
                molecular_weight=self._safe_float(entry.get("mwt")),
                source=self.source_name,
                source_id=str(zinc_id),
                source_url=f"https://zinc22.docking.org/substances/{zinc_id}/" if zinc_id else "",
                confidence=0.75,
                properties={
                    "logp": self._safe_float(entry.get("logp")),
                    "purchasability": entry.get("purchasability"),
                    "tranche_name": entry.get("tranche_name"),
                    "reactivity": entry.get("reactive"),
                },
            )
            results.append(result)

        return results

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None