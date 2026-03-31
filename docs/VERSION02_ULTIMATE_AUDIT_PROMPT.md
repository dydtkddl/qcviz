# ⚠️ QCViz-MCP v5 Enterprise — 시스템 통합 정합성 전수조사 및 결함 수정 지침서

## 1. 감사 목적 (Objective)
현재 QCViz-MCP v5 시스템은 개별 기능 수정 과정에서 발생한 파편화된 코드, 명칭 불일치, 접합부(Interface)의 논리 오류, 그리고 잠재적인 데드락/메모리 누수 위험을 안고 있습니다. 본 지시서는 시스템의 **데이터 흐름(Data Flow) 전체를 횡단하며 모든 부정합을 찾아내고, Enterprise 급 안정성을 확보하는 것**을 목표로 합니다.

## 2. 집중 감사 영역 (Critical Audit Focus)
### A. 백엔드-프론트엔드 데이터 계약 (Contract Alignment)
- `pyscf_runner.py`가 반환하는 JSON 필드명이 `results.js`와 `viewer.js`에서 기대하는 이름과 100% 일치하는가?
- 예: `total_energy_hartree` vs `energy`, `orbital_cube_b64` vs `orbital` 객체 구조 등.

### B. 상태 관리 및 Lock 정합성 (State & Concurrency)
- `compute.py`의 `JobRecord` 상태 업데이트와 WebSocket 이벤트 전송 사이에 Race Condition이 없는가?
- `viewer.js`의 `state.mode` 전환 시 이전 Isosurface/Model이 완벽하게 정리(dispose)되는가?

### C. 에러 전파 및 Fallback (Robustness)
- PySCF 계산 실패, 3Dmol.js 로드 실패, WebSocket 끊김 등 모든 실패 경로에서 사용자에게 명확한 에러 메시지가 전달되고 시스템이 'Ready' 상태로 복귀하는가?
- `try-catch` 내에서 에러를 삼키고(swallow) 로직이 멈추는 구간이 없는가?

## 3. 전체 소스 코드 데이터베이스 (Source Bundle)
아래는 현재 시스템의 모든 핵심 파일 내용입니다. 각 파일의 내용을 기반으로 상호 참조 및 정합성을 검증하십시오.

### File: `compute/pyscf_runner.py`
```py
from __future__ import annotations
import re
import os
import base64
import math
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
from pyscf import dft, gto, scf
from pyscf.tools import cubegen

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:  # pragma: no cover
    geometric_optimize = None

# ----------------------------------------------------------------------------
# CONSTANTS & METADATA
# ----------------------------------------------------------------------------

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
BOHR_TO_ANGSTROM = 0.529177210903
EV_TO_KCAL = 23.06054783061903

DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

DEFAULT_ESP_PRESET_ORDER = [
    "acs",
    "rsc",
    "nature",
    "spectral",
    "inferno",
    "viridis",
    "rwb",
    "bwr",
    "greyscale",
    "high_contrast",
]

ESP_PRESETS_DATA: Dict[str, Dict[str, Any]] = {
    "acs": {
        "id": "acs",
        "label": "ACS-style",
        "aliases": ["american chemical society", "acs-style", "science", "default"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Balanced red-white-blue diverging scheme for molecular ESP.",
    },
    "rsc": {
        "id": "rsc",
        "label": "RSC-style",
        "aliases": ["royal society of chemistry", "rsc-style"],
        "surface_scheme": "bwr",
        "default_range_au": 0.055,
        "description": "Soft blue-white-red variant commonly seen in chemistry figures.",
    },
    "nature": {
        "id": "nature",
        "label": "Nature-style",
        "aliases": ["nature-style"],
        "surface_scheme": "spectral",
        "default_range_au": 0.055,
        "description": "Publication-friendly high-separation spectral diverging scheme.",
    },
    "spectral": {
        "id": "spectral",
        "label": "Spectral",
        "aliases": ["rainbow", "diverging"],
        "surface_scheme": "spectral",
        "default_range_au": 0.060,
        "description": "High contrast diverging palette.",
    },
    "inferno": {
        "id": "inferno",
        "label": "Inferno",
        "aliases": [],
        "surface_scheme": "inferno",
        "default_range_au": 0.055,
        "description": "Perceptually uniform warm palette.",
    },
    "viridis": {
        "id": "viridis",
        "label": "Viridis",
        "aliases": [],
        "surface_scheme": "viridis",
        "default_range_au": 0.055,
        "description": "Perceptually uniform scientific palette.",
    },
    "rwb": {
        "id": "rwb",
        "label": "Red-White-Blue",
        "aliases": ["red-white-blue", "red white blue"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Classic negative/neutral/positive diverging palette.",
    },
    "bwr": {
        "id": "bwr",
        "label": "Blue-White-Red",
        "aliases": ["blue-white-red", "blue white red"],
        "surface_scheme": "bwr",
        "default_range_au": 0.060,
        "description": "Classic positive/neutral/negative diverging palette.",
    },
    "greyscale": {
        "id": "greyscale",
        "label": "Greyscale",
        "aliases": ["gray", "grey", "mono", "monochrome"],
        "surface_scheme": "greyscale",
        "default_range_au": 0.050,
        "description": "Monochrome publication palette.",
    },
    "high_contrast": {
        "id": "high_contrast",
        "label": "High Contrast",
        "aliases": ["high-contrast", "contrast"],
        "surface_scheme": "high_contrast",
        "default_range_au": 0.070,
        "description": "Strong contrast for presentations and screenshots.",
    },
}

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_ALIASES: Dict[str, str] = {
    "hf": "HF",
    "rhf": "HF",
    "uhf": "HF",
    "b3lyp": "B3LYP",
    "pbe": "PBE",
    "pbe0": "PBE0",
    "m062x": "M06-2X",
    "m06-2x": "M06-2X",
    "wb97xd": "wB97X-D",
    "ωb97x-d": "wB97X-D",
    "wb97x-d": "wB97X-D",
    "bp86": "BP86",
    "blyp": "BLYP",
}

_BASIS_ALIASES: Dict[str, str] = {
    "sto-3g": "STO-3G",
    "3-21g": "3-21G",
    "6-31g": "6-31G",
    "6-31g*": "6-31G*",
    "6-31g(d)": "6-31G*",
    "6-31g**": "6-31G**",
    "6-31g(d,p)": "6-31G**",
    "def2svp": "def2-SVP",
    "def2-svp": "def2-SVP",
    "def2tzvp": "def2-TZVP",
    "def2-tzvp": "def2-TZVP",
    "cc-pvdz": "cc-pVDZ",
    "cc-pvtz": "cc-pVTZ",
}

_COVALENT_RADII = {
    "H": 0.31,
    "B": 0.85,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
    "Si": 1.11,
}

BUILTIN_XYZ_LIBRARY = {
    "water": "3\n\nO 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469",
    "ammonia": "4\n\nN 0.000 0.000 0.112\nH 0.000 0.938 -0.262\nH 0.812 -0.469 -0.262\nH -0.812 -0.469 -0.262",
    "methane": "5\n\nC 0.000 0.000 0.000\nH 0.627 0.627 0.627\nH -0.627 -0.627 0.627\nH 0.627 -0.627 -0.627\nH -0.627 0.627 -0.627",
    "benzene": "12\n\nC 0.0000 1.3965 0.0000\nC 1.2094 0.6983 0.0000\nC 1.2094 -0.6983 0.0000\nC 0.0000 -1.3965 0.0000\nC -1.2094 -0.6983 0.0000\nC -1.2094 0.6983 0.0000\nH 0.0000 2.4842 0.0000\nH 2.1514 1.2421 0.0000\nH 2.1514 -1.2421 0.0000\nH 0.0000 -2.4842 0.0000\nH -2.1514 -1.2421 0.0000\nH -2.1514 1.2421 0.0000",
    "acetone": "10\n\nC 0.000 0.280 0.000\nO 0.000 1.488 0.000\nC 1.285 -0.551 0.000\nC -1.285 -0.551 0.000\nH 1.266 -1.203 -0.880\nH 1.266 -1.203 0.880\nH 2.155 0.106 0.000\nH -1.266 -1.203 -0.880\nH -1.266 -1.203 0.880\nH -2.155 0.106 0.000",
}

# ----------------------------------------------------------------------------
# CORE UTILS
# ----------------------------------------------------------------------------

def unique(arr):
    seen = set()
    out = []
    for x in arr:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _dedupe_strings(items: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items or []:
        text = _safe_str(item, "")
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out

def _normalize_name_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^0-9a-zA-Z가-힣+\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_method_name(method: Optional[str]) -> str:
    key = _normalize_name_token(method).replace(" ", "")
    return _METHOD_ALIASES.get(key, _safe_str(method, DEFAULT_METHOD) or DEFAULT_METHOD)

def _normalize_basis_name(basis: Optional[str]) -> str:
    key = _normalize_name_token(basis).replace(" ", "")
    return _BASIS_ALIASES.get(key, _safe_str(basis, DEFAULT_BASIS) or DEFAULT_BASIS)

def _normalize_esp_preset(preset: Optional[str]) -> str:
    raw = _normalize_name_token(preset)
    if not raw:
        return "acs"
    compact = raw.replace(" ", "_")
    if compact in ESP_PRESETS_DATA:
        return compact
    for key, meta in ESP_PRESETS_DATA.items():
        aliases = [_normalize_name_token(a).replace(" ", "_") for a in meta.get("aliases", [])]
        if compact == key or compact in aliases:
            return key
    if compact in {"default", "auto"}:
        return "acs"
    return "acs"

def _looks_like_xyz(text: Optional[str]) -> bool:
    if not text:
        return False
    s = str(text).strip()
    if "\n" in s:
        lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[2:]
        atom_pat = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
        atom_lines = [ln for ln in lines if atom_pat.match(ln.strip())]
        return len(atom_lines) >= 1
    return False

def _strip_xyz_header(xyz_text: str) -> str:
    lines = (xyz_text or "").splitlines()
    
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            start_idx = i
            break
    else:
        return ""
        
    first_line = lines[start_idx].strip()
    if re.fullmatch(r"\d+", first_line):
        start_idx += 2
        
    atom_lines = [ln.strip() for ln in lines[start_idx:] if ln.strip()]
    return "\n".join(atom_lines)

def _iter_structure_libraries() -> Iterable[Mapping[str, str]]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = globals().get(name)
        if isinstance(lib, Mapping) and id(lib) not in seen:
            seen.add(id(lib))
            yield lib

def _lookup_builtin_xyz(query: Optional[str]) -> Optional[Tuple[str, str]]:
    if not query:
        return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    
    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\\b{n}\\b", " ", qc, flags=re.I)
    qc = re.sub(r"\\s+", " ", qc).strip()
    
    candidates = unique([q0, qn, qc, qn.replace(" ", "_"), qn.replace(" ", ""), qc.replace(" ", "_"), qc.replace(" ", "")])
    
    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map = {}
        for key, value in lib.items():
            if not isinstance(value, str): continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
            
        for cand in candidates:
            if cand in normalized_map: return normalized_map[cand]
        
        for kn, pair in normalized_map.items():
            if len(kn) > 2 and (kn in qn or kn in qc):
                return pair
    return None

def _resolve_structure_payload(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
) -> Tuple[str, str]:
    if atom_spec and _safe_str(atom_spec):
        return _safe_str(structure_query, "custom"), _safe_str(atom_spec).strip()

    if xyz and _safe_str(xyz):
        atom_text = _strip_xyz_header(_safe_str(xyz))
        if atom_text:
            return _safe_str(structure_query, "custom"), atom_text

    if structure_query and _looks_like_xyz(structure_query):
        atom_text = _strip_xyz_header(_safe_str(structure_query))
        if atom_text:
            return "custom", atom_text

    if structure_query:
        hit = _lookup_builtin_xyz(structure_query)
        if hit:
            label, xyz_text = hit
            atom_text = _strip_xyz_header(xyz_text)
            return label, atom_text

        # Don't silently swallow the error
        resolve_error = None
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(structure_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except Exception as e:
            resolve_error = e

        if resolve_error:
            raise ValueError(
                f"Could not resolve structure '{structure_query}': {resolve_error}"
            ) from resolve_error

    raise ValueError("No structure could be resolved; provide query, XYZ, or atom-spec text.")

def _mol_to_xyz(mol: gto.Mole, comment: str = "") -> str:
    coords = mol.atom_coords(unit="Angstrom")
    lines = [str(mol.natm), comment or "QCViz-MCP"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        x, y, z = coords[i]
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    return "\n".join(lines)

def _build_mol(
    atom_text: str,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    unit: str = "Angstrom",
) -> gto.Mole:
    basis_name = _normalize_basis_name(basis or DEFAULT_BASIS)
    spin = max(int(multiplicity or 1) - 1, 0)
    return gto.M(
        atom=atom_text,
        basis=basis_name,
        charge=int(charge or 0),
        spin=spin,
        unit=unit,
        verbose=0,
    )

def _build_mean_field(mol: gto.Mole, method: Optional[str] = None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))
    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf

    xc_map = {
        "b3lyp": "b3lyp",
        "pbe": "pbe",
        "pbe0": "pbe0",
        "m06-2x": "m06-2x",
        "m062x": "m06-2x",
        "wb97x-d": "wb97x-d",
        "ωb97x-d": "wb97x-d",
        "wb97x-d": "wb97x-d",
        "bp86": "bp86",
        "blyp": "blyp",
    }
    xc = xc_map.get(key, "b3lyp")
    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass
    return method_name, mf

import hashlib
from qcviz_mcp.compute.disk_cache import save_to_disk, load_from_disk

_SCF_CACHE = {}

def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

import time

def _run_scf_with_fallback(mf, warnings: Optional[List[str]] = None, cache_key: Optional[str] = None, progress_callback: Optional[Callable] = None):
    warnings = warnings if warnings is not None else []

    current_mol = getattr(mf, 'mol', None)

    if cache_key:
        if cache_key in _SCF_CACHE:
            cached_mf, cached_energy = _SCF_CACHE[cache_key]
            if current_mol is not None:
                cached_mf.mol = current_mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Cache hit: SCF skipped (0.0s)")
            return cached_mf, cached_energy

        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            if current_mol is not None:
                disk_mf.mol = current_mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Disk cache hit: SCF loaded (0.0s)")
            return disk_mf, disk_energy
    try:
        mf.conv_tol = min(getattr(mf, "conv_tol", 1e-9), 1e-9)
    except Exception:
        pass
    try:
        mf.max_cycle = max(int(getattr(mf, "max_cycle", 50)), 100)
    except Exception:
        pass

    # Attach a callback to report SCF iterations
    cycle_count = [0]
    def _scf_callback(env):
        cycle_count[0] += 1
        if progress_callback and cycle_count[0] % 2 == 0:
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0)
            _emit_progress(progress_callback, min(0.60, 0.35 + (c / 100.0) * 0.25), "scf", f"SCF iteration {c}/{max_c} (E={e:.4f} Ha)")

    try:
        mf.callback = _scf_callback
    except Exception:
        pass

    t0 = time.time()
    energy = mf.kernel()
    t1 = time.time()
    elapsed = t1 - t0
    
    cycles = cycle_count[0]
    
    if getattr(mf, "converged", False):
        if progress_callback:
            _emit_progress(progress_callback, 0.60, "scf", f"SCF converged in {cycles} cycles ({elapsed:.1f}s)")
        if cache_key:
            _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
        return mf, energy

    warnings.append(f"Primary SCF did not converge after {cycles} cycles; attempting Newton refinement.")
    if progress_callback:
        _emit_progress(progress_callback, 0.60, "scf", "Primary SCF failed; starting Newton refinement")
        
    try:
        mf = mf.newton()
        energy = mf.kernel()
        t2 = time.time()
        elapsed_newton = t2 - t1
        
        if progress_callback:
            _emit_progress(progress_callback, 0.65, "scf", f"Newton refinement finished ({elapsed_newton:.1f}s)")
            
        if cache_key and getattr(mf, "converged", False):
            _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
    except Exception as exc:
        warnings.append(f"Newton refinement failed: {exc}")

    return mf, energy

def _file_to_b64(path: Union[str, Path, None]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")

def _parse_cube_values(path: Union[str, Path]) -> np.ndarray:
    p = Path(path)
    text = p.read_text(errors="ignore").splitlines()
    if len(text) < 7:
        return np.array([], dtype=float)

    try:
        natm = abs(int(text[2].split()[0]))
        data_start = 6 + natm
    except Exception:
        data_start = 6

    values: List[float] = []
    for line in text[data_start:]:
        for token in line.split():
            try:
                values.append(float(token))
            except Exception:
                continue
    return np.asarray(values, dtype=float)

def _nice_symmetric_limit(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.05
    if value < 0.02:
        step = 0.0025
    elif value < 0.05:
        step = 0.005
    elif value < 0.10:
        step = 0.010
    else:
        step = 0.020
    return float(math.ceil(value / step) * step)

def _compute_esp_auto_range(
    esp_values: np.ndarray,
    density_values: Optional[np.ndarray] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    arr = np.asarray(esp_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        default_au = ESP_PRESETS_DATA["acs"]["default_range_au"]
        return {
            "range_au": default_au,
            "range_kcal": default_au * HARTREE_TO_KCAL,
            "stats": {},
            "strategy": "default",
        }

    masked = arr
    if density_values is not None:
        dens_raw = np.asarray(density_values, dtype=float).ravel()
        esp_raw = np.asarray(esp_values, dtype=float).ravel()
        if dens_raw.size == esp_raw.size:
            # finite mask on BOTH arrays simultaneously
            finite_mask = np.isfinite(dens_raw) & np.isfinite(esp_raw)
            if np.count_nonzero(finite_mask) >= 128:
                low = density_iso * 0.35
                high = density_iso * 4.0
                shell_mask = finite_mask & (dens_raw >= low) & (dens_raw <= high)
                if np.count_nonzero(shell_mask) >= 128:
                    masked = esp_raw[shell_mask]

    masked = masked[np.isfinite(masked)] if not np.all(np.isfinite(masked)) else masked
    if masked.size < 32:
        masked = arr

    abs_vals = np.abs(masked)
    p90 = float(np.percentile(abs_vals, 90))
    p95 = float(np.percentile(abs_vals, 95))
    p98 = float(np.percentile(abs_vals, 98))
    p995 = float(np.percentile(abs_vals, 99.5))
    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995
    robust = float(np.clip(robust, 0.02, 0.18))
    nice = _nice_symmetric_limit(robust)

    return {
        "range_au": nice,
        "range_kcal": nice * HARTREE_TO_KCAL,
        "stats": {
            "n": int(masked.size),
            "min_au": float(np.min(masked)),
            "max_au": float(np.max(masked)),
            "mean_au": float(np.mean(masked)),
            "std_au": float(np.std(masked)),
            "p90_abs_au": p90,
            "p95_abs_au": p95,
            "p98_abs_au": p98,
            "p995_abs_au": p995,
        },
        "strategy": "robust_surface_shell_percentile",
    }
def _compute_esp_auto_range_from_cube_files(
    esp_cube_path: Union[str, Path],
    density_cube_path: Optional[Union[str, Path]] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    try:
        esp_values = _parse_cube_values(esp_cube_path)
    except Exception:
        esp_values = np.array([], dtype=float)
    density_values = None
    if density_cube_path:
        try:
            density_values = _parse_cube_values(density_cube_path)
        except Exception:
            density_values = None
    return _compute_esp_auto_range(esp_values, density_values=density_values, density_iso=density_iso)

def _formula_from_symbols(symbols: Sequence[str]) -> str:
    counts = Counter(symbols)
    if not counts:
        return ""
    ordered: List[Tuple[str, int]] = []
    if "C" in counts:
        ordered.append(("C", counts.pop("C")))
    if "H" in counts:
        ordered.append(("H", counts.pop("H")))
    for key in sorted(counts):
        ordered.append((key, counts[key]))
    return "".join(f"{el}{n if n != 1 else ''}" for el, n in ordered)

def _guess_bonds(mol: gto.Mole) -> List[Dict[str, Any]]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds: List[Dict[str, Any]] = []
    for i in range(mol.natm):
        for j in range(i + 1, mol.natm):
            ri = _COVALENT_RADII.get(symbols[i], 0.77)
            rj = _COVALENT_RADII.get(symbols[j], 0.77)
            cutoff = 1.25 * (ri + rj)
            dist = float(np.linalg.norm(coords[i] - coords[j]))
            if 0.1 < dist <= cutoff:
                bonds.append(
                    {
                        "a": i,
                        "b": j,
                        "order": 1,
                        "length_angstrom": dist,
                    }
                )
    return bonds

def _normalize_partial_charges(mol: gto.Mole, charges: Optional[Sequence[float]]) -> List[Dict[str, Any]]:
    if charges is None:
        return []
    out: List[Dict[str, Any]] = []
    for i, q in enumerate(charges):
        out.append(
            {
                "atom_index": i,
                "symbol": mol.atom_symbol(i),
                "charge": float(q),
            }
        )
    return out

def _geometry_summary(mol: gto.Mole, bonds: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    centroid = coords.mean(axis=0) if len(coords) else np.zeros(3)
    bbox_min = coords.min(axis=0) if len(coords) else np.zeros(3)
    bbox_max = coords.max(axis=0) if len(coords) else np.zeros(3)
    dims = bbox_max - bbox_min
    bond_lengths = [float(b["length_angstrom"]) for b in (bonds or []) if "length_angstrom" in b]
    return {
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "centroid_angstrom": [float(x) for x in centroid],
        "bbox_min_angstrom": [float(x) for x in bbox_min],
        "bbox_max_angstrom": [float(x) for x in bbox_max],
        "bbox_size_angstrom": [float(x) for x in dims],
        "bond_count": int(len(bonds or [])),
        "bond_length_min_angstrom": float(min(bond_lengths)) if bond_lengths else None,
        "bond_length_max_angstrom": float(max(bond_lengths)) if bond_lengths else None,
        "bond_length_mean_angstrom": float(np.mean(bond_lengths)) if bond_lengths else None,
    }

def _extract_dipole(mf) -> Optional[Dict[str, Any]]:
    try:
        vec = np.asarray(mf.dip_moment(unit="Debye", verbose=0), dtype=float).ravel()
        if vec.size >= 3:
            return {
                "x": float(vec[0]),
                "y": float(vec[1]),
                "z": float(vec[2]),
                "magnitude": float(np.linalg.norm(vec[:3])),
                "unit": "Debye",
            }
    except Exception:
        return None
    return None

def _extract_mulliken_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, 'mol', None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]
            
        s = getattr(mf, 'get_ovlp', lambda: active_mol.intor_symmetric("int1e_ovlp"))()

        try:
            _, chg = mf.mulliken_pop(mol=active_mol, dm=dm, s=s, verbose=0)
        except TypeError:
            _, chg = mf.mulliken_pop(active_mol, dm, s, verbose=0)
        except AttributeError:
            from pyscf.scf import hf as scf_hf
            _, chg = scf_hf.mulliken_pop(active_mol, dm, s=s, verbose=0)

        safe_chg = []
        for q in chg:
            if np.isnan(q) or np.isinf(q):
                safe_chg.append(0.0)
            else:
                safe_chg.append(float(q))
                
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Mulliken population failed: {e}")
        return []

def _extract_lowdin_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, 'mol', None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]

        s = getattr(mf, 'get_ovlp', lambda: active_mol.intor_symmetric("int1e_ovlp"))()
        
        from pyscf.scf import hf as scf_hf
        try:
            _, chg = scf_hf.lowdin_pop(active_mol, dm, s=s, verbose=0)
        except Exception:
            return []

        safe_chg = []
        for q in chg:
            if np.isnan(q) or np.isinf(q):
                safe_chg.append(0.0)
            else:
                safe_chg.append(float(q))
                
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Löwdin population failed: {e}")
        return []

def _restricted_or_unrestricted_arrays(mf):
    mo_energy = mf.mo_energy
    mo_occ = mf.mo_occ
    mo_coeff = mf.mo_coeff

    # Case 1: tuple (e.g., from some UHF implementations)
    if isinstance(mo_energy, tuple):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels

    # Case 2: list of arrays
    if isinstance(mo_energy, list) and mo_energy and isinstance(mo_energy[0], np.ndarray):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels

    # Case 3: numpy arrays — check dimensionality
    mo_energy = np.asarray(mo_energy)
    mo_occ = np.asarray(mo_occ)

    if mo_energy.ndim == 2 and mo_energy.shape[0] == 2:
        # Unrestricted: shape (2, nmo)
        mo_coeff_arr = np.asarray(mo_coeff)
        if mo_coeff_arr.ndim == 3 and mo_coeff_arr.shape[0] == 2:
            coeff_list = [mo_coeff_arr[0], mo_coeff_arr[1]]
        elif isinstance(mo_coeff, (tuple, list)) and len(mo_coeff) == 2:
            coeff_list = [np.asarray(mo_coeff[0]), np.asarray(mo_coeff[1])]
        else:
            # Fallback: use same coeff for both channels (shouldn't happen)
            coeff_list = [mo_coeff_arr, mo_coeff_arr]
        return [mo_energy[0], mo_energy[1]], [mo_occ[0], mo_occ[1]], coeff_list, ["alpha", "beta"]

    # Case 4: restricted (1D arrays)
    mo_coeff = np.asarray(mo_coeff)
    return [mo_energy], [mo_occ], [mo_coeff], ["restricted"]

def _build_orbital_items(mf, window: int = 4) -> List[Dict[str, Any]]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    items: List[Dict[str, Any]] = []
    for ch, (energies, occs, spin_label) in enumerate(zip(mo_energies, mo_occs, spin_labels)):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)
        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0:
            lo = 0
            hi = min(len(energies), 2 * window + 1)
        else:
            homo = int(occ_idx[-1])
            lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
            lo = max(0, homo - window)
            hi = min(len(energies), lumo + window + 1)
        for idx in range(lo, hi):
            occ = float(occs[idx])
            label = f"MO {idx + 1}"
            if occ_idx.size:
                homo = int(occ_idx[-1])
                lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
                if idx == homo:
                    label = "HOMO"
                elif idx < homo:
                    label = f"HOMO-{homo - idx}"
                elif idx == lumo:
                    label = "LUMO"
                elif idx > lumo:
                    label = f"LUMO+{idx - lumo}"
            items.append(
                {
                    "index": idx + 1,
                    "zero_based_index": idx,
                    "label": label,
                    "spin": spin_label,
                    "occupancy": occ,
                    "energy_hartree": float(energies[idx]),
                    "energy_ev": float(energies[idx] * HARTREE_TO_EV),
                }
            )
    items.sort(key=lambda x: (x.get("spin") != "restricted", x["zero_based_index"]))
    return items

def _resolve_orbital_selection(mf, orbital: Optional[Union[str, int]]) -> Dict[str, Any]:
    mo_energies, mo_occs, mo_coeffs, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel = 0
    spin_label = spin_labels[channel]
    energies = np.asarray(mo_energies[channel], dtype=float)
    occs = np.asarray(mo_occs[channel], dtype=float)

    occ_idx = np.where(occs > 1e-8)[0]
    vir_idx = np.where(occs <= 1e-8)[0]
    homo = int(occ_idx[-1]) if occ_idx.size else 0
    lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)

    raw = _safe_str(orbital, "HOMO").upper()
    if raw in {"", "AUTO"}:
        raw = "HOMO"

    idx = homo
    label = "HOMO"

    if isinstance(orbital, int):
        idx = max(0, min(int(orbital) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif re.fullmatch(r"\d+", raw):
        idx = max(0, min(int(raw) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif raw == "HOMO":
        idx = homo
        label = "HOMO"
    elif raw == "LUMO":
        idx = lumo
        label = "LUMO"
    else:
        m1 = re.fullmatch(r"HOMO\s*-\s*(\d+)", raw)
        m2 = re.fullmatch(r"LUMO\s*\+\s*(\d+)", raw)
        if m1:
            delta = int(m1.group(1))
            idx = max(0, homo - delta)
            label = f"HOMO-{delta}"
        elif m2:
            delta = int(m2.group(1))
            idx = min(len(energies) - 1, lumo + delta)
            label = f"LUMO+{delta}"

    return {
        "spin_channel": channel,
        "spin": spin_label,
        "index": idx + 1,
        "zero_based_index": idx,
        "label": label,
        "energy_hartree": float(energies[idx]),
        "energy_ev": float(energies[idx] * HARTREE_TO_EV),
        "occupancy": float(occs[idx]),
        "coefficient_matrix": mo_coeffs[channel],
    }

def _extract_frontier_gap(mf) -> Dict[str, Any]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel_info: List[Dict[str, Any]] = []
    best_gap = None
    best_homo = None
    best_lumo = None

    for energies, occs, spin_label in zip(mo_energies, mo_occs, spin_labels):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)

        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0 or vir_idx.size == 0:
            continue

        homo_idx = int(occ_idx[-1])
        lumo_idx = int(vir_idx[0])
        gap_ha = float(energies[lumo_idx] - energies[homo_idx])

        info = {
            "spin": spin_label,
            "homo_index": homo_idx + 1,
            "lumo_index": lumo_idx + 1,
            "homo_energy_hartree": float(energies[homo_idx]),
            "lumo_energy_hartree": float(energies[lumo_idx]),
            "homo_energy_ev": float(energies[homo_idx] * HARTREE_TO_EV),
            "lumo_energy_ev": float(energies[lumo_idx] * HARTREE_TO_EV),
            "gap_hartree": gap_ha,
            "gap_ev": gap_ha * HARTREE_TO_EV,
        }
        channel_info.append(info)

        if best_gap is None or gap_ha < best_gap:
            best_gap = gap_ha
            best_homo = info
            best_lumo = info

    out: Dict[str, Any] = {
        "frontier_channels": channel_info,
        "orbital_gap_hartree": float(best_gap) if best_gap is not None else None,
        "orbital_gap_ev": float(best_gap * HARTREE_TO_EV) if best_gap is not None else None,
    }

    if best_homo:
        out["homo_energy_hartree"] = best_homo["homo_energy_hartree"]
        out["homo_energy_ev"] = best_homo["homo_energy_ev"]
        out["homo_index"] = best_homo["homo_index"]
    if best_lumo:
        out["lumo_energy_hartree"] = best_lumo["lumo_energy_hartree"]
        out["lumo_energy_ev"] = best_lumo["lumo_energy_ev"]
        out["lumo_index"] = best_lumo["lumo_index"]
    return out

def _extract_spin_info(mf) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        ss = mf.spin_square()
        if isinstance(ss, tuple) and len(ss) >= 2:
            info["spin_square"] = float(ss[0])
            info["spin_multiplicity_estimate"] = float(ss[1])
    except Exception:
        pass
    return info

def _coalesce_density_matrix(dm) -> np.ndarray:
    if isinstance(dm, tuple):
        return np.asarray(dm[0]) + np.asarray(dm[1])
    dm_arr = np.asarray(dm)
    if dm_arr.ndim == 3 and dm_arr.shape[0] == 2:
        return dm_arr[0] + dm_arr[1]
    return dm_arr

def _selected_orbital_vector(mf, selection: Mapping[str, Any]) -> np.ndarray:
    coeff = mf.mo_coeff
    ch = int(selection.get("spin_channel", 0) or 0)
    idx = int(selection.get("zero_based_index", 0) or 0)

    if isinstance(coeff, tuple):
        coeff_mat = np.asarray(coeff[ch])
    elif isinstance(coeff, list) and coeff and isinstance(coeff[0], np.ndarray):
        coeff_mat = np.asarray(coeff[ch])
    else:
        coeff_mat = np.asarray(coeff)

    return np.asarray(coeff_mat[:, idx], dtype=float)

def _emit_progress(
    progress_callback: Optional[Callable[..., Any]],
    progress: float,
    step: str,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    if not callable(progress_callback):
        return

    payload = {
        "progress": float(progress),
        "step": _safe_str(step, "working"),
        "message": _safe_str(message, message or step),
    }
    payload.update(extra)

    try:
        progress_callback(payload)
        return
    except TypeError:
        pass
    except Exception:
        return

    try:
        progress_callback(float(progress), _safe_str(step, "working"), payload["message"])
    except Exception:
        return

def _focus_tab_for_result(result: Mapping[str, Any]) -> str:
    forced = _safe_str(result.get("advisor_focus_tab") or result.get("focus_tab") or result.get("default_tab"))
    forced = forced.lower()
    if forced in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
        return forced

    vis = result.get("visualization") or {}
    if vis.get("esp_cube_b64") and vis.get("density_cube_b64"):
        return "esp"
    if vis.get("orbital_cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"

def _attach_visualization_payload(
    result: Dict[str, Any],
    xyz_text: str,
    orbital_cube_path: Optional[Union[str, Path]] = None,
    density_cube_path: Optional[Union[str, Path]] = None,
    esp_cube_path: Optional[Union[str, Path]] = None,
    orbital_meta: Optional[Mapping[str, Any]] = None,
    esp_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    vis = result.setdefault("visualization", {})
    vis["xyz"] = xyz_text
    vis["molecule_xyz"] = xyz_text
    result["xyz"] = result.get("xyz") or xyz_text

    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)

    if orbital_cube_path:
        orb_b64 = _file_to_b64(orbital_cube_path)
        if orb_b64:
            vis["orbital_cube_b64"] = orb_b64
            result["orbital_cube_b64"] = orb_b64
            orb_node = vis.setdefault("orbital", {})
            orb_node["cube_b64"] = orb_b64
            if orbital_meta:
                orb_node.update(dict(orbital_meta))
                if orbital_meta.get("label"):
                    defaults.setdefault("orbital_label", orbital_meta.get("label"))
                if orbital_meta.get("index") is not None:
                    defaults.setdefault("orbital_index", orbital_meta.get("index"))

    if density_cube_path:
        dens_b64 = _file_to_b64(density_cube_path)
        if dens_b64:
            vis["density_cube_b64"] = dens_b64
            result["density_cube_b64"] = dens_b64
            dens_node = vis.setdefault("density", {})
            dens_node["cube_b64"] = dens_b64

    if esp_cube_path:
        esp_b64 = _file_to_b64(esp_cube_path)
        if esp_b64:
            vis["esp_cube_b64"] = esp_b64
            result["esp_cube_b64"] = esp_b64
            esp_node = vis.setdefault("esp", {})
            esp_node["cube_b64"] = esp_b64

            if esp_meta:
                esp_node.update(dict(esp_meta))
                preset = _normalize_esp_preset(esp_meta.get("preset"))
                preset_meta = ESP_PRESETS_DATA.get(preset, ESP_PRESETS_DATA["acs"])
                esp_node["preset"] = preset
                esp_node["surface_scheme"] = preset_meta.get("surface_scheme", "rwb")

                defaults.setdefault("esp_preset", preset)
                defaults.setdefault("esp_scheme", preset_meta.get("surface_scheme", "rwb"))
                if esp_meta.get("range_au") is not None:
                    defaults["esp_range"] = float(esp_meta["range_au"])
                    defaults["esp_range_au"] = float(esp_meta["range_au"])
                if esp_meta.get("range_kcal") is not None:
                    defaults["esp_range_kcal"] = float(esp_meta["range_kcal"])
                if esp_meta.get("density_iso") is not None:
                    defaults["esp_density_iso"] = float(esp_meta["density_iso"])
                if esp_meta.get("opacity") is not None:
                    defaults["esp_opacity"] = float(esp_meta["opacity"])

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64")),
        "esp": bool(vis.get("esp_cube_b64") and vis.get("density_cube_b64")),
        "density": bool(vis.get("density_cube_b64")),
    }
    defaults.setdefault("focus_tab", _focus_tab_for_result(result))
    return result

def _finalize_result_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(result or {})
    out.setdefault("success", True)
    out.setdefault("warnings", [])
    out["warnings"] = _dedupe_strings(out.get("warnings", []))

    if not isinstance(out.get("events"), list):
        out["events"] = []

    out["method"] = _normalize_method_name(out.get("method") or DEFAULT_METHOD)
    out["basis"] = _normalize_basis_name(out.get("basis") or DEFAULT_BASIS)
    out["charge"] = int(_safe_int(out.get("charge"), 0) or 0)
    out["multiplicity"] = int(_safe_int(out.get("multiplicity"), 1) or 1)

    e_ha = _safe_float(out.get("total_energy_hartree"))
    if e_ha is not None:
        out["total_energy_hartree"] = e_ha
        out.setdefault("total_energy_ev", e_ha * HARTREE_TO_EV)
        out.setdefault("total_energy_kcal_mol", e_ha * HARTREE_TO_KCAL)

    gap_ha = _safe_float(out.get("orbital_gap_hartree"))
    gap_ev = _safe_float(out.get("orbital_gap_ev"))
    if gap_ha is None and gap_ev is not None:
        out["orbital_gap_hartree"] = gap_ev / HARTREE_TO_EV
    elif gap_ev is None and gap_ha is not None:
        out["orbital_gap_ev"] = gap_ha * HARTREE_TO_EV

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    elif out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(defaults.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_for_result(out))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis.setdefault("xyz", out.get("xyz"))
    vis.setdefault("molecule_xyz", out.get("xyz"))
    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    return out

def _make_base_result(
    *,
    job_type: str,
    structure_name: str,
    atom_text: str,
    mol: gto.Mole,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    advisor_focus_tab: Optional[str] = None,
) -> Dict[str, Any]:
    xyz_text = _mol_to_xyz(mol, comment=structure_name or "QCViz-MCP")
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds = _guess_bonds(mol)
    
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    atoms = []
    for i in range(mol.natm):
        atoms.append({
            "atom_index": i,
            "symbol": symbols[i],
            "element": symbols[i],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "z": float(coords[i, 2]),
        })

    result: Dict[str, Any] = {
        "success": True,
        "job_type": _safe_str(job_type, "analyze"),
        "structure_name": _safe_str(structure_name, "custom"),
        "structure_query": _safe_str(structure_name, "custom"),
        "atom_spec": atom_text,
        "xyz": xyz_text,
        "method": _normalize_method_name(method or DEFAULT_METHOD),
        "basis": _normalize_basis_name(basis or DEFAULT_BASIS),
        "charge": int(charge or 0),
        "multiplicity": int(multiplicity or 1),
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "atoms": atoms,
        "bonds": bonds,
        "geometry_summary": _geometry_summary(mol, bonds),
        "warnings": [],
        "events": [],
        "advisor_focus_tab": advisor_focus_tab,
        "visualization": {
            "xyz": xyz_text,
            "molecule_xyz": xyz_text,
            "defaults": {
                "style": "stick",
                "labels": False,
                "orbital_iso": 0.050,
                "orbital_opacity": 0.85,
                "esp_density_iso": 0.001,
                "esp_opacity": 0.90,
            },
        },
    }
    return _finalize_result_contract(result)

def _populate_scf_fields(
    result: Dict[str, Any],
    mol: gto.Mole,
    mf,
    *,
    include_charges: bool = True,
    include_orbitals: bool = True,
) -> Dict[str, Any]:
    result["scf_converged"] = bool(getattr(mf, "converged", False))
    result["total_energy_hartree"] = float(getattr(mf, "e_tot", np.nan))
    result["total_energy_ev"] = float(result["total_energy_hartree"] * HARTREE_TO_EV)
    result["total_energy_kcal_mol"] = float(result["total_energy_hartree"] * HARTREE_TO_KCAL)

    dip = _extract_dipole(mf)
    if dip:
        result["dipole_moment"] = dip

    result.update(_extract_frontier_gap(mf))
    result.update(_extract_spin_info(mf))

    if include_charges:
        try:
            mull_charges = _extract_mulliken_charges(mol, mf)
            if mull_charges:
                result["mulliken_charges"] = mull_charges
            
            lowdin_charges = _extract_lowdin_charges(mol, mf)
            if lowdin_charges:
                result["lowdin_charges"] = lowdin_charges
                
            if lowdin_charges:
                result["partial_charges"] = lowdin_charges
            elif mull_charges:
                result["partial_charges"] = mull_charges
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Charge analysis failed: {exc}")

    if include_orbitals:
        try:
            result["orbitals"] = _build_orbital_items(mf)
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Orbital analysis failed: {exc}")

    return result

def _prepare_structure_bundle(
    *,
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
) -> Tuple[str, str, gto.Mole]:
    structure_name, atom_text = _resolve_structure_payload(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
    )
    mol = _build_mol(
        atom_text=atom_text,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        unit="Angstrom",
    )
    return structure_name, atom_text, mol

# ----------------------------------------------------------------------------
# PUBLIC RUNNER FUNCTIONS
# ----------------------------------------------------------------------------

def run_resolve_structure(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )
    _emit_progress(progress_callback, 0.75, "geometry", "Preparing geometry payload")

    result = _make_base_result(
        job_type="resolve_structure",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    result["resolved_structure"] = {
        "name": structure_name,
        "xyz": result["xyz"],
        "atom_spec": atom_text,
    }

    _emit_progress(progress_callback, 1.0, "done", "Structure resolved")
    return _finalize_result_contract(result)

def run_geometry_analysis(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="geometry_analysis",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    _emit_progress(progress_callback, 1.0, "done", "Geometry analysis complete")
    return _finalize_result_contract(result)

def run_single_point(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="single_point",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.85, "analyze", "Collecting observables")
    _populate_scf_fields(result, mol, mf, include_charges=False, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Single-point calculation complete")
    return _finalize_result_contract(result)

def run_partial_charges(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="partial_charges",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "charges",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.80, "charges", "Computing Mulliken charges")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=False)

    _emit_progress(progress_callback, 1.0, "done", "Partial charge analysis complete")
    return _finalize_result_contract(result)

def run_orbital_preview(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="orbital_preview",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "orbital",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 0.70, "orbital_select", "Selecting orbital")
    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        with tempfile.TemporaryDirectory(prefix="qcviz_orb_") as tmpdir:
            cube_path = Path(tmpdir) / "orbital.cube"
            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=cube_path,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Orbital cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Orbital preview complete")
    return _finalize_result_contract(result)

def run_esp_map(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="esp_map",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "esp",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    try:
        _emit_progress(progress_callback, 0.70, "cube", "Generating density/ESP cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_esp_") as tmpdir:
            density_cube = Path(tmpdir) / "density.cube"
            esp_cube = Path(tmpdir) / "esp.cube"

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )

            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"ESP cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "ESP map complete")
    result["job_type"] = "esp_map"
    return _finalize_result_contract(result)

def run_geometry_optimization(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol0 = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    # Initialize initial result for tracking warnings and initial state
    initial_result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol0,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    _emit_progress(progress_callback, 0.12, "build_scf", "Building initial SCF model")
    method_name, mf0 = _build_mean_field(mol0, method or DEFAULT_METHOD)
    
    trajectory = []

    def _geomopt_callback(envs):
        try:
            mol_current = envs.get("mol", None)
            e_current = envs.get("e_tot", None)
            grad_norm = None
            g = envs.get("gradients", None)
            if g is not None:
                import numpy as np
                grad_norm = float(np.linalg.norm(g))

            step_num = len(trajectory) + 1
            xyz_string = _mol_to_xyz(mol_current, comment=f"Step {step_num}") if mol_current else None

            step_data = {
                "step": step_num,
                "energy_hartree": float(e_current) if e_current is not None else None,
                "grad_norm": grad_norm,
                "xyz": xyz_string,
            }
            trajectory.append(step_data)

            if progress_callback:
                frac = min(0.3 + (step_num / 50) * 0.55, 0.85)
                msg = f"Opt step {step_num}: E={e_current:.8f} Ha"
                if grad_norm:
                    msg += f", |grad|={grad_norm:.6f}"
                _emit_progress(progress_callback, frac, "optimize", msg)
        except Exception:
            pass

    _emit_progress(progress_callback, 0.30, "optimize", "Starting geometry optimization")
    
    opt_mol = mol0
    optimization_performed = False
    
    try:
        try:
            from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (geometric)")
            opt_mol = geometric_optimize(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
        except (ImportError, Exception) as e:
            if isinstance(e, ImportError):
                logger.info("geometric solver not found, trying berny")
            else:
                logger.warning(f"geometric solver failed: {e}, trying berny")
            
            from pyscf.geomopt.berny_solver import optimize as berny_optimize
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (berny)")
            opt_mol = berny_optimize(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
    except Exception as exc:
        logger.warning(f"Geometry optimization failed: {exc}")
        initial_result.setdefault("warnings", []).append(f"Geometry optimization failed: {exc}")
        optimization_performed = False
        # Use initial molecule if optimization failed completely
        opt_mol = mol0

    _emit_progress(progress_callback, 0.88, "final_scf", "Running final SCF on optimized geometry")
    method_name, mf = _build_mean_field(opt_mol, method or DEFAULT_METHOD)
    
    # Run final SCF on optimized geometry
    new_xyz = _mol_to_xyz(opt_mol, comment=structure_name or "QCViz-MCP")
    cache_key = _get_cache_key(new_xyz, method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    mf, _ = _run_scf_with_fallback(mf, initial_result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    final_result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=_strip_xyz_header(_mol_to_xyz(opt_mol)),
        mol=opt_mol,
        method=method_name,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    final_result["warnings"] = _dedupe_strings(initial_result.get("warnings", []))
    final_result["optimization_performed"] = optimization_performed
    final_result["optimization_steps"] = len(trajectory)
    final_result["trajectory"] = trajectory
    
    if trajectory:
        frames = [step.get("xyz").strip() for step in trajectory if step.get("xyz")]
        if frames:
            final_result["trajectory_xyz"] = "\n".join(frames) + "\n"

    final_result["initial_xyz"] = initial_result["xyz"]
    final_result["optimized_xyz"] = final_result["xyz"]

    _populate_scf_fields(final_result, opt_mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Geometry optimization complete")
    return _finalize_result_contract(final_result)

def run_analyze(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="analyze",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.12, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.30, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.55, "analysis", "Collecting quantitative results")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        _emit_progress(progress_callback, 0.72, "cube", "Generating orbital/ESP visualization cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_all_") as tmpdir:
            tmpdir_p = Path(tmpdir)
            orbital_cube = tmpdir_p / "orbital.cube"
            density_cube = tmpdir_p / "density.cube"
            esp_cube = tmpdir_p / "esp.cube"

            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(orbital_cube), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )
            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=orbital_cube,
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Visualization cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Full analysis complete")
    return _finalize_result_contract(result)

__all__ = [
    "HARTREE_TO_EV",
    "HARTREE_TO_KCAL",
    "BOHR_TO_ANGSTROM",
    "EV_TO_KCAL",
    "DEFAULT_METHOD",
    "DEFAULT_BASIS",
    "ESP_PRESETS_DATA",
    "run_resolve_structure",
    "run_geometry_analysis",
    "run_single_point",
    "run_partial_charges",
    "run_orbital_preview",
    "run_esp_map",
    "run_geometry_optimization",
    "run_analyze",
]

```

