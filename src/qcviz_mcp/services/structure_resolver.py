"""Unified structure resolution pipeline: name → SDF → XYZ.

# FIX(N6): MolChat 1순위, PubChem 폴백, 한국어 별칭, LRU 캐시
Pipeline:
  1. ko_aliases.translate() — 한국어→영어
  2. MolChat resolve → card → SMILES → generate-3d → SDF
  3. Fallback: PubChem name→SDF or name→CID→SDF
  4. SDF → XYZ (sdf_converter)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import difflib
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Mapping, Optional
import re

from qcviz_mcp.llm.normalizer import (
    analyze_semantic_structure_query,
    analyze_structure_input,
    build_structure_hypotheses,
    is_condensed_structural_formula,
    _structure_text_signature,
)
from qcviz_mcp.llm.schemas import ResolutionResult, StructureCandidate

from . import ko_aliases
from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import sdf_to_xyz

try:
    from rdkit import Chem

    _RDKIT_AVAILABLE = True
except Exception:
    Chem = None  # type: ignore
    _RDKIT_AVAILABLE = False

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:
    QCVizAgent = None  # type: ignore

logger = logging.getLogger(__name__)

_CACHE_MAX_SIZE = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))
_LLM_AGENT: Optional[Any] = None
_LLM_AGENT_LOCK = Lock()

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

LOCAL_QUERY_AUTOCORRECTS: Dict[str, str] = {
    "aminobutylic acid": "gamma-aminobutyric acid",
    "aminobutyric acid": "gamma-aminobutyric acid",
    "methyl ethyl aminje": "methylethylamine",
    "methyl ethyl amine": "methylethylamine",
    "diethyl aminje": "diethylamine",
    "triethyl aminje": "triethylamine",
    "etahnol": "ethanol",
    "metahnol": "methanol",
    "benzne": "benzene",
    "tolueen": "toluene",
    "aceton": "acetone",
    "amonia": "ammonia",
    "ammona": "ammonia",
    "formaldehyd": "formaldehyde",
    "aceticacid": "acetic acid",
    "caffiene": "caffeine",
    "cafeine": "caffeine",
}

_KNOWN_MOLECULE_NAMES: List[str] = sorted(
    set(
        list(CHEM_ABBREVIATIONS.values())
        + list(LOCAL_QUERY_AUTOCORRECTS.values())
        + [
            "water",
            "methane",
            "ethane",
            "propane",
            "butane",
            "methanol",
            "ethanol",
            "propanol",
            "butanol",
            "methylamine",
            "ethylamine",
            "dimethylamine",
            "trimethylamine",
            "diethylamine",
            "triethylamine",
            "methylethylamine",
            "benzene",
            "toluene",
            "phenol",
            "aniline",
            "pyridine",
            "naphthalene",
            "styrene",
            "biphenyl",
            "acetone",
            "acetic acid",
            "formic acid",
            "benzoic acid",
            "ammonia",
            "formaldehyde",
            "acetaldehyde",
            "glycine",
            "urea",
            "aspirin",
            "caffeine",
            "glucose",
            "hydrogen peroxide",
            "sulfuric acid",
            "hydrochloric acid",
            "acetylene",
            "butadiene",
            "glutamic acid",
            "serotonin",
            "acetonitrile",
            "tetrahydrofuran",
            "dimethyl sulfoxide",
            "dichloromethane",
            "chloroform",
            "carbon dioxide",
            "carbon monoxide",
            "nitrobenzene",
            "2,4,6-trinitrotoluene",
            "fluorobenzene",
            "cyclohexane",
            "cyclopentane",
            "furan",
            "thiophene",
            "imidazole",
            "gamma-aminobutyric acid",
        ]
    )
)
_KNOWN_MOLECULE_NAMES_LOWER = [name.lower() for name in _KNOWN_MOLECULE_NAMES]
_KNOWN_MOLECULE_NAME_MAP = {name.lower(): name for name in _KNOWN_MOLECULE_NAMES}
_KNOWN_MOLECULE_NAME_COMPACT_MAP = {
    name.lower().replace(" ", ""): name for name in _KNOWN_MOLECULE_NAMES
}


def _fuzzy_rescue_candidates(query: str, cutoff: float = 0.6, n: int = 5) -> List[str]:
    """Generate typo-recovery candidates from a known molecule vocabulary."""
    cleaned = str(query or "").strip().lower()
    if not cleaned or len(cleaned) < 3:
        return []
    if cleaned in _KNOWN_MOLECULE_NAMES_LOWER:
        return []

    matches: List[str] = []
    for token in difflib.get_close_matches(cleaned, _KNOWN_MOLECULE_NAMES_LOWER, n=n, cutoff=cutoff):
        restored = _KNOWN_MOLECULE_NAME_MAP.get(token, token)
        if restored.lower() not in {item.lower() for item in matches}:
            matches.append(restored)

    compact = cleaned.replace(" ", "")
    if compact and compact != cleaned:
        compact_candidates = difflib.get_close_matches(
            compact,
            list(_KNOWN_MOLECULE_NAME_COMPACT_MAP.keys()),
            n=n,
            cutoff=cutoff,
        )
        for token in compact_candidates:
            restored = _KNOWN_MOLECULE_NAME_COMPACT_MAP.get(token, token)
            if restored.lower() not in {item.lower() for item in matches}:
                matches.append(restored)

    return matches[:n]


def _classify_resolution_failure(exc: Exception) -> str:
    message = str(exc or "").lower()
    if any(
        token in message
        for token in (
            "connection",
            "timeout",
            "timed out",
            "refused",
            "event loop",
            "closed",
            "dns",
            "ssl",
            "network",
            "transport",
        )
    ):
        return "infrastructure"
    return "no_match"


def _get_llm_agent() -> Optional[Any]:
    global _LLM_AGENT
    if _LLM_AGENT is not None:
        return _LLM_AGENT
    if QCVizAgent is None:
        return None
    with _LLM_AGENT_LOCK:
        if _LLM_AGENT is not None:
            return _LLM_AGENT
        try:
            agent = QCVizAgent()
        except Exception as exc:
            logger.warning("QCVizAgent initialization failed for condensed formula fallback: %s", exc)
            return None
        if not getattr(agent, "gemini_api_key", None) and not getattr(agent, "openai_api_key", None):
            return None
        _LLM_AGENT = agent
    return _LLM_AGENT


def _extract_json_dict(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _validate_llm_smiles(smiles: str, original_formula: str) -> Optional[str]:
    """Run a lightweight chemistry sanity check on LLM-generated SMILES.

    This is intentionally not a full identity proof. It only filters obviously
    broken or clearly unrelated molecules before 3D generation.
    """
    cleaned = str(smiles or "").strip()
    original = str(original_formula or "").strip()
    if not cleaned:
        return None
    if not _RDKIT_AVAILABLE:
        logger.warning(
            "RDKit not available; skipping LLM SMILES sanity check for %s",
            original or cleaned,
        )
        return cleaned

    try:
        mol = Chem.MolFromSmiles(cleaned, sanitize=False)  # type: ignore[union-attr]
    except Exception:
        mol = None
    if mol is None:
        logger.info(
            "LLM SMILES rejected due to parse failure: formula=%s smiles=%s",
            original,
            cleaned,
        )
        return None

    try:
        Chem.SanitizeMol(mol)  # type: ignore[union-attr]
    except Exception as exc:
        logger.info(
            "LLM SMILES rejected due to sanitize failure: formula=%s smiles=%s error=%s",
            original,
            cleaned,
            exc,
        )
        return None

    heavy_atoms = mol.GetNumHeavyAtoms()
    if heavy_atoms < 2:
        logger.info(
            "LLM SMILES rejected due to too few heavy atoms: formula=%s smiles=%s heavy_atoms=%d",
            original,
            cleaned,
            heavy_atoms,
        )
        return None

    formula_elements = set(re.findall(r"[A-Z][a-z]?", original))
    smiles_elements = {atom.GetSymbol() for atom in mol.GetAtoms()}
    formula_heavy = formula_elements - {"H"}
    smiles_heavy = smiles_elements - {"H"}
    if formula_heavy and not (formula_heavy & smiles_heavy):
        logger.info(
            "LLM SMILES rejected due to element mismatch: formula=%s smiles=%s formula_elements=%s smiles_elements=%s",
            original,
            cleaned,
            sorted(formula_heavy),
            sorted(smiles_heavy),
        )
        return None
    if formula_heavy and len(formula_heavy) >= 2:
        overlap_ratio = len(formula_heavy & smiles_heavy) / len(formula_heavy)
        if overlap_ratio < 0.5:
            logger.info(
                "LLM SMILES rejected due to low element overlap: formula=%s smiles=%s overlap=%.2f formula_elements=%s smiles_elements=%s",
                original,
                cleaned,
                overlap_ratio,
                sorted(formula_heavy),
                sorted(smiles_heavy),
            )
            return None

    canonical = Chem.MolToSmiles(mol, canonical=True)  # type: ignore[union-attr]
    logger.info(
        "LLM SMILES passed sanity check: formula=%s input=%s canonical=%s heavy_atoms=%d",
        original,
        cleaned,
        canonical,
        heavy_atoms,
    )
    return canonical

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
    structure_query_raw: Optional[str] = None
    resolved_structure_name: Optional[str] = None
    resolved_smiles: Optional[str] = None
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
        self._last_failure_class: Optional[str] = None

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
        raw_query = re.sub(r"[‐‑‒–—−]", "-", raw_query)
        raw_query = re.sub(r"\s*/+\s*$", "", raw_query).strip()
        autocorrected_query = LOCAL_QUERY_AUTOCORRECTS.get(raw_query.lower(), raw_query)
        structure_analysis = analyze_structure_input(raw_query)
        condensed_formula = bool(structure_analysis.get("condensed_formula")) or is_condensed_structural_formula(raw_query)
        semantic_info = analyze_semantic_structure_query(raw_query, structure_analysis=structure_analysis)
        translated = ko_aliases.translate(autocorrected_query)
        translated = " ".join(translated.split())
        normalized = translated or autocorrected_query
        preserve_raw_exact = bool(re.match(r"^\d+(?:,\d+)+(?:-[A-Za-z]|\s+[A-Za-z])", raw_query))
        hypothesis_bundle = build_structure_hypotheses(
            autocorrected_query,
            base_analysis=structure_analysis,
            translated_text=translated or autocorrected_query,
            expanded_text=normalized,
        )

        candidate_queries: List[str] = []

        def add_candidate(value: Optional[str]) -> None:
            token = str(value or "").strip()
            if not token:
                return
            if token.lower() not in {item.lower() for item in candidate_queries}:
                candidate_queries.append(token)

        if condensed_formula:
            add_candidate(raw_query)
            return {
                "raw_query": raw_query,
                "normalized_query": raw_query,
                "candidate_queries": candidate_queries or [raw_query],
                "query_kind": "condensed_formula",
                "translated_query": translated or raw_query,
                "expected_charge": None,
                "formula_mentions": [raw_query],
                "alias_mentions": [],
                "canonical_candidates": [raw_query],
                "mixed_input": False,
                "condensed_formula": True,
                "semantic_descriptor": False,
                "display_query": raw_query,
                "hypothesis_confidence": 0.95,
                "hypothesis_needs_clarification": False,
                "reasoning_notes": ["condensed structural formula locked as single structure query"],
            }

        if autocorrected_query.lower() != raw_query.lower():
            add_candidate(autocorrected_query)

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

        if preserve_raw_exact:
            candidate_queries = [raw_query] + [
                item for item in candidate_queries if str(item).strip().lower() != raw_query.lower()
            ]

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

        existing_lower = {item.lower() for item in candidate_queries}
        known_lower = set(_KNOWN_MOLECULE_NAMES_LOWER)
        has_exact_match = bool(existing_lower & known_lower)
        if not has_exact_match and not semantic_info.get("semantic_descriptor"):
            fuzzy_candidates = _fuzzy_rescue_candidates(raw_query)
            for candidate in fuzzy_candidates:
                add_candidate(candidate)
            if not fuzzy_candidates and translated and translated.lower() != raw_query.lower():
                for candidate in _fuzzy_rescue_candidates(translated):
                    add_candidate(candidate)

        fallback_candidates = candidate_queries
        if not fallback_candidates and not semantic_info.get("semantic_descriptor"):
            fallback_candidates = [raw_query]

        query_kind = "unknown"
        if semantic_info.get("semantic_descriptor"):
            query_kind = "semantic_descriptor"
        elif len([tok for tok in normalized.split() if tok.strip()]) >= 2 and any(ch in normalized for ch in "+-/,;"):
            query_kind = "composite"
        elif structure_analysis.get("formula_mentions"):
            query_kind = "formula"
        elif fallback_candidates:
            query_kind = "direct_name"

        normalized_query_value = raw_query if preserve_raw_exact else (
            autocorrected_query
            if autocorrected_query.lower() != raw_query.lower()
            else (hypothesis_bundle.get("primary_candidate") or (candidate_queries[0] if candidate_queries else raw_query))
        )
        display_query_value = raw_query if preserve_raw_exact else (
            autocorrected_query
            if autocorrected_query.lower() != raw_query.lower()
            else (hypothesis_bundle.get("primary_candidate") or structure_analysis.get("primary_candidate") or raw_query)
        )

        return {
            "raw_query": raw_query,
            "normalized_query": normalized_query_value,
            "candidate_queries": fallback_candidates,
            "query_kind": query_kind,
            "translated_query": translated or raw_query,
            "expected_charge": self._infer_expected_charge(raw_query, normalized),
            "formula_mentions": list(structure_analysis.get("formula_mentions") or []),
            "alias_mentions": list(structure_analysis.get("alias_mentions") or []),
            "canonical_candidates": list(structure_analysis.get("canonical_candidates") or []),
            "mixed_input": bool(structure_analysis.get("mixed_input")),
            "condensed_formula": condensed_formula,
            "semantic_descriptor": bool(semantic_info.get("semantic_descriptor")),
            "display_query": display_query_value,
            "hypothesis_confidence": float(hypothesis_bundle.get("confidence") or 0.0),
            "hypothesis_needs_clarification": bool(hypothesis_bundle.get("needs_clarification")),
            "reasoning_notes": list(hypothesis_bundle.get("reasoning_notes") or []),
        }

    def _rank_query_candidates(
        self,
        query_plan: Mapping[str, Any],
        *,
        action_plan: Optional[Mapping[str, Any]] = None,
        state: Optional[Mapping[str, Any]] = None,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        raw_query = str(query_plan.get("raw_query") or "").strip()
        translated_query = str(query_plan.get("translated_query") or "").strip()
        normalized_query = str(query_plan.get("normalized_query") or "").strip()
        raw_sig = _structure_text_signature(raw_query)
        translated_sig = _structure_text_signature(translated_query)
        normalized_sig = _structure_text_signature(normalized_query)
        context_target = ""
        if isinstance(action_plan, Mapping):
            target = action_plan.get("target")
            if isinstance(target, Mapping):
                context_target = str(target.get("molecule_text") or "").strip()
        if not context_target and isinstance(state, Mapping):
            context_target = str(state.get("last_structure_query") or state.get("last_resolved_name") or "").strip()
        context_sig = _structure_text_signature(context_target)

        ranked: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for idx, candidate in enumerate(list(query_plan.get("candidate_queries") or [])):
            token = str(candidate or "").strip()
            if not token:
                continue
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            token_sig = _structure_text_signature(token)
            score = 0
            notes: List[str] = []
            if token_sig and raw_sig and token_sig == raw_sig:
                score += 120
                notes.append("exact_raw_match")
            elif token_sig and translated_sig and token_sig == translated_sig:
                score += 110
                notes.append("exact_translated_match")
            elif token_sig and normalized_sig and token_sig == normalized_sig:
                score += 100
                notes.append("exact_normalized_match")
            else:
                score += max(50, 90 - idx * 5)
                notes.append("variant_candidate")
            if context_sig and token_sig and token_sig == context_sig:
                score += 25
                notes.append("context_continuity_bonus")
            if self._cache_get(lowered):
                score += 10
                notes.append("resolver_cache_bonus")
            similarity = 0
            if token_sig and raw_sig:
                similarity = int(difflib.SequenceMatcher(None, token_sig, raw_sig).ratio() * 100)
            ranked.append(
                {
                    "query": token,
                    "score": score,
                    "similarity": similarity,
                    "notes": notes,
                }
            )
        ranked.sort(key=lambda item: (-int(item.get("score") or 0), -int(item.get("similarity") or 0), str(item.get("query") or "").lower()))
        return ranked[: max(1, int(limit or 8))]

    def preview_resolution_candidates(
        self,
        query: str,
        *,
        action_plan: Optional[Mapping[str, Any]] = None,
        state: Optional[Mapping[str, Any]] = None,
        limit: int = 5,
    ) -> ResolutionResult:
        query_plan = self._build_query_plan(query)
        ranked_queries = self._rank_query_candidates(query_plan, action_plan=action_plan, state=state, limit=limit)
        alternatives = [
            StructureCandidate(
                source="resolver_query_plan",
                display_name=str(item.get("query") or ""),
                canonical_name=str(item.get("query") or ""),
                confidence=min(1.0, max(0.0, float(item.get("score") or 0.0) / 120.0)),
                metadata={"ranking_notes": list(item.get("notes") or []), "similarity": item.get("similarity")},
            )
            for item in ranked_queries
        ]
        best = alternatives[0] if alternatives else None
        return ResolutionResult(
            resolved=bool(best and best.confidence >= 0.90),
            best_candidate=best,
            alternatives=alternatives[1:],
            confidence=best.confidence if best else 0.0,
            needs_clarification=not bool(best and best.confidence >= 0.90),
            reason=None if best else "no_ranked_candidates",
            ranking_notes=[",".join(item.get("notes") or []) for item in ranked_queries],
        )

    async def _try_molchat_with_search_fallback(self, name: str) -> Optional[StructureResult]:
        """Run the legacy MolChat resolve path, then fall back to search/autocorrect."""
        result = await self._try_molchat(name)
        if result:
            return result

        cleaned = str(name or "").strip()
        if not cleaned:
            return None

        try:
            search_payload = await self.molchat.search(cleaned, limit=5)
        except Exception as exc:
            self._last_failure_class = _classify_resolution_failure(exc)
            logger.info("MolChat search fallback failed for %s: %s", cleaned, exc)
            return None

        best_row: Optional[Dict[str, Any]] = None
        for row in list(search_payload.get("results") or []):
            item = dict(row or {})
            if item.get("canonical_smiles") or item.get("smiles") or item.get("cid"):
                best_row = item
                break
        if not best_row:
            logger.info("MolChat search fallback found no grounded candidate: %s", cleaned)
            return None

        resolved_name = str(best_row.get("name") or cleaned).strip() or cleaned
        cid = best_row.get("cid")
        smiles = best_row.get("canonical_smiles") or best_row.get("smiles")
        molecular_weight = best_row.get("molecular_weight")

        card: Optional[Dict[str, Any]] = None
        seen_card_queries = set()
        for card_query in (resolved_name, cleaned):
            token = str(card_query or "").strip()
            lowered = token.lower()
            if not token or lowered in seen_card_queries:
                continue
            seen_card_queries.add(lowered)
            card = await self.molchat.get_card(token)
            if card:
                break

        if card:
            resolved_name = str(card.get("name") or resolved_name or cleaned).strip() or cleaned
            smiles = smiles or card.get("canonical_smiles") or card.get("smiles")
            molecular_weight = molecular_weight or card.get("molecular_weight")
            cid = cid or card.get("cid")

        if not smiles and cid:
            smiles = await self.pubchem.cid_to_smiles(cid)
        if not smiles:
            logger.info("MolChat search fallback found candidate but no SMILES: %s -> %s", cleaned, resolved_name)
            return None

        sdf = await self.molchat.generate_3d_sdf(smiles)
        if not sdf:
            logger.info("MolChat search fallback generate-3d failed: %s -> %s", cleaned, resolved_name)
            return None

        xyz = sdf_to_xyz(sdf, comment=resolved_name)
        logger.info("MolChat search fallback corrected %s -> %s (cid=%s)", cleaned, resolved_name, cid)
        self._last_failure_class = None
        return StructureResult(
            xyz=xyz,
            sdf=sdf,
            smiles=smiles,
            cid=cid,
            name=resolved_name,
            source="molchat_search_autocorrect",
            molecular_weight=molecular_weight,
            resolved_structure_name=resolved_name,
            resolved_smiles=smiles,
        )

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

        raw_sig = _structure_text_signature(raw_query)
        translated_sig = _structure_text_signature(translated_query)
        normalized_sig = _structure_text_signature(normalized_query)

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

        if raw_query and query_plan.get("query_kind") != "semantic_descriptor":
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

        def _rank_key(item: Dict[str, Any]) -> tuple[int, int, int, str]:
            name = str(item.get("name") or "").strip()
            name_sig = _structure_text_signature(name)
            exact_tier = 0
            if name_sig and raw_sig and name_sig == raw_sig:
                exact_tier = 4
            elif name_sig and translated_sig and name_sig == translated_sig:
                exact_tier = 3
            elif name_sig and normalized_sig and name_sig == normalized_sig:
                exact_tier = 2
            elif str(item.get("match_kind") or "") == "query_variant":
                exact_tier = 1
            similarity = 0
            if name_sig and raw_sig:
                similarity = int(difflib.SequenceMatcher(None, name_sig, raw_sig).ratio() * 1000)
            return (
                -exact_tier,
                -similarity,
                -int(item.get("score") or 0),
                -int(bool(item.get("resolver_success"))),
                name.lower(),
            )

        ranked.sort(key=_rank_key)
        return ranked[: max(1, int(limit or 5))]

    async def _llm_condensed_formula_to_smiles(self, formula: str) -> Dict[str, Any]:
        agent = _get_llm_agent()
        if agent is None:
            return {}

        prompt = (
            "You convert a condensed structural formula into a single-molecule canonical SMILES.\n"
            "Return strict JSON only with keys \"smiles\" and optional \"resolved_name\".\n"
            "Do not split substituents in parentheses into separate ions or components.\n"
            "Do not invent salts, charge separation, or mixtures.\n"
            "If uncertain, return {\"smiles\":\"\",\"resolved_name\":\"\"}.\n\n"
            f"Input formula: {formula}\n"
        )

        raw = ""
        if getattr(agent, "gemini_api_key", None) and hasattr(agent, "_gemini_generate"):
            raw = await asyncio.to_thread(agent._gemini_generate, prompt, True)

        if not raw and getattr(agent, "openai_api_key", None):
            try:
                from openai import OpenAI

                def _call_openai() -> str:
                    client = OpenAI(api_key=agent.openai_api_key)
                    resp = client.chat.completions.create(
                        model=agent.openai_model,
                        temperature=0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": "Return strict JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    return str((resp.choices[0].message.content or "")).strip()

                raw = await asyncio.to_thread(_call_openai)
            except Exception as exc:
                logger.info("OpenAI condensed formula fallback failed for %s: %s", formula, exc)

        data = _extract_json_dict(raw)
        smiles = str(data.get("smiles") or "").strip()
        resolved_name = str(data.get("resolved_name") or "").strip()
        if not smiles:
            return {}
        return {
            "smiles": smiles,
            "resolved_name": resolved_name,
        }

    async def _try_condensed_formula_llm_fallback(self, formula: str) -> Optional[StructureResult]:
        payload = await self._llm_condensed_formula_to_smiles(formula)
        smiles = str(payload.get("smiles") or "").strip()
        resolved_name = str(payload.get("resolved_name") or "").strip() or formula
        if not smiles:
            return None

        validated_smiles = _validate_llm_smiles(smiles, formula)
        if not validated_smiles:
            logger.warning(
                "Condensed formula LLM fallback rejected by sanity check: formula=%s raw_smiles=%s",
                formula,
                smiles,
            )
            return None

        try:
            sdf = await self.molchat.generate_3d_sdf(validated_smiles)
        except Exception as exc:
            self._last_failure_class = _classify_resolution_failure(exc)
            logger.info("Condensed formula LLM fallback generate-3d failed for %s: %s", formula, exc)
            return None

        if not sdf:
            logger.info(
                "Condensed formula LLM fallback failed 3D validation for %s: %s",
                formula,
                validated_smiles,
            )
            return None

        xyz = sdf_to_xyz(sdf, comment=resolved_name)
        self._last_failure_class = None
        return StructureResult(
            xyz=xyz,
            sdf=sdf,
            smiles=validated_smiles,
            cid=None,
            name=resolved_name,
            source="llm_condensed_formula",
            molecular_weight=None,
            structure_query_raw=formula,
            resolved_structure_name=resolved_name,
            resolved_smiles=validated_smiles,
        )

    async def resolve(
        self,
        query: str,
        *,
        plan: Optional[Mapping[str, Any]] = None,
        state: Optional[Mapping[str, Any]] = None,
    ) -> StructureResult:
        """Resolve a molecule query to XYZ coordinates.

        Args:
            query: Molecule name (Korean or English), SMILES, or chemical formula.

        Returns:
            StructureResult with xyz, sdf, smiles, etc.

        Raises:
            ValueError: If structure cannot be resolved from any source.
        """
        if not query or not query.strip():
            error = ValueError(
                "구조 쿼리가 비어있습니다 / Structure query is empty"
            )
            error.failure_class = "invalid_input"  # type: ignore[attr-defined]
            raise error

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
        ranked_queries = self._rank_query_candidates(query_plan, action_plan=plan, state=state)
        if ranked_queries:
            query_plan["ranked_candidate_queries"] = ranked_queries
            query_plan["candidate_queries"] = [item.get("query") for item in ranked_queries if str(item.get("query") or "").strip()]

        for candidate in query_plan["candidate_queries"]:
            cache_key = candidate.lower().strip()
            cached = self._cache_get(cache_key)
            if cached:
                logger.debug("Cache hit: %s", cache_key)
                return cached

        # Step 2: Try MolChat pipeline across candidate queries
        saw_infrastructure_failure = False
        for candidate in query_plan["candidate_queries"]:
            result = await self._try_molchat_with_search_fallback(candidate)
            if self._last_failure_class == "infrastructure":
                saw_infrastructure_failure = True
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
                result.name = str(result.name or query_plan.get("display_query") or original_query)
                result.resolved_structure_name = str(result.resolved_structure_name or result.name or original_query)
                result.resolved_smiles = str(result.resolved_smiles or result.smiles or "").strip() or None
                if query_plan.get("condensed_formula"):
                    result.structure_query_raw = str(result.structure_query_raw or original_query)
                result.query_plan = query_plan
                self._cache_put(candidate.lower().strip(), result)
                return result

        # Step 3: Try PubChem fallback across candidate queries
        pubchem_enabled = os.getenv("PUBCHEM_FALLBACK", "true").lower() in ("true", "1", "yes")
        if pubchem_enabled:
            for candidate in query_plan["candidate_queries"]:
                result = await self._try_pubchem(candidate)
                if self._last_failure_class == "infrastructure":
                    saw_infrastructure_failure = True
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
                    result.name = str(result.name or query_plan.get("display_query") or original_query)
                    result.resolved_structure_name = str(result.resolved_structure_name or result.name or original_query)
                    result.resolved_smiles = str(result.resolved_smiles or result.smiles or "").strip() or None
                    if query_plan.get("condensed_formula"):
                        result.structure_query_raw = str(result.structure_query_raw or original_query)
                    result.query_plan = query_plan
                    self._cache_put(candidate.lower().strip(), result)
                    return result

        if query_plan.get("condensed_formula"):
            result = await self._try_condensed_formula_llm_fallback(original_query)
            if result:
                result.query_plan = query_plan
                self._cache_put(original_query.lower().strip(), result)
                return result

        error = ValueError(
            f"'{original_query}' 구조를 찾을 수 없습니다. "
            f"MolChat 및 PubChem에서 모두 실패했습니다. / "
            f"Cannot resolve structure for '{original_query}'. "
            f"Both MolChat and PubChem failed."
        )
        error.failure_class = "infrastructure" if saw_infrastructure_failure else "no_match"  # type: ignore[attr-defined]
        raise error

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

            self._last_failure_class = None
            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="molchat",
                molecular_weight=molecular_weight,
                resolved_structure_name=name,
                resolved_smiles=smiles,
            )

        except Exception as e:
            self._last_failure_class = _classify_resolution_failure(e)
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

            self._last_failure_class = None
            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="pubchem",
                molecular_weight=None,
                resolved_structure_name=name,
                resolved_smiles=smiles,
            )

        except Exception as e:
            self._last_failure_class = _classify_resolution_failure(e)
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
