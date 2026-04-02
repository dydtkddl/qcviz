"""Ion pair abbreviation dictionary and multi-ion resolve logic.

# FIX(N5): 이온쌍 별칭 27개 + 이온쌍 감지 + 개별 resolve + SDF merge
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import merge_sdfs, sdf_to_xyz

if TYPE_CHECKING:
    from .structure_resolver import StructureResolver

logger = logging.getLogger(__name__)

# ── 이온쌍 약어 사전 (27개) ────────────────────────────────────
# format: abbreviation → {"name": full PubChem-searchable name, "type": "cation"|"anion", "default_charge": int}
ION_ALIASES: Dict[str, Dict[str, Any]] = {
    # Cations
    "EMIM":  {"name": "1-ethyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BMIM":  {"name": "1-butyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "HMIM":  {"name": "1-hexyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "OMIM":  {"name": "1-octyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BPy":   {"name": "1-butylpyridinium", "type": "cation", "default_charge": 1},
    "DEME":  {"name": "N,N-diethyl-N-methyl-N-(2-methoxyethyl)ammonium", "type": "cation", "default_charge": 1},
    "P14":   {"name": "N-butyl-N-methylpyrrolidinium", "type": "cation", "default_charge": 1},
    "TEA":   {"name": "tetraethylammonium", "type": "cation", "default_charge": 1},
    "TBA":   {"name": "tetrabutylammonium", "type": "cation", "default_charge": 1},
    "Li":    {"name": "lithium ion", "type": "cation", "default_charge": 1},
    "Na":    {"name": "sodium ion", "type": "cation", "default_charge": 1},
    "K":     {"name": "potassium ion", "type": "cation", "default_charge": 1},
    # Anions
    "TFSI":  {"name": "bis(trifluoromethanesulfonyl)azanide", "type": "anion", "default_charge": -1},
    "BF4":   {"name": "tetrafluoroborate", "type": "anion", "default_charge": -1},
    "PF6":   {"name": "hexafluorophosphate", "type": "anion", "default_charge": -1},
    "OTf":   {"name": "trifluoromethanesulfonate", "type": "anion", "default_charge": -1},
    "DCA":   {"name": "dicyanamide", "type": "anion", "default_charge": -1},
    "SCN":   {"name": "thiocyanate", "type": "anion", "default_charge": -1},
    "OAc":   {"name": "acetate", "type": "anion", "default_charge": -1},
    "Cl":    {"name": "chloride", "type": "anion", "default_charge": -1},
    "Br":    {"name": "bromide", "type": "anion", "default_charge": -1},
    "I":     {"name": "iodide", "type": "anion", "default_charge": -1},
    "NO3":   {"name": "nitrate", "type": "anion", "default_charge": -1},
    "HSO4":  {"name": "hydrogen sulfate", "type": "anion", "default_charge": -1},
    "FSI":   {"name": "bis(fluorosulfonyl)azanide", "type": "anion", "default_charge": -1},
    "BOB":   {"name": "bis(oxalato)borate", "type": "anion", "default_charge": -1},
    "FAP":   {"name": "tris(pentafluoroethyl)trifluorophosphate", "type": "anion", "default_charge": -1},
}


@dataclass
class IonPairResult:
    """Result of ion-pair resolution."""
    xyz: str = ""
    total_charge: int = 0
    smiles_list: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    source: str = "ion_pair_handler"
    individual_sdfs: List[str] = field(default_factory=list)


def expand_alias(name: str) -> Dict[str, Any]:
    """Expand an ion abbreviation to its full searchable name.

    Returns:
        Dict with 'name', 'type', 'default_charge' or the original name
        with charge 0 if not an alias.
    """
    clean = name.strip().rstrip("+-")
    if clean in ION_ALIASES:
        return dict(ION_ALIASES[clean])

    # Case-insensitive lookup
    upper = clean.upper()
    for key, val in ION_ALIASES.items():
        if key.upper() == upper:
            return dict(val)

    # Not a known alias — return as-is with neutral charge
    return {"name": name.strip(), "type": "unknown", "default_charge": 0}


def is_ion_pair(structures: List[Dict[str, Any]]) -> bool:
    """Check if the structures list represents an ion pair.

    An ion pair requires at least 2 structures, and at least one must
    have a non-zero charge or be a known ion alias.
    """
    if not structures or len(structures) < 2:
        return False

    has_charged = False
    for s in structures:
        name = s.get("name", "")
        charge = s.get("charge", 0)
        clean = name.strip().rstrip("+-")

        if charge and charge != 0:
            has_charged = True
        elif clean in ION_ALIASES or clean.upper() in {k.upper() for k in ION_ALIASES}:
            has_charged = True

    return has_charged


async def resolve_ion_pair(
    structures: List[Dict[str, Any]],
    molchat: MolChatClient,
    pubchem: PubChemClient,
    offset: float = 5.0,
    *,
    resolver: Optional["StructureResolver"] = None,
) -> IonPairResult:
    """Resolve an ion pair by resolving each ion individually then merging.

    Args:
        structures: List of dicts with 'name' and optional 'charge'.
        molchat: MolChat API client.
        pubchem: PubChem API client (fallback).
        offset: X-axis offset between fragments (Å).
        resolver: Optional shared StructureResolver instance.

    Returns:
        IonPairResult with merged XYZ and total charge.

    Raises:
        ValueError: If resolution fails for any ion.
    """
    if resolver is None:
        resolver = _new_resolver(molchat=molchat, pubchem=pubchem)

    result = IonPairResult()
    sdfs: List[str] = []

    for ion_spec in structures:
        raw_name = ion_spec.get("name", "").strip()
        explicit_charge = ion_spec.get("charge")

        # Expand alias
        info = expand_alias(raw_name)
        search_name = info["name"]
        ion_charge = explicit_charge if explicit_charge is not None else info["default_charge"]

        logger.info(
            "이온 resolve 중: %s → %s (charge=%d) / "
            "Resolving ion: %s → %s (charge=%d)",
            raw_name, search_name, ion_charge,
            raw_name, search_name, ion_charge,
        )

        # Resolve to SDF via structure_resolver's internal pipeline
        resolved = await resolver.resolve(search_name)

        if not resolved or not resolved.sdf:
            raise ValueError(
                f"이온 '{raw_name}' ({search_name}) 구조 해석 실패 / "
                f"Failed to resolve ion '{raw_name}' ({search_name})"
            )

        sdfs.append(resolved.sdf)
        result.total_charge += ion_charge
        result.names.append(search_name)
        if resolved.smiles:
            result.smiles_list.append(resolved.smiles)

    # Merge SDFs into single XYZ
    comment = f"Ion pair: {' + '.join(result.names)}"
    result.xyz = merge_sdfs(sdfs, offset=offset, comment=comment)
    result.individual_sdfs = sdfs
    result.source = "ion_pair_handler"

    logger.info(
        "이온쌍 해석 완료: %s (total_charge=%d) / "
        "Ion pair resolved: %s (total_charge=%d)",
        result.names, result.total_charge,
        result.names, result.total_charge,
    )

    return result


def _new_resolver(*, molchat: MolChatClient, pubchem: PubChemClient) -> "StructureResolver":
    # Avoid circular import at module import time.
    from .structure_resolver import StructureResolver

    return StructureResolver(molchat=molchat, pubchem=pubchem)
