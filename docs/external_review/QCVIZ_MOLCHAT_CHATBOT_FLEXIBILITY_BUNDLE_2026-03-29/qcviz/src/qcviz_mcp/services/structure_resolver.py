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
from typing import Any, Dict, List, Optional
import re

from qcviz_mcp.llm.normalizer import (
    analyze_semantic_structure_query,
    analyze_structure_input,
    build_structure_hypotheses,
    _structure_text_signature,
)

from . import ko_aliases
from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import sdf_to_xyz

logger = logging.getLogger(__name__)

_CACHE_MAX_SIZE = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))

# Chemistry abbreviation → PubChem-searchable name
CHEM_ABBREVIATIONS: Dict[str, str] = {
    # Battery electrolyte anions
    "tfsi": "bis(trifluoromethanesulfonyl)azanide",
    "tfsi-": "bis(trifluoromethanesulfonyl)azanide",
    "ntf2": "bis(trifluoromethanesulfonyl)azanide",
    "ntf2-": "bis(trifluoromethanesulfonyl)azanide",
    "bistriflimide": "bis(trifluoromethanesulfonyl)azanide",
    "fsi": "bis(fluorosulfonyl)azanide",
    "fsi-": "bis(fluorosulfonyl)azanide",
    "hntf2": "bis(trifluoromethanesulfonyl)imide",
    "tf2nh": "bis(trifluoromethanesulfonyl)imide",
    "pf6": "hexafluorophosphate",
    "pf6-": "hexafluorophosphate",
    "bf4": "tetrafluoroborate",
    "bf4-": "tetrafluoroborate",
    # Battery electrolyte solvents
    "ec": "ethylene carbonate",
    "pc": "propylene carbonate",
    "dmc": "dimethyl carbonate",
    "emc": "ethyl methyl carbonate",
    "dec": "diethyl carbonate",
    "dme": "1,2-dimethoxyethane",
    "fec": "fluoroethylene carbonate",
    "vc": "vinylene carbonate",
    # Battery cations
    "emim": "1-ethyl-3-methylimidazolium",
    "emim+": "1-ethyl-3-methylimidazolium",
    "bmim": "1-butyl-3-methylimidazolium",
    "bmim+": "1-butyl-3-methylimidazolium",
    # Common molecules
    "thf": "tetrahydrofuran",
    "dmf": "dimethylformamide",
    "dmso": "dimethyl sulfoxide",
    "nmp": "n-methyl-2-pyrrolidone",
    "acn": "acetonitrile",
    "meoh": "methanol",
    "etoh": "ethanol",
    "toluene": "toluene",
    "dcm": "dichloromethane",
}

CHEM_QUERY_SYNONYMS: Dict[str, List[str]] = {
    "tfsi": [
        "bis(trifluoromethanesulfonyl)azanide",
        "bistriflimide",
    ],
    "tfsi-": [
        "bis(trifluoromethanesulfonyl)azanide",
        "bistriflimide",
    ],
    "ntf2": [
        "bis(trifluoromethanesulfonyl)azanide",
        "bistriflimide",
    ],
    "ntf2-": [
        "bis(trifluoromethanesulfonyl)azanide",
        "bistriflimide",
    ],
    "fsi": [
        "bis(fluorosulfonyl)azanide",
    ],
    "fsi-": [
        "bis(fluorosulfonyl)azanide",
    ],
}

EXPECTED_FORMAL_CHARGES: Dict[str, int] = {
    "tfsi": -1,
    "tfsi-": -1,
    "ntf2": -1,
    "ntf2-": -1,
    "bistriflimide": -1,
    "fsi": -1,
    "fsi-": -1,
    "pf6": -1,
    "pf6-": -1,
    "bf4": -1,
    "bf4-": -1,
    "emim": 1,
    "emim+": 1,
    "bmim": 1,
    "bmim+": 1,
    "li": 1,
    "na": 1,
    "k": 1,
}

