"""
Tests for the Calculation Confidence Scorer (F7).

Tests cover: score computation, sub-score components,
weight sums, exact-match bonus, edge cases, and recommendations.
"""

import pytest
from qcviz_mcp.advisor.confidence_scorer import (
    ConfidenceScorer,
    ConfidenceReport,
)


@pytest.fixture
def scorer():
    """Create a ConfidenceScorer instance."""
    return ConfidenceScorer()


class TestConfidenceScorerHappyPath:
    """Test normal scoring workflow."""

    def test_good_calculation_scores_high(self, scorer):
        """Well-converged B3LYP/TZVP with PASS should score high."""
        report = scorer.score(
            converged=True,
            n_scf_cycles=15,
            max_cycles=200,
            functional="B3LYP",
            basis="def2-TZVP",
            system_type="organic_small",
            validation_status="PASS",
        )
        assert isinstance(report, ConfidenceReport)
        assert report.overall_score >= 0.7

    def test_unconverged_calculation_scores_low(self, scorer):
        """Unconverged calculation should score low."""
        report = scorer.score(
            converged=False,
            n_scf_cycles=200,
            max_cycles=200,
            functional="B3LYP",
            basis="def2-SVP",
        )
        assert report.overall_score < 0.5
        assert report.convergence_score < 0.3

    def test_breakdown_text_contains_all_components(self, scorer):
        """Breakdown text should contain all score components."""
        report = scorer.score(
            converged=True,
            n_scf_cycles=10,
            functional="B3LYP",
            basis="def2-SVP",
        )
        assert "Convergence" in report.breakdown_text
        assert "Basis Set" in report.breakdown_text
        assert "Method" in report.breakdown_text
        assert "Spin" in report.breakdown_text
        assert "Reference" in report.breakdown_text

    def test_disclaimer_always_present(self, scorer):
        """Disclaimer should always be present."""
        report = scorer.score()
        assert "heuristic" in report.disclaimer.lower() or \
               "confidence" in report.disclaimer.lower()


class TestConfidenceScorerSubScores:
    """Test individual sub-score components."""

    def test_fast_convergence_scores_high(self, scorer):
        """Fast convergence should score high."""
        report = scorer.score(
            converged=True,
            n_scf_cycles=8,
            max_cycles=200,
        )
        assert report.convergence_score >= 0.9

    def test_slow_convergence_scores_lower(self, scorer):
        """Slow convergence should score lower."""
        report = scorer.score(
            converged=True,
            n_scf_cycles=150,
            max_cycles=200,
        )
        assert report.convergence_score < 0.7

    def test_tzvp_basis_scores_high(self, scorer):
        """Triple-zeta basis should score high."""
        report = scorer.score(basis="def2-TZVP")
        assert report.basis_score >= 0.8

    def test_svp_basis_scores_moderate(self, scorer):
        """Double-zeta basis should score moderately."""
        report = scorer.score(basis="def2-SVP")
        assert 0.4 <= report.basis_score <= 0.8

    def test_closed_shell_spin_score_perfect(self, scorer):
        """Closed-shell should have perfect spin score."""
        report = scorer.score(spin=0)
        assert report.spin_score == 1.0

    def test_heavily_contaminated_spin_scores_low(self, scorer):
        """Heavily contaminated spin should score low."""
        report = scorer.score(
            spin=1,
            s2_expected=0.75,
            s2_actual=1.5,
        )
        assert report.spin_score < 0.5


class TestConfidenceScorerEdgeCases:
    """Test edge cases."""

    def test_no_validation_data_gives_neutral_reference(self, scorer):
        """No validation data should give neutral reference score."""
        report = scorer.score(validation_status=None)
        assert report.reference_score == 0.5

    def test_unknown_functional_gives_moderate_method_score(self, scorer):
        """Unknown functional should give moderate method score."""
        report = scorer.score(functional="EXOTIC_42")
        assert report.method_score == 0.5

    def test_all_defaults_does_not_crash(self, scorer):
        """Calling with all defaults should not crash."""
        report = scorer.score()
        assert 0.0 <= report.overall_score <= 1.0

    def test_closed_shell_weights_sum_to_one(self, scorer):
        """Closed-shell weights must sum to 1.0."""
        # We test indirectly: a perfect score should be 1.0
        report = scorer.score(
            converged=True,
            n_scf_cycles=5,
            max_cycles=200,
            functional="B3LYP",
            basis="def2-QZVP",
            system_type="organic_small",
            spin=0,
            validation_status="PASS",
        )
        # If weights sum to 1.0 and all sub-scores are ~1.0,
        # overall should be close to 1.0
        assert report.overall_score >= 0.90

    def test_method_bonus_exact_match_only(self, scorer):
        """Method bonus should apply only for exact functional match."""
        # PBE should NOT get bonus when default is B3LYP
        report_pbe = scorer.score(
            functional="PBE",
            system_type="organic_small",
        )
        report_b3lyp = scorer.score(
            functional="B3LYP",
            system_type="organic_small",
        )
        # B3LYP is the default for organic_small, should score
        # at least as high as PBE
        assert report_b3lyp.method_score >= report_pbe.method_score


class TestConfidenceScorerRecommendations:
    """Test recommendation generation."""

    def test_poor_convergence_triggers_recommendation(self, scorer):
        """Poor convergence should trigger recommendation."""
        report = scorer.score(converged=False, n_scf_cycles=200)
        assert any("convergence" in r.lower() for r in report.recommendations)

    def test_small_basis_for_tm_triggers_recommendation(self, scorer):
        """Small basis for TM should trigger recommendation."""
        report = scorer.score(basis="def2-SVP", system_type="3d_tm")
        assert any("basis" in r.lower() for r in report.recommendations)

    def test_good_calculation_has_few_recommendations(self, scorer):
        """Good calculation should have few/no recommendations."""
        report = scorer.score(
            converged=True,
            n_scf_cycles=10,
            max_cycles=200,
            functional="B3LYP",
            basis="def2-TZVP",
            validation_status="PASS",
        )
        assert len(report.recommendations) <= 1


class TestConfidenceScorerThresholdAlignment:
    """Test WTMAD-2 threshold alignment (Issue #18)."""

    def test_b3lyp_scores_good_not_adequate(self, scorer):
        """B3LYP (WTMAD-2=6.42) should score in the 'good' range."""
        report = scorer.score(
            functional="B3LYP",
            system_type="organic_small",
            converged=True,
            n_scf_cycles=10,
            max_cycles=200,
            basis="def2-TZVP",
            validation_status="PASS",
        )
        # B3LYP is default for organic_small -> gets bonus
        # method_score should be >= 0.80
        assert report.method_score >= 0.80

    def test_pbe_scores_poor(self, scorer):
        """PBE (WTMAD-2=10.32) should score in the 'poor' range."""
        report = scorer.score(
            functional="PBE",
            system_type="organic_small",
        )
        assert report.method_score <= 0.50
