## 파일 1/21: `src/qcviz_mcp/services/__init__.py` (신규)

```python
"""QCViz-MCP v3 services package.

# FIX(N0): 신규 services 패키지 초기화
Provides molecule resolution, API clients, and Gemini agent integration.
"""
from __future__ import annotations

from .ko_aliases import KO_TO_EN, translate  # noqa: F401
from .sdf_converter import sdf_to_xyz, merge_sdfs, sdf_to_atoms_list  # noqa: F401
from .molchat_client import MolChatClient  # noqa: F401
from .pubchem_client import PubChemClient  # noqa: F401
from .ion_pair_handler import IonPairResult, ION_ALIASES, is_ion_pair, resolve_ion_pair  # noqa: F401
from .structure_resolver import StructureResolver, StructureResult  # noqa: F401
from .gemini_agent import GeminiAgent, GeminiResult  # noqa: F401

__all__ = [
    "KO_TO_EN",
    "translate",
    "sdf_to_xyz",
    "merge_sdfs",
    "sdf_to_atoms_list",
    "MolChatClient",
    "PubChemClient",
    "IonPairResult",
    "ION_ALIASES",
    "is_ion_pair",
    "resolve_ion_pair",
    "StructureResolver",
    "StructureResult",
    "GeminiAgent",
    "GeminiResult",
]
```

---

## 파일 2/21: `src/qcviz_mcp/services/ko_aliases.py` (신규)

```python
"""Korean → English molecule name alias dictionary and translator.

# FIX(N1): 한국어 분자명 30개 매핑 + 조사 제거 + 번역 함수
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# ── 한국어→영어 분자명 매핑 (30개) ──────────────────────────────
KO_TO_EN: Dict[str, str] = {
    "물": "water",
    "에탄올": "ethanol",
    "메탄올": "methanol",
    "메탄": "methane",
    "에탄": "ethane",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "아세톤": "acetone",
    "암모니아": "ammonia",
    "이산화탄소": "carbon dioxide",
    "일산화탄소": "carbon monoxide",
    "포름알데히드": "formaldehyde",
    "아세트산": "acetic acid",
    "글리신": "glycine",
    "요소": "urea",
    "피리딘": "pyridine",
    "페놀": "phenol",
    "아스피린": "aspirin",
    "카페인": "caffeine",
    "포도당": "glucose",
    "과산화수소": "hydrogen peroxide",
    "황산": "sulfuric acid",
    "염산": "hydrochloric acid",
    "수산화나트륨": "sodium hydroxide",
    "아세틸렌": "acetylene",
    "프로판": "propane",
    "부탄": "butane",
    "나프탈렌": "naphthalene",
    "글루탐산": "glutamic acid",
    "세로토닌": "serotonin",
}

# ── 한국어 조사 패턴 (제거 대상) ──────────────────────────────
_JOSA_PATTERN = re.compile(
    r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지|처럼|같은|하고|이랑|랑|과|와)\s*$"
)

_JOSA_INLINE_PATTERN = re.compile(
    r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지|처럼|같은|하고|이랑|랑|과|와)(?=\s)"
)


def _strip_josa(text: str) -> str:
    """Remove trailing Korean postpositions (조사)."""
    result = text.strip()
    for _ in range(3):  # iterative strip in case of stacking
        prev = result
        result = _JOSA_PATTERN.sub("", result).strip()
        if result == prev:
            break
    return result


def translate(text: str) -> str:
    """Translate Korean molecule names to English in the input text.

    - Longest-match-first replacement to avoid partial matches.
    - Strips common Korean postpositions before and after replacement.

    Args:
        text: User input that may contain Korean molecule names.

    Returns:
        Text with Korean molecule names replaced by English equivalents.
    """
    if not text or not text.strip():
        return text

    result = text.strip()

    # Sort by length descending for longest-match-first
    sorted_aliases = sorted(KO_TO_EN.items(), key=lambda x: len(x[0]), reverse=True)

    for ko_name, en_name in sorted_aliases:
        if ko_name in result:
            # Replace with surrounding josa removal
            # Pattern: (optional josa before) + ko_name + (optional josa after)
            pattern = re.compile(
                rf"({re.escape(ko_name)})"
                r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지)?"
            )
            result = pattern.sub(en_name, result)

    return result.strip()


def find_molecule_name(text: str) -> Optional[str]:
    """Find and return the English molecule name from Korean text.

    Returns:
        The English molecule name if found, None otherwise.
    """
    if not text:
        return None

    cleaned = _strip_josa(text.strip())

    # Longest match first
    sorted_aliases = sorted(KO_TO_EN.items(), key=lambda x: len(x[0]), reverse=True)

    for ko_name, en_name in sorted_aliases:
        if ko_name in cleaned:
            return en_name

    return None
```

---

## 파일 3/21: `src/qcviz_mcp/services/sdf_converter.py` (신규)