_BRACKET_ATOM_RE = re.compile(r"\[([^\]]+)\]")
_CHARGE_TOKEN_RE = re.compile(r"(\+{1,4}|-{1,4}|[+-]\d+|\d+[+-])")
_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")


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
    query_plan: Dict[str, Any] = field(default_factory=dict)


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

    @staticmethod
    def _infer_expected_charge(raw_query: str, normalized_query: str) -> Optional[int]:
        for token in (normalized_query, raw_query):
            key = str(token or "").strip().lower()
            if key in EXPECTED_FORMAL_CHARGES:
                return EXPECTED_FORMAL_CHARGES[key]
        stripped = str(normalized_query or raw_query or "").strip()
        if stripped.endswith("+"):
            return 1
        if stripped.endswith("-"):
            return -1
        return None

    @staticmethod
    def _charge_from_token(token: str) -> int:
        token = str(token or "").strip()
        if not token:
            return 0
        if token[0] in "+-" and token[1:].isdigit():
            sign = 1 if token[0] == "+" else -1
            return sign * int(token[1:])
        if token[-1] in "+-" and token[:-1].isdigit():
            sign = 1 if token[-1] == "+" else -1
            return sign * int(token[:-1])
        if set(token) == {"+"}:
            return len(token)
        if set(token) == {"-"}:
            return -len(token)
        return 0

    @classmethod
    def _infer_smiles_formal_charge(cls, smiles: Optional[str]) -> Optional[int]:
        text = str(smiles or "").strip()
        if not text:
            return None
        total = 0
        matched = False
        for bracket_body in _BRACKET_ATOM_RE.findall(text):
            for token in _CHARGE_TOKEN_RE.findall(bracket_body):
                total += cls._charge_from_token(token)
                matched = True
        return total if matched else 0

    @classmethod
    def _matches_expected_charge(cls, smiles: Optional[str], expected_charge: Optional[int]) -> bool:
        if expected_charge is None:
            return True
        inferred = cls._infer_smiles_formal_charge(smiles)
        if inferred is None:
            return False
        return inferred == expected_charge

    def _build_query_plan(self, query: str) -> Dict[str, Any]:
        raw_query = str(query or "").translate(_SUBSCRIPT_MAP).strip()
        raw_query = re.sub(r"\s*/+\s*$", "", raw_query).strip()
        structure_analysis = analyze_structure_input(raw_query)
        semantic_info = analyze_semantic_structure_query(raw_query, structure_analysis=structure_analysis)
        translated = ko_aliases.translate(raw_query)
        translated = " ".join(translated.split())
        normalized = translated or raw_query
        hypothesis_bundle = build_structure_hypotheses(
            raw_query,
            base_analysis=structure_analysis,
            translated_text=translated or raw_query,
            expanded_text=normalized,
        )

        candidate_queries: List[str] = []

        def add_candidate(value: Optional[str]) -> None:
            token = str(value or "").strip()
            if not token:
                return
            if token.lower() not in {item.lower() for item in candidate_queries}:
                candidate_queries.append(token)

        for candidate in hypothesis_bundle.get("candidate_queries") or []:
            add_candidate(candidate)

        if structure_analysis.get("mixed_input"):
            for candidate in structure_analysis.get("canonical_candidates") or []:
                add_candidate(candidate)

        abbrev_key = normalized.lower().strip()
        if abbrev_key in CHEM_ABBREVIATIONS:
            add_candidate(CHEM_ABBREVIATIONS[abbrev_key])
            for synonym in CHEM_QUERY_SYNONYMS.get(abbrev_key, []):
                add_candidate(synonym)

        if not semantic_info.get("semantic_descriptor") and not structure_analysis.get("mixed_input"):
            add_candidate(normalized)

        ion_tokens = [tok.strip() for tok in normalized.split() if tok.strip()]
        if len(ion_tokens) == 1:
            add_candidate(ion_tokens[0].strip("+-"))

        for token in ion_tokens:
            mapped = CHEM_ABBREVIATIONS.get(token.lower())
            if mapped:
                add_candidate(mapped)
                for synonym in CHEM_QUERY_SYNONYMS.get(token.lower(), []):
                    add_candidate(synonym)

        if semantic_info.get("semantic_descriptor"):
            raw_variants = {
                variant.lower()
                for variant in (raw_query, translated, normalized)
                if str(variant or "").strip()
            }
            raw_signatures = {
                _structure_text_signature(variant)
                for variant in (raw_query, translated, normalized)
                if _structure_text_signature(variant)
            }
            candidate_queries = [
                item
                for item in candidate_queries
                if str(item).strip().lower() not in raw_variants
                and _structure_text_signature(item) not in raw_signatures
            ]

        fallback_candidates = candidate_queries
        if not fallback_candidates and not semantic_info.get("semantic_descriptor"):
            fallback_candidates = [raw_query]

        return {
            "raw_query": raw_query,
            "normalized_query": hypothesis_bundle.get("primary_candidate") or (candidate_queries[0] if candidate_queries else raw_query),
            "candidate_queries": fallback_candidates,
            "translated_query": translated or raw_query,
            "expected_charge": self._infer_expected_charge(raw_query, normalized),
            "formula_mentions": list(structure_analysis.get("formula_mentions") or []),
            "alias_mentions": list(structure_analysis.get("alias_mentions") or []),
            "canonical_candidates": list(structure_analysis.get("canonical_candidates") or []),
            "mixed_input": bool(structure_analysis.get("mixed_input")),
            "semantic_descriptor": bool(semantic_info.get("semantic_descriptor")),
            "display_query": hypothesis_bundle.get("primary_candidate") or structure_analysis.get("primary_candidate") or raw_query,
            "hypothesis_confidence": float(hypothesis_bundle.get("confidence") or 0.0),
            "hypothesis_needs_clarification": bool(hypothesis_bundle.get("needs_clarification")),
            "reasoning_notes": list(hypothesis_bundle.get("reasoning_notes") or []),
        }

    def suggest_candidate_queries(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return resolver-grounded text candidates without performing network resolution.

        This is intended for clarification UX where we want to preserve the raw user
        input and expose alias/normalized variants from the same resolver pipeline.
        """
        query_plan = self._build_query_plan(query)
        raw_query = str(query_plan.get("raw_query") or "").strip()
        translated_query = str(query_plan.get("translated_query") or "").strip()
        normalized_query = str(query_plan.get("normalized_query") or "").strip()
        expected_charge = query_plan.get("expected_charge")
        candidate_queries = list(query_plan.get("candidate_queries") or [])

        ranked: List[Dict[str, Any]] = []
        seen = set()

        def add(name: str, *, match_kind: str, score: int, source: str) -> None:
            token = str(name or "").strip()
            if not token:
                return
            key = token.lower()
            if key in seen:
                return
            seen.add(key)
            cached = self._cache_get(key)
            ranked.append(
                {
                    "name": token,
                    "match_kind": match_kind,
                    "score": score,
                    "source": source,
                    "resolver_success": cached is not None,
                    "resolver_source": getattr(cached, "source", None) if cached else None,
                    "expected_charge": expected_charge,
                }
            )

        if raw_query and not query_plan.get("semantic_descriptor"):
            add(raw_query, match_kind="raw_exact", score=120, source="user_input")
        if translated_query and translated_query.lower() != raw_query.lower():
            add(translated_query, match_kind="translated", score=110, source="ko_alias")
        if normalized_query and normalized_query.lower() not in {raw_query.lower(), translated_query.lower()}:
            add(normalized_query, match_kind="normalized_exact", score=105, source="resolver_query_plan")

        for idx, candidate in enumerate(candidate_queries):
            add(
                candidate,
                match_kind="query_variant",
                score=max(70, 100 - idx * 5),
                source="resolver_query_plan",
            )

        ranked.sort(key=lambda item: (int(item.get("resolver_success") or 0), int(item.get("score") or 0)), reverse=True)
        return ranked[: max(1, int(limit or 5))]

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
        query_plan = self._build_query_plan(original_query)
        logger.info(
            "Structure query plan raw=%s normalized=%s candidates=%s mixed_input=%s aliases=%s formulas=%s",
            query_plan["raw_query"],
            query_plan["normalized_query"],
            query_plan["candidate_queries"],
            query_plan.get("mixed_input"),
            query_plan.get("alias_mentions"),
            query_plan.get("formula_mentions"),
        )

        for candidate in query_plan["candidate_queries"]:
            cache_key = candidate.lower().strip()
            cached = self._cache_get(cache_key)
            if cached:
                logger.debug("Cache hit: %s", cache_key)
                return cached

        # Step 2: Try MolChat pipeline across candidate queries
        for candidate in query_plan["candidate_queries"]:
            result = await self._try_molchat(candidate)
            if result:
                if not self._matches_expected_charge(result.smiles, query_plan.get("expected_charge")):
                    logger.info(
                        "Rejected MolChat result due to charge mismatch: query=%s candidate=%s expected=%s smiles=%s",
                        original_query,
                        candidate,
                        query_plan.get("expected_charge"),
                        result.smiles,
                    )
                    continue
                result.name = str(query_plan.get("display_query") or original_query)
                result.query_plan = query_plan
                self._cache_put(candidate.lower().strip(), result)
                return result

        # Step 3: Try PubChem fallback across candidate queries
        pubchem_enabled = os.getenv("PUBCHEM_FALLBACK", "true").lower() in ("true", "1", "yes")
        if pubchem_enabled:
            for candidate in query_plan["candidate_queries"]:
                result = await self._try_pubchem(candidate)
                if result:
                    if not self._matches_expected_charge(result.smiles, query_plan.get("expected_charge")):
                        logger.info(
                            "Rejected PubChem result due to charge mismatch: query=%s candidate=%s expected=%s smiles=%s",
                            original_query,
                            candidate,
                            query_plan.get("expected_charge"),
                            result.smiles,
                        )
                        continue
                    result.name = str(query_plan.get("display_query") or original_query)
                    result.query_plan = query_plan
                    self._cache_put(candidate.lower().strip(), result)
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
