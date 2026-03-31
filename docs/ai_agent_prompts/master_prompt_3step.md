# Master Prompt: Gemini + MolChat 3-Step Refactor

```text
당신은 Python/FastAPI/LLM orchestration/interactive scientific UX/production testing에 강한 시니어 엔지니어다.
지금부터 아래 프로젝트를 직접 분석하고, Gemini + MolChat 중심의 AI-native quantum chemistry workflow로 고도화하라.

프로젝트 루트:
- /mnt/d/20260305_양자화학시각화MCP서버구축/version03

핵심 전제:
- MolChat API는 반드시 유지하고 적극 활용한다.
- Gemini도 반드시 사용한다.
- 하지만 LLM이 계산 엔진을 대체하면 안 된다.
- PySCF 계산, 구조 해석의 최종 truth source는 기존 chemistry stack이어야 한다.
- LLM은 orchestration layer로 사용해야 한다.
- 즉 LLM의 역할은 입력 정규화, 의도 파싱, 슬롯 추출, 동적 clarification, 결과 설명, advisor 오케스트레이션이다.

현재 프로젝트에서 파악된 사실:
- 웹 메인 경로는 FastAPI 기반이다.
- 핵심 경로는 대체로 다음과 같다.
  - src/qcviz_mcp/web/routes/chat.py
  - src/qcviz_mcp/web/routes/compute.py
  - src/qcviz_mcp/llm/agent.py
  - src/qcviz_mcp/services/gemini_agent.py
  - src/qcviz_mcp/services/structure_resolver.py
  - src/qcviz_mcp/services/ion_pair_handler.py
  - src/qcviz_mcp/services/molchat_client.py
  - src/qcviz_mcp/services/pubchem_client.py
  - src/qcviz_mcp/web/advisor_flow.py
  - src/qcviz_mcp/llm/bridge.py
  - src/qcviz_mcp/compute/pyscf_runner.py
  - src/qcviz_mcp/web/static/chat.js
  - src/qcviz_mcp/web/static/results.js
  - src/qcviz_mcp/web/templates/index.html
- Gemini는 일부 이미 사용 중이지만, services/gemini_agent.py 의 function/structured parsing 경로가 메인 planner로 완전히 연결되어 있지 않다.
- MolChat은 메인 structure resolution 경로에서 이미 중요하게 사용되고 있다.
- 이 repo는 웹 경로와 레거시 경로가 공존하므로, 핵심 웹 경로를 중심으로 점진 통합해야 한다.

최종 목표:
사용자가 오타 섞인 자연어로 요청해도
1. 분자/작업 의도를 이해하고
2. 필요한 정보만 최소 질문으로 받아내고
3. MolChat/PySCF/advisor를 오케스트레이션하여 계산을 실행하고
4. 결과를 사람이 이해 가능한 설명과 다음 액션 추천까지 포함해 반환하는
AI-native quantum chemistry workflow를 완성하라.

대표 성공 예시:
- “무ㄹ오비탈 계산” -> water, orbital_preview로 이해하고 orbital만 동적 질문
- “아세톤최적화” -> acetone, geometry_optimization
- “emim tfsi esp” -> ion pair 해석 + esp_map
- “메탄 전하 보여줘” -> methane + partial_charges
- “물 설명해줘” -> compute가 아니라 chat/explanation intent

기술 원칙:
- Gemini SDK는 공식 google-genai를 우선 사용하라.
- Gemini 메인 모델은 gemini-2.5-flash를 우선, 고난도 parser/escalation은 gemini-2.5-pro를 선택 가능하게 설계하라.
- 출력은 free-form text가 아니라 구조화된 schema를 거쳐야 한다.
- Pydantic v2 또는 동등한 typed model을 사용하라.
- UI는 LLM이 직접 HTML을 생성하지 않고, 서버가 반환한 typed form schema를 기존 프론트의 skeleton renderer가 렌더링해야 한다.
- fallback 경로는 반드시 유지하라.
- Gemini 실패 시 heuristic path로 degraded mode가 가능해야 한다.
- 기존 compute API 계약은 불필요하게 깨지 말 것.

해야 할 일은 반드시 3 Step으로 나눠서 진행하라.

Step 1. Planner 코어와 입력 정규화 계층 정비
목표:
- Gemini를 실제 메인 planner로 연결
- 자유입력을 robust하게 normalize
- typed plan contract를 확정
세부 작업:
- llm/schemas.py 신설 후 최소 다음 모델 정의:
  - PlanResponse
  - ClarificationForm
  - SlotMergeResult
  - ResultExplanation
- llm/normalizer.py 신설 후 다음 처리:
  - 오타
  - 붙여쓰기
  - 한글/영문 혼용
  - 약어 확장
  - 이온쌍 canonicalization
  - molecule-like token / task-like token 분리
- services/gemini_agent.py를 structured output 중심으로 재설계
- llm/agent.py 의 QCVizAgent.plan()이 실제로 GeminiAgent.parse()를 메인으로 사용하게 연결
- planner 출력에 최소 다음 필드 포함:
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
  - missing_slots
  - needs_clarification
  - provider
  - fallback_reason
- structure_resolver 앞단에 normalized query planner 추가:
  - raw_query
  - normalized_query
  - candidate_queries[]
- compute route가 새 plan을 받아도 기존 runner 경로와 호환되도록 adapter 작성
Step 1 검증:
- pytest unit + integration
- Gemini mock success/failure tests
- MolChat query normalization tests
- compute route compatibility tests
- 대표 입력 10개 snapshot tests
Step 1 종료 기준:
- planner 관련 테스트 모두 green
- Gemini 실패 시도 시스템이 죽지 않음
- 대표 입력 10개가 안정적으로 구조화됨

Step 2. 동적 Clarification UX와 멀티턴 세션
목표:
- 고정 폼이 아니라 필요한 슬롯만 질문
- 멀티턴 대화에서 답변 merge 후 실행
세부 작업:
- chat.py 에 clarification orchestration 추가
- 세션 상태 모델 도입:
  - prior_plan
  - asked_fields
  - slot_values
  - ready_to_execute
- ClarificationForm 생성기 구현
- 허용 field type은 다음만 사용:
  - text
  - radio
  - select
  - number
  - checkbox
- LLM은 질문 내용과 필요한 field만 정하고, 렌더링은 프론트 skeleton이 수행
- 후속 사용자 답변을 기존 plan에 merge하는 slot merge 로직 구현
- 중복 질문 방지
- ambiguity가 높을 때만 질문하고, confidence가 높고 필수 슬롯이 충분하면 자동 실행
- chat.js / app.js / index.html 에 schema-driven form renderer 추가
- websocket/REST 양쪽에서 동일 contract 사용
Step 2 검증:
- clarification generation tests
- slot merge tests
- websocket tests
- Playwright E2E:
  - “무ㄹ오비탈 계산” -> orbital 선택 -> 실행
  - “emim tfsi esp” -> ion pair 처리 -> 실행
  - ambiguity molecule selection flow
  - Gemini fallback flow
Step 2 종료 기준:
- 실제 웹에서 대표 자연어 5개 이상이 동작
- 동적 질문이 JSON schema 기반으로 렌더링
- 후속 답변 merge 후 compute 실행이 된다

Step 3. 결과 해설, advisor 자연통합, 운영 수준 하드닝
목표:
- 결과를 사람이 이해 가능하게 설명
- advisor를 workflow 안으로 통합
- 회귀/실서버 테스트까지 완성
세부 작업:
- ResultExplanation 생성기 구현:
  - summary
  - key_findings[]
  - interpretation[]
  - cautions[]
  - next_actions[]
- orbital, esp, charges, geometry, optimization 별 explanation templates와 Gemini narrative 결합
- results.js 에 explanation panel 렌더링
- SCF/optimization 진행 및 완료 시 convergence chart를 렌더링
- HOMO/LUMO energy, total energy, orbital gap, ESP range 등 주요 수치는 UI에서 단위 변환이 가능하게 설계
- payload에는 가능한 한 Hartree/eV/kcal/mol 같은 원시값과 파생값을 함께 유지
- advisor_flow.py / llm/bridge.py 정리:
  - 목적 기반 preset 추천
  - methods/script/literature/confidence 결과를 자연스럽게 연결
  - focus_tab 자동 조정
- 실패 복구 UX:
  - 구조 해석 실패 이유 설명
  - 후보 분자 제안
  - 재시도/clarification 옵션
- observability 추가:
  - planner latency
  - Gemini success ratio
  - fallback ratio
  - MolChat resolution success ratio
- live smoke tests 추가:
  - 실제 Gemini
  - 실제 MolChat
  - 실제 브라우저 E2E
Step 3 검증:
- pytest full suite
- pytest -m live
- playwright test
- 기존 compute 결과 구조 회귀 검증
Step 3 종료 기준:
- 결과 설명과 next action이 실제 UI에 표시
- advisor가 자연어 workflow 안에서 동작
- live smoke까지 통과

테스트 원칙:
- unit, integration, mocked external, live external, browser E2E를 분리하라.
- 외부 API 없는 환경에서도 대부분의 테스트가 돌아야 한다.
- live test는 marker 또는 env flag 뒤에 둬라.
- pytest-asyncio, httpx.AsyncClient, respx, playwright를 적절히 활용하라.
- 기존 테스트가 있으면 최대한 재사용하되, 새 contract 기반 테스트를 추가하라.

필수 테스트 케이스:
- typo normalization
- Korean molecule parsing
- ion pair parsing
- clarification generation
- slot merge
- duplicate-question prevention
- Gemini malformed/timeout fallback
- MolChat happy path
- PubChem fallback
- result explanation schema validation
- advisor happy path
- SCF convergence data propagation
- unit conversion display regression
- browser E2E end-to-end success

금지사항:
- LLM이 계산값을 fabricated output으로 생성하는 것
- validation 없이 model output을 그대로 신뢰하는 것
- preview 모델을 메인 프로덕션 경로에 하드코딩하는 것
- LLM-generated HTML에 UI를 의존하는 것
- Gemini 실패 시 전체 경로가 붕괴되는 것
- 사용자 기존 계약을 깨는 대규모 파괴적 변경

작업 방식:
- 먼저 코드베이스를 실제로 스캔하라.
- 각 Step 시작 전에 현재 구조와 수정 전략을 5~10줄로 요약하라.
- 구현은 작은 단위 커밋 가능 상태로 유지하라.
- 각 Step 종료 시 테스트 결과와 남은 리스크를 문서화하라.
- 예상 밖의 레거시 충돌이 나오면 핵심 웹 경로 우선 원칙으로 정리하라.

최종 보고 형식:
1. 핵심 변경 요약
2. 아키텍처 변경 설명
3. 수정/추가 파일 목록
4. 테스트 실행 결과
5. live smoke 결과
6. 남은 리스크 및 후속 권장사항

작업 완료 정의:
- 자유입력 -> 구조화 plan
- plan -> 필요한 질문만 동적 생성
- 질문 응답 -> slot merge -> 계산 실행
- 계산 결과 -> explanation + next actions + advisor
- pytest + integration + live + browser E2E까지 검증 완료

지금 해야 할 첫 행동:
- 코드베이스를 직접 읽고
- 현재 planner, chat flow, compute flow, structure resolver, advisor flow, frontend rendering 구조를 요약하고
- Step 1부터 실제 코드 수정과 테스트를 시작하라.
```
