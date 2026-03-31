"""QCViz-MCP 백엔드 공통 인터페이스 및 데이터 클래스 정의.

추상 클래스(ABC)를 통해 다양한 양자화학 프로그램 및 시각화 도구를 지원합니다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SCFResult:
    """단일 SCF 계산 결과."""

    converged: bool
    energy_hartree: float
    mo_coeff: np.ndarray
    mo_occ: np.ndarray
    mo_energy: np.ndarray
    basis: str
    method: str


@dataclass(frozen=True)
class IAOResult:
    """Intrinsic Atomic Orbital 계산 결과."""

    coefficients: np.ndarray
    charges: np.ndarray


@dataclass(frozen=True)
class IBOResult:
    """Intrinsic Bond Orbital 계산 결과."""

    coefficients: np.ndarray
    occupations: np.ndarray
    n_ibo: int


@dataclass(frozen=True)
class ParsedResult:
    """양자화학 프로그램 출력 파싱 결과."""

    energy_hartree: float | None
    coordinates: np.ndarray | None  # shape: (n_atoms, 3)
    atomic_numbers: list[int] | None
    mo_energies: list[np.ndarray] | None  # alpha, beta
    mo_coefficients: list[np.ndarray] | None
    program: str


@dataclass(frozen=True)
class AtomsData:
    """원자 구조 정보 데이터."""

    symbols: list[str]
    positions: np.ndarray  # shape: (n_atoms, 3)
    cell: np.ndarray | None
    pbc: list[bool] | None


class BackendBase(abc.ABC):
    """모든 백엔드의 최상위 기본 클래스."""

    @classmethod
    @abc.abstractmethod
    def name(cls) -> str:
        """백엔드 식별 이름을 반환합니다."""
        pass

    @classmethod
    @abc.abstractmethod
    def is_available(cls) -> bool:
        """해당 백엔드 구동에 필요한 의존성이 설치되어 있는지 확인합니다."""
        pass


class OrbitalBackend(BackendBase):
    """양자화학 계산 및 궤도(오비탈) 분석 백엔드 인터페이스."""

    @abc.abstractmethod
    def compute_scf(self, atom_spec: str, basis: str, method: str) -> SCFResult:
        """SCF 계산을 수행합니다."""
        pass

    @abc.abstractmethod
    def compute_iao(self, scf_result: SCFResult, mol_obj: Any) -> IAOResult:
        """주어진 SCF 결과로부터 IAO를 계산합니다."""
        pass

    @abc.abstractmethod
    def compute_ibo(
        self,
        scf_result: SCFResult,
        iao_result: IAOResult,
        mol_obj: Any,
        localization_method: str = "PM",
    ) -> IBOResult:
        """주어진 IAO/SCF 결과로부터 IBO를 계산합니다."""
        pass

    @abc.abstractmethod
    def generate_cube(
        self,
        mol_obj: Any,
        orbital_coeff: np.ndarray,
        orbital_index: int,
        grid_points: tuple[int, int, int] = (80, 80, 80),
    ) -> np.ndarray:
        """특정 오비탈의 cube 데이터를 생성합니다."""
        pass


class ParserBackend(BackendBase):
    """양자화학 계산 출력 파일 파싱 백엔드 인터페이스."""

    @abc.abstractmethod
    def parse_file(self, path: str | Path) -> ParsedResult:
        """출력 파일을 파싱합니다."""
        pass

    @classmethod
    @abc.abstractmethod
    def supported_programs(cls) -> list[str]:
        """지원하는 양자화학 프로그램 목록을 반환합니다."""
        pass


class VisualizationBackend(BackendBase):
    """3D 분자 및 오비탈 시각화 백엔드 인터페이스."""

    @abc.abstractmethod
    def render_molecule(self, xyz_data: str, style: str = "stick") -> str:
        """분자 구조를 시각화하는 HTML 문자열을 반환합니다."""
        pass

    @abc.abstractmethod
    def render_orbital(
        self,
        xyz_data: str,
        cube_data: str,
        isovalue: float = 0.05,
        colors: tuple[str, str] = ("blue", "red"),
        style: str = "stick",
    ) -> str:
        """오비탈 등치면과 분자 구조를 시각화하는 HTML 문자열을 반환합니다."""
        pass


class StructureBackend(BackendBase):
    """분자 구조 조작 및 포맷 변환 백엔드 인터페이스."""

    @abc.abstractmethod
    def read_structure(self, path: str | Path, format: str | None = None) -> AtomsData:
        """구조 파일을 읽어 AtomsData 객체로 반환합니다."""
        pass

    @abc.abstractmethod
    def write_structure(
        self, atoms: AtomsData, path: str | Path, format: str | None = None
    ) -> Path:
        """AtomsData 객체를 지정된 포맷의 파일로 저장합니다."""
        pass

    @abc.abstractmethod
    def convert_format(self, input_path: str | Path, output_path: str | Path) -> Path:
        """구조 파일 포맷을 변경합니다."""
        pass
