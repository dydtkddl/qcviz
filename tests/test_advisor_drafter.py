"""
Tests for the Computational Methods Section Drafter (F2).

Tests cover: text generation quality, citation handling,
edge cases, reviewer note generation, and citation key ordering.
"""

import pytest
from qcviz_mcp.advisor.methods_drafter import (
    MethodsSectionDrafter,
    MethodsDraft,
    CalculationRecord,
)


@pytest.fixture
def drafter():
    """Create a MethodsSectionDrafter instance."""
    return MethodsSectionDrafter()


@pytest.fixture
def water_record():
    """Create a sample CalculationRecord for water."""
    return CalculationRecord(
        system_name="water",
        atom_spec="O 0 0 0.117\nH 0 0.757 -0.469\nH 0 -0.757 -0.469",
        charge=0,
        spin=0,
        functional="B3LYP",
        basis="def2-SVP",
        dispersion="D3BJ",
        energy_hartree=-76.4200,
        converged=True,
        n_cycles=12,
        software="PySCF",
        software_version="2.5.0",
        optimizer="geomeTRIC",
        convergence_criteria={"energy": 1e-6, "gradient_rms": 3e-4},
        analysis_type="ibo",
    )


class TestMethodsDrafterHappyPath:
    """Test normal methods text generation."""

    def test_basic_draft_produces_text(self, drafter, water_record):
        """Drafting with a valid record should produce text."""
        result = drafter.draft([water_record])
        assert isinstance(result, MethodsDraft)
        assert len(result.methods_text) > 100
        assert "PySCF" in result.methods_text

    def test_functional_is_mentioned(self, drafter, water_record):
        """The functional name should appear in the text."""
        result = drafter.draft([water_record])
        assert "B3LYP" in result.methods_text

    def test_basis_set_is_mentioned(self, drafter, water_record):
        """The basis set should appear in the text."""
        result = drafter.draft([water_record])
        assert "def2-SVP" in result.methods_text

    def test_bibtex_entries_generated(self, drafter, water_record):
        """BibTeX entries should be generated."""
        result = drafter.draft([water_record], include_bibtex=True)
        assert len(result.bibtex_entries) > 0
        assert any("@article" in b for b in result.bibtex_entries)

    def test_disclaimer_present(self, drafter, water_record):
        """Disclaimer should always be present."""
        result = drafter.draft([water_record])
        assert "preliminary" in result.disclaimer.lower() or \
               "reviewed" in result.disclaimer.lower()

    def test_optimizer_mentioned_in_text(self, drafter, water_record):
        """geomeTRIC optimizer should be mentioned."""
        result = drafter.draft([water_record])
        assert "geomeTRIC" in result.methods_text or \
               "optimization" in result.methods_text.lower()

    def test_ibo_analysis_mentioned_in_text(self, drafter, water_record):
        """IBO analysis should be mentioned."""
        result = drafter.draft([water_record])
        assert "IBO" in result.methods_text or \
               "intrinsic bond orbital" in result.methods_text.lower()

    def test_pbe0_citation_matches_pbe0_not_pbe(self, drafter):
        """PBE0 functional should cite Adamo1999, not PBE."""
        rec = CalculationRecord(
            system_name="test",
            atom_spec="O 0 0 0\nH 0 0.75 -0.47\nH 0 -0.75 -0.47",
            charge=0, spin=0,
            functional="PBE0",
            basis="def2-SVP",
            dispersion="D3BJ",
            software="PySCF",
            software_version="2.5.0",
        )
        result = drafter.draft([rec])
        assert "Adamo" in result.methods_text  # FIXED #24: exact match only


class TestMethodsDrafterEdgeCases:
    """Test edge cases."""

    def test_no_dispersion_still_works(self, drafter):
        """Record without dispersion should still work."""
        rec = CalculationRecord(
            system_name="H2",
            atom_spec="H 0 0 0\nH 0 0 0.74",
            charge=0, spin=0,
            functional="HF",
            basis="STO-3G",
        )
        result = drafter.draft([rec])
        assert isinstance(result, MethodsDraft)

    def test_no_bibtex_output(self, drafter, water_record):
        """Should work without bibtex generation."""
        result = drafter.draft([water_record], include_bibtex=False)
        assert isinstance(result, MethodsDraft)

    def test_multiple_records_different_methods(self, drafter, water_record):
        """Multiple records should produce multi-method description."""
        rec2 = CalculationRecord(
            system_name="water",
            atom_spec=water_record.atom_spec,
            charge=0, spin=0,
            functional="B3LYP",
            basis="def2-TZVP",
            energy_hartree=-76.4500,
        )
        result = drafter.draft([water_record, rec2])
        assert "def2-TZVP" in result.methods_text

    def test_unrestricted_functional_still_gets_citation(self, drafter):
        """Leading U should not prevent functional citation lookup."""
        rec = CalculationRecord(
            system_name="methyl radical",
            atom_spec="C 0 0 0\nH 1 0 0\nH -0.5 0.9 0\nH -0.5 -0.9 0",
            charge=0,
            spin=1,
            functional="UB3LYP-D3(BJ)",
            basis="def2-SVP",
            dispersion="D3BJ",
            software="PySCF",
            software_version="2.5.0",
        )
        result = drafter.draft([rec])
        assert "Becke" in result.methods_text

    def test_wb97xd_gets_specific_citation(self, drafter):
        """wB97X-D should cite the Chai-Head-Gordon paper."""
        rec = CalculationRecord(
            system_name="ion pair",
            atom_spec="Na 0 0 0\nCl 0 0 2.3",
            charge=0,
            spin=0,
            functional="wB97X-D",
            basis="def2-TZVP",
            software="PySCF",
            software_version="2.5.0",
        )
        result = drafter.draft([rec])
        assert "Chai" in result.methods_text or "Head-Gordon" in result.methods_text


class TestMethodsDrafterErrors:
    """Test error handling."""

    def test_empty_records_raises_valueerror(self, drafter):
        """Empty record list should raise ValueError."""
        with pytest.raises(ValueError, match="at least one"):
            drafter.draft([])


class TestMethodsDrafterReviewerNotes:
    """Test reviewer note generation."""

    def test_missing_dispersion_triggers_note(self, drafter):
        """Missing dispersion should trigger reviewer note."""
        rec = CalculationRecord(
            system_name="test",
            atom_spec="C 0 0 0\nH 1 0 0\nH 0 1 0\nH 0 0 1\nH -1 0 0",
            charge=0, spin=0,
            functional="B3LYP",
            basis="def2-SVP",
            dispersion="",
        )
        result = drafter.draft([rec])
        assert any("dispersion" in n.lower() for n in result.reviewer_notes)

    def test_small_basis_triggers_note(self, drafter):
        """Small basis should trigger reviewer note."""
        rec = CalculationRecord(
            system_name="test",
            atom_spec="O 0 0 0\nH 0 0.75 -0.47\nH 0 -0.75 -0.47",
            charge=0, spin=0,
            functional="B3LYP",
            basis="def2-SVP",
            dispersion="D3BJ",
        )
        result = drafter.draft([rec])
        assert any("double-zeta" in n.lower() or "svp" in n.lower()
                    for n in result.reviewer_notes)