### File: `web/routes/compute.py`
```py
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:  # pragma: no cover
    QCVizAgent = None  # type: ignore


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])


INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "analyze": "analyze",
    "full_analysis": "analyze",
    "single_point": "single_point",
    "energy": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "optimize": "geometry_optimization",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_ALIASES: Dict[str, str] = {
    "analyze": "analyze",
    "analysis": "analyze",
    "full_analysis": "analyze",
    "singlepoint": "single_point",
    "single_point": "single_point",
    "sp": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "geom": "geometry_analysis",
    "charge": "partial_charges",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "mulliken": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "mo": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "electrostatic_potential": "esp_map",
    "opt": "geometry_optimization",
    "optimize": "geometry_optimization",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "resolve": "resolve_structure",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_TO_RUNNER: Dict[str, str] = {
    "analyze": "run_analyze",
    "single_point": "run_single_point",
    "geometry_analysis": "run_geometry_analysis",
    "partial_charges": "run_partial_charges",
    "orbital_preview": "run_orbital_preview",
    "esp_map": "run_esp_map",
    "geometry_optimization": "run_geometry_optimization",
    "resolve_structure": "run_resolve_structure",
}

TERMINAL_SUCCESS = {"completed"}
TERMINAL_FAILURE = {"failed", "error"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE

DEFAULT_POLL_SECONDS = float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25"))
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "4"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "에텐": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_PAT = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|ωb97x-?d|bp86|blyp)\b",
    re.IGNORECASE,
)
_BASIS_PAT = re.compile(
    r"\b(sto-?3g|3-21g|6-31g\*\*?|6-31g\(d,p\)|6-31g\(d\)|def2-?svp|def2-?tzvp|cc-pvdz|cc-pvtz)\b",
    re.IGNORECASE,
)
_CHARGE_PAT = re.compile(r"(?:charge|전하)\s*[:=]?\s*([+-]?\d+)", re.IGNORECASE)
_MULT_PAT = re.compile(r"(?:multiplicity|spin multiplicity|다중도)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_ORBITAL_PAT = re.compile(
    r"\b(homo(?:\s*-\s*\d+)?|lumo(?:\s*\+\s*\d+)?|mo\s*\d+|orbital\s*\d+)\b",
    re.IGNORECASE,
)
_ESP_PRESET_PAT = re.compile(
    r"\b(acs|rsc|nature|spectral|inferno|viridis|rwb|bwr|greyscale|grayscale|high[_ -]?contrast)\b",
    re.IGNORECASE,
)


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _public_plan_dict(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    return {
        "intent": out.get("intent"),
        "confidence": out.get("confidence"),
        "provider": out.get("provider"),
        "notes": out.get("notes"),
        "job_type": out.get("job_type"),
        "structure_query": out.get("structure_query"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
    }


def _normalize_text_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s가-힣+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "user_message", "text", "prompt", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_session_id(payload: Mapping[str, Any]) -> str:
    for key in ("session_id", "conversation_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_job_type(job_type: Optional[str], intent: Optional[str] = None) -> str:
    jt = _normalize_text_token(job_type).replace(" ", "_")
    if jt in JOB_TYPE_ALIASES:
        return JOB_TYPE_ALIASES[jt]
    intent_key = _normalize_text_token(intent).replace(" ", "_")
    if intent_key in INTENT_TO_JOB_TYPE:
        return INTENT_TO_JOB_TYPE[intent_key]
    return "analyze"


def _normalize_esp_preset(preset: Optional[str]) -> str:
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    if token == "grayscale":
        token = "greyscale"
    if token == "high-contrast":
        token = "high_contrast"
    if token in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}):
        return token
    for key, meta in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}).items():
        aliases = [_normalize_text_token(x).replace(" ", "_") for x in meta.get("aliases", [])]
        if token == key or token in aliases:
            return key
    return "acs"


def _extract_xyz_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    raw = str(text).strip()

    fence = re.search(r"```(?:xyz)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fence:
        block = fence.group(1).strip()
        if block:
            return block

    if "\n" not in raw:
        return None

    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None

    atom_line = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
    if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 3:
        candidate = "\n".join(lines)
        body = lines[2:]
        if body and all(atom_line.match(x.strip()) for x in body):
            return candidate

    atom_lines = [ln for ln in lines if atom_line.match(ln.strip())]
    if len(atom_lines) >= 1 and len(atom_lines) == len(lines):
        return "\n".join(lines)

    return None


def _iter_runner_structure_names() -> Iterable[str]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = getattr(pyscf_runner, name, None)
        if isinstance(lib, Mapping):
            for key in lib.keys():
                s = _safe_str(key)
                if s and s not in seen:
                    seen.add(s)
                    yield s


def _fallback_extract_structure_query(message: str) -> Optional[str]:
    if not message:
        return None
    if _extract_xyz_block(message):
        return None

    normalized = _normalize_text_token(message)

    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in normalized:
            return en_name

    structure_names = list(_iter_runner_structure_names())
    for name in sorted(structure_names, key=len, reverse=True):
        if _normalize_text_token(name) in normalized:
            return name

    patterns = [
        r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})",
        r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})\s+(?:molecule|structure|system)",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
        r"(?i)(?:analyze|show|render|preview|compute|optimize|calculate)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if not m:
            continue
        candidate = _safe_str(m.group(1)).strip()
        
        noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for", "보여줘", "해줘", "계산"]
        for n in noise:
            candidate = re.sub(rf"\b{n}\b", " ", candidate, flags=re.I)
            
        # strip korean postpositions
        for n in ["에 대한", "에대한", "이온쌍", "의", "분자", "구조", "계산", "해줘", "보여줘"]:
            if candidate.endswith(n):
                candidate = candidate[:-len(n)].strip()
                
        candidate = re.sub(r"\s+", " ", candidate).strip()
        
        if not candidate:
            continue

        candidate_norm = _normalize_text_token(candidate)
        if candidate_norm in _KO_STRUCTURE_ALIASES:
            return _KO_STRUCTURE_ALIASES[candidate_norm]
        for name in structure_names:
            if _normalize_text_token(name) == candidate_norm:
                return name
        return candidate

    return None


def _heuristic_plan(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    text = message or _extract_message(payload)

    normalized = _normalize_text_token(text)

    intent = "analyze"
    focus = "summary"

    if re.search(r"\b(homo|lumo|orbital|mo)\b|오비탈", normalized, re.IGNORECASE):
        intent = "orbital"
        focus = "orbital"
    elif re.search(r"\b(esp|electrostatic)\b|정전기|전위", normalized, re.IGNORECASE):
        intent = "esp"
        focus = "esp"
    elif re.search(r"\b(charge|charges|mulliken)\b|전하", normalized, re.IGNORECASE):
        intent = "charges"
        focus = "charges"
    elif re.search(r"\b(opt|optimize|optimization)\b|최적화", normalized, re.IGNORECASE):
        intent = "optimization"
        focus = "geometry"
    elif re.search(r"\b(geometry|bond|angle|dihedral)\b|구조|결합", normalized, re.IGNORECASE):
        intent = "geometry"
        focus = "geometry"
    elif re.search(r"\b(energy|single point|singlepoint)\b|에너지", normalized, re.IGNORECASE):
        intent = "single_point"
        focus = "summary"

    method = None
    basis = None
    charge = None
    multiplicity = None
    orbital = None
    esp_preset = None

    m_method = _METHOD_PAT.search(text)
    if m_method:
        method = m_method.group(1)

    m_basis = _BASIS_PAT.search(text)
    if m_basis:
        basis = m_basis.group(1)

    m_charge = _CHARGE_PAT.search(text)
    if m_charge:
        charge = _safe_int(m_charge.group(1))

    m_mult = _MULT_PAT.search(text)
    if m_mult:
        multiplicity = _safe_int(m_mult.group(1))

    m_orb = _ORBITAL_PAT.search(text)
    if m_orb:
        orbital = m_orb.group(1).upper().replace(" ", "")

    m_preset = _ESP_PRESET_PAT.search(text)
    if m_preset:
        esp_preset = _normalize_esp_preset(m_preset.group(1))

    structure_query = _fallback_extract_structure_query(text)

    job_type = _normalize_job_type(payload.get("job_type"), intent)

    return {
        "intent": intent,
        "confidence": 0.55,
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "structure_query": structure_query,
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
    }


@lru_cache(maxsize=1)
def get_qcviz_agent():
    if QCVizAgent is None:
        return None
    try:
        return QCVizAgent()
    except Exception as exc:  # pragma: no cover
        logger.warning("QCVizAgent initialization failed: %s", exc)
        return None


def _coerce_plan_to_dict(plan_obj: Any) -> Dict[str, Any]:
    if plan_obj is None:
        return {}
    if isinstance(plan_obj, Mapping):
        return dict(plan_obj)

    out: Dict[str, Any] = {}
    for key in (
        "intent",
        "confidence",
        "provider",
        "notes",
        "job_type",
        "structure_query",
        "method",
        "basis",
        "charge",
        "multiplicity",
        "orbital",
        "esp_preset",
        "advisor_focus_tab",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out


def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}

    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan_message") and callable(agent.plan_message):
                return _coerce_plan_to_dict(agent.plan_message(message, payload=payload))
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message, payload=payload))
        except TypeError:
            try:
                if hasattr(agent, "plan_message") and callable(agent.plan_message):
                    return _coerce_plan_to_dict(agent.plan_message(message))
                if hasattr(agent, "plan") and callable(agent.plan):
                    return _coerce_plan_to_dict(agent.plan(message))
            except Exception as exc:
                logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)
        except Exception as exc:
            logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)

    return _heuristic_plan(message, payload=payload)


