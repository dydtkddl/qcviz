# QCViz + MolChat Chatbot Flexibility Hardening

## Mission

당신은 처음 이 저장소들을 접하는 외부 LLM 코드/아키텍처 리뷰어다.  
목표는 **QCViz version03**과 **MolChat v3**를 함께 분석해서,

1. 왜 지금 챗봇이 사람다운 유연성을 보이지 못하는지 정확히 진단하고,  
2. MolChat과 더 잘 결합하면서,  
3. 필요할 때는 MCP/도구 호출도 더 책임 있게 쓰도록 만들고,  
4. 최종적으로는 **초안 수준이 아닌 실제 구현 가능한 최종 패치 설계안**을 내는 것이다.

이 작업은 절대 “아이디어 몇 개 제안”으로 끝나면 안 된다.  
반드시 **코드 경로 기반 분석 + 웹 기반 전수조사 + 최종 패치 설계**까지 완료하라.

---

## Attached Context

첨부 ZIP에는 QCViz와 MolChat의 관련 코드가 들어 있다.  
추가로 아래 deep scan 문서도 함께 들어 있거나 함께 제공된다.

- `DEEP_SCAN_REPORT_qcviz-mcp_2026-03-28.md`
- `DEEP_SCAN_REPORT_MolChat_v3_2026-03-28.md`

분석 시작 전에 첨부된 코드와 문서를 모두 읽고, 실제 코드 경로 기준으로 문제를 정의하라.

---

## What Is Going Wrong Now

현재 시스템은 계산 기능 자체보다 **대화형 인터페이스의 유연성**에서 크게 부족하다.

대표 증상:

1. `MEA알아?` 같은 입력을 보면,
   - 사용자의 의도는 “MEA라는 약어/분자에 대해 아느냐” 또는 “MEA가 무엇인지 설명해 달라”에 가깝다.
   - 그러나 시스템은 이를 대화 질문이 아니라 곧바로 계산 대상 구조 입력으로 승격시킨다.
   - 결과적으로 `structure_query = "MEA 알아?"` 같은 잘못된 값이 생기고,
   - MolChat / PubChem까지 원문 질문 텍스트를 그대로 던진 뒤 실패한다.

2. `TNT에 들어가는 주물질` 같은 서술형 입력은 어느 정도 semantic grounding이 되기 시작했지만,
   - 아직도 QCViz 내부 heuristics, MolChat 후보 사용 방식, clarification lifecycle, turn/job binding 사이 경계가 불안정하다.

3. 사용자는 더 “진짜 챗봇 같은” 상호작용을 기대한다.
   - 질문이면 설명을 해 주고,
   - 구조가 애매하면 자연스럽게 되묻고,
   - 약어면 후보를 정리해 주고,
   - 계산 요청이 확실할 때만 계산을 시작하고,
   - 계산이 시작되면 실제 도구 실행과 결과를 명확히 분리해야 한다.

4. 현재 구조는 여전히 너무 자주 다음과 같은 실패를 보인다.
   - raw question text가 molecule query로 승격됨
   - chat intent와 compute intent가 분리되지 않음
   - 약어 disambiguation이 약함
   - semantic descriptor 처리와 direct molecule resolution이 불안정함
   - MolChat의 장점을 QCViz가 충분히 소비하지 못함
   - “설명형 대화”와 “실제 계산 실행”의 경계가 명확하지 않음

---

## What We Actually Want

우리가 원하는 목표 상태는 아래와 같다.

### A. 챗봇처럼 유연하게 반응

- `MEA알아?`
  - 바로 계산하지 말 것
  - 우선 chat/disambiguation 흐름으로 처리할 것
  - 예: “MEA는 monoethanolamine을 의미할 수도 있고 methyl ethyl amine을 의미할 수도 있습니다. 어떤 것을 말하시나요?”

- `MEA의 HOMO 보여줘`
  - 계산 요청이 있으므로 compute intent로 갈 수 있음
  - 다만 약어가 애매하므로 먼저 후보를 제시해야 함

- `TNT에 들어가는 주물질`
  - semantic descriptor로 처리
  - MolChat에서 해석 후보를 받고
  - dropdown에는 사람이 이해하기 좋은 후보만 보여주고
  - 선택 후에는 바로 다음 단계로 가야 함

- `같은 분자 ESP도 보여줘`
  - 이전 구조 문맥을 재사용해야 함

### B. MolChat과 더 잘 결합

MolChat은 단순한 name search backend가 아니다.  
가능하다면 다음을 적극적으로 활용해야 한다.

- semantic interpretation
- molecule references
- search / resolve API
- chat endpoint가 이미 갖고 있는 대화형 분자 추론 능력
- query resolver / orchestrator 계층

즉, QCViz는 MolChat을 “그냥 이름 검색기”처럼 쓰지 말고,  
**의미 해석 + 분자 grounding + candidate generation** 파트너로 써야 한다.

### C. MCP / Tool Calling도 더 책임 있게

우리는 “LLM이 계산 결과를 지어내는” 시스템을 원하지 않는다.  
원하는 것은:

- LLM이 사용자 의도와 대화 상태를 해석
- 필요한 경우 적절한 툴/도구 호출 계획을 세움
- MolChat, resolver, compute engine, visualization, explanation을 명시적 단계로 오케스트레이션
- 실제 계산 결과와 설명용 텍스트를 엄격히 분리

여기서 “MCP를 잘 호출한다”는 말은 단순히 프로토콜 이름을 붙이라는 뜻이 아니다.  
다음이 필요하다.

- tool boundaries가 명확할 것
- tool input/output contract가 구조화되어 있을 것
- clarification-required 상태가 기계적으로 다룰 수 있을 것
- chat-only response와 compute-triggering response가 섞이지 않을 것

---

## Hard Constraints

다음 제약을 반드시 지켜라.

1. **사전 몇 개 추가** 같은 얕은 해결책으로 끝내지 마라.
   - ko_aliases, regex, heuristic만 더 늘리는 것은 부분 보완일 뿐 최종 해법이 아니다.

2. **“룰기반으로 조금 더 잘 처리”** 수준에 머물지 마라.
   - 우리는 conversational routing, semantic grounding, acronym disambiguation, tool orchestration까지 통합적으로 보길 원한다.

3. **실제 코드 경로를 추적**하라.
   - QCViz 쪽: user input → planner/normalizer → route orchestration → MolChat → resolver → compute → clarify/result UI
   - MolChat 쪽: query/chat/search/interpret/resolve/orchestrator 경로

4. **웹 기반 전수조사**를 반드시 수행하라.
   - 공식 문서
   - 관련 이슈
   - 기술 설계 레퍼런스
   - 화학 식별자 / molecular search / acronym disambiguation 관련 자료
   - MCP / tool calling / structured outputs 관련 공식 자료

5. 산출물은 **초안**이 아니라 **최종 패치 설계안**이어야 한다.
   - 파일별 변경 계획
   - 상태 전이 설계
   - API contract
   - 테스트 전략
   - 회귀 방지 포인트
   - 배포 순서

---

## Required Research Scope

반드시 아래 범위를 전수 조사하라.

### 1. MCP / Tool Calling / Structured Output

조사 목표:

- LLM이 conversational agent이면서도 deterministic tool orchestrator로 동작하려면 어떤 contract가 필요한가
- clarification_required / needs_more_info / action_plan / structured tool result를 어떻게 설계하는 게 좋은가
- OpenAI function calling / structured outputs / MCP official guidance에서 무엇을 참고해야 하는가

반드시 공식 문서와 1차 출처를 우선하라.

### 2. MolChat-like conversational molecule grounding

조사 목표:

