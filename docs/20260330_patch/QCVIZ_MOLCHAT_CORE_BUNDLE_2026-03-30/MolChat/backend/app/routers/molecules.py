"""
Molecule API routes.

Endpoints:
  GET  /api/v1/molecules/search       – search across all sources
  GET  /api/v1/molecules/{id}         – detail by UUID
  GET  /api/v1/molecules/{id}/structure/{format}  – download structure file
  POST /api/v1/molecules/{id}/calculate           – submit xTB calculation
  GET  /api/v1/molecules/calculations/{task_id}   – poll calculation status
  POST /api/v1/molecules/compare      – compare multiple molecules
"""

from __future__ import annotations
import asyncio
import httpx

import uuid
from typing import Any

import structlog
from pydantic import BaseModel as _BaseModel
from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.schemas.common import ErrorResponse
from app.schemas.molecule import (
    MoleculeDetailResponse,
    MoleculeInterpretRequest,
    MoleculeInterpretResponse,
    MoleculeSearchRequest,
    MoleculeSearchResponse,
)
from app.services.molecule_engine.cache_manager import MoleculeCacheManager
from app.services.molecule_engine.layer0_search.aggregator import SearchAggregator
from app.services.molecule_engine.layer0_search.base import classify_query
from app.services.molecule_engine.layer0_search.local_db import LocalDBProvider
from app.services.molecule_engine.layer0_search.pubchem import PubChemProvider
from app.services.molecule_engine.layer1_structure.converter import FormatConverter
from app.services.molecule_engine.layer2_calculation.property_calc import PropertyCalculator
from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue
from app.services.molecule_engine.orchestrator import MoleculeOrchestrator

logger = structlog.get_logger(__name__)



class Generate3DRequest(_BaseModel):
    """Request body for SMILES to 3D structure generation."""
    smiles: str
    name: str | None = None
    format: str = "sdf"
    optimize_xtb: bool = False


class Generate3DResponse(_BaseModel):
    """Response with generated 3D structure."""
    smiles: str
    format: str
    structure_data: str
    generation_method: str
    atom_count: int
    properties: dict | None = None


router = APIRouter(prefix="/molecules")


# ── Dependency helpers ──

