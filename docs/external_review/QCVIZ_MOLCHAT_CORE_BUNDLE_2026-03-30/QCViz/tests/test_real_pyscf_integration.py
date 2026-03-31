from __future__ import annotations
import math
import os
import pytest
from qcviz_mcp.compute import pyscf_runner
pytestmark = [pytest.mark.real_pyscf, pytest.mark.slow]

def test_real_resolve_structure_water():
    result = pyscf_runner.run_resolve_structure(structure_query="water")
    assert result["success"] is True
    assert result["job_type"] == "resolve_structure"
    assert "O" in result["xyz"]
    assert result["geometry_summary"]["n_atoms"] == 3

def test_real_single_point_water_hf_sto3g():
    result = pyscf_runner.run_single_point(structure_query="water", method="HF", basis="STO-3G")
    assert result["success"] is True
    assert result["job_type"] == "single_point"
    assert isinstance(result["scf_converged"], bool)
    assert math.isfinite(float(result["total_energy_hartree"]))
    assert "visualization" in result
    assert "defaults" in result["visualization"]

def test_real_partial_charges_water():
    result = pyscf_runner.run_partial_charges(structure_query="water", method="HF", basis="STO-3G")
    assert result["success"] is True
    assert result["job_type"] == "partial_charges"
    assert len(result["partial_charges"]) == 3
    total_charge = sum(float(x["charge"]) for x in result["partial_charges"])
    assert total_charge == pytest.approx(0.0, abs=1.0e-4)

@pytest.mark.skipif(os.getenv("QCVIZ_RUN_REAL_ANALYZE", "0") != "1", reason="Set QCVIZ_RUN_REAL_ANALYZE=1 to enable the expensive full analyze integration test.")
def test_real_analyze_water_smoke():
    result = pyscf_runner.run_analyze(structure_query="water", method="HF", basis="STO-3G", orbital="HOMO", esp_preset="acs")
    assert result["success"] is True
    assert result["job_type"] == "analyze"
    assert math.isfinite(float(result["total_energy_hartree"]))
    assert result["visualization"]["available"]["orbital"] is True
    assert result["visualization"]["available"]["esp"] is True
