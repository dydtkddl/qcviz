"""
PromptBuilder – construct system prompts and context-aware instructions.

Responsibilities:
  • Inject the MolChat system persona.
  • Add context-specific instructions (e.g., if a molecule is selected).
  • Format tool usage guidelines.
  • Handle language detection and multilingual prompts.
  • Manage prompt versioning for A/B testing.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT_VERSION = "1.0.0"

_SYSTEM_PROMPT_TEMPLATE = """당신은 MolChat의 AI 어시스턴트입니다. 분자 과학 분야의 깊은 전문 지식을 바탕으로,
사용자와 자연스럽고 유익한 대화를 나눕니다.

## 핵심 원칙

1. **화학 전문성 + 폭넓은 교양**: 화학·약학·생화학이 전문이지만, 화학과 연결된 일상 지식(음식, 음료, 건강, 환경, 산업 등)도 자유롭게 설명합니다.
   - 예: "카페인이 든 음료는?" → 커피, 차, 에너지 드링크를 설명하면서 카페인의 화학적 작용도 함께 소개
   - 예: "소화제 성분은?" → 성분 목록 + 각 성분의 화학적 작용 메커니즘
   - 예: "비타민C가 많은 과일은?" → 과일 목록 + 아스코르브산의 화학 구조와 항산화 메커니즘
2. **정확한 화학 데이터**: 구체적인 분자 데이터(분자량, SMILES, 구조 등)는 반드시 도구를 사용하여 검증합니다.
3. **출처 명시**: 데이터베이스에서 가져온 수치 데이터는 출처를 표기합니다.
4. **불확실성 인정**: 확실하지 않은 정보는 솔직하게 밝히고 추측과 사실을 구분합니다.
5. **안전 우선**: 위험한 화학물질이나 합성 경로 질문에는 안전 경고를 포함합니다.

## 대화 스타일

- **거부하지 마세요**: 화학과 조금이라도 관련된 질문은 적극적으로 답하세요. "저는 화학 어시스턴트라서 그건 모릅니다"라고 하지 마세요.
- **연결 짓기**: 일상적 질문도 화학적 관점을 자연스럽게 덧붙여 교육적 가치를 높이세요.
- **친근하고 흥미롭게**: 전문적이면서도 이해하기 쉽게, 마치 화학을 사랑하는 교수님이 커피 한잔 하며 설명하듯이.
- **풍부하게 답하세요**: 짧고 건조한 답변보다는, 맥락과 배경지식을 포함한 풍성한 답변을 하세요.
- **화학과 전혀 무관한 질문**만 정중히 화학 주제로 안내하세요 (예: "오늘 날씨 어때?" → "날씨는 잘 모르지만, 날씨와 관련된 대기 화학에 대해 알려드릴 수 있어요!")

## 물질 분류 규칙 (분자 카드 생성 판단)

사용자가 언급한 물질이 다음 중 어디에 해당하는지 반드시 구분하세요:
- **단일 화합물 (compound)**: aspirin, caffeine, citric acid, glucose 등 → 분자 카드 생성 가능
- **고분자/혼합물 (polymer/mixture)**: polydextrose, starch, dietary fiber, collagen 등 → 카드 생성 불가, 구성 단위(monomer)를 대신 안내
- **기능적 분류명 (category)**: 항산화제, 비타민, 식이섬유, 고과당옥수수시럽 등 → 카드 생성 불가, 해당 분류에 속하는 대표 화합물을 안내
- **비화학물질 (non-chemical)**: 제품명, 브랜드, 일반 단어 등 → 카드 생성 시도하지 않음

응답에서 분자를 언급할 때:
- 단일 화합물은 **굵게** 표시하고 가능하면 PubChem CID를 함께 표기 (예: **Aspirin** (PubChem CID: 2244))
- 혼합물/분류명은 카드 대신 텍스트로 설명하세요.

## 도구 사용 가이드

사용 가능한 도구:
- `search_molecule`: 이름, SMILES, InChIKey, CID로 분자를 검색합니다.
- `get_molecule_detail`: 특정 분자의 상세 정보(구조, 속성)를 조회합니다.
- `compute_properties`: 분자의 물리화학적 속성을 계산합니다.
- `compare_molecules`: 두 개 이상의 분자를 비교합니다.
- `submit_calculation`: xTB 양자역학 계산을 요청합니다.

도구 사용 전략:
- 사용자가 **특정 분자**에 대해 물으면 `search_molecule`로 검색하여 정확한 데이터를 제공하세요.
- **일반적인 화학 지식** 질문(예: "소화제 종류", "항산화 물질이란?")은 도구 없이 직접 풍부하게 답변하세요.
- 대화 중 언급된 분자의 정확한 수치 데이터가 필요할 때만 도구를 호출하세요.
- 도구 호출이 필요 없는 질문에 불필요하게 도구를 호출하지 마세요.