async def _get_orchestrator(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> MoleculeOrchestrator:
    cache = MoleculeCacheManager(redis)
    aggregator = SearchAggregator()
    aggregator.set_local_provider(LocalDBProvider(db))
    return MoleculeOrchestrator(db=db, cache=cache, search_aggregator=aggregator)




# ═══════════════════════════════════════════════
# Generate 3D from SMILES (no DB required)
# ═══════════════════════════════════════════════


@router.post(
    "/generate-3d",
    response_model=Generate3DResponse,
    summary="Generate 3D structure from SMILES",
    description="Convert SMILES to 3D structure using RDKit ETKDG, optionally optimized with xTB.",
)
async def generate_3d_from_smiles(
    body: Generate3DRequest,
) -> Generate3DResponse:
    """Generate 3D molecular structure from SMILES string.

    Full pipeline:
      1. CONFORGE (CDPKit) — best quality 3D conformer
      2. RDKit ETKDGv3 + MMFF94 — fallback if CONFORGE unavailable
      3. xTB GFN2 geometry optimization — optional, on top of 1 or 2
      4. Format conversion if not SDF
    """
    from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
    from app.services.molecule_engine.layer1_structure.conforge_handler import ConforgeHandler
    from app.services.molecule_engine.layer1_structure.converter import FormatConverter

    rdkit_h = RDKitHandler()

    # Validate SMILES
    is_valid = await rdkit_h.parse_smiles(body.smiles)
    if not is_valid:
        raise HTTPException(status_code=422, detail=f"Invalid SMILES: {body.smiles}")

    # Count atoms
    atom_count = await rdkit_h.count_atoms(body.smiles)
    if atom_count > 500:
        raise HTTPException(status_code=422, detail=f"Too many atoms ({atom_count}). Max 500.")

    generation_method = ""
    sdf_data: str | None = None

    # ── Stage 1: CONFORGE (CDPKit) — best quality ──
    try:
        conforge = ConforgeHandler()
        sdf_data = await conforge.smiles_to_sdf(body.smiles)
        if sdf_data and len(sdf_data) > 10:
            generation_method = "conforge"
            logger.info("generate3d_conforge_success", atoms=atom_count, sdf_len=len(sdf_data))
    except Exception as exc:
        logger.debug("generate3d_conforge_failed", error=str(exc))

    # ── Stage 2: RDKit ETKDGv3 + MMFF94 (fallback) ──
    if not sdf_data:
        sdf_data = await rdkit_h.smiles_to_sdf(body.smiles, optimize=True)
        if sdf_data:
            generation_method = "rdkit-etkdg"
            logger.info("generate3d_rdkit_fallback", atoms=atom_count, sdf_len=len(sdf_data))

    if not sdf_data:
        raise HTTPException(status_code=500, detail="3D generation failed for this SMILES")

    # ── Stage 3: xTB GFN2 optimization (optional or always for small molecules) ──
    run_xtb = body.optimize_xtb or atom_count <= 80  # auto-optimize small molecules
    if run_xtb and atom_count <= 150:
        try:
            from app.services.molecule_engine.layer2_calculation.xtb_runner import XTBRunner

            converter = FormatConverter(rdkit_h)
            xyz_data = await converter.convert(sdf_data, "sdf", "xyz")

            if xyz_data:
                import asyncio
                runner = XTBRunner()
                xtb_result = await asyncio.wait_for(
                    runner.run(xyz_data, tasks=["optimize"]),
                    timeout=30.0
                )

                if xtb_result.success and xtb_result.optimized_xyz:
                    opt_sdf = await converter.convert(xtb_result.optimized_xyz, "xyz", "sdf")
                    if opt_sdf and len(opt_sdf) > 10:
                        sdf_data = opt_sdf
                        generation_method = f"{generation_method}+xtb-gfn2"
                        logger.info("generate3d_xtb_success",
                                  energy=xtb_result.total_energy,
                                  elapsed=f"{xtb_result.elapsed_seconds:.1f}s")
        except Exception as exc:
            logger.warning("generate3d_xtb_failed_fallback", error=str(exc))

    # ── Stage 4: Format conversion if needed ──
    structure_data = sdf_data
    if body.format != "sdf":
        converter = FormatConverter(rdkit_h)
        converted = await converter.convert(sdf_data, "sdf", body.format)
        if converted:
            structure_data = converted
        else:
            raise HTTPException(status_code=422, detail=f"Cannot convert to {body.format}")

    # ── Compute properties ──
    properties = await rdkit_h.compute_descriptors(body.smiles)

    return Generate3DResponse(
        smiles=body.smiles,
        format=body.format,
        structure_data=structure_data,
        generation_method=generation_method,
        atom_count=atom_count,
        properties=properties if properties else None,
    )


@router.get(
    "/generate-3d/sdf",
    summary="Generate SDF from SMILES (plain text response)",
    responses={200: {"content": {"text/plain": {}}}},
)
async def generate_sdf_plain(
    smiles: str = Query(..., description="SMILES string"),
    optimize_xtb: bool = Query(default=False),
):
    """Quick endpoint: returns raw SDF text from SMILES."""
    from fastapi.responses import PlainTextResponse
    from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler

    rdkit_h = RDKitHandler()
    is_valid = await rdkit_h.parse_smiles(smiles)
    if not is_valid:
        raise HTTPException(status_code=422, detail="Invalid SMILES")

    sdf = await rdkit_h.smiles_to_sdf(smiles, optimize=True)
    if sdf is None:
        raise HTTPException(status_code=500, detail="3D generation failed")

    return PlainTextResponse(content=sdf, media_type="text/plain")



# ═══════════════════════════════════════════════


# ═══════════════════════════════════════════════
# Molecule Card — comprehensive single-molecule view
# ═══════════════════════════════════════════════

@router.get(
    "/card",
    summary="Get comprehensive molecule card",
    description=(
        "Returns a complete molecule card with properties, safety data, "
        "drug-likeness assessment, similar molecules, and AI-generated summary. "
        "Provide either 'q' (name/SMILES/InChIKey) or 'cid' (PubChem CID)."
    ),
)
async def get_molecule_card(
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=500,
        description="Search query: molecule name, SMILES, InChIKey, or formula",
    ),
    cid: int | None = Query(
        default=None,
        ge=1,
        description="PubChem CID",
    ),
    orchestrator: MoleculeOrchestrator = Depends(_get_orchestrator),
):
    """Comprehensive molecule card — one query, all information."""
    if not q and not cid:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Either 'q' or 'cid' parameter is required",
        )
    return await orchestrator.get_card(q=q, cid=cid)


