"""Tests for ko_aliases dash normalization."""
from __future__ import annotations

from qcviz_mcp.services.ko_aliases import _normalize_formula_text, translate


class TestDashNormalization:
    def test_en_dash_in_formula(self):
        result = _normalize_formula_text("1,3\u2013뷰타다이엔")
        assert "-" in result
        assert "\u2013" not in result

    def test_em_dash_in_formula(self):
        result = _normalize_formula_text("1,3\u2014뷰타다이엔")
        assert "-" in result

    def test_minus_sign_in_formula(self):
        result = _normalize_formula_text("CH₃\u2212CH₃")
        assert result == "CH3-CH3"

    def test_translate_with_en_dash(self):
        result = translate("1,3\u2013뷰타다이엔")
        assert result == "1,3-butadiene"

    def test_subscript_still_works(self):
        result = _normalize_formula_text("H₂O")
        assert result == "H2O"

    def test_trailing_slash_still_removed(self):
        result = _normalize_formula_text("benzene /")
        assert result == "benzene"
