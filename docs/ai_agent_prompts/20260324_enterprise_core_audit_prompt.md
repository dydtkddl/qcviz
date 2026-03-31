# 2026-03-24 Enterprise Core Audit Prompt for QCViz-MCP

## 사용 목적

이 문서는 다른 LLM/AI Agent에게 **QCViz-MCP 프로젝트 전체의 핵심 구조를 정확히 파악시키고**,  
현재까지 반복적으로 발생하는 구조적 문제를 **단순 버그 패치가 아니라 엔터프라이즈급 아키텍처 관점에서 진단하고 해결책을 설계**하게 하기 위한 장문 작업지시 프롬프트이다.

이 프롬프트를 사용할 때는 아래에 명시된 **코어 파일들을 가능한 한 모두 첨부**하라.  
길어져도 상관없다. 중요한 것은 **부분적인 코드 조각이 아니라, 시스템 전체의 연결관계와 책임분산 실패를 이해하게 하는 것**이다.

---

## 다른 LLM에게 전달할 작업지시 프롬프트

```md
당신은 Python/FastAPI/LLM orchestration/quantum chemistry workflow/enterprise architecture/code audit에 강한 시니어 엔지니어이자 소프트웨어 아키텍트다.

지금부터 첨부되는 QCViz-MCP 프로젝트의 핵심 파일들을 전부 읽고, 이 프로젝트의 구조와 현재 문제점을 깊이 진단하라.

중요:
- 표면적인 버그 몇 개를 지적하는 수준으로 끝내면 안 된다.
- 이 프로젝트는 이미 상당한 기능을 갖췄지만, 구조적으로 일관되지 않아서 기본적인 분자명 해석과 resolver UX조차 반복적으로 흔들리고 있다.
- 따라서 당신의 임무는 단순 리뷰가 아니라, **현재 시스템의 코어 컨셉을 먼저 파악하고**, **왜 이런 문제가 반복되는지 구조적으로 진단한 뒤**, **엔터프라이즈급 해결책을 설계하는 것**이다.

---

# 0. 반드시 먼저 파악할 것: 이 프로젝트의 코어 컨셉

이 프로젝트는 단순 계산 스크립트가 아니다. 아래 요소들이 하나의 시스템으로 얽혀 있다.

- Gemini 기반 자연어 의도 해석 / 슬롯 추출 / clarification
- MCP 스타일 도구 호출 및 tool orchestration
- PySCF 기반 양자화학 계산 엔진
- MolChat 기반 구조 해석 / 카드 / 3D 생성
- PubChem fallback
- Web UI + Chat UI + Results UI + Viewer UI
- WebSocket 기반 progress streaming
- Redis/arq 기반 split web/worker 백엔드
- session/auth/quota/admin dashboard
- advisor / explanation / preset recommendation

즉 이 프로젝트의 핵심은:

1. 사용자의 거친 자연어 입력을  
2. 계산 가능한 구조화된 intent/payload로 바꾸고  
3. 구조를 정확히 해석하고  
4. PySCF 계산을 실행하고  
5. 결과를 시각화/해설하며  
6. 여러 사용자 환경에서도 안정적으로 운영되는  
AI-native quantum chemistry workflow를 제공하는 것이다.

당신은 먼저 이 프로젝트를 다음 관점에서 **짧고 명확하게 재정의**하라.

- 제품 관점에서 이 시스템은 무엇인가
- 기술 관점에서 이 시스템은 어떤 계층으로 구성되는가
- LLM, MolChat, PubChem, PySCF, Web UI, Worker가 각각 무슨 역할을 맡아야 하는가
- 지금 구조가 원래 의도한 책임분리를 얼마나 잘 지키고 있는가

---

# 1. 반드시 진단해야 할 현재 핵심 문제

현재 이 프로젝트에는 아래와 같은 증상이 반복적으로 나타난다.

## 대표 실패 사례

### 사례 A
- 입력: `메틸아민`
- 기대: `methylamine`으로 인식되어 바로 계산
- 실제: structure_query를 못 잡고 custom clarification 또는 resolve failure로 빠짐

### 사례 B
- 입력: `CH3COOH (acetic acid)`
- 기대: formula+name 혼합 표현을 canonical structure query로 정리해서 해석
- 실제: `'CH3COOH (acetic acid)' 구조를 찾을 수 없습니다` 식으로 통짜 문자열을 resolver에 넘기고 실패

### 사례 C
- 이전 대화에서 `benzene HOMO` 계산을 완료했는데,
- 후속 대화로 `ESP도 그려줘`라고 하면
- 기대: 이전 session context의 분자가 benzene이라는 사실을 기억해 `benzene ESP`로 이어가야 함
- 실제: context carry-over가 약해서 다시 분자를 묻거나 generic clarification으로 빠질 수 있음

### 사례 D
- bare molecule input, Korean alias, English common name, formula+name, ion pair, abbreviation, translated alias가
- 서로 다른 경로에서 따로따로 처리되어
- 어떤 입력은 planner에서는 잡히고 resolver에서는 실패하거나,
- 어떤 입력은 resolver candidate suggestion은 되는데 planner structure_query가 null이 되는 식의 불일치가 발생함

### 사례 E
- alias dictionary / molecule normalization / resolver candidate planning / fallback extraction / builtin aliases가
- 여러 파일에 중복되어 존재함
- 따라서 한 곳을 고쳐도 다른 경로는 계속 실패함

당신은 위 사례들을 단순 개별 버그가 아니라 **공통 구조 결함의 증상**으로 보아야 한다.

---

# 2. 당신의 핵심 임무

당신은 아래 세 가지를 반드시 수행하라.

## 2-1. 현재 시스템의 코어 컨셉을 재정리

아래를 명확히 설명하라.

- 이 시스템의 본질적 제품 목표
- 사용자 입력부터 계산/결과까지의 end-to-end dataflow
- 각 주요 모듈의 책임
- 지금 시스템에서 “source of truth”가 어디에 있어야 하는지
  - molecule alias source of truth
  - structure canonicalization source of truth
  - task planning source of truth
  - result contract source of truth
  - job state / queue source of truth

## 2-2. 아직까지 많은 문제를 일으키는 제대로 구현되지 않은 부분을 꼼꼼히 진단

아래 관점으로 빠짐없이 분석하라.

### A. 입력 정규화 / alias / canonicalization
- 한국어 분자명
- common English names
- formula aliases
- formula + parenthetical name patterns
- unicode subscript / superscript
- charge notation
- ion pair notation
- human description + chemical name 혼합 입력
- LLM plan output과 resolver input 사이의 canonicalization 불일치

### B. planner-resolver contract
- plan.structure_query는 언제 null이 되는가
- planner가 잡은 structure_query를 resolver가 왜 실패하는가
- explicit structure input과 discovery/disambiguation이 왜 혼동되는가
- “입력한 이름 그대로 사용”과 “resolver-grounded candidate”가 어떤 규칙으로 선택되어야 하는가

### C. clarification UX
- no_structure / disambiguation / discovery / multiple_molecules / missing_orbital 분기 기준이 타당한가
- clarification이 왜 generic candidate picker로 자꾸 흐르는가
- 이전 session context를 활용한 follow-up 해석이 왜 약한가

### D. duplicated knowledge / logic drift
- ko_aliases.py
- llm/normalizer.py
- compute/pyscf_runner.py
- chat.py local suggestion catalog
- structure_resolver.py abbreviation / synonym logic
- fallback_extract_structure_query

위 파일들에 분산된 지식이 서로 어떻게 drift하는지 분석하라.

### E. resolver pipeline robustness
- MolChat resolve/card/generate-3d 호출 순서가 타당한가
- PubChem fallback 설계가 안정적인가
- 왜 formula+name concatenation 같은 입력을 통짜로 보내는가
- raw_query / translated_query / normalized_query / candidate_queries 설계가 충분한가
- resolver suggestion과 actual resolve pipeline이 같은 canonicalization 규칙을 쓰는가

### F. session memory / conversational continuity
- previous computed structure를 follow-up prompt가 제대로 재사용하는가
- “ESP도”, “LUMO도”, “basis 바꿔서 다시” 같은 후속 발화를 plan merge할 준비가 되어 있는가
- session state와 planner state가 분리/중복/유실되는 지점을 찾아라

### G. Web/UI/worker operational integrity
- web / compute / worker / queue / progress / result streaming 구조가 일관적인가
- retry / requeue / stale recovery / heartbeat가 resolver/planner failures와 어떻게 상호작용하는가
- 실제 사용자 입장에서 어떤 실패가 “버그”가 아니라 “구조적 불신”으로 느껴지는가

## 2-3. 해결책을 엔터프라이즈급으로 강구

반드시 다음 수준으로 제안하라.

- “여기 alias 몇 개 추가하면 됩니다” 수준 금지
- “정규화 계층을 단일 source of truth로 분리하고, planner/resolver/chat/fallback이 모두 그것을 참조한다” 수준의 구조 개편 필요
- 아키텍처/계약/테스트/운영까지 포함해야 함

당신은 해결책을 아래 4층으로 설계하라.

### Layer 1. Canonicalization Core
- 입력 정규화
- unicode normalization
- formula-name decomposition
- alias translation
- synonym registry
- explicit vs discovery classification

### Layer 2. Structure Resolution Orchestrator
- raw user text
- canonical structure request
- candidate expansion
- MolChat attempt plan
- PubChem fallback plan
- charge-aware validation
- formula-aware heuristics

### Layer 3. Conversation & Clarification State
- prior structure memory
- follow-up intent inheritance
- slot merge
- clarification policy
- “do not ask again if already known”

### Layer 4. Operational Contract & Testing
- deterministic schemas
- regression tests
- resolver eval set
- alias coverage tests
- conversational continuity tests
- worker/queue/progress integrity tests

---

# 3. 반드시 첨부해서 읽어야 할 파일 목록

아래 파일들은 가능한 한 **전부 첨부**하라.

## A. App / Server Entry
- `src/qcviz_mcp/app.py`
- `src/qcviz_mcp/config.py`
- `src/qcviz_mcp/observability.py`
- `src/qcviz_mcp/web/app.py`

## B. Chat / Compute Core Routes
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/web/routes/compute.py`