def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})

    intent = _safe_str(plan.get("intent"))
    if not out.get("job_type"):
        out["job_type"] = _normalize_job_type(plan.get("job_type"), intent)

    for key in ("method", "basis", "orbital", "advisor_focus_tab"):
        if not out.get(key) and plan.get(key):
            out[key] = plan.get(key)

    for key in ("charge", "multiplicity"):
        if out.get(key) is None and plan.get(key) is not None:
            out[key] = plan.get(key)

    if not out.get("esp_preset") and plan.get("esp_preset"):
        out["esp_preset"] = _normalize_esp_preset(plan.get("esp_preset"))

    if not out.get("structure_query") and plan.get("structure_query"):
        out["structure_query"] = plan.get("structure_query")

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    if not out.get("structure_query") and not out.get("xyz") and not out.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message or _extract_message(out))
        if fallback:
            out["structure_query"] = fallback

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    return out


def _focus_tab_from_result(result: Mapping[str, Any]) -> str:
    for key in ("advisor_focus_tab", "focus_tab", "default_tab"):
        value = _safe_str(result.get(key))
        if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
            return value
    vis = result.get("visualization") or {}
    if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
        vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
    ):
        return "esp"
    if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"


def _normalize_result_contract(result: Any, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(payload or {})

    if isinstance(result, Mapping):
        out = dict(result)
    else:
        out = {"success": True, "result": _json_safe(result)}

    out.setdefault("success", True)
    out.setdefault("job_type", _normalize_job_type(payload.get("job_type"), payload.get("planner_intent")))
    out.setdefault("structure_query", payload.get("structure_query"))
    out.setdefault("structure_name", payload.get("structure_query") or payload.get("structure_name"))
    out.setdefault("method", payload.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"))
    out.setdefault("basis", payload.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"))
    out.setdefault("charge", _safe_int(payload.get("charge"), 0) or 0)
    out.setdefault("multiplicity", _safe_int(payload.get("multiplicity"), 1) or 1)

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    if out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(out.get("esp_preset") or payload.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_from_result(out))

    if out.get("xyz"):
        vis.setdefault("xyz", out.get("xyz"))
        vis.setdefault("molecule_xyz", out.get("xyz"))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    warnings = out.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [warnings]
    out["warnings"] = [_safe_str(x) for x in warnings if _safe_str(x)]

    if out.get("orbital_gap_hartree") is None and out.get("orbital_gap_ev") is not None:
        try:
            out["orbital_gap_hartree"] = float(out["orbital_gap_ev"]) / float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass
    if out.get("orbital_gap_ev") is None and out.get("orbital_gap_hartree") is not None:
        try:
            out["orbital_gap_ev"] = float(out["orbital_gap_hartree"]) * float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass

    out["advisor_focus_tab"] = _focus_tab_from_result(out)
    out["default_tab"] = out["advisor_focus_tab"]
    return _json_safe(out)


def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    data["job_type"] = _normalize_job_type(data.get("job_type"), data.get("planner_intent"))
    data["method"] = _safe_str(
        data.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
    )
    data["basis"] = _safe_str(
        data.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
    )
    data["charge"] = _safe_int(data.get("charge"), 0) or 0
    data["multiplicity"] = _safe_int(data.get("multiplicity"), 1) or 1

    if data.get("esp_preset"):
        data["esp_preset"] = _normalize_esp_preset(data.get("esp_preset"))

    if not data.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message)
        if xyz_block:
            data["xyz"] = xyz_block

    if not data.get("structure_query") and not data.get("xyz") and not data.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message)
        if fallback:
            data["structure_query"] = fallback

    if data["job_type"] not in {"resolve_structure"}:
        if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec")):
            raise HTTPException(
                status_code=400,
                detail="Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text."
            )

    return data


def _build_kwargs_for_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    sig = inspect.signature(func)
    kwargs: Dict[str, Any] = {}

    candidate_map = {
        "structure_query": payload.get("structure_query") or payload.get("query"),
        "xyz": payload.get("xyz"),
        "atom_spec": payload.get("atom_spec"),
        "method": payload.get("method"),
        "basis": payload.get("basis"),
        "charge": payload.get("charge"),
        "multiplicity": payload.get("multiplicity"),
        "orbital": payload.get("orbital"),
        "esp_preset": payload.get("esp_preset"),
        "advisor_focus_tab": payload.get("advisor_focus_tab"),
        "user_message": _extract_message(payload),
        "message": _extract_message(payload),
        "progress_callback": progress_callback,
    }

    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

    for name, param in sig.parameters.items():
        if name in candidate_map and candidate_map[name] is not None:
            kwargs[name] = candidate_map[name]

    if accepts_var_kw:
        for key, value in payload.items():
            if key not in kwargs and value is not None:
                kwargs[key] = value
        if progress_callback is not None and "progress_callback" not in kwargs:
            kwargs["progress_callback"] = progress_callback

    return kwargs


def _invoke_callable_adaptive_sync(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Any:
    kwargs = _build_kwargs_for_callable(func, payload, progress_callback=progress_callback)
    return func(**kwargs)


def _run_direct_compute(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    prepared = _prepare_payload(payload)
    job_type = _normalize_job_type(prepared.get("job_type"), prepared.get("planner_intent"))
    runner_name = JOB_TYPE_TO_RUNNER.get(job_type)
    if not runner_name:
        raise HTTPException(status_code=400, detail=f"Unsupported job_type: {job_type}")

    runner = getattr(pyscf_runner, runner_name, None)
    if not callable(runner):
        raise RuntimeError(f"Runner not available: {runner_name}")

    result = _invoke_callable_adaptive_sync(runner, prepared, progress_callback=progress_callback)
    return _normalize_result_contract(result, prepared)


@dataclass
class JobRecord:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    step: str = "queued"
    message: str = "Queued"
    user_query: str = ""
    created_at: float = field(default_factory=_now_ts)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    updated_at: float = field(default_factory=_now_ts)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    future: Optional[Future] = None
    event_seq: int = 0


import json
import os

class InMemoryJobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        self.cache_file = os.path.join(os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache"), "job_history.json")
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", max_workers)
        self._load_from_disk()

    def _save_to_disk(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                dump_data = {}
                for k, v in self.jobs.items():
                    dump_data[k] = {
                        "job_id": v.job_id,
                        "status": v.status,
                        "user_query": v.user_query,
                        "payload": v.payload,
                        "progress": v.progress,
                        "step": v.step,
                        "message": v.message,
                        "created_at": v.created_at,
                        "started_at": v.started_at,
                        "ended_at": v.ended_at,
                        "error": v.error,
                        "result": v.result,
                        "events": v.events,
                    }
                json.dump(dump_data, f)
        except Exception as e:
            logger.warning(f"Failed to save job history: {e}")

    def _load_from_disk(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    rec = JobRecord(job_id=v["job_id"], user_query=v["user_query"], payload=v["payload"])
                    rec.status = v["status"]
                    rec.progress = v["progress"]
                    rec.step = v["step"]
                    rec.message = v["message"]
                    rec.created_at = v["created_at"]
                    rec.started_at = v["started_at"]
                    rec.ended_at = v["ended_at"]
                    rec.error = v.get("error")
                    rec.result = v.get("result")
                    rec.events = v.get("events", [])
                    self.jobs[k] = rec
        except Exception as e:
            logger.warning(f"Failed to load job history: {e}")

    def _prune(self) -> None:
        with self.lock:
            if len(self.jobs) <= MAX_JOBS:
                return
            ordered = sorted(self.jobs.values(), key=lambda x: x.created_at)
            removable = [j.job_id for j in ordered if j.status in TERMINAL_STATES]
            while len(self.jobs) > MAX_JOBS and removable:
                jid = removable.pop(0)
                self.jobs.pop(jid, None)

    def _append_event(self, job: JobRecord, event_type: str, message: str, data: Optional[Mapping[str, Any]] = None) -> None:
        job.event_seq += 1
        event = {
            "event_id": job.event_seq,
            "ts": _now_ts(),
            "type": _safe_str(event_type),
            "message": _safe_str(message),
            "data": _json_safe(dict(data or {})),
        }
        job.events.append(event)
        if len(job.events) > MAX_JOB_EVENTS:
            job.events = job.events[-MAX_JOB_EVENTS:]

    def _snapshot(
        self,
        job: JobRecord,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Dict[str, Any]:
        snap = {
            "job_id": job.job_id,
            "status": job.status,
            "user_query": job.user_query,
            "molecule_name": job.payload.get("structure_query", ""),
            "method": job.payload.get("method", ""),
            "basis_set": job.payload.get("basis", ""),
            "progress": float(job.progress),
            "step": job.step,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "updated_at": job.updated_at,
        }
        if include_payload:
            snap["payload"] = _json_safe(job.payload)
        if include_result:
            snap["result"] = _json_safe(job.result)
            snap["error"] = _json_safe(job.error)
        if include_events:
            snap["events"] = _json_safe(job.events)
        return snap

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = dict(payload or {})
        job_id = uuid.uuid4().hex
        user_message = _extract_message(prepared)
        record = JobRecord(job_id=job_id, payload=prepared, user_query=user_message)

        with self.lock:
            self.jobs[job_id] = record
            self._append_event(record, "job_submitted", "Job submitted", {"job_type": prepared.get("job_type")})
            record.future = self.executor.submit(self._run_job, job_id)

        self._prune()
        return self._snapshot(record, include_payload=False, include_result=False, include_events=False)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = _now_ts()
            job.updated_at = job.started_at
            job.step = "starting"
            job.message = "Starting job"
            self._append_event(job, "job_started", "Job started")

        def progress_callback(*args: Any, **kwargs: Any) -> None:
            payload: Dict[str, Any] = {}
            if args and isinstance(args[0], Mapping):
                payload.update(dict(args[0]))
            else:
                if len(args) >= 1:
                    payload["progress"] = args[0]
                if len(args) >= 2:
                    payload["step"] = args[1]
                if len(args) >= 3:
                    payload["message"] = args[2]
            payload.update(kwargs)

            with self.lock:
                record = self.jobs[job_id]
                record.progress = max(0.0, min(1.0, float(_safe_float(payload.get("progress"), record.progress) or 0.0)))
                record.step = _safe_str(payload.get("step"), record.step or "running")
                record.message = _safe_str(payload.get("message"), record.message or record.step or "Running")
                record.updated_at = _now_ts()
                self._append_event(
                    record,
                    "job_progress",
                    record.message,
                    {
                        "progress": record.progress,
                        "step": record.step,
                    },
                )

        try:
            result = _run_direct_compute(job.payload, progress_callback=progress_callback)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "completed"
                job.progress = 1.0
                job.step = "done"
                job.message = "Completed"
                job.result = result
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_completed", "Job completed")
        except HTTPException as exc:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = _safe_str(exc.detail, "Request failed")
                job.error = {
                    "message": _safe_str(exc.detail, "Request failed"),
                    "status_code": exc.status_code,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)
        except Exception as exc:
            logger.exception("Direct compute failed for job %s", job_id)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = str(exc)
                job.error = {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)

    def get(
        self,
        job_id: str,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot(
                job,
                include_payload=include_payload,
                include_result=include_result,
                include_events=include_events,
            )

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [
                self._snapshot(
                    job,
                    include_payload=include_payload,
                    include_result=include_result,
                    include_events=include_events,
                )
                for job in jobs
            ]

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status not in TERMINAL_STATES:
                raise HTTPException(status_code=409, detail="Cannot delete a running job.")
            self.jobs.pop(job_id, None)
            return True

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = _now_ts() + timeout if timeout else None
        while True:
            snap = self.get(job_id, include_payload=False, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in TERMINAL_STATES:
                return snap
            if deadline is not None and _now_ts() >= deadline:
                return snap
            time.sleep(DEFAULT_POLL_SECONDS)


JOB_MANAGER = InMemoryJobManager(max_workers=MAX_WORKERS)


def get_job_manager() -> InMemoryJobManager:
    return JOB_MANAGER


@router.get("/health")
def compute_health() -> Dict[str, Any]:
    agent = get_qcviz_agent()
    provider = None
    if agent is not None:
        provider = getattr(agent, "provider", None) or getattr(agent, "resolved_provider", None)

    return {
        "ok": True,
        "route": "/compute",
        "planner_provider": provider or "heuristic",
        "job_count": len(JOB_MANAGER.list()),
        "max_workers": MAX_WORKERS,
        "timestamp": _now_ts(),
    }


@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    should_wait = bool(sync or wait or wait_for_result or body.get("sync") or body.get("wait") or body.get("wait_for_result"))

    snapshot = JOB_MANAGER.submit(body)

    if should_wait:
        terminal = JOB_MANAGER.wait(snapshot["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return terminal

    return snapshot


@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    items = JOB_MANAGER.list(
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
    )
    return {
        "items": items,
        "count": len(items),
    }

@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(
        job_id,
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
    )
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return snap


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_result=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "result": snap.get("result"),
        "error": snap.get("error"),
    }


@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_events=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "events": snap.get("events", []),
    }


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    ok = JOB_MANAGER.delete(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True, "job_id": job_id}


__all__ = [
    "router",
    "JOB_MANAGER",
    "get_job_manager",
    "_extract_message",
    "_extract_session_id",
    "_fallback_extract_structure_query",
    "_merge_plan_into_payload",
    "_normalize_result_contract",
    "_prepare_payload",
    "_public_plan_dict",
    "_safe_plan_message",
]
```

### File: `llm/agent.py`
```py
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "analyze",
                "single_point",
                "geometry_analysis",
                "partial_charges",
                "orbital_preview",
                "esp_map",
                "geometry_optimization",
                "resolve_structure",
            ],
        },
        "structure_query": {"type": "string"},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb",
                "bwr",
                "viridis",
                "inferno",
                "spectral",
                "nature",
                "acs",
                "rsc",
                "greyscale",
                "high_contrast",
                "grey",
                "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbitals", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["intent"],
    "additionalProperties": True,
}


INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbitals"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}


SYSTEM_PROMPT = """
You are QCViz Planner, a planning agent for a quantum chemistry web app.

Your job:
- Read the user's natural-language request.
- Infer the best computation intent.
- Extract structure_query, method, basis, charge, multiplicity, orbital, and esp_preset when explicit.
- Choose the best focus_tab for the frontend.
- Return ONLY arguments for the planning function / JSON object.

Intent rules:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

Extraction rules:
- structure_query should be the molecule/material/system name or pasted geometry string.
- focus_tab should be:
  - orbitals for orbital_preview
  - esp for esp_map
  - charges for partial_charges
  - geometry for geometry_analysis or geometry_optimization
  - summary otherwise
- confidence should be 0.0 to 1.0
- notes can explain ambiguous choices briefly.

If the structure is unclear, still return the best intent and leave structure_query empty.
""".strip()


@dataclass
class AgentPlan:
    intent: str = "analyze"
    structure_query: Optional[str] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    tool_name: str = "run_analyze"
    notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data


class QCVizAgent:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.0-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0}, provider="heuristic")

        chosen = self._choose_provider()
        if chosen == "openai":
            try:
                return self._plan_with_openai(text, context=context or {})
            except Exception:
                pass

        if chosen == "gemini":
            try:
                return self._plan_with_gemini(text, context=context or {})
            except Exception:
                pass

        if chosen == "auto":
            if self.openai_api_key:
                try:
                    return self._plan_with_openai(text, context=context or {})
                except Exception:
                    pass
            if self.gemini_api_key:
                try:
                    return self._plan_with_gemini(text, context=context or {})
                except Exception:
                    pass

        return self._heuristic_plan(text, context=context or {})

    def _choose_provider(self) -> str:
        if self.provider in {"openai", "gemini", "none"}:
            return self.provider
        return "auto"

    def _plan_with_openai(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        from openai import OpenAI

        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=self.openai_api_key)
        user_prompt = self._compose_user_prompt(message, context=context)

        resp = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "plan_quantum_request",
                        "description": "Plan a user request into a QCViz compute intent.",
                        "parameters": PLAN_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "plan_quantum_request"}},
        )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        data: Dict[str, Any]

        if tool_calls:
            args = tool_calls[0].function.arguments or "{}"
            data = json.loads(args)
        else:
            content = self._message_content_to_text(getattr(msg, "content", ""))
            data = self._extract_json_dict(content)

        return self._coerce_plan(data, provider="openai")

    def _plan_with_gemini(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        user_prompt = self._compose_user_prompt(message, context=context)

        # new google-genai
        try:
            from google import genai  # type: ignore

            if not self.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "user", "parts": [{"text": user_prompt}]},
                ],
                config={
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(resp, "text", None) or self._message_content_to_text(resp)
            data = self._extract_json_dict(text)
            return self._coerce_plan(data, provider="gemini")
        except ImportError:
            pass

        # older google-generativeai
        import google.generativeai as genai  # type: ignore

        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel(self.gemini_model)
        resp = model.generate_content(
            f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            generation_config={"response_mime_type": "application/json", "temperature": 0},
        )
        text = getattr(resp, "text", None) or self._message_content_to_text(resp)
        data = self._extract_json_dict(text)
        return self._coerce_plan(data, provider="gemini")

    def _compose_user_prompt(self, message: str, context: Dict[str, Any]) -> str:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return f"Context:\n{context_json}\n\nUser message:\n{message}"

    def _heuristic_plan(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        text = message.strip()
        lower = text.lower()

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = []

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy"]):
            intent = "single_point"
            confidence = 0.82

        structure_query = self._extract_structure_query(text)
        method = self._extract_method(text)
        basis = self._extract_basis(text)
        charge = self._extract_charge(text)
        multiplicity = self._extract_multiplicity(text)
        orbital = self._extract_orbital(text)
        esp_preset = self._extract_esp_preset(text)

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        data = {
            "intent": intent,
            "structure_query": structure_query,
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "orbital": orbital,
            "esp_preset": esp_preset,
            "confidence": confidence,
            "notes": notes,
        }
        return self._coerce_plan(data, provider="heuristic")

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structure_query = self._none_if_blank(data.get("structure_query"))
        method = self._none_if_blank(data.get("method"))
        basis = self._none_if_blank(data.get("basis"))
        orbital = self._none_if_blank(data.get("orbital"))
        esp_preset = self._normalize_preset(self._none_if_blank(data.get("esp_preset")))
        focus_tab = str(data.get("focus_tab") or defaults["focus_tab"]).strip()
        tool_name = str(data.get("tool_name") or defaults["tool_name"]).strip()

        charge = self._safe_int(data.get("charge"))
        multiplicity = self._safe_int(data.get("multiplicity"))
        confidence = self._safe_float(data.get("confidence"), 0.0)
        confidence = max(0.0, min(1.0, confidence))

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]

        return AgentPlan(
            intent=intent,
            structure_query=structure_query,
            method=method,
            basis=basis,
            charge=charge,
            multiplicity=multiplicity,
            orbital=orbital,
            esp_preset=esp_preset,
            focus_tab=focus_tab,
            confidence=confidence,
            tool_name=tool_name,
            notes=[str(x) for x in notes if str(x).strip()],
            provider=provider,
            raw=data,
        )

    def _extract_structure_query(self, text: str) -> Optional[str]:
        # pasted xyz block
        if len(re.findall(r"\n", text)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", text, re.M):
            return text.strip()

        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        if quoted:
            first = quoted[0][0] or quoted[0][1]
            if first.strip():
                return first.strip()

        patterns = [
            r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})",
            r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})\s+(?:molecule|structure|system)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
            r"(?i)(?:analyze|compute|calculate|show|render|visualize|optimize)\s+(?:the\s+)?([A-Za-z0-9_\-\+\(\), ]{2,80})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                candidate = m.group(1).strip(" .,:;")
                candidate = re.split(
                    r"\b(using|with|at|in|and show|and render|method|basis|charge|multiplicity|spin|preset)\b",
                    candidate,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip(" .,:;")
                
                # Filter out korean noise words
                for noise in ["의", "에 대한", "에대한", "분자", "구조", "계산", "해줘", "보여줘"]:
                    if candidate.endswith(noise):
                        candidate = candidate[:-len(noise)].strip(" .,:;")
                        
                if candidate and len(candidate) >= 2:
                    return candidate

        common = [
            "water",
            "methane",
            "ammonia",
            "benzene",
            "ethanol",
            "acetone",
            "formaldehyde",
            "carbon dioxide",
            "co2",
            "nh3",
            "h2o",
            "caffeine",
            "naphthalene",
            "pyridine",
            "phenol",
        ]
        lower = text.lower()
        for name in common:
            if name in lower:
                return name

        return None

    def _extract_method(self, text: str) -> Optional[str]:
        methods = [
            "HF",
            "B3LYP",
            "PBE",
            "PBE0",
            "M06-2X",
            "M062X",
            "wB97X-D",
            "WB97X-D",
            "CAM-B3LYP",
            "TPSSh",
            "BP86",
        ]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g",
            "3-21g",
            "6-31g",
            "6-31g*",
            "6-31g**",
            "6-311g",
            "6-311g*",
            "6-311g**",
            "def2-svp",
            "def2-tzvp",
            "cc-pvdz",
            "cc-pvtz",
            "aug-cc-pvdz",
        ]
        for basis in basis_list:
            if re.search(rf"\b{re.escape(basis)}\b", text, re.I):
                return basis
        return None

    def _extract_charge(self, text: str) -> Optional[int]:
        patterns = [
            r"\bcharge\s*[:=]?\s*([+-]?\d+)\b",
            r"\bq\s*=\s*([+-]?\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\banion\b", text, re.I):
            return -1
        if re.search(r"\bcation\b", text, re.I):
            return 1
        return None

    def _extract_multiplicity(self, text: str) -> Optional[int]:
        patterns = [
            r"\bmultiplicity\s*[:=]?\s*(\d+)\b",
            r"\bspin multiplicity\s*[:=]?\s*(\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\bsinglet\b", text, re.I):
            return 1
        if re.search(r"\bdoublet\b", text, re.I):
            return 2
        if re.search(r"\btriplet\b", text, re.I):
            return 3
        return None

    def _extract_orbital(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(HOMO(?:[+-]\d+)?)\b",
            r"\b(LUMO(?:[+-]\d+)?)\b",
            r"\b(MO\s*\d+)\b",
            r"\borbital\s+([A-Za-z0-9+\-]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip().upper().replace(" ", "")
        return None

    def _extract_esp_preset(self, text: str) -> Optional[str]:
        presets = [
            "rwb",
            "bwr",
            "viridis",
            "inferno",
            "spectral",
            "nature",
            "acs",
            "rsc",
            "greyscale",
            "grey",
            "high_contrast",
            "hicon",
        ]
        for preset in presets:
            if re.search(rf"\b{re.escape(preset)}\b", text, re.I):
                return self._normalize_preset(preset)
        return None

    def _normalize_preset(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        key = value.strip().lower()
        if key == "grey":
            return "greyscale"
        if key == "hicon":
            return "high_contrast"
        return key

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content or "")

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _safe_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _none_if_blank(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
```

### File: `llm/providers.py`
```py
"""
LLM Provider implementations (Gemini, OpenAI).
"""

import json
import os
import logging
from typing import Optional
from pydantic import ValidationError

from .schemas import PlannerRequest, PlannerResponse, ToolCall
from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("qcviz_mcp.llm.providers")

try:
    from google import genai
    from google.genai import types
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False


class LLMProvider:
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        raise NotImplementedError()


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        if not _HAS_GEMINI:
            raise ImportError("google-genai is not installed. Run: pip install google-genai")
        
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
            
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-2.5-flash"
        
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        user_prompt = request.user_prompt
        
        prompt_text = f"""
        User Request: {user_prompt}
        
        Available Tools: {request.available_tools}
        
        Return a JSON object that perfectly matches the PlannerResponse schema.
        """
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=PlannerResponse.model_json_schema(),
                    temperature=0.1,
                ),
            )
            
            raw_text = response.text
            data = json.loads(raw_text)
            return PlannerResponse(**data)
            
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            # Fallback to rule-based logic or default response
            return PlannerResponse(
                thought_process=f"Failed to call LLM: {str(e)}",
                assistant_message="AI 에이전트 호출에 실패하여 기본 룰(Rule-based) 모드로 동작합니다.",
                tool_calls=[],
                is_help_only=True
            )


class DummyProvider(LLMProvider):
    """Fallback provider when no API key is available. Simulates basic rule-based routing."""
    
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        text = request.user_prompt.lower()
        tool = "run_single_point"
        focus = "summary"
        
        if any(x in text for x in ["orbital", "homo", "lumo", "오비탈"]):
            tool = "run_orbital_preview"
            focus = "orbitals"
        elif any(x in text for x in ["esp", "potential", "map", "전기정전위"]):
            tool = "run_esp_map"
            focus = "esp"
        elif any(x in text for x in ["charge", "mulliken", "부분 전하"]):
            tool = "run_partial_charges"
            focus = "charges"
        elif any(x in text for x in ["opt", "최적화"]):
            tool = "run_geometry_optimization"
            focus = "geometry"
            
        return PlannerResponse(
            thought_process="Rule-based fallback routing.",
            assistant_message="API 키가 설정되지 않아 로컬 규칙 기반 엔진이 요청을 처리합니다.",
            tool_calls=[ToolCall(tool_name=tool, parameters={"query": request.user_prompt})],
            is_help_only=False,
            suggested_focus_tab=focus
        )


def get_provider() -> LLMProvider:
    if os.environ.get("GEMINI_API_KEY") and _HAS_GEMINI:
        return GeminiProvider()
    
    logger.warning("No LLM API key found or SDK missing. Using DummyProvider (Rule-based fallback).")
    return DummyProvider()
