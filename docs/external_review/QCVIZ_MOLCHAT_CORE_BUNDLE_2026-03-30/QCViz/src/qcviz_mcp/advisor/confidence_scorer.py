"""
Calculation Confidence Scorer (F7).

Computes a composite confidence score for quantum chemistry
calculations based on convergence quality, method appropriateness,
basis set adequacy, and reference data agreement.

Version: 1.1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import (
    load_dft_accuracy_table,
    load_functional_recommendations,
    normalize_func_key,
)

__all__ = ["ConfidenceScorer", "ConfidenceReport"]

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "This confidence score is a heuristic estimate based on "
    "convergence metrics, method benchmarks, and reference data "
    "agreement. It should not be interpreted as a statistical "
    "probability. Consult a computational chemist for definitive "
    "quality assessment."
)


@dataclass
class ConfidenceReport:
    """Detailed confidence score breakdown."""

    overall_score: float
    convergence_score: float
    basis_score: float
    method_score: float
    spin_score: float
    reference_score: float
    breakdown_text: str
    recommendations: list = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class ConfidenceScorer:
    """Computes composite confidence scores for QC calculations.

    Evaluates multiple quality dimensions and combines them into
    a single 0.0-1.0 confidence metric with detailed breakdown.
    """

    def __init__(self):
        """Initialize scorer with reference data."""
        self._accuracy = load_dft_accuracy_table()
        self._recommendations = load_functional_recommendations()

    def score(
        self,
        converged=True,
        n_scf_cycles=0,
        max_cycles=200,
        functional="B3LYP",
        basis="def2-SVP",
        system_type="organic_small",
        spin=0,
        s2_expected=0.0,
        s2_actual=0.0,
        validation_status=None,
    ):
        """Compute a composite confidence score.

        Args:
            converged (bool): Whether SCF converged.
            n_scf_cycles (int): Number of SCF cycles used.
            max_cycles (int): Maximum allowed SCF cycles.
            functional (str): DFT functional used.
            basis (str): Basis set used.
            system_type (str): System classification.
            spin (int): Spin state (2S).
            s2_expected (float): Expected <S^2> value.
            s2_actual (float): Actual <S^2> value from calculation.
            validation_status (str): 'PASS', 'WARN', 'FAIL', or None.

        Returns:
            ConfidenceReport: Detailed score breakdown.
        """
        # 1. Convergence quality (0-1)
        conv_score = self._score_convergence(
            converged, n_scf_cycles, max_cycles
        )

        # 2. Basis set adequacy (0-1)
        basis_score = self._score_basis(basis, system_type)

        # 3. Method appropriateness (0-1)
        method_score = self._score_method(functional, system_type)

        # 4. Spin contamination (0-1)
        spin_score = self._score_spin(
            spin, s2_expected, s2_actual
        )

        # 5. Reference agreement (0-1)
        ref_score = self._score_reference(validation_status)

        # Weights (verified: both sum to 1.0)
        if spin > 0:
            weights = {
                "convergence": 0.20,
                "basis": 0.15,
                "method": 0.25,
                "spin": 0.20,
                "reference": 0.20,
            }
        else:
            weights = {
                "convergence": 0.20,
                "basis": 0.20,
                "method": 0.25,
                "spin": 0.05,
                "reference": 0.30,
            }

        overall = (
            weights["convergence"] * conv_score
            + weights["basis"] * basis_score
            + weights["method"] * method_score
            + weights["spin"] * spin_score
            + weights["reference"] * ref_score
        )

        # Hard cap: unconverged calculations must never exceed 0.4
        if not converged:
            overall = min(overall, 0.4)

        breakdown = self._format_breakdown(
            conv_score, basis_score, method_score,
            spin_score, ref_score, weights,
        )

        recs = self._generate_recommendations(
            conv_score, basis_score, method_score,
            spin_score, ref_score, functional, basis,
        )

        return ConfidenceReport(
            overall_score=round(overall, 2),
            convergence_score=round(conv_score, 2),
            basis_score=round(basis_score, 2),
            method_score=round(method_score, 2),
            spin_score=round(spin_score, 2),
            reference_score=round(ref_score, 2),
            breakdown_text=breakdown,
            recommendations=recs,
            disclaimer=_DISCLAIMER,
        )

    def _score_convergence(self, converged, n_cycles, max_cycles):
        """Score SCF convergence quality.

        Args:
            converged (bool): Whether SCF converged.
            n_cycles (int): Cycles used.
            max_cycles (int): Max cycles.

        Returns:
            float: Score 0.0-1.0.
        """
        if not converged:
            return 0.1
        if n_cycles == 0:
            return 0.7  # Unknown cycle count
        ratio = n_cycles / float(max_cycles)
        if ratio < 0.1:
            return 1.0
        if ratio < 0.3:
            return 0.9
        if ratio < 0.5:
            return 0.7
        return 0.5

    def _score_basis(self, basis, system_type):
        """Score basis set adequacy for the system type.

        Args:
            basis (str): Basis set name.
            system_type (str): System classification.

        Returns:
            float: Score 0.0-1.0.
        """
        basis_lower = basis.lower()
        if "qzvp" in basis_lower:
            return 1.0
        if "tzvp" in basis_lower:
            return 0.9
        if "svp" in basis_lower:
            if system_type in ("organic_small", "radical"):
                return 0.7
            return 0.5  # SVP too small for complex systems
        # Unknown basis
        return 0.5

    def _score_method(self, functional, system_type):
        """Score method appropriateness for system type.

        Args:
            functional (str): DFT functional.
            system_type (str): System classification.

        Returns:
            float: Score 0.0-1.0.
        """
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})
        wtmad2 = acc.get("wtmad2_kcal", None)

        if wtmad2 is None:
            return 0.5  # Unknown functional

        # FIXED #18: WTMAD-2 thresholds aligned with official Bonn
        # GMTKN55 values (def2-QZVP + dispersion correction).
        # < 5.0 = excellent (wB97X-V 3.98, M06-2X 4.94)
        # 5-7   = good (PW6B95 5.50, B3LYP 6.42, PBE0 6.61)
        # 7-10  = adequate (TPSSh 7.54, R2SCAN ~7.9, TPSS 9.10)
        # > 10  = poor (PBE 10.32)
        if wtmad2 <= 5.0:
            base = 0.95
        elif wtmad2 <= 7.0:
            base = 0.80
        elif wtmad2 <= 10.0:
            base = 0.65
        else:
            base = 0.40

        # System-specific bonus for recommended functional
        # FIXED #7: Exact match only (no substring)
        rules = self._recommendations.get(system_type, {})
        default_func = rules.get("default", {}).get("functional", "")
        if default_func:
            default_func_key = normalize_func_key(default_func)
            if func_key == default_func_key:
                base = min(1.0, base + 0.05)

        return base

    def _score_spin(self, spin, s2_expected, s2_actual):
        """Score spin contamination quality.

        Args:
            spin (int): 2S spin value.
            s2_expected (float): Expected <S^2>.
            s2_actual (float): Actual <S^2>.

        Returns:
            float: Score 0.0-1.0.
        """
        if spin == 0:
            return 1.0  # Closed-shell, no issue
        if s2_actual == 0.0 and s2_expected == 0.0:
            return 0.7  # No data available
        if s2_expected == 0.0:
            return 0.7

        deviation = abs(s2_actual - s2_expected) / s2_expected
        if deviation < 0.05:
            return 1.0
        if deviation < 0.10:
            return 0.8
        if deviation < 0.20:
            return 0.5
        return 0.2

    def _score_reference(self, validation_status):
        """Score agreement with reference data.

        Args:
            validation_status (str or None): Validation status.

        Returns:
            float: Score 0.0-1.0.
        """
        if validation_status is None:
            return 0.5  # No validation performed
        if validation_status == "PASS":
            return 1.0
        if validation_status == "WARN":
            return 0.6
        if validation_status == "FAIL":
            return 0.2
        return 0.5

    def _format_breakdown(
        self, conv, basis, method, spin, ref, weights
    ):
        """Format a human-readable score breakdown.

        Args:
            conv (float): Convergence score.
            basis (float): Basis score.
            method (float): Method score.
            spin (float): Spin score.
            ref (float): Reference score.
            weights (dict): Weight dictionary.

        Returns:
            str: Formatted breakdown text.
        """
        lines = []
        lines.append("Confidence Score Breakdown:")
        lines.append(
            "  Convergence:  %.2f (weight: %.0f%%)"
            % (conv, weights["convergence"] * 100)
        )
        lines.append(
            "  Basis Set:    %.2f (weight: %.0f%%)"
            % (basis, weights["basis"] * 100)
        )
        lines.append(
            "  Method:       %.2f (weight: %.0f%%)"
            % (method, weights["method"] * 100)
        )
        lines.append(
            "  Spin:         %.2f (weight: %.0f%%)"
            % (spin, weights["spin"] * 100)
        )
        lines.append(
            "  Reference:    %.2f (weight: %.0f%%)"
            % (ref, weights["reference"] * 100)
        )
        return "\n".join(lines)

    def _generate_recommendations(
        self, conv, basis, method, spin, ref,
        functional, basis_set,
    ):
        """Generate improvement recommendations.

        Args:
            conv (float): Convergence score.
            basis (float): Basis score.
            method (float): Method score.
            spin (float): Spin score.
            ref (float): Reference score.
            functional (str): Functional name.
            basis_set (str): Basis set name.

        Returns:
            list: List of recommendation strings.
        """
        recs = []
        if conv < 0.5:
            recs.append(
                "SCF convergence is poor. Try increasing max_cycle, "
                "using level shifting, or applying DIIS damping."
            )
        if basis < 0.7:
            recs.append(
                "Consider using a larger basis set (def2-TZVP or "
                "def2-QZVP) for more reliable results."
            )
        if method < 0.6:
            recs.append(
                "The chosen functional (%s) may not be optimal for "
                "this system type. Consult the preset recommender "
                "for alternatives." % functional
            )
        if spin < 0.5:
            recs.append(
                "Significant spin contamination detected. Results "
                "for this open-shell system may be unreliable. "
                "Consider ROHF or a different functional."
            )
        if ref < 0.5:
            recs.append(
                "Computed properties deviate from reference data. "
                "Re-check geometry and method choice."
            )
        return recs