# Search
# ═══════════════════════════════════════════════


@router.get(
    "/search",
    response_model=MoleculeSearchResponse,
    summary="Search molecules",
    description="Search across PubChem, ChEMBL, ChemSpider, ZINC, and local DB.",
    responses={404: {"model": ErrorResponse}},
)
async def search_molecules(
    q: str = Query(
        ..., min_length=1, max_length=500, description="Search query"
    ),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sources: str | None = Query(
        default=None,
        description="Comma-separated source filter: pubchem,chembl,chemspider,zinc,local",
    ),
    orchestrator: MoleculeOrchestrator = Depends(_get_orchestrator),
) -> MoleculeSearchResponse:
    source_list = (
        [s.strip() for s in sources.split(",") if s.strip()]
        if sources
        else None
    )
    return await orchestrator.search(
        q, limit=limit, offset=offset, sources=source_list
    )


@router.post(
    "/interpret",
    response_model=MoleculeInterpretResponse,
    summary="Interpret semantic molecule descriptions",
    description="Convert a free-form molecule description into grounded candidate molecules.",
)
async def interpret_molecule_query(
    body: MoleculeInterpretRequest,
    orchestrator: MoleculeOrchestrator = Depends(_get_orchestrator),
) -> MoleculeInterpretResponse:
    return await orchestrator.interpret_candidates(body.query, limit=body.limit)


# ═══════════════════════════════════════════════
# Detail
# ═══════════════════════════════════════════════



# --- PubChem Name→CID Resolution (Enterprise Patch v2) ---

_pubchem_cache: dict[str, int | None] = {}

@router.get("/resolve")
async def resolve_molecule_names(
    names: str = Query(..., description="Comma-separated molecule names")
):
    """
    Resolve molecule names to PubChem CIDs via PUG-REST.
    Returns verified CID for each name. Caches results.
    """
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for name in name_list[:12]:  # max 12 molecules per request
            # Check cache
            cache_key = name.lower()
            if cache_key in _pubchem_cache:
                cid = _pubchem_cache[cache_key]
                if cid:
                    results.append({"name": name, "cid": cid})
                continue

            try:
                # PubChem name → CID
                url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    cid_list = data.get("IdentifierList", {}).get("CID", [])
                    if cid_list:
                        cid = cid_list[0]  # Take first (most relevant) CID
                        _pubchem_cache[cache_key] = cid
                        results.append({"name": name, "cid": cid})
                    else:
                        _pubchem_cache[cache_key] = None
                elif resp.status_code == 404:
                    _pubchem_cache[cache_key] = None
                else:
                    pass  # Skip on error, don't cache
            except Exception:
                pass  # Skip on network error

            await asyncio.sleep(0.25)  # Respect PubChem rate limit (max 5/s)

    return {"resolved": results, "total": len(results)}
# --- End PubChem Resolution ---

@router.get(
    "/{molecule_id}",
    response_model=MoleculeDetailResponse,
    summary="Get molecule detail",
    responses={404: {"model": ErrorResponse}},
)
async def get_molecule_detail(
    molecule_id: uuid.UUID,
    include_calculation: bool = Query(default=False),
    orchestrator: MoleculeOrchestrator = Depends(_get_orchestrator),
) -> MoleculeDetailResponse:
    return await orchestrator.get_detail(
        molecule_id, include_calculation=include_calculation
    )


# ═══════════════════════════════════════════════
# Structure download
# ═══════════════════════════════════════════════