```

### File: `web/static/viewer.js`
```js
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — 3D Viewer Module
   (Complete Rewrite: Unified Rendering Pipeline)
   ════───────────────────────────────────── */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  /* ─────────────────────────────────────────
     STATE
     ───────────────────────────────────────── */
  var state = {
    ready: false,
    viewer: null,
    model: null,
    mode: "none", // none | molecule | orbital | esp
    style: "stick",
    isovalue: 0.03,
    opacity: 0.75,
    espDensityIso: 0.001,
    colorScheme: "classic",
    showLabels: true,
    result: null,
    jobId: null,
    selectedOrbitalIndex: null,
    // Trajectory
    trajectoryFrames: [],
    trajectoryPlaying: false,
    trajectoryFrame: 0,
    trajectoryTimer: null,
  };

  /* ─────────────────────────────────────────
     DOM REFS — collected once in init()
     FIX #6: 이벤트 바인딩은 init()에서 한 번만
     ───────────────────────────────────────── */
  var dom = {};

  function collectDom() {
    dom.$viewerDiv = document.getElementById("viewer3d");
    dom.$empty = document.getElementById("viewerEmpty");
    dom.$controls = document.getElementById("viewerControls");
    dom.$legend = document.getElementById("viewerLegend");
    dom.$btnReset = document.getElementById("btnViewerReset");
    dom.$btnScreenshot = document.getElementById("btnViewerScreenshot");
    dom.$btnFullscreen = document.getElementById("btnViewerFullscreen");
    dom.$segStyle = document.getElementById("segStyle");
    dom.$grpOrbital = document.getElementById("grpOrbital");
    dom.$grpOpacity = document.getElementById("grpOpacity");
    dom.$grpOrbitalSelect = document.getElementById("grpOrbitalSelect");
    dom.$selectOrbital = document.getElementById("selectOrbital");
    dom.$sliderIso = document.getElementById("sliderIsovalue");
    dom.$lblIso = document.getElementById("lblIsovalue");
    dom.$sliderOp = document.getElementById("sliderOpacity");
    dom.$lblOp = document.getElementById("lblOpacity");
    dom.$btnLabels = document.getElementById("btnToggleLabels");
    dom.$btnModeOrbital = document.getElementById("btnModeOrbital");
    dom.$btnModeESP = document.getElementById("btnModeESP");
    dom.$vizModeToggle = document.getElementById("vizModeToggle");
    dom.$grpESP = document.getElementById("grpESP");
    dom.$selectColor = document.getElementById("selectColorScheme");
  }

  /* ─────────────────────────────────────────
     3Dmol LOADER
     ───────────────────────────────────────── */
  var _loadPromise = null;
  function load3Dmol() {
    if (window.$3Dmol) return Promise.resolve();
    if (_loadPromise) return _loadPromise;
    _loadPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
      s.onload = resolve;
      s.onerror = function () {
        reject(new Error("3Dmol.js load failed"));
      };
      document.head.appendChild(s);
    });
    return _loadPromise;
  }

  function ensureViewer() {
    if (state.viewer && state.ready) return Promise.resolve(state.viewer);
    return load3Dmol()
      .then(function () {
        if (!state.viewer && dom.$viewerDiv) {
          var isDark =
            document.documentElement.getAttribute("data-theme") === "dark";
          state.viewer = window.$3Dmol.createViewer(dom.$viewerDiv, {
            backgroundColor: isDark ? "black" : "white",
            antialias: true,
          });
          try {
            var canvas = dom.$viewerDiv.querySelector("canvas");
            if (canvas) canvas.style.backgroundColor = "transparent";
          } catch (_) {}
          state.ready = true;
          updateViewerBg();
        }
        return state.viewer;
      })
      .catch(function (err) {
        if (dom.$empty) {
          dom.$empty.hidden = false;
          var t = dom.$empty.querySelector(".viewer-empty__text");
          if (t)
            t.textContent =
              "Failed to load 3Dmol.js — check your network connection.";
        }
        throw err;
      });
  }

  function updateViewerBg() {
    if (!state.viewer) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    state.viewer.setBackgroundColor(isDark ? 0x0c0c0f : 0xfafafa, 1.0);
  }

  /* ─────────────────────────────────────────
     COLOR SCHEMES
     ───────────────────────────────────────── */
  var COLOR_SCHEMES = {
    classic: {
      label: "Classic (Blue/Red)",
      orbPositive: "#3b82f6",
      orbNegative: "#ef4444",
      espGradient: "rwb",
      reverse: false,
    },
    jmol: {
      label: "Jmol",
      orbPositive: "#1e40af",
      orbNegative: "#dc2626",
      espGradient: "rwb",
      reverse: false,
    },
    rwb: {
      label: "RWB (Red-White-Blue)",
      orbPositive: "#2563eb",
      orbNegative: "#dc2626",
      espGradient: "rwb",
      reverse: false,
    },
    bwr: {
      label: "BWR (Blue-White-Red)",
      orbPositive: "#dc2626",
      orbNegative: "#2563eb",
      espGradient: "rwb",
      reverse: true,
    },
    spectral: {
      label: "Spectral",
      orbPositive: "#2b83ba",
      orbNegative: "#d7191c",
      espGradient: "sinebow",
      reverse: false,
    },
    viridis: {
      label: "Viridis",
      orbPositive: "#21918c",
      orbNegative: "#fde725",
      espGradient: "roygb",
      reverse: false,
    },
    inferno: {
      label: "Inferno",
      orbPositive: "#fcffa4",
      orbNegative: "#420a68",
      espGradient: "roygb",
      reverse: false,
    },
    coolwarm: {
      label: "Cool-Warm",
      orbPositive: "#4575b4",
      orbNegative: "#d73027",
      espGradient: "rwb",
      reverse: false,
    },
    purplegreen: {
      label: "Purple-Green",
      orbPositive: "#1b7837",
      orbNegative: "#762a83",
      espGradient: "rwb",
      reverse: false,
    },
    greyscale: {
      label: "Greyscale",
      orbPositive: "#f0f0f0",
      orbNegative: "#404040",
      espGradient: "rwb",
      reverse: false,
    },
  };

  function getScheme() {
    return COLOR_SCHEMES[state.colorScheme] || COLOR_SCHEMES.classic;
  }

  function createGradient(type, min, max) {
    if (!window.$3Dmol) return null;
    var G = window.$3Dmol.Gradient;
    if (type === "sinebow" && G.Sinebow) return new G.Sinebow(min, max);
    if (type === "roygb" && G.ROYGB) return new G.ROYGB(min, max);
    return new G.RWB(min, max);
  }

  function updateSchemePreview() {
    var scheme = getScheme();
    var $preview = document.getElementById("schemePreview");
    if (!$preview) return;
    var $pos = $preview.querySelector(".swatch-pos");
    var $neg = $preview.querySelector(".swatch-neg");
    if ($pos) $pos.style.backgroundColor = scheme.orbPositive;
    if ($neg) $neg.style.backgroundColor = scheme.orbNegative;
  }

  /* ─────────────────────────────────────────
     HELPERS
     ───────────────────────────────────────── */
  function dismissLoader() {
    var $loader = document.getElementById("appLoader");
    if (!$loader) return;
    $loader.classList.add("fade-out");
    setTimeout(function () {
      if ($loader.parentNode) $loader.parentNode.removeChild($loader);
    }, 600);
  }

  function buildXyzFromAtoms(atoms) {
    if (!atoms || !atoms.length) return null;
    var lines = [String(atoms.length), "QCViz"];
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "X";
      var x = Number(a.x != null ? a.x : a[1] || 0).toFixed(6);
      var y = Number(a.y != null ? a.y : a[2] || 0).toFixed(6);
      var z = Number(a.z != null ? a.z : a[3] || 0).toFixed(6);
      lines.push(el + " " + x + " " + y + " " + z);
    });
    return lines.join("\n");
  }

  function getXyz(result) {
    if (!result) return null;
    var viz = result.visualization || {};
    return (
      viz.xyz ||
      viz.molecule_xyz ||
      viz.xyz_block ||
      result.xyz_block ||
      result.xyz ||
      null ||
      (result.atoms && result.atoms.length
        ? buildXyzFromAtoms(result.atoms)
        : null)
    );
  }

  function findCubeB64(result, type) {
    var viz = result.visualization || {};
    var key = type + "_cube_b64";
    return viz[key] || result[key] || (viz[type] && viz[type].cube_b64) || null;
  }

  function safeAtob(b64) {
    if (!b64) return null;
    try {
      return atob(b64);
    } catch (e) {
      console.error("[Viewer] atob failed:", e);
      return null;
    }
  }

  function applyStyle(viewer, style) {
    var styles = {
      stick: {
        stick: { radius: 0.14, colorscheme: "Jmol" },
        sphere: { scale: 0.25, colorscheme: "Jmol" },
      },
      sphere: { sphere: { scale: 0.6, colorscheme: "Jmol" } },
      line: { line: { colorscheme: "Jmol" } },
    };
    viewer.setStyle({}, styles[style] || styles.stick);
  }

  /* ─────────────────────────────────────────
     LABELS
     ───────────────────────────────────────── */
  function addLabels(viewer, result) {
    var atoms = result.atoms || [];
    if (!atoms.length) return;

    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    var charges = result.mulliken_charges || result.lowdin_charges || [];

    var maxAbs = 0;
    for (var k = 0; k < charges.length; k++) {
      var cv = charges[k];
      var cval = cv != null && typeof cv === "object" ? cv.charge : cv;
      if (cval != null && isFinite(cval) && Math.abs(cval) > maxAbs)
        maxAbs = Math.abs(cval);
    }
    if (maxAbs < 0.001) maxAbs = 1;

    atoms.forEach(function (a, i) {
      var el = a.element || a.symbol || a[0] || "";
      if (!el) return;

      var rawCharge = charges[i];
      var chargeVal = null;
      if (rawCharge != null) {
        chargeVal =
          typeof rawCharge === "object" ? rawCharge.charge : rawCharge;
        if (chargeVal != null && !isFinite(chargeVal)) chargeVal = null;
      }

      var labelText = el;
      if (chargeVal != null) {
        labelText +=
          " (" + (chargeVal >= 0 ? "+" : "") + chargeVal.toFixed(3) + ")";
      }

      var bgColor, fontColor, borderColor;
      if (chargeVal != null && Math.abs(chargeVal) > 0.005) {
        var alpha = 0.25 + Math.min(Math.abs(chargeVal) / maxAbs, 1.0) * 0.55;
        if (chargeVal > 0) {
          bgColor = "rgba(59,130,246," + alpha.toFixed(2) + ")";
          fontColor = isDark ? "#dbeafe" : "#1e3a5f";
          borderColor = "rgba(59,130,246,0.4)";
        } else {
          bgColor = "rgba(239,68,68," + alpha.toFixed(2) + ")";
          fontColor = isDark ? "#fee2e2" : "#7f1d1d";
          borderColor = "rgba(239,68,68,0.4)";
        }
      } else {
        fontColor = isDark ? "white" : "#333";
        bgColor = isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.7)";
        borderColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
      }

      viewer.addLabel(labelText, {
        position: {
          x: a.x != null ? a.x : a[1] || 0,
          y: a.y != null ? a.y : a[2] || 0,
          z: a.z != null ? a.z : a[3] || 0,
        },
        fontSize: 11,
        fontColor: fontColor,
        backgroundColor: bgColor,
        borderColor: borderColor,
        borderThickness: 1,
        backgroundOpacity: 0.85,
        alignment: "center",
        showBackground: true,
      });
    });
  }

  function refreshLabels() {
    if (!state.viewer) return;
    state.viewer.removeAllLabels();
    if (state.showLabels && state.result) addLabels(state.viewer, state.result);
    state.viewer.render();
  }

  /* ─────────────────────────────────────────
     CORE RENDER PRIMITIVES
     ───────────────────────────────────────── */
  function clearViewer(viewer) {
    if (!viewer) return;
    viewer.removeAllModels();
    viewer.removeAllSurfaces();
    viewer.removeAllLabels();
    if (typeof viewer.removeAllShapes === "function") viewer.removeAllShapes();
    state.model = null;
  }

  function addMoleculeModel(viewer, result) {
    var xyz = getXyz(result);
    if (!xyz) return false;
    state.model = viewer.addModel(xyz, "xyz");
    applyStyle(viewer, state.style);
    return true;
  }

  function addOrbitalSurfaces(viewer, cubeString) {
    if (!cubeString) return;
    var scheme = getScheme();
    var vol = new window.$3Dmol.VolumeData(cubeString, "cube");
    viewer.addIsosurface(vol, {
      isoval: state.isovalue,
      color: scheme.orbPositive,
      alpha: state.opacity,
      smoothness: 3,
      wireframe: false,
    });
    viewer.addIsosurface(vol, {
      isoval: -state.isovalue,
      color: scheme.orbNegative,
      alpha: state.opacity,
      smoothness: 3,
      wireframe: false,
    });
  }

  function addESPSurface(viewer, result) {
    var espB64 = findCubeB64(result, "esp");
    var densB64 = findCubeB64(result, "density");
    var espStr = safeAtob(espB64);
    if (!espStr) {
      console.warn("[Viewer] No ESP cube data found");
      return;
    }

    var scheme = getScheme();
    var range = result.esp_auto_range_au || 0.05;
    var minVal = scheme.reverse ? range : -range;
    var maxVal = scheme.reverse ? -range : range;
    var grad = createGradient(scheme.espGradient, minVal, maxVal);

    var espVol = new window.$3Dmol.VolumeData(espStr, "cube");

    if (densB64) {
      var densStr = safeAtob(densB64);
      if (densStr) {
        var densVol = new window.$3Dmol.VolumeData(densStr, "cube");
        viewer.addIsosurface(densVol, {
          isoval: state.isovalue,
          color: "white",
          alpha: state.opacity,
          smoothness: 1,
          voldata: espVol,
          volscheme: grad,
        });
        return;
      }
    }
    
    // Fallback: Map ESP on its own isosurface (less ideal)
    viewer.addIsosurface(espVol, {
      isoval: state.isovalue,
      alpha: state.opacity,
      smoothness: 3,
      volscheme: grad,
    });
  }

  /* ─────────────────────────────────────────
     HIGH-LEVEL RENDERERS
     ───────────────────────────────────────── */
  function renderMolecule(result) {
    return ensureViewer().then(function (viewer) {
      clearViewer(viewer);
      addMoleculeModel(viewer, result);
      if (state.showLabels) addLabels(viewer, result);
      viewer.zoomTo();
      viewer.render();
      state.mode = "molecule";
      showControls("molecule");
      hideLegend();
    });
  }

  function renderOrbital(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.result ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNew = oldXyz !== newXyz;

      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      var cubeB64 = findCubeB64(result, "orbital");
      var cubeStr = safeAtob(cubeB64);
      if (cubeStr) {
        addOrbitalSurfaces(viewer, cubeStr);
        if (!state.model) {
          state.model = viewer.addModel(cubeStr, "cube");
          applyStyle(viewer, state.style);
        }
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNew) viewer.zoomTo();
      viewer.render();
      state.mode = "orbital";
      showControls("orbital");
      showOrbitalLegend();
      populateOrbitalSelector(result);
    });
  }

  function renderESP(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.result ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNew = oldXyz !== newXyz;

      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      try {
        addESPSurface(viewer, result);
      } catch (e) {
        console.error("[Viewer] ESP render error:", e);
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNew) viewer.zoomTo();
      viewer.render();
      state.mode = "esp";
      showControls("esp");
      showESPLegend();
    });
  }

  function reRenderCurrentSurface() {
    if (!state.viewer || !state.result) return;
    if (state.mode === "orbital") {
      renderOrbital(state.result);
    } else if (state.mode === "esp") {
      renderESP(state.result);
    }
  }

  function switchVizMode(newMode) {
    if (!state.result) return;
    if (state.mode === newMode) return;
    var prevMode = state.mode;
    state.mode = "switching"; 
    
    var p;
    if (newMode === "orbital") {
      p = renderOrbital(state.result);
    } else if (newMode === "esp") {
      p = renderESP(state.result);
    }
    
    if (p) {
      p.then(function() {
        saveViewerSnapshot();
      }).catch(function(err) {
        console.error("[Viewer] Mode switch failed:", err);
        state.mode = prevMode;
        showControls(prevMode);
      });
    } else {
      state.mode = prevMode;
    }
  }

  function showControls(mode) {
    if (dom.$empty) dom.$empty.hidden = true;
    if (dom.$controls) dom.$controls.hidden = false;

    var result = state.result || {};
    var hasOrbital = !!(findCubeB64(result, "orbital") || (result.orbitals && result.orbitals.length));
    var hasESP = !!findCubeB64(result, "esp");

    if (dom.$grpOrbital) dom.$grpOrbital.hidden = !hasOrbital;
    if (dom.$grpESP) dom.$grpESP.hidden = !hasESP;
    if (dom.$grpOpacity) dom.$grpOpacity.hidden = !(hasOrbital || hasESP);
    if (dom.$vizModeToggle) dom.$vizModeToggle.hidden = !(hasOrbital && hasESP);
    if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = mode !== "orbital" || !hasOrbital;

    if (dom.$sliderIso) {
      if (mode === "esp") {
        dom.$sliderIso.min = "0.0001"; 
        dom.$sliderIso.max = "0.02"; 
        dom.$sliderIso.step = "0.0001";
        if (state.isovalue > 0.02 || state.isovalue < 0.0001) state.isovalue = 0.002;
      } else {
        dom.$sliderIso.min = "0.001"; 
        dom.$sliderIso.max = "0.2"; 
        dom.$sliderIso.step = "0.001";
        if (state.isovalue < 0.001 || state.isovalue > 0.2) state.isovalue = 0.03;
      }
      dom.$sliderIso.value = state.isovalue;
      if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
    }

    if (dom.$btnModeOrbital) dom.$btnModeOrbital.classList.toggle("active", mode === "orbital");
    if (dom.$btnModeESP) dom.$btnModeESP.classList.toggle("active", mode === "esp");

    if (mode === "orbital") showOrbitalLegend();
    else if (mode === "esp") showESPLegend();
    else hideLegend();
  }

  function showOrbitalLegend() {
    if (!dom.$legend) return;
    var s = getScheme();
    dom.$legend.hidden = false;
    dom.$legend.innerHTML = '<div class="viewer-legend__title">Orbital Lobes</div>' +
      '<div class="viewer-legend__row"><span class="viewer-legend__swatch" style="background:'+s.orbPositive+'"></span><span>Positive (+' + state.isovalue.toFixed(3) + ')</span></div>' +
      '<div class="viewer-legend__row"><span class="viewer-legend__swatch" style="background:'+s.orbNegative+'"></span><span>Negative (\u2212' + state.isovalue.toFixed(3) + ')</span></div>';
  }

  function showESPLegend() {
    if (!dom.$legend) return;
    var css = getGradientCSS(getScheme());
    dom.$legend.hidden = false;
    dom.$legend.innerHTML = '<div class="viewer-legend__title">ESP Surface</div>' +
      '<div class="viewer-legend__row" style="justify-content:center;width:100%;margin-top:4px;">' +
      '<span class="viewer-legend__swatch" style="background:'+css+';width:100px;height:12px;border-radius:3px;"></span></div>' +
      '<div class="viewer-legend__row" style="display:flex;justify-content:space-between;width:100px;margin:2px auto 0;">' +
      '<span style="font-size:11px;color:var(--text-3)">\u2212</span><span style="font-size:10px;color:var(--text-4)">0</span><span style="font-size:11px;color:var(--text-3)">+</span></div>';
  }

  function hideLegend() {
    if (dom.$legend) { dom.$legend.hidden = true; dom.$legend.innerHTML = ""; }
  }

  function getGradientCSS(schemeObj) {
    var g = schemeObj.espGradient;
    var r = schemeObj.reverse;
    if (g === "sinebow") return "linear-gradient(90deg,#ff0000,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)";
    if (g === "roygb") return r ? "linear-gradient(90deg,#0000ff,#00ff00,#ffff00,#ff0000)" : "linear-gradient(90deg,#ff0000,#ffff00,#00ff00,#0000ff)";
    return r ? "linear-gradient(90deg,#3b82f6,#ffffff,#ef4444)" : "linear-gradient(90deg,#ef4444,#ffffff,#3b82f6)";
  }

  function populateOrbitalSelector(result) {
    if (!dom.$selectOrbital || !result) return;
    var orbitals = result.orbitals || [];
    var moE = result.mo_energies || [];
    var moO = result.mo_occupations || [];
    dom.$selectOrbital.innerHTML = "";

    if (orbitals.length > 0) {
      var info = (result.visualization && result.visualization.orbital_info) || result.orbital_info || {};
      var currentIdx = info.orbital_index != null ? info.orbital_index : (result.selected_orbital ? result.selected_orbital.zero_based_index : -1);
      orbitals.forEach(function (orb) {
        var opt = document.createElement("option");
        opt.value = orb.zero_based_index;
        opt.textContent = orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
        if (orb.zero_based_index === currentIdx) opt.selected = true;
        dom.$selectOrbital.appendChild(opt);
      });
      state.selectedOrbitalIndex = currentIdx;
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = false;
    } else if (moE.length > 0) {
      var homoIdx = -1;
      for (var i = 0; i < moE.length; i++) if (moO[i] > 0) homoIdx = i;
      var lumoIdx = (homoIdx >= 0 && homoIdx + 1 < moE.length) ? homoIdx + 1 : -1;
      var currentIdx2 = homoIdx; 
      var start = Math.max(0, homoIdx - 4);
      var end = Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 5);
      for (var j = start; j < end; j++) {
        var opt = document.createElement("option");
        opt.value = j;
        var label = "MO " + j;
        if (j === homoIdx) label = "HOMO";
        else if (j === lumoIdx) label = "LUMO";
        opt.textContent = label + " (" + Number(moE[j]).toFixed(3) + " Ha)";
        if (j === currentIdx2) opt.selected = true;
        dom.$selectOrbital.appendChild(opt);
      }
      state.selectedOrbitalIndex = currentIdx2;
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = false;
    } else {
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = true;
    }
  }

  function saveViewerSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(state.jobId, Object.assign({}, existing, {
      viewerStyle: state.style,
      viewerIsovalue: state.isovalue,
      viewerOpacity: state.opacity,
      viewerLabels: state.showLabels,
      viewerMode: state.mode,
      viewerOrbitalIndex: state.selectedOrbitalIndex,
      viewerColorScheme: state.colorScheme,
    }));
  }

  function restoreViewerSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (!snap) return;
    if (snap.viewerStyle) state.style = snap.viewerStyle;
    if (snap.viewerIsovalue != null) state.isovalue = snap.viewerIsovalue;
    if (snap.viewerOpacity != null) state.opacity = snap.viewerOpacity;
    if (snap.viewerLabels != null) state.showLabels = snap.viewerLabels;
    if (snap.viewerOrbitalIndex != null) state.selectedOrbitalIndex = snap.viewerOrbitalIndex;
    if (snap.viewerColorScheme) state.colorScheme = snap.viewerColorScheme;
    syncUIToState();
  }

  function syncUIToState() {
    if (dom.$segStyle) {
      dom.$segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
        b.classList.toggle("segmented__btn--active", b.dataset.value === state.style);
      });
    }
    if (dom.$sliderIso) dom.$sliderIso.value = state.isovalue;
    if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
    if (dom.$sliderOp) dom.$sliderOp.value = state.opacity;
    if (dom.$lblOp) dom.$lblOp.textContent = state.opacity.toFixed(2);
    if (dom.$btnLabels) {
      dom.$btnLabels.setAttribute("data-active", String(state.showLabels));
      dom.$btnLabels.textContent = state.showLabels ? "On" : "Off";
    }
    if (dom.$selectColor) dom.$selectColor.value = state.colorScheme;
    updateSchemePreview();
  }

  function handleResult(detail) {
    var result = detail.result;
    var jobId = detail.jobId;
    if (!result) {
      if (state.viewer) { clearViewer(state.viewer); state.viewer.render(); }
      state.result = null; state.jobId = null; state.mode = "none";
      if (dom.$empty) dom.$empty.hidden = false;
      if (dom.$controls) dom.$controls.hidden = true;
      hideLegend(); return;
    }
    state.result = result; state.jobId = jobId;
    if (detail.source === "history" && jobId) restoreViewerSnapshot(jobId);
    var p;
    if (findCubeB64(result, "orbital")) p = renderOrbital(result);
    else if (findCubeB64(result, "esp")) p = renderESP(result);
    else if (getXyz(result)) p = renderMolecule(result);
    if (p) p.then(saveViewerSnapshot).catch(console.error);
  }

  function handleResultSwitched(data) {
    var r = data.result; if (!r) return;
    state.result = r; state.jobId = data.jobId || null;
    if (findCubeB64(r, "orbital")) renderOrbital(r);
    else if (findCubeB64(r, "esp")) renderESP(r);
    else if (getXyz(r)) renderMolecule(r);
  }

  function bindEvents() {
    if (dom.$segStyle) dom.$segStyle.addEventListener("click", function (e) {
      var b = e.target.closest(".segmented__btn"); if (!b) return;
      state.style = b.dataset.value;
      dom.$segStyle.querySelectorAll(".segmented__btn").forEach(function (x) { x.classList.toggle("segmented__btn--active", x.dataset.value === state.style); });
      if (state.viewer && state.model) { applyStyle(state.viewer, state.style); state.viewer.render(); }
      saveViewerSnapshot();
    });
    if (dom.$btnLabels) dom.$btnLabels.addEventListener("click", function () {
      state.showLabels = !state.showLabels; refreshLabels(); syncUIToState(); saveViewerSnapshot();
    });
    if (dom.$btnReset) dom.$btnReset.addEventListener("click", function () { if (state.viewer) { state.viewer.zoomTo(); state.viewer.render(); } });
    if (dom.$btnScreenshot) dom.$btnScreenshot.addEventListener("click", function () {
      if (!state.viewer) return;
      var a = document.createElement("a"); a.href = state.viewer.pngURI(); a.download = "qcviz-" + (state.jobId || "capture") + ".png"; a.click();
    });
    if (dom.$btnFullscreen) dom.$btnFullscreen.addEventListener("click", function () {
      var p = document.getElementById("panelViewer"); if (p) p.classList.toggle("is-fullscreen");
      setTimeout(function () { if (state.viewer) { state.viewer.resize(); state.viewer.render(); } }, 150);
    });
    if (dom.$sliderIso) {
      dom.$sliderIso.addEventListener("input", function () { state.isovalue = parseFloat(dom.$sliderIso.value); if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4); });
      dom.$sliderIso.addEventListener("change", function () { reRenderCurrentSurface(); saveViewerSnapshot(); });
    }
    if (dom.$sliderOp) {
      dom.$sliderOp.addEventListener("input", function () { state.opacity = parseFloat(dom.$sliderOp.value); if (dom.$lblOp) dom.$lblOp.textContent = state.opacity.toFixed(2); });
      dom.$sliderOp.addEventListener("change", function () { reRenderCurrentSurface(); saveViewerSnapshot(); });
    }
    if (dom.$selectOrbital) dom.$selectOrbital.addEventListener("change", function () {
      var idx = parseInt(dom.$selectOrbital.value, 10); if (isNaN(idx)) return;
      state.selectedOrbitalIndex = idx;
      // In a real implementation, we might need to fetch the orbital cube here if not cached.
      // For now, assume it's available or handled by the parent.
      saveViewerSnapshot();
    });
    if (dom.$btnModeOrbital) dom.$btnModeOrbital.addEventListener("click", function () { switchVizMode("orbital"); });
    if (dom.$btnModeESP) dom.$btnModeESP.addEventListener("click", function () { switchVizMode("esp"); });
    if (dom.$selectColor) dom.$selectColor.addEventListener("change", function () {
      state.colorScheme = dom.$selectColor.value; updateSchemePreview(); reRenderCurrentSurface(); saveViewerSnapshot();
    });

    App.on("result:changed", handleResult);
    App.on("result:switched", handleResultSwitched);
    App.on("theme:changed", function () { updateViewerBg(); refreshLabels(); });
    window.addEventListener("resize", function () { if (state.viewer) { state.viewer.resize(); state.viewer.render(); } });
  }

  function init() {
    collectDom(); bindEvents(); syncUIToState();
    var safety = setTimeout(dismissLoader, 5000);
    ensureViewer().then(function () {
      clearTimeout(safety);
      var ajid = App.store && App.store.activeJobId;
      if (ajid && App.store.resultsByJobId[ajid]) {
        var r = App.store.resultsByJobId[ajid];
        // handleResult with source:history will call restoreViewerSnapshot
        handleResult({ result: r, jobId: ajid, source: "history" });
      }
      dismissLoader();
    }).catch(function (e) { clearTimeout(safety); console.error(e); dismissLoader(); });
  }

  App.viewer = { reset: function() { if (state.viewer) state.viewer.zoomTo(); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();

```

### File: `web/static/app.js`
```js
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — App Orchestrator
   Theme, shortcuts, history, status sync, init
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var PREFIX = App.apiPrefix || "/api";

  /* ─── DOM ─── */
  var $statusDot = document.querySelector("#globalStatus .status-indicator__dot");
  var $statusText = document.querySelector("#globalStatus .status-indicator__text");
  var $themeBtn = document.getElementById("btnThemeToggle");
  var $shortcutsBtn = document.getElementById("btnKeyboardShortcuts");
  var $shortcutsModal = document.getElementById("modalShortcuts");
  var $historyList = document.getElementById("historyList");
  var $historyEmpty = document.getElementById("historyEmpty");
  var $historySearch = document.getElementById("historySearch");
  var $btnRefresh = document.getElementById("btnRefreshHistory");
  var $chatInput = document.getElementById("chatInput");

  /* ─── Global Status ─── */
  App.on("status:changed", function (s) {
    if ($statusDot) $statusDot.setAttribute("data-kind", s.kind || "idle");
    if ($statusText) $statusText.textContent = s.text || "Ready";

    if (s.kind === "success" || s.kind === "completed") {
      setTimeout(function () {
        if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
          App.setStatus("Ready", "idle", "app");
        }
      }, 4000);
    }
  });

  /* ─── Theme Toggle ─── */
  if ($themeBtn) {
    $themeBtn.addEventListener("click", function () {
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
    });
  }

  /* ─── Modal Helpers ─── */
  function openModal(dialog) {
    if (!dialog) return;
    dialog.showModal();
  }
  function closeModal(dialog) {
    if (!dialog) return;
    dialog.close();
  }

  if ($shortcutsBtn) {
    $shortcutsBtn.addEventListener("click", function () { openModal($shortcutsModal); });
  }

  if ($shortcutsModal) {
    $shortcutsModal.addEventListener("click", function (e) {
      if (e.target.hasAttribute("data-close") || e.target.closest("[data-close]")) {
        closeModal($shortcutsModal);
      }
    });
  }

  /* ─── Keyboard Shortcuts ─── */
  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    var isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    // Ctrl+/ → Focus chat
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      if ($chatInput) $chatInput.focus();
      return;
    }

    // Ctrl+K → Focus history search
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if ($historySearch) $historySearch.focus();
      return;
    }

    // Ctrl+\ → Toggle theme
    if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
      e.preventDefault();
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
      return;
    }

    // Escape
    if (e.key === "Escape") {
      if ($shortcutsModal && $shortcutsModal.open) {
        closeModal($shortcutsModal);
        return;
      }
      if (isTyping) {
        document.activeElement.blur();
        return;
      }
    }

    // ? → Show shortcuts
    if (e.key === "?" && !isTyping) {
      openModal($shortcutsModal);
    }
  });

  /* ─── History Panel ─── */
  var historyFilter = "";

  function getJobDisplayName(job) {
    if (job.user_query && typeof job.user_query === "string" && job.user_query.trim()) {
      var q = job.user_query.trim();
      return q.length > 40 ? q.substring(0, 40) + "\u2026" : q;
    }
    
    var molName = job.molecule_name || job.molecule || (job.result && (job.result.structure_name || job.result.structure_query)) || (job.payload && (job.payload.structure_query || job.payload.molecule_name || job.payload.molecule));
    var method = job.method || (job.result && job.result.method) || (job.payload && job.payload.method) || "";
    var basis = job.basis_set || (job.result && job.result.basis_set) || (job.payload && job.payload.basis_set) || "";
    var jobType = job.job_type || (job.result && job.result.job_type) || (job.payload && job.payload.job_type) || "computation";

    if (molName) {
        var name = molName;
        if (jobType === "orbital_preview" || jobType === "orbital") {
             var orb = job.orbital || (job.payload && job.payload.orbital);
             if (orb) name = orb + " of " + name;
             else name = "Orbital of " + name;
        } else if (jobType === "esp_map" || jobType === "esp") {
             name = "ESP of " + name;
        }
        return name.length > 40 ? name.substring(0, 40) + "\u2026" : name;
    }
    
    if (method || basis) return [method, basis].filter(Boolean).join(" / ");
    
    // Nice fallback instead of ugly ID
    var prettyType = jobType.replace(/_/g, " ");
    return prettyType.charAt(0).toUpperCase() + prettyType.slice(1);
  }

  function getJobDetailLine(job) {
    var parts = [];
    var jobType = job.job_type || (job.payload && job.payload.job_type) || "";
    if (jobType) parts.push(jobType);
    var method = job.method || (job.result && job.result.method) || (job.payload && job.payload.method) || "";
    if (method) parts.push(method);
    var basis = job.basis_set || (job.result && job.result.basis_set) || (job.payload && job.payload.basis_set) || "";
    if (basis) parts.push(basis);
    if (parts.length > 0) return parts.join(" \u00B7 ");

    // Fallback to timestamp
    var ts = job.submitted_at || job.created_at || job.updated_at;
    if (ts) {
      var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " +
        d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }
    return "\u2014";
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function escAttr(s) {
    return String(s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderHistory() {
    if (!$historyList) return;

    var jobs = App.store.jobOrder.map(function (id) { return App.store.jobsById[id]; }).filter(Boolean);

    var filtered = jobs;
    if (historyFilter) {
      var q = historyFilter.toLowerCase();
      filtered = jobs.filter(function (j) {
        var searchable = [
          j.user_query || "",
          j.molecule_name || "",
          j.molecule || "",
          j.method || "",
          j.basis_set || "",
          j.job_id || "",
          (j.payload && j.payload.molecule) || "",
          (j.payload && j.payload.method) || "",
        ].join(" ").toLowerCase();
        return searchable.indexOf(q) !== -1;
      });
    }

    // Remove old items
    var oldItems = $historyList.querySelectorAll(".history-item");
    oldItems.forEach(function (el) { el.remove(); });

    if (filtered.length === 0) {
      if ($historyEmpty) {
        $historyEmpty.hidden = false;
        var p = $historyEmpty.querySelector("p");
        if (p) p.textContent = historyFilter ? "No matching jobs" : "No previous computations";
      }
      return;
    }

    if ($historyEmpty) $historyEmpty.hidden = true;

    var activeJobId = App.store.activeJobId;
    var html = "";

    filtered.forEach(function (job) {
      var id = job.job_id || "";
      var status = job.status || "queued";
      var name = getJobDisplayName(job);
      var detail = getJobDetailLine(job);
      var energy = job.result ? (job.result.total_energy_hartree != null ? job.result.total_energy_hartree : job.result.energy) : null;
      var energyStr = energy != null ? Number(energy).toFixed(4) + " Ha" : "";
      var isActive = id === activeJobId;

      html += '<div class="history-item' + (isActive ? ' history-item--active' : '') + '" data-job-id="' + escAttr(id) + '">' +
        '<span class="history-item__status history-item__status--' + escAttr(status) + '"></span>' +
        '<div class="history-item__info">' +
        '<div class="history-item__title">' + esc(name) + '</div>' +
        '<div class="history-item__detail">' + esc(detail) + '</div>' +
        '</div>' +
        (energyStr ? '<span class="history-item__energy">' + esc(energyStr) + '</span>' : '') +
        '</div>';
    });

    if ($historyEmpty) {
      $historyEmpty.insertAdjacentHTML("beforebegin", html);
    } else {
      $historyList.innerHTML = html;
    }
  }

  // History click
  if ($historyList) {
    $historyList.addEventListener("click", function (e) {
      var item = e.target.closest(".history-item");
      if (!item) return;
      var jobId = item.dataset.jobId;
      if (!jobId) return;
      App.setActiveJob(jobId);
      renderHistory();
    });
  }

  // History search
  if ($historySearch) {
    $historySearch.addEventListener("input", function () {
      historyFilter = $historySearch.value.trim();
      renderHistory();
    });
  }

  // Fetch history from server
  function fetchHistory() {
    return fetch(PREFIX + "/compute/jobs?include_result=true")
      .then(function (res) {
        if (!res.ok) return;
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        var jobs = Array.isArray(data) ? data : (data.items || data.jobs || []);
        
        var sortedJobs = jobs.sort(function(a, b) { return (a.created_at || 0) - (b.created_at || 0); });
        sortedJobs.forEach(function (j) { App.upsertJob(j); });
        
        // Auto-activate last job if none active
        if (!App.store.activeJobId && App.store.jobOrder.length > 0) {
            App.setActiveJob(App.store.jobOrder[0]);
        }
        
        renderHistory();
        renderSessionTabs();
      })
      .catch(function (e) {
        console.error("fetchHistory error:", e);
      });
  }

  if ($btnRefresh) {
    $btnRefresh.addEventListener("click", function () {
      $btnRefresh.classList.add("is-spinning");
      fetchHistory().then(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      }).catch(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      });
    });
  }


  /* ─── Session Tabs ─── */
  var $sessionTabsContainer = document.getElementById("sessionTabsContainer");
  var $sessionTabs = document.getElementById("sessionTabs");

  function renderSessionTabs() {
    if (!$sessionTabs || !$sessionTabsContainer) return;
    var maxTabs = 15;
    var order = App.store.jobOrder.slice(0, maxTabs);
    
    if (order.length === 0) {
      $sessionTabsContainer.hidden = true;
      return;
    }
    
    $sessionTabsContainer.hidden = false;
    var html = "";
    
    order.forEach(function (id) {
      var job = App.store.jobsById[id];
      if (!job) return;
      
      var isActive = id === App.store.activeJobId;
      var name = job.molecule_name || job.user_query || id;
      if (name.length > 20) name = name.substring(0, 20) + "...";
      
      var method = job.method || "";
      var badge = "";
      if (job.status === "running") badge = " ⏳";
      else if (job.status === "failed") badge = " ❌";
      
      var displayStr = name + (method ? " (" + method + ")" : "") + badge;
      
      html += '<div class="session-tab' + (isActive ? ' session-tab--active' : '') + '" data-job-id="' + escAttr(id) + '" title="' + escAttr(job.user_query || "") + '">' +
              esc(displayStr) +
              '</div>';
    });
    
    $sessionTabs.innerHTML = html;
  }

  if ($sessionTabs) {
    $sessionTabs.addEventListener("click", function(e) {
      var tab = e.target.closest(".session-tab");
      if (!tab) return;
      var jid = tab.getAttribute("data-job-id");
      if (jid && jid !== App.store.activeJobId) {
        App.setActiveJob(jid);
      }
    });
  }

  App.on("jobs:changed", function () {
    renderHistory();
    renderSessionTabs();
  });

  App.on("activejob:changed", function () {
    renderHistory();
    renderSessionTabs();
  });


  /* ─── Init ─── */
  fetchHistory();
  renderHistory();

  console.log(
    "%c QCViz-MCP Enterprise v5 %c Loaded ",
    "background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-weight:bold;padding:3px 8px;border-radius:4px 0 0 4px;",
    "background:#18181b;color:#a1a1aa;padding:3px 8px;border-radius:0 4px 4px 0;"
  );

})();