```python
"""SDF (V2000 MOL) → XYZ converter and multi-SDF merger.

# FIX(N2): SDF→XYZ 변환, 다중 SDF 합치기, PySCF 입력용 atoms list 생성
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 원자번호 → 원소기호 (fallback) ─────────────────────────────
_ATOMIC_SYMBOLS: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
    9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
    16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 26: "Fe", 29: "Cu",
    30: "Zn", 35: "Br", 53: "I",
}


def _parse_mol_block(sdf_text: str) -> List[Tuple[str, float, float, float]]:
    """Parse V2000 MOL block from SDF text.

    Returns:
        List of (symbol, x, y, z) tuples.

    Raises:
        ValueError: If the SDF cannot be parsed.
    """
    if not sdf_text or not sdf_text.strip():
        raise ValueError("빈 SDF 텍스트입니다 / Empty SDF text")

    lines = sdf_text.strip().splitlines()

    # Find counts line (line index 3 in standard V2000, but be flexible)
    counts_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # V2000 counts line pattern: "  N  M  ... V2000"
        if stripped.endswith("V2000") or re.match(r"^\s*\d+\s+\d+\s+", stripped):
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    int(parts[0])
                    int(parts[1])
                    counts_idx = i
                    break
                except ValueError:
                    continue

    if counts_idx is None:
        raise ValueError(
            "V2000 MOL 블록의 counts 라인을 찾을 수 없습니다 / "
            "Cannot find V2000 counts line in SDF"
        )

    counts_parts = lines[counts_idx].split()
    n_atoms = int(counts_parts[0])
    # n_bonds = int(counts_parts[1])  # not needed for XYZ

    if n_atoms <= 0:
        raise ValueError(
            f"원자 수가 0 이하입니다: {n_atoms} / Atom count is <= 0: {n_atoms}"
        )

    atom_start = counts_idx + 1
    atoms: List[Tuple[str, float, float, float]] = []

    for i in range(n_atoms):
        line_idx = atom_start + i
        if line_idx >= len(lines):
            raise ValueError(
                f"SDF 원자 라인 부족: {i+1}/{n_atoms} / "
                f"Not enough atom lines: {i+1}/{n_atoms}"
            )

        parts = lines[line_idx].split()
        if len(parts) < 4:
            raise ValueError(
                f"원자 라인 파싱 실패 (라인 {line_idx}): '{lines[line_idx]}' / "
                f"Failed to parse atom line {line_idx}"
            )

        try:
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
        except ValueError as e:
            raise ValueError(
                f"좌표 파싱 실패 (라인 {line_idx}): {e} / "
                f"Coordinate parse error at line {line_idx}: {e}"
            ) from e

        symbol = parts[3].strip()
        # Clean up symbol (some SDF files have extra characters)
        symbol = re.sub(r"[^A-Za-z]", "", symbol)
        if not symbol:
            raise ValueError(
                f"원소 기호가 비어있습니다 (라인 {line_idx}) / "
                f"Empty element symbol at line {line_idx}"
            )

        # Capitalize properly
        symbol = symbol[0].upper() + symbol[1:].lower() if len(symbol) > 1 else symbol.upper()
        atoms.append((symbol, x, y, z))

    return atoms


def sdf_to_xyz(sdf_text: str, comment: str = "Converted from SDF") -> str:
    """Convert SDF (V2000) text to XYZ format string.

    Args:
        sdf_text: SDF/MOL text content.
        comment: Comment line for XYZ header.

    Returns:
        XYZ format string (natoms\\ncomment\\nsymbol x y z\\n...).

    Raises:
        ValueError: If SDF parsing fails.
    """
    atoms = _parse_mol_block(sdf_text)
    n = len(atoms)

    lines = [str(n), comment]
    for symbol, x, y, z in atoms:
        lines.append(f"{symbol:2s} {x: .8f} {y: .8f} {z: .8f}")

    return "\n".join(lines)


def sdf_to_atoms_list(
    sdf_text: str,
) -> List[Tuple[str, Tuple[float, float, float]]]:
    """Convert SDF to PySCF-compatible atoms list.

    Returns:
        List of (symbol, (x, y, z)) tuples suitable for ``gto.M(atom=...)``.
    """
    raw_atoms = _parse_mol_block(sdf_text)
    return [(sym, (x, y, z)) for sym, x, y, z in raw_atoms]


def merge_sdfs(
    sdf_list: List[str],
    offset: float = 5.0,
    comment: str = "Merged ion pair",
) -> str:
    """Merge multiple SDF structures into a single XYZ with coordinate offsets.

    Each subsequent SDF's atoms are offset along the X-axis by ``offset`` Å
    to prevent atom overlap.

    Args:
        sdf_list: List of SDF text strings.
        offset: X-axis offset in Ångströms between fragments.
        comment: Comment line for XYZ header.

    Returns:
        Combined XYZ format string.

    Raises:
        ValueError: If any SDF parsing fails or list is empty.
    """
    if not sdf_list:
        raise ValueError("빈 SDF 리스트입니다 / Empty SDF list")

    all_atoms: List[Tuple[str, float, float, float]] = []
    current_offset = 0.0

    for idx, sdf_text in enumerate(sdf_list):
        try:
            atoms = _parse_mol_block(sdf_text)
        except ValueError as e:
            raise ValueError(
                f"SDF #{idx+1} 파싱 실패: {e} / "
                f"Failed to parse SDF #{idx+1}: {e}"
            ) from e

        for symbol, x, y, z in atoms:
            all_atoms.append((symbol, x + current_offset, y, z))

        if atoms:
            # Calculate max X extent for this fragment
            max_x = max(x for _, x, _, _ in atoms)
            current_offset = max_x + offset

    n = len(all_atoms)
    lines = [str(n), comment]
    for symbol, x, y, z in all_atoms:
        lines.append(f"{symbol:2s} {x: .8f} {y: .8f} {z: .8f}")

    return "\n".join(lines)
```

---

## 파일 4/21: `src/qcviz_mcp/services/molchat_client.py` (신규)

```python
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
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://psid.aizen.co.kr/molchat"
_DEFAULT_TIMEOUT = 15


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
        self._client: Optional[httpx.AsyncClient] = None

    # ── lifecycle ──────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── health ─────────────────────────────────────────────────

    async def health_live(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/health/live")
            return resp.status_code == 200
        except Exception:
            return False

    async def health_ready(self) -> bool:
        try:
            client = await self._get_client()
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

        client = await self._get_client()
        names_param = ",".join(n.strip() for n in names if n.strip())
        resp = await client.get(
            "/api/v1/molecules/resolve",
            params={"names": names_param},
        )
        resp.raise_for_status()
        data = resp.json()
        resolved = data.get("resolved", [])
        return [r for r in resolved if r.get("cid")]

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

        client = await self._get_client()
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

        client = await self._get_client()
        params: Dict[str, Any] = {"smiles": smiles.strip()}
        if optimize_xtb:
            params["optimize_xtb"] = "true"

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
```

