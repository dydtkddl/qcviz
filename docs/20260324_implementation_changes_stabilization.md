# QCViz-MCP Immediate Stabilization Implementation Changes

## 목적

이 문서는 2026-03-24 기준으로 QCViz-MCP의 즉시 안정화 작업에서
"이전 방식이 어떻게 동작했고, 지금은 무엇이 어떻게 바뀌었는지"를
구현 중심으로 설명한다.

대상 문제는 다음과 같다.

- `CH3COOH (acetic acid)` 같은 formula + alias mixed input 실패
- `Biphenyl`, `메틸아민`, `아세트산` 같은 명시적 분자명도 generic clarification으로 빠지는 문제
- `벤젠 HOMO -> ESP도` 같은 follow-up continuity 실패
- `TFSI-`, `EMIM TFSI`, `LiTFSI` 같은 charge / ion pair / salt 처리 불안정
- planner가 이해한 semantic metadata가 route와 resolver 단계에서 사라지는 문제

이 문서는 전면 재설계 문서가 아니다. 현재 코드에서 실제로 바뀐 즉시 안정화 구현을 설명한다.

---

## 1. 핵심 결론

이전 구현의 본질적인 문제는 `structure_query: str` 한 필드가 사실상 유일한 중간 truth였다는 점이다.
입력이 planner, normalizer, route, resolver를 거치는 동안 "분자 의미"가 유지되지 않고,
각 단계가 다시 raw string을 재해석했다.

이번 변경의 핵심은 다음 네 가지다.

1. mixed input을 raw string이 아니라 decomposition 결과로 다루기 시작했다.
2. planner/heuristic 결과에 semantic metadata를 붙여 route가 이를 보존하게 했다.
3. session 단위 continuation state를 추가해 follow-up을 fresh request가 아니라 continuation으로 처리하기 시작했다.
4. resolver query를 raw literal first가 아니라 canonical candidate ordering으로 바꿨다.

---

## 2. 이전 구현 방식

## 2.1 String-first 구조

이전 구현은 입력 구조를 대체로 아래처럼 처리했다.

1. user message
2. `extract_structure_candidate()`
3. `structure_query: str`
4. route fallback merge
5. resolver / PySCF runner

문제는 이 흐름에서 중간 표현이 거의 항상 문자열 하나였다는 점이다.

예를 들어:

- `CH3COOH (acetic acid)` -> 그대로 `"CH3COOH (acetic acid)"`
- `ESP도 그려줘` -> 구조 없음
- `EMIM TFSI` -> 그냥 `"EMIM TFSI"`
- `LiTFSI` -> 그냥 `"LiTFSI"`

즉, 시스템은 molecule identity를 보존하지 않고 "지금 보이는 문자열"을 계속 다음 단계로 넘겼다.

## 2.2 Mixed input 처리 부재

이전에는 `CH3COOH (acetic acid)` 같은 입력을 다음처럼 해석했다.

- formula mention과 alias mention을 분리하지 않음
- equivalence cluster를 만들지 않음
- external resolver에 literal mixed string을 그대로 전달

그 결과 MolChat에는 다음이 갔다.

- `resolve?names=CH3COOH (acetic acid)`

PubChem에도 사실상 없는 compound name으로 조회가 나갔다.

## 2.3 Planner 의미 손실

planner나 heuristic이 일부 구조 정보를 알아도, route merge 과정에서 남는 것은 보통 아래 정도였다.

- `structure_query`
- `job_type`
- `basis`

즉, 아래 정보는 실제 실행 단계로 거의 전달되지 않았다.

- formula mentions
- alias mentions
- canonical candidate ordering
- mixed input 여부
- follow-up mode
- clarification kind
- charge hint
- ion pair / salt decomposition 정보

## 2.4 Follow-up continuity 부재

이전에는 `ESP도`, `LUMO도`, `basis만 더 키워봐` 같은 후속 발화를 처리할 공통 세션 상태가 없었다.
websocket 쪽에 일부 `last_molecule`류 해킹은 있었지만, REST / worker / route 공통의 continuation state는 없었다.

그래서:

- `벤젠의 HOMO 오비탈을 보여줘`
- `ESP도 그려줘`

가 같은 구조의 연속 작업이 아니라, 두 번째 요청이 fresh request로 처리됐다.

## 2.5 Clarification discipline 부재

기존 clarification 흐름은 아래 둘을 충분히 구분하지 못했다.

- discovery: 분자 자체를 모름
- disambiguation: 후보가 여러 개임

그 결과 explicit molecule도 generic picker / custom input으로 빠질 수 있었다.

---

## 3. 지금 구현에서 바뀐 핵심 구조

## 3.1 Normalizer가 mixed input decomposition을 수행

파일:

