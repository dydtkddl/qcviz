"""Advisor-tools integration layer for QCViz web chat flow.

Exact-signature adapter for qcviz_mcp.tools.advisor_tools.

This module is intentionally tuned to the real tool signatures:

- recommend_preset(atom_spec, purpose, charge, spin)
- draft_methods_section(system_name, atom_spec, functional, basis, charge, spin,
                        dispersion, software_version, optimizer, analysis_type,
                        citation_style, energy_hartree, converged, n_cycles)
- generate_script(system_name, atom_spec, functional, basis, charge, spin,
                  dispersion, optimizer, analysis_type, include_analysis)
- validate_against_literature(system_formula, functional, basis,
                              bond_lengths, bond_angles)
- score_confidence(functional, basis, converged, n_scf_cycles, max_cycles,
                   system_type, spin, s2_expected, s2_actual, validation_status)
"""

from __future__ import annotations

import importlib
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from qcviz_mcp import __version__ as QCVIZ_VERSION
try:
    from qcviz_mcp.tools.core import MoleculeResolver
except Exception:
    MoleculeResolver = None

def _get_resolver():
    if MoleculeResolver:
        return MoleculeResolver
    class _Fallback:
        @classmethod
        def resolve_with_friendly_errors(cls, q): return q
        @staticmethod
        def _is_xyz_text(t): return False
        @staticmethod
        def _is_atom_spec_text(t): return False
    return _Fallback

logger = logging.getLogger(__name__)

_MODULE_CACHE = None

_TM_3D = {
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
}
_TM_HEAVY = {
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
}
_LANTHANIDES = {
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
    "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
}
_MAIN_GROUP_METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Ga", "In",
    "Sn", "Tl", "Pb", "Bi", "Rb", "Sr", "Cs", "Ba",
}


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _parse_jsonish(value: Any) -> Any:
    """Parse JSON-like tool output when possible."""
    if isinstance(value, (dict, list)):
        return value

    if value is None:
        return None

    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except Exception:
            return value

    return value


def _load_advisor_module():
    """Load advisor tool module once."""
    global _MODULE_CACHE
    if _MODULE_CACHE is not None:
        return _MODULE_CACHE

    _MODULE_CACHE = importlib.import_module("qcviz_mcp.tools.advisor_tools")
    return _MODULE_CACHE


def _resolve_tool_callable(obj: Any) -> Any:
    """Resolve callable from MCP-decorated object if needed."""
    if callable(obj):
        return obj

    for attr in ("fn", "func", "__wrapped__"):
        candidate = getattr(obj, attr, None)
        if callable(candidate):
            return candidate

    return obj


def _get_tool(tool_name: str):
    module = _load_advisor_module()
    if not hasattr(module, tool_name):
        raise AttributeError(f"advisor tool not found: {tool_name}")

    obj = getattr(module, tool_name)
    func = _resolve_tool_callable(obj)
    if not callable(func):
        raise TypeError(f"advisor tool is not callable: {tool_name}")

    return func


def _wrap_tool_result(tool_name: str, raw: Any) -> Dict[str, Any]:
    """Normalize raw tool output into a common result envelope."""
    parsed = _parse_jsonish(raw)

    if isinstance(parsed, dict) and parsed.get("status") == "error":
        return {
            "status": "error",
            "tool": tool_name,
            "error": parsed.get("error") or "advisor tool error",
            "data": parsed,
            "raw": raw,
        }

    return {
        "status": "success",
        "tool": tool_name,
        "data": parsed,
        "raw": raw,
    }


def _call_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Call one advisor tool exactly once."""
    try:
        func = _get_tool(tool_name)
        raw = func(**kwargs)
        return _wrap_tool_result(tool_name, raw)
    except Exception as exc:
        logger.exception("advisor tool %s failed", tool_name)
        return {
            "status": "error",
            "tool": tool_name,
            "error": str(exc),
            "data": None,
            "raw": None,
        }


def _call_tool_candidates(tool_name: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Try multiple exact-signature candidate payloads until one succeeds."""
    attempts: List[Dict[str, Any]] = []

    for idx, kwargs in enumerate(candidates):
        result = _call_tool(tool_name, **kwargs)
        attempts.append({
            "index": idx,
            "status": result.get("status"),
            "error": result.get("error"),
            "keys": sorted(kwargs.keys()),
        })
        if result.get("status") == "success":
            result["attempts"] = attempts
            result["selected_candidate_index"] = idx
            return result

    return {
        "status": "error",
        "tool": tool_name,
        "error": "all exact-signature candidates failed",
        "data": None,
        "raw": None,
        "attempts": attempts,
    }


