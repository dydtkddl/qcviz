"""
Tests for the Reproducibility Script Generator (F3).

Tests cover: script generation, content validation,
analysis inclusion, D3 stripping, and edge cases.
"""

import pytest
from qcviz_mcp.advisor.script_generator import (
    ReproducibilityScriptGenerator,
)
from qcviz_mcp.advisor.methods_drafter import CalculationRecord


@pytest.fixture
def generator():
    """Create a ReproducibilityScriptGenerator instance."""
    return ReproducibilityScriptGenerator()


@pytest.fixture
def water_record():
    """Create a sample CalculationRecord for water."""
    return CalculationRecord(
        system_name="water",
        atom_spec="O 0.0 0.0 0.117\nH 0.0 0.757 -0.469\nH 0.0 -0.757 -0.469",
        charge=0,
        spin=0,
        functional="B3LYP-D3(BJ)",
        basis="def2-SVP",
        dispersion="D3BJ",
        energy_hartree=-76.42,
        converged=True,
        n_cycles=12,
        software="PySCF",
        software_version="2.5.0",
        analysis_type="ibo",
    )


class TestScriptGeneratorHappyPath:
    """Test normal script generation."""

    def test_generates_nonempty_string(self, generator, water_record):
        """Should return a non-empty string."""
        script = generator.generate(water_record)
        assert isinstance(script, str)
        assert len(script) > 200

    def test_contains_pyscf_imports(self, generator, water_record):
        """Script should contain PySCF imports."""
        script = generator.generate(water_record)
        assert "from pyscf import" in script

    def test_contains_mol_definition(self, generator, water_record):
        """Script should define the molecule."""
        script = generator.generate(water_record)
        assert "gto.M(" in script

    def test_contains_scf_kernel_call(self, generator, water_record):
        """Script should call SCF kernel."""
        script = generator.generate(water_record)
        assert "kernel()" in script

    def test_contains_ibo_analysis_code(self, generator, water_record):
        """Script should include IBO analysis code."""
        script = generator.generate(water_record)
        assert "ibo" in script.lower() or "lo.ibo" in script

    def test_contains_disclaimer_warning(self, generator, water_record):
        """Script should contain warning disclaimer."""
        script = generator.generate(water_record)
        assert "WARNING" in script or "preliminary" in script.lower()

    def test_d3_stripped_from_xc_in_scf_block(self, generator, water_record):
        """D3(BJ) must NOT appear in mf.xc assignment."""
        script = generator.generate(water_record)
        # Find lines like mf.xc = '...'
        for line in script.split("\n"):
            if "mf.xc" in line and "=" in line:
                assert "d3" not in line.lower()
                assert "(bj)" not in line.lower()


class TestScriptGeneratorEdgeCases:
    """Test edge cases."""

    def test_no_analysis_excludes_ibo(self, generator):
        """Script without analysis should still work."""
        rec = CalculationRecord(
            system_name="H2",
            atom_spec="H 0 0 0\nH 0 0 0.74",
            charge=0, spin=0,
            functional="HF",
            basis="STO-3G",
        )
        script = generator.generate(rec, include_analysis=False)
        assert "gto.M(" in script
        assert "ibo" not in script.lower()

    def test_open_shell_uses_uks(self, generator):
        """Open-shell system should use UKS."""
        rec = CalculationRecord(
            system_name="CH3",
            atom_spec="C 0 0 0\nH 1.079 0 0\nH -0.540 0.934 0\nH -0.540 -0.934 0",
            charge=0, spin=1,
            functional="B3LYP",
            basis="def2-SVP",
        )
        script = generator.generate(rec)
        assert "UKS" in script

    def test_esp_analysis_includes_cubegen(self, generator):
        """ESP analysis should include cubegen."""
        rec = CalculationRecord(
            system_name="water",
            atom_spec="O 0 0 0.117\nH 0 0.757 -0.469\nH 0 -0.757 -0.469",
            charge=0, spin=0,
            functional="B3LYP",
            basis="def2-SVP",
            analysis_type="esp",
        )
        script = generator.generate(rec)
        assert "cubegen" in script

    def test_geomopt_block_strips_d3_from_xc(self, generator):
        """Geometry optimization re-run should strip D3 from xc."""
        rec = CalculationRecord(
            system_name="water",
            atom_spec="O 0 0 0.117\nH 0 0.757 -0.469\nH 0 -0.757 -0.469",
            charge=0, spin=0,
            functional="B3LYP-D3(BJ)",
            basis="def2-SVP",
            optimizer="geomeTRIC",
        )
        script = generator.generate(rec)
        assert "optimize" in script.lower()
        # Count mf.xc lines — all should be clean
        for line in script.split("\n"):
            if "mf.xc" in line and "=" in line:
                assert "d3" not in line.lower()


class TestScriptGeneratorContent:
    """Test script content quality."""

    def test_basis_matches_record(self, generator, water_record):
        """Basis set in script should match record."""
        script = generator.generate(water_record)
        assert "def2-svp" in script.lower()

    def test_functional_in_script(self, generator, water_record):
        """Functional in script should be present (cleaned)."""
        script = generator.generate(water_record)
        assert "b3lyp" in script.lower()
