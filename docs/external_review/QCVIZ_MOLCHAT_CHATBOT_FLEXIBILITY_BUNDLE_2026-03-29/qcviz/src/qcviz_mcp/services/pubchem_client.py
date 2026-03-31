"""PubChem PUG-REST async client (fallback for MolChat).

# FIX(N4): PubChem REST 클라이언트 — name→CID, CID→SMILES, CID→3D SDF
Rate limit: 4 req/s (sleep 0.25s between calls).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_DEFAULT_TIMEOUT = 10
_RATE_LIMIT_DELAY = 0.25  # 4 req/s


def _encoded_name_segment(name: str) -> str:
    return quote(str(name or "").strip(), safe="")


class PubChemClient:
    """Async HTTP client for PubChem PUG-REST API."""

    def __init__(
        self,
        timeout: Optional[float] = None,
    ) -> None:
        self.timeout: float = timeout or float(
            os.getenv("PUBCHEM_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "QCViz-MCP/3.0 PubChemFallback",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        await asyncio.sleep(_RATE_LIMIT_DELAY)

    # ── name → CID ─────────────────────────────────────────────

    async def name_to_cid(self, name: str) -> Optional[int]:
        """Resolve molecule name to PubChem CID.

        GET /compound/name/{name}/cids/JSON
        """
        if not name or not name.strip():
            return None

        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/cids/JSON"
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            cids = data.get("IdentifierList", {}).get("CID", [])
            return int(cids[0]) if cids else None
        except Exception as e:
            logger.warning(
                "PubChem name_to_cid 실패: %s → %s / "
                "PubChem name_to_cid failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── CID → SMILES ──────────────────────────────────────────

    async def cid_to_smiles(self, cid: int) -> Optional[str]:
        """Get canonical SMILES from CID.

        GET /compound/cid/{cid}/property/CanonicalSMILES/JSON
        """
        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,ConnectivitySMILES,IsomericSMILES/JSON"
        try:
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
            logger.warning(
                "PubChem cid_to_smiles 실패: CID %d → %s / "
                "PubChem cid_to_smiles failed: CID %d → %s",
                cid, e, cid, e,
            )
            return None

    # ── CID → 3D SDF ─────────────────────────────────────────

    async def cid_to_sdf_3d(self, cid: int) -> Optional[str]:
        """Download 3D SDF from PubChem.

        GET /compound/cid/{cid}/SDF?record_type=3d
        """
        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/SDF"
        try:
            resp = await client.get(url, params={"record_type": "3d"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text.strip()
            if "V2000" in text:
                return text
            logger.warning(
                "PubChem SDF 응답에 V2000 블록 없음 (CID %d) / "
                "No V2000 in PubChem SDF response (CID %d)",
                cid, cid,
            )
            return None
        except Exception as e:
            logger.warning(
                "PubChem cid_to_sdf_3d 실패: CID %d → %s / "
                "PubChem cid_to_sdf_3d failed: CID %d → %s",
                cid, e, cid, e,
            )
            return None

    # ── name → 3D SDF (direct) ────────────────────────────────

    async def name_to_sdf_3d(self, name: str) -> Optional[str]:
        """Download 3D SDF directly by name (convenience shortcut).

        GET /compound/name/{name}/SDF?record_type=3d
        """
        if not name or not name.strip():
            return None

        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/SDF"
        try:
            resp = await client.get(url, params={"record_type": "3d"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text.strip()
            if "V2000" in text:
                return text
            return None
        except Exception as e:
            logger.warning(
                "PubChem name_to_sdf_3d 실패: %s → %s / "
                "PubChem name_to_sdf_3d failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── high-level: name → XYZ pipeline ──────────────────────

    async def name_to_sdf_full(self, name: str) -> Optional[str]:
        """Try direct name→SDF, then name→CID→SDF fallback.

        Returns:
            SDF text or None.
        """
        # Try direct
        sdf = await self.name_to_sdf_3d(name)
        if sdf:
            return sdf

        # Fallback: name → CID → SDF
        cid = await self.name_to_cid(name)
        if cid:
            sdf = await self.cid_to_sdf_3d(cid)
            if sdf:
                return sdf

        return None