---

## 파일 5/21: `src/qcviz_mcp/services/pubchem_client.py` (신규)

```python
"""PubChem PUG-REST async client (fallback for MolChat).

# FIX(N4): PubChem REST 클라이언트 — name→CID, CID→SMILES, CID→3D SDF
Rate limit: 4 req/s (sleep 0.25s between calls).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_DEFAULT_TIMEOUT = 10
_RATE_LIMIT_DELAY = 0.25  # 4 req/s


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
        url = f"{_PUBCHEM_BASE}/compound/name/{httpx.URL(name.strip())}/cids/JSON"
        # Use manual URL to avoid double encoding
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
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES/JSON"
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                return props[0].get("CanonicalSMILES")
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
        url = f"{_PUBCHEM_BASE}/compound/name/{httpx.URL(name.strip())}/SDF"
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
```

---

## 파일 6/21: `src/qcviz_mcp/services/ion_pair_handler.py` (신규)

```python
"""Ion pair abbreviation dictionary and multi-ion resolve logic.

# FIX(N5): 이온쌍 별칭 27개 + 이온쌍 감지 + 개별 resolve + SDF merge
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import merge_sdfs, sdf_to_xyz

logger = logging.getLogger(__name__)

# ── 이온쌍 약어 사전 (27개) ────────────────────────────────────
# format: abbreviation → {"name": full PubChem-searchable name, "type": "cation"|"anion", "default_charge": int}
ION_ALIASES: Dict[str, Dict[str, Any]] = {
    # Cations
    "EMIM":  {"name": "1-ethyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BMIM":  {"name": "1-butyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "HMIM":  {"name": "1-hexyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "OMIM":  {"name": "1-octyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BPy":   {"name": "1-butylpyridinium", "type": "cation", "default_charge": 1},
    "DEME":  {"name": "N,N-diethyl-N-methyl-N-(2-methoxyethyl)ammonium", "type": "cation", "default_charge": 1},
    "P14":   {"name": "N-butyl-N-methylpyrrolidinium", "type": "cation", "default_charge": 1},
    "TEA":   {"name": "tetraethylammonium", "type": "cation", "default_charge": 1},
    "TBA":   {"name": "tetrabutylammonium", "type": "cation", "default_charge": 1},
    "Li":    {"name": "lithium ion", "type": "cation", "default_charge": 1},
    "Na":    {"name": "sodium ion", "type": "cation", "default_charge": 1},
    "K":     {"name": "potassium ion", "type": "cation", "default_charge": 1},
    # Anions
    "TFSI":  {"name": "bis(trifluoromethylsulfonyl)imide", "type": "anion", "default_charge": -1},
    "BF4":   {"name": "tetrafluoroborate", "type": "anion", "default_charge": -1},
    "PF6":   {"name": "hexafluorophosphate", "type": "anion", "default_charge": -1},
    "OTf":   {"name": "trifluoromethanesulfonate", "type": "anion", "default_charge": -1},
    "DCA":   {"name": "dicyanamide", "type": "anion", "default_charge": -1},
    "SCN":   {"name": "thiocyanate", "type": "anion", "default_charge": -1},
    "OAc":   {"name": "acetate", "type": "anion", "default_charge": -1},
    "Cl":    {"name": "chloride", "type": "anion", "default_charge": -1},
    "Br":    {"name": "bromide", "type": "anion", "default_charge": -1},
    "I":     {"name": "iodide", "type": "anion", "default_charge": -1},
    "NO3":   {"name": "nitrate", "type": "anion", "default_charge": -1},
    "HSO4":  {"name": "hydrogen sulfate", "type": "anion", "default_charge": -1},
    "FSI":   {"name": "bis(fluorosulfonyl)imide", "type": "anion", "default_charge": -1},
    "BOB":   {"name": "bis(oxalato)borate", "type": "anion", "default_charge": -1},
    "FAP":   {"name": "tris(pentafluoroethyl)trifluorophosphate", "type": "anion", "default_charge": -1},
}


@dataclass
class IonPairResult:
    """Result of ion-pair resolution."""
    xyz: str = ""
    total_charge: int = 0
    smiles_list: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    source: str = "ion_pair_handler"
    individual_sdfs: List[str] = field(default_factory=list)


def expand_alias(name: str) -> Dict[str, Any]:
    """Expand an ion abbreviation to its full searchable name.

    Returns:
        Dict with 'name', 'type', 'default_charge' or the original name
        with charge 0 if not an alias.
    """
    clean = name.strip().rstrip("+-")
    if clean in ION_ALIASES:
        return dict(ION_ALIASES[clean])

    # Case-insensitive lookup
    upper = clean.upper()
    for key, val in ION_ALIASES.items():
        if key.upper() == upper:
            return dict(val)

    # Not a known alias — return as-is with neutral charge
    return {"name": name.strip(), "type": "unknown", "default_charge": 0}


def is_ion_pair(structures: List[Dict[str, Any]]) -> bool:
    """Check if the structures list represents an ion pair.

    An ion pair requires at least 2 structures, and at least one must
    have a non-zero charge or be a known ion alias.
    """
    if not structures or len(structures) < 2:
        return False

    has_charged = False
    for s in structures:
        name = s.get("name", "")
        charge = s.get("charge", 0)
        clean = name.strip().rstrip("+-")

        if charge and charge != 0:
            has_charged = True
        elif clean in ION_ALIASES or clean.upper() in {k.upper() for k in ION_ALIASES}:
            has_charged = True

    return has_charged


async def resolve_ion_pair(
    structures: List[Dict[str, Any]],
    molchat: MolChatClient,
    pubchem: PubChemClient,
    offset: float = 5.0,
) -> IonPairResult:
    """Resolve an ion pair by resolving each ion individually then merging.

    Args:
        structures: List of dicts with 'name' and optional 'charge'.
        molchat: MolChat API client.
        pubchem: PubChem API client (fallback).
        offset: X-axis offset between fragments (Å).

    Returns:
        IonPairResult with merged XYZ and total charge.

    Raises:
        ValueError: If resolution fails for any ion.
    """
    # Avoid circular import
    from .structure_resolver import StructureResolver

    resolver = StructureResolver(molchat=molchat, pubchem=pubchem)

    result = IonPairResult()
    sdfs: List[str] = []

    for ion_spec in structures:
        raw_name = ion_spec.get("name", "").strip()
        explicit_charge = ion_spec.get("charge")

        # Expand alias
        info = expand_alias(raw_name)
        search_name = info["name"]
        ion_charge = explicit_charge if explicit_charge is not None else info["default_charge"]

        logger.info(
            "이온 resolve 중: %s → %s (charge=%d) / "
            "Resolving ion: %s → %s (charge=%d)",
            raw_name, search_name, ion_charge,
            raw_name, search_name, ion_charge,
        )

        # Resolve to SDF via structure_resolver's internal pipeline
        resolved = await resolver.resolve(search_name)

        if not resolved or not resolved.sdf:
            raise ValueError(
                f"이온 '{raw_name}' ({search_name}) 구조 해석 실패 / "
                f"Failed to resolve ion '{raw_name}' ({search_name})"
            )

        sdfs.append(resolved.sdf)
        result.total_charge += ion_charge
        result.names.append(search_name)
        if resolved.smiles:
            result.smiles_list.append(resolved.smiles)

    # Merge SDFs into single XYZ
    comment = f"Ion pair: {' + '.join(result.names)}"
    result.xyz = merge_sdfs(sdfs, offset=offset, comment=comment)
    result.individual_sdfs = sdfs
    result.source = "ion_pair_handler"

    logger.info(
        "이온쌍 해석 완료: %s (total_charge=%d) / "
        "Ion pair resolved: %s (total_charge=%d)",
        result.names, result.total_charge,
        result.names, result.total_charge,
    )

    return result
```

