"""
Molecule tools – search, detail, comparison, property computation.

Each tool function:
  • Accepts typed keyword arguments.
  • Returns a dict or string (serialized to JSON for the LLM).
  • Handles its own errors and returns error dicts (never raises).
"""

from __future__ import annotations

from typing import Any

import structlog

from app.services.intelligence.tools import ToolRegistry

logger = structlog.get_logger(__name__)


def register_molecule_tools(registry: ToolRegistry) -> None:
    """Register all molecule-related tools."""

    # ── 1. search_molecule ──
    registry.register(
        name="search_molecule",
        fn=search_molecule,
        definition={
            "name": "search_molecule",
            "description": (
                "분자 데이터베이스(PubChem, ChEMBL, ZINC 등)에서 분자를 검색합니다. "
                "이름, SMILES, InChIKey, CID, 분자식으로 검색할 수 있습니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색어 (분자 이름, SMILES, InChIKey, CID, 분자식)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 결과 수 (기본값: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    )

    # ── 2. get_molecule_detail ──
    registry.register(
        name="get_molecule_detail",
        fn=get_molecule_detail,
        definition={
            "name": "get_molecule_detail",
            "description": (
                "특정 분자의 상세 정보를 조회합니다. "
                "구조, 3D 좌표, 물리화학적 속성, 약물유사성 등을 포함합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "molecule_id": {
                        "type": "string",
                        "description": "분자 UUID (검색 결과에서 얻은 ID)",
                    },
                    "include_calculation": {
                        "type": "boolean",
                        "description": "xTB 양자 계산 포함 여부 (기본값: false)",
                        "default": False,
                    },
                },
                "required": ["molecule_id"],
            },
        },
    )

    # ── 3. compute_properties ──
    registry.register(
        name="compute_properties",
        fn=compute_properties,
        definition={
            "name": "compute_properties",
            "description": (
                "SMILES 문자열로부터 분자의 물리화학적 속성을 계산합니다. "
                "분자량, LogP, TPSA, 수소결합, 회전결합, QED, Lipinski 규칙 등을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "smiles": {
                        "type": "string",
                        "description": "분자의 SMILES 문자열",
                    },
                },
                "required": ["smiles"],
            },
        },
    )

    # ── 4. compare_molecules ──
    registry.register(
        name="compare_molecules",
        fn=compare_molecules,
        definition={
            "name": "compare_molecules",
            "description": (
                "두 개 이상의 분자를 비교합니다. "
                "각 분자의 속성을 나란히 비교하여 구조적·물리화학적 차이를 보여줍니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "smiles_list": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "비교할 분자들의 SMILES 목록 (2~5개)",
                    },
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "분자 이름 목록 (선택, smiles_list와 같은 순서)",
                    },
                },
                "required": ["smiles_list"],
            },
        },
    )


# ═══════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════


async def search_molecule(
    query: str,
    limit: int = 5,
    **kwargs: Any,
) -> dict[str, Any]:
    """Search for molecules across all databases."""
    try:
        from app.services.molecule_engine.layer0_search.pubchem import PubChemProvider
        from app.services.molecule_engine.layer0_search.base import classify_query

        search_type = classify_query(query)
        provider = PubChemProvider()
        results = await provider.search(query, search_type, limit=limit)

        if not results:
            return {
                "found": False,
                "query": query,
                "message": f"'{query}'에 대한 검색 결과가 없습니다.",
            }

        return {
            "found": True,
            "query": query,
            "total": len(results),
            "results": [
                {
                    "name": r.name,
                    "canonical_smiles": r.canonical_smiles,
                    "inchikey": r.inchikey,
                    "cid": r.cid,
                    "molecular_formula": r.molecular_formula,
                    "molecular_weight": r.molecular_weight,
                    "source": r.source,
                    "source_url": r.source_url,
                    "properties": r.properties,
                }
                for r in results
            ],
        }

    except Exception as exc:
        logger.error("tool_search_molecule_error", error=str(exc))
        return {"error": f"검색 중 오류 발생: {exc}", "query": query}


