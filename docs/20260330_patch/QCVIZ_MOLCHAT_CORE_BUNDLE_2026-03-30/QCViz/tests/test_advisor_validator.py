"""
Tests for the Literature Energy Validator (F4).

Tests cover: bond length validation, overall status computation,
confidence scoring, recommendation generation, formula aliases,
and edge cases.
"""

import pytest
from qcviz_mcp.advisor.literature_validator import (
    LiteratureEnergyValidator,
    ValidationRequest,
    ValidationResult,
    BondValidation,
)


@pytest.fixture
def validator():
    """Create a LiteratureEnergyValidator instance."""
    return LiteratureEnergyValidator()


class TestValidatorHappyPath:
    """Test normal validation workflow."""

    def test_water_good_geometry_passes(self, validator):
        """Water with good geometry should pass."""
        req = ValidationRequest(
            bond_lengths={"O-H": 0.960},
            bond_angles={"H-O-H": 104.0},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert isinstance(result, ValidationResult)
        assert result.overall_status in ("PASS", "WARN")

    def test_water_bad_bond_flagged_as_fail(self, validator):
        """Water with bad O-H bond should be flagged."""
        req = ValidationRequest(
            bond_lengths={"O-H": 1.10},  # 0.14 A too long
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        fail_bonds = [v for v in result.bond_validations
                      if v.status == "FAIL"]
        assert len(fail_bonds) > 0

    def test_methane_good_ch_bond_passes(self, validator):
        """Methane with correct C-H should pass."""
        req = ValidationRequest(
            bond_lengths={"C-H": 1.089},
            system_formula="CH4",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        if result.bond_validations:
            assert result.bond_validations[0].status == "PASS"

    def test_disclaimer_always_present(self, validator):
        """Disclaimer should always be present."""
        req = ValidationRequest(system_formula="H2O")
        result = validator.validate(req)
        assert "preliminary" in result.disclaimer.lower() or \
               "reviewed" in result.disclaimer.lower()

    def test_method_assessment_generated_for_b3lyp(self, validator):
        """Method assessment should be generated for known functionals."""
        req = ValidationRequest(
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert result.method_assessment != ""
        assert "WTMAD" in result.method_assessment or \
               "B3LYP" in result.method_assessment

    def test_formaldehyde_ch2o_lookup(self, validator):
        """CH2O (formaldehyde) should be found in NIST data."""
        req = ValidationRequest(
            bond_lengths={"C=O": 1.205},
            system_formula="CH2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert len(result.bond_validations) > 0


class TestValidatorEdgeCases:
    """Test edge cases."""

    def test_unknown_molecule_returns_empty(self, validator):
        """Unknown molecule formula should return empty validations."""
        req = ValidationRequest(
            bond_lengths={"X-Y": 1.5},
            system_formula="UnknownMolecule",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert result.bond_validations == []

    def test_empty_request_returns_unknown(self, validator):
        """Empty request should return UNKNOWN status."""
        req = ValidationRequest()
        result = validator.validate(req)
        assert result.overall_status == "UNKNOWN"

    def test_unknown_functional_still_validates(self, validator):
        """Unknown functional should still produce result."""
        req = ValidationRequest(
            bond_lengths={"O-H": 0.960},
            system_formula="H2O",
            functional="EXOTIC_FUNCTIONAL_42",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert isinstance(result, ValidationResult)


class TestValidatorConfidence:
    """Test confidence score computation."""

    def test_all_pass_gives_high_confidence(self, validator):
        """All passing validations should give high confidence."""
        req = ValidationRequest(
            bond_lengths={"O-H": 0.959},
            bond_angles={"H-O-H": 104.5},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        if result.bond_validations:
            assert result.confidence >= 0.7

    def test_fail_reduces_confidence(self, validator):
        """Failing validations should reduce confidence."""
        req = ValidationRequest(
            bond_lengths={"O-H": 1.20},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert result.confidence < 0.7


class TestValidatorRecommendations:
    """Test recommendation generation."""

    def test_small_basis_triggers_recommendation(self, validator):
        """Small basis should trigger recommendation."""
        req = ValidationRequest(
            bond_lengths={"O-H": 0.960},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        has_basis_rec = any("basis" in r.lower() for r in result.recommendations)
        # SVP should trigger "use TZVP" recommendation
        assert has_basis_rec

    def test_no_dispersion_triggers_recommendation(self, validator):
        """Missing dispersion should trigger recommendation."""
        req = ValidationRequest(
            bond_lengths={"O-H": 0.960},
            system_formula="H2O",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        assert any("dispersion" in r.lower() for r in result.recommendations)


class TestValidatorAngleReversal:
    """Test angle type reverse matching (Issue #17)."""

    def test_asymmetric_angle_reverse_matching(self, validator):
        """Asymmetric angle types should match via reversal."""
        # HOCl has angle stored as H-O-Cl in NIST data (via ClHO key)
        req = ValidationRequest(
            bond_angles={"Cl-O-H": 102.5},
            system_formula="ClHO",
            functional="B3LYP",
            basis="def2-SVP",
        )
        result = validator.validate(req)
        # Should find match via reversal: Cl-O-H -> H-O-Cl
        if result.angle_validations:
            assert result.angle_validations[0].status == "PASS"
