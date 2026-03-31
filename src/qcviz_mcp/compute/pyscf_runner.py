"""PySCF computation runner — single-point, geometry, orbital, ESP, optimization.

# FIX(M4): XYZ 문자열 직접 입력 강화, atoms list [(sym,(x,y,z))] 지원,
#          +/- regex 안전화, re.error 방지, progress callback 유지
기존 인터페이스 전부 유지 (run_analyze, run_single_point 등).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import math
import re
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

import numpy as np
from pyscf import dft, gto, scf
from pyscf.data import elements
from pyscf.tools import cubegen

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:
    geometric_optimize = None

# ── CONSTANTS ────────────────────────────────────────────────

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
BOHR_TO_ANGSTROM = 0.529177210903
EV_TO_KCAL = 23.06054783061903

DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

DEFAULT_ESP_PRESET_ORDER = [
    "acs", "rsc", "nature", "spectral", "inferno",
    "viridis", "rwb", "bwr", "greyscale", "high_contrast",
]

ESP_PRESETS_DATA: Dict[str, Dict[str, Any]] = {
    "acs": {"id": "acs", "label": "ACS-style", "aliases": ["american chemical society", "acs-style", "science", "default"], "surface_scheme": "rwb", "default_range_au": 0.060, "description": "Balanced red-white-blue diverging scheme."},
    "rsc": {"id": "rsc", "label": "RSC-style", "aliases": ["royal society of chemistry", "rsc-style"], "surface_scheme": "bwr", "default_range_au": 0.055, "description": "Soft blue-white-red variant."},
    "nature": {"id": "nature", "label": "Nature-style", "aliases": ["nature-style"], "surface_scheme": "spectral", "default_range_au": 0.055, "description": "Publication-friendly spectral scheme."},
    "spectral": {"id": "spectral", "label": "Spectral", "aliases": ["rainbow", "diverging"], "surface_scheme": "spectral", "default_range_au": 0.060, "description": "High contrast diverging palette."},
    "inferno": {"id": "inferno", "label": "Inferno", "aliases": [], "surface_scheme": "inferno", "default_range_au": 0.055, "description": "Perceptually uniform warm palette."},
    "viridis": {"id": "viridis", "label": "Viridis", "aliases": [], "surface_scheme": "viridis", "default_range_au": 0.055, "description": "Perceptually uniform scientific palette."},
    "rwb": {"id": "rwb", "label": "Red-White-Blue", "aliases": ["red-white-blue", "red white blue"], "surface_scheme": "rwb", "default_range_au": 0.060, "description": "Classic diverging palette."},
    "bwr": {"id": "bwr", "label": "Blue-White-Red", "aliases": ["blue-white-red", "blue white red"], "surface_scheme": "bwr", "default_range_au": 0.060, "description": "Classic positive/neutral/negative."},
    "greyscale": {"id": "greyscale", "label": "Greyscale", "aliases": ["gray", "grey", "mono", "monochrome"], "surface_scheme": "greyscale", "default_range_au": 0.050, "description": "Monochrome publication palette."},
    "high_contrast": {"id": "high_contrast", "label": "High Contrast", "aliases": ["high-contrast", "contrast"], "surface_scheme": "high_contrast", "default_range_au": 0.070, "description": "Strong contrast for presentations."},
}

# FIX(M4): Korean aliases moved to services/ko_aliases.py but kept here for backward compat
_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water", "워터": "water", "암모니아": "ammonia", "메탄": "methane",
    "에탄": "ethane", "에틸렌": "ethylene", "아세틸렌": "acetylene", "벤젠": "benzene",
    "톨루엔": "toluene", "페놀": "phenol", "아닐린": "aniline", "피리딘": "pyridine",
    "아세톤": "acetone", "메탄올": "methanol", "에탄올": "ethanol",
    "메틸아민": "methylamine", "메탄아민": "methylamine", "에틸아민": "ethylamine",
    "에탄아민": "ethylamine", "디메틸아민": "dimethylamine", "트리메틸아민": "trimethylamine",
    "포름알데히드": "formaldehyde", "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid", "아세트산": "acetic_acid", "요소": "urea",
    "우레아": "urea", "이산화탄소": "carbon_dioxide", "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen", "산소": "oxygen", "수소": "hydrogen", "불소": "fluorine", "네온": "neon",
}

_METHOD_ALIASES: Dict[str, str] = {
    "hf": "HF", "rhf": "HF", "uhf": "HF", "b3lyp": "B3LYP",
    "pbe": "PBE", "pbe0": "PBE0", "m062x": "M06-2X", "m06-2x": "M06-2X",
    "wb97xd": "wB97X-D", "ωb97x-d": "wB97X-D", "wb97x-d": "wB97X-D",
    "wb97xv": "wB97X-V", "wb97x-v": "wB97X-V",
    "tpssh": "TPSSh", "tpss": "TPSS", "r2scan": "r2SCAN", "pw6b95": "PW6B95",
    "bp86": "BP86", "blyp": "BLYP", "mp2": "MP2", "ccsd": "CCSD",
}

_BASIS_ALIASES: Dict[str, str] = {
    "sto-3g": "STO-3G", "3-21g": "3-21G", "6-31g": "6-31G",
    "6-31g*": "6-31G*", "6-31g(d)": "6-31G*", "6-31g**": "6-31G**",
    "6-31g(d,p)": "6-31G**", "def2svp": "def2-SVP", "def2-svp": "def2-SVP",
    "def2tzvp": "def2-TZVP", "def2-tzvp": "def2-TZVP",
    "cc-pvdz": "cc-pVDZ", "cc-pvtz": "cc-pVTZ",
    "aug-cc-pvdz": "aug-cc-pVDZ", "aug-cc-pvtz": "aug-cc-pVTZ",
}

_COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.85, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38,
    "I": 1.39, "Xe": 1.40, "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
}

BUILTIN_XYZ_LIBRARY = {
    "water": "3\n\nO 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469",
    "ammonia": "4\n\nN 0.000 0.000 0.112\nH 0.000 0.938 -0.262\nH 0.812 -0.469 -0.262\nH -0.812 -0.469 -0.262",
    "methane": "5\n\nC 0.000 0.000 0.000\nH 0.627 0.627 0.627\nH -0.627 -0.627 0.627\nH 0.627 -0.627 -0.627\nH -0.627 0.627 -0.627",
    "benzene": "12\n\nC 0.0000 1.3965 0.0000\nC 1.2094 0.6983 0.0000\nC 1.2094 -0.6983 0.0000\nC 0.0000 -1.3965 0.0000\nC -1.2094 -0.6983 0.0000\nC -1.2094 0.6983 0.0000\nH 0.0000 2.4842 0.0000\nH 2.1514 1.2421 0.0000\nH 2.1514 -1.2421 0.0000\nH 0.0000 -2.4842 0.0000\nH -2.1514 -1.2421 0.0000\nH -2.1514 1.2421 0.0000",
    "acetone": "10\n\nC 0.000 0.280 0.000\nO 0.000 1.488 0.000\nC 1.285 -0.551 0.000\nC -1.285 -0.551 0.000\nH 1.266 -1.203 -0.880\nH 1.266 -1.203 0.880\nH 2.155 0.106 0.000\nH -1.266 -1.203 -0.880\nH -1.266 -1.203 0.880\nH -2.155 0.106 0.000",
}

# ── CORE UTILS ───────────────────────────────────────────────

def unique(arr: list) -> list:
    seen: set = set()
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
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
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
    seen: set = set()
    out: List[str] = []
    for item in items or []:
        text = _safe_str(item, "")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_name_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    # FIX(M4): safe regex — escape + and - inside character class properly
    s = re.sub(r"[^0-9a-zA-Z가-힣\+\-\s]", " ", s)
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
        # FIX(M4): safe atom pattern — no unescaped +/- issues
        atom_pat = re.compile(r"^[A-Za-z]{1,3}\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?$")
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


# FIX(M4): atoms list [(sym, (x,y,z))] → atom_spec string
def _atoms_list_to_spec(atoms_list: List[Tuple[str, Tuple[float, float, float]]]) -> str:
    """Convert [(symbol, (x, y, z)), ...] to PySCF atom-spec string."""
    lines = []
    for sym, (x, y, z) in atoms_list:
        lines.append(f"{sym} {x:.8f} {y:.8f} {z:.8f}")
    return "\n".join(lines)


def _iter_structure_libraries() -> Iterable[Mapping[str, str]]:
    candidate_names = ["BUILTIN_XYZ_LIBRARY", "XYZ_LIBRARY", "XYZ_LIBRARY_DATA", "STRUCTURE_LIBRARY", "MOLECULE_LIBRARY"]
    seen: set = set()
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

    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges",
             "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\b{re.escape(n)}\b", " ", qc, flags=re.I)
    qc = re.sub(r"\s+", " ", qc).strip()

    candidates = unique([q0, qn, qc, qn.replace(" ", "_"), qn.replace(" ", ""),
                         qc.replace(" ", "_"), qc.replace(" ", "")])

    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
        for kn_key, pair in normalized_map.items():
            if len(kn_key) > 2 and (kn_key in qn or kn_key in qc):
                return pair
    return None


def _resolve_structure_payload(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    # FIX(M4): atoms_list support
    atoms_list: Optional[List[Tuple[str, Tuple[float, float, float]]]] = None,
) -> Tuple[str, str]:
    """Resolve structure input to (name, atom_text).

    # FIX(M4): Now accepts atoms_list [(sym,(x,y,z))] in addition to xyz/atom_spec.
    """
    # FIX(M4): atoms_list takes priority
    if atoms_list:
        atom_text = _atoms_list_to_spec(atoms_list)
        return _safe_str(structure_query, "custom"), atom_text

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

        # Apply chemistry abbreviation lookup before resolver
        _resolve_query = structure_query
        try:
            from qcviz_mcp.services.structure_resolver import CHEM_ABBREVIATIONS
            abbrev_key = _resolve_query.lower().strip()
            if abbrev_key in CHEM_ABBREVIATIONS:
                _resolve_query = CHEM_ABBREVIATIONS[abbrev_key]
                logger.info("Abbreviation '%s' → '%s'", structure_query, _resolve_query)
        except ImportError:
            pass

        # FIX(M4): Try MoleculeResolver if available (backward compat with tools/core.py)
        resolve_error = None
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(_resolve_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except ImportError:
            pass
        except Exception as e:
            resolve_error = e

        if resolve_error:
            raise ValueError(
                f"'{structure_query}' 구조를 해석할 수 없습니다: {resolve_error} / "
                f"Could not resolve structure '{structure_query}': {resolve_error}"
            ) from resolve_error

    raise ValueError(
        "구조를 확인할 수 없습니다. 쿼리, XYZ, 또는 atom-spec을 제공하세요. / "
        "No structure could be resolved; provide query, XYZ, or atom-spec text."
    )


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
    effective_mult, warning = coerce_multiplicity_for_structure(
        atom_spec=atom_text,
        charge=charge,
        multiplicity=multiplicity,
    )
    spin = max(int(effective_mult or 1) - 1, 0)
    mol = gto.M(
        atom=atom_text,
        basis=basis_name,
        charge=int(charge or 0),
        spin=spin,
        unit=unit,
        verbose=0,
    )
    try:
        setattr(mol, "_qcviz_requested_multiplicity", int(_safe_int(multiplicity, 1) or 1))
        setattr(mol, "_qcviz_effective_multiplicity", int(effective_mult))
        setattr(mol, "_qcviz_effective_spin", int(spin))
        if warning:
            setattr(mol, "_qcviz_spin_warning", warning)
    except Exception:
        pass
    return mol


def _iter_atom_symbols(atom_text: str) -> List[str]:
    lines = [ln.strip() for ln in _strip_xyz_header(_safe_str(atom_text)).splitlines() if ln.strip()]
    symbols: List[str] = []
    for line in lines:
        token = line.split()[0]
        if not token:
            continue
        if token.isdigit():
            atomic_number = int(token)
            if 0 < atomic_number < len(elements.ELEMENTS):
                symbols.append(elements.ELEMENTS[atomic_number])
            continue
        if token[0].isdigit():
            continue
        sym = token[0].upper() + token[1:].lower()
        symbols.append(sym)
    return symbols


def _estimate_electron_count(atom_text: str, charge: int = 0) -> Optional[int]:
    symbols = _iter_atom_symbols(atom_text)
    if not symbols:
        return None
    total = 0
    for sym in symbols:
        try:
            total += int(elements.charge(sym))
        except Exception:
            return None
    return total - int(_safe_int(charge, 0) or 0)


def coerce_multiplicity_for_structure(
    *,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
) -> Tuple[int, Optional[str]]:
    atom_text = _safe_str(atom_spec) or _safe_str(_strip_xyz_header(_safe_str(xyz)))
    requested = max(int(_safe_int(multiplicity, 1) or 1), 1)
    electron_count = _estimate_electron_count(atom_text, charge=charge)
    if electron_count is None or electron_count <= 0:
        return requested, None

    requested_spin = requested - 1
    if requested_spin <= electron_count and ((electron_count - requested_spin) % 2 == 0):
        return requested, None

    if electron_count % 2 == 0:
        corrected = requested if requested % 2 == 1 else max(1, requested - 1)
        if corrected < 1 or (corrected - 1) > electron_count:
            corrected = 1
    else:
        corrected = requested if requested % 2 == 0 else requested + 1
        if corrected < 2:
            corrected = 2
        if (corrected - 1) > electron_count:
            corrected = max(2, electron_count if electron_count % 2 == 1 else electron_count + 1)

    if corrected == requested:
        return corrected, None

    warning = (
        f"Multiplicity auto-adjusted from {requested} to {corrected} "
        f"to match electron-count parity (N={electron_count}, charge={int(_safe_int(charge, 0) or 0)})."
    )
    return corrected, warning


def _build_mean_field(mol: gto.Mole, method: Optional[str] = None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))
    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf
    xc_map = {
        "b3lyp": "b3lyp", "pbe": "pbe", "pbe0": "pbe0", "m06-2x": "m06-2x",
        "m062x": "m06-2x", "wb97x-d": "wb97x-d", "wb97x-v": "wb97x-v",
        "tpssh": "tpssh", "tpss": "tpss", "r2scan": "r2scan", "pw6b95": "pw6b95",
        "bp86": "bp86", "blyp": "blyp",
    }
    xc = xc_map.get(key)
    if xc is None:
        xc = key
        logger.warning("Method '%s' not predefined; using '%s' directly.", method_name, key)
    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass
    return method_name, mf


# ── SCF Cache ────────────────────────────────────────────────

try:
    from qcviz_mcp.compute.disk_cache import save_to_disk, load_from_disk
except ImportError:
    def save_to_disk(*a: Any, **kw: Any) -> None: pass  # type: ignore
    def load_from_disk(*a: Any, **kw: Any) -> Tuple[None, None]: return None, None  # type: ignore

_SCF_CACHE: Dict[str, Any] = {}
_SCF_CACHE_LOCK = threading.Lock()
_CANCEL_FLAGS: Dict[str, bool] = {}  # job cancellation flags


def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode("utf-8")).hexdigest()


def _run_scf_with_fallback(
    mf: Any,
    warnings: Optional[List[str]] = None,
    cache_key: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    job_id: Optional[str] = None,
) -> Tuple[Any, float]:
    warnings = warnings if warnings is not None else []
    current_mol = getattr(mf, "mol", None)

    if cache_key:
        with _SCF_CACHE_LOCK:
            if cache_key in _SCF_CACHE:
                cached_mf, cached_energy = _SCF_CACHE[cache_key]
                if current_mol is not None:
                    cached_mf.mol = current_mol
                if progress_callback:
                    _emit_progress(
                        progress_callback,
                        0.5,
                        "scf",
                        "Cache hit: SCF skipped (0.0s)",
                        scf_history=list(getattr(cached_mf, "_qcviz_scf_history", []) or [])[-50:],
                        scf_cycle=int(getattr(cached_mf, "_qcviz_scf_cycles", 0) or 0),
                        scf_elapsed_s=float(getattr(cached_mf, "_qcviz_scf_elapsed_s", 0.0) or 0.0),
                    )
                return cached_mf, cached_energy
        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            if current_mol is not None:
                disk_mf.mol = current_mol
            if progress_callback:
                _emit_progress(
                    progress_callback,
                    0.5,
                    "scf",
                    "Disk cache hit (0.0s)",
                    scf_history=list(getattr(disk_mf, "_qcviz_scf_history", []) or [])[-50:],
                    scf_cycle=int(getattr(disk_mf, "_qcviz_scf_cycles", 0) or 0),
                    scf_elapsed_s=float(getattr(disk_mf, "_qcviz_scf_elapsed_s", 0.0) or 0.0),
                )
            return disk_mf, disk_energy

    try:
        mf.conv_tol = min(getattr(mf, "conv_tol", 1e-9), 1e-9)
    except Exception:
        pass
    try:
        mf.max_cycle = max(int(getattr(mf, "max_cycle", 50)), 100)
    except Exception:
        pass

    cycle_count = [0]
    prev_energy = [None]
    scf_history = []  # list of {cycle, energy, dE}

    def _attach_scf_metadata(target_mf: Any, *, elapsed_s: Optional[float] = None) -> None:
        try:
            setattr(target_mf, "_qcviz_scf_history", list(scf_history))
            setattr(target_mf, "_qcviz_scf_cycles", int(cycle_count[0]))
            if elapsed_s is not None:
                setattr(target_mf, "_qcviz_scf_elapsed_s", float(elapsed_s))
            if scf_history:
                setattr(target_mf, "_qcviz_scf_final_delta_e_hartree", scf_history[-1].get("dE"))
        except Exception:
            pass

    def _scf_callback(env: Dict[str, Any]) -> None:
        try:
            cycle_count[0] += 1
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0)

            # Compute dE (energy change from previous cycle)
            dE = None
            if prev_energy[0] is not None:
                dE = e - prev_energy[0]
            prev_energy[0] = e

            # Build history entry
            entry = {"cycle": c, "energy": round(e, 10)}
            if dE is not None:
                entry["dE"] = round(dE, 12)
            scf_history.append(entry)

            # Check cancel flag
            cancel_key = cache_key if cache_key and cache_key in _CANCEL_FLAGS else (job_id if job_id and job_id in _CANCEL_FLAGS else None)
            if cancel_key:
                del _CANCEL_FLAGS[cancel_key]
                raise KeyboardInterrupt("Job cancelled by user")

            if progress_callback:
                pct = min(0.60, 0.35 + (c / 100.0) * 0.25)
                dE_str = f" dE={dE:+.2e}" if dE is not None else ""
                msg = f"SCF iteration {c}/{max_c} (E={e:.6f} Ha{dE_str})"
                _emit_progress(progress_callback, pct, "scf", msg,
                               scf_cycle=c, scf_energy=e, scf_dE=dE,
                               scf_max_cycle=max_c if isinstance(max_c, int) else 100,
                               scf_history=scf_history[-20:])  # last 20 for chart
        except KeyboardInterrupt:
            raise
        except Exception:
            pass

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
        _attach_scf_metadata(mf, elapsed_s=elapsed)
        if progress_callback:
            _emit_progress(
                progress_callback,
                0.60,
                "scf",
                f"SCF converged in {cycles} cycles ({elapsed:.1f}s)",
                scf_history=scf_history[-50:],
                scf_cycle=cycles,
                scf_elapsed_s=elapsed,
            )
        if cache_key:
            with _SCF_CACHE_LOCK:
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
        _attach_scf_metadata(mf, elapsed_s=(t2 - t0))
        if progress_callback:
            _emit_progress(
                progress_callback,
                0.65,
                "scf",
                f"Newton refinement finished ({t2 - t1:.1f}s)",
                scf_history=scf_history[-50:],
                scf_cycle=cycle_count[0],
                scf_elapsed_s=(t2 - t0),
            )
        if cache_key and getattr(mf, "converged", False):
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
    except Exception as exc:
        warnings.append(f"Newton refinement failed: {exc}")

    _attach_scf_metadata(mf, elapsed_s=(time.time() - t0))
    return mf, energy


# ── File / cube helpers ──────────────────────────────────────

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
        return {"range_au": default_au, "range_kcal": default_au * HARTREE_TO_KCAL, "stats": {}, "strategy": "default"}

    masked = arr
    if density_values is not None:
        dens_raw = np.asarray(density_values, dtype=float).ravel()
        esp_raw = np.asarray(esp_values, dtype=float).ravel()
        if dens_raw.size == esp_raw.size:
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
    dynamic_upper = max(0.18, min(float(p995) * 1.2, 0.50))
    robust = float(np.clip(robust, 0.02, dynamic_upper))
    nice = _nice_symmetric_limit(robust)

    return {
        "range_au": nice, "range_kcal": nice * HARTREE_TO_KCAL,
        "stats": {
            "n": int(masked.size), "min_au": float(np.min(masked)),
            "max_au": float(np.max(masked)), "mean_au": float(np.mean(masked)),
            "std_au": float(np.std(masked)), "p90_abs_au": p90,
            "p95_abs_au": p95, "p98_abs_au": p98, "p995_abs_au": p995,
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
            pass
    return _compute_esp_auto_range(esp_values, density_values=density_values, density_iso=density_iso)


# ── Geometry / charge / orbital helpers ──────────────────────

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
                bonds.append({"a": i, "b": j, "order": 1, "length_angstrom": dist})
    return bonds


def _normalize_partial_charges(mol: gto.Mole, charges: Optional[Sequence[float]]) -> List[Dict[str, Any]]:
    if charges is None:
        return []
    return [{"atom_index": i, "symbol": mol.atom_symbol(i), "charge": float(q)} for i, q in enumerate(charges)]


def _geometry_summary(mol: gto.Mole, bonds: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    centroid = coords.mean(axis=0) if len(coords) else np.zeros(3)
    bbox_min = coords.min(axis=0) if len(coords) else np.zeros(3)
    bbox_max = coords.max(axis=0) if len(coords) else np.zeros(3)
    dims = bbox_max - bbox_min
    bond_lengths = [float(b["length_angstrom"]) for b in (bonds or []) if "length_angstrom" in b]
    return {
        "n_atoms": int(mol.natm), "formula": _formula_from_symbols(symbols),
        "centroid_angstrom": [float(x) for x in centroid],
        "bbox_min_angstrom": [float(x) for x in bbox_min],
        "bbox_max_angstrom": [float(x) for x in bbox_max],
        "bbox_size_angstrom": [float(x) for x in dims],
        "bond_count": int(len(bonds or [])),
        "bond_length_min_angstrom": float(min(bond_lengths)) if bond_lengths else None,
        "bond_length_max_angstrom": float(max(bond_lengths)) if bond_lengths else None,
        "bond_length_mean_angstrom": float(np.mean(bond_lengths)) if bond_lengths else None,
    }


def _extract_dipole(mf: Any) -> Optional[Dict[str, Any]]:
    try:
        vec = np.asarray(mf.dip_moment(unit="Debye", verbose=0), dtype=float).ravel()
        if vec.size >= 3:
            return {"x": float(vec[0]), "y": float(vec[1]), "z": float(vec[2]),
                    "magnitude": float(np.linalg.norm(vec[:3])), "unit": "Debye"}
    except Exception:
        pass
    return None


def _extract_mulliken_charges(mol: gto.Mole, mf: Any) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, "mol", None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]
        s = getattr(mf, "get_ovlp", lambda: active_mol.intor_symmetric("int1e_ovlp"))()
        try:
            _, chg = mf.mulliken_pop(mol=active_mol, dm=dm, s=s, verbose=0)
        except TypeError:
            _, chg = mf.mulliken_pop(active_mol, dm, s, verbose=0)
        except AttributeError:
            from pyscf.scf import hf as scf_hf
            _, chg = scf_hf.mulliken_pop(active_mol, dm, s=s, verbose=0)
        safe_chg = [0.0 if (np.isnan(q) or np.isinf(q)) else float(q) for q in chg]
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        logger.warning("Mulliken population failed: %s", e)
        return []


def _extract_lowdin_charges(mol: gto.Mole, mf: Any) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, "mol", None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]
        s = getattr(mf, "get_ovlp", lambda: active_mol.intor_symmetric("int1e_ovlp"))()
        from pyscf.scf import hf as scf_hf
        _, chg = scf_hf.lowdin_pop(active_mol, dm, s=s, verbose=0)
        safe_chg = [0.0 if (np.isnan(q) or np.isinf(q)) else float(q) for q in chg]
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        logger.warning("Löwdin population failed: %s", e)
        return []


def _restricted_or_unrestricted_arrays(mf: Any) -> Tuple[list, list, list, List[str]]:
    mo_energy = mf.mo_energy
    mo_occ = mf.mo_occ
    mo_coeff = mf.mo_coeff
    if isinstance(mo_energy, tuple):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels
    if isinstance(mo_energy, list) and mo_energy and isinstance(mo_energy[0], np.ndarray):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels
    mo_energy = np.asarray(mo_energy)
    mo_occ = np.asarray(mo_occ)
    if mo_energy.ndim == 2 and mo_energy.shape[0] == 2:
        mo_coeff_arr = np.asarray(mo_coeff)
        if mo_coeff_arr.ndim == 3 and mo_coeff_arr.shape[0] == 2:
            coeff_list = [mo_coeff_arr[0], mo_coeff_arr[1]]
        elif isinstance(mo_coeff, (tuple, list)) and len(mo_coeff) == 2:
            coeff_list = [np.asarray(mo_coeff[0]), np.asarray(mo_coeff[1])]
        else:
            coeff_list = [mo_coeff_arr, mo_coeff_arr]
        return [mo_energy[0], mo_energy[1]], [mo_occ[0], mo_occ[1]], coeff_list, ["alpha", "beta"]
    mo_coeff = np.asarray(mo_coeff)
    return [mo_energy], [mo_occ], [mo_coeff], ["restricted"]


def _build_orbital_items(mf: Any, window: int = 4) -> List[Dict[str, Any]]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    items: List[Dict[str, Any]] = []
    for ch, (energies, occs, spin_label) in enumerate(zip(mo_energies, mo_occs, spin_labels)):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)
        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0:
            lo, hi = 0, min(len(energies), 2 * window + 1)
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
            items.append({
                "index": idx + 1, "zero_based_index": idx, "label": label,
                "spin": spin_label, "occupancy": occ,
                "energy_hartree": float(energies[idx]),
                "energy_ev": float(energies[idx] * HARTREE_TO_EV),
            })
    items.sort(key=lambda x: (x.get("spin") != "restricted", x["zero_based_index"]))
    return items


def _resolve_orbital_selection(mf: Any, orbital: Optional[Union[str, int]]) -> Dict[str, Any]:
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
        idx, label = homo, "HOMO"
    elif raw == "LUMO":
        idx, label = lumo, "LUMO"
    else:
        # FIX(M4): safe regex for HOMO-N / LUMO+N — escaped + properly
        m1 = re.fullmatch(r"HOMO\s*-\s*(\d+)", raw)
        m2 = re.fullmatch(r"LUMO\s*\+\s*(\d+)", raw)
        if m1:
            delta = int(m1.group(1))
            idx, label = max(0, homo - delta), f"HOMO-{delta}"
        elif m2:
            delta = int(m2.group(1))
            idx, label = min(len(energies) - 1, lumo + delta), f"LUMO+{delta}"
    return {
        "spin_channel": channel, "spin": spin_label, "index": idx + 1,
        "zero_based_index": idx, "label": label,
        "energy_hartree": float(energies[idx]), "energy_ev": float(energies[idx] * HARTREE_TO_EV),
        "occupancy": float(occs[idx]), "coefficient_matrix": mo_coeffs[channel],
    }


def _extract_frontier_gap(mf: Any) -> Dict[str, Any]:
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
            "spin": spin_label, "homo_index": homo_idx + 1, "lumo_index": lumo_idx + 1,
            "homo_energy_hartree": float(energies[homo_idx]),
            "lumo_energy_hartree": float(energies[lumo_idx]),
            "homo_energy_ev": float(energies[homo_idx] * HARTREE_TO_EV),
            "lumo_energy_ev": float(energies[lumo_idx] * HARTREE_TO_EV),
            "gap_hartree": gap_ha, "gap_ev": gap_ha * HARTREE_TO_EV,
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


def _extract_spin_info(mf: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        ss = mf.spin_square()
        if isinstance(ss, tuple) and len(ss) >= 2:
            info["spin_square"] = float(ss[0])
            info["spin_multiplicity_estimate"] = float(ss[1])
    except Exception:
        pass
    return info


def _coalesce_density_matrix(dm: Any) -> np.ndarray:
    if isinstance(dm, tuple):
        return np.asarray(dm[0]) + np.asarray(dm[1])
    dm_arr = np.asarray(dm)
    if dm_arr.ndim == 3 and dm_arr.shape[0] == 2:
        return dm_arr[0] + dm_arr[1]
    return dm_arr


def _selected_orbital_vector(mf: Any, selection: Mapping[str, Any]) -> np.ndarray:
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


def generate_orbital_cube_b64(cache_key: str, orbital_index: int) -> Optional[str]:
    """Generate cube data for a specific orbital using cached SCF result."""
    with _SCF_CACHE_LOCK:
        cached = _SCF_CACHE.get(cache_key)
    if cached is None:
        # Try disk cache fallback
        disk_mf, disk_energy = load_from_disk(cache_key)
        if disk_mf is not None:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            cached = (disk_mf, disk_energy)
    if cached is None:
        return None
    mf, _ = cached
    mol = mf.mol
    try:
        coeff = mf.mo_coeff
        if isinstance(coeff, (tuple, list)):
            coeff_mat = np.asarray(coeff[0])
        else:
            coeff_mat = np.asarray(coeff)
        if orbital_index < 0 or orbital_index >= coeff_mat.shape[1]:
            return None
        coeff_vec = np.asarray(coeff_mat[:, orbital_index], dtype=float)
        with tempfile.TemporaryDirectory(prefix="qcviz_orb_") as tmpdir:
            cube_path = Path(tmpdir) / "orbital.cube"
            cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)
            return _file_to_b64(cube_path)
    except Exception as exc:
        logger.warning("generate_orbital_cube_b64 failed: %s", exc)
        return None


def _emit_progress(progress_callback: Optional[Callable[..., Any]], progress: float, step: str, message: Optional[str] = None, **extra: Any) -> None:
    if not callable(progress_callback):
        return
    payload = {"progress": float(progress), "step": _safe_str(step, "working"), "message": _safe_str(message, message or step)}
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
    forced = _safe_str(result.get("advisor_focus_tab") or result.get("focus_tab") or result.get("default_tab")).lower()
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


def _attach_visualization_payload(result: Dict[str, Any], xyz_text: str,
                                   orbital_cube_path: Optional[Union[str, Path]] = None,
                                   density_cube_path: Optional[Union[str, Path]] = None,
                                   esp_cube_path: Optional[Union[str, Path]] = None,
                                   orbital_meta: Optional[Mapping[str, Any]] = None,
                                   esp_meta: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
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
            vis.setdefault("density", {})["cube_b64"] = dens_b64
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


def _make_base_result(*, job_type: str, structure_name: str, atom_text: str, mol: gto.Mole,
                       method: Optional[str] = None, basis: Optional[str] = None,
                       charge: int = 0, multiplicity: int = 1,
                       advisor_focus_tab: Optional[str] = None) -> Dict[str, Any]:
    xyz_text = _mol_to_xyz(mol, comment=structure_name or "QCViz-MCP")
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds = _guess_bonds(mol)
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    atoms = [{"atom_index": i, "symbol": symbols[i], "element": symbols[i],
              "x": float(coords[i, 0]), "y": float(coords[i, 1]), "z": float(coords[i, 2])}
             for i in range(mol.natm)]
    effective_multiplicity = int(getattr(mol, "_qcviz_effective_multiplicity", _safe_int(multiplicity, 1) or 1) or 1)
    result: Dict[str, Any] = {
        "success": True, "job_type": _safe_str(job_type, "analyze"),
        "structure_name": _safe_str(structure_name, "custom"),
        "structure_query": _safe_str(structure_name, "custom"),
        "atom_spec": atom_text, "xyz": xyz_text,
        "method": _normalize_method_name(method or DEFAULT_METHOD),
        "basis": _normalize_basis_name(basis or DEFAULT_BASIS),
        "charge": int(charge or 0), "multiplicity": effective_multiplicity,
        "n_atoms": int(mol.natm), "formula": _formula_from_symbols(symbols),
        "atoms": atoms, "bonds": bonds, "geometry_summary": _geometry_summary(mol, bonds),
        "warnings": [], "events": [], "advisor_focus_tab": advisor_focus_tab,
        "visualization": {"xyz": xyz_text, "molecule_xyz": xyz_text,
                          "defaults": {"style": "stick", "labels": False, "orbital_iso": 0.050,
                                       "orbital_opacity": 0.85, "esp_density_iso": 0.001, "esp_opacity": 0.90}},
    }
    spin_warning = _safe_str(getattr(mol, "_qcviz_spin_warning", ""))
    if spin_warning:
        result["warnings"].append(spin_warning)
    return _finalize_result_contract(result)


def _populate_scf_fields(result: Dict[str, Any], mol: gto.Mole, mf: Any, *,
                          include_charges: bool = True, include_orbitals: bool = True) -> Dict[str, Any]:
    result["scf_converged"] = bool(getattr(mf, "converged", False))
    result["total_energy_hartree"] = float(getattr(mf, "e_tot", np.nan))
    result["total_energy_ev"] = float(result["total_energy_hartree"] * HARTREE_TO_EV)
    result["total_energy_kcal_mol"] = float(result["total_energy_hartree"] * HARTREE_TO_KCAL)
    scf_history = list(getattr(mf, "_qcviz_scf_history", []) or [])
    if scf_history:
        result["scf_history"] = scf_history[-100:]
        result["n_scf_cycles"] = int(getattr(mf, "_qcviz_scf_cycles", len(scf_history)) or len(scf_history))
        final_delta = getattr(mf, "_qcviz_scf_final_delta_e_hartree", None)
        if final_delta is None and scf_history:
            final_delta = scf_history[-1].get("dE")
        if final_delta is not None:
            result["scf_final_delta_e_hartree"] = float(final_delta)
    elapsed_s = getattr(mf, "_qcviz_scf_elapsed_s", None)
    if elapsed_s is not None:
        result["scf_elapsed_s"] = float(elapsed_s)
    dip = _extract_dipole(mf)
    if dip:
        result["dipole_moment"] = dip
    result.update(_extract_frontier_gap(mf))
    result.update(_extract_spin_info(mf))
    if include_charges:
        try:
            mull = _extract_mulliken_charges(mol, mf)
            if mull:
                result["mulliken_charges"] = mull
            low = _extract_lowdin_charges(mol, mf)
            if low:
                result["lowdin_charges"] = low
            result["partial_charges"] = low if low else mull
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Charge analysis failed: {exc}")
    if include_orbitals:
        try:
            result["orbitals"] = _build_orbital_items(mf)
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Orbital analysis failed: {exc}")
    return result


def _prepare_structure_bundle(*, structure_query: Optional[str] = None, xyz: Optional[str] = None,
                               atom_spec: Optional[str] = None,
                               atoms_list: Optional[List[Tuple[str, Tuple[float, float, float]]]] = None,
                               basis: Optional[str] = None, charge: int = 0,
                               multiplicity: int = 1) -> Tuple[str, str, gto.Mole]:
    # FIX(M4): atoms_list support propagated
    structure_name, atom_text = _resolve_structure_payload(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec, atoms_list=atoms_list,
    )
    mol = _build_mol(atom_text=atom_text, basis=basis or DEFAULT_BASIS,
                     charge=charge, multiplicity=multiplicity, unit="Angstrom")
    return structure_name, atom_text, mol


# ── PUBLIC RUNNER FUNCTIONS ──────────────────────────────────
# All signatures kept identical for backward compatibility.

def run_resolve_structure(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                          atom_spec: Optional[str] = None, basis: Optional[str] = None,
                          charge: int = 0, multiplicity: int = 1,
                          progress_callback: Optional[Callable[..., Any]] = None,
                          advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    _emit_progress(progress_callback, 0.75, "geometry", "Preparing geometry payload")
    result = _make_base_result(job_type="resolve_structure", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=kwargs.get("method") or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "geometry")
    result["resolved_structure"] = {"name": structure_name, "xyz": result["xyz"], "atom_spec": atom_text}
    _emit_progress(progress_callback, 1.0, "done", "Structure resolved")
    return _finalize_result_contract(result)


def run_geometry_analysis(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                          atom_spec: Optional[str] = None, basis: Optional[str] = None,
                          charge: int = 0, multiplicity: int = 1,
                          progress_callback: Optional[Callable[..., Any]] = None,
                          advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    result = _make_base_result(job_type="geometry_analysis", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=kwargs.get("method") or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "geometry")
    _emit_progress(progress_callback, 1.0, "done", "Geometry analysis complete")
    return _finalize_result_contract(result)


def run_single_point(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                     atom_spec: Optional[str] = None, method: Optional[str] = None,
                     basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                     progress_callback: Optional[Callable[..., Any]] = None,
                     advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    result = _make_base_result(job_type="single_point", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=method or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "summary")
    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    _emit_progress(progress_callback, 0.85, "analyze", "Collecting observables")
    _populate_scf_fields(result, mol, mf, include_charges=False, include_orbitals=True)
    _emit_progress(progress_callback, 1.0, "done", "Single-point calculation complete")
    return _finalize_result_contract(result)


def run_partial_charges(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                        atom_spec: Optional[str] = None, method: Optional[str] = None,
                        basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                        progress_callback: Optional[Callable[..., Any]] = None,
                        advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    result = _make_base_result(job_type="partial_charges", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=method or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "charges")
    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    _emit_progress(progress_callback, 0.80, "charges", "Computing Mulliken charges")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=False)
    _emit_progress(progress_callback, 1.0, "done", "Partial charge analysis complete")
    return _finalize_result_contract(result)


def run_orbital_preview(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                        atom_spec: Optional[str] = None, method: Optional[str] = None,
                        basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                        orbital: Optional[Union[str, int]] = None,
                        progress_callback: Optional[Callable[..., Any]] = None,
                        advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    result = _make_base_result(job_type="orbital_preview", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=method or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "orbital")
    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)
    _emit_progress(progress_callback, 0.70, "orbital_select", "Selecting orbital")
    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {k: v for k, v in selection.items() if k != "coefficient_matrix"}

    # Generate cubes for ALL orbitals in the window (for instant switching)
    orbitals_list = result.get("orbitals", [])
    orbital_cubes = {}  # zero_based_index -> cube_b64
    try:
        with tempfile.TemporaryDirectory(prefix="qcviz_orb_") as tmpdir:
            coeff = mf.mo_coeff
            if isinstance(coeff, (tuple, list)):
                coeff_mat = np.asarray(coeff[0])
            else:
                coeff_mat = np.asarray(coeff)

            for i, orb in enumerate(orbitals_list):
                idx = orb.get("zero_based_index", i)
                if idx < 0 or idx >= coeff_mat.shape[1]:
                    continue
                pct = 0.70 + (i / max(len(orbitals_list), 1)) * 0.25
                _emit_progress(progress_callback, pct, "orbital_cube",
                               f"Generating cube {i+1}/{len(orbitals_list)} ({orb.get('label', idx)})")
                try:
                    cube_path = Path(tmpdir) / f"orbital_{idx}.cube"
                    coeff_vec = np.asarray(coeff_mat[:, idx], dtype=float)
                    cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)
                    b64 = _file_to_b64(cube_path)
                    if b64:
                        orbital_cubes[str(idx)] = b64
                except Exception as exc:
                    logger.warning("Cube generation failed for orbital %s: %s", idx, exc)

            # Attach the selected orbital's cube as the primary visualization
            sel_idx = str(selection.get("zero_based_index", 0))
            sel_cube = orbital_cubes.get(sel_idx)
            if sel_cube:
                cube_path = Path(tmpdir) / "selected.cube"
                # Write back the selected cube for _attach_visualization_payload
                import base64
                cube_bytes = base64.b64decode(sel_cube)
                cube_path.write_bytes(cube_bytes)
                _attach_visualization_payload(result, xyz_text=result["xyz"], orbital_cube_path=cube_path,
                                              orbital_meta={"label": selection.get("label"), "index": selection.get("index"),
                                                            "zero_based_index": selection.get("zero_based_index"),
                                                            "spin": selection.get("spin"),
                                                            "energy_hartree": selection.get("energy_hartree"),
                                                            "energy_ev": selection.get("energy_ev"),
                                                            "occupancy": selection.get("occupancy")})
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Orbital cube generation failed: {exc}")

    result["orbital_cubes"] = orbital_cubes
    _emit_progress(progress_callback, 1.0, "done", "Orbital preview complete")
    return _finalize_result_contract(result)


def run_esp_map(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                atom_spec: Optional[str] = None, method: Optional[str] = None,
                basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                esp_preset: Optional[str] = None,
                progress_callback: Optional[Callable[..., Any]] = None,
                advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(job_type="esp_map", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=method or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "esp")
    result["esp_preset"] = preset_key
    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)
    try:
        _emit_progress(progress_callback, 0.70, "cube", "Generating density/ESP cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_esp_") as tmpdir:
            density_cube = Path(tmpdir) / "density.cube"
            esp_cube = Path(tmpdir) / "esp.cube"
            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            esp_fit = _compute_esp_auto_range_from_cube_files(esp_cube, density_cube, density_iso=0.001)
            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit
            _attach_visualization_payload(result, xyz_text=result["xyz"],
                                          density_cube_path=density_cube, esp_cube_path=esp_cube,
                                          esp_meta={"preset": preset_key, "range_au": esp_fit["range_au"],
                                                    "range_kcal": esp_fit["range_kcal"], "density_iso": 0.001,
                                                    "opacity": 0.90, "fit_stats": esp_fit.get("stats", {}),
                                                    "fit_strategy": esp_fit.get("strategy")})
    except Exception as exc:
        result.setdefault("warnings", []).append(f"ESP cube generation failed: {exc}")
    _emit_progress(progress_callback, 1.0, "done", "ESP map complete")
    result["job_type"] = "esp_map"
    return _finalize_result_contract(result)


def run_geometry_optimization(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                               atom_spec: Optional[str] = None, method: Optional[str] = None,
                               basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                               progress_callback: Optional[Callable[..., Any]] = None,
                               advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol0 = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    initial_result = _make_base_result(job_type="geometry_optimization", structure_name=structure_name,
                                        atom_text=atom_text, mol=mol0, method=method or DEFAULT_METHOD,
                                        basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                        advisor_focus_tab=advisor_focus_tab or "geometry")
    _emit_progress(progress_callback, 0.12, "build_scf", "Building initial SCF model")
    method_name, mf0 = _build_mean_field(mol0, method or DEFAULT_METHOD)
    trajectory: List[Dict[str, Any]] = []

    def _geomopt_callback(envs: Dict[str, Any]) -> None:
        try:
            mol_current = envs.get("mol")
            e_current = envs.get("e_tot")
            g = envs.get("gradients", envs.get("gradient"))
            grad_norm = float(np.linalg.norm(g)) if g is not None else None
            step_num = len(trajectory) + 1
            xyz_string = _mol_to_xyz(mol_current, comment=f"Step {step_num}") if mol_current else None
            trajectory.append({"step": step_num, "energy_hartree": float(e_current) if e_current is not None else None,
                               "grad_norm": grad_norm, "xyz": xyz_string})
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
            from pyscf.geomopt.geometric_solver import optimize as geo_opt
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (geometric)")
            opt_mol = geo_opt(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
        except (ImportError, Exception) as e:
            if isinstance(e, ImportError):
                logger.info("geometric solver not found, trying berny")
            else:
                logger.warning("geometric solver failed: %s, trying berny", e)
            from pyscf.geomopt.berny_solver import optimize as berny_opt
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (berny)")
            opt_mol = berny_opt(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
    except Exception as exc:
        logger.warning("Geometry optimization failed: %s", exc)
        initial_result.setdefault("warnings", []).append(f"Geometry optimization failed: {exc}")
        opt_mol = mol0

    _emit_progress(progress_callback, 0.88, "final_scf", "Running final SCF on optimized geometry")
    method_name, mf = _build_mean_field(opt_mol, method or DEFAULT_METHOD)
    new_xyz = _mol_to_xyz(opt_mol, comment=structure_name or "QCViz-MCP")
    cache_key = _get_cache_key(new_xyz, method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    mf, _ = _run_scf_with_fallback(mf, initial_result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    final_result = _make_base_result(job_type="geometry_optimization", structure_name=structure_name,
                                      atom_text=_strip_xyz_header(_mol_to_xyz(opt_mol)), mol=opt_mol,
                                      method=method_name, basis=basis or DEFAULT_BASIS, charge=charge,
                                      multiplicity=multiplicity, advisor_focus_tab=advisor_focus_tab or "geometry")
    final_result["warnings"] = _dedupe_strings(initial_result.get("warnings", []))
    final_result["optimization_performed"] = optimization_performed
    final_result["optimization_steps"] = len(trajectory)
    final_result["trajectory"] = trajectory
    if trajectory:
        frames = [step.get("xyz", "").strip() for step in trajectory if step.get("xyz")]
        if frames:
            final_result["trajectory_xyz"] = "\n".join(frames) + "\n"
    final_result["initial_xyz"] = initial_result["xyz"]
    final_result["optimized_xyz"] = final_result["xyz"]
    _populate_scf_fields(final_result, opt_mol, mf, include_charges=True, include_orbitals=True)
    _emit_progress(progress_callback, 1.0, "done", "Geometry optimization complete")
    return _finalize_result_contract(final_result)


def run_analyze(structure_query: Optional[str] = None, xyz: Optional[str] = None,
                atom_spec: Optional[str] = None, method: Optional[str] = None,
                basis: Optional[str] = None, charge: int = 0, multiplicity: int = 1,
                orbital: Optional[Union[str, int]] = None, esp_preset: Optional[str] = None,
                progress_callback: Optional[Callable[..., Any]] = None,
                advisor_focus_tab: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query, xyz=xyz, atom_spec=atom_spec,
        atoms_list=kwargs.get("atoms_list"), basis=basis, charge=charge, multiplicity=multiplicity)
    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(job_type="analyze", structure_name=structure_name,
                                atom_text=atom_text, mol=mol, method=method or DEFAULT_METHOD,
                                basis=basis or DEFAULT_BASIS, charge=charge, multiplicity=multiplicity,
                                advisor_focus_tab=advisor_focus_tab or "summary")
    result["esp_preset"] = preset_key
    _emit_progress(progress_callback, 0.12, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    _emit_progress(progress_callback, 0.30, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback, job_id=kwargs.get("job_id"))
    _emit_progress(progress_callback, 0.55, "analysis", "Collecting quantitative results")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)
    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {k: v for k, v in selection.items() if k != "coefficient_matrix"}
    try:
        _emit_progress(progress_callback, 0.72, "cube", "Generating visualization cubes")
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
            esp_fit = _compute_esp_auto_range_from_cube_files(esp_cube, density_cube, density_iso=0.001)
            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit
            _attach_visualization_payload(result, xyz_text=result["xyz"],
                                          orbital_cube_path=orbital_cube, density_cube_path=density_cube,
                                          esp_cube_path=esp_cube,
                                          orbital_meta={"label": selection.get("label"), "index": selection.get("index"),
                                                        "zero_based_index": selection.get("zero_based_index"),
                                                        "spin": selection.get("spin"),
                                                        "energy_hartree": selection.get("energy_hartree"),
                                                        "energy_ev": selection.get("energy_ev"),
                                                        "occupancy": selection.get("occupancy")},
                                          esp_meta={"preset": preset_key, "range_au": esp_fit["range_au"],
                                                    "range_kcal": esp_fit["range_kcal"], "density_iso": 0.001,
                                                    "opacity": 0.90, "fit_stats": esp_fit.get("stats", {}),
                                                    "fit_strategy": esp_fit.get("strategy")})
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Visualization cube generation failed: {exc}")
    _emit_progress(progress_callback, 1.0, "done", "Full analysis complete")
    return _finalize_result_contract(result)


__all__ = [
    "HARTREE_TO_EV", "HARTREE_TO_KCAL", "BOHR_TO_ANGSTROM", "EV_TO_KCAL",
    "DEFAULT_METHOD", "DEFAULT_BASIS", "ESP_PRESETS_DATA",
    "coerce_multiplicity_for_structure",
    "run_resolve_structure", "run_geometry_analysis", "run_single_point",
    "run_partial_charges", "run_orbital_preview", "run_esp_map",
    "run_geometry_optimization", "run_analyze",
]
