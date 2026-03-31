# Step 1 Prompt: Planner, Normalization, Typed Contracts

```text
당신은 이 프로젝트의 Step 1 담당 엔지니어다.
지금 해야 할 일은 Gemini + MolChat 기반 orchestration의 토대를 만드는 것이다.
이번 Step에서는 UI 확장보다 planner 코어, 입력 정규화, typed schema, fallback 안정성을 우선하라.

프로젝트 루트:
- /mnt/d/20260305_양자화학시각화MCP서버구축/version03

집중 대상 파일:
- src/qcviz_mcp/llm/agent.py
- src/qcviz_mcp/services/gemini_agent.py
- src/qcviz_mcp/web/routes/compute.py
- src/qcviz_mcp/services/structure_resolver.py
- src/qcviz_mcp/services/ion_pair_handler.py
- 필요 시 신설:
  - src/qcviz_mcp/llm/schemas.py
  - src/qcviz_mcp/llm/normalizer.py

Step 1 최종 목표:
- Gemini를 실제 메인 planner 경로에 연결
- 자유입력을 robust하게 normalize
- typed plan contract를 확정
- Gemini 실패 시 heuristic fallback이 완전하게 작동
- 이후 Step 2가 이 contract 위에서 동작할 수 있게 만들기

제품 요구:
- “무ㄹ오비탈 계산” 같은 오타 섞인 자연어도 가능한 한 `water + orbital_preview`로 해석해야 한다.
- “아세톤최적화” 같은 붙여쓰기 입력도 잡아야 한다.
- “emim tfsi esp” 같은 이온쌍/약어 입력도 구조화해야 한다.
- “물 설명해줘”는 계산이 아니라 chat/explanation 계열 intent로 분리해야 한다.

핵심 원칙:
- LLM은 계산을 하지 않는다.
- LLM은 의도 해석과 슬롯 추출만 한다.
- 구조 해석의 source of truth는 MolChat/PubChem/chemistry layer다.
- 출력은 구조화된 typed schema를 거쳐야 한다.
- free-form JSON 파싱 의존을 줄이고 structured output 경로를 우선한다.

반드시 구현할 것:
1. typed schema 정의
- 최소 모델:
  - PlanResponse
  - ClarificationForm
  - SlotMergeResult
  - ResultExplanation
- Step 1에서는 특히 PlanResponse를 완성도 높게 설계하라.
- 필수 필드 예시:
  - normalized_text
  - intent
  - job_type
  - structure_query
  - structures
  - method
  - basis
  - charge
  - multiplicity
  - orbital
  - esp_preset
  - focus_tab
  - confidence
  - confidence_band
  - missing_slots
  - needs_clarification
  - provider
  - fallback_reason
  - reasoning_notes

2. normalization layer 추가
- cheap deterministic cleanup 먼저 수행
- 오타, 붙여쓰기, 한글/영문 혼용, 약어를 처리
- molecule-like token과 task-like token을 분리
- 이온쌍 alias normalization을 지원
- 결과는 최소:
  - raw_text
  - normalized_text
  - candidate_queries
  - maybe_structure_hint
  - maybe_task_hint

3. Gemini planner 연결
- services/gemini_agent.py를 structured output 중심으로 재정리
- llm/agent.py의 QCVizAgent.plan()이 실제로 GeminiAgent.parse()를 메인 planner로 사용하게 만들어라
- Gemini 실패 시 heuristic fallback path로 내려가야 한다
- fallback reason이 로깅되고 결과에도 반영되게 하라

4. resolver 앞단 query planning
- structure_resolver.py에 raw query를 바로 넘기지 말고 normalized query planner를 거치게 하라
- MolChat 우선 경로를 유지하되 query quality를 개선하라
- candidate_queries를 단계적으로 시도할 수 있게 설계하라

5. compute route 호환성 유지
- compute route는 새 PlanResponse를 받아도 기존 runner를 깨지 말아야 한다
- 필요한 경우 adapter 계층을 추가하라

금지사항:
- Step 1에서 프론트 대수술을 하지 말 것
- Step 1에서 explanation/advisor UI까지 욕심내지 말 것
- 기존 compute runner 계약을 깨지 말 것
- Gemini output을 validation 없이 곧바로 신뢰하지 말 것

필수 테스트:
- typo normalization
- Korean molecule parsing
- ion pair parsing
- Gemini success path
- Gemini malformed output
- Gemini timeout/exception fallback
- structure_resolver query planning
- compute route compatibility
- 대표 입력 10개 snapshot

대표 입력 예시:
- 무ㄹ오비탈 계산
- 물 오비탈 계산
- 아세톤최적화
- 메탄 전하 보여줘
- emim tfsi esp
- EMIM+ TFSI- 에너지
- 물 설명해줘
- HOMO가 뭐야
- caffeine optimize
- benzene esp

테스트 도구:
- pytest
- pytest-asyncio
- httpx.AsyncClient
- respx 또는 동등한 mocking 도구

종료 기준:
- planner 관련 테스트 green
- Gemini가 없어도 heuristic degraded mode 동작
- 대표 입력 10개에 대한 parse snapshot이 안정화
- 다음 Step에서 clarification UX를 붙일 수 있을 정도로 schema와 state contract가 명확함

작업 완료 후 보고 형식:
1. planner 아키텍처 변경
2. schema 설계 요약
3. normalization 전략
4. Gemini/fallback 정책
5. 수정 파일 목록
6. 테스트 결과
7. 남은 리스크
```
