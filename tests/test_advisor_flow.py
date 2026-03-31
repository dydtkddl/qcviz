"""Tests for advisor-to-runner preset application."""

from qcviz_mcp.web.advisor_flow import apply_preset_to_runner_kwargs


def test_apply_preset_uses_clean_runner_method():
    prepared = {"_method_user_supplied": False, "_basis_user_supplied": False}
    advisor_plan = {
        "applied_functional": "UM06-2X-D3(0)",
        "applied_basis": "def2-TZVP",
        "preset": {
            "status": "success",
            "data": {
                "pyscf_settings": {"xc": "m062x"},
            },
        },
    }
    merged = apply_preset_to_runner_kwargs(prepared, advisor_plan)
    assert merged["method"] == "M06-2X"
    assert merged["basis"] == "def2-TZVP"


def test_apply_preset_does_not_override_user_method():
    prepared = {
        "method": "PBE0",
        "_method_user_supplied": True,
        "_basis_user_supplied": False,
    }
    advisor_plan = {
        "applied_functional": "B3LYP-D3(BJ)",
        "applied_basis": "def2-SVP",
        "preset": {
            "status": "success",
            "data": {
                "pyscf_settings": {"xc": "b3lyp"},
            },
        },
    }
    merged = apply_preset_to_runner_kwargs(prepared, advisor_plan)
    assert merged["method"] == "PBE0"
    assert merged["basis"] == "def2-SVP"
