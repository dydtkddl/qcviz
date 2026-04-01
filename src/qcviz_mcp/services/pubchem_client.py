"""PubChem PUG-REST async client (fallback for MolChat).

# FIX(N4): PubChem REST client - name->CID, CID->SMILES, CID->3D SDF
# FAM-03: fresh AsyncClient per request to avoid cross-loop reuse failures
# PATCH-6: capped concurrency + start-interval rate limiting.
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
_RATE_LIMIT_RPS = float(os.getenv("PUBCHEM_RATE_LIMIT_RPS", "4"))
_MAX_CONCURRENT_REQUESTS = int(os.getenv("PUBCHEM_MAX_CONCURRENT_REQUESTS", "4"))


def _encoded_name_segment(name: str) -> str:
    return quote(str(name or "").strip(), safe="")


class _TokenBucketRateLimiter:
    """Simple async limiter for request start times.

    This is intentionally conservative: it keeps request starts at or below the
    configured rate while allowing the first request after idle to pass
    immediately. A separate semaphore caps concurrent in-flight requests.
    """

    def __init__(self, max_rps: float = 4.0) -> None:
        self._max_rps = max(0.1, float(max_rps))
        self._interval = 1.0 / self._max_rps
        self._last_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            next_allowed = self._last_time + self._interval if self._last_time else 0.0
            if self._last_time and now < next_allowed:
                await asyncio.sleep(next_allowed - now)
                self._last_time = next_allowed
            else:
                self._last_time = now


class PubChemClient:
    """Async HTTP client for PubChem PUG-REST API.

    A fresh AsyncClient is created per request. Reusing one cached client across
    different asyncio.run() loops can trigger "Event loop is closed" when the
    resolver is exercised from mixed sync/async entrypoints.
    """

    def __init__(
        self,
        timeout: Optional[float] = None,
        rate_limit_rps: Optional[float] = None,
    ) -> None:
        self.timeout: float = timeout or float(
            os.getenv("PUBCHEM_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self._limiter = _TokenBucketRateLimiter(rate_limit_rps or _RATE_LIMIT_RPS)
        self._semaphore = asyncio.Semaphore(max(1, _MAX_CONCURRENT_REQUESTS))

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
        await self._limiter.acquire()

    async def _get_with_rate_limit(self, url: str, *, params: Optional[dict] = None) -> httpx.Response:
        async with self._semaphore:
            await self._rate_limit()
            async with self._build_client() as client:
                return await client.get(url, params=params)

    async def name_to_cid(self, name: str) -> Optional[int]:
        """Resolve molecule name to PubChem CID."""
        if not name or not name.strip():
            return None

        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/cids/JSON"
        try:
            resp = await self._get_with_rate_limit(url)
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
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,ConnectivitySMILES,IsomericSMILES/JSON"
        try:
            resp = await self._get_with_rate_limit(url)
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
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/SDF"
        try:
            resp = await self._get_with_rate_limit(url, params={"record_type": "3d"})
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

        url = f"{_PUBCHEM_BASE}/compound/name/{_encoded_name_segment(name)}/SDF"
        try:
            resp = await self._get_with_rate_limit(url, params={"record_type": "3d"})
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