# -----------------------------------------------------------------------------
# Structure / chemistry helpers
# -----------------------------------------------------------------------------


def _is_xyz_text(text: Optional[str]) -> bool:
    if not text:
        return False
    lines = [line.strip() for line in str(text).strip().splitlines()]
    if len(lines) < 3:
        return False
    if not lines[0].isdigit():
        return False
    atom_count = int(lines[0])
    return len([line for line in lines if line]) >= atom_count + 1


def _xyz_to_atom_spec(xyz_text: str) -> str:
    """Convert XYZ to compact atom-spec (headerless atom lines)."""
    lines = [line.rstrip() for line in str(xyz_text).strip().splitlines() if line.strip()]
    if len(lines) >= 3 and lines[0].strip().isdigit():
        return "\n".join(lines[2:]).strip()
    return str(xyz_text).strip()


def _extract_symbols_from_xyz(xyz_text: Optional[str]) -> List[str]:
    if not xyz_text:
        return []

    lines = [line.strip() for line in str(xyz_text).strip().splitlines()]
    if len(lines) < 3 or not lines[0].isdigit():
        return []

    atom_count = int(lines[0])
    if len([line for line in lines if line]) < atom_count + 1:
        return []

    symbols: List[str] = []
    for line in lines[2:2 + atom_count]:
        parts = line.split()
        if parts:
            symbols.append(parts[0])
    return symbols


def _formula_from_xyz(xyz_text: Optional[str]) -> Optional[str]:
    symbols = _extract_symbols_from_xyz(xyz_text)
    if not symbols:
        return None

    counts = Counter(symbols)
    parts: List[str] = []

    for elem in ("C", "H"):
        if elem in counts:
            n_val = counts.pop(elem)
            parts.append(elem if n_val == 1 else f"{elem}{n_val}")

    for elem in sorted(counts.keys()):
        n_val = counts[elem]
        parts.append(elem if n_val == 1 else f"{elem}{n_val}")

    return "".join(parts) if parts else None


def _display_name_from_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "molecule"

    resolver = _get_resolver()
    if hasattr(resolver, "_is_xyz_text") and resolver._is_xyz_text(text):
        return "molecule"
    if hasattr(resolver, "_is_atom_spec_text") and resolver._is_atom_spec_text(text):
        return "molecule"

    return text[:100]


def _intent_to_purpose(intent_name: str) -> str:
    """Map chat intent to recommend_preset purpose values."""
    name = (intent_name or "").strip().lower()

    if name == "geometry_opt":
        return "geometry_opt"
    if name == "single_point":
        return "single_point"
    if name == "esp":
        return "esp_mapping"
    if name in {"orbital", "partial_charges", "analyze"}:
        return "bonding_analysis"
    if name in {"validate", "draft_methods", "generate_script", "resolve"}:
        return "single_point"
    return "single_point"


def _intent_to_analysis_type(intent_name: str) -> str:
    """Map chat intent to methods/script analysis labels."""
    name = (intent_name or "").strip().lower()

    if name == "geometry_opt":
        return "geometry_optimization"
    if name == "partial_charges":
        return "population_analysis"
    if name == "orbital":
        return "orbital_analysis"
    if name == "esp":
        return "esp"
    if name == "validate":
        return "geometry_validation"
    if name == "draft_methods":
        return "methods_drafting"
    if name == "generate_script":
        return "script_generation"
    if name == "resolve":
        return "structure_resolution"
    return "single_point"


def _guess_dispersion(functional: Optional[str], preset_dispersion: Optional[str]) -> str:
    if preset_dispersion:
        return str(preset_dispersion)

    name = (functional or "").lower()
    if "d3" in name and "bj" in name:
        return "D3(BJ)"
    if "d3" in name:
        return "D3"
    if "d4" in name:
        return "D4"
    if "vv10" in name:
        return "VV10"
    return ""