## C. LLM / Planning / Normalization
- `src/qcviz_mcp/llm/agent.py`
- `src/qcviz_mcp/llm/bridge.py`
- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/llm/schemas.py`
- `src/qcviz_mcp/services/gemini_agent.py`

## D. Structure Resolution Core
- `src/qcviz_mcp/services/ko_aliases.py`
- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`
- `src/qcviz_mcp/services/ion_pair_handler.py`
- `src/qcviz_mcp/services/sdf_converter.py`

## E. Compute Core
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `src/qcviz_mcp/compute/job_manager.py`
- `src/qcviz_mcp/compute/disk_cache.py`
- `src/qcviz_mcp/compute/safety_guard.py`

## F. Worker / Queue / Runtime
- `src/qcviz_mcp/web/job_backend.py`
- `src/qcviz_mcp/web/arq_backend.py`
- `src/qcviz_mcp/web/redis_job_store.py`
- `src/qcviz_mcp/worker/arq_worker.py`
- `src/qcviz_mcp/web/session_auth.py`
- `src/qcviz_mcp/web/auth_store.py`

## G. Advisor / Explanation Layer
- `src/qcviz_mcp/web/advisor_flow.py`
- `src/qcviz_mcp/web/result_explainer.py`
- `src/qcviz_mcp/tools/advisor_tools.py`
- `src/qcviz_mcp/advisor/preset_recommender.py`
- `src/qcviz_mcp/advisor/methods_drafter.py`
- `src/qcviz_mcp/advisor/script_generator.py`
- `src/qcviz_mcp/advisor/literature_validator.py`
- `src/qcviz_mcp/advisor/confidence_scorer.py`

