"""cclib 기반 양자화학 출력 파일 파싱 백엔드 구현."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from qcviz_mcp.backends.base import ParsedResult, ParserBackend
from qcviz_mcp.backends.registry import registry

try:
    import cclib

    _HAS_CCLIB = True
except ImportError:
    _HAS_CCLIB = False

logger = logging.getLogger(__name__)


class CclibBackend(ParserBackend):
    """cclib 기반 양자화학 출력 파일 파서.

    지원하는 프로그램: ORCA, Gaussian, GAMESS, NWChem, Psi4, Q-Chem 등 16개.
    """

    @classmethod
    def name(cls) -> str:
        return "cclib"

    @classmethod
    def is_available(cls) -> bool:
        return _HAS_CCLIB

    def parse_file(self, path: str | Path) -> ParsedResult:
        if not _HAS_CCLIB:
            raise ImportError("cclib가 설치되지 않았습니다.")

        path_str = str(path)
        logger.info("파일 파싱 시도: %s", path_str)

        try:
            # cclib의 ccopen을 통해 파일 파싱
            parser = cclib.io.ccopen(path_str)
            if parser is None:
                raise ValueError(f"cclib가 지원하지 않는 파일 형식입니다: {path_str}")

            data = parser.parse()
            logger.info(
                "파싱 성공: %s", getattr(data, "metadata", {}).get("package", "Unknown")
            )

            # 에너지 (scfenergies의 마지막 값, eV 단위이므로 Hartree로 변환 필요)
            # 1 eV = 0.0367493 Hartree
            energy_hartree = None
            if hasattr(data, "scfenergies") and len(data.scfenergies) > 0:
                energy_ev = data.scfenergies[-1]
                energy_hartree = float(energy_ev) * 0.036749322

            # 좌표 (atomcoords의 마지막 구조 사용)
            coordinates = None
            if hasattr(data, "atomcoords") and len(data.atomcoords) > 0:
                coordinates = np.array(data.atomcoords[-1])

            # 원자 번호
            atomic_numbers = None
            if hasattr(data, "atomnos"):
                atomic_numbers = list(data.atomnos)

            # MO 에너지
            mo_energies = None
            if hasattr(data, "moenergies"):
                mo_energies = [np.array(e) for e in data.moenergies]

            # MO 계수
            mo_coefficients = None
            if hasattr(data, "mocoeffs"):
                mo_coefficients = [np.array(c) for c in data.mocoeffs]

            program = getattr(data, "metadata", {}).get("package", "Unknown")

            return ParsedResult(
                energy_hartree=energy_hartree,
                coordinates=coordinates,
                atomic_numbers=atomic_numbers,
                mo_energies=mo_energies,
                mo_coefficients=mo_coefficients,
                program=program,
            )

        except Exception as e:
            logger.error("파일 파싱 중 에러 발생: %s", str(e))
            raise ValueError(f"파싱 실패: {e}")

    @classmethod
    def supported_programs(cls) -> list[str]:
        # cclib가 공식 지원하는 프로그램들 중 대표적인 것들.
        return [
            "ADF",
            "DALTON",
            "Firefly",
            "GAMESS",
            "GAMESS-UK",
            "Gaussian",
            "Jaguar",
            "Molcas",
            "Molpro",
            "MOPAC",
            "NBO",
            "NWChem",
            "ORCA",
            "Psi3",
            "Psi4",
            "Q-Chem",
            "Turbomole",
        ]


registry.register(CclibBackend)
