"""
Literature Energy Validator (F4).

Compares computed molecular properties against curated reference
databases (NIST CCCBDB, GMTKN55, W4-11) to assess calculation
quality and flag potential issues.

Version: 1.1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import (
    load_nist_bonds,
    load_dft_accuracy_table,
    normalize_func_key,
)

__all__ = [
    "LiteratureEnergyValidator",
    "ValidationRequest",
    "ValidationResult",
    "BondValidation",
]

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "IMPORTANT: This validation is based on comparison with a limited "
    "curated reference dataset. It provides a preliminary quality "
    "assessment only. Results should be reviewed by a qualified "
    "computational chemist before drawing scientific conclusions or "
    "preparing manuscripts for publication."
)

# Status thresholds
_BOND_PASS_THRESHOLD = 0.02   # Angstrom
_BOND_WARN_THRESHOLD = 0.05   # Angstrom
_ANGLE_PASS_THRESHOLD = 2.0   # degrees
_ANGLE_WARN_THRESHOLD = 5.0   # degrees

# Hill-system formula aliases for common molecules
_FORMULA_ALIASES = {
    "H2CO": "CH2O",
    "HCHO": "CH2O",
    "H2O2": "H2O2",
    "HOOH": "H2O2",
}


@dataclass
class BondValidation:
    """Validation result for a single bond length or angle."""

    bond_type: str
    computed: float
    reference: float
    reference_source: str
    deviation: float
    status: str
    expected_accuracy: str
    comment: str


@dataclass
class ValidationRequest:
    """Input for literature validation."""

    bond_lengths: dict = field(default_factory=dict)
    bond_angles: dict = field(default_factory=dict)
    energy_hartree: float = 0.0
    functional: str = ""
    basis: str = ""
    system_formula: str = ""


@dataclass
class ValidationResult:
    """Complete validation output."""

    bond_validations: list = field(default_factory=list)
    angle_validations: list = field(default_factory=list)
    method_assessment: str = ""
    overall_status: str = "UNKNOWN"
    confidence: float = 0.0
    recommendations: list = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class LiteratureEnergyValidator:
    """Validates computed results against literature reference data.

    Compares bond lengths, bond angles, and energies with curated
    reference values from NIST CCCBDB and benchmark databases.
    Provides status tags (PASS/WARN/FAIL) and actionable recommendations.
    """

    def __init__(self):
        """Initialize validator with reference databases."""
        self._nist = load_nist_bonds()
        self._accuracy = load_dft_accuracy_table()

    def validate(self, request):
        """Validate computed properties against reference data.

        Args:
            request (ValidationRequest): Properties to validate.

        Returns:
            ValidationResult: Detailed validation report.
        """
        bond_vals = []
        if request.bond_lengths:
            bond_vals = self._validate_bonds(
                request.bond_lengths,
                request.system_formula,
                request.functional,
                request.basis,
            )

        angle_vals = []
        if request.bond_angles:
            angle_vals = self._validate_angles(
                request.bond_angles,
                request.system_formula,
            )

        method_assess = self._assess_method(
            request.functional, request.basis
        )

        overall = self._compute_overall_status(
            bond_vals, angle_vals
        )
        confidence = self._compute_confidence(
            bond_vals, angle_vals, request.functional
        )
        recs = self._generate_recommendations(
            bond_vals, angle_vals, request.functional, request.basis
        )

        return ValidationResult(
            bond_validations=bond_vals,
            angle_validations=angle_vals,
            method_assessment=method_assess,
            overall_status=overall,
            confidence=round(confidence, 2),
            recommendations=recs,
            disclaimer=_DISCLAIMER,
        )

    def _resolve_formula(self, formula):
        """Resolve formula aliases to canonical Hill-system key.

        Args:
            formula (str): Molecular formula.

        Returns:
            str: Canonical formula key.
        """
        return _FORMULA_ALIASES.get(formula, formula)

    def _validate_bonds(
        self, bond_lengths, formula, functional, basis
    ):
        """Validate computed bond lengths against NIST data.

        Args:
            bond_lengths (dict): {'O-H': 0.969, ...}
            formula (str): Molecular formula.
            functional (str): DFT functional used.
            basis (str): Basis set used.

        Returns:
            list: List of BondValidation objects.
        """
        results = []
        canonical = self._resolve_formula(formula)
        mol_data = self._nist.get(canonical, {})
        # Also try original formula
        if not mol_data or canonical == formula:
            mol_data = self._nist.get(formula, mol_data)

        func_key = normalize_func_key(functional)
        accuracy_data = self._accuracy.get(func_key, {})
        expected_mae = accuracy_data.get(
            "bond_length_mae_angstrom", 0.01
        )

        for bond_type, computed_val in bond_lengths.items():
            # Normalize bond type: "O-H" and "H-O" should match
            normalized = self._normalize_bond_type(bond_type)
            ref_entry = mol_data.get(normalized, None)

            if ref_entry is None:
                # Try reverse
                reversed_bt = self._reverse_bond_type(normalized)
                ref_entry = mol_data.get(reversed_bt, None)

            if ref_entry is None:
                # No reference data available
                continue

            ref_val = ref_entry.get("value", 0.0)
            source = ref_entry.get("source", "NIST CCCBDB")
            deviation = abs(computed_val - ref_val)

            if deviation <= _BOND_PASS_THRESHOLD:
                status = "PASS"
                comment = (
                    "Within expected DFT accuracy "
                    "(typical MAE: %.3f Angstrom)." % expected_mae
                )
            elif deviation <= _BOND_WARN_THRESHOLD:
                status = "WARN"
                comment = (
                    "Deviation (%.3f Angstrom) is slightly above typical "
                    "DFT accuracy. Consider checking geometry convergence."
                    % deviation
                )
            else:
                status = "FAIL"
                comment = (
                    "Deviation (%.3f Angstrom) significantly exceeds "
                    "typical DFT accuracy (MAE %.3f Angstrom). "
                    "This may indicate a problem with the geometry "
                    "or method choice." % (deviation, expected_mae)
                )

            results.append(BondValidation(
                bond_type=bond_type,
                computed=round(computed_val, 4),
                reference=round(ref_val, 4),
                reference_source=source,
                deviation=round(deviation, 4),
                status=status,
                expected_accuracy=(
                    "%s/%s typical MAE: %.3f Angstrom"
                    % (functional, basis, expected_mae)
                ),
                comment=comment,
            ))

        return results

    def _validate_angles(self, bond_angles, formula):
        """Validate computed bond angles against reference data.

        Args:
            bond_angles (dict): {'H-O-H': 104.5, ...}
            formula (str): Molecular formula.

        Returns:
            list: List of BondValidation objects (reused for angles).
        """
        results = []
        canonical = self._resolve_formula(formula)
        mol_data = self._nist.get(canonical, {})
        if not mol_data or canonical == formula:
            mol_data = self._nist.get(formula, mol_data)

        for angle_type, computed_val in bond_angles.items():
            ref_entry = mol_data.get(angle_type, None)
            # FIXED #17: Try reversed angle key (e.g., F-C-H -> H-C-F)
            if ref_entry is None:
                reversed_at = self._reverse_bond_type(angle_type)
                ref_entry = mol_data.get(reversed_at, None)
            if ref_entry is None:
                continue

            ref_val = ref_entry.get("value", 0.0)
            source = ref_entry.get("source", "NIST CCCBDB")
            deviation = abs(computed_val - ref_val)

            if deviation <= _ANGLE_PASS_THRESHOLD:
                status = "PASS"
                comment = "Within expected accuracy."
            elif deviation <= _ANGLE_WARN_THRESHOLD:
                status = "WARN"
                comment = (
                    "Deviation of %.1f degrees is slightly above normal."
                    % deviation
                )
            else:
                status = "FAIL"
                comment = (
                    "Deviation of %.1f degrees is significant. "
                    "Check geometry convergence." % deviation
                )

            results.append(BondValidation(
                bond_type=angle_type,
                computed=round(computed_val, 2),
                reference=round(ref_val, 2),
                reference_source=source,
                deviation=round(deviation, 2),
                status=status,
                expected_accuracy="Typical DFT angle error: 1-2 degrees",
                comment=comment,
            ))

        return results

    def _assess_method(self, functional, basis):
        """Generate an overall method quality assessment.

        Args:
            functional (str): DFT functional.
            basis (str): Basis set.

        Returns:
            str: Assessment text.
        """
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})

        if not acc:
            return (
                "No benchmark data available for %s. "
                "Consider using a well-benchmarked functional."
                % functional
            )

        wtmad2 = acc.get("wtmad2_kcal", None)
        bond_mae = acc.get("bond_length_mae_angstrom", None)
        reaction_mae = acc.get("reaction_energy_mae_kcal", None)

        parts = []
        parts.append(
            "Method: %s/%s." % (functional, basis)
        )
        if wtmad2 is not None:
            parts.append(
                "GMTKN55 WTMAD-2: %.1f kcal/mol." % wtmad2
            )
        if bond_mae is not None:
            parts.append(
                "Typical bond length MAE: %.3f Angstrom." % bond_mae
            )
        if reaction_mae is not None:
            parts.append(
                "Typical reaction energy MAE: %.1f kcal/mol."
                % reaction_mae
            )

        return " ".join(parts)

    def _compute_overall_status(self, bond_vals, angle_vals):
        """Compute overall validation status.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.

        Returns:
            str: 'PASS', 'WARN', or 'FAIL'.
        """
        all_vals = bond_vals + angle_vals
        if not all_vals:
            return "UNKNOWN"

        statuses = [v.status for v in all_vals]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"

    def _compute_confidence(self, bond_vals, angle_vals, functional):
        """Compute numerical confidence score.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.
            functional (str): Functional used.

        Returns:
            float: Confidence score 0.0-1.0.
        """
        if not bond_vals and not angle_vals:
            return 0.5  # No data to validate against

        all_vals = bond_vals + angle_vals
        n_total = len(all_vals)
        n_pass = sum(1 for v in all_vals if v.status == "PASS")
        n_warn = sum(1 for v in all_vals if v.status == "WARN")

        base_score = (n_pass + 0.5 * n_warn) / n_total

        # Method quality bonus
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})
        wtmad2 = acc.get("wtmad2_kcal", 10.0)
        method_bonus = max(0, min(0.1, (10.0 - wtmad2) / 100.0))

        return min(1.0, base_score + method_bonus)

    def _generate_recommendations(
        self, bond_vals, angle_vals, functional, basis
    ):
        """Generate actionable recommendations.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.
            functional (str): Functional used.
            basis (str): Basis set used.

        Returns:
            list: List of recommendation strings.
        """
        recs = []

        fail_bonds = [v for v in bond_vals if v.status == "FAIL"]
        if fail_bonds:
            recs.append(
                "Some bond lengths deviate significantly from "
                "experiment. Consider: (1) re-optimizing the geometry "
                "with tighter convergence, (2) using a larger basis "
                "set, or (3) trying an alternative functional."
            )

        if "svp" in basis.lower() and "tzvp" not in basis.lower():
            recs.append(
                "A double-zeta basis set is used. For more accurate "
                "energies, perform a single-point calculation with "
                "def2-TZVP at the optimized geometry."
            )

        has_disp = any(
            d in functional.lower()
            for d in ("d3", "d4", "vv10", "-d")
        )
        if not has_disp:
            recs.append(
                "No dispersion correction detected. Modern best "
                "practices recommend always including a dispersion "
                "correction (e.g., D3BJ). See Bursch et al. "
                "Angew. Chem. Int. Ed. 2022, 61, e202205735."
            )

        return recs

    def _normalize_bond_type(self, bond_type):
        """Normalize a bond type string (e.g., 'O-H' stays 'O-H').

        Args:
            bond_type (str): Bond type string.

        Returns:
            str: Normalized bond type.
        """
        return bond_type.strip()

    def _reverse_bond_type(self, bond_type):
        """Reverse a bond or angle type string.

        For bonds (2 atoms): 'O-H' -> 'H-O'.
        For angles (3 atoms): 'F-C-H' -> 'H-C-F'
        (central atom stays in place).

        Args:
            bond_type (str): Bond or angle type string.

        Returns:
            str: Reversed type string.
        """
        parts = bond_type.split("-")
        if len(parts) == 2:
            return "%s-%s" % (parts[1], parts[0])
        if len(parts) == 3:
            return "%s-%s-%s" % (parts[2], parts[1], parts[0])
        return bond_type