---

## 파일 7/21: `src/qcviz_mcp/services/structure_resolver.py` (신규)

```python
"""Unified structure resolution pipeline: name → SDF → XYZ.

# FIX(N6): MolChat 1순위, PubChem 폴백, 한국어 별칭, LRU 캐시
Pipeline:
  1. ko_aliases.translate() — 한국어→영어
  2. MolChat resolve → card → SMILES → generate-3d → SDF
  3. Fallback: PubChem name→SDF or name→CID→SDF
  4. SDF → XYZ (sdf_converter)
"""
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from . import ko_aliases
from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import sdf_to_xyz

logger = logging.getLogger(__name__)

_CACHE_MAX_SIZE = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))


@dataclass
class StructureResult:
    """Resolved structure data."""
    xyz: str = ""
    sdf: Optional[str] = None
    smiles: Optional[str] = None
    cid: Optional[int] = None
    name: str = ""
    source: str = ""  # "molchat", "pubchem", "builtin", etc.
    molecular_weight: Optional[float] = None


class StructureResolver:
    """Stateful resolver with LRU cache."""

    def __init__(
        self,
        molchat: Optional[MolChatClient] = None,
        pubchem: Optional[PubChemClient] = None,
        cache_max_size: int = _CACHE_MAX_SIZE,
    ) -> None:
        self.molchat = molchat or MolChatClient()
        self.pubchem = pubchem or PubChemClient()
        self._cache: OrderedDict[str, StructureResult] = OrderedDict()
        self._cache_max = cache_max_size
        self._cache_lock = Lock()

    # ── cache helpers ─────────────────────────────────────────

    def _cache_get(self, key: str) -> Optional[StructureResult]:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: str, value: StructureResult) -> None:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                self._cache[key] = value
                while len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)

    # ── main resolve ──────────────────────────────────────────

    async def resolve(self, query: str) -> StructureResult:
        """Resolve a molecule query to XYZ coordinates.

        Args:
            query: Molecule name (Korean or English), SMILES, or chemical formula.

        Returns:
            StructureResult with xyz, sdf, smiles, etc.

        Raises:
            ValueError: If structure cannot be resolved from any source.
        """
        if not query or not query.strip():
            raise ValueError(
                "구조 쿼리가 비어있습니다 / Structure query is empty"
            )

        original_query = query.strip()

        # Step 1: Korean → English translation
        translated = ko_aliases.translate(original_query)
        # If translation changed the text, use translated version
        search_name = translated if translated != original_query else original_query

        # Check cache
        cache_key = search_name.lower().strip()
        cached = self._cache_get(cache_key)
        if cached:
            logger.debug("Cache hit: %s", cache_key)
            return cached

        # Step 2: Try MolChat pipeline
        result = await self._try_molchat(search_name)
        if result:
            result.name = original_query
            self._cache_put(cache_key, result)
            return result

        # Step 3: Try PubChem fallback
        pubchem_enabled = os.getenv("PUBCHEM_FALLBACK", "true").lower() in ("true", "1", "yes")
        if pubchem_enabled:
            result = await self._try_pubchem(search_name)
            if result:
                result.name = original_query
                self._cache_put(cache_key, result)
                return result

        raise ValueError(
            f"'{original_query}' 구조를 찾을 수 없습니다. "
            f"MolChat 및 PubChem에서 모두 실패했습니다. / "
            f"Cannot resolve structure for '{original_query}'. "
            f"Both MolChat and PubChem failed."
        )

    # ── MolChat pipeline ─────────────────────────────────────

    async def _try_molchat(self, name: str) -> Optional[StructureResult]:
        """MolChat: resolve → card → SMILES → generate-3d → SDF → XYZ."""
        try:
            # resolve name → CID
            resolved = await self.molchat.resolve([name])
            if not resolved:
                logger.info("MolChat resolve 실패: %s", name)
                return None

            cid = resolved[0].get("cid")

            # get card → SMILES
            card = await self.molchat.get_card(name)
            smiles: Optional[str] = None
            molecular_weight: Optional[float] = None

            if card:
                smiles = card.get("canonical_smiles") or card.get("smiles")
                molecular_weight = card.get("molecular_weight")

            if not smiles and cid:
                # Fallback: get SMILES from PubChem using CID
                smiles = await self.pubchem.cid_to_smiles(cid)

            if not smiles:
                logger.info("MolChat에서 SMILES를 얻지 못함: %s", name)
                return None

            # generate 3D SDF
            sdf = await self.molchat.generate_3d_sdf(smiles)
            if not sdf:
                logger.info("MolChat generate-3d 실패: %s (SMILES: %s)", name, smiles)
                return None

            # SDF → XYZ
            xyz = sdf_to_xyz(sdf, comment=name)

            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="molchat",
                molecular_weight=molecular_weight,
            )

        except Exception as e:
            logger.warning(
                "MolChat 파이프라인 실패: %s → %s / "
                "MolChat pipeline failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── PubChem pipeline ──────────────────────────────────────

    async def _try_pubchem(self, name: str) -> Optional[StructureResult]:
        """PubChem fallback: name → SDF (direct or via CID)."""
        try:
            # Try direct name → SDF
            sdf = await self.pubchem.name_to_sdf_3d(name)

            cid: Optional[int] = None
            smiles: Optional[str] = None

            if not sdf:
                # Try name → CID → SDF
                cid = await self.pubchem.name_to_cid(name)
                if cid:
                    sdf = await self.pubchem.cid_to_sdf_3d(cid)

            if not sdf:
                return None

            # Get SMILES for metadata
            if cid:
                smiles = await self.pubchem.cid_to_smiles(cid)
            else:
                cid = await self.pubchem.name_to_cid(name)
                if cid:
                    smiles = await self.pubchem.cid_to_smiles(cid)

            xyz = sdf_to_xyz(sdf, comment=name)

            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="pubchem",
                molecular_weight=None,
            )

        except Exception as e:
            logger.warning(
                "PubChem 파이프라인 실패: %s → %s / "
                "PubChem pipeline failed: %s → %s",
                name, e, name, e,
            )
            return None

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        await self.molchat.close()
        await self.pubchem.close()
```