```

### File: `web/static/chat.js`
```js
function stringifyError(val) {
  if (val == null) return "";
  if (typeof val === "string") return val;
  if (val instanceof Error) return val.message || String(val);
  if (typeof val === "object") {
    if (typeof val.message === "string") return val.message;
    if (typeof val.error === "string") return val.error;
    if (typeof val.detail === "string") return val.detail;
    if (typeof val.error === "object") return stringifyError(val.error);
    if (typeof val.detail === "object") return stringifyError(val.detail);
    try {
      return JSON.stringify(val, null, 2);
    } catch (_) {
      return String(val);
    }
  }
  return String(val);
}

/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Chat Module
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var PREFIX = App.apiPrefix || "/api";

  var state = {
    sessionId: App.store.sessionId,
    ws: null,
    wsConnected: false,
    reconnectTimer: null,
    reconnectAttempts: 0,
    maxReconnect: 8,
    activeJobId: null,
    sending: false,
    streamBuffer: "",
    activeAssistantEl: null,
    activeProgressEl: null,
    lastUserInput: "",
  };

  var $messages = document.getElementById("chatMessages");
  var $scroll = document.getElementById("chatScroll");
  var $form = document.getElementById("chatForm");
  var $input = document.getElementById("chatInput");
  var $send = document.getElementById("chatSend");
  var $suggestions = document.getElementById("chatSuggestions");
  var $wsDot = document.querySelector("#wsStatus .ws-status__dot");
  var $wsLabel = document.querySelector("#wsStatus .ws-status__label");

  function now() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      if ($scroll) $scroll.scrollTop = $scroll.scrollHeight;
    });
  }

  function setWsUI(connected) {
    state.wsConnected = connected;
    if ($wsDot) $wsDot.setAttribute("data-connected", String(connected));
    if ($wsLabel) $wsLabel.textContent = connected ? "Connected" : "Disconnected";
  }

  function setSending(v) {
    state.sending = v;
    if ($send) $send.disabled = v || !($input && $input.value.trim());
  }

  function escHtml(s) {
    if (s == null) return "";
    if (typeof s === "object") {
      try { s = JSON.stringify(s, null, 2); } catch (_) { s = String(s); }
    }
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  /* 깊은 텍스트 추출: [object Object] 절대 반환하지 않음 */
  function extractReadableText(obj) {
    if (obj == null) return "";
    if (typeof obj === "string") return obj;
    if (typeof obj === "number" || typeof obj === "boolean") return String(obj);
    if (typeof obj === "object") {
      var keys = ["message", "text", "content", "detail", "reason", "error", "description", "response", "answer", "reply"];
      for (var i = 0; i < keys.length; i++) {
        if (obj[keys[i]] != null) {
          var v = extractReadableText(obj[keys[i]]);
          if (v) return v;
        }
      }
      try { return JSON.stringify(obj, null, 2); } catch (_) { return "[data]"; }
    }
    return String(obj);
  }

  function extractTextFromMsg(msg) {
    var keys = ["text", "content", "message", "response", "answer", "reply", "detail"];
    for (var i = 0; i < keys.length; i++) {
      if (msg[keys[i]] != null) {
        var v = extractReadableText(msg[keys[i]]);
        if (v) return v;
      }
    }
    return "";
  }

  function formatMarkdown(text) {
    if (!text) return "";
    var s = escHtml(text);
    s = s.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\n/g, "<br>");
    return s;
  }

  /* 메시지 버블 생성 */
  function createMsgEl(role, opts) {
    opts = opts || {};
    var div = document.createElement("div");
    div.className = "chat-msg chat-msg--" + role;

    var avatar = document.createElement("div");
    avatar.className = "chat-msg__avatar chat-msg__avatar--" + role;
    if (role === "user") {
      avatar.textContent = "U";
    } else if (role === "assistant") {
      avatar.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
    } else if (role === "error") {
      avatar.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    }

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var meta = document.createElement("div");
    meta.className = "chat-msg__meta";

    var nameEl = document.createElement("span");
    nameEl.className = "chat-msg__name";
    nameEl.textContent = role === "user" ? "You" : role === "error" ? "Error" : "QCViz";

    var timeEl = document.createElement("span");
    timeEl.className = "chat-msg__time";
    timeEl.textContent = now();

    meta.appendChild(nameEl);
    meta.appendChild(timeEl);
    body.appendChild(meta);

    var safeHtml = opts.html ? (typeof opts.html === "object" ? escHtml(opts.html) : opts.html) : null;
    var safeText = opts.text ? extractReadableText(opts.text) : null;

    var textEl = document.createElement("div");
    textEl.className = "chat-msg__text";
    if (safeHtml) textEl.innerHTML = safeHtml;
    else if (safeText) textEl.textContent = safeText;
    body.appendChild(textEl);

    div.appendChild(avatar);
    div.appendChild(body);
    if ($messages) $messages.appendChild(div);
    scrollToBottom();

    return { root: div, body: body, text: textEl };
  }

  function addTypingIndicator() {
    removeTypingIndicator();
    var div = document.createElement("div");
    div.className = "chat-msg chat-msg--assistant";
    div.id = "typingIndicator";
    div.innerHTML = '<div class="chat-msg__avatar chat-msg__avatar--assistant"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg></div><div class="chat-msg__body"><div class="chat-typing"><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span></div></div>';
    if ($messages) $messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function removeTypingIndicator() {
    var el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  /* Progress UI — 부모 body에 붙임 */
  function addProgressUI(parentBody) {
    var container = document.createElement("div");
    container.className = "chat-progress";
    var bar = document.createElement("div");
    bar.className = "chat-progress__bar";
    var fill = document.createElement("div");
    fill.className = "chat-progress__fill chat-progress__fill--indeterminate";
    bar.appendChild(fill);
    container.appendChild(bar);
    var stepsEl = document.createElement("div");
    stepsEl.className = "chat-progress__steps";
    container.appendChild(stepsEl);
    parentBody.appendChild(container);
    scrollToBottom();

    return {
      container: container,
      fill: fill,
      stepsEl: stepsEl,
      setProgress: function (pct) {
        fill.classList.remove("chat-progress__fill--indeterminate");
        fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      },
      addStep: function (label, status) {
        var existingActive = stepsEl.querySelector(".chat-progress__step--active");
        if (existingActive && status !== "error") {
          existingActive.className = "chat-progress__step chat-progress__step--done";
          existingActive.innerHTML = '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' + escHtml(existingActive.dataset.label || "") + '</span>';
        }

        while (stepsEl.children.length > 6) {
          stepsEl.removeChild(stepsEl.firstChild);
        }

        var step = document.createElement("div");
        step.className = "chat-progress__step chat-progress__step--" + (status || "active");
        step.dataset.label = label;
        var icon;
        if (status === "done") icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
        else if (status === "error") icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        else icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor"><animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/></circle></svg>';
        step.innerHTML = '<span class="chat-progress__icon">' + icon + '</span><span>' + escHtml(label) + '</span>';
        stepsEl.appendChild(step);
        scrollToBottom();
        return step;
      },
      finish: function () {
        fill.classList.remove("chat-progress__fill--indeterminate");
        fill.style.width = "100%";
        fill.style.background = "var(--success)";
        
        var active = stepsEl.querySelector(".chat-progress__step--active");
        if (active) {
          active.className = "chat-progress__step chat-progress__step--done";
          active.innerHTML = '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' + escHtml(active.dataset.label || "") + '</span>';
        }
      }
    };
  }

  /* 어시스턴트 버블 보장 — 없으면 생성 */
  function ensureAssistantBubble() {
    if (!state.activeAssistantEl) {
      removeTypingIndicator();
      state.activeAssistantEl = createMsgEl("assistant", { text: "" });
    }
    return state.activeAssistantEl;
  }

  /* 프로그레스 보장 */
  function ensureProgressUI() {
    if (!state.activeProgressEl) {
      var bubble = ensureAssistantBubble();
      state.activeProgressEl = addProgressUI(bubble.body);
    }
    return state.activeProgressEl;
  }

  /* ─── WebSocket ─── */
  function buildWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + PREFIX + "/ws/chat";
  }

  function connectWS() {
  // Clear old handlers to prevent ghost callbacks
  if (state.ws) {
    if (
      state.ws.readyState === WebSocket.OPEN ||
      state.ws.readyState === WebSocket.CONNECTING
    )
      return;
    state.ws.onopen = null;
    state.ws.onclose = null;
    state.ws.onerror = null;
    state.ws.onmessage = null;
    state.ws = null;
  }

  try {
    state.ws = new WebSocket(buildWsUrl());
  } catch (e) {
    setWsUI(false);
    scheduleReconnect();
    return;
  }

  state.ws.onopen = function () {
    // Verify this is still the active WS
    if (this !== state.ws) return;
    setWsUI(true);
    state.reconnectAttempts = 0;
    console.log(
      "%c[WS] Connected",
      "background:#22c55e;color:white;padding:2px 6px;border-radius:3px;",
    );
  };

  state.ws.onclose = function () {
    if (this !== state.ws) return;
    setWsUI(false);
    scheduleReconnect();
  };

  state.ws.onerror = function () {
    if (this !== state.ws) return;
    setWsUI(false);
  };

  state.ws.onmessage = function (event) {
    if (this !== state.ws) return;
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    handleServerEvent(data);
  };
}

  function safeSendWs(obj) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    if (state.reconnectAttempts >= state.maxReconnect) return;
    var delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts), 30000);
    state.reconnectAttempts++;
    state.reconnectTimer = setTimeout(function () {
      state.reconnectTimer = null;
      connectWS();
    }, delay);
  }

  /* ─── Server Event Router ─── */
  function handleServerEvent(msg) {
    var type = (msg.type || msg.event || msg.action || msg.kind || "").toLowerCase().trim();
    var jobId = msg.job_id || msg.jobId || msg.id || null;
    var status = (msg.status || msg.state || "").toLowerCase();
    var textContent = extractTextFromMsg(msg);

    switch (type) {
      case "ready": case "ack": case "hello": case "connected": case "pong":
        break;

      case "assistant": case "response": case "answer": case "reply":
      case "chat_response": case "chat_reply":
        removeTypingIndicator();
        if (!textContent) break;
        if (state.activeAssistantEl) {
          state.streamBuffer += "\n" + textContent;
          state.activeAssistantEl.text.innerHTML = formatMarkdown(state.streamBuffer);
        } else {
          state.streamBuffer = textContent;
          state.activeAssistantEl = createMsgEl("assistant", { html: formatMarkdown(textContent) });
        }
        scrollToBottom();
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "assistant_start": case "stream_start":
        removeTypingIndicator();
        state.streamBuffer = "";
        state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        break;

      case "assistant_chunk": case "stream": case "chunk": case "delta": case "token":
        var chunk = textContent || msg.chunk || msg.delta || msg.token || "";
        if (!chunk) break;
        if (!state.activeAssistantEl) {
          removeTypingIndicator();
          state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        }
        state.streamBuffer += chunk;
        state.activeAssistantEl.text.innerHTML = formatMarkdown(state.streamBuffer);
        scrollToBottom();
        break;

      case "assistant_end": case "stream_end": case "done":
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "job_submitted": case "submitted": case "queued":
      case "job_created": case "job_queued":
        var jid = jobId || state.activeJobId;
        var jobSnap = msg.job || {};
        if (!jid && jobSnap.job_id) jid = jobSnap.job_id;
        if (!jid) break;
        state.activeJobId = jid;
        App.upsertJob({
            job_id: jid,
            status: "queued",
            submitted_at: Date.now() / 1000,
            updated_at: Date.now() / 1000,
            user_query: state.lastUserInput,
            molecule_name: jobSnap.molecule_name || msg.molecule_name || msg.molecule || (msg.payload ? msg.payload.molecule : "") || "",
            method: jobSnap.method || msg.method || (msg.payload ? msg.payload.method : "") || "",
            basis_set: jobSnap.basis_set || msg.basis_set || (msg.payload ? msg.payload.basis_set : "") || "",
        });
        App.setStatus("Job submitted", "running", "chat");
        var prog = ensureProgressUI();
        prog.addStep("Job submitted", "done");
        break;

      case "job_update": case "job_event": case "job_progress": case "progress":
      case "status": case "step": case "stage": case "computing": case "running":
        var jid2 = jobId || state.activeJobId;
        var progress = msg.progress != null ? msg.progress : (msg.percent != null ? msg.percent : (msg.pct != null ? msg.pct : null));
        var msgText = msg.message || textContent || "";
        var stepKey = msg.step || msg.stage || "";
        var detailText = msg.detail || msg.description || "";
        var combinedLabel = stepKey ? "[" + stepKey + "] " + (msgText || detailText || "Processing...") : (msgText || detailText || "Computing...");

        if (jid2) {
          App.upsertJob({ job_id: jid2, status: status || "running", updated_at: Date.now() / 1000, progress: progress });
        }

        var prog2 = ensureProgressUI();
        if (combinedLabel) {
          var stepStatus = (status === "failed" || status === "error") ? "error"
            : (status === "completed" || status === "done") ? "done" : "active";
          prog2.addStep(combinedLabel, stepStatus);
        }
        if (typeof progress === "number") {
          prog2.setProgress(progress);
        }

        App.setStatus(combinedLabel || "Computing...", "running", "chat");
        break;

      case "result":
        removeTypingIndicator();
        var rjid = jobId || state.activeJobId;
        var result = msg.result || msg.results || msg.data || msg.output || msg.computation || null;
        if (result && rjid) {
          App.upsertJob({
            job_id: rjid, status: "completed", result: result, updated_at: Date.now() / 1000,
            user_query: state.lastUserInput || (App.store.jobsById[rjid] ? App.store.jobsById[rjid].user_query : ""),
            molecule_name: result.structure_name || result.molecule_name || result.molecule || "",
            method: result.method || "",
            basis_set: result.basis || result.basis_set || "",
        });
          App.setActiveResult(result, { jobId: rjid, source: "chat" });
          App.setStatus("Completed", "success", "chat");

          var energy = result.total_energy_hartree != null ? result.total_energy_hartree : result.energy;
          if (energy != null) {
            var summary = "Computation complete. Total energy: " + Number(energy).toFixed(8) + " Hartree";
            if (result.molecule_name) summary = result.molecule_name + " \u2014 " + summary;
            createMsgEl("assistant", { html: formatMarkdown(summary) });
          }
        } else if (result) {
          App.setActiveResult(result, { source: "chat" });
          App.setStatus("Completed", "success", "chat");
        } else if (textContent) {
          createMsgEl("assistant", { html: formatMarkdown(textContent) });
        }

        state.activeProgressEl = null;
        state.activeAssistantEl = null;
        setSending(false);
        break;

      case "error": case "fail": case "failed": case "job_failed": case "job_error":
        removeTypingIndicator();
        var errMsg = "An error occurred";
        var cands = [msg.message, msg.error, msg.text, msg.detail, msg.reason, msg.description];
        for (var ci = 0; ci < cands.length; ci++) {
          var c = cands[ci];
          if (typeof c === "string" && c.length > 0) { errMsg = c; break; }
        }
        if (errMsg === "An error occurred") {
          for (var ci2 = 0; ci2 < cands.length; ci2++) {
            if (cands[ci2] && typeof cands[ci2] === "object") {
              var nested = extractReadableText(cands[ci2]);
              if (nested && nested !== "An error occurred" && nested !== "[data]") { errMsg = nested; break; }
            }
          }
        }
        /* 파이프 구분자 처리 (백엔드가 "msg|detail" 형태로 보내는 경우) */
        if (errMsg.indexOf("|") !== -1) {
          errMsg = errMsg.split("|").map(function(s){return s.trim();}).filter(Boolean).join(" — ");
        }

        createMsgEl("error", { text: errMsg });

        if (state.activeProgressEl) {
          state.activeProgressEl.addStep(errMsg, "error");
          state.activeProgressEl.fill.style.background = "var(--error)";
          state.activeProgressEl.fill.classList.remove("chat-progress__fill--indeterminate");
          state.activeProgressEl.fill.style.width = "100%";
          state.activeProgressEl = null;
        }

        var errJid = jobId || state.activeJobId;
        if (errJid) App.upsertJob({ job_id: errJid, status: "failed", updated_at: Date.now() / 1000 });
        App.setStatus("Error", "error", "chat");
        state.activeAssistantEl = null;
        setSending(false);
        break;

      default:
        /* Auto-detect */
        if (msg.result || msg.results || (msg.data && msg.data.total_energy_hartree)) {
          handleServerEvent(Object.assign({}, msg, { type: "result" })); return;
        }
        if (status === "completed" || status === "done" || status === "finished") {
          handleServerEvent(Object.assign({}, msg, { type: "result" })); return;
        }
        if (status === "running" || status === "computing" || status === "processing") {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" })); return;
        }
        if (status === "queued" || status === "submitted") {
          handleServerEvent(Object.assign({}, msg, { type: "job_submitted" })); return;
        }
        if (status === "failed" || status === "error") {
          handleServerEvent(Object.assign({}, msg, { type: "error" })); return;
        }
        if (jobId && (msg.progress != null || msg.step || msg.stage)) {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" })); return;
        }
        if (textContent) {
          removeTypingIndicator();
          createMsgEl("assistant", { html: formatMarkdown(textContent) });
          state.activeAssistantEl = null;
          state.streamBuffer = "";
          setSending(false);
          return;
        }
        break;
    }
  }

  /* ─── Submit ─── */
  function submitMessage(text) {
    text = (text || "").trim();
    if (!text || state.sending) return;

    setSending(true);
    state.lastUserInput = text;
    App.store.lastUserInput = text;

    createMsgEl("user", { text: text });
    App.addChatMessage({ role: "user", text: text, at: Date.now() });

    if ($suggestions) $suggestions.hidden = true;

    state.activeAssistantEl = null;
    state.activeProgressEl = null;
    state.streamBuffer = "";

    addTypingIndicator();

    var sent = safeSendWs({
      type: "chat",
      session_id: state.sessionId,
      message: text,
    });

    if (sent) return;

    removeTypingIndicator();
    fetch(PREFIX + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, message: text }),
    })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      if (data.type) handleServerEvent(data);
      else if (data.result) handleServerEvent(Object.assign({ type: "result" }, data));
      else {
        var t = extractTextFromMsg(data);
        handleServerEvent({ type: "assistant", text: t || JSON.stringify(data, null, 2) });
      }
    })
    .catch(function (err) {
      handleServerEvent({ type: "error", message: "Request failed: " + err.message });
    });
  }

  /* ─── Input ─── */
  if ($input) {
    $input.addEventListener("input", function () {
      if ($send) $send.disabled = state.sending || !$input.value.trim();
      $input.style.height = "auto";
      $input.style.height = Math.min($input.scrollHeight, 120) + "px";
    });
    $input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!state.sending && $input.value.trim()) {
          var val = $input.value;
          $input.value = "";
          $input.style.height = "auto";
          if ($send) $send.disabled = true;
          submitMessage(val);
        }
      }
    });
  }

  if ($form) {
    $form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.sending && $input && $input.value.trim()) {
        var val = $input.value;
        $input.value = "";
        $input.style.height = "auto";
        if ($send) $send.disabled = true;
        submitMessage(val);
      }
    });
  }

  if ($suggestions) {
    $suggestions.addEventListener("click", function (e) {
      var chip = e.target.closest(".suggestion-chip");
      if (!chip) return;
      var prompt = chip.dataset.prompt;
      if (prompt) submitMessage(prompt);
    });
  }

  connectWS();

  App.chat = {
    submit: submitMessage,
    connect: connectWS,
    getState: function () { return Object.assign({}, state, { ws: undefined }); },
  };
})();

