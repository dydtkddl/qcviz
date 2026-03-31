"""
Query Validation Pipeline for Molecule Card
============================================
3-stage validation to prevent false matches:
  Stage 1: PubChem Autocomplete dictionary check
  Stage 2: Jaro-Winkler string similarity
  Stage 3: Synonym reverse lookup

Stage 1 is mandatory (must pass).
Stage 2 and Stage 3 are OR-relation (either pass is OK).
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger(__name__)

AUTOCOMPLETE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/{query}/json?limit=5"
AUTOCOMPLETE_TIMEOUT = 2.0
JARO_WINKLER_THRESHOLD = 0.75


@dataclass
class ValidationResult:
    valid: bool
    stage_failed: str | None = None
    reason: str | None = None
    autocomplete_total: int = 0
    jaro_winkler_score: float = 0.0
    synonym_matched: bool = False
    elapsed_ms: float = 0.0


# ── Jaro-Winkler (pure Python, no dependencies) ──

def _jaro_similarity(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3
    return jaro


def _jaro_winkler(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
    jaro = _jaro_similarity(s1, s2)
    prefix = 0
    for i in range(min(4, len(s1), len(s2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * prefix_weight * (1 - jaro)


# ── Stage 1: PubChem Autocomplete ──

async def _check_autocomplete(query: str) -> tuple[bool, int]:
    """Check if query exists in PubChem compound dictionary."""
    query_clean = query.strip().lower()
    if len(query_clean) < 3:
        return True, -1  # too short, skip

    try:
        async with httpx.AsyncClient(timeout=AUTOCOMPLETE_TIMEOUT) as client:
            url = AUTOCOMPLETE_URL.format(query=httpx.URL(query_clean).raw_path.decode() if False else query_clean)
            # Simple URL construction
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/{query_clean}/json?limit=5"
            resp = await client.get(url)
            if resp.status_code != 200:
                return True, -1  # API error → pass (fail-open)

            data = resp.json()
            total = data.get("total", 0)
            terms = data.get("dictionary_terms", {}).get("compound", [])

            if total == 0:
                return False, 0

            # Check if any returned term is related to the query
            query_lower = query_clean.lower()
            for term in terms:
                term_lower = term.lower()
                if query_lower in term_lower or term_lower in query_lower:
                    return True, total
                # Also check Jaro-Winkler between query and autocomplete result
                if _jaro_winkler(query_lower, term_lower) >= 0.85:
                    return True, total

            # Autocomplete returned results but none match the query well
            return False, total

    except Exception as e:
        logger.warning("autocomplete_check_error", error=str(e))
        return True, -1  # fail-open on error


# ── Stage 2: Jaro-Winkler similarity ──

def _check_jaro_winkler(query: str, result_name: str, iupac_name: str | None) -> tuple[bool, float]:
    """Check string similarity between query and result names."""
    q = query.strip().lower()
    best = 0.0

    for name in [result_name, iupac_name]:
        if not name:
            continue
        n = name.strip().lower()
        score = _jaro_winkler(q, n)
        best = max(best, score)

        # Also check individual words for multi-word queries
        # e.g., "citric acid" vs "citric acid" should work
        if ' ' in q and ' ' in n:
            q_words = set(q.split())
            n_words = set(n.split())
            if q_words & n_words:  # shared words
                overlap = len(q_words & n_words) / max(len(q_words), len(n_words))
                best = max(best, overlap)

    return best >= JARO_WINKLER_THRESHOLD, best


# ── Stage 3: Synonym reverse check ──

def _check_synonyms(query: str, synonyms: list[str]) -> bool:
    """Check if query appears in the synonym list."""
    if not synonyms:
        return False

    q = query.strip().lower()
    for syn in synonyms:
        s = syn.strip().lower()
        if q in s or s in q:
            return True
        # Check Jaro-Winkler for close matches (e.g., typos)
        if _jaro_winkler(q, s) >= 0.90:
            return True
    return False


# ── Main Validation Function ──

async def validate_query_match(
    query: str,
    result_name: str,
    iupac_name: str | None = None,
    synonyms: list[str] | None = None,
    is_cid_query: bool = False,
) -> ValidationResult:
    """
    Validate that a search result actually matches the query.
    
    Args:
        query: Original user query string
        result_name: Name returned by PubChem search
        iupac_name: IUPAC name of the result
        synonyms: List of synonyms for the result
        is_cid_query: If True, skip all validation (CID is exact)
    
    Returns:
        ValidationResult with valid=True/False and diagnostics
    """
    t0 = time.perf_counter()

    # CID queries are always valid (exact identifier)
    if is_cid_query:
        return ValidationResult(
            valid=True,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    synonyms = synonyms or []

    # ── Stage 1: Autocomplete ──
    ac_pass, ac_total = await _check_autocomplete(query)
    if not ac_pass:
        return ValidationResult(
            valid=False,
            stage_failed="autocomplete",
            reason=f"Query '{query}' not found in PubChem compound dictionary (total={ac_total})",
            autocomplete_total=ac_total,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    # ── Stage 2 & 3: OR-relation ──
    jw_pass, jw_score = _check_jaro_winkler(query, result_name, iupac_name)
    syn_pass = _check_synonyms(query, synonyms)

    if not jw_pass and not syn_pass:
        return ValidationResult(
            valid=False,
            stage_failed="similarity_and_synonym",
            reason=f"Low similarity (JW={jw_score:.3f}) and query not in synonyms",
            autocomplete_total=ac_total,
            jaro_winkler_score=jw_score,
            synonym_matched=False,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    return ValidationResult(
        valid=True,
        autocomplete_total=ac_total,
        jaro_winkler_score=jw_score,
        synonym_matched=syn_pass,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )
