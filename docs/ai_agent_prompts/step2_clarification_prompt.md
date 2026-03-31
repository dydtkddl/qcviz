# Step 2 Prompt: Dynamic Clarification and Multi-Turn UX

```text
당신은 이 프로젝트의 Step 2 담당 엔지니어다.
이번 Step의 목표는 planner가 만든 typed contract 위에 동적 clarification UX와 멀티턴 세션을 구현하는 것이다.

프로젝트 루트:
- /mnt/d/20260305_양자화학시각화MCP서버구축/version03

전제:
- Step 1에서 PlanResponse, normalization, fallback contract가 정리되었다고 가정한다.
- 이번 Step에서는 고정 폼이 아니라 필요한 슬롯만 묻는 인터랙션을 만든다.
- UI는 LLM-generated HTML이 아니라 schema-driven skeleton renderer를 사용해야 한다.

집중 대상 파일:
- src/qcviz_mcp/web/routes/chat.py
- src/qcviz_mcp/web/routes/compute.py
- src/qcviz_mcp/web/static/chat.js
- src/qcviz_mcp/web/static/app.js
- src/qcviz_mcp/web/templates/index.html
- 필요 시 state/schema 보강 파일

Step 2 최종 목표:
- 사용자의 자유 입력에서 부족한 슬롯만 동적으로 질문
- 후속 사용자 답변을 기존 plan에 merge
- 멀티턴 상태를 유지하면서 중복 질문을 방지
- 실제 웹 UI에서 자연스럽게 동작

반드시 구현할 것:
1. ClarificationForm orchestration
- planner 결과의 missing_slots, confidence_band, ambiguity 정보를 기반으로 질문 생성
- 질문 수는 최소화
- confidence가 높고 필수 슬롯이 충분하면 질문 없이 실행 가능해야 함
- needs_clarification이 true일 때만 폼을 띄움

2. 허용 field type 제한
- 다음 type만 허용:
  - text
  - radio
  - select
  - number
  - checkbox
- LLM이 임의의 새 field type을 만들면 안 된다
- field type 결정은 서버 로직 또는 whitelist 기반으로 제한하라

3. session state 도입
- 최소 상태:
  - session_id
  - prior_plan
  - asked_fields
  - slot_values
  - ready_to_execute
  - last_user_message
- 이미 물어본 필드는 다시 묻지 말 것
- 이전 답변으로 채워진 슬롯은 유지할 것

4. slot merge 구현
- 사용자 후속 답변을 기존 plan에 merge
- merge 후 still_missing_slots 계산
- 준비되면 compute 실행
- 여전히 비어 있으면 다음 clarification으로 넘어감

5. 프론트 renderer 구현
- chat.js / app.js / index.html에서 schema-driven form renderer를 구현
- 서버 JSON contract만 보고 skeleton component를 렌더링
- UI는 심플해도 되지만 일관되어야 함
- radio/select/number/text/checkbox 처리
- submit 후 session merge 요청

6. websocket/REST 일관성
- websocket chat과 REST 경로가 동일한 clarification contract를 사용해야 한다
- protocol drift를 만들지 말 것

대표 시나리오:
1.
User: “무ㄹ오비탈 계산”
System:
- normalize -> water orbital calculation
- parse -> orbital_preview, structure=water
- missing_slots -> orbital target
- form -> HOMO/LUMO/both
User: “HOMO”
System:
- merge
- ready_to_execute=true
- compute 실행

2.
User: “emim tfsi esp”
System:
- ion pair candidate 감지
- charge/multiplicity 필요하면 질문
- 답변 merge 후 실행

3.
User: “5개 원자 분자 오비탈”
System:
- structure 미정
- molecule candidate suggestion 또는 선택형 clarification

4.
User: “물”
System:
- intent가 불명확하면 계산보다 clarification 또는 conversational suggestion

금지사항:
- 프론트를 LLM-generated markup에 의존하지 말 것
- 매 요청마다 고정 폼 전체를 보여주지 말 것
- 세션 merge 없이 새 plan을 매번 처음부터 다시 만들지 말 것
- 사용자 입력이 애매한데 무리하게 계산부터 시작하지 말 것

필수 테스트:
- clarification generation unit tests
- slot merge unit tests
- duplicate-question prevention
- websocket integration tests
- REST/session flow tests
- Playwright E2E:
  - 무ㄹ오비탈 계산 -> orbital 선택 -> 실행
  - emim tfsi esp -> ion pair clarification -> 실행
  - ambiguity candidate selection
  - Gemini fallback clarification

종료 기준:
- 실제 웹 UI에서 동적 질문이 JSON schema 기반으로 렌더링됨
- 대표 자연어 5개 이상이 브라우저에서 끝까지 동작
- 멀티턴 후 compute 실행 성공
- 중복 질문이 발생하지 않음

작업 완료 후 보고 형식:
1. clarification architecture
2. session state design
3. renderer 구현 요약
4. websocket/REST contract 설명
5. 수정 파일 목록
6. 테스트 결과
7. 남은 UX 리스크
```
