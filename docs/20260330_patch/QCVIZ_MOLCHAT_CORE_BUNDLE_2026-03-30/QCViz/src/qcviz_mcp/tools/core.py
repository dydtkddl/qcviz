"""QCViz-MCP tool implementation v3.0.0 (Enterprise - Sync Compatible)."""

from __future__ import annotations

import json
import logging
import pathlib
import traceback
import os
import asyncio
import concurrent.futures
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np

from qcviz_mcp.backends.pyscf_backend import PySCFBackend, ESPResult, _cli
from qcviz_mcp.backends.viz_backend import (
    Py3DmolBackend,
    DashboardPayload,
    CubeNormalizer,
)

from qcviz_mcp.backends.registry import registry
from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.security import (
    validate_atom_spec_strict, validate_path, validate_basis,
    default_bucket, validate_atom_spec as _validate_atom_spec,
    validate_path as _validate_file_path, _PROJECT_ROOT
)
from qcviz_mcp.observability import traced_tool, metrics, ToolInvocation
try:
    from qcviz_mcp.execution.worker import _executor
except Exception:
    import atexit
    import os
    from concurrent.futures import ThreadPoolExecutor

    _executor = ThreadPoolExecutor(
        max_workers=max(4, min(32, (os.cpu_count() or 4) * 2)),
        thread_name_prefix="qcviz-core-fallback",
    )

    @atexit.register
    def _shutdown_core_executor():
        try:
            _executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
from qcviz_mcp.execution.cache import cache

logger = logging.getLogger(__name__)
HARTREE_TO_EV = 27.2114
OUTPUT_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
_pyscf = PySCFBackend()
_viz = Py3DmolBackend()


class _NumpyEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


def _parse_atom_spec(atom_spec):
    lines = atom_spec.strip().splitlines()
    if len(lines) <= 2:
        return atom_spec
    if lines[0].strip().isdigit():
        return "\n".join(lines[2:])
    return atom_spec


def _extract_name(molecule_str, mol_obj):
    lines = molecule_str.strip().splitlines()
    if len(lines) > 1:
        name = lines[1].strip()
        if name and not name[0].isdigit() and len(name) < 100:
            return name.replace("\n", " ").replace("\r", " ")
    syms = [mol_obj.atom_symbol(i) for i in range(mol_obj.natm)]
    counts = Counter(syms)
    return "".join(
        "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
        for e in sorted(counts.keys())
    )


def _sanitize_display_name(name: Optional[str], fallback: str = "molecule") -> str:
    if not name:
        return fallback
    cleaned = str(name).strip().replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100] if cleaned else fallback


def _safe_filename(name: str, fallback: str = "molecule") -> str:
    cleaned = _sanitize_display_name(name, fallback=fallback)
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or fallback


