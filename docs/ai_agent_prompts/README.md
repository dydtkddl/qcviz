# AI Agent Prompts

이 디렉토리는 Gemini + MolChat 기반 QCViz-MCP 고도화 작업을 다른 AI 에이전트에게 위임할 때 바로 사용할 수 있는 작업지시 프롬프트 모음이다.

파일 구성:

- `master_prompt_3step.md`
  - 전체 3 Step 전략을 한 번에 지시하는 통합 프롬프트
- `step1_planner_prompt.md`
  - Planner, 정규화, typed schema, fallback 정비 전용 프롬프트
- `step2_clarification_prompt.md`
  - 동적 clarification, 멀티턴 세션, 웹 UX 전용 프롬프트
- `step3_explanation_advisor_prompt.md`
  - 결과 해설, advisor 통합, observability, live 검증 전용 프롬프트

권장 사용 순서:

1. `master_prompt_3step.md`로 전체 컨텍스트와 최종 목표를 이해시킨다.
2. 실제 구현은 `step1_planner_prompt.md`부터 순서대로 투입한다.
3. 각 Step 종료 후 `pytest`, integration test, E2E, live smoke 결과를 확인한 뒤 다음 Step으로 넘어간다.

권장 검증 게이트:

```bash
pytest -q
pytest -m "not live"
pytest -m live
playwright test
```

운영 원칙:

- MolChat API는 구조 해석의 핵심 경로로 유지한다.
- Gemini는 orchestration layer로 사용한다.
- 계산 엔진(PySCF)과 chemistry truth source를 LLM이 대체하면 안 된다.
- LLM 출력은 반드시 typed schema와 validation을 거치게 한다.
