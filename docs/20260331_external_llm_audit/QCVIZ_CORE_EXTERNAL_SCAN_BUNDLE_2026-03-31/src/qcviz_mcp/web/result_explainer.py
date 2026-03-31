from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from qcviz_mcp.llm.schemas import ResultExplanation


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _confidence_score(advisor: Optional[Mapping[str, Any]]) -> Optional[float]:
    payload = dict(advisor or {})
    confidence = payload.get("confidence") or {}
    data = confidence.get("data") if isinstance(confidence, dict) else None
    if not isinstance(data, Mapping):
        return None
    return _safe_float(
        data.get("overall_score")
        or data.get("score")
        or data.get("confidence")
        or data.get("final_score")
    )


def _confidence_recommendations(advisor: Optional[Mapping[str, Any]]) -> List[str]:
    payload = dict(advisor or {})
    confidence = payload.get("confidence") or {}
    data = confidence.get("data") if isinstance(confidence, dict) else None
    if not isinstance(data, Mapping):
        return []
    recommendations = data.get("recommendations") or []
    if not isinstance(recommendations, list):
        return []
    return [str(item).strip() for item in recommendations if str(item).strip()]


def _top_charge_atoms(result: Mapping[str, Any]) -> Dict[str, Optional[Mapping[str, Any]]]:
    charges = result.get("partial_charges") or result.get("mulliken_charges") or []
    if not isinstance(charges, list) or not charges:
        return {"most_negative": None, "most_positive": None}
    ranked = [item for item in charges if isinstance(item, Mapping) and _safe_float(item.get("charge")) is not None]
    if not ranked:
        return {"most_negative": None, "most_positive": None}
    return {
        "most_negative": min(ranked, key=lambda item: float(item.get("charge"))),
        "most_positive": max(ranked, key=lambda item: float(item.get("charge"))),
    }


