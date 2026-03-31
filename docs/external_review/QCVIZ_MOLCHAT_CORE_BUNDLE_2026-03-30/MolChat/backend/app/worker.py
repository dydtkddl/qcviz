"""
xTB Worker – long-running process that consumes calculation tasks from Redis.

Architecture:
  • Runs as a separate container (``molchat-xtb-worker``).
  • BRPOP loop on ``molchat:calc:queue``.
  • Each task: generate XYZ → run xTB → parse → store results → update status.
  • Concurrency controlled by ``XTB_WORKER_CONCURRENCY`` (asyncio.Semaphore).
  • Graceful shutdown on SIGTERM/SIGINT.

Usage:
  python -m app.worker
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from typing import Any

import structlog

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis import get_redis_client, close_redis_pool
from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue
from app.services.molecule_engine.layer2_calculation.xtb_runner import XTBRunner, XTBResult

setup_logging()
logger = structlog.get_logger("xtb_worker")

_SHUTDOWN = asyncio.Event()
_SEMAPHORE: asyncio.Semaphore | None = None


async def process_task(
    payload: dict[str, Any],
    queue: CalculationQueue,
    xtb: XTBRunner,
    rdkit: RDKitHandler,
) -> None:
    """Process a single xTB calculation task."""
    task_id = payload["task_id"]
    smiles = payload["smiles"]
    method = payload.get("method", "gfn2")
    tasks = payload.get("tasks", ["energy"])
    charge = payload.get("charge", 0)
    multiplicity = payload.get("multiplicity", 1)
    solvent = payload.get("solvent")

    log = logger.bind(task_id=task_id, smiles=smiles[:50])
    log.info("task_processing_started", tasks=tasks)

    try:
        # Update status: running
        await queue.update_status(
            task_id, status="running", progress=10, message="Generating 3D structure"
        )

        # Generate XYZ from SMILES
        xyz_data = await rdkit.smiles_to_xyz(smiles)
        if xyz_data is None:
            await queue.mark_failed(
                task_id, error="Failed to generate 3D structure from SMILES"
            )
            return

        await queue.update_status(
            task_id, status="running", progress=30, message="Running xTB calculation"
        )

        # Run xTB
        result: XTBResult = await xtb.run(
            xyz_data,
            tasks=tasks,
            charge=charge,
            multiplicity=multiplicity,
            solvent=solvent,
        )

        if not result.success:
            await queue.mark_failed(task_id, error=result.error_message)
            log.warning("task_xtb_failed", error=result.error_message)
            return

        await queue.update_status(
            task_id, status="running", progress=80, message="Storing results"
        )

        # Store results
        result_data: dict[str, Any] = {
            "total_energy": result.total_energy,
            "homo_energy": result.homo_energy,
            "lumo_energy": result.lumo_energy,
            "homo_lumo_gap": result.homo_lumo_gap,
            "dipole_moment": result.dipole_moment,
            "gibbs_free_energy": result.gibbs_free_energy,
            "enthalpy": result.enthalpy,
            "zpve": result.zpve,
            "frequencies": result.frequencies,
            "imaginary_frequencies": result.imaginary_frequencies,
            "optimized_xyz": result.optimized_xyz,
            "method": result.method,
            "tasks_completed": result.tasks_completed,
            "elapsed_seconds": result.elapsed_seconds,
            "molecule_id": payload.get("molecule_id"),
            "smiles": smiles,
        }

        await queue.store_result(task_id, result_data)

        # Persist to database if molecule_id exists
        molecule_id = payload.get("molecule_id")
        if molecule_id:
            await _persist_xtb_results(molecule_id, result_data)

        log.info(
            "task_completed",
            energy=result.total_energy,
            elapsed=f"{result.elapsed_seconds:.1f}s",
        )

    except Exception as exc:
        log.error("task_unexpected_error", error=str(exc))
        await queue.mark_failed(task_id, error=f"Unexpected error: {exc}")


async def _persist_xtb_results(
    molecule_id: str,
    result_data: dict[str, Any],
) -> None:
    """Persist xTB results to the molecule_properties table."""
    try:
        from app.core.database import async_session_factory
        from app.models.molecule import MoleculeProperty, MoleculeStructure

        async with async_session_factory() as session:
            # Store properties
            prop = MoleculeProperty(
                id=uuid.uuid4(),
                molecule_id=uuid.UUID(molecule_id),
                source="xtb",
                data={
                    k: v for k, v in result_data.items()
                    if k not in ("optimized_xyz", "smiles", "molecule_id")
                    and v is not None
                },
            )
            session.add(prop)

            # Store optimized structure
            optimized_xyz = result_data.get("optimized_xyz")
            if optimized_xyz:
                structure = MoleculeStructure(
                    id=uuid.uuid4(),
                    molecule_id=uuid.UUID(molecule_id),
                    format="xyz",
                    structure_data=optimized_xyz,
                    generation_method="xtb-optimized",
                    is_primary=False,
                )
                session.add(structure)

            await session.commit()
            logger.info("xtb_results_persisted", molecule_id=molecule_id)

    except Exception as exc:
        logger.warning("xtb_persist_error", error=str(exc))


async def worker_loop() -> None:
    """Main worker loop: dequeue tasks and process them."""
    global _SEMAPHORE

    concurrency = settings.XTB_WORKER_CONCURRENCY
    _SEMAPHORE = asyncio.Semaphore(concurrency)

    redis = get_redis_client()
    queue = CalculationQueue(redis)
    xtb = XTBRunner()
    rdkit = RDKitHandler()

    logger.info(
        "worker_started",
        concurrency=concurrency,
        method=settings.XTB_METHOD,
        max_atoms=settings.XTB_MAX_ATOMS,
    )

    # Clean up stale tasks on startup
    stale_count = await queue.cleanup_stale(max_age_seconds=3600)
    if stale_count > 0:
        logger.info("stale_tasks_cleaned", count=stale_count)

    while not _SHUTDOWN.is_set():
        try:
            payload = await queue.dequeue(timeout=5)

            if payload is None:
                continue

            # Process with concurrency limit
            async with _SEMAPHORE:
                await process_task(payload, queue, xtb, rdkit)

        except asyncio.CancelledError:
            break

        except Exception as exc:
            logger.error("worker_loop_error", error=str(exc))
            await asyncio.sleep(1.0)

    logger.info("worker_loop_stopped")


async def main() -> None:
    """Entry point: setup signal handlers and run the worker loop."""
    loop = asyncio.get_event_loop()

    def _shutdown_handler():
        logger.info("shutdown_signal_received")
        _SHUTDOWN.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_handler)

    try:
        await worker_loop()
    finally:
        await close_redis_pool()
        logger.info("worker_shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())