async def get_molecule_detail(
    molecule_id: str,
    include_calculation: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Get detailed information about a specific molecule."""
    try:
        # For now, search by the molecule_id as a CID or name
        from app.services.molecule_engine.layer0_search.pubchem import PubChemProvider
        from app.services.molecule_engine.layer0_search.base import SearchType

        provider = PubChemProvider()

        # Try as CID first
        if molecule_id.isdigit():
            result = await provider.get_by_identifier(
                molecule_id, SearchType.CID
            )
        else:
            result = await provider.get_by_identifier(
                molecule_id, SearchType.NAME
            )

        if result is None:
            return {
                "found": False,
                "molecule_id": molecule_id,
                "message": "분자를 찾을 수 없습니다.",
            }

        # Compute RDKit properties if SMILES available
        properties = {}
        if result.canonical_smiles:
            from app.services.molecule_engine.layer2_calculation.property_calc import (
                PropertyCalculator,
            )

            calc = PropertyCalculator()
            properties = await calc.rdkit_descriptors(result.canonical_smiles)

        return {
            "found": True,
            "name": result.name,
            "canonical_smiles": result.canonical_smiles,
            "inchi": result.inchi,
            "inchikey": result.inchikey,
            "cid": result.cid,
            "molecular_formula": result.molecular_formula,
            "molecular_weight": result.molecular_weight,
            "source": result.source,
            "source_url": result.source_url,
            "properties": {**result.properties, **properties},
            "has_3d_structure": result.structure_3d is not None,
        }

    except Exception as exc:
        logger.error("tool_get_detail_error", error=str(exc))
        return {"error": f"상세 조회 중 오류 발생: {exc}"}


async def compute_properties(
    smiles: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compute molecular properties from SMILES."""
    try:
        from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
        from app.services.molecule_engine.layer2_calculation.property_calc import PropertyCalculator

        rdkit = RDKitHandler()

        # Validate SMILES
        is_valid = await rdkit.parse_smiles(smiles)
        if not is_valid:
            return {
                "error": f"유효하지 않은 SMILES: {smiles}",
                "smiles": smiles,
            }

        # Canonicalize
        canonical = await rdkit.canonical_smiles(smiles)

        # Compute properties
        calc = PropertyCalculator(rdkit_handler=rdkit)
        properties = await calc.rdkit_descriptors(canonical or smiles)

        # Drug-likeness
        drug_likeness = calc._assess_drug_likeness(properties)

        return {
            "smiles": canonical or smiles,
            "properties": properties,
            "drug_likeness": drug_likeness,
        }

    except Exception as exc:
        logger.error("tool_compute_props_error", error=str(exc))
        return {"error": f"속성 계산 중 오류 발생: {exc}", "smiles": smiles}


async def compare_molecules(
    smiles_list: list[str],
    names: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compare multiple molecules side by side."""
    try:
        from app.services.molecule_engine.layer2_calculation.property_calc import PropertyCalculator

        if len(smiles_list) < 2:
            return {"error": "비교하려면 최소 2개의 분자가 필요합니다."}
        if len(smiles_list) > 5:
            return {"error": "최대 5개까지 비교할 수 있습니다."}

        names = names or [f"Molecule {i+1}" for i in range(len(smiles_list))]
        calc = PropertyCalculator()
        comparisons = []

        for i, smiles in enumerate(smiles_list):
            props = await calc.rdkit_descriptors(smiles)
            drug_likeness = calc._assess_drug_likeness(props)
            comparisons.append({
                "name": names[i] if i < len(names) else f"Molecule {i+1}",
                "smiles": smiles,
                "properties": props,
                "drug_likeness": drug_likeness,
            })

        # Summary differences
        all_keys = set()
        for comp in comparisons:
            all_keys.update(comp["properties"].keys())

        return {
            "count": len(comparisons),
            "molecules": comparisons,
            "property_keys": sorted(all_keys),
        }

    except Exception as exc:
        logger.error("tool_compare_error", error=str(exc))
        return {"error": f"비교 중 오류 발생: {exc}"}