@router.get(
    "/{molecule_id}/structure/{fmt}",
    summary="Download structure in specified format",
    responses={
        200: {"content": {"text/plain": {}}},
        404: {"model": ErrorResponse},
    },
)
async def get_structure(
    molecule_id: uuid.UUID,
    fmt: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Any:
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import select
    from app.models.molecule import Molecule, MoleculeStructure

    cache = MoleculeCacheManager(redis)

    # Cache check
    cached = await cache.get_structure(molecule_id, fmt)
    if cached:
        return PlainTextResponse(content=cached, media_type="text/plain")

    # DB lookup
    stmt = (
        select(MoleculeStructure)
        .where(
            MoleculeStructure.molecule_id == molecule_id,
            MoleculeStructure.format == fmt,
        )
        .order_by(MoleculeStructure.is_primary.desc())
    )
    result = await db.execute(stmt)
    structure = result.scalars().first()

    if structure is None:
        # Try to generate via converter
        mol_stmt = select(Molecule).where(Molecule.id == molecule_id)
        mol_result = await db.execute(mol_stmt)
        mol = mol_result.scalar_one_or_none()

        if mol is None:
            from app.middleware.error_handler import MoleculeNotFoundError
            raise MoleculeNotFoundError(str(molecule_id))

        # If SMILES is missing, try to get it from RDKit via InChI
        smiles = mol.canonical_smiles
        if not smiles and mol.inchi:
            try:
                from rdkit import Chem
                m = Chem.MolFromInchi(mol.inchi)
                if m:
                    smiles = Chem.MolToSmiles(m)
                    # Save back to DB
                    mol.canonical_smiles = smiles
                    await db.flush()
            except Exception:
                pass

        if not smiles:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"No SMILES available for molecule {molecule_id}")

        converter = FormatConverter()
        converted = await converter.convert(
            smiles, "smiles", fmt
        )
        if converted is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Cannot generate {fmt} format for this molecule",
            )

        await cache.set_structure(molecule_id, fmt, converted)
        return PlainTextResponse(content=converted, media_type="text/plain")

    await cache.set_structure(molecule_id, fmt, structure.structure_data)
    return PlainTextResponse(
        content=structure.structure_data, media_type="text/plain"
    )


# ═══════════════════════════════════════════════
# Calculation
# ═══════════════════════════════════════════════




@router.get(
    "/{molecule_id}/structures",
    summary="List available structure versions",
)
async def list_structures(
    molecule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return all available structure versions for a molecule."""
    from sqlalchemy import select as sa_select
    from app.models.molecule import MoleculeStructure

    stmt = sa_select(MoleculeStructure).where(
        MoleculeStructure.molecule_id == molecule_id,
    )
    result = await db.execute(stmt)
    structures = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "format": s.format,
            "generation_method": s.generation_method,
            "is_primary": s.is_primary,
            "data_length": len(s.structure_data) if s.structure_data else 0,
        }
        for s in structures
    ]

@router.post(
    "/{molecule_id}/calculate",
    summary="Submit xTB calculation",
    responses={422: {"model": ErrorResponse}},
)
async def submit_calculation(
    molecule_id: uuid.UUID,
    method: str = Query(default="gfn2"),
    tasks: str = Query(default="energy", description="Comma-separated: energy,optimize,frequencies"),
    orchestrator: MoleculeOrchestrator = Depends(_get_orchestrator),
) -> dict[str, Any]:
    task_list = [t.strip() for t in tasks.split(",") if t.strip()]
    return await orchestrator.calculate(
        molecule_id, method=method, tasks=task_list
    )


@router.get(
    "/calculations/{task_id}",
    summary="Poll calculation status",
)
async def get_calculation_status(
    task_id: str,
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    queue = CalculationQueue(redis)
    return await queue.get_status(task_id)


# ═══════════════════════════════════════════════
# Compare
# ═══════════════════════════════════════════════


@router.post(
    "/compare",
    summary="Compare multiple molecules",
)
async def compare_molecules(
    smiles_list: list[str],
    names: list[str] | None = None,
) -> dict[str, Any]:
    from app.services.intelligence.tools.molecule_tools import compare_molecules as _compare
    return await _compare(smiles_list=smiles_list, names=names)