def _normalize_bond_key(label: str) -> str:
    elems = re.findall(r"[A-Z][a-z]?", label or "")
    if len(elems) < 2:
        return label or "bond"
    elems = sorted(elems[:2])
    return f"{elems[0]}-{elems[1]}"


def _normalize_angle_key(label: str) -> str:
    elems = re.findall(r"[A-Z][a-z]?", label or "")
    if len(elems) < 3:
        return label or "angle"
    elems = elems[:3]
    return f"{elems[0]}-{elems[1]}-{elems[2]}"


def _summarize_bond_lengths(result: Dict[str, Any]) -> Dict[str, float]:
    bonds = result.get("bonds") or []
    if not isinstance(bonds, list):
        return {}

    out: Dict[str, float] = {}
    for bond in bonds:
        if not isinstance(bond, dict):
            continue

        label = str(
            bond.get("label")
            or bond.get("pair")
            or bond.get("atoms")
            or ""
        )
        key = _normalize_bond_key(label)
        dist = _safe_float(
            bond.get("distance_angstrom")
            or bond.get("length_angstrom")
            or bond.get("distance")
            or bond.get("length")
        )
        if dist is None:
            continue

        if key not in out or dist < out[key]:
            out[key] = dist

    return out


def _summarize_bond_angles(result: Dict[str, Any]) -> Dict[str, float]:
    angles = result.get("angles") or []
    if not isinstance(angles, list):
        return {}

    bucket: Dict[str, List[float]] = defaultdict(list)

    for angle in angles:
        if not isinstance(angle, dict):
            continue

        label = str(angle.get("label") or angle.get("atoms") or "")
        key = _normalize_angle_key(label)
        val = _safe_float(angle.get("angle_deg") or angle.get("angle"))
        if val is not None:
            bucket[key].append(val)

    out: Dict[str, float] = {}
    for key, values in bucket.items():
        if values:
            out[key] = sum(values) / float(len(values))
    return out


def _extract_energy_hartree(result: Dict[str, Any]) -> float:
    if "energy_hartree" in result:
        return float(result.get("energy_hartree") or 0.0)

    scf = result.get("scf") or {}
    for key in ("energy_hartree", "energy", "e_tot"):
        if key in scf:
            return float(scf.get(key) or 0.0)

    return 0.0


def _extract_converged(result: Dict[str, Any]) -> bool:
    if isinstance(result.get("converged"), bool):
        return result["converged"]

    scf = result.get("scf") or {}
    if isinstance(scf.get("converged"), bool):
        return scf["converged"]

    return True


def _extract_n_cycles(result: Dict[str, Any]) -> int:
    if "scf_cycles" in result:
        return _safe_int(result.get("scf_cycles"), 0)

    scf = result.get("scf") or {}
    for key in ("n_cycles", "cycles", "scf_cycles", "iterations"):
        if key in scf:
            return _safe_int(scf.get(key), 0)

    return 0


def _extract_max_cycles(result: Dict[str, Any]) -> int:
    if "max_cycles" in result:
        return _safe_int(result.get("max_cycles"), 200)

    scf = result.get("scf") or {}
    return _safe_int(scf.get("max_cycles"), 200)


def _extract_s2_actual(result: Dict[str, Any]) -> float:
    if "actual_s2" in result:
        return float(result.get("actual_s2") or 0.0)

    scf = result.get("scf") or {}
    for key in ("actual_s2", "s2", "<S^2>", "spin_square"):
        if key in scf:
            return float(scf.get(key) or 0.0)

    return 0.0


def _s2_expected_from_spin(spin: int) -> float:
    s_val = float(spin) / 2.0
    return s_val * (s_val + 1.0)


def _infer_system_type(result: Dict[str, Any], xyz_text: Optional[str]) -> str:
    symbols = _extract_symbols_from_xyz(xyz_text)
    charge = _safe_int(result.get("charge"), 0)
    spin = _safe_int(result.get("spin"), 0)
    atom_count = _safe_int(result.get("atom_count"), len(symbols))

    if any(sym in _LANTHANIDES for sym in symbols):
        return "lanthanide"
    if any(sym in _TM_3D for sym in symbols):
        return "3d_tm"
    if any(sym in _TM_HEAVY for sym in symbols):
        return "heavy_tm"
    if any(sym in _MAIN_GROUP_METALS for sym in symbols):
        return "main_group_metal"
    if spin > 0:
        return "radical"
    if charge != 0:
        return "charged_organic"
    if atom_count > 24:
        return "organic_large"
    return "organic_small"


