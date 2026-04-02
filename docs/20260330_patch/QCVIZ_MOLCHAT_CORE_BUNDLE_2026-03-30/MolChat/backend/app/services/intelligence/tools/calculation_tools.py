"""
Calculation tools – xTB quantum chemistry and conformer generation.

These tools submit long-running tasks to the calculation queue
and return task handles for async polling.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.services.intelligence.tools import ToolRegistry

logger = structlog.get_logger(__name__)


def register_calculation_tools(registry: ToolRegistry) -> None:
    """Register all calculation-related tools."""

    # ── 1. submit_calculation ──
    registry.register(
        name="submit_calculation",
        fn=submit_calculation,
        definition={
            "name": "submit_calculation",
            "description": (
                "xTB(GFN2-xTB) 양자역학 계산을 요청합니다. "
                "에너지, 구조 최적화, 진동수 분석 등을 수행할 수 있습니다. "
                "계산은 비동기적으로 진행되며, task_id를 통해 상태를 확인할 수 있습니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "smiles": {
                        "type": "string",
                        "description": "분자의 SMILES 문자열",
                    },
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["energy", "optimize", "frequencies"],
                        },
                        "description": "수행할 계산 종류 (기본값: ['energy'])",
                        "default": ["energy"],
                    },
                    "charge": {
                        "type": "integer",
                        "description": "분자의 전하 (기본값: 0)",
                        "default": 0,
                    },
                    "solvent": {
                        "type": "string",
                        "description": "용매 이름 (예: 'water', 'methanol'). 생략 시 기상 계산.",
                    },
                },
                "required": ["smiles"],
            },
        },
    )

    # ── 2. check_calculation ──
    registry.register(
        name="check_calculation",
        fn=check_calculation,
        definition={
            "name": "check_calculation",
            "description": (
                "진행 중인 xTB 계산의 상태를 확인합니다. "
                "완료된 경우 계산 결과(에너지, 최적화 구조, 진동수 등)를 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "submit_calculation에서 반환된 task_id",
                    },
                },
                "required": ["task_id"],
            },
        },
    )

    # ── 3. generate_conformers ──
    registry.register(
        name="generate_conformers",
        fn=generate_conformers,
        definition={
            "name": "generate_conformers",
            "description": (
                "분자의 3D 컨포머(conformer) 앙상블을 생성합니다. "
                "ETKDG 알고리즘으로 다양한 3D 배향을 탐색하고 "
                "MMFF 에너지로 순위를 매깁니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "smiles": {
                        "type": "string",
                        "description": "분자의 SMILES 문자열",
                    },
                    "num_conformers": {
                        "type": "integer",
                        "description": "생성할 컨포머 수 (기본값: 20)",
                        "default": 20,
                    },
                    "energy_window": {
                        "type": "number",
                        "description": "에너지 필터 윈도우 (kcal/mol, 기본값: 10.0)",
                        "default": 10.0,
                    },
                },
                "required": ["smiles"],
            },
        },
    )


# ═══════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════


async def submit_calculation(
    smiles: str,
    tasks: list[str] | None = None,
    charge: int = 0,
    solvent: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Submit an xTB calculation to the task queue."""
    try:
        from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
        from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue
        from app.core.config import settings

        rdkit = RDKitHandler()
        tasks = tasks or ["energy"]

        # Validate SMILES
        is_valid = await rdkit.parse_smiles(smiles)
        if not is_valid:
            return {"error": f"유효하지 않은 SMILES: {smiles}"}

        # Check atom count
        atom_count = await rdkit.count_atoms(smiles)
        if atom_count > settings.XTB_MAX_ATOMS:
            return {
                "error": (
                    f"분자가 너무 큽니다 ({atom_count}개 원자, "
                    f"최대 {settings.XTB_MAX_ATOMS}개)"
                ),
            }

        # Generate XYZ for xTB
        xyz = await rdkit.smiles_to_xyz(smiles)
        if xyz is None:
            return {"error": "3D 구조를 생성할 수 없습니다."}

        # Submit to queue
        queue = CalculationQueue()
        molecule_id = uuid.uuid4()

        task_id = await queue.submit(
            molecule_id=molecule_id,
            smiles=smiles,
            method=settings.XTB_METHOD,
            tasks=tasks,
            charge=charge,
            solvent=solvent,
        )

        return {
            "task_id": task_id,
            "status": "pending",
            "smiles": smiles,
            "tasks": tasks,
            "atom_count": atom_count,
            "charge": charge,
            "solvent": solvent or "gas phase",
            "message": (
                f"xTB 계산이 제출되었습니다 (task_id: {task_id}). "
                f"check_calculation 도구로 상태를 확인하세요."
            ),
        }

    except Exception as exc:
        logger.error("tool_submit_calc_error", error=str(exc))
        return {"error": f"계산 제출 중 오류 발생: {exc}"}


async def check_calculation(
    task_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Check the status of a submitted calculation."""
    try:
        from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue

        queue = CalculationQueue()
        status = await queue.get_status(task_id)

        if status.get("status") == "not_found":
            return {
                "task_id": task_id,
                "error": "해당 task_id를 찾을 수 없습니다.",
            }

        if status.get("status") == "completed":
            result = status.get("result", {})
            return {
                "task_id": task_id,
                "status": "completed",
                "total_energy_hartree": result.get("total_energy"),
                "homo_lumo_gap_ev": result.get("homo_lumo_gap"),
                "dipole_moment_debye": result.get("dipole_moment"),
                "gibbs_free_energy_hartree": result.get("gibbs_free_energy"),
                "frequencies_count": len(result.get("frequencies", [])),
                "imaginary_frequencies": result.get("imaginary_frequencies", 0),
                "elapsed_seconds": result.get("elapsed_seconds"),
            }

        return {
            "task_id": task_id,
            "status": status.get("status", "unknown"),
            "progress": status.get("progress", 0),
            "message": status.get("message", ""),
        }

    except Exception as exc:
        logger.error("tool_check_calc_error", error=str(exc))
        return {"error": f"상태 확인 중 오류 발생: {exc}"}


async def generate_conformers(
    smiles: str,
    num_conformers: int = 20,
    energy_window: float = 10.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate a conformer ensemble for a molecule."""
    try:
        from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler
        from app.services.molecule_engine.layer2_calculation.conformer import ConformerGenerator

        rdkit = RDKitHandler()

        # Validate
        is_valid = await rdkit.parse_smiles(smiles)
        if not is_valid:
            return {"error": f"유효하지 않은 SMILES: {smiles}"}

        generator = ConformerGenerator()
        ensemble = await generator.generate(
            smiles,
            num_conformers=min(num_conformers, 100),
            energy_window=energy_window,
        )

        conformer_summaries = []
        for conf in ensemble.conformers[:10]:  # Limit to top 10
            conformer_summaries.append({
                "id": conf.conformer_id,
                "energy_kcal_mol": conf.energy,
                "rmsd_to_best": conf.rmsd_to_best,
                "is_minimum": conf.is_minimum,
            })

        return {
            "smiles": smiles,
            "num_generated": ensemble.num_generated,
            "num_converged": ensemble.num_converged,
            "num_unique": len(ensemble.conformers),
            "method": ensemble.method,
            "elapsed_seconds": round(ensemble.elapsed_seconds, 2),
            "best_energy_kcal_mol": (
                ensemble.conformers[0].energy
                if ensemble.conformers
                else None
            ),
            "conformers": conformer_summaries,
        }

    except Exception as exc:
        logger.error("tool_conformers_error", error=str(exc))
        return {"error": f"컨포머 생성 중 오류 발생: {exc}"}
