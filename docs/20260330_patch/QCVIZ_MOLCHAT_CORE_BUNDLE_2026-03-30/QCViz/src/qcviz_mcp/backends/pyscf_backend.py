"""PySCF 기반 IAO/IBO 및 엔터프라이즈 기능(Rich CLI, Shell-Sampling) 백엔드 v3.0.1."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from collections import Counter

import numpy as np

try:
    import pyscf
    from pyscf import gto, lo, scf, lib
    from pyscf.tools import cubegen
    _HAS_PYSCF = True
except ImportError:
    _HAS_PYSCF = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn,
    )
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

from qcviz_mcp.backends.base import IAOResult, IBOResult, OrbitalBackend, SCFResult
from qcviz_mcp.backends.registry import registry
from qcviz_mcp.analysis.sanitize import sanitize_xyz as _sanitize_xyz, extract_atom_list, atoms_to_xyz_string

logger = logging.getLogger(__name__)

_SUPPORTED_METHODS = frozenset({"HF", "RHF", "UHF", "RKS", "UKS", "B3LYP", "PBE0"})
_HEAVY_TM_Z = set(range(39, 49)) | set(range(72, 81))  # 4d(Y-Cd) + 5d(Hf-Hg)

# ================================================================
# §0  Errors & Strategies (Restored for tests)
# ================================================================

class ConvergenceError(RuntimeError):
    """적응적 SCF 수렴 전략이 모두 실패했을 때 발생."""
    pass

class ConvergenceStrategy:
    """적응적 SCF 수렴 에스컬레이션 엔진 (5단계)."""
    LEVELS = (
        {"name": "diis_default", "max_cycle": 100, "level_shift": 0.0, "soscf": False, "damp": 0.0},
        {"name": "diis_levelshift", "max_cycle": 200, "level_shift": 0.5, "soscf": False, "damp": 0.0},
        {"name": "diis_damp", "max_cycle": 200, "level_shift": 0.3, "soscf": False, "damp": 0.5},
        {"name": "soscf", "max_cycle": 200, "level_shift": 0.0, "soscf": True, "damp": 0.0},
        {"name": "soscf_shift", "max_cycle": 300, "level_shift": 0.5, "soscf": True, "damp": 0.0},
    )

    @staticmethod
    def apply(mf, level_idx: int = 0):
        if level_idx < 0 or level_idx >= len(ConvergenceStrategy.LEVELS):
            raise ValueError(f"Invalid strategy level: {level_idx}")
        cfg = ConvergenceStrategy.LEVELS[level_idx]
        mf.max_cycle = cfg["max_cycle"]
        mf.level_shift = cfg["level_shift"]
        mf.damp = cfg["damp"]
        if cfg["soscf"]:
            mf = mf.newton()
        return mf

    @staticmethod
    def level_name(level_idx: int) -> str:
        return ConvergenceStrategy.LEVELS[level_idx]["name"]

def _has_heavy_tm(mol) -> bool:
    if not _HAS_PYSCF: return False
    for ia in range(mol.natm):
        if int(mol.atom_charge(ia)) in _HEAVY_TM_Z: return True
    return False

def parse_cube_string(cube_text: str) -> dict:
    lines = cube_text.strip().splitlines()
    parts = lines[2].split()
    natm = abs(int(parts[0]))
    origin = (float(parts[1]), float(parts[2]), float(parts[3]))
    axes = []; npts_list = []
    for i in range(3):
        p = lines[3 + i].split()
        n = int(p[0]); npts_list.append(n)
        vec = np.array([float(p[1]), float(p[2]), float(p[3])]) * n
        axes.append(vec)
    npts = tuple(npts_list); atoms = []
    for i in range(natm):
        p = lines[6 + i].split()
        atoms.append((int(float(p[0])), float(p[2]), float(p[3]), float(p[4])))
    data_start = 6 + natm
    values = []
    for line in lines[data_start:]: values.extend(float(v) for v in line.split())
    data = np.array(values).reshape(npts)
    return {"data": data, "origin": origin, "axes": axes, "npts": npts, "atoms": atoms}

def _parse_atom_spec(atom_spec: str) -> str:
    lines = atom_spec.strip().splitlines()
    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        return atom_spec
    atom_lines: list[str] = []
    for line in lines[2 : 2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            atom_lines.append(f"{parts[0]}  {parts[1]}  {parts[2]}  {parts[3]}")
    return "; ".join(atom_lines)

def _safe_parse_atom_spec(atom_spec: str) -> str:
    """sanitize_xyz를 시도하고, 실패 시 기존 _parse_atom_spec으로 폴백."""
    try:
        return _sanitize_xyz(atom_spec)
    except (ValueError, Exception):
        return _parse_atom_spec(atom_spec)

# ================================================================
# §1  Rich CLI Reporter
# ================================================================
class _CLIReporter:
    def __init__(self):
        self.console = Console(stderr=True) if _HAS_RICH else None

    def print_calc_summary(self, method, basis, charge, spin, natoms, formula):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]QCViz Setup[/bold cyan]", header_style="bold white on dark_blue", border_style="blue")
            t.add_column("Parameter", style="bold"); t.add_column("Value", style="green")
            t.add_row("Method", method); t.add_row("Basis", basis); t.add_row("Charge", str(charge))
            t.add_row("Spin", str(spin)); t.add_row("Atoms", str(natoms)); t.add_row("Formula", formula)
            self.console.print(t)

    def run_scf_with_progress(self, mf, method, basis):
        if not self.console or not _HAS_RICH:
            mf.run(); return mf
        cd = {"n": 0, "last_e": None, "max": getattr(mf, "max_cycle", 50)}
        prog = Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), BarColumn(bar_width=30, complete_style="green"),
                        TextColumn("[cyan]{task.fields[energy]}"), TextColumn("[yellow]{task.fields[delta]}"), TimeElapsedColumn(), console=self.console)
        tid = [None]
        def cb(envs):
            cd["n"] += 1; e = envs.get("e_tot"); d_str = ""
            if e is not None:
                if cd["last_e"] is not None: d_str = "dE=%.2e" % (e - cd["last_e"])
                cd["last_e"] = e
            e_str = "E=%.8f" % e if e is not None else "E=..."
            if tid[0] is not None: prog.update(tid[0], completed=min(cd["n"]/cd["max"]*100, 100), energy=e_str, delta=d_str, description="SCF Cycle %d" % cd["n"])
        mf.callback = cb
        with prog:
            tid[0] = prog.add_task("SCF ...", total=100, energy="E=...", delta="")
            mf.run()
        if mf.converged: self.console.print(Panel(Text("CONVERGED  E = %.10f Ha" % mf.e_tot, style="bold green"), title="SCF Result", border_style="green"))
        return mf

    def print_esp_summary(self, vmin_raw, vmax_raw, vmin_sym, vmax_sym, p_lo, p_hi):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]ESP Analysis[/bold cyan]", border_style="cyan")
            t.add_column("Metric"); t.add_column("Value", style="green")
            t.add_row("Raw Min/Max", "%.6f / %.6f" % (vmin_raw, vmax_raw))
            t.add_row("P5/P95", "%.6f / %.6f" % (p_lo, p_hi))
            t.add_row("Final Range", "[bold]%.6f .. %.6f[/bold]" % (vmin_sym, vmax_sym))
            self.console.print(t)

    def print_cube_progress(self, current, total, label):
        if self.console and _HAS_RICH: self.console.print("  [dim]Cube[/dim] [bold]%d[/bold]/%d  %s" % (current, total, label))

_cli = _CLIReporter()

@dataclass
class ESPResult:
    density_cube: str; potential_cube: str; vmin: float; vmax: float; vmin_raw: float; vmax_raw: float
    atom_symbols: list; energy_hartree: float; basis: str; grid_size: int = 60; margin: float = 10.0

# ================================================================
# §2  PySCF Backend
# ================================================================

class PySCFBackend(OrbitalBackend):
    @classmethod
    def name(cls): return "pyscf"
    @classmethod
    def is_available(cls): return _HAS_PYSCF

    def compute_scf(self, atom_spec, basis="cc-pvdz", method="RHF", charge=0, spin=0):
        if not _HAS_PYSCF: raise ImportError("PySCF가 설치되지 않았습니다.")
        method_upper = method.upper()
        if method_upper not in _SUPPORTED_METHODS: raise ValueError(f"지원하지 않는 메서드 유형: {method}")
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, verbose=0)
        
        is_dft = any(xc in method_upper for xc in ("B3LYP", "PBE", "WB97", "M06", "RKS", "UKS", "TPSS"))
        if is_dft:
            mf = scf.UKS(mol) if (spin > 0 or method_upper == "UKS") else scf.RKS(mol)
            if method_upper not in ("RKS", "UKS"): mf.xc = method
        else:
            mf = scf.UHF(mol) if (spin > 0 or method_upper == "UHF") else scf.RHF(mol)
        
        syms = [mol.atom_symbol(i) for i in range(mol.natm)]; counts = Counter(syms)
        formula = "".join("%s%s" % (e, str(counts[e]) if counts[e] > 1 else "") for e in sorted(counts.keys()))
        _cli.print_calc_summary(method, basis, charge, spin, mol.natm, formula)
        mf = _cli.run_scf_with_progress(mf, method, basis)
        
        if not mf.converged: mf, mol = self.compute_scf_adaptive(mol, spin=spin)
        return (SCFResult(True, float(mf.e_tot), mf.mo_coeff, mf.mo_occ, mf.mo_energy, basis, method), mol)

    def compute_esp(self, atom_spec, basis="cc-pvdz", grid_size=60, method="rhf", charge=0, spin=0):
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, unit="Angstrom", verbose=0)
        mol.build(); mf = scf.RKS(mol) if spin == 0 else scf.UKS(mol); mf.run(); dm = mf.make_rdm1()
        d_p = p_p = None
        try:
            with tempfile.NamedTemporaryFile(suffix="_den.cube", delete=False) as f1: d_p = f1.name
            with tempfile.NamedTemporaryFile(suffix="_pot.cube", delete=False) as f2: p_p = f2.name
            cubegen.density(mol, d_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            cubegen.mep(mol, p_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            with open(d_p) as f: d_c = f.read()
            with open(p_p) as f: p_c = f.read()
        finally:
            for p in (d_p, p_p):
                if p and os.path.exists(p): os.unlink(p)
        vr, vxr, p_lo, p_hi = self._extract_surface_potential_range(d_c, p_c)
        abs_max = max(abs(p_lo), abs(p_hi))
        if abs_max < 1e-5: abs_max = 0.05
        _cli.print_esp_summary(vr, vxr, -abs_max, abs_max, p_lo, p_hi)
        return ESPResult(d_c, p_c, -abs_max, abs_max, vr, vxr, [mol.atom_symbol(i) for i in range(mol.natm)], float(mf.e_tot), basis, grid_size, 10.0)

    def _extract_surface_potential_range(self, den_cube, pot_cube, isoval=0.002):
        def get_data(cube):
            ls = cube.splitlines()
            if len(ls) < 7: return np.array([])
            toks2 = ls[2].split(); na = abs(int(toks2[0])); ds = 6 + na + (1 if int(toks2[0]) < 0 else 0)
            raw = " ".join(ls[ds:]).replace("D", "E").replace("d", "e")
            return np.fromstring(raw, sep=" ")
        darr = get_data(den_cube); parr = get_data(pot_cube)
        if len(darr) == 0 or len(darr) != len(parr): return -0.1, 0.1, -0.1, 0.1
        mask = (darr >= isoval * 0.8) & (darr <= isoval * 1.2)
        if not np.any(mask): mask = darr >= isoval
        surf_p = parr[mask]
        surf_p = surf_p[np.isfinite(surf_p)]
        if len(surf_p) == 0: return -0.1, 0.1, -0.1, 0.1
        p_lo = float(np.percentile(surf_p, 5))
        p_hi = float(np.percentile(surf_p, 95))
        return float(np.min(surf_p)), float(np.max(surf_p)), p_lo, p_hi

    def generate_cube(self, mol, coeffs, orbital_index, grid_points=(60,60,60)):
        with tempfile.NamedTemporaryFile(suffix=".cube", delete=False) as tmp: t_p = tmp.name
        try:
            cubegen.orbital(mol, t_p, coeffs[:, orbital_index], nx=grid_points[0], ny=grid_points[1], nz=grid_points[2], margin=10.0)
            with open(t_p) as f: return f.read()
        finally:
            if os.path.exists(t_p): os.remove(t_p)

    def compute_iao(self, scf_res, mol, minao="minao"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        iao_coeff = lo.iao.iao(mol, orbocc, minao=minao)
        charges = self._compute_iao_charges(mol, scf_res, iao_coeff)
        return IAOResult(coefficients=iao_coeff, charges=charges)

    def _iao_population_custom(self, mol, dm, iao_coeff):
        ovlp = mol.intor_symmetric("int1e_ovlp")
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        p_matrix = (iao_coeff @ np.linalg.inv(s_iao) @ iao_coeff.T @ ovlp @ dm @ ovlp)
        a_pop = [np.trace(p_matrix[b0:b1, b0:b1]) for b0, b1 in [mol.aoslice_by_atom()[i][2:] for i in range(mol.natm)]]
        return np.array(a_pop)

    def _compute_iao_charges(self, mol: Any, scf_result: SCFResult, iao_coeff: np.ndarray) -> np.ndarray:
        ovlp = mol.intor_symmetric("int1e_ovlp")
        orbocc = scf_result.mo_coeff[:, scf_result.mo_occ > 0]
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        eigvals, eigvecs = np.linalg.eigh(s_iao)
        s_iao_inv_half = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
        iao_orth = iao_coeff @ s_iao_inv_half
        proj = iao_orth.T @ ovlp @ orbocc
        dm_iao = (1.0 if mol.spin > 0 else 2.0) * proj @ proj.T
        
        from pyscf.lo.iao import reference_mol
        effective_minao, _ = self._resolve_minao(mol, "minao")
        pmol = reference_mol(mol, minao=effective_minao)
        ref_labels = pmol.ao_labels(fmt=False)
        n_iao = iao_orth.shape[1]
        charges = np.zeros(mol.natm)
        for j in range(n_iao):
            atom_idx = ref_labels[j][0]
            charges[atom_idx] += dm_iao[j, j]
        for i in range(mol.natm):
            charges[i] = mol.atom_charge(i) - charges[i]
        return charges

    def compute_ibo(self, scf_res, iao_res, mol, localization_method: str = "IBO"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        if localization_method.upper() == "BOYS":
            loc_obj = lo.Boys(mol, orbocc)
            ibo_coeff = loc_obj.kernel()
        elif localization_method.upper() == "PM":
            loc_obj = lo.PM(mol, orbocc)
            ibo_coeff = loc_obj.kernel()
        else:
            ibo_coeff = lo.ibo.ibo(mol, orbocc, iaos=iao_res.coefficients)
        n_ibo = ibo_coeff.shape[1]
        return IBOResult(coefficients=ibo_coeff, occupations=np.full(n_ibo, 2.0), n_ibo=n_ibo)

    def _resolve_minao(self, mol, minao="minao"):
        warnings = []; effective = minao; ecp_detected = False
        if hasattr(mol, "has_ecp"):
            ecp_result = mol.has_ecp()
            ecp_detected = bool(ecp_result) if not isinstance(ecp_result, dict) else len(ecp_result) > 0
        if not ecp_detected and hasattr(mol, "_ecp") and mol._ecp: ecp_detected = True
        if ecp_detected and minao == "minao":
            effective = "sto-3g"
            warnings.append("ECP detected. Switched IAO reference basis to 'sto-3g'.")
        if _has_heavy_tm(mol) and minao == "minao":
            warnings.append("Heavy TM (4d/5d) detected. Consider using minao='sto-3g' if IAO fails.")
        return effective, warnings

    @staticmethod
    def _unpack_uhf(mo_coeff, mo_occ):
        if isinstance(mo_coeff, (tuple, list)): return mo_coeff[0], mo_coeff[1], mo_occ[0], mo_occ[1]
        elif isinstance(mo_coeff, np.ndarray) and mo_coeff.ndim == 3: return mo_coeff[0], mo_coeff[1], mo_occ[0], mo_occ[1]
        raise ValueError("Unexpected mo_coeff type")

    def export_molden(self, mol_obj: Any, mo_coeff: np.ndarray, output_path: str) -> str:
        from pyscf.tools import molden as molden_mod
        molden_mod.from_mo(mol_obj, output_path, mo_coeff)
        return str(Path(output_path).resolve())

    def compute_scf_flexible(self, atom_spec: str, basis: str = "sto-3g", charge: int = 0, spin: int = 0, adaptive: bool = False):
        if not _HAS_PYSCF: raise ImportError("PySCF가 설치되지 않았습니다.")
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, verbose=0)
        if adaptive: return self.compute_scf_adaptive(mol, spin=spin)
        mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
        mf.kernel()
        if not mf.converged: raise RuntimeError(f"SCF not converged for spin={spin}")
        return mf, mol

    def compute_scf_adaptive(self, mol, spin: int = 0, max_escalation: int = 4):
        max_level = min(max_escalation, len(ConvergenceStrategy.LEVELS) - 1)
        for level in range(max_level + 1):
            mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
            mf = ConvergenceStrategy.apply(mf, level)
            try:
                mf = _cli.run_scf_with_progress(mf, f"Adaptive L{level}", mol.basis)
                if mf.converged:
                    logger.info("SCF converged at level %d: %s (E=%.8f)", level, ConvergenceStrategy.level_name(level), mf.e_tot)
                    return mf, mol
            except Exception as e:
                logger.warning("Level %d failed: %s", level, e)
                continue
        raise ConvergenceError(f"SCF failed after {max_level + 1} strategies.")

    def compute_scf_relativistic(self, atom_spec, basis="def2-svp", ecp=None, spin=0, charge=0, relativistic="sfx2c1e"):
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, ecp=ecp, charge=charge, spin=spin, verbose=0)
        mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
        if relativistic == "sfx2c1e": mf = mf.sfx2c1e()
        elif relativistic == "x2c": mf = mf.x2c()
        mf = _cli.run_scf_with_progress(mf, f"Relativistic ({relativistic})", basis)
        if not mf.converged: mf, mol = self.compute_scf_adaptive(mol, spin=spin)
        return mf, mol

    def compute_iao_uhf(self, mf, mol, minao: str = "minao"):
        effective, warnings = self._resolve_minao(mol, minao)
        mo_a, mo_b, occ_a, occ_b = self._unpack_uhf(mf.mo_coeff, mf.mo_occ)
        mo_occ_a = mo_a[:, occ_a > 0]; mo_occ_b = mo_b[:, occ_b > 0]
        iao_a = lo.iao.iao(mol, mo_occ_a, minao=effective)
        iao_b = lo.iao.iao(mol, mo_occ_b, minao=effective)
        return {"alpha": {"iao_coeff": iao_a, "n_iao": iao_a.shape[1]}, "beta": {"iao_coeff": iao_b, "n_iao": iao_b.shape[1]}, "is_uhf": True, "minao_used": effective, "warnings": warnings}

    def compute_ibo_uhf(self, mf, iao_result, mol):
        mo_a, mo_b, occ_a, occ_b = self._unpack_uhf(mf.mo_coeff, mf.mo_occ)
        mo_occ_a = mo_a[:, occ_a > 0]; mo_occ_b = mo_b[:, occ_b > 0]
        ibo_a = lo.ibo.ibo(mol, mo_occ_a, iaos=iao_result["alpha"]["iao_coeff"])
        ibo_b = lo.ibo.ibo(mol, mo_occ_b, iaos=iao_result["beta"]["iao_coeff"])
        return {"alpha": {"ibo_coeff": ibo_a, "n_ibo": ibo_a.shape[1]}, "beta": {"ibo_coeff": ibo_b, "n_ibo": ibo_b.shape[1]}, "is_uhf": True, "total_ibo": ibo_a.shape[1] + ibo_b.shape[1]}

    def compute_uhf_charges(self, mf, mol):
        dm = mf.make_rdm1()
        dm_total = dm[0] + dm[1] if (isinstance(dm, np.ndarray) and dm.ndim == 3) or isinstance(dm, (list, tuple)) else dm
        s = mol.intor("int1e_ovlp")
        pop, chg = mf.mulliken_pop(mol, dm_total, s, verbose=0)
        return [float(c) for c in chg]

    def compute_geomopt(
        self,
        atom_spec: str,
        basis: str = "def2-svp",
        method: str = "B3LYP",
        charge: int = 0,
        spin: int = 0,
        maxsteps: int = 100,
        use_d3: bool = True,
    ) -> dict:
        """PySCF geomeTRIC 기반 구조 최적화.

        Parameters
        ----------
        atom_spec : str
            원자 좌표 (XYZ 또는 PySCF 형식).
        basis : str
            기저 함수 (기본: def2-svp).
        method : str
            계산 방법 (기본: B3LYP).
        charge, spin : int
            분자 전하 및 스핀 다중도.
        maxsteps : int
            최대 최적화 단계 수.
        use_d3 : bool
            DFT-D3 분산 보정 사용 여부.

        Returns