## H. MCP / Tool Surface
- `src/qcviz_mcp/mcp_server.py`
- `src/qcviz_mcp/tools/core.py`
- `src/qcviz_mcp/tools/health.py`
- `src/qcviz_mcp/backends/registry.py`
- `src/qcviz_mcp/backends/pyscf_backend.py`
- `src/qcviz_mcp/backends/viz_backend.py`

## I. Frontend Core
- `src/qcviz_mcp/web/templates/index.html`
- `src/qcviz_mcp/web/static/app.js`
- `src/qcviz_mcp/web/static/chat.js`
- `src/qcviz_mcp/web/static/results.js`
- `src/qcviz_mcp/web/static/viewer.js`
- `src/qcviz_mcp/web/static/style.css`

## J. Existing context / docs worth reading
- `docs/20260320_전체기능_정성설명서.md`
- `docs/20260321_structure_clarification_issue_dossier.md`
- `docs/20260321_web_worker_split_runtime_status.md`
- `docs/20260321_queue_eta_recovery_admin.md`
- `docs/20260321_arq_worker_activation.md`

## K. Tests to inspect for drift / missing coverage
- `tests/test_structure_extraction.py`
- `tests/test_chat_api.py`
- `tests/test_compute_api.py`
- `tests/test_redis_job_store.py`
- `tests/test_admin_api.py`
- `tests/test_arq_worker.py`
- `tests/test_web_server_smoke.py`
- `tests/v3/unit/test_structure_resolver.py`
- `tests/v3/integration/test_chat_routes.py`
- `tests/v3/integration/test_compute_routes.py`

