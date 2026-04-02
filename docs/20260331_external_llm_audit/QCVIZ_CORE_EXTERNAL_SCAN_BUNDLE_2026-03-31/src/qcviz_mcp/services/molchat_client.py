"""MolChat API async client.

# FIX(N3): MolChat REST 클라이언트 — resolve, card, generate-3d/sdf
Base URL: http://psid.aizen.co.kr/molchat
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://psid.aizen.co.kr/molchat"
_DEFAULT_TIMEOUT = 15


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else None
        return bool(status is None or status >= 500 or status == 429)
    return False


class MolChatClient:
    """Async HTTP client for the MolChat molecule service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url: str = (
            base_url
            or os.getenv("MOLCHAT_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout: float = timeout or float(
            os.getenv("MOLCHAT_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self.api_key: Optional[str] = api_key or os.getenv("MOLCHAT_API_KEY")

    # ── lifecycle ──────────────────────────────────────────────

    def _client_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "QCViz-MCP/3.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_client(self) -> httpx.AsyncClient:
        # Build a fresh AsyncClient per request. Reusing one AsyncClient across
        # WebSocket/HTTP request loops can pin internal anyio primitives to the
        # wrong event loop and break live semantic grounding.
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            headers=self._client_headers(),
            follow_redirects=True,
        )

    async def close(self) -> None:
        return None

    # ── health ─────────────────────────────────────────────────

    async def health_live(self) -> bool:
        try:
            async with self._build_client() as client:
                resp = await client.get("/api/v1/health/live")
                return resp.status_code == 200
        except Exception:
            return False

    async def health_ready(self) -> bool:
        try:
            async with self._build_client() as client:
                resp = await client.get("/api/v1/health/ready")
                return resp.status_code == 200
        except Exception:
            return False

    # ── resolve ────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def resolve(self, names: List[str]) -> List[Dict[str, Any]]:
        """Resolve molecule names to CIDs.

        GET /api/v1/molecules/resolve?names=water,ethanol

        Returns:
            List of {name, cid} dicts. Items without CID are omitted.
        """
        if not names:
            return []

        names_param = ",".join(n.strip() for n in names if n.strip())
        async with self._build_client() as client:
            resp = await client.get(
                "/api/v1/molecules/resolve",
                params={"names": names_param},
            )
            resp.raise_for_status()
            data = resp.json()
        resolved = data.get("resolved", [])
        return [r for r in resolved if r.get("cid")]

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Search grounded molecule records from MolChat."""
        cleaned = str(query or "").strip()
        if not cleaned:
            return {"query": cleaned, "results": [], "total": 0, "resolve_method": None, "resolve_suggestions": []}

        async with self._build_client() as client:
            resp = await client.get(
                "/api/v1/molecules/search",
                params={"q": cleaned, "limit": int(limit or 5)},
            )
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            return {"query": cleaned, "results": [], "total": 0, "resolve_method": None, "resolve_suggestions": []}
        data.setdefault("query", cleaned)
        data.setdefault("results", [])
        data.setdefault("total", len(data.get("results") or []))
        data.setdefault("resolve_method", None)
        data.setdefault("resolve_suggestions", [])
        return data

    async def _search_fallback_candidates(self, query: str, limit: int = 5) -> Dict[str, Any]:
        search_payload = await self.search(query, limit=max(3, int(limit or 5)))
        candidates: List[Dict[str, Any]] = []
        for idx, row in enumerate(list(search_payload.get("results") or [])[: max(1, int(limit or 5))]):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            confidence = max(0.35, 0.85 - idx * 0.1)
            rationale_parts = []
            resolve_method = str(search_payload.get("resolve_method") or "").strip()
            resolved_query = str(search_payload.get("resolved_query") or "").strip()
            if resolve_method:
                rationale_parts.append(f"MolChat search fallback via {resolve_method}")
            if resolved_query:
                rationale_parts.append(f"resolved as {resolved_query}")
            candidates.append(
                {
                    "name": name,
                    "cid": row.get("cid"),
                    "canonical_smiles": row.get("canonical_smiles"),
                    "molecular_formula": row.get("molecular_formula"),
                    "molecular_weight": row.get("molecular_weight"),
                    "confidence": confidence,
                    "source": "molchat_search_fallback",
                    "rationale": " / ".join(rationale_parts) if rationale_parts else "MolChat search fallback",
                }
            )
        return {
            "query": str(query or "").strip(),
            "query_mode": "semantic_descriptor",
            "candidates": candidates,
            "notes": ["MolChat /molecules/interpret unavailable; used /molecules/search fallback."],
            "resolution_method": f"search_fallback:{search_payload.get('resolve_method') or 'unknown'}",
        }

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def interpret_candidates(
        self,
        query: str,
        limit: int = 5,
        *,
        locale: str = "ko",
        mode: str = "clarification",
        allow_llm: bool = True,
    ) -> Dict[str, Any]:
        """Interpret a free-form molecule description into grounded candidates."""
        cleaned = str(query or "").strip()
        if not cleaned:
            return {"query": cleaned, "query_mode": "empty", "candidates": [], "notes": []}

        try:
            async with self._build_client() as client:
                resp = await client.post(
                    "/api/v1/molecules/interpret",
                    json={
                        "query": cleaned,
                        "limit": int(limit or 5),
                        "max_candidates": int(limit or 5),
                        "locale": locale,
                        "mode": mode,
                        "allow_llm": allow_llm,
                        "context": {
                            "source_system": "qcviz",
                            "preserve_ion_pairs": True,
                        },
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {404, 405, 501}:
                logger.info(
                    "MolChat interpret endpoint unavailable (status=%s); falling back to search for %r",
                    status,
                    cleaned,
                )
                return await self._search_fallback_candidates(cleaned, limit=limit)
            raise
        if not isinstance(data, dict):
            return {"query": cleaned, "query_mode": "unknown", "candidates": [], "notes": []}
        data.setdefault("query", cleaned)
        data.setdefault("candidates", [])
        data.setdefault("notes", [])
        return data

    # ── card ───────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def get_card(self, query: str) -> Optional[Dict[str, Any]]:
        """Get molecule card (SMILES, weight, etc.).

        GET /api/v1/molecules/card?q=aspirin

        Returns:
            Card dict or None if not found.
        """
        if not query or not query.strip():
            return None

        async with self._build_client() as client:
            resp = await client.get(
                "/api/v1/molecules/card",
                params={"q": query.strip()},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return data if data.get("cid") else None

    # ── generate-3d SDF ───────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def generate_3d_sdf(
        self,
        smiles: str,
        optimize_xtb: bool = False,
    ) -> Optional[str]:
        """Generate 3D SDF from SMILES.

        GET /api/v1/molecules/generate-3d/sdf?smiles=O&optimize_xtb=false

        Returns:
            SDF text string or None.
        """
        if not smiles or not smiles.strip():
            return None

        params: Dict[str, Any] = {"smiles": smiles.strip()}
        if optimize_xtb:
            params["optimize_xtb"] = "true"

        async with self._build_client() as client:
            resp = await client.get(
                "/api/v1/molecules/generate-3d/sdf",
                params=params,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text.strip()
        if not text or "V2000" not in text:
            logger.warning(
                "MolChat generate-3d 응답에 V2000 MOL 블록 없음 / "
                "No V2000 block in MolChat generate-3d response"
            )
            return None

        return text

    # ── convenience: name → SDF pipeline ──────────────────────

    async def name_to_sdf(self, name: str, optimize_xtb: bool = False) -> Optional[str]:
        """High-level: molecule name → resolve → card → SMILES → 3D SDF.

        Returns:
            SDF text or None if any step fails.
        """
        # Step 1: resolve to CID
        resolved = await self.resolve([name])
        if not resolved:
            logger.info("MolChat resolve 실패: %s / MolChat resolve failed: %s", name, name)
            return None

        # Step 2: get card for SMILES
        card = await self.get_card(name)
        smiles: Optional[str] = None
        if card:
            smiles = card.get("canonical_smiles") or card.get("smiles")

        # If card failed, try PubChem-style CID→SMILES later (caller handles fallback)
        if not smiles:
            logger.info(
                "MolChat card에서 SMILES를 못 얻음: %s / "
                "No SMILES from MolChat card: %s",
                name, name,
            )
            return None

        # Step 3: generate 3D SDF
        sdf = await self.generate_3d_sdf(smiles, optimize_xtb=optimize_xtb)
        return sdf
