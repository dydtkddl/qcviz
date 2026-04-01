"""PubChem PUG-REST async client (fallback for MolChat).

# FIX(N4): PubChem REST client - name->CID, CID->SMILES, CID->3D SDF
# FAM-03: fresh AsyncClient per request to avoid cross-loop reuse failures
Rate limit: 4 req/s (sleep 0.25s between calls).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_DEFAULT_TIMEOUT = 10
_RATE_LIMIT_DELAY = 0.25  # 4 req/s


def _encoded_name_segment(name: str) -> str:
    return quote(str(name or "").strip(), safe="")


class PubChemClient:
    """Async HTTP client for PubChem PUG-REST API.

    A fresh AsyncClient is created per request. Reusing one cached client across
    different asyncio.run() loops can trigger "Event loop is closed" when the
    resolver is exercised from mixed sync/async entrypoints.
    """

    def __init__(
        self,
        timeout: Optional[float] = None,
    ) -> None:
        self.timeout: float = timeout or float(
            os.getenv("PUBCHEM_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )

    @asynccontextmanager
    async def _build_client(self) -> AsyncIterator[httpx.AsyncClient]:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0 PubChemFallback",
            },
            follow_redirects=True,
        )
        try:
            yield client
        finally:
            await client.aclose()

    async def close(self) -> None:
        # Compatibility no-op. Clients are request-scoped now.
        return None

    async def _rate_limit(self) -> None:
        await asyncio.sleep(_RATE_LIMIT_DELAY)

    async def name_to_cid(self, name: str) -> Optional[int]:
        """Resolve molecule name to PubChem CID."""
        if not name or not name.strip():
            return None

        await self._rate_limit()
        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/cids/JSON"
        try:
            async with self._build_client() as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                cids = data.get("IdentifierList", {}).get("CID", [])
                return int(cids[0]) if cids else None
        except Exception as e:
            logger.warning("PubChem name_to_cid failed: %s -> %s", name, e)
            return None

    async def name_exists(self, name: str) -> bool:
        """Lightweight existence probe for a corrected name."""
        cid = await self.name_to_cid(name)
        return cid is not None

    async def cid_to_smiles(self, cid: int) -> Optional[str]:
        """Get canonical SMILES from CID."""
        await self._rate_limit()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,ConnectivitySMILES,IsomericSMILES/JSON"
        try:
            async with self._build_client() as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                props = data.get("PropertyTable", {}).get("Properties", [])
                if props:
                    row = props[0]
                    return (
                        row.get("CanonicalSMILES")
                        or row.get("IsomericSMILES")
                        or row.get("ConnectivitySMILES")
                    )
                return None
        except Exception as e:
            logger.warning("PubChem cid_to_smiles failed: CID %d -> %s", cid, e)
            return None

    async def cid_to_sdf_3d(self, cid: int) -> Optional[str]:
        """Download 3D SDF from PubChem."""
        await self._rate_limit()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/SDF"
        try:
            async with self._build_client() as client:
                resp = await client.get(url, params={"record_type": "3d"})
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                text = resp.text.strip()
                if "V2000" in text:
                    return text
                logger.warning("No V2000 in PubChem SDF response (CID %d)", cid)
                return None
        except Exception as e:
            logger.warning("PubChem cid_to_sdf_3d failed: CID %d -> %s", cid, e)
            return None

    async def name_to_sdf_3d(self, name: str) -> Optional[str]:
        """Download 3D SDF directly by name."""
        if not name or not name.strip():
            return None

        await self._rate_limit()
        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/SDF"
        try:
            async with self._build_client() as client:
                resp = await client.get(url, params={"record_type": "3d"})
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                text = resp.text.strip()
                if "V2000" in text:
                    return text
                return None
        except Exception as e:
            logger.warning("PubChem name_to_sdf_3d failed: %s -> %s", name, e)
            return None

    async def name_to_sdf_full(self, name: str) -> Optional[str]:
        """Try direct name->SDF, then name->CID->SDF fallback."""
        sdf = await self.name_to_sdf_3d(name)
        if sdf:
            return sdf

        cid = await self.name_to_cid(name)
        if cid:
            sdf = await self.cid_to_sdf_3d(cid)
            if sdf:
                return sdf

        return None
