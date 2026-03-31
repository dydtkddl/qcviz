"""
MoleculeOrchestrator – single facade that coordinates all three layers.

Responsibilities:
  1. Accept a free-form query (name / SMILES / InChIKey / CID / formula).
  2. Check cache → L0 search → persist to DB → L1 structure → optional L2 calc.
  3. Return a fully-hydrated ``MoleculeRecord``.

Design decisions:
  • Every public method is async and re-entrant (no mutable instance state).
  • Errors bubble up as domain exceptions (``MolChatError`` subclasses).
  • Structured logging on every significant step for observability.
  • Timeouts are enforced per-layer so a slow upstream never blocks the pipeline.
"""

from __future__ import annotations
import httpx

import asyncio
import time
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.middleware.error_handler import (
    CalculationError,
    ExternalServiceError,
    MoleculeNotFoundError,
)
from app.models.molecule import Molecule, MoleculeProperty, MoleculeStructure
from app.schemas.molecule import (
    MoleculeDetailResponse,
    MoleculeInterpretCandidate,
    MoleculeInterpretResponse,
    MoleculeRecord,
    MoleculeSearchResponse,
)
from app.services.molecule_engine.cache_manager import MoleculeCacheManager
from app.services.molecule_engine.query_resolver import QueryResolver
from app.services.molecule_engine.pug_rest_resolver import resolve_name_to_cid, PugRestResult
from app.services.molecule_engine.layer0_search.aggregator import SearchAggregator
from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
from app.services.molecule_engine.layer1_structure.conforge_handler import ConforgeHandler
from app.services.molecule_engine.layer1_structure.converter import FormatConverter
from app.services.molecule_engine.layer1_structure.validator import StructureValidator
from app.services.molecule_engine.layer2_calculation.property_calc import PropertyCalculator
from app.services.molecule_engine.layer2_calculation.xtb_runner import XTBRunner
from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue

logger = structlog.get_logger(__name__)