---

# 4. 반드시 포함해야 할 분석 산출물

아래 산출물을 반드시 순서대로 작성하라.

## Output A. Executive Summary
- 이 시스템이 무엇인지 10줄 이내 요약
- 현재 가장 치명적인 구조적 문제 5개
- 왜 기본적인 입력조차 자주 실패하는지 한 문장 요약

## Output B. Core Concept Map
- 컴포넌트별 역할
- 데이터 흐름
- source of truth map

## Output C. Problem Lookup Table
반드시 표로 작성:

| 문제 ID | 증상 | 실제 근본원인 | 관련 파일 | 왜 반복되는가 | 영향도 | 우선순위 |
|---|---|---|---|---|---|---|

## Output D. Cross-File Drift Map
반드시 표로 작성:

| 개념 | 현재 중복 구현 위치 | 서로 불일치하는 내용 | 통합해야 할 정답 위치 |
|---|---|---|---|

예:
- Korean alias dictionary
- formula normalization
- structure extraction heuristic
- resolver candidate suggestions
- follow-up context inheritance
- retry / worker heartbeat / job state

## Output E. Architecture Defect Report
아래 주제를 각 1~3문단씩 깊게 설명:

1. planner-resolver contract failure
2. canonicalization source-of-truth 부재
3. clarification policy의 구조적 결함
4. session memory / follow-up intent inheritance 부족
5. worker/runtime는 개선됐지만 domain normalization은 여전히 파편화되어 있는 문제

## Output F. Enterprise-Grade Fix Plan
반드시 단계별로 작성:

### Phase 1. Stabilization
- 지금 당장 깨지는 핵심 입력군 복구
- alias/formula/parser drift 제거
- regression test 보강

### Phase 2. Contract Unification
- planner/resolver shared canonicalization layer
- shared typed schema
- single source of truth 도입

### Phase 3. Conversational Intelligence
- follow-up memory
- prior structure inheritance
- action chaining
- clarification minimization

### Phase 4. Operational Hardening
- eval suite
- failure analytics
- resolver telemetry
- admin observability
- safe retry / stale recovery policy 정교화

## Output G. Concrete Refactor Proposal
반드시 포함:

- 새 모듈 제안
- 없애야 할 중복 로직
- 이동해야 할 로직
- 호환성을 깨지 않는 migration strategy
- 테스트 매트릭스

## Output H. “If I were to fix this repo next” Plan
실행 가능한 작업 티켓 15~30개로 쪼개라.
각 티켓은 다음을 포함:

- 티켓명
- 목적
- 수정 파일
- 리스크
- 테스트
- 완료 기준

---

# 5. 절대 하면 안 되는 것

- alias 몇 개 더 넣자는 수준에서 끝내지 말 것
- MolChat이 죽었다고 가정하고 넘기지 말 것
- Gemini prompt만 바꾸면 된다고 단순화하지 말 것
- 구조적 중복을 무시한 채 “각 파일 조금씩 수정”으로 끝내지 말 것
- 현재 구현이 이미 가지고 있는 세션/worker/admin/runtime 복잡성을 과소평가하지 말 것

---

# 6. 가장 중요한 한 줄

이 프로젝트의 문제는 “기본 분자명을 몇 개 못 알아듣는 것”이 아니라,  
**입력 정규화, planner, resolver, clarification, follow-up memory의 source of truth가 분산되어 있어서 같은 개념이 여러 곳에서 서로 다르게 해석되는 구조적 결함**이라는 점을 중심으로 진단하라.
```

---

## 사용 메모

- 이 프롬프트는 **코드 수정 요청 전용**이 아니라, 먼저 **엔터프라이즈급 아키텍처 진단**을 뽑아내기 위한 것이다.
- 즉, 다른 LLM에게 바로 “수정해”라고 하기 전에, 먼저 이 프롬프트로 **정확한 문제정의와 해결 설계**를 받는 용도다.
- 이후 그 결과를 바탕으로 별도의 구현 프롬프트를 만드는 것이 좋다.

