"""IAO 기반 프래그먼트 간 전하 이전 분석.

개별 원자의 IAO 부분 전하를 프래그먼트별로 합산하여
프래그먼트 순전하(net charge)와 프래그먼트 간 전하 이전량(ΔQ)을 계산한다.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


def compute_fragment_charges(
    iao_charges: np.ndarray,
    fragments: List[List[int]],
    atom_symbols: List[str],
) -> Dict:
    """IAO 부분 전하를 프래그먼트별로 합산.

    Parameters
    ----------
    iao_charges : np.ndarray
        원자별 IAO 부분 전하 (길이 = 원자 수).
    fragments : list of list of int
        프래그먼트별 원자 인덱스.
    atom_symbols : list of str
        원자 기호 리스트.

    Returns
    -------
    dict
        프래그먼트별 전하, 전하 이전 정보를 포함하는 분석 결과.
    """
    from collections import Counter

    frag_data = []
    for i, indices in enumerate(fragments):
        syms = [atom_symbols[idx] for idx in indices]
        counts = Counter(syms)
        formula = "".join(
            "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
            for e in sorted(counts.keys())
        )
        frag_charge = float(np.sum(iao_charges[indices]))
        atom_charges = {idx: float(iao_charges[idx]) for idx in indices}
        frag_data.append({
            "fragment_id": i,
            "formula": formula,
            "net_charge": frag_charge,
            "atom_charges": atom_charges,
            "n_atoms": len(indices),
        })

    # 프래그먼트 간 전하 이전 분석
    transfers = []
    if len(frag_data) >= 2:
        for i in range(len(frag_data)):
            for j in range(i + 1, len(frag_data)):
                qi = frag_data[i]["net_charge"]
                qj = frag_data[j]["net_charge"]
                # 양전하 프래그먼트 → 음전하 프래그먼트로의 전하 이전량
                delta_q = abs(qi - qj) / 2.0
                donor = i if qi > qj else j
                acceptor = j if qi > qj else i
                transfers.append({
                    "donor_fragment": donor,
                    "acceptor_fragment": acceptor,
                    "donor_formula": frag_data[donor]["formula"],
                    "acceptor_formula": frag_data[acceptor]["formula"],
                    "delta_q": delta_q,
                    "donor_charge": frag_data[donor]["net_charge"],
                    "acceptor_charge": frag_data[acceptor]["net_charge"],
                })

    # 상호작용 강도 추정 (정전기 근사, 조 표면 간)
    binding_info = None
    if len(frag_data) >= 2 and len(transfers) > 0:
        t = transfers[0]  # 가장 큰 두 프래그먼트 간
        # 프래그먼트 중심 간 거리 추정은 호출자가 제공
        binding_info = {
            "dominant_transfer": t,
            "interpretation": _interpret_transfer(t["delta_q"]),
        }

    return {
        "fragments": frag_data,
        "transfers": transfers,
        "binding_info": binding_info,
        "total_charge_check": float(np.sum(iao_charges)),
    }


def _interpret_transfer(delta_q: float) -> str:
    """전하 이전량에 따른 결합 특성 해석."""
    if delta_q < 0.05:
        return "Minimal charge_transfer — predominantly dispersive/vdW interaction"
    elif delta_q < 0.15:
        return "Moderate charge transfer — mixed electrostatic/CT interaction"
    elif delta_q < 0.40:
        return "Significant charge transfer — strong donor-acceptor character"
    else:
        return "Large charge transfer — ionic or dative bonding character"
