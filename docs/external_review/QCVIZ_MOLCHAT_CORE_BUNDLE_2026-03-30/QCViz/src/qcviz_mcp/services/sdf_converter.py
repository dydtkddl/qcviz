"""SDF (V2000 MOL) → XYZ converter and multi-SDF merger.

# FIX(N2): SDF→XYZ 변환, 다중 SDF 합치기, PySCF 입력용 atoms list 생성
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 원자번호 → 원소기호 (fallback) ─────────────────────────────
_ATOMIC_SYMBOLS: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
    9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
    16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 26: "Fe", 29: "Cu",
    30: "Zn", 35: "Br", 53: "I",
}


def _parse_mol_block(sdf_text: str) -> List[Tuple[str, float, float, float]]:
    """Parse V2000 MOL block from SDF text.

    Returns:
        List of (symbol, x, y, z) tuples.

    Raises:
        ValueError: If the SDF cannot be parsed.
    """
    if not sdf_text or not sdf_text.strip():
        raise ValueError("빈 SDF 텍스트입니다 / Empty SDF text")

    lines = sdf_text.strip().splitlines()

    # Find counts line (line index 3 in standard V2000, but be flexible)
    counts_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # V2000 counts line pattern: "  N  M  ... V2000"
        if stripped.endswith("V2000") or re.match(r"^\s*\d+\s+\d+\s+", stripped):
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    int(parts[0])
                    int(parts[1])
                    counts_idx = i
                    break
                except ValueError:
                    continue

    if counts_idx is None:
        raise ValueError(
            "V2000 MOL 블록의 counts 라인을 찾을 수 없습니다 / "
            "Cannot find V2000 counts line in SDF"
        )

    counts_parts = lines[counts_idx].split()
    n_atoms = int(counts_parts[0])
    # n_bonds = int(counts_parts[1])  # not needed for XYZ

    if n_atoms <= 0:
        raise ValueError(
            f"원자 수가 0 이하입니다: {n_atoms} / Atom count is <= 0: {n_atoms}"
        )

    atom_start = counts_idx + 1
    atoms: List[Tuple[str, float, float, float]] = []

    for i in range(n_atoms):
        line_idx = atom_start + i
        if line_idx >= len(lines):
            raise ValueError(
                f"SDF 원자 라인 부족: {i+1}/{n_atoms} / "
                f"Not enough atom lines: {i+1}/{n_atoms}"
            )

        parts = lines[line_idx].split()
        if len(parts) < 4:
            raise ValueError(
                f"원자 라인 파싱 실패 (라인 {line_idx}): '{lines[line_idx]}' / "
                f"Failed to parse atom line {line_idx}"
            )

        try:
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
        except ValueError as e:
            raise ValueError(
                f"좌표 파싱 실패 (라인 {line_idx}): {e} / "
                f"Coordinate parse error at line {line_idx}: {e}"
            ) from e

        symbol = parts[3].strip()
        # Clean up symbol (some SDF files have extra characters)
        symbol = re.sub(r"[^A-Za-z]", "", symbol)
        if not symbol:
            raise ValueError(
                f"원소 기호가 비어있습니다 (라인 {line_idx}) / "
                f"Empty element symbol at line {line_idx}"
            )

        # Capitalize properly
        symbol = symbol[0].upper() + symbol[1:].lower() if len(symbol) > 1 else symbol.upper()
        atoms.append((symbol, x, y, z))

    return atoms


def sdf_to_xyz(sdf_text: str, comment: str = "Converted from SDF") -> str:
    """Convert SDF (V2000) text to XYZ format string.

    Args:
        sdf_text: SDF/MOL text content.
        comment: Comment line for XYZ header.

    Returns:
        XYZ format string (natoms\\ncomment\\nsymbol x y z\\n...).

    Raises:
        ValueError: If SDF parsing fails.
    """
    atoms = _parse_mol_block(sdf_text)
    n = len(atoms)

    lines = [str(n), comment]
    for symbol, x, y, z in atoms:
        lines.append(f"{symbol:2s} {x: .8f} {y: .8f} {z: .8f}")

    return "\n".join(lines)


def sdf_to_atoms_list(
    sdf_text: str,
) -> List[Tuple[str, Tuple[float, float, float]]]:
    """Convert SDF to PySCF-compatible atoms list.

    Returns:
        List of (symbol, (x, y, z)) tuples suitable for ``gto.M(atom=...)``.
    """
    raw_atoms = _parse_mol_block(sdf_text)
    return [(sym, (x, y, z)) for sym, x, y, z in raw_atoms]


def merge_sdfs(
    sdf_list: List[str],
    offset: float = 5.0,
    comment: str = "Merged ion pair",
) -> str:
    """Merge multiple SDF structures into a single XYZ with coordinate offsets.

    Each subsequent SDF's atoms are offset along the X-axis by ``offset`` Å
    to prevent atom overlap.

    Args:
        sdf_list: List of SDF text strings.
        offset: X-axis offset in Ångströms between fragments.
        comment: Comment line for XYZ header.

    Returns:
        Combined XYZ format string.

    Raises:
        ValueError: If any SDF parsing fails or list is empty.
    """
    if not sdf_list:
        raise ValueError("빈 SDF 리스트입니다 / Empty SDF list")

    all_atoms: List[Tuple[str, float, float, float]] = []
    current_offset = 0.0

    for idx, sdf_text in enumerate(sdf_list):
        try:
            atoms = _parse_mol_block(sdf_text)
        except ValueError as e:
            raise ValueError(
                f"SDF #{idx+1} 파싱 실패: {e} / "
                f"Failed to parse SDF #{idx+1}: {e}"
            ) from e

        for symbol, x, y, z in atoms:
            all_atoms.append((symbol, x + current_offset, y, z))

        if atoms:
            # Calculate max X extent for this fragment
            max_x = max(x for _, x, _, _ in atoms)
            current_offset = max_x + offset

    n = len(all_atoms)
    lines = [str(n), comment]
    for symbol, x, y, z in all_atoms:
        lines.append(f"{symbol:2s} {x: .8f} {y: .8f} {z: .8f}")

    return "\n".join(lines)
