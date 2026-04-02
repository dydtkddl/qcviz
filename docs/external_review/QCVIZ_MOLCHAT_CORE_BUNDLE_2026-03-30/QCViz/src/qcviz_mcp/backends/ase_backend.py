"""ASE 기반 구조 조작 및 포맷 변환 백엔드 구현."""

from __future__ import annotations

import logging
from pathlib import Path

from qcviz_mcp.backends.base import AtomsData, StructureBackend
from qcviz_mcp.backends.registry import registry

try:
    import ase.io

    _HAS_ASE = True
except ImportError:
    _HAS_ASE = False

logger = logging.getLogger(__name__)


class ASEBackend(StructureBackend):
    """ASE 기반 분자 구조 조작 백엔드.

    Note: ASE는 LGPL 라이선스를 가지며, 여기서는 동적 import를 통해 사용합니다.
    """

    @classmethod
    def name(cls) -> str:
        return "ase"

    @classmethod
    def is_available(cls) -> bool:
        return _HAS_ASE

    def read_structure(self, path: str | Path, format: str | None = None) -> AtomsData:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        path_str = str(path)
        logger.info("구조 읽기 시도: %s", path_str)
        try:
            atoms = ase.io.read(path_str, format=format)

            return AtomsData(
                symbols=atoms.get_chemical_symbols(),
                positions=atoms.get_positions(),
                cell=atoms.get_cell().array if atoms.cell else None,  # 타입 문제 회피
                pbc=atoms.get_pbc().tolist() if hasattr(atoms, "get_pbc") else None,
            )
        except Exception as e:
            logger.error("구조 읽기 실패: %s", str(e))
            raise ValueError(f"지원하지 않거나 잘못된 형식: {e}")

    def write_structure(
        self, atoms_data: AtomsData, path: str | Path, format: str | None = None
    ) -> Path:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        from ase import Atoms

        path_obj = Path(path)
        try:
            atoms = Atoms(
                symbols=atoms_data.symbols,
                positions=atoms_data.positions,
                cell=atoms_data.cell,
                pbc=atoms_data.pbc,
            )
            ase.io.write(str(path_obj), atoms, format=format)
            return path_obj
        except Exception as e:
            logger.error("구조 쓰기 실패: %s", str(e))
            raise ValueError(f"파일 저장 실패: {e}")

    def convert_format(self, input_path: str | Path, output_path: str | Path) -> Path:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        in_str = str(input_path)
        out_str = str(output_path)

        logger.info("포맷 변환: %s -> %s", in_str, out_str)
        try:
            atoms = ase.io.read(in_str)
            ase.io.write(out_str, atoms)
            return Path(out_str)
        except Exception as e:
            logger.error("포맷 변환 실패: %s", str(e))
            raise ValueError(f"포맷 변환 실패: {e}")


registry.register(ASEBackend)