```

### File: `web/static/results.js`
```js
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Results Module
   (Fixed: field name alignment with backend)
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var TAB_ORDER = [
    ["summary", "Summary"],
    ["geometry", "Geometry"],
    ["orbital", "Orbital"],
    ["esp", "ESP"],
    ["charges", "Charges"],
    ["json", "JSON"],
  ];

  var state = { result: null, jobId: null, activeTab: "summary", tabs: [] };

  var sessionResults = [];
  var activeSessionIdx = -1;

  function buildResultLabel(result, index) {
    var mol = result.molecule_name || result.structure_name || "Mol";
    var type = "";

    if (result.optimization_performed) {
      type = "Opt";
    } else if (result.orbital_cube_b64 || result.orbital_cube) {
      var orbs = result.orbitals || [];
      var selIdx = 0;
      for (var i = 0; i < orbs.length; i++) {
        if (orbs[i] && orbs[i].is_selected) { selIdx = i; break; }
      }
      var orbLabel = (orbs[selIdx] && orbs[selIdx].label) || "MO";
      type = orbLabel;
    } else if (result.esp_cube_b64 || result.esp_cube) {
      type = "ESP";
    } else {
      type = result.method || "SCF";
    }
    return "#" + index + " " + mol + " " + type;
  }

  function renderSessionTabs() {
    var $bar = document.getElementById("sessionTabBar");
    if (!$bar) return;
    $bar.innerHTML = "";
    $bar.hidden = sessionResults.length <= 1;

    for (var i = 0; i < sessionResults.length; i++) {
      (function(idx) {
        var entry = sessionResults[idx];
        var $tab = document.createElement("button");
        $tab.className = "session-tab" + (idx === activeSessionIdx ? " active" : "");
        $tab.textContent = entry.label;
        $tab.title = new Date(entry.timestamp).toLocaleTimeString();
        $tab.setAttribute("data-idx", idx);

        $tab.addEventListener("click", function () {
          switchToSessionResult(idx);
        });

        var $close = document.createElement("span");
        $close.className = "session-tab-close";
        $close.textContent = "×";
        $close.title = "이 결과 닫기";
        $close.addEventListener("click", function (e) {
          e.stopPropagation();
          removeSessionResult(idx);
        });

        $tab.appendChild($close);
        $bar.appendChild($tab);
      })(i);
    }
  }

  function switchToSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    if (idx === activeSessionIdx) return;
    activeSessionIdx = idx;
    var entry = sessionResults[idx];
    state.result = entry.result;
    state.jobId = entry.jobId;
    
    var available = getAvailableTabs(entry.result);
    state.tabs = available;
    if (available.indexOf(state.activeTab) === -1) {
        state.activeTab = decideFocusTab(entry.result, available);
    }
    
    renderSessionTabs();
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, entry.result);
    App.emit("result:switched", { result: entry.result, jobId: entry.jobId });
  }

  function removeSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    sessionResults.splice(idx, 1);
    if (sessionResults.length === 0) {
      activeSessionIdx = -1;
      state.result = null;
      state.jobId = null;
      renderSessionTabs();
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      App.emit("result:cleared");
      return;
    }
    if (idx === activeSessionIdx) {
      activeSessionIdx = Math.min(idx, sessionResults.length - 1);
      var entry = sessionResults[activeSessionIdx];
      state.result = entry.result;
      state.jobId = entry.jobId;
      var available = getAvailableTabs(entry.result);
      state.tabs = available;
      if (available.indexOf(state.activeTab) === -1) {
          state.activeTab = decideFocusTab(entry.result, available);
      }
      renderTabs(available, state.activeTab);
      renderContent(state.activeTab, entry.result);
    } else if (idx < activeSessionIdx) {
      activeSessionIdx--;
    }
    renderSessionTabs();
  }



  var $tabs = document.getElementById("resultsTabs");
  var $content = document.getElementById("resultsContent");
  var $empty = document.getElementById("resultsEmpty");

  function normalizeResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    var r = App.clone(raw);

    /* ── energy aliases ── */
    if (r.total_energy_hartree == null && r.energy != null)
      r.total_energy_hartree = r.energy;

    /* ── visualization normalization ── */
    if (!r.visualization) r.visualization = {};
    var viz = r.visualization;

    /* Backend sends viz.xyz and viz.molecule_xyz, NOT viz.xyz_block */
    if (!viz.xyz_block) {
      viz.xyz_block =
        viz.xyz || viz.molecule_xyz || r.xyz_block || r.xyz || null;
    }

    if (!viz.orbital_cube_b64 && r.orbital_cube_b64)
      viz.orbital_cube_b64 = r.orbital_cube_b64;
    if (!viz.orbital_info && r.orbital_info) viz.orbital_info = r.orbital_info;
    if (!viz.esp_cube_b64 && r.esp_cube_b64) viz.esp_cube_b64 = r.esp_cube_b64;
    if (!viz.density_cube_b64 && r.density_cube_b64)
      viz.density_cube_b64 = r.density_cube_b64;

    /* ── orbital sub-objects ── */
    if (!viz.orbital_cube_b64 && viz.orbital && viz.orbital.cube_b64) {
      viz.orbital_cube_b64 = viz.orbital.cube_b64;
    }
    if (!viz.esp_cube_b64 && viz.esp && viz.esp.cube_b64) {
      viz.esp_cube_b64 = viz.esp.cube_b64;
    }
    if (!viz.density_cube_b64 && viz.density && viz.density.cube_b64) {
      viz.density_cube_b64 = viz.density.cube_b64;
    }

    /* ── selected_orbital → orbital_info ── */
    if (!viz.orbital_info && r.selected_orbital) {
      viz.orbital_info = r.selected_orbital;
    }

    /* ── charges: backend returns [{atom_index, symbol, charge}, ...] ── */
    /* Normalize to parallel arrays for easy rendering */
    if (
      r.mulliken_charges &&
      r.mulliken_charges.length &&
      typeof r.mulliken_charges[0] === "object"
    ) {
      r._mulliken_raw = r.mulliken_charges;
      r.mulliken_charges = r.mulliken_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.lowdin_charges &&
      r.lowdin_charges.length &&
      typeof r.lowdin_charges[0] === "object"
    ) {
      r._lowdin_raw = r.lowdin_charges;
      r.lowdin_charges = r.lowdin_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.partial_charges &&
      r.partial_charges.length &&
      typeof r.partial_charges[0] === "object"
    ) {
      r.partial_charges = r.partial_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }

    /* ── fallback aliases for old-style keys ── */
    if (!r.mulliken_charges && r.charges) r.mulliken_charges = r.charges;
    if (!r.atoms && r.geometry) r.atoms = r.geometry;

    /* ── Build mo_energies / mo_occupations from orbitals array ── */
    if (
      (!r.mo_energies || !r.mo_energies.length) &&
      r.orbitals &&
      r.orbitals.length
    ) {
      var sorted = r.orbitals.slice().sort(function (a, b) {
        return a.zero_based_index - b.zero_based_index;
      });
      r.mo_energies = sorted.map(function (o) {
        return o.energy_hartree;
      });
      r.mo_occupations = sorted.map(function (o) {
        return o.occupancy;
      });
      r._orbital_index_offset = sorted[0] ? sorted[0].zero_based_index : 0;
      r._orbital_labels = sorted.map(function (o) {
        return o.label;
      });
    }

    return r;
  }

  function getAvailableTabs(r) {
    if (!r) return [];
    var a = ["summary"];
    var viz = r.visualization || {};
    
    if (viz.xyz_block || (r.atoms && r.atoms.length)) a.push("geometry");
    
    if (
      viz.orbital_cube_b64 ||
      (r.mo_energies && r.mo_energies.length) ||
      (r.orbitals && r.orbitals.length)
    ) a.push("orbital");
    
    if (viz.esp_cube_b64) a.push("esp");
    
    // Sometimes backend returns single float or object instead of arrays, 
    // or array of objects [{charge: 0.1}, ...]
    // Better to check if the property exists and has elements/keys.
    var hasMulliken = r.mulliken_charges && Object.keys(r.mulliken_charges).length > 0;
    var hasLowdin = r.lowdin_charges && Object.keys(r.lowdin_charges).length > 0;
    
    if (hasMulliken || hasLowdin) a.push("charges");
    
    a.push("json");
    return a;
  }

  function decideFocusTab(r, a) {
    /* Use backend's advisor_focus_tab if valid */
    var advised =
      r.advisor_focus_tab ||
      r.default_tab ||
      (r.visualization &&
        r.visualization.defaults &&
        r.visualization.defaults.focus_tab);
    if (advised && a.indexOf(advised) !== -1) return advised;
    if (a.indexOf("orbital") !== -1) return "orbital";
    if (a.indexOf("esp") !== -1) return "esp";
    if (a.indexOf("geometry") !== -1) return "geometry";
    return "summary";
  }

  function renderTabs(available, active) {
    if (!$tabs) return;
    $tabs.innerHTML = "";
    TAB_ORDER.forEach(function (pair) {
      if (available.indexOf(pair[0]) === -1) return;
      var btn = document.createElement("button");
      btn.className =
        "tab-btn" + (pair[0] === active ? " tab-btn--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("data-tab", pair[0]);
      btn.textContent = pair[1];
      btn.addEventListener("click", function () {
        switchTab(pair[0]);
      });
      $tabs.appendChild(btn);
    });
  }

  function switchTab(key) {
    if (key === state.activeTab) return;
    state.activeTab = key;
    if ($tabs)
      $tabs.querySelectorAll(".tab-btn").forEach(function (b) {
        b.classList.toggle("tab-btn--active", b.dataset.tab === key);
      });
    renderContent(key, state.result);
    saveSnapshot();
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function metric(label, value, unit) {
    return (
      '<div class="result-metric"><span class="result-metric__label">' +
      esc(label) +
      '</span><span class="result-metric__value">' +
      esc(String(value)) +
      (unit
        ? '<span class="result-metric__unit"> ' + esc(unit) + "</span>"
        : "") +
      "</span></div>"
    );
  }

  function renderContent(tab, r) {
    if (!r || !$content) {
      if ($content) $content.innerHTML = "";
      return;
    }
    var html = '<div class="result-card">';
    switch (tab) {
      case "summary":
        html += renderSummary(r);
        break;
      case "geometry":
        html += renderGeometry(r);
        break;
      case "orbital":
        html += renderOrbital(r);
        break;
      case "esp":
        html += renderESP(r);
        break;
      case "charges":
        html += renderCharges(r);
        break;
      case "json":
        html += renderJSON(r);
        break;
    }
    html += "</div>";
    $content.innerHTML = html;
  }

    function renderSummary(r) {
    var html = '<div class="metrics-grid">';
    var has = false;
    var m = [];

    if (r.structure_name || r.molecule_name || r.molecule)
      m.push([
        "Molecule",
        r.structure_name || r.molecule_name || r.molecule,
        "",
      ]);
    if (r.formula) m.push(["Formula", r.formula, ""]);
    if (r.method) m.push(["Method", r.method, ""]);
    /* Backend sends "basis", not "basis_set" */
    if (r.basis || r.basis_set)
      m.push(["Basis Set", r.basis || r.basis_set, ""]);
    if (r.n_atoms != null) m.push(["Atoms", r.n_atoms, ""]);
    if (r.scf_converged != null)
      m.push(["SCF Converged", r.scf_converged ? "Yes" : "No", ""]);

    if (r.total_energy_hartree != null)
      m.push(["Total Energy", Number(r.total_energy_hartree).toFixed(8), "Ha"]);
    if (r.total_energy_ev != null)
      m.push(["Energy", Number(r.total_energy_ev).toFixed(4), "eV"]);

    /* Backend sends homo_energy_hartree / homo_energy_ev, NOT homo_energy */
    if (r.homo_energy_hartree != null)
      m.push(["HOMO", Number(r.homo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.homo_energy != null)
      m.push(["HOMO", Number(r.homo_energy).toFixed(6), "Ha"]);

    if (r.lumo_energy_hartree != null)
      m.push(["LUMO", Number(r.lumo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.lumo_energy != null)
      m.push(["LUMO", Number(r.lumo_energy).toFixed(6), "Ha"]);

    /* Backend sends orbital_gap_hartree / orbital_gap_ev, NOT homo_lumo_gap */
    if (r.orbital_gap_hartree != null)
      m.push(["HOMO-LUMO Gap", Number(r.orbital_gap_hartree).toFixed(6), "Ha"]);
    else if (r.homo_lumo_gap != null)
      m.push(["HOMO-LUMO Gap", Number(r.homo_lumo_gap).toFixed(6), "Ha"]);

    if (r.orbital_gap_ev != null)
      m.push(["H-L Gap", Number(r.orbital_gap_ev).toFixed(4), "eV"]);
    else if (r.homo_lumo_gap_ev != null)
      m.push(["H-L Gap", Number(r.homo_lumo_gap_ev).toFixed(4), "eV"]);

    if (r.dipole_moment != null) {
      var dm;
      if (
        typeof r.dipole_moment === "object" &&
        r.dipole_moment.magnitude != null
      ) {
        dm = Number(r.dipole_moment.magnitude).toFixed(4);
      } else if (Array.isArray(r.dipole_moment)) {
        dm = r.dipole_moment
          .map(function (v) {
            return Number(v).toFixed(4);
          })
          .join(", ");
      } else {
        dm = Number(r.dipole_moment).toFixed(4);
      }
      m.push(["Dipole Moment", dm, "Debye"]);
    }

    m.forEach(function (x) {
      html += metric(x[0], x[1], x[2]);
      has = true;
    });
    html += "</div>";
    if (!has)
      html =
        '<p class="result-note">No summary data available. Check the JSON tab.</p>';
    return html;
  }

  function renderGeometry(r) {
    var atoms = r.atoms || [];
    if (!atoms.length && !r.visualization.xyz_block)
      return '<p class="result-note">No geometry data.</p>';
    var html = "";

    /* Geometry summary from backend */
    var gs = r.geometry_summary;
    if (gs) {
      html += '<div class="metrics-grid" style="margin-bottom:var(--sp-4)">';
      if (gs.formula) html += metric("Formula", gs.formula, "");
      if (gs.n_atoms != null) html += metric("Atoms", gs.n_atoms, "");
      if (gs.bond_count != null) html += metric("Bonds", gs.bond_count, "");
      if (gs.bond_length_mean_angstrom != null)
        html += metric(
          "Avg Bond",
          Number(gs.bond_length_mean_angstrom).toFixed(4),
          "\u00C5",
        );
      html += "</div>";
    }

    if (atoms.length) {
      html +=
        '<table class="result-table"><thead><tr><th>#</th><th>Element</th><th>X (\u00C5)</th><th>Y (\u00C5)</th><th>Z (\u00C5)</th></tr></thead><tbody>';
      atoms.forEach(function (a, i) {
        var el = a.element || a.symbol || a[0] || "?";
        html +=
          "<tr><td>" +
          (i + 1) +
          "</td><td>" +
          esc(el) +
          "</td><td>" +
          Number(a.x != null ? a.x : a[1] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.y != null ? a.y : a[2] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.z != null ? a.z : a[3] || 0).toFixed(6) +
          "</td></tr>";
      });
      html += "</tbody></table>";
    }
    if (r.visualization.xyz_block) {
      html +=
        '<details style="margin-top:var(--sp-4)"><summary>Raw XYZ Block</summary><pre class="result-json" style="margin-top:var(--sp-2)">' +
        esc(r.visualization.xyz_block) +
        "</pre></details>";
    }
    return html;
  }

  function renderOrbital(r) {
    var info =
      (r.visualization && r.visualization.orbital_info) ||
      r.selected_orbital ||
      r.orbital_info ||
      {};
    var html = '<div class="metrics-grid">';
    if (info.label) html += metric("Selected", info.label, "");
    if (info.energy_hartree != null)
      html += metric("Energy", Number(info.energy_hartree).toFixed(6), "Ha");
    if (info.energy_ev != null)
      html += metric("Energy", Number(info.energy_ev).toFixed(4), "eV");
    if (info.occupancy != null) html += metric("Occupancy", info.occupancy, "");
    if (info.spin) html += metric("Spin", info.spin, "");
    html += "</div>";

    /* Use orbitals array from backend if available */
    var orbitals = r.orbitals || [];
    var moE = r.mo_energies || [];
    var moO = r.mo_occupations || [];
    var offset = r._orbital_index_offset || 0;
    var labels = r._orbital_labels || [];

    if (orbitals.length > 0 || moE.length > 0) {
      html +=
        '<div class="energy-diagram"><div class="energy-diagram__title">MO Energy Levels</div>';

      if (orbitals.length > 0 && moE.length === 0) {
        /* Render directly from orbitals array */
        orbitals.forEach(function (orb) {
          var occ = orb.occupancy || 0;
          var cls = "energy-level";
          var lbl = orb.label || "MO " + orb.index;
          if (lbl === "HOMO") cls += " energy-level--homo";
          else if (lbl === "LUMO") cls += " energy-level--lumo";
          else if (occ > 0) cls += " energy-level--occupied";
          else cls += " energy-level--virtual";
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(orb.energy_hartree).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        });
      } else {
        /* Legacy path: mo_energies + mo_occupations arrays */
        var homoIdx = -1;
        for (var i = 0; i < moE.length; i++) {
          if (moO[i] != null && moO[i] > 0) homoIdx = i;
        }
        var lumoIdx =
          homoIdx >= 0 && homoIdx + 1 < moE.length ? homoIdx + 1 : -1;
        var start = moE.length > 16 ? Math.max(0, homoIdx - 5) : 0;
        var end =
          moE.length > 16
            ? Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 6)
            : moE.length;
        for (var j = start; j < end; j++) {
          var realIdx = j + offset;
          var occ = moO[j] != null ? moO[j] : 0;
          var cls = "energy-level";
          var lbl = labels[j] || "MO " + realIdx;
          if (lbl === "HOMO") {
            cls += " energy-level--homo";
          } else if (lbl === "LUMO") {
            cls += " energy-level--lumo";
          } else if (lbl.indexOf("HOMO") === 0) {
            cls += " energy-level--occupied";
          } else if (lbl.indexOf("LUMO") === 0) {
            cls += " energy-level--virtual";
          } else if (occ > 0) {
            cls += " energy-level--occupied";
          } else {
            cls += " energy-level--virtual";
          }
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(moE[j]).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        }
      }
      html += "</div>";
    }
    html +=
      '<p class="result-note">The orbital is rendered in the 3D viewer. Use the controls to adjust isosurface and select orbitals.</p>';
    return html;
  }

  function renderESP(r) {
    var html = '<div class="metrics-grid">';
    if (r.esp_auto_range_au != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_au).toFixed(4),
        "a.u.",
      );
    }
    if (r.esp_auto_range_kcal != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_kcal).toFixed(2),
        "kcal/mol",
      );
    }
    if (r.esp_preset) {
      html += metric("Color Scheme", r.esp_preset, "");
    }
    /* Legacy */
    if (r.esp_range && !r.esp_auto_range_au) {
      html +=
        metric("ESP Min", Number(r.esp_range[0]).toFixed(4), "a.u.") +
        metric("ESP Max", Number(r.esp_range[1]).toFixed(4), "a.u.");
    }
    html += '</div>';
    html +=
      '<p class="result-note">The ESP surface is rendered in the 3D viewer. Use the Isosurface slider to adjust the electron density level and the Opacity slider for transparency.</p>';
    return html;

  }

  function renderCharges(r) {
  var mullRaw = r.mulliken_charges || {};
  var lowdRaw = r.lowdin_charges || {};
  var mull = Array.isArray(mullRaw) ? mullRaw : Object.values(mullRaw);
  var lowd = Array.isArray(lowdRaw) ? lowdRaw : Object.values(lowdRaw);
  var atoms = r.atoms || [];
  if (!mull.length && !lowd.length)
    return '<p class="result-note">No charge data.</p>';

  var primary = mull.length ? mull : lowd;
  var secondary = mull.length && lowd.length ? lowd : null;
  var primaryLabel = mull.length ? "Mulliken" : "Löwdin";
  var secondaryLabel = secondary ? "Löwdin" : null;

  function chargeVal(arr, i) {
    var v = arr[i];
    if (v == null) return null;
    if (typeof v === "object") return v.charge != null ? Number(v.charge) : null;
    return Number(v);
  }

  var maxAbs = 0;
  var n = Math.max(primary.length, secondary ? secondary.length : 0);
  for (var i = 0; i < n; i++) {
    var pv = chargeVal(primary, i);
    if (pv != null && Math.abs(pv) > maxAbs) maxAbs = Math.abs(pv);
    if (secondary) {
      var sv = chargeVal(secondary, i);
      if (sv != null && Math.abs(sv) > maxAbs) maxAbs = Math.abs(sv);
    }
  }
  if (maxAbs < 0.0001) maxAbs = 0.5;
  var plotMax = maxAbs;

  var html = "";

  html += '<div class="butterfly-legend">';
  html += '<span class="butterfly-legend__item">' +
    '<span class="butterfly-legend__swatch butterfly-legend__swatch--neg"></span>' +
    'Negative (−)</span>';
  html += '<span class="butterfly-legend__item">' +
    '<span class="butterfly-legend__swatch butterfly-legend__swatch--pos"></span>' +
    'Positive (+)</span>';
  if (secondary) {
    html += '<span class="butterfly-legend__item" style="margin-left:auto;">' +
      '<span style="font-size:11px;color:var(--text-3);">' +
      '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent);margin-right:4px;"></span>' +
      primaryLabel +
      ' &nbsp; <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent-2);margin-right:4px;"></span>' +
      secondaryLabel +
      '</span></span>';
  }
  html += '</div>';

  html += '<div class="butterfly-chart">';

  for (var i = 0; i < n; i++) {
    var el = atoms[i]
      ? (atoms[i].element || atoms[i].symbol || atoms[i][0] || "?")
      : "?";

    var pv = chargeVal(primary, i);
    var sv = secondary ? chargeVal(secondary, i) : null;

    html += '<div class="butterfly-row">';

    html += '<div class="butterfly-bar-area butterfly-bar-area--neg">';
    if (pv != null && pv < 0) {
      var pctP = (Math.abs(pv) / plotMax * 100).toFixed(1);
      html += '<div class="butterfly-bar butterfly-bar--neg-primary" ' +
        'style="width:' + pctP + '%" ' +
        'title="' + primaryLabel + ': ' + pv.toFixed(6) + '">' +
        '<span class="butterfly-bar__val">' + pv.toFixed(4) + '</span>' +
        '</div>';
    }
    if (sv != null && sv < 0) {
      var pctS = (Math.abs(sv) / plotMax * 100).toFixed(1);
      html += '<div class="butterfly-bar butterfly-bar--neg-secondary" ' +
        'style="width:' + pctS + '%" ' +
        'title="' + secondaryLabel + ': ' + sv.toFixed(6) + '"></div>';
    }
    html += '</div>';

    html += '<div class="butterfly-label">' +
      '<span class="butterfly-label__idx">' + (i + 1) + '</span>' +
      '<span class="butterfly-label__el">' + esc(el) + '</span>' +
      '</div>';

    html += '<div class="butterfly-bar-area butterfly-bar-area--pos">';
    if (pv != null && pv >= 0) {
      var pctP = (Math.abs(pv) / plotMax * 100).toFixed(1);
      html += '<div class="butterfly-bar butterfly-bar--pos-primary" ' +
        'style="width:' + pctP + '%" ' +
        'title="' + primaryLabel + ': ' + (pv >= 0 ? "+" : "") + pv.toFixed(6) + '">' +
        '<span class="butterfly-bar__val">+' + pv.toFixed(4) + '</span>' +
        '</div>';
    }
    if (sv != null && sv >= 0) {
      var pctS = (Math.abs(sv) / plotMax * 100).toFixed(1);
      html += '<div class="butterfly-bar butterfly-bar--pos-secondary" ' +
        'style="width:' + pctS + '%" ' +
        'title="' + secondaryLabel + ': +' + sv.toFixed(6) + '"></div>';
    }
    html += '</div>';

    html += '</div>'; 
  }

  html += '</div>'; 

  html += '<details style="margin-top:var(--sp-4)">';
  html += '<summary>Detailed Charge Table</summary>';
  html += '<table class="result-table" style="margin-top:var(--sp-2)"><thead><tr>' +
    '<th>#</th><th>Element</th>';
  if (mull.length) html += '<th>Mulliken</th>';
  if (lowd.length) html += '<th>Löwdin</th>';
  html += '</tr></thead><tbody>';
  for (var i = 0; i < n; i++) {
    var el = atoms[i]
      ? (atoms[i].element || atoms[i].symbol || atoms[i][0] || "?")
      : "?";
    html += '<tr><td>' + (i + 1) + '</td><td>' + esc(el) + '</td>';
    if (mull.length) {
      var mv = chargeVal(mull, i);
      html += '<td>' + (mv != null ? mv.toFixed(6) : '—') + '</td>';
    }
    if (lowd.length) {
      var lv = chargeVal(lowd, i);
      html += '<td>' + (lv != null ? lv.toFixed(6) : '—') + '</td>';
    }
    html += '</tr>';
  }
  html += '</tbody></table></details>';

  return html;
}

  function renderJSON(r) {
    var json;
    /* Remove huge base64 fields for readability */
    var cleaned = App.clone(r);
    var viz = cleaned.visualization || {};
    if (viz.orbital_cube_b64)
      viz.orbital_cube_b64 =
        "[base64 data omitted, " + viz.orbital_cube_b64.length + " chars]";
    if (viz.esp_cube_b64)
      viz.esp_cube_b64 =
        "[base64 data omitted, " + viz.esp_cube_b64.length + " chars]";
    if (viz.density_cube_b64)
      viz.density_cube_b64 =
        "[base64 data omitted, " + viz.density_cube_b64.length + " chars]";
    if (cleaned.orbital_cube_b64) cleaned.orbital_cube_b64 = "[omitted]";
    if (cleaned.esp_cube_b64) cleaned.esp_cube_b64 = "[omitted]";
    if (cleaned.density_cube_b64) cleaned.density_cube_b64 = "[omitted]";
    if (viz.orbital && viz.orbital.cube_b64) viz.orbital.cube_b64 = "[omitted]";
    if (viz.esp && viz.esp.cube_b64) viz.esp.cube_b64 = "[omitted]";
    if (viz.density && viz.density.cube_b64) viz.density.cube_b64 = "[omitted]";
    delete cleaned._mulliken_raw;
    delete cleaned._lowdin_raw;
    delete cleaned._orbital_index_offset;
    delete cleaned._orbital_labels;
    try {
      json = JSON.stringify(cleaned, null, 2);
    } catch (_) {
      json = String(r);
    }
    return '<pre class="result-json">' + esc(json) + "</pre>";
  }

  function saveSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(
      state.jobId,
      Object.assign({}, existing, {
        activeTab: state.activeTab,
        timestamp: Date.now(),
      }),
    );
  }

  function restoreSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (snap && snap.activeTab) state.activeTab = snap.activeTab;
  }

  function update(result, jobId, source) {
    var normalized = normalizeResult(result);
    
    if (normalized) {
      var label = buildResultLabel(normalized, sessionResults.length + 1);
      var entry = {
        id: jobId || ("local-" + Date.now()),
        label: label,
        result: normalized,
        jobId: jobId,
        timestamp: Date.now(),
      };
      
      // Check if it's an update to an existing job in the session
      var existingIdx = -1;
      if (jobId) {
          for(var i=0; i<sessionResults.length; i++){
              if (sessionResults[i].jobId === jobId) { existingIdx = i; break; }
          }
      }
      
      if (existingIdx >= 0) {
          sessionResults[existingIdx] = entry;
          if (activeSessionIdx === existingIdx) {
              state.result = normalized;
          }
      } else {
          sessionResults.push(entry);
          activeSessionIdx = sessionResults.length - 1;
          state.result = normalized;
          state.jobId = jobId || null;
      }
    } else {
        state.result = null;
        state.jobId = null;
    }
    
    renderSessionTabs();
    if (!normalized) {
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      return;
    }
    if ($empty) $empty.hidden = true;
    var available = getAvailableTabs(normalized);
    state.tabs = available;
    if (source === "history" && jobId) {
      restoreSnapshot(jobId);
      if (available.indexOf(state.activeTab) === -1)
        state.activeTab = decideFocusTab(normalized, available);
    } else {
      state.activeTab = decideFocusTab(normalized, available);
    }
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, normalized);
    saveSnapshot();
  }

  App.on("result:changed", function (d) {
    update(d.result, d.jobId, d.source);
  });

  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var num = parseInt(e.key, 10);
    if (
      num >= 1 &&
      num <= 6 &&
      state.tabs.length > 0 &&
      num - 1 < state.tabs.length
    ) {
      switchTab(state.tabs[num - 1]);
    }
  });

  App.results = {
    getState: function () {
      return Object.assign({}, state);
    },
    switchTab: switchTab,
  };
})();
```

### File: `web/static/style.css`
```css
html, body { height: 100vh; overflow: hidden; }
/* ═══════════════════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Design System
   ═══════════════════════════════════════════════════════ */

:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-full: 9999px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-8: 32px; --sp-10: 40px;
  --blur-sm: 8px; --blur-md: 16px; --blur-lg: 32px; --blur-xl: 48px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-smooth: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 120ms; --duration-base: 200ms; --duration-slow: 350ms;
  --z-base: 1; --z-sticky: 10; --z-controls: 20; --z-overlay: 100; --z-modal: 1000;
}

[data-theme="dark"] {
  --bg-0: #09090b; --bg-1: #0c0c0f; --bg-2: #111115; --bg-3: #18181b; --bg-4: #1f1f23; --bg-5: #27272a;
  --surface-0: rgba(17,17,21,0.72); --surface-1: rgba(24,24,27,0.65);
  --surface-2: rgba(31,31,35,0.60); --surface-raised: rgba(39,39,42,0.55);
  --surface-overlay: rgba(9,9,11,0.88);
  --border-0: rgba(255,255,255,0.06); --border-1: rgba(255,255,255,0.09);
  --border-2: rgba(255,255,255,0.12); --border-3: rgba(255,255,255,0.16);
  --border-focus: rgba(99,102,241,0.5);
  --text-0: #fafafa; --text-1: #e4e4e7; --text-2: #a1a1aa; --text-3: #71717a; --text-4: #52525b;
  --accent: #6366f1; --accent-hover: #818cf8;
  --accent-muted: rgba(99,102,241,0.15); --accent-subtle: rgba(99,102,241,0.08); --accent-2: #8b5cf6;
  --success: #22c55e; --success-muted: rgba(34,197,94,0.12);
  --warning: #f59e0b; --warning-muted: rgba(245,158,11,0.12);
  --error: #ef4444; --error-muted: rgba(239,68,68,0.12);
  --info: #3b82f6; --info-muted: rgba(59,130,246,0.12);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3); --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.5); --shadow-xl: 0 24px 64px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.06);
  color-scheme: dark;
}

[data-theme="light"] {
  --bg-0: #ffffff; --bg-1: #fafafa; --bg-2: #f4f4f5; --bg-3: #e4e4e7; --bg-4: #d4d4d8; --bg-5: #a1a1aa;
  --surface-0: rgba(255,255,255,0.82); --surface-1: rgba(250,250,250,0.78);
  --surface-2: rgba(244,244,245,0.72); --surface-raised: rgba(255,255,255,0.92);
  --surface-overlay: rgba(255,255,255,0.92);
  --border-0: rgba(0,0,0,0.05); --border-1: rgba(0,0,0,0.08);
  --border-2: rgba(0,0,0,0.12); --border-3: rgba(0,0,0,0.16);
  --border-focus: rgba(99,102,241,0.4);
  --text-0: #09090b; --text-1: #18181b; --text-2: #52525b; --text-3: #71717a; --text-4: #a1a1aa;
  --accent: #6366f1; --accent-hover: #4f46e5;
  --accent-muted: rgba(99,102,241,0.10); --accent-subtle: rgba(99,102,241,0.05); --accent-2: #7c3aed;
  --success: #16a34a; --success-muted: rgba(22,163,74,0.08);
  --warning: #d97706; --warning-muted: rgba(217,119,6,0.08);
  --error: #dc2626; --error-muted: rgba(220,38,38,0.08);
  --info: #2563eb; --info-muted: rgba(37,99,235,0.08);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04); --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.08); --shadow-xl: 0 24px 64px rgba(0,0,0,0.10);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.03);
  color-scheme: light;
}

/* Reset */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;}
html{font-family:var(--font-sans);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;scroll-behavior:smooth;}
body{background:var(--bg-0);color:var(--text-1);min-height:100dvh;overflow-x:hidden;transition:background var(--duration-slow) var(--ease-smooth),color var(--duration-base) var(--ease-smooth);}
a{color:var(--accent);text-decoration:none;transition:color var(--duration-fast);}a:hover{color:var(--accent-hover);}
::selection{background:var(--accent-muted);color:var(--text-0);}
:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px;}
::-webkit-scrollbar{width:6px;height:6px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:var(--radius-full);}::-webkit-scrollbar-thumb:hover{background:var(--text-4);}

/* App Shell */
.app-shell { display: grid; gap: 18px; padding: 18px; height: 100vh; overflow: hidden; box-sizing: border-box; }

/* Top Bar */
.topbar{display:flex;align-items:center;justify-content:space-between;height:52px;padding:0 var(--sp-4);background:var(--surface-0);backdrop-filter:blur(var(--blur-lg));-webkit-backdrop-filter:blur(var(--blur-lg));border:1px solid var(--border-0);border-radius:var(--radius-lg);position:sticky;top:var(--sp-3);z-index:var(--z-sticky);transition:box-shadow var(--duration-base) var(--ease-out);}
.topbar:hover{box-shadow:var(--shadow-sm);}
.topbar__left,.topbar__center,.topbar__right{display:flex;align-items:center;gap:var(--sp-3);}
.topbar__left{flex:1;}.topbar__center{flex:0 0 auto;}.topbar__right{flex:1;justify-content:flex-end;}
.topbar__logo{display:flex;align-items:center;gap:var(--sp-2);}
.topbar__title{font-weight:600;font-size:15px;color:var(--text-0);letter-spacing:-0.02em;}
.topbar__badge{font-size:10px;font-weight:600;padding:1px 6px;border-radius:var(--radius-full);background:var(--accent-muted);color:var(--accent);letter-spacing:0.02em;text-transform:uppercase;vertical-align:super;}

/* Status */
.status-indicator{display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-1) var(--sp-3);border-radius:var(--radius-full);background:var(--surface-1);border:1px solid var(--border-0);font-size:12px;color:var(--text-2);user-select:none;}
.status-indicator__dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:background var(--duration-base),box-shadow var(--duration-base);}
.status-indicator__dot[data-kind="idle"]{background:var(--text-4);}
.status-indicator__dot[data-kind="running"],.status-indicator__dot[data-kind="computing"]{background:var(--info);box-shadow:0 0 8px rgba(59,130,246,0.4);animation:pulse-dot 1.5s ease-in-out infinite;}
.status-indicator__dot[data-kind="success"],.status-indicator__dot[data-kind="completed"]{background:var(--success);box-shadow:0 0 8px rgba(34,197,94,0.3);}
.status-indicator__dot[data-kind="error"],.status-indicator__dot[data-kind="failed"]{background:var(--error);box-shadow:0 0 8px rgba(239,68,68,0.3);}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.5;transform:scale(1.4);}}

/* Buttons */
.icon-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:1px solid var(--border-1);border-radius:var(--radius-md);background:transparent;color:var(--text-2);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);flex-shrink:0;}
.icon-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);transform:translateY(-1px);}
.icon-btn:active{transform:translateY(0);}
.icon-btn--sm{width:28px;height:28px;}
[data-theme="dark"] .icon-moon{display:none;}[data-theme="light"] .icon-sun{display:none;}
.chip-btn{display:inline-flex;align-items:center;gap:var(--sp-1);height:28px;padding:0 var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-2);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.chip-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);}
.icon-btn.is-spinning svg{animation:spin 0.6s linear infinite;}
@keyframes spin{from{transform:rotate(0deg);}to{transform:rotate(360deg);}}

/* Dashboard Grid — 뷰어 최소 55% 면적 보장 */
.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: minmax(450px, 1.8fr) minmax(180px, 0.6fr);
  grid-template-areas: "viewer chat" "results history";
  gap: var(--sp-3);
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.panel--results,
.panel--history {
  max-height: 45vh;
  overflow: hidden;
}

.panel--results .results-content,
.panel--history .history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* Mobile: < 768px */
@media (max-width: 767px) {
  .dashboard {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(380px, 1fr) auto auto auto;
    grid-template-areas: "viewer" "chat" "results" "history";
    overflow-y: auto;
  }
  .panel--results,
  .panel--history {
    max-height: none;
  }
}

/* Tablet: 768px – 1099px */
@media (min-width: 768px) and (max-width: 1099px) {
  .dashboard {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(380px, 1.8fr) minmax(160px, 0.6fr);
    grid-template-areas: "viewer chat" "results history";
  }
  .panel--viewer .viewer-container {
    min-height: 380px;
  }
}

/* Desktop wide: ≥ 1500px */
@media (min-width: 1500px) {
  .dashboard {
    grid-template-columns: 1.3fr 0.9fr 0.8fr;
    grid-template-rows: 1.8fr 0.6fr;
    grid-template-areas: "viewer chat history" "results results history";
  }
}
.panel--viewer{grid-area:viewer;}.panel--chat{grid-area:chat;}.panel--results{grid-area:results;}.panel--history{grid-area:history;}

/* Panel */
.panel{display:flex;flex-direction:column;background:var(--surface-0);backdrop-filter:blur(var(--blur-md));-webkit-backdrop-filter:blur(var(--blur-md));border:1px solid var(--border-0);border-radius:var(--radius-lg);overflow:hidden;transition:box-shadow var(--duration-slow) var(--ease-out),border-color var(--duration-base) var(--ease-out);min-height:0;}
.panel:hover{border-color:var(--border-1);box-shadow:var(--shadow-sm),var(--shadow-glow);}
.panel__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border-0);flex-shrink:0;min-height:44px;}
.panel__title{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-weight:600;color:var(--text-3);letter-spacing:0.04em;text-transform:uppercase;}
.panel__title svg{color:var(--text-4);flex-shrink:0;}
.panel__actions{display:flex;align-items:center;gap:var(--sp-2);}


/* Viewer Panel */
.viewer-container{position:relative;flex:1;min-height:300px;background:var(--bg-1);overflow:hidden;transition:background var(--duration-slow) var(--ease-smooth);}
.viewer-3d{position:absolute;inset:0;width:100%;height:100%;z-index:var(--z-base);overflow:hidden;}
.viewer-empty{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--sp-3);pointer-events:none;animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-empty[hidden]{display:none;}
.viewer-empty__icon{color:var(--text-4);}
.viewer-empty__text{font-size:14px;color:var(--text-3);text-align:center;}
.viewer-empty__hint{font-size:12px;color:var(--text-4);font-family:var(--font-mono);}

.viewer-controls{position:absolute;bottom:var(--sp-3);left:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);display:flex;align-items:center;gap:var(--sp-4);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);animation:slideUp var(--duration-slow) var(--ease-out);flex-wrap:wrap;overflow-x:auto;}
.viewer-controls[hidden]{display:none;}
.viewer-controls::-webkit-scrollbar{display:none;}
.viewer-controls__group{display:flex;align-items:center;gap:var(--sp-2);flex-shrink:0;}
.viewer-controls__group[hidden]{display:none;}
.viewer-controls__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;white-space:nowrap;}
.viewer-controls__value{font-size:11px;font-family:var(--font-mono);color:var(--text-2);min-width:36px;text-align:right;}

.viewer-legend{position:absolute;top:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);font-size:11px;color:var(--text-2);animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-legend[hidden]{display:none;}
.viewer-legend__title{font-weight:600;color:var(--text-1);margin-bottom:var(--sp-1);font-size:11px;letter-spacing:0.02em;}
.viewer-legend__row{display:flex;align-items:center;gap:var(--sp-2);margin-top:3px;}
.viewer-legend__swatch{width:12px;height:12px;border-radius:3px;flex-shrink:0;border:1px solid var(--border-0);}

/* Segmented */
.segmented{display:inline-flex;background:var(--bg-3);border-radius:var(--radius-sm);padding:2px;gap:1px;}
.segmented__btn{padding:3px 10px;border:none;border-radius:var(--radius-xs);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.segmented__btn:hover{color:var(--text-1);}
.segmented__btn--active{background:var(--surface-raised);color:var(--text-0);box-shadow:var(--shadow-sm);}

/* Range */
.range-input{-webkit-appearance:none;appearance:none;width:80px;height:4px;background:var(--bg-4);border-radius:var(--radius-full);outline:none;cursor:pointer;}
.range-input:hover{background:var(--bg-5);}
.range-input::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;background:var(--accent);border-radius:50%;box-shadow:0 0 6px rgba(99,102,241,0.3);border:2px solid var(--bg-0);transition:transform var(--duration-fast) var(--ease-spring);}
.range-input::-webkit-slider-thumb:hover{transform:scale(1.2);}
.range-input::-moz-range-thumb{width:14px;height:14px;background:var(--accent);border:2px solid var(--bg-0);border-radius:50%;}

/* Toggle */
.toggle-btn{padding:3px 10px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);}
.toggle-btn[data-active="true"]{background:var(--accent-muted);color:var(--accent);border-color:rgba(99,102,241,0.3);}
.toggle-btn:hover{border-color:var(--border-2);}

/* Viewer select */
.viewer-select{padding:3px 8px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:var(--bg-3);color:var(--text-1);font-size:11px;font-family:var(--font-mono);cursor:pointer;outline:none;max-width:160px;transition:border-color var(--duration-fast);}
.viewer-select:focus{border-color:var(--accent);}
.viewer-select option{background:var(--bg-2);color:var(--text-1);}

/* Chat Panel */
.panel--chat{display:flex;flex-direction:column;}
.ws-status{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-3);}
.ws-status__dot{width:6px;height:6px;border-radius:50%;transition:background var(--duration-base),box-shadow var(--duration-base);}
.ws-status__dot[data-connected="false"]{background:var(--error);}
.ws-status__dot[data-connected="true"]{background:var(--success);box-shadow:0 0 6px rgba(34,197,94,0.4);}

.chat-scroll{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;scroll-behavior:smooth;}
.chat-messages{display:flex;flex-direction:column;gap:var(--sp-1);padding:var(--sp-3) var(--sp-4);}

.chat-msg{display:flex;gap:var(--sp-3);padding:var(--sp-3);border-radius:var(--radius-md);transition:background var(--duration-fast);animation:chatMsgIn var(--duration-slow) var(--ease-out);}
.chat-msg:hover{background:var(--surface-1);}
@keyframes chatMsgIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}

.chat-msg__avatar{width:28px;height:28px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:12px;font-weight:600;}
.chat-msg__avatar--system{background:var(--accent-muted);color:var(--accent);}
.chat-msg__avatar--user{background:var(--surface-2);color:var(--text-2);}
.chat-msg__avatar--assistant{background:linear-gradient(135deg,var(--accent-muted),rgba(139,92,246,0.15));color:var(--accent);}
.chat-msg__avatar--error{background:var(--error-muted);color:var(--error);}

.chat-msg__body{flex:1;min-width:0;}
.chat-msg__meta{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:2px;}
.chat-msg__name{font-size:12px;font-weight:600;color:var(--text-1);}
.chat-msg__time{font-size:11px;color:var(--text-4);}
.chat-msg__text{font-size:13px;line-height:1.65;color:var(--text-1);word-break:break-word;}
.chat-msg__text strong{font-weight:600;color:var(--text-0);}
.chat-msg__text code{font-family:var(--font-mono);font-size:12px;padding:1px 5px;background:var(--surface-2);border:1px solid var(--border-0);border-radius:var(--radius-xs);color:var(--accent);}

/* Chat progress */
.chat-progress{margin-top:var(--sp-2);display:flex;flex-direction:column;gap:var(--sp-2);}
.chat-progress__bar{height:3px;background:var(--bg-4);border-radius:var(--radius-full);overflow:hidden;margin-top:var(--sp-1);}
.chat-progress__fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:var(--radius-full);transition:width var(--duration-slow) var(--ease-out);width:0%;}
.chat-progress__fill--indeterminate{width:40%!important;animation:indeterminate 1.5s ease-in-out infinite;}
@keyframes indeterminate{0%{transform:translateX(-100%);}100%{transform:translateX(350%);}}
.chat-progress__steps{display:flex;flex-direction:column;gap:2px;}
.chat-progress__step{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-family:var(--font-mono);color:var(--text-3);transition:color var(--duration-fast);animation:fadeIn var(--duration-base) var(--ease-out);}
.chat-progress__step--active{color:var(--info);}
.chat-progress__step--done{color:var(--success);}
.chat-progress__step--error{color:var(--error);}
.chat-progress__icon{width:16px;height:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}

/* Typing */
.chat-typing{display:flex;align-items:center;gap:4px;padding:var(--sp-2) 0;}
.chat-typing__dot{width:5px;height:5px;border-radius:50%;background:var(--text-4);animation:typingBounce 1.4s ease-in-out infinite;}
.chat-typing__dot:nth-child(2){animation-delay:0.2s;}
.chat-typing__dot:nth-child(3){animation-delay:0.4s;}
@keyframes typingBounce{0%,60%,100%{transform:translateY(0);opacity:0.3;}30%{transform:translateY(-6px);opacity:1;}}

/* Chat input */
.chat-input-area{border-top:1px solid var(--border-0);padding:var(--sp-3) var(--sp-4);flex-shrink:0;}
.chat-suggestions{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-3);flex-wrap:wrap;}
.chat-suggestions:empty,.chat-suggestions[hidden]{display:none;}
.suggestion-chip{padding:var(--sp-1) var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-3);font-size:12px;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.suggestion-chip:hover{background:var(--accent-muted);border-color:rgba(99,102,241,0.3);color:var(--accent);}

.chat-form{position:relative;}
.chat-form__input-wrap{display:flex;align-items:flex-end;gap:var(--sp-2);background:var(--surface-1);border:1px solid var(--border-1);border-radius:var(--radius-md);padding:var(--sp-2) var(--sp-3);transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.chat-form__input-wrap:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.chat-form__input{flex:1;border:none;background:transparent;color:var(--text-0);font-family:var(--font-sans);font-size:13px;line-height:1.5;resize:none;outline:none;min-height:20px;max-height:120px;}
.chat-form__input::placeholder{color:var(--text-4);}
.chat-form__send{display:flex;align-items:center;justify-content:center;width:32px;height:32px;border:none;border-radius:var(--radius-sm);background:var(--accent);color:white;cursor:pointer;flex-shrink:0;transition:all var(--duration-fast) var(--ease-out);}
.chat-form__send:disabled{opacity:0.3;cursor:not-allowed;}
.chat-form__send:not(:disabled):hover{background:var(--accent-hover);transform:scale(1.05);}
.chat-form__send:not(:disabled):active{transform:scale(0.98);}
.chat-form__hint{font-size:11px;color:var(--text-4);margin-top:var(--sp-2);text-align:right;}
.chat-form__hint kbd{font-family:var(--font-mono);font-size:10px;padding:1px 4px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:3px;color:var(--text-3);}

/* Results Panel */
.panel--results{min-height:200px;}
.results-tabs{display:flex;gap:0;padding:0 var(--sp-4);border-bottom:1px solid var(--border-0);overflow-x:auto;flex-shrink:0;}
.results-tabs:empty{display:none;}
.results-tabs::-webkit-scrollbar{display:none;}
.tab-btn{position:relative;padding:var(--sp-2) var(--sp-3);border:none;background:transparent;color:var(--text-3);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;white-space:nowrap;transition:color var(--duration-fast);}
.tab-btn:hover{color:var(--text-1);}
.tab-btn--active{color:var(--text-0);}
.tab-btn--active::after{content:'';position:absolute;bottom:-1px;left:var(--sp-3);right:var(--sp-3);height:2px;background:var(--accent);border-radius:1px 1px 0 0;animation:tabLine var(--duration-base) var(--ease-out);}
@keyframes tabLine{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.results-content{flex:1;overflow-y:auto;padding:var(--sp-4);min-height:0;}
.results-empty{display:flex;align-items:center;justify-content:center;height:100%;min-height:120px;color:var(--text-4);font-size:13px;text-align:center;}
.results-empty[hidden]{display:none;}
.result-card{animation:fadeIn var(--duration-slow) var(--ease-out);}
.metrics-grid{display:flex;flex-wrap:wrap;gap:var(--sp-2);}
.result-metric{display:inline-flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);min-width:130px;flex:1 1 130px;max-width:220px;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.result-metric:hover{border-color:var(--border-2);box-shadow:var(--shadow-sm);}
.result-metric__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;}
.result-metric__value{font-size:18px;font-weight:700;color:var(--text-0);font-family:var(--font-mono);letter-spacing:-0.03em;line-height:1.3;}
.result-metric__unit{font-size:11px;color:var(--text-3);font-weight:400;}

/* Energy diagram */
.energy-diagram{display:flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);margin-top:var(--sp-3);max-height:300px;overflow-y:auto;}
.energy-diagram__title{font-size:11px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:var(--sp-2);}
.energy-level{display:flex;align-items:center;gap:var(--sp-2);padding:3px var(--sp-2);border-radius:var(--radius-xs);font-size:11px;font-family:var(--font-mono);transition:background var(--duration-fast);}
.energy-level:hover{background:var(--surface-2);}
.energy-level--occupied{color:var(--accent);}
.energy-level--virtual{color:var(--text-3);}
.energy-level--homo{color:var(--accent);font-weight:600;background:var(--accent-muted);}
.energy-level--lumo{color:var(--warning);font-weight:600;background:var(--warning-muted);}
.energy-level__bar{width:24px;height:3px;border-radius:2px;flex-shrink:0;}
.energy-level--occupied .energy-level__bar{background:var(--accent);}
.energy-level--virtual .energy-level__bar{background:var(--text-4);}
.energy-level--homo .energy-level__bar{background:var(--accent);height:4px;}
.energy-level--lumo .energy-level__bar{background:var(--warning);height:4px;}
.energy-level__label{min-width:60px;}
.energy-level__energy{flex:1;text-align:right;}
.energy-level__occ{min-width:28px;text-align:center;color:var(--text-4);font-size:10px;}

.result-table{width:100%;border-collapse:collapse;font-size:12px;}
.result-table th{text-align:left;font-weight:600;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;font-size:11px;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-1);position:sticky;top:0;background:var(--bg-2);}
.result-table td{padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);color:var(--text-1);font-family:var(--font-mono);font-size:12px;}
.result-table tr:hover td{background:var(--surface-1);}
.result-json{background:var(--bg-2);border:1px solid var(--border-0);border-radius:var(--radius-md);padding:var(--sp-4);overflow:auto;max-height:400px;font-family:var(--font-mono);font-size:12px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all;}
.result-note{font-size:12px;color:var(--text-3);margin-top:var(--sp-3);line-height:1.5;}

