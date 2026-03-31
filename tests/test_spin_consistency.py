from __future__ import annotations

import pytest

from qcviz_mcp.compute import pyscf_runner


@pytest.mark.contract
def test_coerce_multiplicity_promotes_closed_shell_default_for_odd_electrons():
    atom_spec = "N 0.0 0.0 0.0\nO 0.0 0.0 1.15"
    multiplicity, warning = pyscf_runner.coerce_multiplicity_for_structure(
        atom_spec=atom_spec,
        charge=0,
        multiplicity=1,
    )
    assert multiplicity == 2
    assert warning
    assert "auto-adjusted" in warning


@pytest.mark.contract
def test_coerce_multiplicity_keeps_valid_closed_shell_request():
    atom_spec = "O 0.0 0.0 0.0\nH 0.0 0.8 0.6\nH 0.0 -0.8 0.6"
    multiplicity, warning = pyscf_runner.coerce_multiplicity_for_structure(
        atom_spec=atom_spec,
        charge=0,
        multiplicity=1,
    )
    assert multiplicity == 1
    assert warning is None