def build_result_explanation(
    *,
    query: str,
    intent_name: str,
    result: Mapping[str, Any],
    advisor: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    job_type = _safe_str(result.get("job_type") or intent_name or "analyze")
    structure = _safe_str(result.get("structure_name") or result.get("structure_query") or query or "molecule")
    explanation = ResultExplanation()

    total_energy_ev = _safe_float(result.get("total_energy_ev"))
    gap_ev = _safe_float(result.get("orbital_gap_ev"))
    converged = bool(result.get("scf_converged"))
    n_cycles = result.get("n_scf_cycles")
    confidence_score = _confidence_score(advisor)

    if job_type == "orbital_preview":
        explanation.summary = f"{structure}의 오비탈 계산이 완료되었습니다. HOMO/LUMO와 관련 에너지 차이를 바로 확인할 수 있습니다."
        selected = result.get("selected_orbital") or {}
        if _safe_str(selected.get("label")):
            explanation.key_findings.append(
                f"선택된 오비탈은 {_safe_str(selected.get('label'))}이며 에너지는 {_safe_float(selected.get('energy_ev'), 0.0):.4f} eV 입니다."
            )
        if gap_ev is not None:
            explanation.key_findings.append(f"HOMO-LUMO gap은 {gap_ev:.4f} eV 입니다.")
            if gap_ev < 3.0:
                explanation.interpretation.append("비교적 작은 gap은 전자 재배치가 쉬운 편일 수 있음을 시사합니다.")
            elif gap_ev > 6.0:
                explanation.interpretation.append("상대적으로 큰 gap은 전자적 안정성이 더 큰 쪽으로 해석될 수 있습니다.")
        explanation.next_actions.extend([
            "LUMO 또는 반대 스핀 궤도까지 비교해 전자 분포 차이를 확인하세요.",
            "ESP 맵을 함께 계산하면 반응성이 높은 영역을 더 직관적으로 볼 수 있습니다.",
        ])
    elif job_type == "esp_map":
        explanation.summary = f"{structure}의 ESP 분석이 완료되었습니다. 전하 분포가 집중되는 영역을 시각적으로 해석할 수 있습니다."
        range_kcal = _safe_float(result.get("esp_auto_range_kcal"))
        if range_kcal is not None:
            explanation.key_findings.append(f"ESP 표시 범위는 약 ±{range_kcal:.2f} kcal/mol 수준입니다.")
        explanation.interpretation.append("ESP의 양/음 전위 분포는 친전자성 또는 친핵성 공격 위치를 추정할 때 유용합니다.")
        explanation.next_actions.extend([
            "부분 전하 계산과 함께 보면 원자별 전하 분포를 교차 검증할 수 있습니다.",
            "geometry optimization 후 다시 ESP를 계산하면 더 안정화된 구조에서 비교할 수 있습니다.",
        ])
    elif job_type == "partial_charges":
        explanation.summary = f"{structure}의 부분 전하 계산이 완료되었습니다. 원자별 전자 밀도 편중을 비교할 수 있습니다."
        charge_summary = _top_charge_atoms(result)
        most_negative = charge_summary["most_negative"]
        most_positive = charge_summary["most_positive"]
        if most_negative:
            explanation.key_findings.append(
                f"가장 음전하가 큰 원자는 {_safe_str(most_negative.get('symbol'))} ({float(most_negative.get('charge')):.4f}) 입니다."
            )
        if most_positive:
            explanation.key_findings.append(
                f"가장 양전하가 큰 원자는 {_safe_str(most_positive.get('symbol'))} ({float(most_positive.get('charge')):.4f}) 입니다."
            )
        explanation.interpretation.append("전하 분포는 결합 극성과 반응 중심을 해석할 때 직접적인 힌트를 줍니다.")
        explanation.next_actions.extend([
            "ESP 맵을 추가로 보면 공간적인 전위 분포를 함께 해석할 수 있습니다.",
            "구조 최적화 후 다시 전하를 계산해 기하구조 변화 영향을 비교하세요.",
        ])
    elif job_type == "geometry_optimization":
        explanation.summary = f"{structure}의 구조 최적화가 완료되었습니다. 최적화된 좌표와 안정화 경향을 확인할 수 있습니다."
        explanation.interpretation.append("최적화 결과는 이후 ESP, 오비탈, 전하 계산의 기준 구조로 쓰는 것이 일반적입니다.")
        explanation.next_actions.extend([
            "최적화된 구조에서 single-point 또는 orbital 계산을 이어서 수행하세요.",
            "필요하면 더 큰 basis set으로 재최적화해 민감도를 확인하세요.",
        ])
    elif job_type == "geometry_analysis":
        explanation.summary = f"{structure}의 기하구조 분석이 완료되었습니다. 결합 길이와 구조적 특징을 검토할 수 있습니다."
        explanation.interpretation.append("결합 길이와 구조 요약은 문헌값 또는 최적화 전후 비교에 유용합니다.")
        explanation.next_actions.extend([
            "문헌값과 비교하거나 geometry optimization 결과와 차이를 검토하세요.",
            "결합 각도/이온쌍 배치를 기준으로 ESP 또는 전하 계산을 이어가세요.",
        ])
    else:
        explanation.summary = f"{structure} 계산이 완료되었습니다. 핵심 에너지와 수렴 상태를 바탕으로 후속 분석을 진행할 수 있습니다."
        if total_energy_ev is not None:
            explanation.key_findings.append(f"총 에너지는 {total_energy_ev:.4f} eV 입니다.")
        explanation.next_actions.extend([
            "원하는 성질에 따라 orbital, ESP, partial charge 계산을 추가하세요.",
            "더 높은 정확도가 필요하면 basis set이나 방법론을 한 단계 올려 비교하세요.",
        ])

    if converged:
        cycle_text = f"{n_cycles} cycles" if n_cycles is not None else "수렴"
        explanation.key_findings.append(f"SCF는 {cycle_text} 내에서 정상 수렴했습니다.")
    else:
        explanation.cautions.append("SCF가 완전히 수렴하지 않았을 수 있으므로 수치 해석은 보수적으로 해야 합니다.")

    final_delta = _safe_float(result.get("scf_final_delta_e_hartree"))
    if final_delta is not None and abs(final_delta) > 1e-3:
        explanation.cautions.append("최종 dE가 비교적 커서 수렴 품질을 한 번 더 확인하는 것이 좋습니다.")

    if confidence_score is not None:
        explanation.key_findings.append(f"advisor confidence score는 {confidence_score:.2f} 입니다.")
        if confidence_score < 0.45:
            explanation.cautions.append("advisor confidence가 낮아 방법론 또는 basis 재검토가 필요할 수 있습니다.")

    for item in _confidence_recommendations(advisor):
        if item not in explanation.next_actions:
            explanation.next_actions.append(item)

    literature = (advisor or {}).get("literature") if isinstance(advisor, Mapping) else None
    if isinstance(literature, Mapping) and literature.get("status") == "error":
        explanation.cautions.append("문헌 검증은 실패했거나 충분한 기하 정보가 없어 생략되었습니다.")

    explanation.key_findings = explanation.key_findings[:5]
    explanation.interpretation = explanation.interpretation[:4]
    explanation.cautions = explanation.cautions[:4]
    explanation.next_actions = explanation.next_actions[:5]
    return explanation.model_dump()