- 자유문 질문에서 molecular entity를 뽑고
- semantic descriptor를 candidate molecules로 grounding하고
- acronym / alias / abbreviation ambiguity를 다루는 방법
- user intent가 “설명 요청”인지 “계산 요청”인지 분리하는 대화형 패턴

특히 다음 케이스를 다룰 수 있는 방향을 조사하라.

- `MEA알아?`
- `TNT에 들어가는 주물질`
- `니트로 벤젠`
- `베 ㄴ젠`
- `같은 분자 ESP도`

### 3. Chemical search and acronym disambiguation

조사 목표:

- PubChem, RDKit, name-to-structure, acronym expansion, chemical NER, entity linking
- “MEA”, “DMA”, “TNT” 같은 약어/약칭의 대화형 disambiguation UX
- 바로 계산에 들어가기 전에 어떤 질문을 던지는 게 가장 자연스럽고 안전한가

### 4. Conversational UX for scientific assistants

조사 목표:

- 언제 바로 답하고
- 언제 clarification을 띄우고
- 언제 candidate dropdown을 만들고
- 언제 계산을 시작해야 하는가

“실험 화학자가 쓰는 연구 도구”라는 맥락에 맞는 UX 관점으로 정리하라.

---

## Repositories And Code Paths To Analyze

아래 두 프로젝트를 함께 보라.

### QCViz version03

중점 경로:

