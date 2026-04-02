"""
HallucinationGuard – three-stage verification of LLM responses.

Stages:
  1. **Cross-reference** – compare claimed facts against tool results.
  2. **Confidence scoring** – evaluate numeric claims and chemical assertions.
  3. **Citation validation** – check that cited sources exist and match.

Output: ``GuardResult`` with overall confidence, list of flags,
and optionally a corrected response.

Design:
  • Runs synchronously after the LLM produces its final answer.
  • Does NOT call the LLM again (no recursive risk).
  • All checks are rule-based or regex-based for determinism.
  • Configurable thresholds via settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Thresholds
_MIN_CONFIDENCE = 0.7
_MOLECULAR_WEIGHT_TOLERANCE = 0.5  # Daltons
_ENERGY_TOLERANCE = 0.01           # Hartree
_LOGP_TOLERANCE = 0.5


@dataclass
class GuardResult:
    """Output of the hallucination guard."""

    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    corrected_response: str | None = None
    checks_performed: int = 0
    checks_passed: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.flags) == 0 and self.confidence >= _MIN_CONFIDENCE


class HallucinationGuard:
    """Three-stage hallucination detection and mitigation."""

    async def check(
        self,
        response: str,
        tool_results: list[Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> GuardResult:
        """Run all guard stages on the LLM response.

        Args:
            response: The LLM's text response.
            tool_results: Raw results from tool calls (for cross-reference).
            context: Additional context (e.g., molecule data).
        """
        result = GuardResult()
        tool_results = tool_results or []
        context = context or {}

        # Stage 1: Cross-reference
        self._stage_cross_reference(response, tool_results, result)

        # Stage 2: Confidence scoring
        self._stage_confidence_scoring(response, tool_results, result)

        # Stage 3: Citation validation
        self._stage_citation_validation(response, result)

        # Additional checks
        self._check_hedging_language(response, result)
        self._check_fabricated_data(response, tool_results, result)

        # Calculate overall confidence
        if result.checks_performed > 0:
            result.confidence = round(
                result.checks_passed / result.checks_performed, 2
            )
        else:
            result.confidence = 0.95  # Default high if no checkable claims

        # Build corrected response if needed
        if not result.is_clean:
            result.corrected_response = self._build_corrected_response(
                response, result
            )

        logger.info(
            "hallucination_guard_result",
            confidence=result.confidence,
            flags=result.flags,
            checks=f"{result.checks_passed}/{result.checks_performed}",
        )

        return result

    # ═══════════════════════════════════════════
    # Stage 1: Cross-reference
    # ═══════════════════════════════════════════

    def _stage_cross_reference(
        self,
        response: str,
        tool_results: list[Any],
        result: GuardResult,
    ) -> None:
        """Compare claimed molecular data against tool results."""
        if not tool_results:
            return

        flat_data = self._flatten_tool_results(tool_results)

        # Check molecular weight claims
        mw_matches = re.findall(
            r"(?:분자량|molecular weight|MW|mol\.?\s*wt\.?)[\s:]*"
            r"([\d.]+)\s*(?:g/mol|Da|dalton)?",
            response,
            re.IGNORECASE,
        )
        for mw_str in mw_matches:
            result.checks_performed += 1
            claimed_mw = float(mw_str)
            actual_mw = flat_data.get("molecular_weight")
            if actual_mw is not None:
                if abs(claimed_mw - actual_mw) <= _MOLECULAR_WEIGHT_TOLERANCE:
                    result.checks_passed += 1
                else:
                    result.flags.append("WRONG_MOLECULAR_WEIGHT")
                    result.issues.append({
                        "type": "cross_ref",
                        "field": "molecular_weight",
                        "claimed": claimed_mw,
                        "actual": actual_mw,
                    })

        # Check LogP claims
        logp_matches = re.findall(
            r"(?:LogP|XLogP|logP)[\s:]*([+-]?[\d.]+)",
            response,
            re.IGNORECASE,
        )
        for logp_str in logp_matches:
            result.checks_performed += 1
            claimed_logp = float(logp_str)
            actual_logp = flat_data.get("logp") or flat_data.get("xlogp")
            if actual_logp is not None:
                if abs(claimed_logp - actual_logp) <= _LOGP_TOLERANCE:
                    result.checks_passed += 1
                else:
                    result.flags.append("WRONG_LOGP")
                    result.issues.append({
                        "type": "cross_ref",
                        "field": "logp",
                        "claimed": claimed_logp,
                        "actual": actual_logp,
                    })

        # Check molecular formula
        formula_matches = re.findall(
            r"(?:분자식|formula|분자 공식)[\s:]*([A-Z][A-Za-z0-9]+)",
            response,
            re.IGNORECASE,
        )
        for formula in formula_matches:
            result.checks_performed += 1
            actual_formula = flat_data.get("molecular_formula")
            if actual_formula is not None:
                if formula.strip() == actual_formula.strip():
                    result.checks_passed += 1
                else:
                    result.flags.append("WRONG_FORMULA")
                    result.issues.append({
                        "type": "cross_ref",
                        "field": "molecular_formula",
                        "claimed": formula,
                        "actual": actual_formula,
                    })

        # Check CID
        cid_matches = re.findall(
            r"(?:CID|PubChem\s*(?:CID)?)[\s:#]*(\d{2,})",
            response,
            re.IGNORECASE,
        )
        for cid_str in cid_matches:
            result.checks_performed += 1
            claimed_cid = int(cid_str)
            actual_cid = flat_data.get("cid")
            if actual_cid is not None:
                if claimed_cid == actual_cid:
                    result.checks_passed += 1
                else:
                    result.flags.append("WRONG_CID")
                    result.issues.append({
                        "type": "cross_ref",
                        "field": "cid",
                        "claimed": claimed_cid,
                        "actual": actual_cid,
                    })

    # ═══════════════════════════════════════════
    # Stage 2: Confidence scoring
    # ═══════════════════════════════════════════

    def _stage_confidence_scoring(
        self,
        response: str,
        tool_results: list[Any],
        result: GuardResult,
    ) -> None:
        """Score confidence based on response characteristics."""
        # Check for specific numeric claims without tool backing
        numeric_claims = re.findall(
            r"([\d.]+)\s*(?:kcal/mol|kJ/mol|eV|Hartree|Å|nm|pm|K|°C|atm|bar|ppm)",
            response,
        )

        has_tool_data = bool(tool_results)

        if numeric_claims and not has_tool_data:
            # Numeric claims without tool results = suspicious
            result.flags.append("UNVERIFIED_NUMERIC_CLAIMS")
            result.issues.append({
                "type": "confidence",
                "message": f"Found {len(numeric_claims)} numeric claims with no tool data",
                "values": numeric_claims[:5],
            })

        # Check for SMILES-like strings that weren't validated
        smiles_pattern = re.findall(
            r"`([A-Za-z0-9@+\-\[\]\\/()\=#$.]+)`",
            response,
        )
        for smiles_candidate in smiles_pattern:
            if len(smiles_candidate) > 5 and any(
                c in smiles_candidate for c in "()[]=#"
            ):
                result.checks_performed += 1
                # Check against tool results
                flat_data = self._flatten_tool_results(tool_results)
                actual_smiles = flat_data.get("canonical_smiles")
                if actual_smiles and smiles_candidate == actual_smiles:
                    result.checks_passed += 1
                elif actual_smiles:
                    result.flags.append("POSSIBLY_WRONG_SMILES")
                    result.issues.append({
                        "type": "confidence",
                        "field": "smiles",
                        "claimed": smiles_candidate,
                        "actual": actual_smiles,
                    })

    # ═══════════════════════════════════════════
    # Stage 3: Citation validation
    # ═══════════════════════════════════════════

    def _stage_citation_validation(
        self,
        response: str,
        result: GuardResult,
    ) -> None:
        """Validate that cited sources are plausible."""
        # Check for PubChem URLs
        pubchem_urls = re.findall(
            r"pubchem\.ncbi\.nlm\.nih\.gov/compound/(\d+)",
            response,
        )
        for cid_str in pubchem_urls:
            result.checks_performed += 1
            cid = int(cid_str)
            if 1 <= cid <= 500_000_000:  # Plausible CID range
                result.checks_passed += 1
            else:
                result.flags.append("IMPLAUSIBLE_CID_CITATION")

        # Check for DOI patterns
        dois = re.findall(r"10\.\d{4,}/[^\s]+", response)
        for doi in dois:
            result.checks_performed += 1
            # Basic plausibility: DOI format is correct
            if re.match(r"^10\.\d{4,}/\S+$", doi):
                result.checks_passed += 1
            else:
                result.flags.append("MALFORMED_DOI")

        # Check for fabricated journal names
        fake_journal_patterns = [
            r"Journal of (?:Advanced|Modern|International) (?:Chemistry|Science)",
            r"Nature Chemistry.*vol\.\s*\d+.*p\.\s*\d+",
        ]
        for pattern in fake_journal_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                result.checks_performed += 1
                result.flags.append("POSSIBLY_FABRICATED_CITATION")
                result.issues.append({
                    "type": "citation",
                    "message": "Response contains a possibly fabricated citation",
                })

    # ═══════════════════════════════════════════
    # Additional checks
    # ═══════════════════════════════════════════

    def _check_hedging_language(
        self,
        response: str,
        result: GuardResult,
    ) -> None:
        """Detect excessive hedging that may indicate uncertainty."""
        hedging_markers = [
            "아마도", "추정", "대략", "정확하지 않", "확인이 필요",
            "probably", "approximately", "might be", "not sure",
            "I think", "I believe", "it seems", "possibly",
        ]
        hedge_count = sum(
            1 for marker in hedging_markers
            if marker.lower() in response.lower()
        )

        if hedge_count >= 3:
            result.flags.append("EXCESSIVE_HEDGING")
            result.issues.append({
                "type": "language",
                "message": f"Response contains {hedge_count} hedging markers",
            })

    def _check_fabricated_data(
        self,
        response: str,
        tool_results: list[Any],
        result: GuardResult,
    ) -> None:
        """Detect potentially fabricated structured data."""
        # Suspiciously round numbers in scientific context
        round_number_pattern = re.findall(
            r"([\d]+\.0{2,})\s*(?:kcal|kJ|eV|Hartree)", response
        )
        if round_number_pattern and not tool_results:
            result.flags.append("SUSPICIOUSLY_ROUND_VALUES")
            result.issues.append({
                "type": "fabrication",
                "message": "Suspiciously round scientific values without tool data",
                "values": round_number_pattern[:3],
            })

    # ═══════════════════════════════════════════
    # Correction
    # ═══════════════════════════════════════════

    def _build_corrected_response(
        self,
        original: str,
        guard_result: GuardResult,
    ) -> str:
        """Append a disclaimer to flagged responses."""
        disclaimer_parts: list[str] = []

        if "WRONG_MOLECULAR_WEIGHT" in guard_result.flags:
            for issue in guard_result.issues:
                if issue.get("field") == "molecular_weight":
                    disclaimer_parts.append(
                        f"⚠️ 분자량 수정: {issue['claimed']} → {issue['actual']} g/mol"
                    )

        if "WRONG_FORMULA" in guard_result.flags:
            for issue in guard_result.issues:
                if issue.get("field") == "molecular_formula":
                    disclaimer_parts.append(
                        f"⚠️ 분자식 수정: {issue['claimed']} → {issue['actual']}"
                    )

        if "WRONG_CID" in guard_result.flags:
            for issue in guard_result.issues:
                if issue.get("field") == "cid":
                    disclaimer_parts.append(
                        f"⚠️ CID 수정: {issue['claimed']} → {issue['actual']}"
                    )

        if "UNVERIFIED_NUMERIC_CLAIMS" in guard_result.flags:
            disclaimer_parts.append(
                "⚠️ 일부 수치 데이터는 도구로 검증되지 않았습니다."
            )

        if "POSSIBLY_FABRICATED_CITATION" in guard_result.flags:
            disclaimer_parts.append(
                "⚠️ 인용된 일부 출처의 정확성을 확인할 수 없습니다."
            )

        if not disclaimer_parts:
            return original

        disclaimer = "\n\n---\n" + "\n".join(disclaimer_parts)
        return original + disclaimer

    # ═══════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════

    @staticmethod
    def _flatten_tool_results(tool_results: list[Any]) -> dict[str, Any]:
        """Flatten tool result list into a single dict for easy lookup."""
        flat: dict[str, Any] = {}
        for tr in tool_results:
            if isinstance(tr, dict):
                flat.update(tr)
                # Handle nested structures
                if "molecule" in tr and isinstance(tr["molecule"], dict):
                    flat.update(tr["molecule"])
                if "properties" in tr and isinstance(tr["properties"], dict):
                    flat.update(tr["properties"])
                if "results" in tr and isinstance(tr["results"], list):
                    for item in tr["results"]:
                        if isinstance(item, dict):
                            flat.update(item)
        return flat