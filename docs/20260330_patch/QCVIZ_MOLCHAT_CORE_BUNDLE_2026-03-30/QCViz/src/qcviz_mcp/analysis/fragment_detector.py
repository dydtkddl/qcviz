"""거리 기반 분자 프래그먼트 자동 감지.

공유결합 반지름 + 허용 오차(1.3배)로 원자 연결성 그래프를 구축하고,
연결 성분(connected components)을 프래그먼트로 식별한다.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Dict

# 공유결합 반지름 (Angstrom), Cordero et al. 2008
_COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84,
    "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "Ar": 1.06, "K": 2.03, "Ca": 1.76,
    "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20,
    "Kr": 1.16, "Rb": 2.20, "Sr": 1.95, "Y": 1.90, "Zr": 1.75,
    "Nb": 1.64, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39,
    "Te": 1.38, "I": 1.39, "Xe": 1.40,
}

_DEFAULT_RADIUS = 1.50  # 알 수 없는 원소 기본값
_BOND_TOLERANCE = 1.3   # 결합 판정 허용 배수


def detect_fragments(
    atoms: List[Tuple[str, float, float, float]],
    tolerance: float = _BOND_TOLERANCE,
) -> List[List[int]]:
    """원자 리스트에서 프래그먼트(연결 성분)를 감지.

    Parameters
    ----------
    atoms : list of (symbol, x, y, z)
    tolerance : float
        공유결합 반지름 합에 곱하는 허용 배수.

    Returns
    -------
    list of list of int
        각 프래그먼트의 원자 인덱스 리스트. 크기 순 정렬 (큰 것 먼저).
    """
    n = len(atoms)
    if n == 0:
        return []

    # 인접 리스트 구축
    adj = [[] for _ in range(n)]
    for i in range(n):
        si, xi, yi, zi = atoms[i]
        ri = _COVALENT_RADII.get(si, _DEFAULT_RADIUS)
        for j in range(i + 1, n):
            sj, xj, yj, zj = atoms[j]
            rj = _COVALENT_RADII.get(sj, _DEFAULT_RADIUS)
            dist = math.sqrt((xi - xj)**2 + (yi - yj)**2 + (zi - zj)**2)
            if dist <= (ri + rj) * tolerance:
                adj[i].append(j)
                adj[j].append(i)

    # BFS로 연결 성분 탐색
    visited = [False] * n
    fragments = []
    for start in range(n):
        if visited[start]:
            continue
        component = []
        queue = [start]
        visited[start] = True
        while queue:
            node = queue.pop(0)
            component.append(node)
            for neighbor in adj[node]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
        fragments.append(sorted(component))

    # 크기 순 정렬 (큰 프래그먼트 먼저)
    fragments.sort(key=lambda f: -len(f))
    return fragments


def fragment_summary(
    atoms: List[Tuple[str, float, float, float]],
    fragments: List[List[int]],
) -> List[Dict]:
    """각 프래그먼트의 요약 정보 생성."""
    from collections import Counter
    results = []
    for i, frag_indices in enumerate(fragments):
        syms = [atoms[idx][0] for idx in frag_indices]
        counts = Counter(syms)
        formula = "".join(
            "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
            for e in sorted(counts.keys())
        )
        # 프래그먼트 중심
        cx = sum(atoms[idx][1] for idx in frag_indices) / len(frag_indices)
        cy = sum(atoms[idx][2] for idx in frag_indices) / len(frag_indices)
        cz = sum(atoms[idx][3] for idx in frag_indices) / len(frag_indices)
        results.append({
            "fragment_id": i,
            "atom_indices": frag_indices,
            "n_atoms": len(frag_indices),
            "formula": formula,
            "center": (cx, cy, cz),
        })
    return results