- `src/qcviz_mcp/llm/`
- `src/qcviz_mcp/services/`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/app.py`
- `src/qcviz_mcp/web/static/chat.js`
- `src/qcviz_mcp/web/static/app.js`
- `src/qcviz_mcp/web/templates/index.html`
- 관련 테스트들

특히 확인할 것:

- `normalize_user_text`
- `extract_structure_candidate`
- `build_structure_hypotheses`
- MolChat client integration
- clarification form building
- websocket event lifecycle
- turn/job binding
- follow-up continuation logic
- semantic grounding / discovery / disambiguation mode 분기

### MolChat v3

중점 경로:

- `backend/app/routers/molecules.py`
- `backend/app/routers/chat.py`
- `backend/app/services/molecule_engine/query_resolver.py`
- `backend/app/services/molecule_engine/orchestrator.py`
- `backend/app/services/molecule_engine/pug_rest_resolver.py`
- `backend/app/schemas/molecule.py`
- `backend/app/schemas/chat.py`
- 관련 router wiring / main app

특히 확인할 것:

- 현재 QCViz가 무엇을 호출할 수 있고
- 무엇을 호출해야 더 좋아지는지
- `interpret`, `search`, `resolve`, `chat` 중 어느 경로가 어떤 의도에 맞는지
- Molecule references를 dropdown source로 직접 사용할 수 있는지

---

## What You Must Deliver

산출물은 아래 순서와 포맷을 따라라.

### 1. Executive Diagnosis

짧게 요약하지 말고, 아래를 명확히 적어라.

- 현재 시스템이 왜 챗봇처럼 느껴지지 않는가
- 왜 raw question이 molecule query로 오염되는가
- 왜 MolChat을 붙였는데도 여전히 경직적인가
- 어디가 architecture problem이고 어디가 heuristic problem인가

### 2. Failure Taxonomy

실패 유형을 체계적으로 분류하라.

예:

- Chat-vs-compute intent confusion
- Raw question promotion bug
- Acronym ambiguity mishandling
- Semantic grounding fallback failure
- Clarification UX failure
- Tool/result boundary ambiguity
- Follow-up context reuse mismatch

각 항목마다:

- trigger example
- root cause
- affected files
- why user trust breaks

를 적어라.

### 3. End-to-End Desired Architecture

다음의 target flow를 제안하라.

- User message
- Intent classification
- Entity grounding
- Clarification / disambiguation / direct answer
- Tool orchestration
- Compute execution
- Result explanation
- UI rendering

이 흐름을 ASCII diagram으로 그려라.

### 4. Final Patch Design

이게 가장 중요하다.

QCViz와 MolChat 각각에 대해:

- 어떤 파일을 바꿔야 하는지
- 어떤 함수/클래스를 추가/수정해야 하는지
- 어떤 API field를 새로 만들거나 바꿔야 하는지
- 어떤 상태 기계를 도입해야 하는지
- 어떤 heuristic은 유지하고 어떤 것은 제거해야 하는지
- 어디를 LLM reasoning에 맡기고 어디를 deterministic contract로 고정해야 하는지

를 **파일 단위로 상세히** 적어라.

### 5. MCP / Tool Integration Strategy

QCViz가 앞으로 더 chatbot-like 하면서도 계산 신뢰성을 잃지 않으려면:

- 실제 MCP protocol을 어디까지 적용할지
- 내부 tool abstraction만으로 충분한지
- MolChat / compute / visualize / explain을 어떻게 tool boundary로 나눌지

를 기술적으로 제안하라.

단, 추상 논의로 끝내지 말고 실제 코드 구조에 대응시켜라.

### 6. API Contract Proposal

아래 타입의 구조화 응답/상태를 제안하라.

- chat_response
- clarification_required
- candidate_list
- semantic_grounding_result
- compute_plan
- tool_result
- explain_only_response

JSON 예시까지 포함하라.

### 7. UX / Conversation Policy

아래 질문에 답하는 정책 문서를 작성하라.

- 언제 바로 대답할 것인가
- 언제 분자를 고르라고 물을 것인가
- 언제 계산을 시작할 것인가
- 언제 후보 dropdown을 띄울 것인가
- acronym은 어떤 방식으로 물을 것인가
- semantic descriptor는 어떻게 처리할 것인가

실험 화학자 사용성을 기준으로 제안하라.

### 8. Test Strategy

최소한 아래를 포함하라.

- unit tests
- API tests
- websocket tests
- playwright end-to-end tests
- regression cases

반드시 포함할 예시 케이스:

- `MEA알아?`
- `MEA의 HOMO 보여줘`
- `TNT에 들어가는 주물질`
- `니트로 벤젠`
- `같은 분자 ESP도`
- `벤젠의 HOMO를 보여줘` 뒤에 다른 질문을 했을 때 이전 결과가 섞이지 않는지

### 9. Migration / Deployment Plan

- MolChat 먼저 바꿔야 하는지
- QCViz 먼저 바꿔야 하는지
- backward compatibility는 어떻게 할지
- feature flag가 필요한지
- 운영 검증은 어떻게 할지

를 단계별로 정리하라.

### 10. Optional But Strongly Preferred

가능하다면 아래도 포함하라.

- file-by-file patch pseudo-diff
- exact new schema proposal
- websocket event contract proposal
- dropdown label simplification proposal
- chat intent classifier decision table

---

## Output Quality Bar

아래 수준을 만족해야 한다.

- shallow suggestion 금지
- “maybe”, “could”, “consider” 남발 금지
- 실제 코드 경로와 함수 이름을 찍어라
- 기존 코드가 왜 실패하는지 증명하라
- 새 설계가 왜 더 좋은지 설명하라
- 반례와 회귀 위험도 같이 적어라

이 작업의 목표는 “읽고 나면 바로 구현에 착수할 수 있는 최종 패치 설계서”를 얻는 것이다.

---

## Final Instruction

다시 강조한다.

이건 단순 리뷰 요청이 아니다.  
**QCViz를 더 유연한 분자 계산 챗봇으로 만들기 위한, MolChat 연동 중심의 최종 패치 설계 작업**이다.

절대 다음 수준에서 멈추지 마라.

- 사전 더 추가하세요
- regex 좀 고치세요
- fallback을 줄이세요
- intent 분류기를 넣으세요

그건 출발점일 뿐이다.  
반드시 **전체 구조를 재정렬한 최종 설계안**을 제출하라.
