"""
PropertyCalculator – unified interface for computing molecular properties.

Sources:
  1. RDKit descriptors (fast, ~1 ms per molecule)
  2. xTB-derived properties (slow, queued)
  3. PubChem imported properties (cached)

Handles merging, unit conversion, and property normalization.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler

logger = structlog.get_logger(__name__)

# Standard property keys we always try to populate
STANDARD_PROPERTIES = [
    "molecular_weight",
    "logp",
    "tpsa",
    "hbd",
    "hba",
    "rotatable_bonds",
    "heavy_atom_count",
    "ring_count",
    "aromatic_rings",
    "fraction_csp3",
    "qed",
    "formal_charge",
    "lipinski_violations",
]


class PropertyCalculator:
    """Compute and merge molecular properties from multiple sources."""

    def __init__(self, rdkit_handler: RDKitHandler | None = None) -> None:
        self._rdkit = rdkit_handler or RDKitHandler()

    async def rdkit_descriptors(self, smiles: str) -> dict[str, Any]:
        """Compute the full RDKit descriptor set."""
        return await self._rdkit.compute_descriptors(smiles)

    async def full_property_report(
        self,
        smiles: str,
        *,
        pubchem_props: dict[str, Any] | None = None,
        xtb_props: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge properties from all available sources into a unified report.

        Priority (higher overrides lower):
          1. xTB (most accurate for energetics)
          2. RDKit (standard descriptors)
          3. PubChem (imported)
        """
        rdkit_props = await self.rdkit_descriptors(smiles)

        merged: dict[str, Any] = {}

        # Layer: PubChem (lowest priority)
        if pubchem_props:
            merged.update(self._normalize_pubchem(pubchem_props))

        # Layer: RDKit
        if rdkit_props:
            merged.update(rdkit_props)

        # Layer: xTB (highest priority for energetics)
        if xtb_props:
            merged.update(self._normalize_xtb(xtb_props))

        # Drug-likeness assessment
        merged["drug_likeness"] = self._assess_drug_likeness(merged)

        # Source tracking
        merged["_sources"] = {
            "rdkit": bool(rdkit_props),
            "pubchem": bool(pubchem_props),
            "xtb": bool(xtb_props),
        }

        return merged

    def _normalize_pubchem(self, props: dict[str, Any]) -> dict[str, Any]:
        """Map PubChem property names to our standard keys."""
        mapping: dict[str, str] = {
            "xlogp": "logp",
            "tpsa": "tpsa",
            "hbond_donor": "hbd",
            "hbond_acceptor": "hba",
            "rotatable_bonds": "rotatable_bonds",
            "heavy_atom_count": "heavy_atom_count",
            "exact_mass": "exact_mass",
            "monoisotopic_mass": "monoisotopic_mass",
            "charge": "formal_charge",
            "complexity": "complexity",
        }
        result: dict[str, Any] = {}
        for src_key, dst_key in mapping.items():
            if src_key in props and props[src_key] is not None:
                result[dst_key] = props[src_key]
        return result

    def _normalize_xtb(self, props: dict[str, Any]) -> dict[str, Any]:
        """Map xTB result fields to our standard keys."""
        result: dict[str, Any] = {}
        key_map: dict[str, str] = {
            "total_energy": "total_energy_hartree",
            "homo_energy": "homo_energy_ev",
            "lumo_energy": "lumo_energy_ev",
            "homo_lumo_gap": "homo_lumo_gap_ev",
            "dipole_moment": "dipole_moment_debye",
            "gibbs_free_energy": "gibbs_free_energy_hartree",
            "enthalpy": "enthalpy_hartree",
            "zpve": "zpve_hartree",
        }
        for src_key, dst_key in key_map.items():
            if src_key in props and props[src_key] is not None:
                result[dst_key] = props[src_key]

        # Convert Hartree → kcal/mol for common properties
        hartree_to_kcal = 627.509474
        if result.get("total_energy_hartree") is not None:
            result["total_energy_kcal_mol"] = round(
                result["total_energy_hartree"] * hartree_to_kcal, 2
            )

        return result

    @staticmethod
    def _assess_drug_likeness(props: dict[str, Any]) -> dict[str, Any]:
        """Assess Lipinski, Veber, and Ghose drug-likeness rules."""
        mw = props.get("molecular_weight")
        logp = props.get("logp")
        hbd = props.get("hbd")
        hba = props.get("hba")
        tpsa = props.get("tpsa")
        rotatable = props.get("rotatable_bonds")

        assessment: dict[str, Any] = {}

        # Lipinski Rule of 5
        if all(v is not None for v in [mw, logp, hbd, hba]):
            violations = sum([
                (mw or 0) > 500,
                (logp or 0) > 5,
                (hbd or 0) > 5,
                (hba or 0) > 10,
            ])
            assessment["lipinski"] = {
                "passes": violations <= 1,
                "violations": violations,
            }

        # Veber Rules
        if tpsa is not None and rotatable is not None:
            assessment["veber"] = {
                "passes": (tpsa <= 140) and (rotatable <= 10),
                "tpsa_ok": tpsa <= 140,
                "rotatable_ok": rotatable <= 10,
            }

        # Ghose Filter
        if all(v is not None for v in [mw, logp]):
            assessment["ghose"] = {
                "passes": (
                    160 <= (mw or 0) <= 480
                    and -0.4 <= (logp or 0) <= 5.6
                ),
            }

        return assessment