/* History */
.panel--history{min-height:200px;}
.history-search-wrap{position:relative;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);}
.history-search-icon{position:absolute;left:var(--sp-5);top:50%;transform:translateY(-50%);color:var(--text-4);pointer-events:none;}
.history-search{width:100%;padding:var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-8);border:1px solid var(--border-0);border-radius:var(--radius-sm);background:var(--surface-1);color:var(--text-1);font-size:12px;font-family:var(--font-sans);outline:none;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.history-search:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.history-search::placeholder{color:var(--text-4);}
.history-list{flex:1;overflow-y:auto;padding:var(--sp-2);}
.history-empty{display:flex;align-items:center;justify-content:center;min-height:80px;color:var(--text-4);font-size:12px;}
.history-empty[hidden]{display:none;}
.history-item{display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-2) var(--sp-3);border-radius:var(--radius-md);cursor:pointer;transition:background var(--duration-fast),border-color var(--duration-fast);border:1px solid transparent;animation:slideIn var(--duration-slow) var(--ease-out);}
.history-item:hover{background:var(--surface-1);}
.history-item--active{background:var(--accent-muted);border-color:rgba(99,102,241,0.25);}
.history-item__status{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.history-item__status--completed{background:var(--success);}
.history-item__status--running{background:var(--info);animation:pulse-dot 1.5s ease-in-out infinite;}
.history-item__status--failed{background:var(--error);}
.history-item__status--queued{background:var(--warning);}
.history-item__info{flex:1;min-width:0;}
.history-item__title{font-size:12px;font-weight:500;color:var(--text-1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__detail{font-size:11px;color:var(--text-4);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__energy{font-size:11px;font-family:var(--font-mono);color:var(--text-3);white-space:nowrap;flex-shrink:0;}

/* Modal */
.modal{border:none;background:transparent;padding:0;max-width:100vw;max-height:100vh;overflow:visible;}
.modal::backdrop{background:transparent;}
.modal__backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);z-index:0;animation:fadeIn var(--duration-base) var(--ease-out);}
.modal__content{position:relative;z-index:1;background:var(--bg-2);border:1px solid var(--border-1);border-radius:var(--radius-lg);box-shadow:var(--shadow-xl);width:440px;max-width:90vw;margin:15vh auto;animation:modalIn var(--duration-slow) var(--ease-out);}
.modal__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-4) var(--sp-5);border-bottom:1px solid var(--border-0);}
.modal__header h3{font-size:15px;font-weight:600;color:var(--text-0);}
.modal__body{padding:var(--sp-5);}
.shortcuts-grid{display:flex;flex-direction:column;gap:var(--sp-3);}
.shortcut-row{display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--text-2);}
.shortcut-keys{display:flex;align-items:center;gap:3px;}
.shortcut-plus,.shortcut-dash{font-size:11px;color:var(--text-4);}
.shortcut-row kbd{font-family:var(--font-mono);font-size:11px;padding:2px 6px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:var(--radius-xs);color:var(--text-1);min-width:22px;text-align:center;}
@keyframes modalIn{from{opacity:0;transform:translateY(-12px) scale(0.97);}to{opacity:1;transform:translateY(0) scale(1);}}

/* Animations */
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
@keyframes slideIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
@keyframes slideUp{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}

/* Fullscreen */
.panel--viewer.is-fullscreen{position:fixed;inset:0;z-index:var(--z-overlay);border-radius:0;margin:0;border:none;}
.panel--viewer.is-fullscreen .viewer-container{min-height:100%;}

/* Utils */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.mono{font-family:var(--font-mono);}
details{border:1px solid var(--border-0);border-radius:var(--radius-sm);padding:var(--sp-2) var(--sp-3);}
details summary{cursor:pointer;color:var(--text-3);font-size:12px;font-weight:500;user-select:none;}
details summary:hover{color:var(--text-1);}
details[open] summary{margin-bottom:var(--sp-2);}

/* ═══ 요구사항 2: Orbital/ESP 토글 버튼 ═══ */
.viz-mode-toggle { display: inline-flex; gap: 0; border: 1px solid var(--border-1); border-radius: 6px; overflow: hidden; margin: 0 8px; }
.viz-mode-toggle .toggle-btn { padding: 4px 14px; font-size: 12px; font-weight: 600; border: none; background: var(--bg-2); color: var(--text-2); cursor: pointer; transition: background 0.15s, color 0.15s; }
.viz-mode-toggle .toggle-btn:not(:last-child) { border-right: 1px solid var(--border-1); }
.viz-mode-toggle .toggle-btn.active { background: var(--accent); color: #fff; }
.viz-mode-toggle .toggle-btn:hover:not(.active) { background: var(--bg-3); }

/* ═══ 요구사항 3: Trajectory Player ═══ */
.trajectory-player { padding: 6px 12px; border-top: 1px solid var(--border-1); background: var(--bg-2); flex: 0 0 auto; z-index: 10; position: relative;}
.traj-controls { display: flex; align-items: center; gap: 8px; }
.traj-btn { width: 32px; height: 32px; border: 1px solid var(--border-1); border-radius: 6px; background: var(--bg-1); cursor: pointer; font-size: 14px; display: flex; align-items: center; justify-content: center; transition: background 0.15s; color: var(--text-1); }
.traj-btn:hover { background: var(--bg-3); }
.traj-slider { flex: 1; min-width: 100px; cursor: pointer; }
.traj-label { font-size: 11px; color: var(--text-3); white-space: nowrap; min-width: 220px; font-family: var(--font-mono); }

/* ═══ 요구사항 4: Session Tab Bar ═══ */
.session-tab-bar { display: flex; flex-wrap: nowrap; gap: 0; padding: 4px 8px 0; border-bottom: 1px solid var(--border-1); background: var(--bg-2); overflow-x: auto; overflow-y: hidden; flex: 0 0 auto; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }
.session-tab-bar .session-tab { position: relative; padding: 5px 26px 5px 10px; font-size: 11px; font-weight: 500; white-space: nowrap; border: 1px solid var(--border-1); border-bottom: none; border-radius: 6px 6px 0 0; background: var(--bg-3); color: var(--text-2); cursor: pointer; transition: background 0.15s, color 0.15s; flex: 0 0 auto; }
.session-tab-bar .session-tab.active { background: var(--bg-1); color: var(--text-1); border-bottom: 1px solid var(--bg-1); margin-bottom: -1px; font-weight: 600; }
.session-tab-bar .session-tab:hover:not(.active) { background: var(--bg-4); }
.session-tab-bar .session-tab-close { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; line-height: 14px; text-align: center; font-size: 13px; color: var(--text-3); border-radius: 3px; cursor: pointer; transition: background 0.1s, color 0.1s; }
.session-tab-bar .session-tab-close:hover { background: rgba(200, 50, 50, 0.15); color: #f43f5e; }

/* ═══ 요구사항 1: Loading Overlay ═══ */
.app-loader { position: fixed; inset: 0; z-index: 99999; display: flex; align-items: center; justify-content: center; background: var(--bg-1); transition: opacity 0.45s ease, visibility 0.45s ease; }
.app-loader.fade-out { opacity: 0; visibility: hidden; pointer-events: none; }
.loader-content { text-align: center; }
.loader-spinner { width: 48px; height: 48px; margin: 0 auto 18px; border: 4px solid var(--border-1); border-top-color: var(--accent); border-radius: 50%; animation: qcviz-loader-spin 0.75s linear infinite; }
@keyframes qcviz-loader-spin { to { transform: rotate(360deg); } }
.loader-text { font-size: 16px; font-weight: 600; color: var(--text-1); margin: 0 0 6px; }
.loader-sub { font-size: 12px; color: var(--text-3); margin: 0; }

/* ═══ 요구사항 3: Color Scheme 선택 UI ═══ */
.scheme-preview { display: inline-flex; gap: 3px; margin-left: 8px; vertical-align: middle; }
.swatch { display: inline-block; width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--border-1); }

/* ═══════════════════════════════════════════════════════════
   Butterfly Chart — Charges Visualization
   ═══════════════════════════════════════════════════════════ */

.butterfly-legend { display: flex; align-items: center; gap: var(--sp-4); padding: var(--sp-2) 0; margin-bottom: var(--sp-3); font-size: 11px; color: var(--text-2); }
.butterfly-legend__item { display: inline-flex; align-items: center; gap: var(--sp-1); }
.butterfly-legend__swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--border-0); }
.butterfly-legend__swatch--neg { background: var(--error); }
.butterfly-legend__swatch--pos { background: var(--info); }
.butterfly-chart { display: flex; flex-direction: column; gap: 3px; }
.butterfly-row { display: grid; grid-template-columns: 1fr 56px 1fr; align-items: center; gap: 0; min-height: 26px; transition: background var(--duration-fast); border-radius: var(--radius-xs); padding: 1px 0; }
.butterfly-row:hover { background: var(--surface-1); }
.butterfly-label { display: flex; align-items: center; justify-content: center; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-0); text-align: center; padding: 0 4px; background: var(--surface-0); border-left: 1px solid var(--border-1); border-right: 1px solid var(--border-1); min-height: 26px; z-index: 1; }
.butterfly-label__idx { font-size: 10px; font-weight: 400; color: var(--text-4); font-family: var(--font-mono); }
.butterfly-label__el { font-family: var(--font-sans); }
.butterfly-bar-area { position: relative; display: flex; flex-direction: column; gap: 1px; height: 100%; justify-content: center; }
.butterfly-bar-area--neg { align-items: flex-end; padding-right: 0; }
.butterfly-bar-area--pos { align-items: flex-start; padding-left: 0; }
.butterfly-bar { height: 16px; border-radius: 2px; min-width: 2px; max-width: 100%; position: relative; transition: width var(--duration-base) var(--ease-out), opacity var(--duration-fast); cursor: default; }
.butterfly-bar:hover { opacity: 0.85; }
.butterfly-bar--neg-primary { background: linear-gradient(270deg, var(--error), rgba(239, 68, 68, 0.6)); border-radius: 2px 0 0 2px; }
.butterfly-bar--neg-secondary { background: rgba(239, 68, 68, 0.3); border: 1px solid rgba(239, 68, 68, 0.4); height: 8px; border-radius: 2px 0 0 2px; }
.butterfly-bar--pos-primary { background: linear-gradient(90deg, var(--info), rgba(59, 130, 246, 0.6)); border-radius: 0 2px 2px 0; }
.butterfly-bar--pos-secondary { background: rgba(59, 130, 246, 0.3); border: 1px solid rgba(59, 130, 246, 0.4); height: 8px; border-radius: 0 2px 2px 0; }
.butterfly-bar__val { position: absolute; top: 50%; transform: translateY(-50%); font-size: 10px; font-family: var(--font-mono); color: var(--text-0); white-space: nowrap; pointer-events: none; text-shadow: 0 0 3px var(--bg-0); }
.butterfly-bar-area--neg .butterfly-bar__val { left: 4px; }
.butterfly-bar-area--pos .butterfly-bar__val { right: 4px; }
.butterfly-bar[style*="width:0"] .butterfly-bar__val, .butterfly-bar[style*="width:1"] .butterfly-bar__val, .butterfly-bar[style*="width:2"] .butterfly-bar__val, .butterfly-bar[style*="width:3"] .butterfly-bar__val { color: var(--text-2); }
@media (max-width: 600px) { .butterfly-row { grid-template-columns: 1fr 44px 1fr; } .butterfly-label { font-size: 11px; } .butterfly-bar__val { font-size: 9px; } }

.butterfly-axis { display: grid; grid-template-columns: 1fr 1fr 56px 1fr 1fr; margin-bottom: 4px; padding: 0; }
.axis-tick { font-size: 10px; color: var(--text-4); font-family: var(--font-mono); position: relative; }
.axis-tick:nth-child(1) { text-align: left; }
.axis-tick:nth-child(2) { text-align: right; margin-right: 4px;}
.center-tick { text-align: center; color: var(--text-3); font-weight: bold; border-left: 1px dashed var(--border-1); border-right: 1px dashed var(--border-1); background: var(--surface-0); border-radius: 2px;}
.axis-tick:nth-child(4) { text-align: left; margin-left: 4px; }
.axis-tick:nth-child(5) { text-align: right; }

.butterfly-chart {
  border-top: 1px dashed var(--border-1);
  padding-top: 4px;
}

/* Session Tabs */
.session-tabs-container {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--surface-0);
  border-bottom: 1px solid var(--border-0);
  overflow-x: auto;
  white-space: nowrap;
}
.session-tabs-container .session-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-full);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.session-tabs-container .session-tab:hover {
  background: var(--surface-2);
  color: var(--text-1);
}
.session-tabs-container .session-tab--active {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.4);
  color: var(--accent);
}
.session-tabs-container .session-tab__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-left: 2px;
}
.session-tabs-container .session-tab__close:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--error);
}

```

### File: `web/templates/index.html`
```html
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>QCViz-MCP Enterprise v5</title>
  <meta name="description" content="Enterprise quantum chemistry visualization with PySCF, 3Dmol.js, chat orchestration, job history restoration, and state-synced viewer controls." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="/static/style.css" />

  <script>
    (function (g) {
      "use strict";
      if (g.QCVizApp && g.QCVizApp.__enterpriseV5) return;

      var STORAGE_KEY = "QCVIZ_ENTERPRISE_V5_UI_SNAPSHOTS";
      var listeners = new Map();

      function safeStr(v, fb) { return v == null ? (fb || "") : String(v).trim(); }
      function clone(v) { try { return JSON.parse(JSON.stringify(v)); } catch (_) { return v; } }
      function deepMerge(base, patch) {
        var lhs = base && typeof base === "object" ? clone(base) : {};
        var rhs = patch && typeof patch === "object" ? patch : {};
        Object.keys(rhs).forEach(function (k) {
          var lv = lhs[k], rv = rhs[k];
          if (lv && rv && typeof lv === "object" && typeof rv === "object" && !Array.isArray(lv) && !Array.isArray(rv)) {
            lhs[k] = deepMerge(lv, rv);
          } else { lhs[k] = clone(rv); }
        });
        return lhs;
      }

      /* 읽기 쉬운 세션 ID 생성 */
      function makeSessionId() {
        var ts = Date.now().toString(36);
        var r = Math.random().toString(36).substring(2, 8);
        return "qcviz-" + ts + "-" + r;
      }

      var apiPrefix = g.QCVIZ_API_PREFIX || "/api";

      var store = {
        version: "enterprise-v5",
        jobsById: {},
        jobOrder: [],
        resultsByJobId: {},
        activeJobId: null,
        activeResult: null,
        status: { text: "Ready", kind: "idle", source: "app", at: Date.now() },
        uiSnapshotsByJobId: {},
        chatMessages: [],
        theme: "dark",
        lastUserInput: "",
        sessionId: makeSessionId(),
      };

      function emit(ev, detail) {
        (listeners.get(ev) || []).slice().forEach(function (fn) { try { fn(detail); } catch (_) {} });
      }
      function on(ev, fn) {
        if (!listeners.has(ev)) listeners.set(ev, []);
        listeners.get(ev).push(fn);
        return function () {
          var arr = listeners.get(ev) || [];
          var idx = arr.indexOf(fn);
          if (idx >= 0) arr.splice(idx, 1);
        };
      }

      function persistSnapshots() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(store.uiSnapshotsByJobId)); } catch (_) {}
      }
      function loadSnapshots() {
        try {
          var raw = localStorage.getItem(STORAGE_KEY);
          if (raw) store.uiSnapshotsByJobId = JSON.parse(raw);
        } catch (_) {}
      }
      loadSnapshots();

      var prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
      function applyTheme(theme) {
        store.theme = theme;
        document.documentElement.setAttribute("data-theme", theme);
        emit("theme:changed", { theme: theme });
      }
      var savedTheme = localStorage.getItem("QCVIZ_THEME");
      if (savedTheme) applyTheme(savedTheme);
      else applyTheme(prefersDark.matches ? "dark" : "light");
      prefersDark.addEventListener("change", function (e) {
        if (!localStorage.getItem("QCVIZ_THEME")) applyTheme(e.matches ? "dark" : "light");
      });

      g.QCVizApp = {
        __enterpriseV5: true,
        store: store,
        on: on,
        emit: emit,
        clone: clone,
        deepMerge: deepMerge,
        apiPrefix: apiPrefix,

        setTheme: function (theme) {
          localStorage.setItem("QCVIZ_THEME", theme);
          applyTheme(theme);
        },

        setStatus: function (text, kind, source) {
          store.status = { text: text, kind: kind || "idle", source: source || "app", at: Date.now() };
          emit("status:changed", clone(store.status));
        },

        upsertJob: function (job) {
          if (!job || typeof job !== "object") return null;
          var jobId = safeStr(job.job_id);
          if (!jobId) return null;
          var prev = store.jobsById[jobId] || {};
          var next = deepMerge(prev, job);
          store.jobsById[jobId] = next;
          if (next.result) store.resultsByJobId[jobId] = clone(next.result);
          store.jobOrder = Object.values(store.jobsById)
            .sort(function (a, b) { return Number(b.updated_at || 0) - Number(a.updated_at || 0); })
            .map(function (j) { return j.job_id; });
          emit("jobs:changed", { job: clone(next), jobs: store.jobOrder.map(function (id) { return clone(store.jobsById[id]); }) });
          return clone(next);
        },

        setActiveJob: function (jobId) {
          store.activeJobId = jobId;
          var result = store.resultsByJobId[jobId] || null;
          store.activeResult = result ? clone(result) : null;
          emit("activejob:changed", { jobId: jobId, result: store.activeResult });
          if (result) emit("result:changed", { jobId: jobId, result: clone(result), source: "history" });
        },

        setActiveResult: function (res, opts) {
          opts = opts || {};
          var jobId = safeStr(opts.jobId || store.activeJobId);
          store.activeResult = res;
          if (jobId) {
            store.activeJobId = jobId;
            store.resultsByJobId[jobId] = clone(res);
          }
          emit("result:changed", { jobId: jobId, result: clone(res), source: opts.source || "app" });
        },

        saveUISnapshot: function (jobId, snapshot) {
          if (!jobId) return;
          store.uiSnapshotsByJobId[jobId] = clone(snapshot);
          persistSnapshots();
        },

        getUISnapshot: function (jobId) {
          return store.uiSnapshotsByJobId[jobId] ? clone(store.uiSnapshotsByJobId[jobId]) : null;
        },

        addChatMessage: function (msg) {
          store.chatMessages.push(msg);
          emit("chat:message", clone(msg));
        },
      };
    })(window);
  </script>
</head>

<body>

<!-- ═══ 로딩 오버레이 ═══ -->
<div id="appLoader" class="app-loader">
  <div class="loader-content">
    <div class="loader-spinner"></div>
    <p class="loader-text">Initializing QCViz-MCP...</p>
    <p class="loader-sub">Loading 3D visualization engine</p>
  </div>
</div>
<script>
  // Fallback to ensure loader doesn't hang forever
  window.addEventListener('load', function() {
    setTimeout(function() {
      var loader = document.getElementById('appLoader');
      if (loader) {
        loader.classList.add('fade-out');
        setTimeout(function() {
          if (loader.parentNode) loader.parentNode.removeChild(loader);
        }, 600);
      }
    }, 1500);
  });
</script>

  <div class="app-shell" id="appShell">

    <!-- Top Bar -->
    <header class="topbar" id="topbar">
      <div class="topbar__left">
        <div class="topbar__logo" aria-label="QCViz Logo">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="28" height="28" rx="8" fill="url(#logoGrad)"/>
            <path d="M8 14a6 6 0 1 1 12 0 6 6 0 0 1-12 0Zm6-3.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" fill="white" fill-opacity="0.95"/>
            <path d="M17.5 17.5L21 21" stroke="white" stroke-width="2" stroke-linecap="round" stroke-opacity="0.9"/>
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
                <stop stop-color="#6366f1"/>
                <stop offset="1" stop-color="#8b5cf6"/>
              </linearGradient>
            </defs>
          </svg>
          <span class="topbar__title">QCViz-MCP <span class="topbar__badge">v5</span></span>
        </div>
      </div>
      <div class="topbar__center">
        <div class="status-indicator" id="globalStatus">
          <span class="status-indicator__dot" data-kind="idle"></span>
          <span class="status-indicator__text">Ready</span>
        </div>
      </div>
      <div class="topbar__right">
        <button class="icon-btn" id="btnThemeToggle" aria-label="Toggle theme" title="Toggle theme (Ctrl+\)">
          <svg class="icon-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          <svg class="icon-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        </button>
        <button class="icon-btn" id="btnKeyboardShortcuts" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/></svg>
        </button>
      </div>
    </header>

    <!-- App-level Session Tabs -->
    <div id="sessionTabsContainer" class="session-tabs-container" hidden>
      <div id="sessionTabs" class="session-tabs"></div>
    </div>

    <!-- Dashboard Grid -->
    <main class="dashboard" id="dashboard">

      <!-- Viewer Panel -->
      <section class="panel panel--viewer" id="panelViewer" aria-label="3D Molecular Viewer">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            Molecular Viewer
          </h2>
          <div class="panel__actions">
            <button class="chip-btn" id="btnViewerReset" title="Reset view">Reset</button>
            <div id="vizModeToggle" class="viz-mode-toggle" hidden>
              <button id="btnModeOrbital" class="toggle-btn active" title="Orbital 표면 보기">Orbital</button>
              <button id="btnModeESP" class="toggle-btn" title="ESP 맵 보기">ESP</button>
            </div>
            <button class="chip-btn" id="btnViewerScreenshot" title="Screenshot">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/></svg>
              Capture
            </button>
            <button class="icon-btn icon-btn--sm" id="btnViewerFullscreen" title="Fullscreen">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
            </button>
          </div>
        </div>
        <div class="viewer-container" id="viewerContainer">
          <div class="viewer-3d" id="viewer3d"></div>
          <div class="viewer-empty" id="viewerEmpty">
            <div class="viewer-empty__icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.35"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            </div>
            <p class="viewer-empty__text">Submit a computation to render the molecule</p>
            <p class="viewer-empty__hint">Try: "Calculate energy of water with STO-3G"</p>
          </div>
          <div class="viewer-controls" id="viewerControls" hidden>
            <div class="viewer-controls__group">
              <label class="viewer-controls__label">Style</label>
              <div class="segmented" id="segStyle">
                <button class="segmented__btn segmented__btn--active" data-value="stick">Stick</button>
                <button class="segmented__btn" data-value="sphere">Sphere</button>
                <button class="segmented__btn" data-value="line">Line</button>
              </div>
            </div>
            <div class="viewer-controls__group" id="grpOrbital" hidden>
              <label class="viewer-controls__label">Isosurface</label>
              <input type="range" class="range-input" id="sliderIsovalue" min="0.001" max="0.1" step="0.001" value="0.03" />
              <span class="viewer-controls__value" id="lblIsovalue">0.030</span>
            </div>
            <div class="viewer-controls__group" id="grpOpacity" hidden>
              <label class="viewer-controls__label">Opacity</label>
              <input type="range" class="range-input" id="sliderOpacity" min="0.1" max="1.0" step="0.05" value="0.75" />
              <span class="viewer-controls__value" id="lblOpacity">0.75</span>
            </div>
            
            <div class="viewer-controls__group" id="grpColorScheme">
              <label class="viewer-controls__label">Color Scheme</label>
              <select id="selectColorScheme" class="viewer-select">
                <option value="classic">Classic (Blue/Red)</option>
                <option value="jmol">Jmol</option>
                <option value="rwb">RWB (Red-White-Blue)</option>
                <option value="bwr">BWR (Blue-White-Red)</option>
                <option value="spectral">Spectral</option>
                <option value="viridis">Viridis</option>
                <option value="inferno">Inferno</option>
                <option value="coolwarm">Cool-Warm</option>
                <option value="purplegreen">Purple-Green</option>
                <option value="greyscale">Greyscale</option>
              </select>
              <span id="schemePreview" class="scheme-preview">
                <span class="swatch swatch-pos"></span>
                <span class="swatch swatch-neg"></span>
              </span>
            </div>

            <div class="viewer-controls__group" id="grpOrbitalSelect" hidden>
              <label class="viewer-controls__label">Orbital</label>
              <select class="viewer-select" id="selectOrbital"></select>
            </div>
            <div class="viewer-controls__group">
              <label class="viewer-controls__label">Labels</label>
              <button class="toggle-btn" id="btnToggleLabels" data-active="true" aria-pressed="true">On</button>
            </div>
          </div>
          <div class="viewer-legend" id="viewerLegend" hidden></div>
        </div>
      </section>

      <!-- Chat Panel -->
      <section class="panel panel--chat" id="panelChat" aria-label="Chat Assistant">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            Assistant
          </h2>
          <div class="panel__actions">
            <div class="ws-status" id="wsStatus">
              <span class="ws-status__dot" data-connected="false"></span>
              <span class="ws-status__label">Disconnected</span>
            </div>
          </div>
        </div>
        <div class="chat-scroll" id="chatScroll">
          <div class="chat-messages" id="chatMessages">
            <div class="chat-msg chat-msg--system">
              <div class="chat-msg__avatar chat-msg__avatar--system">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>
              </div>
              <div class="chat-msg__body">
                <p class="chat-msg__text">Welcome to <strong>QCViz-MCP v5</strong>. I can run quantum chemistry calculations using PySCF. Ask me to compute energies, optimize geometries, or visualize orbitals and ESP maps.</p>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-input-area" id="chatInputArea">
          <div class="chat-suggestions" id="chatSuggestions">
            <button class="suggestion-chip" data-prompt="Calculate the energy of water using STO-3G basis">Water energy</button>
            <button class="suggestion-chip" data-prompt="Optimize the geometry of methane with 6-31G basis">Methane geometry</button>
            <button class="suggestion-chip" data-prompt="Show the HOMO orbital of formaldehyde">Formaldehyde HOMO</button>
          </div>
          <form class="chat-form" id="chatForm" autocomplete="off">
            <div class="chat-form__input-wrap">
              <textarea class="chat-form__input" id="chatInput" placeholder="Ask about quantum chemistry..." rows="1" maxlength="4000"></textarea>
              <button class="chat-form__send" id="chatSend" type="submit" aria-label="Send" disabled>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </button>
            </div>
            <p class="chat-form__hint">Press <kbd>Enter</kbd> to send, <kbd>Shift+Enter</kbd> for new line</p>
          </form>
        </div>
      </section>

      <!-- Results Panel -->
      <section class="panel panel--results" id="panelResults" aria-label="Computation Results">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            Results
          </h2>
        </div>
        <div id="sessionTabBar" class="session-tab-bar" hidden></div>
        <div class="results-tabs" id="resultsTabs" role="tablist"></div>
        <div class="results-content" id="resultsContent">
          <div class="results-empty" id="resultsEmpty">
            <p>No results yet. Submit a computation from the chat.</p>
          </div>
        </div>
      </section>

      <!-- History Panel -->
      <section class="panel panel--history" id="panelHistory" aria-label="Job History">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            History
          </h2>
          <div class="panel__actions">
            <button class="icon-btn icon-btn--sm" id="btnRefreshHistory" title="Refresh">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            </button>
          </div>
        </div>
        <div class="history-search-wrap">
          <svg class="history-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="search" class="history-search" id="historySearch" placeholder="Search jobs..." />
        </div>
        <div class="history-list" id="historyList">
          <div class="history-empty" id="historyEmpty">
            <p>No previous computations</p>
          </div>
        </div>
      </section>

    </main>
  </div>

  <!-- Keyboard Shortcuts Modal -->
  <dialog class="modal" id="modalShortcuts">
    <div class="modal__backdrop" data-close></div>
    <div class="modal__content">
      <div class="modal__header">
        <h3>Keyboard Shortcuts</h3>
        <button class="icon-btn icon-btn--sm" data-close aria-label="Close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal__body shortcuts-grid">
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>/</kbd></span><span>Focus chat input</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>K</kbd></span><span>Search history</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>\</kbd></span><span>Toggle theme</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Esc</kbd></span><span>Close modals / blur</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>1</kbd><span class="shortcut-dash">&ndash;</span><kbd>6</kbd></span><span>Switch result tabs</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>?</kbd></span><span>Show this dialog</span></div>
      </div>
    </div>
  </dialog>

  <script src="/static/chat.js" defer></script>
  <script src="/static/results.js" defer></script>
  <script src="/static/viewer.js" defer></script>
  <script src="/static/app.js" defer></script>
</body>
</html>

```

## 4. 실행 단계 (Action Steps)
1. **전수조사**: 위 소스 코드를 바탕으로 백엔드 `_finalize_result_contract`부터 프론트엔드 `App.on('result:changed')`까지의 파이프라인을 1줄씩 검증하여 필드명/데이터타입 불일치를 리스트업 하십시오.
2. **접합부 수정**: 식별된 모든 접합부 에러를 수정하십시오.
3. **안정성 강화**: 미선언 변수 참조(ReferenceError), 널 참조(TypeError), 무한 루프 가능성을 전면 제거하십시오.
4. **최종 보고**: 수정된 사항을 파일별로 요약하고, 시스템의 모든 기능이 'Ready' 상태임을 증명하십시오.