class MoleculeOrchestrator:
    """Top-level facade for the Molecule Engine.

    Instantiated once at app startup and shared across requests
    via FastAPI's dependency injection.
    """

    def __init__(
        self,
        db: AsyncSession,
        cache: MoleculeCacheManager,
        search_aggregator: SearchAggregator | None = None,
        rdkit_handler: RDKitHandler | None = None,
        converter: FormatConverter | None = None,
        validator: StructureValidator | None = None,
        property_calc: PropertyCalculator | None = None,
        xtb_runner: XTBRunner | None = None,
        calc_queue: CalculationQueue | None = None,
    ) -> None:
        self._db = db
        self._cache = cache
        self._resolver = QueryResolver()
        self._search = search_aggregator or SearchAggregator()
        self._conforge = ConforgeHandler()
        self._rdkit = rdkit_handler or RDKitHandler()
        self._converter = converter or FormatConverter()
        self._validator = validator or StructureValidator()
        self._property_calc = property_calc or PropertyCalculator()
        self._xtb = xtb_runner or XTBRunner()
        self._calc_queue = calc_queue or CalculationQueue()

    # ═══════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        sources: list[str] | None = None,
    ) -> MoleculeSearchResponse:
        """Full search pipeline: cache → L0 → persist → L1 enrich."""
        t0 = time.perf_counter()
        # ── 0. Query Resolution (Korean, typos, aliases) ──
        resolved = await self._resolver.resolve(query)
        if resolved.method != "passthrough":
            log = logger.bind(
                original_query=query,
                resolved_query=resolved.resolved_query,
                resolve_method=resolved.method,
                limit=limit,
                sources=sources,
            )
            log.info("query_resolved", suggestions=resolved.suggestions[:3])
            query = resolved.resolved_query  # Use resolved query for search
        else:
            log = logger.bind(query=query, limit=limit, sources=sources)

        log.info("search_started")

        # ── 1. Cache lookup ──
        cached = await self._cache.get_search(query, limit, offset)
        if cached is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            log.info("search_cache_hit", elapsed_ms=elapsed)
            cached.cache_hit = True
            cached.elapsed_ms = elapsed
            # Restore resolve info for this specific request
            if resolved.method != "passthrough":
                cached.original_query = resolved.original
                cached.resolved_query = resolved.resolved_query
                cached.resolve_method = resolved.method
                cached.resolve_suggestions = resolved.suggestions
            else:
                cached.original_query = None
                cached.resolved_query = None
                cached.resolve_method = None
                cached.resolve_suggestions = []
            return cached

        # ── 2. L0 – Multi-source search ──
        try:
            raw_results = await asyncio.wait_for(
                self._search.search(query, limit=limit, sources=sources),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            raise ExternalServiceError("search_aggregator", "Search timed out after 30 s")

        if not raw_results.results:
            raise MoleculeNotFoundError(query)

        # ── 3. Persist to DB & enrich with L1 ──
        records: list[MoleculeRecord] = []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for raw in raw_results.results:
            # Persist to DB and get the actual DB ID
            db_id = None
            try:
                persisted = await self._persist_molecule(raw)
                db_id = persisted.id
            except Exception as persist_err:
                logger.warning("persist_skip", error=str(persist_err))

            # Build response record with DB ID (enables detail page navigation)
            props = raw.get("properties") or {}
            mw = props.get("molecular_weight") or raw.get("molecular_weight")
            if mw is not None:
                try:
                    mw = float(mw)
                except (ValueError, TypeError):
                    mw = None
            records.append(MoleculeRecord(
                id=db_id or uuid.uuid4(),
                cid=raw.get("cid"),
                name=raw.get("name") or "",
                canonical_smiles=raw.get("canonical_smiles") or "",
                inchi=raw.get("inchi"),
                inchikey=raw.get("inchikey"),
                molecular_formula=raw.get("molecular_formula"),
                molecular_weight=mw,
                properties=props,
                structures=[],
                computed_properties=[],
                created_at=now,
                updated_at=now,
            ))

        # ── 4. Build response ──
        response = MoleculeSearchResponse(
            query=resolved.resolved_query if resolved.method != "passthrough" else query,
            original_query=resolved.original if resolved.method != "passthrough" else None,
            resolved_query=resolved.resolved_query if resolved.method != "passthrough" else None,
            resolve_method=resolved.method if resolved.method != "passthrough" else None,
            resolve_suggestions=resolved.suggestions if resolved.method != "passthrough" else [],
            total=raw_results.total,
            limit=limit,
            offset=offset,
            results=records,
            sources_queried=raw_results.sources_queried,
            cache_hit=False,
            elapsed_ms=0,
        )

        # ── 5. Cache write ──
        await self._cache.set_search(query, limit, offset, response)

        elapsed = (time.perf_counter() - t0) * 1000
        response.elapsed_ms = elapsed
        log.info("search_completed", total=len(records), elapsed_ms=elapsed)
        return response

    async def interpret_candidates(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> MoleculeInterpretResponse:
        """Interpret semantic molecule descriptions into grounded PubChem candidates."""
        mode, normalized_query, resolution_method, notes, candidates = await self._resolver.interpret_candidates(
            query,
            limit=limit,
        )

        grounded: list[MoleculeInterpretCandidate] = []
        seen: set[str] = set()

        resolution_results = await asyncio.gather(
            *[resolve_name_to_cid(candidate.name) for candidate in candidates],
            return_exceptions=True,
        )

        for candidate, resolved in zip(candidates, resolution_results, strict=False):
            if isinstance(resolved, Exception) or not isinstance(resolved, PugRestResult) or not resolved.found:
                continue
            key = str(candidate.name).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            grounded.append(
                MoleculeInterpretCandidate(
                    name=resolved.name or candidate.name,
                    cid=resolved.cid,
                    canonical_smiles=resolved.canonical_smiles,
                    molecular_formula=resolved.molecular_formula,
                    molecular_weight=resolved.molecular_weight,
                    confidence=max(0.0, min(float(candidate.confidence), 1.0)),
                    source=candidate.source,
                    rationale=candidate.rationale or f"verified in PubChem via {candidate.source}",
                )
            )

        return MoleculeInterpretResponse(
            query=query,
            query_mode=mode,
            normalized_query=normalized_query,
            resolution_method=resolution_method,
            notes=notes,
            candidates=grounded[: max(1, int(limit or 5))],
        )

    async def get_detail(
        self,
        molecule_id: uuid.UUID,
        *,
        include_calculation: bool = False,
    ) -> MoleculeDetailResponse:
        """Return full detail for a molecule by ID, optionally triggering L2 calc."""
        log = logger.bind(molecule_id=str(molecule_id))
        log.info("detail_requested")

        # ── Cache ──
        cached = await self._cache.get_detail(molecule_id)
        if cached is not None:
            log.info("detail_cache_hit")
            return cached

        # ── DB lookup with eager loading (prevents greenlet issues) ──
        stmt = (
            select(Molecule)
            .where(
                Molecule.id == molecule_id,
                Molecule.is_deleted.is_(False),
            )
            .options(
                selectinload(Molecule.structures),
                selectinload(Molecule.computed_properties),
            )
        )
        result = await self._db.execute(stmt)
        molecule = result.scalar_one_or_none()

        if molecule is None:
            raise MoleculeNotFoundError(str(molecule_id))

        # ── L1 enrichment (auto-generate 3D structure if missing) ──
        record = await self._enrich_l1(molecule)

        # ── L2 calculation (async / queue) ──
        calc_status: str | None = None
        if include_calculation:
            calc_status = await self._trigger_l2(molecule)

        # ── Available formats (re-query DB after enrichment) ──
        from sqlalchemy import select as sa_select
        fmt_stmt = sa_select(MoleculeStructure.format).where(
            MoleculeStructure.molecule_id == molecule_id
        )
        fmt_result = await self._db.execute(fmt_stmt)
        formats = [row[0] for row in fmt_result.fetchall()]

        detail = MoleculeDetailResponse(
            molecule=record,
            available_formats=sorted(set(formats)),
            calculation_status=calc_status,
        )

        await self._cache.set_detail(molecule_id, detail)
        log.info("detail_completed")
        return detail

    async def calculate(
        self,
        molecule_id: uuid.UUID,
        *,
        method: str = "gfn2",
        tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit an L2 quantum calculation and return the task handle."""
        log = logger.bind(molecule_id=str(molecule_id), method=method)
        log.info("calculation_requested")

        stmt = select(Molecule).where(
            Molecule.id == molecule_id,
            Molecule.is_deleted.is_(False),
        )
        result = await self._db.execute(stmt)
        molecule = result.scalar_one_or_none()

        if molecule is None:
            raise MoleculeNotFoundError(str(molecule_id))

        # Validate atom count
        atom_count = await self._rdkit.count_atoms(molecule.canonical_smiles)
        if atom_count > settings.XTB_MAX_ATOMS:
            raise CalculationError(
                f"Molecule has {atom_count} atoms (max {settings.XTB_MAX_ATOMS})"
            )

        tasks = tasks or ["optimize", "energy", "frequencies"]
        task_id = await self._calc_queue.submit(
            molecule_id=molecule_id,
            smiles=molecule.canonical_smiles,
            method=method,
            tasks=tasks,
        )

        log.info("calculation_submitted", task_id=task_id)
        return {
            "task_id": task_id,
            "molecule_id": str(molecule_id),
            "method": method,
            "tasks": tasks,
            "status": "pending",
        }

    async def get_calculation_status(self, task_id: str) -> dict[str, Any]:
        """Poll the status of a queued L2 calculation."""
        return await self._calc_queue.get_status(task_id)

    # ═══════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════

    async def _persist_molecule(self, raw: dict[str, Any]) -> Molecule:
        """Insert or update a molecule row from raw search data.

        Uses InChIKey as the natural dedup key, falling back to CID.
        """
        inchikey = raw.get("inchikey")
        cid = raw.get("cid")

        existing: Molecule | None = None

        if inchikey:
            stmt = select(Molecule).where(Molecule.inchikey == inchikey)
            result = await self._db.execute(stmt)
            existing = result.scalar_one_or_none()

        if existing is None and cid:
            stmt = select(Molecule).where(Molecule.cid == cid)
            result = await self._db.execute(stmt)
            existing = result.scalar_one_or_none()

        if existing is not None:
            # Merge any new properties
            if raw.get("properties"):
                merged = {**(existing.properties or {}), **raw["properties"]}
                existing.properties = merged
            # Save PubChem 3D SDF if not already stored
            structure_3d = raw.get("structure_3d")
            if structure_3d and isinstance(structure_3d, str) and len(structure_3d) > 10:
                from app.models.molecule import MoleculeStructure
                check_stmt = select(MoleculeStructure).where(
                    MoleculeStructure.molecule_id == existing.id,
                    MoleculeStructure.generation_method == "pubchem-3d",
                )
                check_result = await self._db.execute(check_stmt)
                if check_result.scalar_one_or_none() is None:
                    # Demote any existing primary SDF before inserting new primary
                    from sqlalchemy import update as sa_update
                    demote_stmt = (
                        sa_update(MoleculeStructure)
                        .where(
                            MoleculeStructure.molecule_id == existing.id,
                            MoleculeStructure.format == "sdf",
                            MoleculeStructure.is_primary == True,
                        )
                        .values(is_primary=False)
                    )
                    await self._db.execute(demote_stmt)
                    pubchem_struct = MoleculeStructure(
                        molecule_id=existing.id,
                        format="sdf",
                        structure_data=structure_3d,
                        generation_method="pubchem-3d",
                        is_primary=True,
                    )
                    self._db.add(pubchem_struct)
                    logger.info("pubchem_3d_saved_existing", molecule_id=str(existing.id))
            await self._db.flush()
            await self._db.refresh(existing)
            return existing

        # Ensure numeric types
        mw = raw.get("molecular_weight")
        try:
            mw = float(mw) if mw is not None else None
        except (ValueError, TypeError):
            mw = None

        raw_cid = raw.get("cid")
        try:
            raw_cid = int(raw_cid) if raw_cid is not None else None
        except (ValueError, TypeError):
            raw_cid = None

        molecule = Molecule(
            id=uuid.uuid4(),
            cid=raw_cid,
            name=raw.get("name", "Unknown"),
            canonical_smiles=raw.get("canonical_smiles", ""),
            inchi=raw.get("inchi"),
            inchikey=inchikey,
            molecular_formula=raw.get("molecular_formula"),
            molecular_weight=mw,
            properties=raw.get("properties", {}),
        )
        mol_name = raw.get("name", "Unknown")


        mol_id = molecule.id
        self._db.add(molecule)
        await self._db.flush()

        # Save PubChem 3D SDF if available in search result
        structure_3d = raw.get("structure_3d")
        if structure_3d and isinstance(structure_3d, str) and len(structure_3d) > 10:
            from app.models.molecule import MoleculeStructure
            pubchem_struct = MoleculeStructure(
                molecule_id=molecule.id,
                format="sdf",
                structure_data=structure_3d,
                generation_method="pubchem-3d",
                is_primary=True,
            )
            self._db.add(pubchem_struct)
            await self._db.flush()
            logger.info("pubchem_3d_saved", molecule_id=str(mol_id))

        logger.info(
            "molecule_persisted",
            molecule_id=str(mol_id),
            name=mol_name,
        )
        return molecule

    async def _enrich_l1(self, molecule: Molecule) -> MoleculeRecord:
        """4-stage structure generation pipeline:
        
        Stage 1: PubChem 3D (already saved during search, skip if exists)
        Stage 2: CONFORGE (CDPKit) — best open-source conformer quality
        Stage 3: RDKit ETKDGv3 + MMFF94 — fast fallback
        Stage 4: xTB GFN2-xTB optimization (optional, on existing structure)
        """
        try:
            has_any_sdf = any(
                s.format == "sdf" for s in (molecule.structures or [])
            )

            # ── Stage 1: PubChem 3D (already present from search) ──
            has_pubchem = any(
                s.generation_method == "pubchem-3d" for s in (molecule.structures or [])
            )

            # ── Stage 2: CONFORGE (CDPKit) ──
            has_conforge = any(
                s.generation_method == "conforge" for s in (molecule.structures or [])
            )
            if not has_conforge and molecule.canonical_smiles:
                sdf_data = await self._conforge.smiles_to_sdf(molecule.canonical_smiles)
                if sdf_data and len(sdf_data) > 10:
                    structure = MoleculeStructure(
                        molecule_id=molecule.id,
                        format="sdf",
                        structure_data=sdf_data,
                        generation_method="conforge",
                        is_primary=False,  # Never auto-promote; PubChem 3D or first-inserted is primary
                    )
                    self._db.add(structure)
                    has_conforge = True
                    has_any_sdf = True
                    logger.info("conforge_structure_saved", molecule_id=str(molecule.id))

            # ── Stage 3: RDKit ETKDGv3 + MMFF94 (fallback) ──
            has_rdkit = any(
                s.generation_method == "rdkit" for s in (molecule.structures or [])
            )
            if not has_rdkit and not has_conforge and molecule.canonical_smiles:
                sdf_data = await self._rdkit.smiles_to_sdf(molecule.canonical_smiles)
                if sdf_data:
                    structure = MoleculeStructure(
                        molecule_id=molecule.id,
                        format="sdf",
                        structure_data=sdf_data,
                        generation_method="rdkit",
                        is_primary=False,
                    )
                    self._db.add(structure)
                    has_any_sdf = True
                    logger.info("rdkit_structure_saved", molecule_id=str(molecule.id))

            # ── Stage 4: xTB GFN2-xTB optimization (best available SDF → XYZ → optimize) ──
            has_xtb = any(
                s.generation_method == "xtb-gfn2" for s in (molecule.structures or [])
            )
            if not has_xtb and has_any_sdf and molecule.canonical_smiles:
                await self._run_xtb_optimization(molecule)

            # ── RDKit descriptors ──
            has_rdkit_props = any(
                p.source == "rdkit" for p in (molecule.computed_properties or [])
            )
            if not has_rdkit_props and molecule.canonical_smiles:
                descriptors = await self._property_calc.rdkit_descriptors(
                    molecule.canonical_smiles
                )
                if descriptors:
                    prop = MoleculeProperty(
                        molecule_id=molecule.id,
                        source="rdkit",
                        data=descriptors,
                    )
                    self._db.add(prop)

            await self._db.flush()

            # Ensure exactly one primary SDF exists
            await self._db.refresh(molecule, attribute_names=["structures"])
            sdf_structs = [s for s in (molecule.structures or []) if s.format == "sdf"]
            has_primary = any(s.is_primary for s in sdf_structs)
            if not has_primary and sdf_structs:
                # Priority: pubchem-3d > conforge > rdkit > xtb-gfn2
                priority_order = ["pubchem-3d", "conforge", "rdkit", "xtb-gfn2"]
                best = None
                for method in priority_order:
                    for s in sdf_structs:
                        if s.generation_method == method:
                            best = s
                            break
                    if best:
                        break
                if best is None:
                    best = sdf_structs[0]
                best.is_primary = True
                await self._db.flush()
                logger.info("primary_promoted", molecule_id=str(molecule.id), method=best.generation_method)

        except Exception as exc:
            try:
                await self._db.rollback()
            except Exception:
                pass
            logger.warning(
                "l1_enrichment_partial_failure",
                molecule_id=str(molecule.id),
                error=str(exc),
            )

        # Build record
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        try:
            created = molecule.created_at
        except Exception:
            created = now
        try:
            updated = molecule.updated_at
        except Exception:
            updated = now
        return MoleculeRecord(
            id=molecule.id,
            cid=molecule.cid,
            name=molecule.name,
            canonical_smiles=molecule.canonical_smiles or "",
            inchi=molecule.inchi,
            inchikey=molecule.inchikey,
            molecular_formula=molecule.molecular_formula,
            molecular_weight=molecule.molecular_weight,
            properties=molecule.properties,
            structures=[],
            computed_properties=[],
            created_at=created,
            updated_at=updated,
        )

    async def _run_xtb_optimization(self, molecule: Molecule) -> None:
        """Stage 4: Run xTB GFN2-xTB geometry optimization on best available structure."""
        try:
            # Find best SDF (prefer pubchem-3d > conforge > rdkit)
            best_sdf = None
            for method in ["pubchem-3d", "conforge", "rdkit"]:
                for s in (molecule.structures or []):
                    if s.format == "sdf" and s.generation_method == method:
                        best_sdf = s.structure_data
                        break
                if best_sdf:
                    break

            if not best_sdf:
                return

            # Count atoms (check limit: <=150 for xTB to keep under 30s)
            atom_count = self._rdkit._count_atoms_sync(molecule.canonical_smiles) if molecule.canonical_smiles else 0
            if atom_count > 150:
                logger.info("xtb_skip_too_large", atoms=atom_count, molecule_id=str(molecule.id))
                return

            # Convert SDF → XYZ via converter
            xyz_data = await self._converter.convert(best_sdf, "sdf", "xyz")
            if not xyz_data:
                return

            # Run xTB optimization
            if self._xtb_runner is None:
                return

            result = await self._xtb_runner.run(
                xyz_data,
                tasks=["optimize"],
                charge=0,
                multiplicity=1,
            )

            if result.success and result.optimized_xyz:
                # Convert optimized XYZ back to SDF for storage
                opt_sdf = await self._converter.convert(result.optimized_xyz, "xyz", "sdf")
                if opt_sdf and len(opt_sdf) > 10:
                    structure = MoleculeStructure(
                        molecule_id=molecule.id,
                        format="sdf",
                        structure_data=opt_sdf,
                        generation_method="xtb-gfn2",
                        is_primary=False,  # Not primary, just an option
                    )
                    self._db.add(structure)
                    logger.info("xtb_structure_saved",
                              molecule_id=str(molecule.id),
                              energy=result.total_energy,
                              elapsed=result.elapsed_seconds)
            else:
                logger.debug("xtb_optimization_failed",
                           molecule_id=str(molecule.id),
                           error=getattr(result, 'error_message', 'unknown'))

        except Exception as exc:
            logger.debug("xtb_stage_error", molecule_id=str(molecule.id), error=str(exc))

    async def _trigger_l2(self, molecule: Molecule) -> str:
        """Enqueue an L2 xTB calculation if not already done/running."""
        # Check if we already have xTB results
        has_xtb = any(
            p.source == "xtb" for p in (molecule.computed_properties or [])
        )
        if has_xtb:
            return "completed"

        # Check atom count limit
        try:
            atom_count = await self._rdkit.count_atoms(molecule.canonical_smiles)
            if atom_count > settings.XTB_MAX_ATOMS:
                return "skipped_too_large"
        except Exception:
            return "skipped_invalid_smiles"

        await self._calc_queue.submit(
            molecule_id=molecule.id,
            smiles=molecule.canonical_smiles,
            method=settings.XTB_METHOD,
            tasks=["optimize", "energy"],
        )
        return "pending"
    # ═══════════════════════════════════════════
    # Molecule Card — comprehensive single-molecule view
    # ═══════════════════════════════════════════

    async def get_card(
        self,
        *,
        q: str | None = None,
        cid: int | None = None,
    ) -> "MoleculeCardResponse":
        """Build a comprehensive molecule card in <3 seconds.

        Pipeline:
          Layer A (required): search → core properties (<1s)
          Layer B (parallel):  GHS safety + similar molecules (<2s)
          Layer C (parallel):  AI summary (<1.5s)
          Local calc:          drug-likeness (instant)
        """
        import asyncio
        import time
        from app.schemas.molecule_card import (
            MoleculeCardResponse,
            GHSSafety,
            SimilarMolecule,
        )
        from app.services.molecule_engine.drug_likeness import (
            evaluate_lipinski,
            evaluate_veber,
            evaluate_ghose,
        )
        from app.services.molecule_engine.ghs_parser import fetch_ghs
        # [REMOVED] Old query_validator — replaced by pug_rest_resolver

        t0 = time.perf_counter()

        # --- CID-pattern safety net (patch_cid_bug) ---
        import re as _re_cid
        if q:
            _cid_m = _re_cid.match(r'^CID[:\s:\-]*?(\d+)$', q.strip(), _re_cid.IGNORECASE)
            if _cid_m:
                logger.info('cid_pattern_redirect', original_q=q, extracted_cid=int(_cid_m.group(1)))
                cid = int(_cid_m.group(1))
                q = None
        # --- end CID-pattern safety net ---

        log = logger.bind(card_query=q or str(cid))

        # ── Cache check: Redis (hot) → DB (permanent) ──
        cache_key = f"molcard:cid:{cid}" if cid else f"molcard:name:{q.lower().strip()}"
        cached = await self._cache.get_raw(cache_key)
        if cached is not None:
            log.info("card_cache_hit", source="redis")
            cached["cached"] = True
            return MoleculeCardResponse(**cached)

        # DB permanent cache fallback
        try:
            from app.core.database import async_session_factory
            from app.models.molecule_card import MoleculeCardCache
            from sqlalchemy import select
            async with async_session_factory() as db_session:
                if cid:
                    stmt = select(MoleculeCardCache).where(MoleculeCardCache.cid == cid)
                else:
                    stmt = select(MoleculeCardCache).where(
                        MoleculeCardCache.name.ilike(q.strip())
                    )
                row = (await db_session.execute(stmt)).scalar_one_or_none()
                if row is not None:
                    card_data = row.card_json
                    card_data["cached"] = True
                    # Re-warm Redis
                    try:
                        await self._cache.set_raw(cache_key, card_data, ttl=86400)
                        if row.cid:
                            await self._cache.set_raw(f"molcard:cid:{row.cid}", card_data, ttl=86400)
                    except Exception:
                        pass
                    log.info("card_cache_hit", source="db")
                    return MoleculeCardResponse(**card_data)
        except Exception as _db_err:
            log.warning("card_db_cache_read_failed", error=str(_db_err))

        # ── Layer A: resolve molecule ──
        mol = None

        # ── PUG REST: Direct name→CID exact match (NEW — replaces Autocomplete validator) ──
        if q and not cid:
            pug_result = await resolve_name_to_cid(q)
            if pug_result.found and pug_result.cid:
                # PUG REST found an exact match — use it as CID for the rest of the pipeline
                cid = pug_result.cid
                log.info("pug_rest_direct_hit", query=q, cid=cid, 
                         name=pug_result.name, elapsed_ms=round(pug_result.elapsed_ms, 1))
            else:
                # PUG REST says this name doesn't exist in PubChem
                # This is a clean rejection — no fuzzy matching involved
                log.info("pug_rest_not_found", query=q, error=pug_result.error,
                         elapsed_ms=round(pug_result.elapsed_ms, 1))
                raise MoleculeNotFoundError(
                    f"'{q}' is not a recognized chemical compound in PubChem"
                )


        # CID가 직접 주어진 경우: PubChem REST로 직접 조회
        if cid and not q:
            try:
                async with httpx.AsyncClient(timeout=5.0) as _client:
                    prop_url = (
                        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}"
                        f"/property/IUPACName,MolecularFormula,MolecularWeight,"
                        f"CanonicalSMILES,InChI,InChIKey,XLogP,TPSA,"
                        f"HBondDonorCount,HBondAcceptorCount,RotatableBondCount,"
                        f"HeavyAtomCount,Complexity,ExactMass,Charge/JSON"
                    )
                    resp = await _client.get(prop_url)
                    if resp.status_code == 200:
                        p = resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]

                        # Fetch synonyms
                        syn_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
                        syn_resp = await _client.get(syn_url, timeout=3.0)
                        synonyms = []
                        common_name = p.get("IUPACName", f"CID-{cid}")
                        if syn_resp.status_code == 200:
                            syn_data = syn_resp.json()
                            syn_list = (syn_data.get("InformationList", {})
                                        .get("Information", [{}])[0]
                                        .get("Synonym", []))
                            synonyms = syn_list[:10]
                            if syn_list:
                                common_name = syn_list[0]

                        import uuid as _uuid
                        from app.schemas.molecule import MoleculeRecord
                        from datetime import datetime, timezone
                        mol = MoleculeRecord(
                            id=_uuid.uuid4(),
                            cid=cid,
                            name=common_name,
                            canonical_smiles=p.get("CanonicalSMILES", ""),
                            inchi=p.get("InChI"),
                            inchikey=p.get("InChIKey"),
                            molecular_formula=p.get("MolecularFormula"),
                            molecular_weight=p.get("MolecularWeight"),
                            properties={
                                "iupac_name": p.get("IUPACName"),
                                "xlogp": p.get("XLogP"),
                                "tpsa": p.get("TPSA"),
                                "hbond_donor": p.get("HBondDonorCount"),
                                "hbond_acceptor": p.get("HBondAcceptorCount"),
                                "rotatable_bonds": p.get("RotatableBondCount"),
                                "heavy_atom_count": p.get("HeavyAtomCount"),
                                "complexity": p.get("Complexity"),
                                "exact_mass": str(p.get("ExactMass", "")),
                                "charge": p.get("Charge"),
                                "synonyms": synonyms,
                                "_source": "pubchem",
                                "_source_id": str(cid),
                                "_source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                                "_confidence": 1.0,
                            },
                            structures=[],
                            computed_properties=[],
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
            except Exception as e:
                log.warning("card_cid_direct_failed", cid=cid, error=str(e))

        # 이름/SMILES 검색 또는 CID 직접 조회 실패 시 fallback
        if mol is None:
            search_q = q if q else str(cid)
            search_result = await self.search(search_q, limit=1, sources=["pubchem"])
            if not search_result.results:
                search_result = await self.search(search_q, limit=1)
            if not search_result.results:
                raise MoleculeNotFoundError(search_q)
            mol = search_result.results[0]

        # ── Query Validation: now handled upstream by PUG REST exact match ──
        # The old Autocomplete+JW+Synonym 3-stage validator has been removed.
        # PUG REST name search (in pug_rest_resolver.py) does exact matching,
        # so no post-hoc validation is needed.

        mol_cid = mol.cid
        props = mol.properties or {}

        # ── Layer B + C: parallel enrichment ──



        async def _safe_fetch_ghs() -> GHSSafety | None:
            if not mol_cid:
                return None
            try:
                return await fetch_ghs(mol_cid)
            except Exception:
                return None

        async def _safe_fetch_similar() -> list[SimilarMolecule]:
            if not mol_cid:
                return []
            try:
                return await self._fetch_similar_molecules(mol_cid)
            except Exception:
                return []

        async def _safe_generate_summary() -> str | None:
            try:
                return await self._generate_card_summary(mol)
            except Exception:
                return None

        ghs_result, similar_result, ai_summary = await asyncio.gather(
            _safe_fetch_ghs(),
            _safe_fetch_similar(),
            _safe_generate_summary(),
        )

        # ── Drug-likeness (local, instant) ──
        drug_likeness = [
            evaluate_lipinski(
                mol.molecular_weight,
                props.get("xlogp"),
                props.get("hbond_donor"),
                props.get("hbond_acceptor"),
            ),
            evaluate_veber(
                props.get("tpsa"),
                props.get("rotatable_bonds"),
            ),
            evaluate_ghose(
                mol.molecular_weight,
                props.get("xlogp"),
            ),
        ]

        # ── Assemble response ──
        elapsed = (time.perf_counter() - t0) * 1000

        image_url = ""
        if mol_cid:
            image_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{mol_cid}/PNG"

        card = MoleculeCardResponse(
            id=mol.id,
            cid=mol_cid,
            name=mol.name,
            iupac_name=props.get("iupac_name"),
            synonyms=(props.get("synonyms") or [])[:10],
            canonical_smiles=mol.canonical_smiles,
            inchi=mol.inchi,
            inchikey=mol.inchikey,
            image_url=image_url,
            molecular_formula=mol.molecular_formula,
            molecular_weight=mol.molecular_weight,
            xlogp=props.get("xlogp"),
            tpsa=props.get("tpsa"),
            hbond_donor=props.get("hbond_donor"),
            hbond_acceptor=props.get("hbond_acceptor"),
            rotatable_bonds=props.get("rotatable_bonds"),
            heavy_atom_count=props.get("heavy_atom_count"),
            complexity=props.get("complexity"),
            exact_mass=props.get("exact_mass"),
            charge=props.get("charge"),
            drug_likeness=drug_likeness,
            ghs_safety=ghs_result,
            similar_molecules=similar_result or [],
            ai_summary=ai_summary,
            source=props.get("_source", "pubchem"),
            source_url=props.get("_source_url"),
            elapsed_ms=elapsed,
            cached=False,
        )

        # ── Cache (24h TTL) ──
        try:
            card_dict = card.model_dump(mode="json")
            await self._cache.set_raw(cache_key, card_dict, ttl=86400)
            if mol_cid and q:
                cid_key = f"molcard:cid:{mol_cid}"
                await self._cache.set_raw(cid_key, card_dict, ttl=86400)
        except Exception as _cache_err:
            logger.error('card_cache_save_failed', error=str(_cache_err))
            card_dict = card.model_dump(mode="json")

        # ── DB permanent save ──
        try:
            from app.core.database import async_session_factory
            from app.models.molecule_card import MoleculeCardCache
            from sqlalchemy import select
            async with async_session_factory() as db_session:
                existing = None
                if mol_cid:
                    existing = (await db_session.execute(
                        select(MoleculeCardCache).where(MoleculeCardCache.cid == mol_cid)
                    )).scalar_one_or_none()
                if existing:
                    existing.card_json = card_dict
                    existing.query = q or str(cid or "")
                else:
                    db_session.add(MoleculeCardCache(
                        cid=mol_cid,
                        name=card_dict.get("name", ""),
                        query=q or str(cid or ""),
                        card_json=card_dict,
                    ))
                await db_session.commit()
                log.info("card_db_saved", cid=mol_cid, name=card_dict.get("name"))
        except Exception as _db_err:
            log.warning("card_db_save_failed", error=str(_db_err))

        log.info("card_completed", elapsed_ms=round(elapsed, 1))
        return card

    async def _fetch_similar_molecules(
        self, cid: int, threshold: int = 90, max_records: int = 3
    ) -> list:
        """Fetch similar molecules from PubChem 2D similarity search."""
        from app.schemas.molecule_card import SimilarMolecule

        url = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"fastsimilarity_2d/cid/{cid}/"
            f"property/IUPACName,MolecularFormula,CanonicalSMILES/JSON"
            f"?Threshold={threshold}&MaxRecords={max_records + 1}"
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

        props_list = resp.json().get("PropertyTable", {}).get("Properties", [])

        results = []
        for p in props_list:
            result_cid = p.get("CID")
            if result_cid == cid:
                continue  # skip self
            results.append(
                SimilarMolecule(
                    cid=result_cid,
                    name=p.get("IUPACName", f"CID-{result_cid}"),
                    similarity=threshold / 100.0,
                    molecular_formula=p.get("MolecularFormula"),
                    thumbnail_url=f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{result_cid}/PNG?image_size=120x120",
                )
            )
            if len(results) >= max_records:
                break
        return results

    async def _generate_card_summary(self, mol) -> str | None:
        """Generate a 1-2 sentence AI summary of the molecule."""
        try:
            from app.core.config import settings
            if not settings.GEMINI_API_KEY:
                return None

            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = (
                f"In 1-2 concise sentences, describe what {mol.name} "
                f"(SMILES: {mol.canonical_smiles}) is, including its primary uses, "
                f"drug class (if applicable), and key characteristics. "
                f"Be factual and scientific. If it's not a well-known compound, "
                f"describe its chemical class based on functional groups."
            )
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = response.text.strip() if response.text else None
            return text[:500] if text else None
        except Exception as e:
            logger.debug("card_summary_failed", error=str(e))
            return None