---

## 파일 8/21: `src/qcviz_mcp/services/gemini_agent.py` (신규)

```python
"""Gemini Function Calling agent for natural language → computation intent.

# FIX(N7): Gemini API function calling 스키마 3종 + 파싱 에이전트
Uses google-genai SDK with tool declarations for structured extraction.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Gemini Tool Schema ─────────────────────────────────────────

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "run_calculation",
        "description": (
            "양자화학 계산을 실행한다. 단일 분자 또는 이온쌍을 받아 PySCF로 계산한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "structure": {
                    "type": "string",
                    "description": "단일 분자명/화학식. 예: water, H2O, aspirin, benzene",
                },
                "structures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "이온/분자의 PubChem 검색 가능한 영문 화학명",
                            },
                            "charge": {
                                "type": "integer",
                                "description": "이온 전하. 예: +1, -1",
                            },
                        },
                        "required": ["name"],
                    },
                    "description": (
                        "이온쌍/다중 분자. 약어(TFSI, EMIM 등)가 아닌 풀네임으로 변환하여 반환할 것"
                    ),
                },
                "method": {
                    "type": "string",
                    "enum": ["hf", "b3lyp", "mp2", "pbe", "pbe0", "ccsd"],
                    "description": "계산 방법. 기본: hf",
                },
                "basis_set": {
                    "type": "string",
                    "description": "기저함수. 예: sto-3g, 6-31g*, cc-pvdz. 기본: sto-3g",
                },
                "job_type": {
                    "type": "string",
                    "enum": ["energy", "optimize", "frequency", "orbital", "esp"],
                    "description": "계산 종류. 기본: energy",
                },
                "charge": {
                    "type": "integer",
                    "description": "분자 전체 전하. 기본: 0",
                },
                "multiplicity": {
                    "type": "integer",
                    "description": "스핀 다중도. 기본: 1",
                },
            },
        },
    },
    {
        "name": "search_molecule",
        "description": "분자를 이름, 화학식, CAS 번호로 검색한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색어"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_molecule_info",
        "description": "특정 분자의 상세 정보(물성, 구조, 안전데이터)를 조회한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "분자명 (영문)"},
                "properties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "요청 속성. 예: molecular_weight, smiles, safety",
                },
            },
            "required": ["name"],
        },
    },
]

# ── System prompt ─────────────────────────────────────────────

_SYSTEM_PROMPT = """You are QCViz Planner, a quantum chemistry assistant.

Given the user's natural language request, call the most appropriate tool function.

Rules:
- Always call a function. Never respond with plain text.
- For ion pairs (e.g., "EMIM+ TFSI-", "NaCl"), use the `structures` array in run_calculation.
  Expand abbreviations: EMIM → 1-ethyl-3-methylimidazolium, TFSI → bis(trifluoromethylsulfonyl)imide.
- For Korean molecule names, translate them to English first.
- Default method is "hf", default basis_set is "sto-3g".
- Infer job_type from context: "에너지" → energy, "최적화" → optimize, "오비탈"/"HOMO"/"LUMO" → orbital, "ESP"/"전위" → esp.
- If the user just names a molecule without specifying a task, use job_type="energy".
""".strip()


@dataclass
class GeminiResult:
    """Parsed result from Gemini function calling."""
    function_name: str = ""
    intent: str = ""
    structure: Optional[str] = None
    structures: Optional[List[Dict[str, Any]]] = None
    method: str = "hf"
    basis_set: str = "sto-3g"
    job_type: str = "energy"
    charge: int = 0
    multiplicity: int = 1
    raw_response: str = ""
    model_used: str = ""
    # For search/info functions
    query: Optional[str] = None
    properties: Optional[List[str]] = None


class GeminiAgent:
    """Gemini function-calling agent for intent extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self.api_key: str = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model: str = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout: float = timeout or float(os.getenv("GEMINI_TIMEOUT", "10"))
        self.temperature: float = (
            temperature if temperature is not None
            else float(os.getenv("GEMINI_TEMPERATURE", "0.1"))
        )

    def is_available(self) -> bool:
        """Check if Gemini API key is configured."""
        return bool(self.api_key)

    async def parse(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        """Parse user message using Gemini function calling.

        Args:
            message: User's natural language input.
            history: Optional conversation history.

        Returns:
            GeminiResult if successful, None on failure.
        """
        if not self.is_available():
            logger.warning(
                "Gemini API 키 미설정, 폴백 사용 / "
                "Gemini API key not set, using fallback"
            )
            return None

        try:
            return await self._call_gemini(message, history)
        except Exception as e:
            logger.warning(
                "Gemini 호출 실패: %s — 폴백 사용 / "
                "Gemini call failed: %s — using fallback",
                e, e,
            )
            return None

    async def _call_gemini(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        """Internal: make Gemini API call with function declarations."""
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        client = genai.Client(api_key=self.api_key)

        # Build tool declarations
        tool_declarations = []
        for schema in TOOL_SCHEMAS:
            tool_declarations.append(
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema.get("description", ""),
                    parameters=schema.get("parameters"),
                )
            )

        tools = [types.Tool(function_declarations=tool_declarations)]

        # Build contents
        contents: List[types.Content] = []

        if history:
            for msg in history:
                role = msg.get("role", "user")
                text = msg.get("text", msg.get("content", ""))
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=text)],
                    )
                )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )
        )

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            tools=tools,
            temperature=self.temperature,
        )

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        return self._extract_result(response)

    def _extract_result(self, response: Any) -> Optional[GeminiResult]:
        """Extract function call result from Gemini response."""
        try:
            # Navigate response to find function call
            candidates = getattr(response, "candidates", [])
            if not candidates:
                logger.warning("Gemini 응답에 candidates 없음")
                return None

            content = candidates[0].content
            parts = content.parts if content else []

            for part in parts:
                fn_call = getattr(part, "function_call", None)
                if fn_call is None:
                    continue

                fn_name = fn_call.name
                args = dict(fn_call.args) if fn_call.args else {}

                logger.info(
                    "Gemini function call: %s(%s)",
                    fn_name,
                    json.dumps(args, ensure_ascii=False, default=str)[:200],
                )

                result = GeminiResult(
                    function_name=fn_name,
                    raw_response=str(response)[:500],
                    model_used=self.model,
                )

                if fn_name == "run_calculation":
                    result.intent = "calculate"
                    result.structure = args.get("structure")
                    result.structures = args.get("structures")
                    result.method = args.get("method", "hf")
                    result.basis_set = args.get("basis_set", "sto-3g")
                    result.job_type = args.get("job_type", "energy")
                    result.charge = int(args.get("charge", 0))
                    result.multiplicity = int(args.get("multiplicity", 1))

                elif fn_name == "search_molecule":
                    result.intent = "search"
                    result.query = args.get("query")

                elif fn_name == "get_molecule_info":
                    result.intent = "info"
                    result.structure = args.get("name")
                    result.properties = args.get("properties")

                return result

            # No function call found — try to extract text
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    logger.info("Gemini returned text instead of function call: %s", text[:200])

            return None

        except Exception as e:
            logger.warning("Gemini 응답 파싱 실패: %s", e)
            return None
```