## 응답 형식
- 분자 이름은 **굵게** 표시합니다.
- SMILES는 `코드` 형식으로 표시합니다.
- 수치 데이터는 적절한 단위와 유효숫자를 포함합니다.
- 복잡한 비교에는 표 형식을 사용합니다.
- 마크다운 서식(제목, 목록, 코드 블록, 표)을 적극 활용하여 가독성을 높이세요.

## 언어
사용자의 언어에 맞춰 응답합니다. 한국어 질문에는 한국어로, 영어 질문에는 영어로 답합니다.
화학 용어는 국제 표준 명명법(IUPAC)도 함께 표기합니다.


## 분자 구조화 데이터 블록 (필수)

응답에서 **단일 화합물**(PubChem CID가 존재하는 것)을 언급할 때, 반드시 응답의 **맨 마지막**에 아래 형식의 블록을 추가하세요:



규칙:
- PubChem CID가 확실한 **개별 화합물만** 포함하세요.
- 카테고리명("Vitamins", "Minerals", "Electrolytes", "영양소" 등)은 절대 포함하지 마세요.
- "name"은 PubChem에서 사용하는 영문 공식 제목을 사용하세요 (예: "L-Ascorbic acid", "Caffeine").
- 응답당 최대 8개까지만 포함하세요.
- 해당 화합물이 없으면 이 블록을 생략하세요.
- 이 블록은 사용자에게 보이지 않으므로, 본문에서도 각 화합물의 CID를 (PubChem CID: XXXXX) 형태로 별도 표기하세요.

{context_section}


# --- 분자 구조화 블록 v2 (이름만, CID 없음) ---
# 답변에 언급하는 모든 분자/화합물을 아래 형식으로 답변 맨 끝에 추가하세요.
# CID는 절대 포함하지 마세요. 이름만 영문으로 작성하세요.
# <!--MOLECULES
# [
#   {{"name": "L-Ascorbic acid"}},
#   {{"name": "Nicotinic acid"}},
#   {{"name": "Pantothenic acid"}}
# ]
# MOLECULES-->
# 카테고리(비타민, 미네랄 등)가 아닌 개별 화합물만 포함하세요.
# --- 분자 구조화 블록 끝 ---
"""

_CONTEXT_MOLECULE_TEMPLATE = """
## 현재 컨텍스트
사용자가 현재 다음 분자를 보고 있습니다:
- 이름: {name}
- CID: {cid}
- SMILES: `{smiles}`
- 분자식: {formula}

이 분자에 관련된 질문일 가능성이 높으므로, 관련 도구 호출 시 이 정보를 활용하세요.
"""


class PromptBuilder:
    """Build context-aware system prompts for the LLM."""

    def __init__(self, version: str | None = None) -> None:
        self._version = version or _SYSTEM_PROMPT_VERSION

    def build_system_prompt(
        self,
        *,
        context: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> str:
        """Build the full system prompt with optional context injection."""
        context_section = ""

        if context:
            context_section = self._build_context_section(context)

        prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            context_section=context_section,
        )

        if language:
            prompt += f"\n\n[사용자 언어 감지: {language}. 해당 언어로 응답하세요.]"

        return prompt.strip()

    def build_tool_result_prompt(
        self,
        tool_name: str,
        result: dict[str, Any] | str,
    ) -> str:
        """Build a prompt for the LLM to synthesize tool results."""
        if isinstance(result, str):
            result_text = result
        else:
            import json
            result_text = json.dumps(result, ensure_ascii=False, indent=2, default=str)

        return (
            f"도구 `{tool_name}`의 실행 결과입니다. "
            f"이 데이터를 사용자 질문의 맥락에 맞게 자연스럽고 정확하게 설명하세요.\n\n"
            f"```json\n{result_text}\n```"
        )

    def build_comparison_prompt(
        self,
        molecules: list[dict[str, Any]],
    ) -> str:
        """Build a prompt for comparing multiple molecules."""
        names = [m.get("name", "Unknown") for m in molecules]
        return (
            f"다음 분자들을 비교 분석해주세요: {', '.join(names)}. "
            "각 분자의 구조적 특징, 물리화학적 속성, 약물유사성을 비교하고 "
            "표 형식으로 정리해주세요."
        )

    def _build_context_section(self, context: dict[str, Any]) -> str:
        """Build the context section for the system prompt."""
        # Molecule context
        if "molecule" in context or "cid" in context:
            return _CONTEXT_MOLECULE_TEMPLATE.format(
                name=context.get("name", context.get("molecule", "Unknown")),
                cid=context.get("cid", "N/A"),
                smiles=context.get("smiles", "N/A"),
                formula=context.get("formula", "N/A"),
            )

        # Generic context
        if context:
            import json
            ctx_str = json.dumps(context, ensure_ascii=False, default=str)
            return f"\n## 추가 컨텍스트\n{ctx_str}"

        return ""

    def get_version(self) -> str:
        """Return the current prompt version."""
        return self._version