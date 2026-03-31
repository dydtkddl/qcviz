"""
PubChem PUG-REST search provider.

Endpoints used:
  • ``/rest/pug/compound/name/{name}/property/...``
  • ``/rest/pug/compound/smiles/{smiles}/property/...``
  • ``/rest/pug/compound/inchikey/{key}/property/...``
  • ``/rest/pug/compound/cid/{cid}/property/...``
  • ``/rest/pug/compound/cid/{cid}/record/SDF``

Rate-limit: 5 requests/second (enforced via async semaphore).
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

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PROPERTIES = (
    "IUPACName,MolecularFormula,MolecularWeight,CanonicalSMILES,"
    "InChI,InChIKey,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,"
    "RotatableBondCount,HeavyAtomCount,ExactMass,MonoisotopicMass,"
    "Charge,Complexity"
)

# PubChem rate-limit: max 5 concurrent requests
_SEMAPHORE = asyncio.Semaphore(5)
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


class PubChemProvider(BaseSearchProvider):
    """PubChem PUG-REST adapter."""

    @property
    def source_name(self) -> str:
        return "pubchem"

    @property
    def priority(self) -> int:
        return 10  # Highest priority

    @property
    def timeout(self) -> float:
        return 20.0

    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        """Search PubChem by name, SMILES, InChIKey, CID, or formula."""
        try:
            url = self._build_search_url(query, search_type)
            if url is None:
                return []

            data = await self._request(url)
            if data is None:
                return []

            results = self._parse_property_table(data, limit)

            # Fetch 3D SDF for each result with CID (parallel, best-effort)
            await self._attach_3d_sdfs(results)

            # Enrich with common names from PubChem synonyms API
            await self._enrich_with_common_names(results)

            return results

        except Exception as exc:
            logger.warning("pubchem_search_error", query=query, error=str(exc))
            return []

    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        """Fetch a single compound with full properties."""
        results = await self.search(identifier, id_type, limit=1)
        if results:
            # Also try to fetch 3D SDF
            result = results[0]
            if result.cid:
                sdf = await self._fetch_3d_sdf(result.cid)
                if sdf:
                    result.structure_3d = sdf
                    result.structure_format = "sdf"
            return result
        return None

    async def health_check(self) -> bool:
        """Check PubChem availability."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE}/compound/cid/2244/property/MolecularFormula/JSON")
                return resp.status_code == 200
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════

    def _build_search_url(self, query: str, search_type: SearchType) -> str | None:
        """Build the PUG-REST property URL for the given query type."""
        q = query.strip()
        namespace_map = {
            SearchType.NAME: f"compound/name/{q}",
            SearchType.SMILES: f"compound/smiles/{q}",
            SearchType.INCHIKEY: f"compound/inchikey/{q}",
            SearchType.CID: f"compound/cid/{q}",
            SearchType.FORMULA: f"compound/fastformula/{q}",
        }
        namespace = namespace_map.get(search_type)
        if namespace is None:
            # CAS → fall back to name search
            namespace = f"compound/name/{q}"

        return f"{_BASE}/{namespace}/property/{_PROPERTIES}/JSON"

    async def _request(self, url: str) -> dict[str, Any] | None:
        """Execute a rate-limited HTTP GET and return parsed JSON."""
        async with _SEMAPHORE:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                logger.debug("pubchem_request", url=url)
                resp = await client.get(url)

                if resp.status_code == 404:
                    return None
                if resp.status_code == 503:
                    # PubChem throttling — backoff and retry once
                    logger.warning("pubchem_throttled", url=url)
                    await asyncio.sleep(1.0)
                    resp = await client.get(url)

                resp.raise_for_status()
                return resp.json()

    def _parse_property_table(
        self, data: dict[str, Any], limit: int
    ) -> list[RawSearchResult]:
        """Parse PubChem PropertyTable JSON into RawSearchResult list."""
        table = data.get("PropertyTable", {})
        properties_list = table.get("Properties", [])

        results: list[RawSearchResult] = []
        for entry in properties_list[:limit]:
            cid = entry.get("CID")
            result = RawSearchResult(
                name=entry.get("IUPACName", ""),
                canonical_smiles=(entry.get("CanonicalSMILES") or entry.get("SMILES") or entry.get("ConnectivitySMILES") or ""),
                inchi=entry.get("InChI"),
                inchikey=entry.get("InChIKey"),
                cid=cid,
                molecular_formula=entry.get("MolecularFormula"),
                molecular_weight=entry.get("MolecularWeight"),
                source=self.source_name,
                source_id=str(cid) if cid else "",
                source_url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else "",
                confidence=1.0,
                properties={
                    "xlogp": entry.get("XLogP"),
                    "tpsa": entry.get("TPSA"),
                    "hbond_donor": entry.get("HBondDonorCount"),
                    "hbond_acceptor": entry.get("HBondAcceptorCount"),
                    "rotatable_bonds": entry.get("RotatableBondCount"),
                    "heavy_atom_count": entry.get("HeavyAtomCount"),
                    "exact_mass": entry.get("ExactMass"),
                    "monoisotopic_mass": entry.get("MonoisotopicMass"),
                    "charge": entry.get("Charge"),
                    "complexity": entry.get("Complexity"),
                },
            )
            results.append(result)

        return results

    async def _attach_3d_sdfs(self, results: list) -> None:
        """Best-effort parallel 3D SDF fetch for search results."""
        import asyncio as _aio

        async def _fetch_one(r) -> None:
            if r.cid:
                try:
                    sdf = await _aio.wait_for(
                        self._fetch_3d_sdf(r.cid),
                        timeout=5.0,
                    )
                    if sdf and len(sdf) > 10:
                        r.structure_3d = sdf
                        r.structure_format = "sdf"
                except _aio.TimeoutError:
                    logger.debug("pubchem_3d_timeout", cid=r.cid)
                except Exception as exc:
                    logger.debug("pubchem_3d_skip", cid=r.cid, error=str(exc))

        tasks = [_fetch_one(r) for r in results]
        if tasks:
            await _aio.gather(*tasks, return_exceptions=True)

    async def _fetch_3d_sdf(self, cid: int) -> str | None:
        """Download the 3D conformer SDF from PubChem."""
        url = f"{_BASE}/compound/cid/{cid}/record/SDF/?record_type=3d&response_type=save"
        try:
            async with _SEMAPHORE:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    return None
        except Exception as exc:
            logger.debug("pubchem_3d_sdf_error", cid=cid, error=str(exc))
            return None

    async def _enrich_with_common_names(self, results: list[RawSearchResult]) -> None:
        """Fetch PubChem synonyms and use the first (common) name instead of IUPAC."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for r in results:
                if not r.cid:
                    continue
                try:
                    async with _SEMAPHORE:
                        resp = await client.get(
                            f"{_BASE}/compound/cid/{r.cid}/synonyms/JSON"
                        )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    synonyms = (
                        data.get("InformationList", {})
                        .get("Information", [{}])[0]
                        .get("Synonym", [])
                    )
                    if synonyms:
                        # First synonym is usually the common/preferred name
                        common = synonyms[0]
                        # Store IUPAC in properties, use common as name
                        r.properties["iupac_name"] = r.name
                        r.name = common
                        # Also store top synonyms for future use
                        r.properties["synonyms"] = synonyms[:10]
                except Exception as exc:
                    logger.debug("synonym_fetch_error", cid=r.cid, error=str(exc))