class MoleculeResolver:
    """Resolve user query (XYZ / atom-spec / molecule name / SMILES) into XYZ text.

    Resolution order:
    1. If already XYZ text -> return as-is
    2. If already atom-spec text -> return as-is
    3. If looks like SMILES -> call Molchat directly
    4. Otherwise try PubChem name -> CanonicalSMILES -> Molchat
    """

    PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    MOLCHAT_BASE = "http://psid.aizen.co.kr/molchat/api/v1"
    DEFAULT_TIMEOUT = 30

    _ATOM_LINE_RE = re.compile(
        r"^\s*[A-Z][a-z]?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$"
    )
    _SMILES_LIKE_RE = re.compile(r"^[A-Za-z0-9@\+\-\[\]\(\)=#$\\/%.]+$")
    _SIMPLE_SMILES_TOKEN_RE = re.compile(
        r"^(?:Cl|Br|Si|Li|Na|Ca|Al|Mg|Zn|Fe|Cu|Mn|Hg|Ag|Pt|Au|Sn|Pb|Se|"
        r"[BCNOFPSIKH]|[bcnops])+$"
    )

    @classmethod
    def resolve(cls, query: str) -> str:
        if query is None:
            raise ValueError("입력 query가 비어 있습니다.")
        text = str(query).strip()
        if not text:
            raise ValueError("입력 query가 비어 있습니다.")

        if cls._is_xyz_text(text):
            return text

        if cls._is_atom_spec_text(text):
            return text

        if cls._looks_like_smiles(text):
            logger.info("MoleculeResolver: input recognized as SMILES-like string.")
            smiles = text
        else:
            logger.info("MoleculeResolver: resolving molecule name via PubChem: %s", text)
            smiles = cls._resolve_name_to_smiles(text)

        xyz = cls._generate_xyz_via_molchat(smiles)
        if not cls._is_xyz_text(xyz):
            raise ValueError("Molchat가 유효한 XYZ 구조를 반환하지 않았습니다.")
        return xyz

    @classmethod
    def _is_xyz_text(cls, text: str) -> bool:
        lines = [line.strip() for line in text.strip().splitlines()]
        if len(lines) < 3:
            return False
        if not lines[0].isdigit():
            return False

        atom_count = int(lines[0])
        if atom_count <= 0:
            return False

        # Some generators might omit the comment line or leave it empty
        # If line 1 is empty, it's just an empty comment
        atom_lines = lines[2:2 + atom_count]
        if len(atom_lines) < atom_count:
            # Maybe there was no comment line at all? Let's check if line 1 looks like an atom
            parts = lines[1].split()
            if len(parts) >= 4 and parts[0].isalpha():
                atom_lines = lines[1:1 + atom_count]
            else:
                return False

        if len(atom_lines) < atom_count:
            return False

        matched = 0
        for line in atom_lines:
            parts = line.split()
            if len(parts) < 4:
                return False
            try:
                float(parts[1])
                float(parts[2])
                float(parts[3])
            except Exception:
                return False
            matched += 1
        return matched == atom_count

    @classmethod
    def _is_atom_spec_text(cls, text: str) -> bool:
        lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return False
        if len(lines) == 1:
            return False
        return all(cls._ATOM_LINE_RE.match(line) for line in lines)

    @classmethod
    def _looks_like_smiles(cls, text: str) -> bool:
        if "\n" in text:
            return False

        s = text.strip()
        if not s or " " in s:
            return False

        if not cls._SMILES_LIKE_RE.match(s):
            return False

        # Strong SMILES markers
        if any(ch in s for ch in "[]=#()/\\@+$%"):
            return True
        if any(ch.isdigit() for ch in s):
            return True

        # Simple elemental-token-only linear smiles like CCO, CCN, O, N, ClCCl
        if cls._SIMPLE_SMILES_TOKEN_RE.fullmatch(s):
            return True

        return False

    @classmethod
    def _http_get_json(cls, url: str, timeout: int = None) -> Dict[str, Any]:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _http_post_json(
        cls,
        url: str,
        body: Dict[str, Any],
        timeout: int = None,
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _resolve_name_to_smiles(cls, name: str) -> str:
        import re
        clean_name = re.sub(r"(?i)\b(?:the|of|orbital|homo|lumo|mo|esp|map|charge|charges|mulliken|partial)\b", "", name).strip()
        quoted = urllib.parse.quote(clean_name, safe="")
        direct_url = (
            f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/property/CanonicalSMILES,IsomericSMILES/JSON"
        )

        try:
            data = cls._http_get_json(direct_url, timeout=20)
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                smiles = (p.get("CanonicalSMILES") or p.get("IsomericSMILES")
                          or p.get("SMILES") or p.get("ConnectivitySMILES"))
                if smiles:
                    return smiles
                # If PubChem returned properties but no SMILES, fall through to CID lookup
        except urllib.error.HTTPError as e:
            logger.warning("PubChem direct name->SMILES failed for %s: %s", name, e)
        except Exception as e:
            logger.warning("PubChem direct name->SMILES error for %s: %s", name, e)
        cid_url = f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/cids/JSON"
        try:
            data = cls._http_get_json(cid_url, timeout=20)
            cids = data.get("IdentifierList", {}).get("CID", [])
            if not cids:
                raise ValueError(f"PubChem에서 '{name}'에 대한 CID를 찾지 못했습니다.")
            cid = cids[0]
            prop_url = f"{cls.PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES/JSON"
            prop_data = cls._http_get_json(prop_url, timeout=20)
            props = prop_data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                return p.get("CanonicalSMILES") or p.get("IsomericSMILES") or p.get("SMILES") or p.get("ConnectivitySMILES")
        except Exception as e:
            raise ValueError(
                f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다: {e}"
            ) from e

        raise ValueError(f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다.")

    @classmethod
    def _generate_xyz_via_molchat(cls, smiles: str) -> str:
        url = f"{cls.MOLCHAT_BASE}/molecules/generate-3d"
        body = {
            "smiles": smiles,
            "format": "xyz",
            "optimize_xtb": True,
        }
        try:
            data = cls._http_post_json(url, body=body, timeout=60)
        except urllib.error.HTTPError as e:
            try:
                details = e.read().decode("utf-8", errors="replace")
            except Exception:
                details = str(e)
            raise ValueError(f"Molchat API 호출 실패: HTTP {e.code} - {details}") from e
        except Exception as e:
            raise ValueError(f"Molchat API 호출 실패: {e}") from e

        xyz = data.get("structure_data")
        if not xyz or not str(xyz).strip():
            raise ValueError("Molchat API 응답에 structure_data(XYZ)가 없습니다.")
        return str(xyz).strip()

    @classmethod
    def resolve_with_friendly_errors(cls, query: str) -> str:
        try:
            return cls.resolve(query)
        except Exception as e:
            raise ValueError(
                "분자 구조를 확보하지 못했습니다. "
                "XYZ 좌표를 직접 제공하거나, 인식 가능한 분자명/SMILES를 입력해 주세요. "
                f"원인: {e}"
            ) from e


def _resolve_query_input(query: str) -> Tuple[str, str, Optional[str]]:
    resolved_structure = MoleculeResolver.resolve_with_friendly_errors(query)
    validate_atom_spec_strict(resolved_structure)
    atom_data = _parse_atom_spec(resolved_structure)

    raw_query = str(query).strip() if query is not None else ""
    if MoleculeResolver._is_xyz_text(raw_query) or MoleculeResolver._is_atom_spec_text(raw_query):
        display_name_hint = None
    else:
        display_name_hint = _sanitize_display_name(raw_query)

    return resolved_structure, atom_data, display_name_hint


# --- Top-level implementation functions for Executor (Pickle-safe) ---

def _sync_compute_ibo_impl(
    atom_spec,
    basis,
    method,
    charge,
    spin,
    n_orbitals,
    include_esp,
    xyz_string_raw,
    display_name_hint=None,
):
    """
    Hybrid Orbital Rendering Architecture:
    - Occupied orbitals (idx <= HOMO): IBO coefficients for intuitive bond visualization
    - Virtual orbitals  (idx >  HOMO): Canonical MO coefficients from SCF result
    """
    scf_res, mol = _pyscf.compute_scf(atom_spec, basis, method, charge=charge, spin=spin)
    iao_res = _pyscf.compute_iao(scf_res, mol)
    ibo_res = _pyscf.compute_ibo(scf_res, iao_res, mol)

    # ── Determine orbital index boundaries ──
    mo_occ = scf_res.mo_occ
    n_ibo = ibo_res.n_ibo
    n_mo_total = scf_res.mo_coeff.shape[1]

    homo_idx = 0
    for i in range(len(mo_occ)):
        if mo_occ[i] > 0.5:
            homo_idx = i
    lumo_idx = homo_idx + 1

    selected = []

    if n_orbitals > 0:
        # Roughly half occupied / half virtual
        n_occ_to_show = max(1, n_orbitals // 2)
        n_vir_to_show = max(1, n_orbitals - n_occ_to_show)

        occ_start = max(0, homo_idx - n_occ_to_show + 1)
        occ_end = homo_idx + 1

        vir_start = lumo_idx
        vir_end = min(n_mo_total, lumo_idx + n_vir_to_show)

        occ_selected = [i for i in range(occ_start, occ_end) if scf_res.mo_energy[i] > -10.0]
        if not occ_selected and occ_end > 0:
            occ_selected = [homo_idx]

        vir_selected = list(range(vir_start, vir_end))
        selected = occ_selected + vir_selected

        if not selected:
            selected = list(range(max(0, n_ibo - n_orbitals), n_ibo))

    # ── Build XYZ data ──
    xyz_lines = [str(mol.natm), "QCViz Pro"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        c = mol.atom_coord(i) * 0.529177249  # Bohr to Angstrom
        xyz_lines.append("%s %.6f %.6f %.6f" % (sym, c[0], c[1], c[2]))
    xyz_data = "\n".join(xyz_lines)

    # ── Metadata ──
    if display_name_hint:
        clean_name = _sanitize_display_name(display_name_hint)
    else:
        clean_name = _extract_name(xyz_string_raw, mol)

    atom_symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    charges_dict = {
        "%s%d" % (atom_symbols[i], i + 1): float(iao_res.charges[i])
        for i in range(mol.natm)
    }

    payload = DashboardPayload(
        molecule_name=clean_name,
        xyz_data=xyz_data,
        atom_symbols=atom_symbols,
        basis=basis,
        method=method,
        energy_hartree=scf_res.energy_hartree,
        charges=charges_dict,
    )

    # ── Generate cube files with hybrid IBO/Canonical branching ──
    total_q = len(selected)
    for qi, i in enumerate(selected):
        if i == homo_idx:
            lbl = "HOMO"
        elif i == lumo_idx:
            lbl = "LUMO"
        elif i < homo_idx:
            lbl = "HOMO-%d" % (homo_idx - i)
        else:
            lbl = "LUMO+%d" % (i - lumo_idx)

        if i <= homo_idx:
            ibo_col_idx = i
            if ibo_col_idx < n_ibo:
                coeff_to_use = ibo_res.coefficients
                col_idx = ibo_col_idx
                lbl_suffix = "(IBO)"
            else:
                coeff_to_use = scf_res.mo_coeff
                col_idx = i
                lbl_suffix = "(Canonical)"
        else:
            coeff_to_use = scf_res.mo_coeff
            col_idx = i
            lbl_suffix = "(Canonical)"

        full_label = "%s %s" % (lbl, lbl_suffix)
        _cli.print_cube_progress(qi + 1, total_q, full_label)

        cube = _pyscf.generate_cube(
            mol, coeff_to_use, col_idx,
            grid_points=(60, 60, 60)
        )
        energy_eV = float(scf_res.mo_energy[i]) * HARTREE_TO_EV

        payload.orbitals.append(
            _viz.prepare_orbital_data(cube, i, full_label, energy=energy_eV)
        )

    # ── ESP calculation ──
    if include_esp:
        esp_res = _pyscf.compute_esp(
            atom_spec, basis, grid_size=60, charge=charge, spin=spin
        )
        payload.esp_data = _viz.prepare_esp_data(
            esp_res.density_cube, esp_res.potential_cube,
            esp_res.vmin, esp_res.vmax
        )

    # ── Render and save ──
    html = _viz.render_dashboard(payload)
    safe_name = _safe_filename(clean_name, fallback="molecule")
    html_path = OUTPUT_DIR / f"{safe_name}_dashboard.html"
    html_path.write_text(html, encoding="utf-8")

    n_occ_shown = len([i for i in selected if i <= homo_idx])
    n_vir_shown = len([i for i in selected if i > homo_idx])
    lumo_energy_ev = (
        round(float(scf_res.mo_energy[lumo_idx]) * HARTREE_TO_EV, 3)
        if lumo_idx < len(scf_res.mo_energy)
        else None
    )

    if n_orbitals > 0:
        message = (
            f"Hybrid orbital calculation complete: "
            f"{n_occ_shown} occupied (IBO) + {n_vir_shown} virtual (Canonical MO) orbitals. "
            f"HOMO={homo_idx}, LUMO={lumo_idx}, Total MOs={n_mo_total}."
        )
    else:
        message = (
            f"ESP calculation complete. "
            f"HOMO={homo_idx}, LUMO={lumo_idx}, Total MOs={n_mo_total}."
        )

    return {
        "status": "success",
        "message": message,
        "html_file": str(html_path),
        "n_ibo": int(n_ibo),
        "n_occupied_shown": int(n_occ_shown),
        "n_virtual_shown": int(n_vir_shown),
        "homo_idx": int(homo_idx),
        "lumo_idx": int(lumo_idx),
        "total_mos": int(n_mo_total),
        "energy_hartree": float(scf_res.energy_hartree),
        "homo_energy_ev": round(float(scf_res.mo_energy[homo_idx]) * HARTREE_TO_EV, 3),
        "lumo_energy_ev": lumo_energy_ev,
        "visualization_html": html,
    }


def _sync_compute_partial_charges_impl(
    xyz_string,
    basis,
    method="rhf",
    display_name_hint=None,
):
    atom_data = _parse_atom_spec(xyz_string)
    scf_res, mol = _pyscf.compute_scf(atom_data, basis=basis, method=method)
    iao_res = _pyscf.compute_iao(scf_res, mol)

    title = _sanitize_display_name(display_name_hint, fallback="molecule") if display_name_hint else None
    if title:
        msg = f"{title} — IAO 부분 전하 분석 결과:\n"
    else:
        msg = "IAO 부분 전하 분석 결과:\n"

    for i in range(mol.natm):
        msg += f"{mol.atom_symbol(i)}{i + 1}: {iao_res.charges[i]:+.4f}\n"
    return msg


def _sync_visualize_orbital_impl(
    xyz_string,
    orbital_index,
    basis,
    display_name_hint=None,
):
    atom_data = _parse_atom_spec(xyz_string)
    scf_res, mol = _pyscf.compute_scf(atom_data, basis=basis)
    idx = (
        orbital_index
        if orbital_index is not None
        else (len(scf_res.mo_occ[scf_res.mo_occ > 0.5]) - 1)
    )
    cube = _pyscf.generate_cube(mol, scf_res.mo_coeff, idx)

    mol_name = _sanitize_display_name(display_name_hint, fallback="QCViz") if display_name_hint else "QCViz"
    xyz_lines = [str(mol.natm), mol_name]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        c = mol.atom_coord(i) * 0.529177249
        xyz_lines.append("%s %.6f %.6f %.6f" % (sym, c[0], c[1], c[2]))
    xyz_data = "\n".join(xyz_lines)

    html = (
        "<!-- 성공적으로 오비탈 렌더링 HTML 생성 완료 -->\n"
        + _viz.render_orbital(xyz_data, cube)
    )

    safe_name = _safe_filename(mol_name, fallback=f"orbital_{idx}")
    html_path = OUTPUT_DIR / f"{safe_name}_orbital_{idx}.html"
    html_path.write_text(html, encoding="utf-8")
    return html


def _sync_convert_format_impl(input_path, output_path):
    from qcviz_mcp.backends.ase_backend import ASEBackend
    ASEBackend().convert_format(input_path, output_path)
    return f"성공적으로 변환 완료: {output_path}"


# --- Helper to run implementation functions safely (handles no-executor mode) ---
def _run_impl(func, *args, timeout=300.0, **kwargs):
    if _executor is None:
        return func(*args, **kwargs)
    else:
        return _executor.submit(func, *args, **kwargs).result(timeout=timeout)


# --- Tracing helper for sync tools ---
def sync_traced_tool(func):
    import uuid
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        invocation = ToolInvocation(
            tool_name=func.__name__,
            request_id=str(uuid.uuid4())[:8],
            parameters={k: str(v)[:100] for k, v in kwargs.items()},
        )
        try:
            result = func(*args, **kwargs)
            invocation.finish(status="success")
            metrics.record(invocation)
            return result
        except Exception as e:
            invocation.finish(status="error")
            invocation.error = str(e)
            metrics.record(invocation)
            raise

    return wrapper


# --- MCP Tool Definitions ---

@mcp.tool()
@sync_traced_tool
def compute_ibo(
    query: str,
    basis: str = "sto-3g",
    method: str = "rhf",
    charge: int = 0,
    spin: int = 0,
    n_orbitals: int = 12,
    include_esp: bool = True,
) -> str:
    """Intrinsic Bond Orbital (IBO) analysis and ESP visualization.

    query accepts:
    - XYZ string
    - atom-spec string
    - molecule name (resolved via PubChem -> SMILES -> Molchat)
    - SMILES (resolved via Molchat)
    """
    try:
        if not default_bucket.consume(10):
            return json.dumps({"status": "error", "error": "Rate limit exceeded"})

        validate_basis(basis)

        resolved_structure, atom_data, display_name_hint = _resolve_query_input(query)

        cache_key = cache.make_key(
            "compute_ibo",
            resolved_structure=resolved_structure,
            display_name_hint=display_name_hint,
            basis=basis,
            method=method,
            charge=charge,
            spin=spin,
            n_orbitals=n_orbitals,
            include_esp=include_esp,
        )
        cached = cache.get(cache_key)
        if cached:
            return cached

        result_dict = _run_impl(
            _sync_compute_ibo_impl,
            atom_data,
            basis,
            method,
            charge,
            spin,
            n_orbitals,
            include_esp,
            resolved_structure,
            display_name_hint,
            timeout=300.0,
        )
        res_json = json.dumps(result_dict, cls=_NumpyEncoder)
        cache.put(cache_key, res_json)
        return res_json

    except Exception as e:
        logger.error(traceback.format_exc())
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
@sync_traced_tool
def compute_esp(
    query: str,
    basis: str = "sto-3g",
    charge: int = 0,
) -> str:
    """Electrostatic Potential (ESP) surface generation."""
    return compute_ibo(
        query=query,
        basis=basis,
        include_esp=True,
        n_orbitals=0,
        charge=charge,
    )


@mcp.tool()
@sync_traced_tool
def compute_partial_charges(
    query: str,
    basis: str = "sto-3g",
    method: str = "rhf",
) -> str:
    """Compute IAO-based partial atomic charges.

    query accepts:
    - XYZ string
    - atom-spec string
    - molecule name
    - SMILES
    """
    try:
        if not default_bucket.consume(5):
            return "Error: Rate limit exceeded"

        validate_basis(basis)
        resolved_structure, _, display_name_hint = _resolve_query_input(query)

        return _run_impl(
            _sync_compute_partial_charges_impl,
            resolved_structure,
            basis,
            method=method,
            display_name_hint=display_name_hint,
            timeout=120.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def visualize_orbital(
    query: str,
    orbital_index: int = None,
    basis: str = "sto-3g",
) -> str:
    """Generate a standalone HTML for a specific molecular orbital."""
    try:
        if not default_bucket.consume(2):
            return "Error: Rate limit exceeded"

        validate_basis(basis)
        resolved_structure, _, display_name_hint = _resolve_query_input(query)

        return _run_impl(
            _sync_visualize_orbital_impl,
            resolved_structure,
            orbital_index,
            basis,
            display_name_hint=display_name_hint,
            timeout=120.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def parse_output(file_path: str) -> str:
    """Parse quantum chemistry output file using cclib."""
    from qcviz_mcp.backends.cclib_backend import CclibBackend
    try:
        if not default_bucket.consume(1):
            return "Error: Rate limit exceeded"
        p = validate_path(file_path)
        res = CclibBackend().parse_file(str(p))
        return json.dumps(
            {"program": res.program, "energy": res.energy_hartree},
            cls=_NumpyEncoder,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def convert_format(input_path: str, output_path: str) -> str:
    """Convert chemical files between formats (e.g., xyz to cif)."""
    try:
        if not default_bucket.consume(1):
            return "Error: Rate limit exceeded"
        p_in = validate_path(input_path)
        p_out = validate_path(output_path, mode="w")
        return _run_impl(
            _sync_convert_format_impl,
            str(p_in),
            str(p_out),
            timeout=60.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def analyze_bonding(query: str, basis: str = "sto-3g") -> str:
    """Analyze chemical bonding using IAO/IBO theory."""
    res_json = compute_ibo(
        query=query,
        basis=basis,
        n_orbitals=10,
        include_esp=False,
    )
    res = json.loads(res_json)
    if res["status"] == "success":
        return (
            f"IBO 결합 분석 완료. "
            f"전체 점유 IBO 수: {res['n_ibo']}. "
            f"표시된 점유/가상 오비탈: {res['n_occupied_shown']}/{res['n_virtual_shown']}. "
            f"대시보드: {res['html_file']}"
        )
    return f"분석 실패: {res.get('error')}"