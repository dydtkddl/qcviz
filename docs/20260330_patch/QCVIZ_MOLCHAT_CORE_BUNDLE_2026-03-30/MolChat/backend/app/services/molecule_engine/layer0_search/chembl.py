"""
ChEMBL REST API search provider.

Endpoint: https://www.ebi.ac.uk/chembl/api/data/molecule/search
Free, no API key required. Rate-limit is generous (~50 req/s).
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

_BASE = "https://www.ebi.ac.uk/chembl/api/data"
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
_SEMAPHORE = asyncio.Semaphore(10)


class ChEMBLProvider(BaseSearchProvider):
    """ChEMBL REST API adapter."""

    @property
    def source_name(self) -> str:
        return "chembl"

    @property
    def priority(self) -> int:
        return 20

    @property
    def timeout(self) -> float:
        return 20.0

    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        """Search ChEMBL molecules."""
        try:
            if search_type == SearchType.SMILES:
                return await self._search_by_smiles(query, limit)
            elif search_type == SearchType.INCHIKEY:
                return await self._search_by_inchikey(query, limit)
            else:
                return await self._search_by_name(query, limit)
        except Exception as exc:
            logger.warning("chembl_search_error", query=query, error=str(exc))
            return []

    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        results = await self.search(identifier, id_type, limit=1)
        return results[0] if results else None

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE}/status.json")
                return resp.status_code == 200
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # Internal search methods
    # ═══════════════════════════════════════════

    async def _search_by_name(
        self, name: str, limit: int
    ) -> list[RawSearchResult]:
        url = f"{_BASE}/molecule/search.json"
        params = {"q": name, "limit": limit}
        data = await self._request(url, params=params)
        return self._parse_molecules(data)

    async def _search_by_smiles(
        self, smiles: str, limit: int
    ) -> list[RawSearchResult]:
        url = f"{_BASE}/molecule.json"
        params = {
            "molecule_structures__canonical_smiles__flexmatch": smiles,
            "limit": limit,
        }
        data = await self._request(url, params=params)
        return self._parse_molecules(data)

    async def _search_by_inchikey(
        self, inchikey: str, limit: int
    ) -> list[RawSearchResult]:
        url = f"{_BASE}/molecule.json"
        params = {
            "molecule_structures__standard_inchi_key": inchikey,
            "limit": limit,
        }
        data = await self._request(url, params=params)
        return self._parse_molecules(data)

    async def _request(
        self, url: str, params: dict | None = None
    ) -> dict[str, Any] | None:
        async with _SEMAPHORE:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()

    def _parse_molecules(
        self, data: dict[str, Any] | None
    ) -> list[RawSearchResult]:
        if data is None:
            return []

        molecules = data.get("molecules", [])
        results: list[RawSearchResult] = []

        for mol in molecules:
            props = mol.get("molecule_properties") or {}
            structs = mol.get("molecule_structures") or {}
            chembl_id = mol.get("molecule_chembl_id", "")

            result = RawSearchResult(
                name=mol.get("pref_name") or chembl_id,
                canonical_smiles=structs.get("canonical_smiles", ""),
                inchi=structs.get("standard_inchi"),
                inchikey=structs.get("standard_inchi_key"),
                molecular_formula=props.get("full_molformula"),
                molecular_weight=self._safe_float(props.get("full_mwt")),
                source=self.source_name,
                source_id=chembl_id,
                source_url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}",
                confidence=0.9,
                properties={
                    "alogp": self._safe_float(props.get("alogp")),
                    "psa": self._safe_float(props.get("psa")),
                    "hba": self._safe_int(props.get("hba")),
                    "hbd": self._safe_int(props.get("hbd")),
                    "num_ro5_violations": self._safe_int(props.get("num_ro5_violations")),
                    "rtb": self._safe_int(props.get("rtb")),
                    "heavy_atoms": self._safe_int(props.get("heavy_atoms")),
                    "aromatic_rings": self._safe_int(props.get("aromatic_rings")),
                    "max_phase": mol.get("max_phase"),
                    "molecule_type": mol.get("molecule_type"),
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

    @staticmethod
    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None