from __future__ import annotations
import base64
import pytest
from qcviz_mcp.web.routes import compute as compute_route
pytestmark = [pytest.mark.contract]

def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

def test_normalize_result_contract_adds_defaults_and_available_flags():
    result = {
        "success": True, "job_type": "esp_map", "structure_name": "acetone",
        "xyz": "3\nx\nO 0 0 0\nH 0 0 1\nH 0 1 0\n",
        "mulliken_charges": [{"atom_index": 0, "symbol": "O", "charge": -0.5}],
        "visualization": {"esp_cube_b64": _b64("ESP"), "density_cube_b64": _b64("DENS")},
    }
    normalized = compute_route._normalize_result_contract(result, {"job_type": "esp_map", "esp_preset": "acs"})
    assert normalized["partial_charges"] == normalized["mulliken_charges"]
    assert normalized["visualization"]["available"]["density"] is True
    assert normalized["visualization"]["available"]["esp"] is True
    assert normalized["visualization"]["defaults"]["esp_preset"] == "acs"
    assert normalized["advisor_focus_tab"] == "esp"

def test_normalize_result_contract_backfills_gap_units():
    result = {"success": True, "job_type": "single_point", "structure_name": "water", "orbital_gap_ev": 6.802845}
    normalized = compute_route._normalize_result_contract(result, {"job_type": "single_point"})
    assert normalized["orbital_gap_ev"] == pytest.approx(6.802845)
    assert normalized["orbital_gap_hartree"] == pytest.approx(6.802845 / 27.211386245988, rel=1e-6)

def test_normalize_result_contract_preserves_scf_history_payload():
    result = {
        "success": True,
        "job_type": "single_point",
        "structure_name": "water",
        "total_energy_hartree": -76.0,
        "scf_history": [
            {"cycle": 1, "energy": -75.5},
            {"cycle": 2, "energy": -76.0, "dE": -0.5},
        ],
        "n_scf_cycles": 2,
    }
    normalized = compute_route._normalize_result_contract(result, {"job_type": "single_point"})
    assert normalized["scf_history"][-1]["dE"] == pytest.approx(-0.5)
    assert normalized["n_scf_cycles"] == 2

def test_normalize_result_contract_prefers_orbital_focus_when_orbital_cube_present():
    result = {"success": True, "job_type": "orbital_preview", "structure_name": "benzene", "visualization": {"orbital_cube_b64": _b64("ORB")}}
    normalized = compute_route._normalize_result_contract(result, {"job_type": "orbital_preview"})
    assert normalized["visualization"]["available"]["orbital"] is True
    assert normalized["advisor_focus_tab"] == "orbital"

def test_normalize_result_contract_sets_method_basis_charge_defaults():
    result = {"success": True, "job_type": "analyze"}
    normalized = compute_route._normalize_result_contract(result, {})
    assert normalized["method"]
    assert normalized["basis"]
    assert normalized["charge"] == 0
    assert normalized["multiplicity"] == 1
    assert "defaults" in normalized["visualization"]