- `src/qcviz_mcp/llm/normalizer.py`

핵심 추가점:

- `analyze_structure_input()` 도입
- formula mentions / alias mentions / canonical candidates 계산
- mixed input 여부 판단
- primary candidate 계산

관련 구현:

- `analyze_structure_input()` [normalizer.py](../src/qcviz_mcp/llm/normalizer.py)
- `_collect_structure_mentions()` [normalizer.py](../src/qcviz_mcp/llm/normalizer.py)

현재는 `CH3COOH (acetic acid)`를 다음과 같이 분해한다.

- `raw_input = "CH3COOH (acetic acid)"`
- `formula_mentions = ["CH3COOH"]`
- `alias_mentions = ["acetic acid"]`
- `canonical_candidates = ["acetic acid", "ethanoic acid", "CH3COOH"]`
- `mixed_input = True`
- `primary_candidate = "acetic acid"`

즉, 입력을 더 이상 raw literal 하나로 취급하지 않는다.

## 3.2 `extract_structure_candidate()`도 mixed input aware

이전:

- `"CH3COOH (acetic acid)"` -> `"CH3COOH (acetic acid)"`

현재:

- mixed input이면 `primary_candidate` 우선 반환
- quoted input, task-attached input, Korean alias input에도 동일 규칙 적용

예:

- `CH3COOH (acetic acid)` -> `acetic acid`
- `메틸아민 계산해줘` -> `methylamine`
- `Biphenyl` -> `Biphenyl`

즉 route fallback도 이전처럼 raw literal을 다시 살려내지 않게 바뀌었다.

## 3.3 Composite / charge / salt 분석 추가

파일:

- `src/qcviz_mcp/llm/normalizer.py`

핵심 함수:

- `analyze_composite_structure_input()`
- `analyze_follow_up_request()`

현재 normalizer는 다음도 같이 판별한다.

- `TFSI-` -> charge hint
- `EMIM TFSI` -> `composition_kind = ion_pair`
- `LiTFSI` -> `composition_kind = salt`
- component list -> `structures`

예전에는 resolver나 route가 raw string 기반으로 이걸 추측했지만,
지금은 normalizer가 먼저 decomposition metadata를 만든다.

---

## 4. Planner / heuristic 결과의 데이터 계약이 넓어짐

파일:

- `src/qcviz_mcp/llm/schemas.py`
- `src/qcviz_mcp/web/routes/compute.py`

`PlanResponse`는 이제 기존의 얇은 scalar slot 외에 아래 semantic metadata를 보존한다.

- `structure_query_candidates`
- `formula_mentions`
- `alias_mentions`
- `canonical_candidates`
- `raw_input`
- `mixed_input`
- `composition_kind`
- `charge_hint`
- `structures`
- `follow_up_mode`
- `clarification_kind`

이전에는 planner 결과가 `"structure_query": "...", "job_type": "..."` 정도로 축소됐다.
지금은 heuristic fallback이어도 같은 semantic field set을 채우도록 바뀌었다.

이 구현의 핵심은 `compute.py`의 두 지점이다.

1. `_heuristic_plan()`
2. `_safe_plan_message()` 내부 `_enrich_plan()`

즉 현재는 LLM path이든 heuristic path이든,
route에 들어오는 plan dict가 최대한 같은 semantic metadata를 유지한다.

---

## 5. Route가 metadata를 다시 잃어버리지 않도록 변경

파일:

- `src/qcviz_mcp/web/routes/compute.py`

핵심 함수:

- `_merge_plan_into_payload()`
- `_preserve_structure_decomposition()`
- `_apply_session_continuation()`

## 5.1 이전 방식

이전 route merge는 대체로 아래 패턴이었다.

1. `structure_query` 하나만 payload에 넣음
2. 부족하면 raw message에서 다시 fallback extract
3. 실행 직전엔 원래 semantic metadata가 거의 남지 않음

즉 route가 planner 출력을 보존하지 않고, 자체 string repair를 반복했다.

## 5.2 현재 방식

현재 `_merge_plan_into_payload()`는 plan에서 아래 필드를 같이 넘긴다.

- `structure_query_candidates`
- `formula_mentions`
- `alias_mentions`
- `canonical_candidates`
- `raw_input`
- `mixed_input`
- `follow_up_mode`
- `clarification_kind`

그 다음 `_preserve_structure_decomposition()`가 다시 한 번 payload에 semantic decomposition을 고정한다.
여기서 mixed input이면:

- `structure_query_raw`에 기존 raw string을 남기고
- `structure_query`를 `primary_candidate`로 교체한다

즉 최종 payload 기준으로도 `"CH3COOH (acetic acid)"`가 아니라 `"acetic acid"`가 structure query가 된다.

---

