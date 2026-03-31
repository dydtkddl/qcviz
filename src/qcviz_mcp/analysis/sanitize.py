"""범용 원자 좌표 문자열 정규화 모듈.

모든 도구 경로(SCF, ESP, IBO, GeomOpt)에서 사용되는 단일 정규화 지점.
지원 형식: XYZ 파일(헤더 포함/미포함), PySCF 세미콜론 형식, 빈 줄/주석 포함.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 원소 기호 집합 (Z=1-118)
_ELEMENTS = frozenset({
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf",
    "Es", "Fm", "Md", "No", "Lr",
    "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn",
    "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
})

_COMMENT_RE = re.compile(r"^\s*[#!%]")
_BLANK_RE = re.compile(r"^\s*$")


def _is_atom_line(line: str) -> bool:
    """원소기호 + 3개 float 좌표가 있는 줄인지 판별."""
    parts = line.split()
    if len(parts) < 4:
        return False
    # 첫 토큰이 원소 기호인지 (대소문자 무관)
    sym = parts[0].strip().capitalize()
    # 숫자로 시작하는 경우 원자번호일 수 있음 (e.g., "8 0.0 0.0 0.0")
    if sym.isdigit():
        return len(parts) >= 4
    if sym not in _ELEMENTS:
        return False
    # 나머지 3개가 float인지
    try:
        for i in range(1, 4):
            float(parts[i])
        return True
    except (ValueError, IndexError):
        return False


def sanitize_xyz(raw: str, max_atoms: int = 200) -> str:
    """원시 원자 좌표 문자열을 PySCF 세미콜론 형식으로 정규화.

    Parameters
    ----------
    raw : str
        XYZ 파일 전체, PySCF 형식, 또는 혼합 형식의 원자 좌표 문자열.
    max_atoms : int
        허용 최대 원자 수 (보안 제한).

    Returns
    -------
    str
        "C 0.0 0.0 0.0; H 1.0 0.0 0.0; ..." 형식의 정규화된 문자열.

    Raises
    ------
    ValueError
        원자 좌표를 하나도 추출할 수 없는 경우.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty atom specification")

    raw = raw.strip()

    # 모든 구분자(세미콜론, 개행)를 개행으로 통일하여 줄 단위 처리
    normalized_raw = raw.replace(";", "\n")
    lines = normalized_raw.splitlines()
    atoms = []

    for line in lines:
        line = line.strip()
        if not line: continue
        # 빈 줄, 주석 줄 건너뛰기
        if _BLANK_RE.match(line) or _COMMENT_RE.match(line):
            continue
        # 순수 정수 한 개만 있는 줄 (XYZ 헤더의 원자 수)
        if line.isdigit():
            continue
        # 원자 줄 시도
        if _is_atom_line(line):
            atoms.append(_normalize_atom_token(line))
        # 그 외: XYZ 파일의 comment line (두 번째 줄) — 무시

    if not atoms:
        raise ValueError(
            "No valid atom coordinates found. Expected format: "
            "'Element X Y Z' (one per line) or 'Element X Y Z; Element X Y Z; ...'"
        )

    if len(atoms) > max_atoms:
        raise ValueError("Too many atoms: %d (max %d)" % (len(atoms), max_atoms))

    return "; ".join(atoms)


def _normalize_atom_token(line: str) -> str:
    """단일 원자 줄을 'Element X Y Z' 형식으로 정규화."""
    parts = line.split()
    sym = parts[0].strip()

    # 원자번호인 경우 원소 기호로 변환
    if sym.isdigit():
        sym = _z_to_symbol(int(sym))
    else:
        sym = sym.capitalize()
        # "C1", "H2" 같은 라벨에서 숫자 제거
        sym = re.sub(r"\d+$", "", sym)

    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
    return "%s  %.10f  %.10f  %.10f" % (sym, x, y, z)


def _z_to_symbol(z: int) -> str:
    """원자번호를 원소 기호로 변환."""
    _Z_MAP = [
        "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
        "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr",
        "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
        "In", "Sn", "Sb", "Te", "I", "Xe",
    ]
    if 1 <= z < len(_Z_MAP):
        return _Z_MAP[z]
    return "X"


def extract_atom_list(sanitized: str) -> list:
    """정규화된 문자열에서 [(symbol, x, y, z), ...] 리스트 추출."""
    atoms = []
    for seg in sanitized.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split()
        atoms.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    return atoms


def atoms_to_xyz_string(atoms: list, comment: str = "") -> str:
    """[(symbol, x, y, z), ...] 리스트를 XYZ 파일 문자열로 변환."""
    lines = [str(len(atoms)), comment]
    for sym, x, y, z in atoms:
        lines.append("%-2s  %14.8f  %14.8f  %14.8f" % (sym, x, y, z))
    return "\n".join(lines)