def _normalize_validation_status(literature_result: Optional[Dict[str, Any]]) -> Optional[str]:
    """Convert validator overall_status to PASS/WARN/FAIL-ish status."""
    if not literature_result or literature_result.get("status") != "success":
        return None

    data = literature_result.get("data")
    if not isinstance(data, dict):
        return None

    raw = str(data.get("overall_status") or "").strip().upper()
    if not raw:
        return None

    if raw in {"PASS", "OK", "GOOD", "CONSISTENT"}:
        return "PASS"
    if raw in {"WARN", "WARNING", "PARTIAL", "MIXED"}:
        return "WARN"
    if raw in {"FAIL", "BAD", "ERROR"}:
        return "FAIL"

    return raw


# -----------------------------------------------------------------------------
# Tool output normalization
# -----------------------------------------------------------------------------


def _extract_preset_data(preset_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not preset_result or preset_result.get("status") != "success":
        return {}

    data = preset_result.get("data")
    if not isinstance(data, dict):
        return {}

    return {
        "functional": data.get("functional"),
        "basis": data.get("basis"),
        "dispersion": data.get("dispersion"),
        "spin_treatment": data.get("spin_treatment"),
        "relativistic": data.get("relativistic"),
        "convergence": data.get("convergence"),
        "alternatives": data.get("alternatives"),
        "warnings": data.get("warnings"),
        "references": data.get("references"),
        "rationale": data.get("rationale"),
        "confidence": data.get("confidence"),
        "pyscf_settings": data.get("pyscf_settings"),
        "raw": data,
    }


# -----------------------------------------------------------------------------
# Record building
# -----------------------------------------------------------------------------


def _build_record(
    query: str,
    intent_name: str,
    result: Dict[str, Any],
    preset_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    xyz_text = result.get("xyz") or (preset_bundle or {}).get("resolved_xyz")
    compact_atom_spec = _xyz_to_atom_spec(xyz_text) if xyz_text else ""
    formula = result.get("formula") or _formula_from_xyz(xyz_text)
    preset_data = _extract_preset_data((preset_bundle or {}).get("preset"))

    functional = result.get("method") or preset_data.get("functional") or "B3LYP"
    basis = result.get("basis") or preset_data.get("basis") or "def2-SVP"
    dispersion = (
        result.get("dispersion")
        or preset_data.get("dispersion")
        or _guess_dispersion(functional, preset_data.get("dispersion"))
    )

    return {
        "query": query,
        "intent": intent_name,
        "purpose": _intent_to_purpose(intent_name),
        "analysis_type": _intent_to_analysis_type(intent_name),
        "system_name": result.get("display_name") or formula or _display_name_from_query(query),
        "formula": formula,
        "xyz_text": xyz_text,
        "atom_spec_compact": compact_atom_spec,
        "functional": functional,
        "basis": basis,
        "dispersion": dispersion,
        "charge": _safe_int(result.get("charge"), 0),
        "spin": _safe_int(result.get("spin"), 0),
        "software": "PySCF",
        "software_version": str(result.get("software_version") or f"QCViz-MCP {QCVIZ_VERSION}"),
        "optimizer": str(result.get("optimizer") or ("geomeTRIC" if intent_name == "geometry_opt" else "")),
        "energy_hartree": _extract_energy_hartree(result),
        "converged": _extract_converged(result),
        "n_cycles": _extract_n_cycles(result),
        "max_cycles": _extract_max_cycles(result),
        "s2_expected": _s2_expected_from_spin(_safe_int(result.get("spin"), 0)),
        "s2_actual": _extract_s2_actual(result),
        "system_type": _infer_system_type(result, xyz_text),
        "job_type": result.get("job_type"),
        "atom_count": _safe_int(result.get("atom_count"), 0),
    }


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def prepare_advisor_plan(
    query: str,
    intent_name: str,
    charge: int = 0,
    spin: int = 0,
) -> Dict[str, Any]:
    """Resolve geometry and run exact-signature recommend_preset."""
    out: Dict[str, Any] = {
        "status": "success",
        "purpose": _intent_to_purpose(intent_name),
        "resolved_xyz": None,
        "resolved_atom_spec": None,
        "preset": None,
        "applied_functional": None,
        "applied_basis": None,
        "warnings": [],
    }

    try:
        resolver = _get_resolver()
        xyz = resolver.resolve_with_friendly_errors(query)
        out["resolved_xyz"] = xyz
        out["resolved_atom_spec"] = _xyz_to_atom_spec(xyz)
    except Exception as exc:
        out["status"] = "error"
        out["warnings"].append(f"구조 사전 해석 실패: {exc}")
        return out

    # There is ambiguity in the codebase: the parameter is named atom_spec,
    # but docstrings mention XYZ format. We therefore try both compact atom-spec
    # and full XYZ, using the exact same signature each time.
    preset_candidates = [
        {
            "atom_spec": out["resolved_atom_spec"],
            "purpose": out["purpose"],
            "charge": int(charge),
            "spin": int(spin),
        },
        {
            "atom_spec": out["resolved_xyz"],
            "purpose": out["purpose"],
            "charge": int(charge),
            "spin": int(spin),
        },
    ]

    preset = _call_tool_candidates("recommend_preset", preset_candidates)
    out["preset"] = preset

    norm = _extract_preset_data(preset)
    out["applied_functional"] = norm.get("functional")
    out["applied_basis"] = norm.get("basis")

    if preset.get("status") != "success":
        out["warnings"].append(
            f"advisor preset 실패: {preset.get('error', 'unknown error')}"
        )
    if not out["applied_functional"]:
        out["warnings"].append("advisor preset에서 functional을 추출하지 못했습니다.")
    if not out["applied_basis"]:
        out["warnings"].append("advisor preset에서 basis를 추출하지 못했습니다.")

    return out


def prepare_advisor_plan_from_geometry(
    *,
    intent_name: str,
    xyz_text: Optional[str] = None,
    atom_spec: Optional[str] = None,
    charge: int = 0,
    spin: int = 0,
) -> Dict[str, Any]:
    """Run recommend_preset directly from already-resolved geometry.

    This avoids re-resolving the structure through legacy resolver paths and is
    safe to call from the web compute pipeline after geometry is available.
    """
    compact_atom_spec = atom_spec or (_xyz_to_atom_spec(xyz_text) if xyz_text else None)
    out: Dict[str, Any] = {
        "status": "success",
        "purpose": _intent_to_purpose(intent_name),
        "resolved_xyz": xyz_text,
        "resolved_atom_spec": compact_atom_spec,
        "preset": None,
        "applied_functional": None,
        "applied_basis": None,
        "warnings": [],
    }

    preset_candidates = []
    if compact_atom_spec:
        preset_candidates.append(
            {
                "atom_spec": compact_atom_spec,
                "purpose": out["purpose"],
                "charge": int(charge),
                "spin": int(spin),
            }
        )
    if xyz_text:
        preset_candidates.append(
            {
                "atom_spec": xyz_text,
                "purpose": out["purpose"],
                "charge": int(charge),
                "spin": int(spin),
            }
        )

    if not preset_candidates:
        out["status"] = "error"
        out["warnings"].append("advisor preset을 위한 geometry 정보가 없습니다.")
        return out

    preset = _call_tool_candidates("recommend_preset", preset_candidates)
    out["preset"] = preset

    norm = _extract_preset_data(preset)
    out["applied_functional"] = norm.get("functional")
    out["applied_basis"] = norm.get("basis")

    if preset.get("status") != "success":
        out["warnings"].append(
            f"advisor preset 실패: {preset.get('error', 'unknown error')}"
        )
    if not out["applied_functional"]:
        out["warnings"].append("advisor preset에서 functional을 추출하지 못했습니다.")
    if not out["applied_basis"]:
        out["warnings"].append("advisor preset에서 basis를 추출하지 못했습니다.")

    return out


def apply_preset_to_runner_kwargs(
    runner_kwargs: Dict[str, Any],
    advisor_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply advisor preset into compute runner kwargs."""
    merged = dict(runner_kwargs or {})
    if not advisor_plan:
        return merged

    functional = advisor_plan.get("applied_functional")
    basis = advisor_plan.get("applied_basis")

    if functional and not merged.get("_method_user_supplied", False):
        merged["method"] = functional
    if basis and not merged.get("_basis_user_supplied", False):
        merged["basis"] = basis

    return merged


def enrich_result_with_advisor(
    query: str,
    intent_name: str,
    result: Dict[str, Any],
    preset_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run exact-signature postcompute advisor enrichment."""
    advisor: Dict[str, Any] = {
        "status": "success",
        "preset": None,
        "methods": None,
        "script": None,
        "literature": None,
        "confidence": None,
        "record": None,
    }

    if preset_bundle:
        advisor["preset"] = preset_bundle.get("preset")
    else:
        advisor["preset"] = prepare_advisor_plan(
            query=query,
            intent_name=intent_name,
            charge=_safe_int(result.get("charge"), 0),
            spin=_safe_int(result.get("spin"), 0),
        ).get("preset")

    record = _build_record(
        query=query,
        intent_name=intent_name,
        result=result,
        preset_bundle=preset_bundle,
    )
    advisor["record"] = record

    # -----------------------------------------------------------------
    # draft_methods_section
    # Exact signature:
    #   system_name, atom_spec, functional, basis, charge, spin,
    #   dispersion, software_version, optimizer, analysis_type,
    #   citation_style, energy_hartree, converged, n_cycles
    # -----------------------------------------------------------------
    methods_candidates = []
    for atom_spec_candidate in filter(None, [record["xyz_text"], record["atom_spec_compact"]]):
        methods_candidates.append({
            "system_name": record["system_name"],
            "atom_spec": atom_spec_candidate,
            "functional": record["functional"],
            "basis": record["basis"],
            "charge": int(record["charge"]),
            "spin": int(record["spin"]),
            "dispersion": record["dispersion"],
            "software_version": record["software_version"],
            "optimizer": record["optimizer"],
            "analysis_type": record["analysis_type"],
            "citation_style": "acs",
            "energy_hartree": float(record["energy_hartree"]),
            "converged": bool(record["converged"]),
            "n_cycles": int(record["n_cycles"]),
        })
    advisor["methods"] = _call_tool_candidates("draft_methods_section", methods_candidates)

    # -----------------------------------------------------------------
    # generate_script
    # Exact signature:
    #   system_name, atom_spec, functional, basis, charge, spin,
    #   dispersion, optimizer, analysis_type, include_analysis
    # -----------------------------------------------------------------
    script_candidates = []
    for atom_spec_candidate in filter(None, [record["xyz_text"], record["atom_spec_compact"]]):
        script_candidates.append({
            "system_name": record["system_name"],
            "atom_spec": atom_spec_candidate,
            "functional": record["functional"],
            "basis": record["basis"],
            "charge": int(record["charge"]),
            "spin": int(record["spin"]),
            "dispersion": record["dispersion"],
            "optimizer": record["optimizer"],
            "analysis_type": record["analysis_type"],
            "include_analysis": True,
        })
    advisor["script"] = _call_tool_candidates("generate_script", script_candidates)

    # -----------------------------------------------------------------
    # validate_against_literature
    # Exact signature:
    #   system_formula, functional, basis, bond_lengths, bond_angles
    # -----------------------------------------------------------------
    bond_lengths = _summarize_bond_lengths(result)
    bond_angles = _summarize_bond_angles(result)

    if record["formula"] and (bond_lengths or bond_angles):
        advisor["literature"] = _call_tool(
            "validate_against_literature",
            system_formula=record["formula"],
            functional=record["functional"],
            basis=record["basis"],
            bond_lengths=bond_lengths or None,
            bond_angles=bond_angles or None,
        )
    else:
        advisor["literature"] = {
            "status": "skipped",
            "tool": "validate_against_literature",
            "error": "formula 또는 geometry 요약 정보가 부족하여 문헌 검증을 생략했습니다.",
            "data": None,
            "raw": None,
        }

    # -----------------------------------------------------------------
    # score_confidence
    # Exact signature:
    #   functional, basis, converged, n_scf_cycles, max_cycles,
    #   system_type, spin, s2_expected, s2_actual, validation_status
    # -----------------------------------------------------------------
    validation_status = _normalize_validation_status(advisor["literature"])
    advisor["confidence"] = _call_tool(
        "score_confidence",
        functional=record["functional"],
        basis=record["basis"],
        converged=bool(record["converged"]),
        n_scf_cycles=int(record["n_cycles"]),
        max_cycles=int(record["max_cycles"]),
        system_type=record["system_type"],
        spin=int(record["spin"]),
        s2_expected=float(record["s2_expected"]),
        s2_actual=float(record["s2_actual"]),
        validation_status=validation_status,
    )

    advisor["meta"] = {
        "query": query,
        "intent_name": intent_name,
        "system_name": record["system_name"],
        "formula": record["formula"],
        "purpose": record["purpose"],
        "analysis_type": record["analysis_type"],
        "functional": record["functional"],
        "basis": record["basis"],
        "dispersion": record["dispersion"],
        "charge": record["charge"],
        "spin": record["spin"],
        "software_version": record["software_version"],
        "optimizer": record["optimizer"],
        "energy_hartree": record["energy_hartree"],
        "converged": record["converged"],
        "n_cycles": record["n_cycles"],
        "max_cycles": record["max_cycles"],
        "system_type": record["system_type"],
        "s2_expected": record["s2_expected"],
        "s2_actual": record["s2_actual"],
        "bond_length_keys": sorted(list(bond_lengths.keys())),
        "bond_angle_keys": sorted(list(bond_angles.keys())),
        "validation_status_normalized": validation_status,
    }

    return advisor


def summarize_advisor_payload(advisor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a compact UI-friendly summary from advisor tool payloads."""
    payload = dict(advisor or {})
    preset_data = _extract_preset_data(payload.get("preset"))

    confidence_bundle = payload.get("confidence") or {}
    confidence_data = confidence_bundle.get("data") if isinstance(confidence_bundle, dict) else None
    literature_bundle = payload.get("literature") or {}
    literature_data = literature_bundle.get("data") if isinstance(literature_bundle, dict) else None
    methods_bundle = payload.get("methods") or {}
    methods_data = methods_bundle.get("data") if isinstance(methods_bundle, dict) else None
    script_bundle = payload.get("script") or {}
    script_data = script_bundle.get("data") if isinstance(script_bundle, dict) else None

    methods_text = ""
    if isinstance(methods_data, dict):
        methods_text = str(
            methods_data.get("methods_text")
            or methods_data.get("summary")
            or methods_data.get("message")
            or ""
        ).strip()
    elif isinstance(methods_data, str):
        methods_text = methods_data.strip()

    script_text = ""
    if isinstance(script_data, dict):
        script_text = str(
            script_data.get("script")
            or script_data.get("script_text")
            or script_data.get("message")
            or ""
        ).strip()
    elif isinstance(script_data, str):
        script_text = script_data.strip()

    confidence_score = None
    recommendations: List[str] = []
    if isinstance(confidence_data, dict):
        confidence_score = _safe_float(
            confidence_data.get("overall_score")
            or confidence_data.get("score")
            or confidence_data.get("confidence")
            or confidence_data.get("final_score")
        )
        raw_recs = confidence_data.get("recommendations") or []
        if isinstance(raw_recs, list):
            recommendations = [str(item).strip() for item in raw_recs if str(item).strip()]

    literature_status = None
    literature_summary = None
    if isinstance(literature_data, dict):
        literature_status = str(
            literature_data.get("status")
            or literature_data.get("validation_status")
            or ""
        ).strip() or None
        literature_summary = str(
            literature_data.get("summary")
            or literature_data.get("message")
            or literature_data.get("status")
            or ""
        ).strip() or None
    elif literature_bundle:
        literature_status = str(literature_bundle.get("status") or "").strip() or None
        literature_summary = str(literature_bundle.get("error") or "").strip() or None

    return {
        "recommended_functional": preset_data.get("functional"),
        "recommended_basis": preset_data.get("basis"),
        "preset_rationale": preset_data.get("rationale"),
        "confidence_score": confidence_score,
        "confidence_label": (
            "high" if confidence_score is not None and confidence_score >= 0.75
            else "medium" if confidence_score is not None and confidence_score >= 0.45
            else "low" if confidence_score is not None
            else None
        ),
        "literature_status": literature_status,
        "literature_summary": literature_summary,
        "methods_preview": methods_text[:400] if methods_text else None,
        "script_preview": script_text[:280] if script_text else None,
        "recommendations": recommendations[:5],
    }