## 6. Resolver가 raw literal first가 아니라 query plan 기반으로 동작

파일:

- `src/qcviz_mcp/services/structure_resolver.py`

핵심 함수:

- `_build_query_plan()`
- `resolve()`

## 6.1 이전 방식

이전 resolver는 사실상 raw string 중심이었다.
`CH3COOH (acetic acid)` 같은 입력을 그대로 primary candidate로 쓸 수 있었다.

그 결과:

- MolChat 502
- PubChem 404

같은 외부 오류가 발생했다.

## 6.2 현재 방식

현재 resolver는 먼저 `analyze_structure_input()` 결과를 읽고 query plan을 만든다.

예:

- raw query: `CH3COOH (acetic acid)`
- normalized query: `acetic acid`
- candidate queries:
  - `acetic acid`
  - `ethanoic acid`
  - `CH3COOH`

핵심 규칙:

- mixed input이면 raw mixed string을 primary external query로 쓰지 않음
- alias/common name 우선
- formula는 fallback
- expected charge가 있으면 결과 charge도 검증

또한 resolver는 `query_plan`을 결과 객체에 다시 붙인다.
즉 downstream에서도 "어떤 후보 순서로 resolve되었는지"를 추적할 수 있다.

---

## 7. Follow-up continuity가 lightweight session state로 추가됨

파일:

- `src/qcviz_mcp/web/conversation_state.py`
- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/worker/arq_worker.py`

## 7.1 이전 방식

이전에는 follow-up continuity의 공통 source of truth가 없었다.

- websocket 로컬 상태 일부 존재
- REST와 worker는 공유 안 함
- 마지막 구조 / 마지막 job type / 마지막 basis / 마지막 xyz를 재사용하기 어려움

## 7.2 현재 방식

새 파일 `conversation_state.py`가 추가되었다.

이 상태는 세션 기준으로 다음을 저장한다.

- `last_structure_query`
- `last_resolved_name`
- `last_job_type`
- `last_method`
- `last_basis`
- `last_resolved_artifact`
- `analysis_history`
- `available_result_tabs`

작업 완료 후 `update_conversation_state_from_execution()`가 실행 결과를 세션 상태에 반영한다.

그 후 `_apply_session_continuation()`가 후속 요청에서 이를 읽는다.

예:

- 첫 요청: `벤젠의 HOMO 오비탈을 보여줘`
- 상태 저장:
  - benzene
  - orbital preview
  - xyz
  - basis
- 다음 요청: `ESP도 그려줘`
- normalizer가 `follow_up_mode = add_analysis`
- route가 session state를 읽어 structure / xyz / basis를 상속

즉 두 번째 요청은 이제 새 분자 discovery로 가지 않고 continuation으로 처리된다.

---

## 8. Clarification 흐름이 조금 더 disciplined 해짐

파일:

- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/schemas.py`

이번 단계는 full typed clarification architecture는 아니지만,
최소한 clarification 목적을 구분할 수 있게 만들었다.

현재 사용되는 구분:

- `discovery`
- `disambiguation`
- `parameter_completion`
- `continuation_targeting`

특히 아래 경우는 clarification을 줄이는 방향으로 바뀌었다.

- explicit single-molecule input
- formula + alias mixed input이 한 canonical cluster로 수렴하는 경우
- follow-up인데 session continuation으로 바로 이어갈 수 있는 경우

즉 `Biphenyl`, `메틸아민`, `CH3COOH (acetic acid)`는 예전보다 generic picker로 빠질 가능성이 줄었다.

---

## 9. Charged species / ion pair / salt 처리도 normalizer 중심으로 이동

이전에는 `TFSI-`, `EMIM TFSI`, `LiTFSI` 같은 케이스가 경로마다 다르게 해석되었다.

현재는 normalizer가 먼저 다음을 만들어 준다.

- `composition_kind`
- `structures`
- `charge_hint`

그 다음 compute route는 이 metadata를 활용해:

- ion pair면 `_resolve_ion_pair_async()` 우선
- charge hint가 있으면 payload charge에 반영
- single raw literal first 전략을 피함

즉 resolver 이전 단계부터 "이건 단일 분자인가, composite인가, charge가 있는가"를 알고 들어간다.

---

## 10. Before / After 예시

## 10.1 `CH3COOH (acetic acid)`

이전:

- `structure_query = "CH3COOH (acetic acid)"`
- MolChat query도 raw mixed literal
- PubChem query도 raw mixed literal
- 실패 시 그대로 backend error

현재:

- `formula_mentions = ["CH3COOH"]`
- `alias_mentions = ["acetic acid"]`
- `canonical_candidates = ["acetic acid", "ethanoic acid", "CH3COOH"]`
- `structure_query = "acetic acid"`
- MolChat first query = `acetic acid`