---

## 파일 9/21: `src/qcviz_mcp/config.py` (수정)

```python
"""Server configuration with environment variable loading.

# FIX(M6): v3 환경변수 9개 추가 — Gemini, MolChat, PubChem, 캐시, 이온쌍 오프셋
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


@dataclass(frozen=True)
class ServerConfig:
    """서버 설정. 환경 변수 또는 기본값에서 로드. 불변."""

    # ── 서버 ────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8765
    transport: str = "sse"  # "sse" | "stdio"

    # ── 계산 ────────────────────────────────────────────────
    max_atoms: int = 50
    max_workers: int = 2
    computation_timeout_seconds: float = 300.0
    default_basis: str = "sto-3g"
    default_cube_resolution: int = 80

    # ── 캐시 ────────────────────────────────────────────────
    cache_max_size: int = 50
    cache_ttl_seconds: float = 3600.0

    # ── 보안 ────────────────────────────────────────────────
    rate_limit_capacity: int = 100
    rate_limit_refill_rate: float = 1.0
    allowed_output_root: Path = field(default_factory=lambda: Path.cwd() / "output")

    # ── 관측가능성 ──────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = False

    # ── 렌더러 ──────────────────────────────────────────────
    preferred_renderer: str = "auto"  # "auto" | "pyvista" | "playwright" | "py3dmol"

    # ── FIX(M6): Gemini API ─────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout: float = 10.0
    gemini_temperature: float = 0.1

    # ── FIX(M6): MolChat API ────────────────────────────────
    molchat_base_url: str = "http://psid.aizen.co.kr/molchat"
    molchat_timeout: float = 15.0

    # ── FIX(M6): PubChem fallback ───────────────────────────
    pubchem_fallback: bool = True

    # ── FIX(M6): SCF / structure cache ──────────────────────
    scf_cache_max_size: int = 256

    # ── FIX(M6): Ion pair offset ────────────────────────────
    ion_offset_angstrom: float = 5.0

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """환경 변수에서 설정 로드. QCVIZ_ 접두사."""
        kwargs: dict = {}
        for f_name, f_field in cls.__dataclass_fields__.items():
            env_key = f"QCVIZ_{f_name.upper()}"
            env_val = os.environ.get(env_key)

            # FIX(M6): Gemini/MolChat/PubChem 환경변수는 접두사 없이도 읽기
            if env_val is None:
                alt_keys = {
                    "gemini_api_key": "GEMINI_API_KEY",
                    "gemini_model": "GEMINI_MODEL",
                    "gemini_timeout": "GEMINI_TIMEOUT",
                    "gemini_temperature": "GEMINI_TEMPERATURE",
                    "molchat_base_url": "MOLCHAT_BASE_URL",
                    "molchat_timeout": "MOLCHAT_TIMEOUT",
                    "pubchem_fallback": "PUBCHEM_FALLBACK",
                    "scf_cache_max_size": "SCF_CACHE_MAX_SIZE",
                    "ion_offset_angstrom": "ION_OFFSET_ANGSTROM",
                }
                alt = alt_keys.get(f_name)
                if alt:
                    env_val = os.environ.get(alt)

            if env_val is not None:
                field_type = f_field.type
                if field_type in ("int", int):
                    kwargs[f_name] = int(env_val)
                elif field_type in ("float", float):
                    kwargs[f_name] = float(env_val)
                elif field_type in ("bool", bool):
                    kwargs[f_name] = env_val.lower() in ("true", "1", "yes")
                elif "Path" in str(field_type):
                    kwargs[f_name] = Path(env_val)
                else:
                    kwargs[f_name] = env_val
        return cls(**kwargs)
```

