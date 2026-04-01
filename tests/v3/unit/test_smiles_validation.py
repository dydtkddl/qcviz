"""Tests for LLM SMILES sanity checks."""
from __future__ import annotations

import pytest

from qcviz_mcp.services.structure_resolver import _validate_llm_smiles

pytest.importorskip("rdkit")


class TestValidateLlmSmiles:
    def test_valid_ethanol(self):
        result = _validate_llm_smiles("CCO", "CH3CH2OH")
        assert result is not None
        assert "C" in result
        assert "O" in result

    def test_valid_chloroethane(self):
        result = _validate_llm_smiles("CCCl", "CH3-CH2Cl")
        assert result is not None

    def test_reject_parse_failure(self):
        assert _validate_llm_smiles("C(C(C", "CH3CH3") is None

    def test_reject_element_mismatch_hallucination(self):
        assert _validate_llm_smiles("CCCC", "CH3-C(CH3)(Cl)-CH2CH3") is None

    def test_reject_single_heavy_atom(self):
        assert _validate_llm_smiles("[Na]", "CH3CH2OH") is None

    def test_accept_expected_element_overlap(self):
        result = _validate_llm_smiles("CCN", "CH3CH2NH2")
        assert result is not None

    def test_reject_low_overlap(self):
        assert _validate_llm_smiles("CCCC", "CH3CONHSCH3") is None

    def test_canonical_output(self):
        result = _validate_llm_smiles("COC", "CH3OCH3")
        assert result == "COC"
