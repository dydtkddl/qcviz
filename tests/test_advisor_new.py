"""
Additional tests for QCViz-MCP v5.0 Advisor Module.

Added during the 2026-03-08 audit to close coverage gaps.
15 new tests bringing total from 78 to 93.
"""

import json
import pytest

from qcviz_mcp.advisor import (
    PresetRecommender,
    PresetRecommendation,
    MethodsSectionDrafter,
    MethodsDraft,
    CalculationRecord,
    ReproducibilityScriptGenerator,
    LiteratureEnergyValidator,
    ValidationRequest,
    ValidationResult,
    BondValidation,
    ConfidenceScorer,
    ConfidenceReport,
)
from qcviz_mcp.advisor.reference_data import normalize_func_key


# ────────────────────────────────────────────
# N3: normalize_func_key tests
# ────────────────────────────────────────────

class TestNormalizeFuncKey:
    """Test the normalize_func_key helper."""

    def test_b3lyp_d3bj(self):
        assert normalize_func_key("B3LYP-D3(BJ)") == "B3LYP"

    def test_m062x_d30(self):
        assert normalize_func_key("M06-2X-D3(0)") == "M062X"

    def test_wb97x_v(self):
        assert normalize_func_key("wB97X-V") == "WB97X"

    def test_pbe0_d3bj(self):
        assert normalize_func_key("PBE0-D3(BJ)") == "PBE0"

    def test_tpssh_d3bj(self):
        assert normalize_func_key("TPSSh-D3(BJ)") == "TPSSH"

    def test_r2scan_plain(self):
        assert normalize_func_key("r2SCAN") == "R2SCAN"

    def test_pw6b95_d3bj(self):
        assert normalize_func_key("PW6B95-D3(BJ)") == "PW6B95"

    def test_pbe_d3bj(self):
        assert normalize_func_key("PBE-D3(BJ)") == "PBE"

    def test_unrestricted_b3lyp_d3bj(self):
        assert normalize_func_key("UB3LYP-D3(BJ)") == "B3LYP"

    def test_unrestricted_m062x_d30(self):
        assert normalize_func_key("UM06-2X-D3(0)") == "M062X"


# ────────────────────────────────────────────
# N4: Noble gas parsing
# ────────────────────────────────────────────

class TestNobleGasParsing:
    """Test that noble gas atoms are recognized."""

    def test_argon_atom_parsed(self):
        rec = PresetRecommender()
        result = rec.recommend(
            "Ar  0.0  0.0  0.0",
            purpose="single_point",
        )
        assert isinstance(result, PresetRecommendation)


# ────────────────────────────────────────────
# N11: __version__ existence
# ────────────────────────────────────────────

class TestVersionAttribute:
    """Test that __version__ is defined."""

    def test_version_string(self):
        import qcviz_mcp.advisor as advisor
        assert hasattr(advisor, "__version__")
        assert advisor.__version__ == "1.1.0"


# ────────────────────────────────────────────
# Coverage gap: single atom
# ────────────────────────────────────────────

class TestSingleAtomMolecule:
    """Test single-atom input."""

    def test_single_oxygen_atom(self):
        rec = PresetRecommender()
        result = rec.recommend(
            "O  0.0  0.0  0.0",
            purpose="single_point",
        )
        assert isinstance(result, PresetRecommendation)
        assert result.confidence > 0.0


# ────────────────────────────────────────────
# Coverage gap: lanthanide + radical
# ────────────────────────────────────────────

class TestLanthanideRadical:
    """Test lanthanide system with non-zero spin."""

    def test_gd_radical_classified_as_lanthanide(self):
        """Gd complex with spin=7 should still be lanthanide."""
        rec = PresetRecommender()
        result = rec.recommend(
            "Gd 0.0 0.0 0.0\nO 2.3 0.0 0.0\nH 2.3 0.9 0.0",
            purpose="geometry_opt",
            spin=7,
        )
        assert result.spin_treatment == "UKS"
        # Should have BOTH lanthanide warning AND spin warning
        assert any("lanthanide" in w.lower() or "4f" in w.lower()
                    for w in result.warnings)
        assert any("spin" in w.lower() for w in result.warnings)


# ────────────────────────────────────────────
# Coverage gap: angle-only validation
# ────────────────────────────────────────────

class TestAngleOnlyValidation:
    """Test validation with only angles, no bonds."""

    def test_water_angle_only(self):
        val = LiteratureEnergyValidator()
        req = ValidationRequest(
            bond_angles={"H-O-H": 104.5},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = val.validate(req)
        assert result.overall_status in ("PASS", "WARN", "UNKNOWN")
        assert len(result.angle_validations) > 0