---

## 파일 10/21: `src/qcviz_mcp/llm/agent.py` (수정)

```python
"""QCViz LLM Agent — Gemini function calling primary, keyword heuristic fallback.

# FIX(M1): regex 기반 구조 추출 삭제, Gemini agent 연동, ko_aliases 폴백
기존 인터페이스(AgentPlan, QCVizAgent, SYSTEM_PROMPT 등) 최대 유지.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── FIX(M1): Gemini agent + ko_aliases import ─────────────────
try:
    from qcviz_mcp.services.gemini_agent import GeminiAgent, GeminiResult
except ImportError:
    GeminiAgent = None  # type: ignore
    GeminiResult = None  # type: ignore

try:
    from qcviz_mcp.services.ko_aliases import translate as ko_translate
except ImportError:
    def ko_translate(text: str) -> str:  # type: ignore
        return text


# ── Plan tool schema (kept for backward compat) ──────────────

PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "analyze", "single_point", "geometry_analysis",
                "partial_charges", "orbital_preview", "esp_map",
                "geometry_optimization", "resolve_structure",
            ],
        },
        "structure_query": {"type": "string"},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb", "bwr", "viridis", "inferno", "spectral",
                "nature", "acs", "rsc", "greyscale", "high_contrast",
                "grey", "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent"],
    "additionalProperties": True,
}

INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}

SYSTEM_PROMPT = """
You are QCViz Planner, a planning agent for a quantum chemistry web app.

Your job:
- Read the user's natural-language request.
- Infer the best computation intent.
- Extract structure_query, method, basis, charge, multiplicity, orbital, and esp_preset when explicit.
- Choose the best focus_tab for the frontend.
- Return ONLY arguments for the planning function / JSON object.

Intent rules:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

If the structure is unclear, still return the best intent and leave structure_query empty.
""".strip()


# ── FIX(M1): Gemini job_type → AgentPlan intent 매핑 ──────────
_GEMINI_JOB_TYPE_TO_INTENT: Dict[str, str] = {
    "energy": "single_point",
    "optimize": "geometry_optimization",
    "frequency": "analyze",
    "orbital": "orbital_preview",
    "esp": "esp_map",
}


@dataclass
class AgentPlan:
    intent: str = "analyze"
    structure_query: Optional[str] = None
    # FIX(M1): structures 필드 추가 (이온쌍 지원)
    structures: Optional[List[Dict[str, Any]]] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    tool_name: str = "run_analyze"
    notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data


class QCVizAgent:
    """LLM-powered planning agent with Gemini primary + heuristic fallback."""

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

        # FIX(M1): GeminiAgent 인스턴스 생성
        self._gemini_agent: Optional[Any] = None
        if GeminiAgent and self.gemini_api_key:
            try:
                self._gemini_agent = GeminiAgent(
                    api_key=self.gemini_api_key,
                    model=self.gemini_model,
                )
            except Exception as e:
                logger.warning("GeminiAgent 초기화 실패: %s", e)

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        """Plan a user request. Tries Gemini first, falls back to heuristic.

        # FIX(M1): Gemini function calling → 어댑터 → AgentPlan
        """
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0}, provider="heuristic")

        # FIX(M1): Try Gemini function calling first
        if self._gemini_agent and self._gemini_agent.is_available():
            try:
                gemini_result = self._try_gemini_function_calling(text)
                if gemini_result:
                    return gemini_result
            except Exception as e:
                logger.warning("Gemini function calling 실패, 폴백 / Gemini FC failed, fallback: %s", e)

        # FIX(M1): Fallback: Korean translation + heuristic
        translated = ko_translate(text)
        return self._heuristic_plan(translated, context=context or {})

    def _try_gemini_function_calling(self, message: str) -> Optional[AgentPlan]:
        """Call Gemini agent and convert result to AgentPlan.

        # FIX(M1): async → sync bridge for Gemini agent
        """
        if not self._gemini_agent:
            return None

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._gemini_agent.parse(message))
                    result = future.result(timeout=float(os.getenv("GEMINI_TIMEOUT", "10")))
            else:
                result = asyncio.run(self._gemini_agent.parse(message))
        except Exception as e:
            logger.warning("Gemini async bridge 실패: %s", e)
            return None

        if result is None:
            return None

        return self._gemini_result_to_plan(result)

    def _gemini_result_to_plan(self, gr: Any) -> AgentPlan:
        """Convert GeminiResult to AgentPlan.

        # FIX(M1): Gemini function calling 결과 어댑터
        """
        intent = _GEMINI_JOB_TYPE_TO_INTENT.get(gr.job_type, "analyze")
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structures = gr.structures if gr.structures else None

        return AgentPlan(
            intent=intent,
            structure_query=gr.structure,
            structures=structures,
            method=gr.method if gr.method != "hf" else None,
            basis=gr.basis_set if gr.basis_set != "sto-3g" else None,
            charge=gr.charge if gr.charge != 0 else None,
            multiplicity=gr.multiplicity if gr.multiplicity != 1 else None,
            orbital=None,
            esp_preset=None,
            focus_tab=defaults["focus_tab"],
            confidence=0.92,
            tool_name=defaults["tool_name"],
            notes=[f"Gemini FC: {gr.function_name}"],
            provider="gemini",
            raw={"gemini_result": gr.__dict__ if hasattr(gr, "__dict__") else {}},
        )

    # ── FIX(M1): Simplified heuristic (no more regex structure extraction) ──

    def _heuristic_plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        """Keyword-based intent detection. Structure extraction delegated to resolver."""
        text = message.strip()
        lower = text.lower()

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = ["heuristic fallback"]

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map", "정전기", "전위"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface", "오비탈"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution", "전하"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize", "최적화"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle", "구조", "결합"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy", "에너지"]):
            intent = "single_point"
            confidence = 0.82

        # FIX(M1): Structure extraction delegated to structure_resolver
        # Only do minimal name extraction for the plan
        structure_query = self._minimal_structure_extract(text)

        method = self._extract_method(text)
        basis = self._extract_basis(text)
        orbital = self._extract_orbital(text)

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        data = {
            "intent": intent,
            "structure_query": structure_query,
            "method": method,
            "basis": basis,
            "orbital": orbital,
            "confidence": confidence,
            "notes": notes,
        }
        return self._coerce_plan(data, provider="heuristic")

    def _minimal_structure_extract(self, text: str) -> Optional[str]:
        """Minimal structure name extraction — just quoted strings and common names.

        # FIX(M1): Regex 파싱 대신 최소한의 추출만 수행
        """
        # Quoted strings
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        if quoted:
            first = quoted[0][0] or quoted[0][1]
            if first.strip():
                return first.strip()

        # Common molecule names (English)
        common = [
            "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
            "formaldehyde", "carbon dioxide", "caffeine", "aspirin",
            "naphthalene", "pyridine", "phenol", "glucose", "glycine",
            "urea", "serotonin", "propane", "butane", "acetylene",
        ]
        lower = text.lower()
        for name in common:
            if name in lower:
                return name

        # Chemical formulas: H2O, CO2, NH3, etc.
        formula_match = re.search(r"\b([A-Z][a-z]?(?:\d+)?(?:[A-Z][a-z]?(?:\d+)?){0,5})\b", text)
        if formula_match:
            candidate = formula_match.group(1)
            # Must have at least one uppercase letter and look like a formula
            if re.match(r"^[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+$", candidate):
                return candidate

        # Return the whole cleaned text as a structure query (let resolver handle it)
        # Strip known noise words
        cleaned = text.strip()
        noise = [
            "calculate", "compute", "show", "render", "analyze", "optimize",
            "visualize", "the", "energy", "of", "for", "with", "using",
            "계산", "해줘", "보여줘", "분석", "에너지",
        ]
        for n in noise:
            cleaned = re.sub(rf"\b{re.escape(n)}\b", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if cleaned and len(cleaned) >= 2 and len(cleaned) <= 80:
            return cleaned

        return None

    def _extract_method(self, text: str) -> Optional[str]:
        methods = ["HF", "B3LYP", "PBE", "PBE0", "M06-2X", "MP2", "CCSD", "wB97X-D", "BP86"]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g", "3-21g", "6-31g", "6-31g*", "6-31g**",
            "6-311g", "6-311g*", "6-311g**", "def2-svp", "def2-tzvp",
            "cc-pvdz", "cc-pvtz", "aug-cc-pvdz", "aug-cc-pvtz",
        ]
        for basis in basis_list:
            if re.search(rf"\b{re.escape(basis)}\b", text, re.I):
                return basis
        return None

    def _extract_orbital(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(HOMO(?:[+-]\d+)?)\b",
            r"\b(LUMO(?:[+-]\d+)?)\b",
            r"\b(MO\s*\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip().upper().replace(" ", "")
        return None

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        def _none_if_blank(v: Any) -> Optional[str]:
            if v is None:
                return None
            t = str(v).strip()
            return t or None

        def _safe_int(v: Any) -> Optional[int]:
            if v is None or v == "":
                return None
            try:
                return int(v)
            except Exception:
                return None

        def _safe_float(v: Any, default: float) -> float:
            try:
                return float(v)
            except Exception:
                return default

        structure_query = _none_if_blank(data.get("structure_query"))
        structures = data.get("structures")
        method = _none_if_blank(data.get("method"))
        basis = _none_if_blank(data.get("basis"))
        orbital = _none_if_blank(data.get("orbital"))
        esp_preset = _none_if_blank(data.get("esp_preset"))
        focus_tab = str(data.get("focus_tab") or defaults["focus_tab"]).strip()
        tool_name = str(data.get("tool_name") or defaults["tool_name"]).strip()

        charge = _safe_int(data.get("charge"))
        multiplicity = _safe_int(data.get("multiplicity"))
        confidence = _safe_float(data.get("confidence"), 0.0)
        confidence = max(0.0, min(1.0, confidence))

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]

        return AgentPlan(
            intent=intent,
            structure_query=structure_query,
            structures=structures,
            method=method,
            basis=basis,
            charge=charge,
            multiplicity=multiplicity,
            orbital=orbital,
            esp_preset=esp_preset,
            focus_tab=focus_tab,
            confidence=confidence,
            tool_name=tool_name,
            notes=[str(x) for x in notes if str(x).strip()],
            provider=provider,
            raw=data,
        )
```

여기서 한번 끊겠습니다. 11번 파일(`compute.py`)부터 이어서 출력합니다. "이어서"라고 입력해 주세요.
