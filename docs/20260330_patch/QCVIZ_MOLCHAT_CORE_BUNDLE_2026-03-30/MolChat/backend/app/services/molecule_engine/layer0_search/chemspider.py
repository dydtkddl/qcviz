"""
ChemSpider REST API search provider.

Requires an API key (free registration at https://developer.rsc.org).
If the key is empty the provider silently returns no results.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.services.molecule_engine.layer0_search.base import (
    BaseSearchProvider,
    RawSearchResult,
    SearchType,
)

logger = structlog.get_logger(__name__)

_BASE = "https://api.rsc.org/compounds/v1"
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
_SEMAPHORE = asyncio.Semaphore(5)


class ChemSpiderProvider(BaseSearchProvider):
    """ChemSpider REST API adapter."""

    @property
    def source_name(self) -> str:
        return "chemspider"

    @property
    def priority(self) -> int:
        return 30

    @property
    def timeout(self) -> float:
        return 25.0

    def _api_key(self) -> str:
        return settings.CHEMSPIDER_API_KEY

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._api_key(),
            "Accept": "application/json",
        }

    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        if not self._api_key():
            return []

        try:
            if search_type == SearchType.NAME:
                return await self._search_by_name(query, limit)
            elif search_type == SearchType.SMILES:
                return await self._search_by_smiles(query, limit)
            elif search_type == SearchType.INCHIKEY:
                return await self._search_by_inchikey(query, limit)
            elif search_type == SearchType.FORMULA:
                return await self._search_by_formula(query, limit)
            else:
                return await self._search_by_name(query, limit)
        except Exception as exc:
            logger.warning("chemspider_search_error", query=query, error=str(exc))
            return []

    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        results = await self.search(identifier, id_type, limit=1)
        return results[0] if results else None

    async def health_check(self) -> bool:
        if not self._api_key():
            return False
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_BASE}/lookups/datasources",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # Search helpers
    # ═══════════════════════════════════════════

    async def _search_by_name(self, name: str, limit: int) -> list[RawSearchResult]:
        query_id = await self._initiate_filter(
            {"name": name, "orderBy": "recordId", "orderDirection": "ascending"}
        )
        if query_id is None:
            return []
        record_ids = await self._poll_results(query_id, limit)
        return await self._fetch_records(record_ids)

    async def _search_by_smiles(self, smiles: str, limit: int) -> list[RawSearchResult]:
        query_id = await self._initiate_filter(
            {"smiles": smiles, "orderBy": "recordId", "orderDirection": "ascending"}
        )
        if query_id is None:
            return []
        record_ids = await self._poll_results(query_id, limit)
        return await self._fetch_records(record_ids)

    async def _search_by_inchikey(self, inchikey: str, limit: int) -> list[RawSearchResult]:
        query_id = await self._initiate_filter(
            {"inchikey": inchikey}
        )
        if query_id is None:
            return []
        record_ids = await self._poll_results(query_id, limit)
        return await self._fetch_records(record_ids)

    async def _search_by_formula(self, formula: str, limit: int) -> list[RawSearchResult]:
        query_id = await self._initiate_filter(
            {"formula": formula, "orderBy": "molecularWeight", "orderDirection": "ascending"}
        )
        if query_id is None:
            return []
        record_ids = await self._poll_results(query_id, limit)
        return await self._fetch_records(record_ids)

    # ═══════════════════════════════════════════
    # ChemSpider async filter workflow
    # ═══════════════════════════════════════════

    async def _initiate_filter(self, payload: dict) -> str | None:
        """POST to /filter endpoint and return queryId."""
        async with _SEMAPHORE:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE}/filter/name" if "name" in payload
                    else f"{_BASE}/filter/smiles" if "smiles" in payload
                    else f"{_BASE}/filter/inchikey" if "inchikey" in payload
                    else f"{_BASE}/filter/formula",
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return None
                return resp.json().get("queryId")

    async def _poll_results(
        self, query_id: str, limit: int, max_attempts: int = 10
    ) -> list[int]:
        """Poll /filter/{queryId}/results until complete."""
        url = f"{_BASE}/filter/{query_id}/results"
        for attempt in range(max_attempts):
            async with _SEMAPHORE:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.get(url, headers=self._headers())
                    if resp.status_code == 200:
                        results = resp.json().get("results", [])
                        return results[:limit]
                    if resp.status_code == 202:
                        # Still processing
                        await asyncio.sleep(1.0)
                        continue
                    return []
        return []

    async def _fetch_records(self, record_ids: list[int]) -> list[RawSearchResult]:
        """Fetch full records for a list of ChemSpider record IDs."""
        results: list[RawSearchResult] = []
        for rid in record_ids:
            try:
                async with _SEMAPHORE:
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await client.get(
                            f"{_BASE}/records/{rid}/details",
                            params={"fields": "SMILES,Formula,InChI,InChIKey,MolecularWeight,CommonName"},
                            headers=self._headers(),
                        )
                        if resp.status_code != 200:
                            continue
                        data = resp.json()

                result = RawSearchResult(
                    name=data.get("commonName", ""),
                    canonical_smiles=data.get("smiles", ""),
                    inchi=data.get("inchi"),
                    inchikey=data.get("inchiKey"),
                    molecular_formula=data.get("formula"),
                    molecular_weight=data.get("molecularWeight"),
                    source=self.source_name,
                    source_id=str(rid),
                    source_url=f"http://www.chemspider.com/Chemical-Structure.{rid}.html",
                    confidence=0.85,
                )
                results.append(result)
            except Exception as exc:
                logger.debug("chemspider_record_error", rid=rid, error=str(exc))

        return results