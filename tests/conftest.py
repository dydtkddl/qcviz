from __future__ import annotations

import base64
import importlib.util
import logging
import sys
import time
import types
from typing import Any, Callable, Dict, Optional

import pytest
from fastapi.testclient import TestClient

_HAS_REAL_PYSCF = importlib.util.find_spec("pyscf") is not None
_HAS_WSPROTO = importlib.util.find_spec("wsproto") is not None


def _install_pyscf_stub() -> None:
    if "pyscf" in sys.modules:
        return

    pyscf_module = types.ModuleType("pyscf")
    pyscf_module.dft = types.ModuleType("pyscf.dft")
    pyscf_module.gto = types.ModuleType("pyscf.gto")
    pyscf_module.scf = types.ModuleType("pyscf.scf")
    pyscf_module.data = types.ModuleType("pyscf.data")
    element_symbols = [
        "",
        "H",
        "He",
        "Li",
        "Be",
        "B",
        "C",
        "N",
        "O",
        "F",
        "Ne",
        "Na",
        "Mg",
        "Al",
        "Si",
        "P",
        "S",
        "Cl",
    ]
    element_charges = {symbol: index for index, symbol in enumerate(element_symbols) if symbol}
    pyscf_module.data.elements = types.SimpleNamespace(
        ELEMENTS=element_symbols,
        charge=lambda symbol: element_charges[str(symbol).strip().capitalize()],
    )
    pyscf_module.tools = types.ModuleType("pyscf.tools")
    pyscf_module.tools.cubegen = types.SimpleNamespace()
    pyscf_module.geomopt = types.ModuleType("pyscf.geomopt")
    pyscf_module.geomopt.geometric_solver = types.ModuleType("pyscf.geomopt.geometric_solver")
    pyscf_module.geomopt.geometric_solver.optimize = None
    pyscf_module.geomopt.berny_solver = types.ModuleType("pyscf.geomopt.berny_solver")
    pyscf_module.geomopt.berny_solver.optimize = None

    sys.modules["pyscf"] = pyscf_module
    sys.modules["pyscf.dft"] = pyscf_module.dft
    sys.modules["pyscf.gto"] = pyscf_module.gto
    sys.modules["pyscf.scf"] = pyscf_module.scf
    sys.modules["pyscf.data"] = pyscf_module.data
    sys.modules["pyscf.data.elements"] = pyscf_module.data.elements
    sys.modules["pyscf.tools"] = pyscf_module.tools
    sys.modules["pyscf.tools.cubegen"] = pyscf_module.tools.cubegen
    sys.modules["pyscf.geomopt"] = pyscf_module.geomopt
    sys.modules["pyscf.geomopt.geometric_solver"] = pyscf_module.geomopt.geometric_solver
    sys.modules["pyscf.geomopt.berny_solver"] = pyscf_module.geomopt.berny_solver


def _install_arq_stub() -> None:
    if "arq" in sys.modules:
        return

    arq_module = types.ModuleType("arq")
    connections_module = types.ModuleType("arq.connections")

    class _RedisSettings:
        def __init__(self, dsn: str = "") -> None:
            self.dsn = dsn

        @classmethod
        def from_dsn(cls, dsn: str):
            return cls(dsn)

    connections_module.RedisSettings = _RedisSettings
    arq_module.connections = connections_module

    sys.modules["arq"] = arq_module
    sys.modules["arq.connections"] = connections_module


_install_pyscf_stub()
_install_arq_stub()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def pytest_collection_modifyitems(config, items):
    if not _HAS_REAL_PYSCF:
        skip_real_pyscf = pytest.mark.skip(reason="Real PySCF is not installed in this environment.")
        for item in items:
            if item.get_closest_marker("real_pyscf") or "tests/test_run_geometry_optimization.py" in item.nodeid:
                item.add_marker(skip_real_pyscf)
    if not _HAS_WSPROTO:
        skip_wsproto = pytest.mark.skip(reason="wsproto is not installed in this environment.")
        for item in items:
            if "tests/test_web_server_smoke.py" in item.nodeid:
                item.add_marker(skip_wsproto)