## 10.2 `Biphenyl`

이전:

- explicit molecule인데도 일부 경로에서 clarification leakage 가능

현재:

- plain molecule name으로 direct extraction
- route가 그대로 resolve path로 전달

## 10.3 `메틸아민`

이전:

- Korean alias 처리가 route / alias map / resolver에 분산

현재:

- Korean alias translation이 normalizer 초입에서 먼저 일어남
- `extract_structure_candidate("메틸아민") -> "methylamine"`

## 10.4 `벤젠 HOMO -> ESP도`

이전:

- 두 번째 turn은 구조가 없는 fresh request
- 다시 어떤 분자인지 물어봄

현재:

- follow-up intent 감지
- session continuation state에서 마지막 구조와 xyz 상속
- 새 resolver discovery 없이 같은 구조로 analysis 추가

## 10.5 `TFSI-`, `EMIM TFSI`, `LiTFSI`

이전:

- raw literal 기반 처리
- neutral / charged / composite distinction이 경로별로 흔들림

현재:

- `TFSI-` -> charge hint 유지
- `EMIM TFSI` -> ion pair decomposition
- `LiTFSI` -> salt decomposition

---

## 11. 테스트도 semantic regression 쪽으로 확장됨

관련 테스트 파일:

- `tests/test_structure_extraction.py`
- `tests/test_chat_api.py`
- `tests/test_compute_api.py`
- `tests/v3/unit/test_structure_resolver.py`
- `tests/v3/unit/test_agent.py`

추가된 테스트 축은 대략 다음과 같다.

- mixed input decomposition
- direct molecule extraction
- canonical candidate ordering
- raw mixed literal이 external candidate first로 쓰이지 않는지 검증
- follow-up classification
- continuation state 재사용
- charged species / ion pair / salt normalization

즉 이전의 "mock happy path" 중심 테스트에서,
"semantic metadata가 실제로 유지되는가"를 일부 검증하기 시작했다.

---

## 12. 아직 남아 있는 한계

이번 변경은 즉시 안정화이지, 최종 아키텍처 완성은 아니다.

남은 한계:

1. `CanonicalMoleculeRef`, `ExecutionContext`, `ClarificationIntent` 같은 완전한 typed contract는 아직 없다.
2. `src/qcviz_mcp/compute/pyscf_runner.py`에는 legacy `MoleculeResolver` fallback 경로가 아직 남아 있다.
3. alias authority는 줄었지만 완전히 단일화되지는 않았다.
4. `conversation_state.py`는 lightweight continuation state이지, 완전한 enterprise-grade conversation model은 아니다.
5. 일부 route / frontend / advisor 경로에는 여전히 구 아키텍처 흔적이 남아 있다.

즉 지금 상태는 "반복적으로 깨지던 핵심 UX를 덜 깨지게 만든 단계"다.

---

## 13. 운영상 매우 중요한 주의사항

이번 변경은 소스 수정만으로 끝나지 않는다.
실행 중인 `uvicorn` 프로세스가 수정 전에 떠 있었다면,
브라우저는 계속 수정 전 동작을 본다.

실제로 2026-03-24에는 다음 상황이 확인되었다.

- 서버 프로세스 시작 시각이 핵심 파일 수정 시각보다 빨랐다.
- 그래서 현재 소스에서는 성공하는 `CH3COOH (acetic acid)`가,
  실제 떠 있는 서버에서는 여전히 예전처럼 실패했다.

즉 이런 종류의 변경은 반드시 서버 재시작 후 검증해야 한다.

---

## 14. 다음 단계

즉시 안정화 이후 다음 단계는 아래 순서가 적절하다.

1. `CanonicalMoleculeRef` 도입
2. `ExecutionContext` 도입
3. `ConversationState`를 typed contract로 승격
4. clarification을 discovery / disambiguation / continuation targeting으로 명확히 분리
5. `pyscf_runner` 내부 legacy resolver 제거
6. semantic regression test corpus 확대

---

## 15. 요약

이번 변경의 본질은 기능 추가가 아니라 "의미를 문자열로 다시 잃어버리지 않게 만드는 것"이다.

이전 구현:

- raw string 중심
- route 재해석 반복
- follow-up memory 부재
- resolver query safety 부족

현재 구현:

- mixed input decomposition
- semantic metadata 보존
- session continuation state 추가
- canonical candidate ordering 기반 resolver
- follow-up / charge / composite 케이스 즉시 안정화

아직 전면 재설계는 아니지만,
기본적인 분자명 해석과 후속 요청 continuity가 반복적으로 무너지는 가장 큰 원인을
현재 코드 레벨에서 직접 줄이는 방향으로 구현이 바뀌었다.
