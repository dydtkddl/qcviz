"""
Tests for the Computation Preset Recommender (F1).

Tests cover: system classification, functional recommendation,
edge cases, error handling, PySCF settings, lanthanide detection,
and XYZ header parsing.
"""

import pytest

from qcviz_mcp.advisor.preset_recommender import (
    PresetRecommender,
    PresetRecommendation,
    VALID_PURPOSES,
)


@pytest.fixture
def recommender():
    """Create a PresetRecommender instance."""
    return PresetRecommender()


# --- Water molecule XYZ ---
WATER_XYZ = """\
O   0.0000000   0.0000000   0.1173000
H   0.0000000   0.7572000  -0.4692000
H   0.0000000  -0.7572000  -0.4692000
"""

# --- Water with XYZ header ---
WATER_XYZ_WITH_HEADER = """\
3
water molecule - test comment line
O   0.0000000   0.0000000   0.1173000
H   0.0000000   0.7572000  -0.4692000
H   0.0000000  -0.7572000  -0.4692000
"""

# --- Methane XYZ ---
METHANE_XYZ = """\
C   0.0000   0.0000   0.0000
H   0.6276   0.6276   0.6276
H  -0.6276  -0.6276   0.6276
H  -0.6276   0.6276  -0.6276
H   0.6276  -0.6276  -0.6276
"""

# --- Iron pentacarbonyl (3d TM) ---
FE_CO5_XYZ = """\
Fe  0.000  0.000  0.000
C   0.000  0.000  1.830
O   0.000  0.000  2.970
C   0.000  0.000 -1.830
O   0.000  0.000 -2.970
C   1.830  0.000  0.000
O   2.970  0.000  0.000
C  -1.830  0.000  0.000
O  -2.970  0.000  0.000
C   0.000  1.830  0.000
O   0.000  2.970  0.000
"""

# --- Methyl radical (open shell) ---
CH3_RADICAL_XYZ = """\
C   0.0000   0.0000   0.0000
H   1.0790   0.0000   0.0000
H  -0.5395   0.9343   0.0000
H  -0.5395  -0.9343   0.0000
"""

# --- Gadolinium complex (lanthanide) ---
GD_COMPLEX_XYZ = """\
Gd  0.000  0.000  0.000
O   2.300  0.000  0.000
O  -2.300  0.000  0.000
O   0.000  2.300  0.000
H   2.300  0.900  0.000
H  -2.300  0.900  0.000
H   0.000  2.300  0.900
"""

# --- Iridium complex (5d TM) ---
IR_COMPLEX_XYZ = """\
Ir  0.000  0.000  0.000
N   2.100  0.000  0.000
C   2.800  1.200  0.000
C   2.800 -1.200  0.000
H   3.800  1.200  0.000
H   3.800 -1.200  0.000
"""


class TestPresetRecommenderHappyPath:
    """Test normal operation with valid inputs."""

    def test_water_geometry_opt_recommends_b3lyp(self, recommender):
        """Water geometry optimization should recommend B3LYP-D3."""
        rec = recommender.recommend(WATER_XYZ, purpose="geometry_opt")
        assert isinstance(rec, PresetRecommendation)
        assert "B3LYP" in rec.functional or "b3lyp" in rec.functional.lower()
        assert "def2" in rec.basis.lower()
        assert rec.spin_treatment == "RKS"
        assert rec.confidence > 0.5
        assert len(rec.references) > 0

    def test_water_single_point_uses_tzvp(self, recommender):
        """Water single point should recommend larger basis."""
        rec = recommender.recommend(WATER_XYZ, purpose="single_point")
        assert "tzvp" in rec.basis.lower()

    def test_methane_bonding_analysis(self, recommender):
        """Methane bonding analysis should work."""
        rec = recommender.recommend(METHANE_XYZ, purpose="bonding_analysis")
        assert isinstance(rec, PresetRecommendation)
        assert rec.rationale != ""

    def test_iron_complex_detects_3d_tm(self, recommender):
        """Iron complex should be classified as 3d TM."""
        rec = recommender.recommend(FE_CO5_XYZ, purpose="geometry_opt")
        assert any("transition metal" in w.lower() or "3d" in w.lower()
                    for w in rec.warnings)

    def test_radical_detects_open_shell(self, recommender):
        """Methyl radical should trigger UKS and spin warning."""
        rec = recommender.recommend(
            CH3_RADICAL_XYZ, purpose="geometry_opt",
            spin=1,
        )
        assert rec.spin_treatment == "UKS"
        assert any("spin" in w.lower() for w in rec.warnings)

    def test_lanthanide_classification(self, recommender):
        """Gadolinium complex should be classified as lanthanide."""
        rec = recommender.recommend(
            GD_COMPLEX_XYZ, purpose="geometry_opt"
        )
        assert any(
            "lanthanide" in w.lower() or "4f" in w.lower()
            for w in rec.warnings
        )
        assert rec.relativistic is True

    def test_iridium_classified_as_heavy_tm(self, recommender):
        """Iridium complex should be classified as heavy TM."""
        rec = recommender.recommend(
            IR_COMPLEX_XYZ, purpose="geometry_opt"
        )
        assert any("heavy" in w.lower() or "relativistic" in w.lower()
                    for w in rec.warnings)
        assert rec.relativistic is True


class TestPresetRecommenderEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_atom_hydrogen(self, recommender):
        """Single hydrogen atom should work."""
        rec = recommender.recommend("H 0.0 0.0 0.0", purpose="single_point")
        assert isinstance(rec, PresetRecommendation)

    def test_large_organic_system_triggers_warning(self, recommender):
        """System with >100 atoms should trigger size warning."""
        lines = []
        for i in range(120):
            lines.append("C  %.1f  0.0  0.0" % (i * 1.5))
        atom_spec = "\n".join(lines)
        rec = recommender.recommend(atom_spec, purpose="geometry_opt")
        assert any("large" in w.lower() or "atom" in w.lower()
                    for w in rec.warnings)

    def test_charged_system_handled(self, recommender):
        """Charged system should be handled."""
        rec = recommender.recommend(
            WATER_XYZ, purpose="geometry_opt", charge=-1
        )
        assert isinstance(rec, PresetRecommendation)

    def test_xyz_with_header_parsed_correctly(self, recommender):
        """XYZ with 2-line header should be parsed correctly."""
        rec = recommender.recommend(
            WATER_XYZ_WITH_HEADER, purpose="geometry_opt"
        )
        assert isinstance(rec, PresetRecommendation)
        # Should detect 3 atoms (O, H, H), not crash on header
        assert rec.confidence > 0.5


class TestPresetRecommenderErrors:
    """Test error handling."""

    def test_invalid_purpose_raises_valueerror(self, recommender):
        """Invalid purpose should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid purpose"):
            recommender.recommend(WATER_XYZ, purpose="invalid_purpose")

    def test_empty_atom_spec_raises_valueerror(self, recommender):
        """Empty atom spec should raise ValueError."""
        with pytest.raises(ValueError, match="Could not parse"):
            recommender.recommend("", purpose="geometry_opt")

    def test_garbage_input_raises_valueerror(self, recommender):
        """Non-XYZ input should raise ValueError."""
        with pytest.raises(ValueError):
            recommender.recommend("this is not xyz", purpose="geometry_opt")


class TestPresetRecommenderPySCFSettings:
    """Test PySCF-specific settings generation."""

    def test_pyscf_settings_contains_xc(self, recommender):
        """PySCF settings should contain xc functional."""
        rec = recommender.recommend(WATER_XYZ, purpose="geometry_opt")
        assert "xc" in rec.pyscf_settings
        assert rec.pyscf_settings["xc"] != ""

    def test_pyscf_settings_contains_basis(self, recommender):
        """PySCF settings should contain basis set."""
        rec = recommender.recommend(WATER_XYZ, purpose="geometry_opt")
        assert "basis" in rec.pyscf_settings
        assert "def2" in rec.pyscf_settings["basis"]

    def test_pyscf_xc_does_not_contain_d3(self, recommender):
        """PySCF xc string must not contain -D3(BJ) suffix."""
        rec = recommender.recommend(WATER_XYZ, purpose="geometry_opt")
        xc = rec.pyscf_settings["xc"]
        assert "d3" not in xc.lower()
        assert "(bj)" not in xc.lower()