-------
        dict
            optimized_xyz: 최적화된 XYZ 문자열,
            energy: 최종 에너지 (Hartree),
            converged: 수렴 여부,
            n_steps: 최적화 단계 수.
        """
        if not _HAS_PYSCF:
            raise ImportError("PySCF가 설치되지 않았습니다.")

        try:
            from pyscf.geomopt.geometric_solver import optimize as geom_optimize
        except ImportError:
            raise ImportError(
                "geomeTRIC이 설치되지 않았습니다. "
                "'pip install geometric'으로 설치하세요."
            )

        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin,
                     unit="Angstrom", verbose=0)

        method_upper = method.upper()
        is_dft = any(xc in method_upper for xc in (
            "B3LYP", "PBE", "WB97", "M06", "RKS", "UKS", "TPSS", "PBE0",
        ))

        if is_dft:
            from pyscf import dft
            mf = dft.UKS(mol) if spin > 0 else dft.RKS(mol)
            if method_upper not in ("RKS", "UKS"):
                mf.xc = method
            else:
                mf.xc = "b3lyp"
        else:
            mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)

        # D3 분산 보정
        if use_d3 and is_dft:
            try:
                from pyscf import dftd3
                mf = dftd3.dftd3(mf)
                logger.info("DFT-D3 dispersion correction enabled")
            except ImportError:
                logger.warning("pyscf-dftd3 not installed, skipping D3 correction")

        mf = _cli.run_scf_with_progress(mf, method, basis)

        # geomeTRIC 최적화
        conv_params = {
            "convergence_energy": 1e-6,
            "convergence_grms": 3e-4,
            "convergence_gmax": 4.5e-4,
            "convergence_drms": 1.2e-3,
            "convergence_dmax": 1.8e-3,
        }

        step_count = [0]
        def _opt_callback(envs):
            step_count[0] += 1
            if _cli.console and _HAS_RICH:
                e = envs.get("energy", 0.0)
                gnorm = envs.get("gradnorm", 0.0)
                _cli.console.print(
                    "  [dim]Opt Step[/dim] [bold]%d[/bold]  "
                    "E=%.8f  |g|=%.6f" % (step_count[0], e, gnorm)
                )

        try:
            mol_eq = geom_optimize(
                mf, maxsteps=maxsteps, callback=_opt_callback, **conv_params
            )
            converged = True
        except Exception as e:
            logger.warning("Geometry optimization did not converge: %s", e)
            mol_eq = mf.mol  # 마지막 지오메트리 사용
            converged = False

        # 최적화된 좌표를 XYZ 문자열로 변환
        from qcviz_mcp.analysis.sanitize import atoms_to_xyz_string
        coords = mol_eq.atom_coords(unit="Angstrom")
        symbols = [mol_eq.atom_symbol(i) for i in range(mol_eq.natm)]
        opt_atoms = list(zip(symbols, coords[:, 0], coords[:, 1], coords[:, 2]))
        opt_xyz = atoms_to_xyz_string(
            opt_atoms,
            comment="Optimized: %s/%s E=%.8f Ha" % (method, basis, mf.e_tot)
        )

        return {
            "optimized_xyz": opt_xyz,
            "optimized_atom_spec": mol_eq.tostring(),
            "energy_hartree": float(mf.e_tot),
            "converged": converged,
            "n_steps": step_count[0],
            "method": method,
            "basis": basis,
        }

registry.register(PySCFBackend)