from qcviz_mcp.app import create_app
from qcviz_mcp.compute import pyscf_runner
from qcviz_mcp.web import auth_store
from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route

WATER_XYZ = """3
water
O  0.000000  0.000000  0.000000
H  0.000000  0.757160  0.586260
H  0.000000 -0.757160  0.586260
"""

DUMMY_CUBE_TEXT = """CPMD CUBE FILE.
OUTER LOOP: X, MIDDLE LOOP: Y, INNER LOOP: Z
    1    0.000000    0.000000    0.000000
    2    1.000000    0.000000    0.000000
    2    0.000000    1.000000    0.000000
    2    0.000000    0.000000    1.000000
    8    8.000000    0.000000    0.000000    0.000000
 0.010000 0.020000 0.030000 0.040000 0.050000 0.060000 0.070000 0.080000
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _emit_progress(
    progress_callback: Optional[Callable[..., Any]],
    progress: float,
    step: str,
    message: str,
    **extra: Any,
) -> None:
    if not callable(progress_callback):
        return
    payload = {"progress": float(progress), "step": str(step), "message": str(message), **extra}
    try:
        progress_callback(payload)
        return
    except TypeError:
        pass
    progress_callback(progress, step, message)


def _base_result(
    *,
    job_type: str,
    structure_name: str = "water",
    method: str = "B3LYP",
    basis: str = "def2-SVP",
    charge: int = 0,
    multiplicity: int = 1,
) -> Dict[str, Any]:
    return {
        "success": True,
        "job_type": job_type,
        "structure_name": structure_name,
        "structure_query": structure_name,
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "xyz": WATER_XYZ,
        "formula": "H2O",
        "geometry_summary": {
            "n_atoms": 3,
            "formula": "H2O",
            "bond_count": 2,
            "bond_length_min_angstrom": 0.95,
            "bond_length_max_angstrom": 0.95,
            "bond_length_mean_angstrom": 0.95,
        },
        "warnings": [],
        "events": [],
        "scf_history": [
            {"cycle": 1, "energy": -75.9000000000},
            {"cycle": 2, "energy": -76.2100000000, "dE": -0.310000000000},
            {"cycle": 3, "energy": -76.3300000000, "dE": -0.120000000000},
            {"cycle": 4, "energy": -76.3681234500, "dE": -0.038123450000},
        ],
        "n_scf_cycles": 4,
        "scf_elapsed_s": 0.02,
        "scf_final_delta_e_hartree": -0.03812345,
        "visualization": {
            "xyz": WATER_XYZ,
            "molecule_xyz": WATER_XYZ,
            "defaults": {
                "style": "stick",
                "labels": False,
                "orbital_iso": 0.05,
                "orbital_opacity": 0.85,
                "esp_density_iso": 0.001,
                "esp_opacity": 0.90,
            },
        },
    }


def _fake_runner_factory(job_type: str):
    def _runner(
        structure_query=None,
        xyz=None,
        atom_spec=None,
        method=None,
        basis=None,
        charge=0,
        multiplicity=1,
        orbital=None,
        esp_preset=None,
        advisor_focus_tab=None,
        progress_callback=None,
        **kwargs,
    ):
        if not (structure_query or xyz or atom_spec):
            raise ValueError("No structure could be resolved; provide query, XYZ, or atom-spec text.")
        structure_name = structure_query or "custom"
        result = _base_result(
            job_type=job_type,
            structure_name=structure_name,
            method=method or "B3LYP",
            basis=basis or "def2-SVP",
            charge=charge,
            multiplicity=multiplicity,
        )

        _emit_progress(progress_callback, 0.10, "resolve", "Resolving structure")
        time.sleep(0.01)
        _emit_progress(
            progress_callback,
            0.45,
            "compute",
            f"Running {job_type}",
            scf_history=result.get("scf_history"),
            scf_cycle=result.get("n_scf_cycles"),
            scf_dE=result.get("scf_final_delta_e_hartree"),
            scf_energy=result.get("total_energy_hartree"),
        )
        time.sleep(0.01)

        if job_type in {"single_point", "partial_charges", "orbital_preview", "esp_map", "geometry_optimization", "analyze"}:
            result["scf_converged"] = True
            result["total_energy_hartree"] = -76.36812345
            result["total_energy_ev"] = -76.36812345 * float(getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988))
            result["total_energy_kcal_mol"] = -76.36812345 * float(getattr(pyscf_runner, "HARTREE_TO_KCAL", 627.5094740631))
            result["orbital_gap_hartree"] = 0.2500
            result["orbital_gap_ev"] = 0.2500 * float(getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988))
        if job_type in {"partial_charges", "orbital_preview", "esp_map", "geometry_optimization", "analyze"}:
            result["mulliken_charges"] = [
                {"atom_index": 0, "symbol": "O", "charge": -0.80},
                {"atom_index": 1, "symbol": "H", "charge": 0.40},
                {"atom_index": 2, "symbol": "H", "charge": 0.40},
            ]
            result["partial_charges"] = result["mulliken_charges"]
        if job_type in {"orbital_preview", "analyze"}:
            cube_b64 = _b64(DUMMY_CUBE_TEXT)
            result["selected_orbital"] = {
                "label": orbital or "HOMO",
                "index": 5,
                "zero_based_index": 4,
                "spin": "restricted",
                "occupancy": 2.0,
                "energy_hartree": -0.3125,
                "energy_ev": -8.5036,
            }
            result["homo_energy_hartree"] = -0.3125
            result["homo_energy_ev"] = -8.5036
            result["lumo_energy_hartree"] = -0.0625
            result["lumo_energy_ev"] = -1.7007
            result["orbitals"] = [
                {"label": "HOMO", "index": 5, "zero_based_index": 4, "spin": "restricted", "occupancy": 2.0, "energy_hartree": -0.3125, "energy_ev": -8.5036},
                {"label": "LUMO", "index": 6, "zero_based_index": 5, "spin": "restricted", "occupancy": 0.0, "energy_hartree": -0.0625, "energy_ev": -1.7007},
            ]
            result["visualization"]["orbital_cube_b64"] = cube_b64
            result["visualization"]["orbital"] = {"cube_b64": cube_b64, "label": orbital or "HOMO", "index": 5}
            result["advisor_focus_tab"] = advisor_focus_tab or "orbital"
        if job_type in {"esp_map", "analyze"}:
            dens_b64 = _b64(DUMMY_CUBE_TEXT)
            esp_b64 = _b64(DUMMY_CUBE_TEXT)
            result["esp_preset"] = esp_preset or "acs"
            result["esp_auto_range_au"] = 0.055
            result["esp_auto_range_kcal"] = 34.51
            result["esp_auto_fit"] = {
                "range_au": 0.055,
                "range_kcal": 34.51,
                "strategy": "robust_surface_shell_percentile",
                "stats": {"n": 2048, "min_au": -0.071, "max_au": 0.068, "p95_abs_au": 0.049},
            }
            result["visualization"]["density_cube_b64"] = dens_b64
            result["visualization"]["density"] = {"cube_b64": dens_b64}
            result["visualization"]["esp_cube_b64"] = esp_b64
            result["visualization"]["esp"] = {
                "cube_b64": esp_b64,
                "preset": esp_preset or "acs",
                "surface_scheme": "rwb",
                "range_au": 0.055,
                "range_kcal": 34.51,
                "density_iso": 0.001,
                "opacity": 0.90,
            }
            result["advisor_focus_tab"] = advisor_focus_tab or "esp"
        if job_type == "geometry_analysis":
            result["atoms"] = [
                {"atom_index": 0, "symbol": "O", "x": 0.0, "y": 0.0, "z": 0.0},
                {"atom_index": 1, "symbol": "H", "x": 0.0, "y": 0.7572, "z": 0.5863},
                {"atom_index": 2, "symbol": "H", "x": 0.0, "y": -0.7572, "z": 0.5863},
            ]
            result["advisor_focus_tab"] = advisor_focus_tab or "geometry"
        if job_type == "resolve_structure":
            result["resolved_structure"] = {
                "name": structure_name,
                "xyz": WATER_XYZ,
                "atom_spec": "O 0 0 0; H 0 0.75 0.58; H 0 -0.75 0.58",
            }
            result["advisor_focus_tab"] = advisor_focus_tab or "geometry"
        if job_type == "geometry_optimization":
            result["optimization_performed"] = True
            result["initial_xyz"] = WATER_XYZ
            result["optimized_xyz"] = WATER_XYZ
            result["advisor_focus_tab"] = advisor_focus_tab or "geometry"
        if job_type in {"single_point", "analyze"}:
            result["advisor_focus_tab"] = advisor_focus_tab or "summary"
        if job_type == "partial_charges":
            result["advisor_focus_tab"] = advisor_focus_tab or "charges"

        _emit_progress(progress_callback, 0.90, "finalize", "Finalizing result", scf_history=result.get("scf_history"))
        time.sleep(0.01)
        _emit_progress(progress_callback, 1.00, "done", "Completed")
        return result

    return _runner


@pytest.fixture()
def isolated_auth_db(monkeypatch, tmp_path):
    db_path = tmp_path / "qcviz_auth.sqlite3"
    monkeypatch.setenv("QCVIZ_AUTH_DB", str(db_path))
    auth_store.init_auth_db()
    yield db_path


@pytest.fixture()
def isolated_job_manager(monkeypatch):
    manager = compute_route.InMemoryJobManager(max_workers=1)
    monkeypatch.setattr(manager, "_save_to_disk", lambda: None, raising=False)
    monkeypatch.setattr(compute_route, "JOB_MANAGER", manager, raising=False)
    monkeypatch.setattr(compute_route, "get_job_manager", lambda: manager, raising=False)
    monkeypatch.setattr(chat_route, "get_job_manager", lambda: manager, raising=False)
    monkeypatch.setattr(compute_route, "DEFAULT_POLL_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(chat_route, "WS_POLL_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    yield manager
    manager.executor.shutdown(wait=False, cancel_futures=True)


@pytest.fixture()
def patch_fake_runners(monkeypatch):
    async def _fake_resolve_structure_async(query: str):
        return {
            "xyz": WATER_XYZ,
            "smiles": "O",
            "cid": 962,
            "name": query or "water",
            "source": "test",
            "sdf": None,
            "molecular_weight": 18.015,
            "query_plan": {"raw_query": query, "normalized_query": query, "candidate_queries": [query]},
        }

    async def _fake_resolve_ion_pair_async(structures):
        names = [str(item.get("name", "")).strip() for item in (structures or [])]
        return {
            "xyz": WATER_XYZ,
            "total_charge": sum(int(item.get("charge", 0)) for item in (structures or [])),
            "smiles_list": ["O"] * max(1, len(names)),
            "names": names or ["water"],
            "source": "test",
        }

    monkeypatch.setattr(pyscf_runner, "run_resolve_structure", _fake_runner_factory("resolve_structure"))
    monkeypatch.setattr(pyscf_runner, "run_geometry_analysis", _fake_runner_factory("geometry_analysis"))
    monkeypatch.setattr(pyscf_runner, "run_single_point", _fake_runner_factory("single_point"))
    monkeypatch.setattr(pyscf_runner, "run_partial_charges", _fake_runner_factory("partial_charges"))
    monkeypatch.setattr(pyscf_runner, "run_orbital_preview", _fake_runner_factory("orbital_preview"))
    monkeypatch.setattr(pyscf_runner, "run_esp_map", _fake_runner_factory("esp_map"))
    monkeypatch.setattr(pyscf_runner, "run_geometry_optimization", _fake_runner_factory("geometry_optimization"))
    monkeypatch.setattr(pyscf_runner, "run_analyze", _fake_runner_factory("analyze"))
    monkeypatch.setattr(compute_route, "_resolve_structure_async", _fake_resolve_structure_async)
    monkeypatch.setattr(compute_route, "_resolve_ion_pair_async", _fake_resolve_ion_pair_async)
    return True


@pytest.fixture()
def app(isolated_job_manager, isolated_auth_db):
    return create_app()


@pytest.fixture()
def client(app, patch_fake_runners):
    with TestClient(app) as c:
        yield c
