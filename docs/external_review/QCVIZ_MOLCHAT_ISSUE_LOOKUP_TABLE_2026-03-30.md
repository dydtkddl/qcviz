# QCViz + MolChat Issue Lookup Table

이 문서는 `QCViz version03`와 `MolChat v3` 연동 과정에서 지금까지 관찰된 문제를 가능한 한 빠짐없이 정리한 룩업 테이블이다.  
목표는 외부 LLM 또는 다른 엔지니어가 현재 상태를 빠르게 이해하고, 문제를 누락 없이 추적하며, 해결 우선순위를 결정할 수 있게 하는 것이다.

## 요약

- 현재 가장 큰 문제군은 `semantic grounding`, `chat vs compute routing`, `clarification lifecycle`, `state integrity`, `runtime/deployment drift`, `Korean string corruption`, `chat UX policy` 여섯 가지다.
- 일부 문제는 이미 상당 부분 해결되었고, 일부는 정책/UX 레이어에서 아직 마무리가 필요하다.
- 본 문서는 `수정 완료`, `부분 해결`, `미해결`, `운영 이슈`를 한 테이블 안에서 함께 다룬다.

## Issue Table

| ID | 문제명 | 대표 재현 입력 / 상황 | 사용자가 느끼는 증상 | 추정/확인 원인 | 현재 상태 | 관련 핵심 파일 |
|---|---|---|---|---|---|---|
| QV-001 | Semantic descriptor가 raw phrase로 승격됨 | `TNT에 들어가는 주물질` | raw 문장 자체가 분자 후보처럼 뜨거나 잘못된 후보로 이어짐 | semantic descriptor 쿼리에서 raw phrase가 candidate list로 재유입 | 상당 부분 해결 | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/services/structure_resolver.py` |
| QV-002 | Generic fallback 오염 | `TNT에 들어가는 주물질`, `니트로벤젠` | `water`, `benzene`, `ethanol` 같은 무관한 후보가 dropdown에 등장 | semantic descriptor 경로에서 generic suggestion fallback이 허용됨 | 상당 부분 해결 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-003 | MolChat interpret 미배포 | `POST /api/v1/molecules/interpret` | 405 Method Not Allowed | 운영 MolChat backend 미재시작 또는 구버전 라우팅 | 운영 측 해결됨 | `C:/Users/user/Desktop/molcaht/molchat/v3/backend/app/routers/molecules.py` |
| QV-004 | MolChat interpret 성공 후에도 QCViz가 generic fallback으로 재하강 | semantic query + MolChat live 응답 정상 | MolChat가 후보를 줬는데도 다시 generic 후보가 섞임 | QCViz가 MolChat interpret 결과를 최종 후보 source로 쓰지 못함 | 상당 부분 해결 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-005 | Turn/result contamination | 새 질문 직후 이전 질문 결과가 붙음 | 현재 턴 결과 대신 이전 계산 결과가 메시지에 섞여 보임 | turn_id와 job/result binding 경계 부실 | 상당 부분 해결 | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` |
| QV-006 | Clarification 카드 누적 | clarification round-trip 여러 번 | 현재 유효한 카드 외에 이전 카드가 계속 남음 | append-only 렌더링 및 lifecycle 정리 부족 | 상당 부분 해결 | `src/qcviz_mcp/web/static/chat.js` |
| QV-007 | 이전 대화 중복/복원 오염 | 세션 전환, history hydration | 동일 메시지가 여러 번 보이거나 `이전 대화` 블록이 현 턴과 섞임 | history restore + live append dedupe 부족 | 상당 부분 해결 | `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-008 | Canonical molecule을 다시 composition heuristic이 재해석 | `2,4,6-TRINITROTOLUENE` 선택 후 | 다시 `ion pair / single / separate`를 묻는 2차 clarification | 선택 완료된 canonical structure도 composition heuristic이 다시 먹음 | 해결됨 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-009 | 질문형 약어 입력이 계산으로 진입 | `MEA 알아?`, `MEA라는 물질이 뭐야?` | 설명을 원했는데 계산 플랜이 뜨고 resolve 실패 | chat vs compute routing이 너무 늦게 갈림 | 부분 해결, UX 정책 미완 | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/llm/agent.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-010 | unknown acronym compute request가 바로 계산되거나 raw acronym으로 resolve 시도 | `MEA HOMO 보여줘` | 약어를 바로 계산하려고 하거나 raw acronym이 구조명처럼 소비됨 | grounding_required 우선순위 미약 | 상당 부분 해결 | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-011 | batch multi-molecule request가 semantic grounding에 막힘 | 여러 분자 문단형 입력 | 이미 선택된 여러 분자가 있는데도 semantic clarification으로 멈춤 | explicit multi-molecule selection보다 semantic descriptor가 우선 적용됨 | 해결됨 | `src/qcviz_mcp/llm/normalizer.py` |
| QV-012 | follow-up analysis가 이전 구조를 못 이어받거나 continuation으로 과잉 분기 | `ESP도 보여줘`, `HOMO LUMO ESP` | 불필요한 clarification 또는 잘못된 새 구조 추정 | continuation_targeting 우선순위와 structure lock 경계 미흡 | 상당 부분 해결 | `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-013 | direct explicit molecule request가 너무 늦게 compute_ready로 들어감 | `benzene HOMO 보여줘` | 불필요한 grounding/clarification 가능성 | question-like / semantic descriptor 규칙이 과도하면 직접 질의도 막힘 | 현재는 정상 유지 목표 | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/llm/agent.py` |
| QV-014 | single high-confidence semantic candidate인데도 dropdown을 띄움 | `TNT에 들어가는 주물질이 뭐지?` | 사실상 정답 후보가 1개인데 확인 UI부터 뜸 | semantic grounding 결과를 설명형 chat response로 전환하는 정책 부재 | 미완, 중요 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-015 | explanation question이 analyze/resolve로 이어짐 | `MEA라는 물질이 뭐야?` | 설명형 질문인데 계산 플랜, resolve, error가 발생 | chat_only와 semantic_grounding이 배타적으로 설계됨 | 미완, 중요 | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-016 | semantic grounding 결과가 chat-only 응답에 반영되지 않음 | `MEA라는 물질이 뭐야?` | MolChat는 후보를 주지만 사용자 응답은 에러/clarification/계산 시도로 끝남 | grounded candidate -> direct answer lane 부재 | 미완, 중요 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-017 | semantic fallback query contract mismatch | semantic fallback 테스트 | compact raw phrase vs normalized readable query 기대가 어긋남 | 구현 계약은 정규화된 readable query로 바뀌었는데 일부 테스트는 구계약 기대 | 부분 해결 | `tests/test_chat_api.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-018 | Korean UI 문구 mojibake | semantic grounding 안내문, 일부 clarification label | 안내 문구가 깨진 문자로 출력됨 | 소스 내부 문자열 일부가 손상된 상태로 저장됨 | 일부 해결, 잔존 가능성 있음 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-019 | Clarification label/help/placeholder 일부 한글이 깨짐 | multi-select / custom / parameter completion | UI는 작동하지만 한국어 문구가 어색하거나 깨짐 | 과거 인코딩 손상 문자열이 잔존 | 미완 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-020 | MolChat direct_name/semantic_descriptor 모드 결과 활용 정책 불명확 | interpret 결과 `query_mode=direct_name`, single candidate | direct-name like result도 confirmation UI 또는 compute 플랜으로 새어 나감 | query_mode, candidate count, confidence 기반 UX 정책이 없음 | 미완 | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/services/molchat_client.py` |
| QV-021 | Event loop is closed 로그 | 실패 후 종료 시점 | 최종 사용자 에러와 함께 asyncio cleanup 예외가 로그에 남음 | 비동기 클라이언트/transport 종료 시점 문제 추정 | 운영 이슈, 별도 추적 필요 | `src/qcviz_mcp/services/molchat_client.py`, runtime environment |
| QV-022 | runtime drift 감지 필요 | 디스크 코드 수정 후 서버 미재시작 | 수정했는데 live behavior가 안 바뀜 | stale process / cache / deployment mismatch | 일부 해결 | `src/qcviz_mcp/web/runtime_info.py`, `/api/chat/health` |
| QV-023 | semantic descriptor path에서 custom-only fallback이 필요한 경우가 있음 | MolChat interpret=0, generic LLM fallback discard | 후보가 없는데도 안전한 fallback 정책이 불명확 | generic fallback 금지 후 safe recovery UX가 필요 | 부분 해결 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-024 | dropdown label이 지나치게 장황하거나 추론 로그처럼 보임 | semantic grounding 후보 UI | 후보 선택 UI가 자연어 답변 로그처럼 보임 | rationale/description 조합 정책 미정리 | 부분 해결 | `src/qcviz_mcp/web/routes/chat.py` |
| QV-025 | structure_locked 이후 compute submit precedence 불안정 | clarification answer 적용 직후 | 선택 구조가 plan/result에 일관되게 남지 않음 | merge order / planner_applied / continuation helper 경계 부실 | 상당 부분 해결 | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/routes/compute.py` |
| QV-026 | semantic descriptor 테스트 픽스처가 실제 UX 목표와 어긋날 수 있음 | Playwright / API stub | 모든 질문에 TNT 하나만 반환하는 stub로 인해 챗봇 UX 회귀를 놓칠 수 있음 | 테스트 fixture가 query-sensitive하지 않음 | 미완 | `tests/test_chat_playwright.py` 및 관련 테스트 |
| QV-027 | abbreviation map와 chemistry action term이 충돌 | `HOMO`, `ESP`, `MEA` 혼합 질의 | 분석 용어를 acronym으로 오탐하거나 반대로 실제 약어를 compute-ready로 통과 | unknown acronym 판정과 analysis token 판정 경계 미세 조정 필요 | 부분 해결 | `src/qcviz_mcp/llm/normalizer.py` |
| QV-028 | MolChat를 resolver backend처럼만 소비 | QCViz semantic query 전반 | semantic grounding 파트너가 아니라 resolve backend로만 쓰이던 설계 | `/molecules/interpret` 승격 이전 구조 | 부분 해결 | `src/qcviz_mcp/services/molchat_client.py`, `src/qcviz_mcp/web/routes/chat.py` |
| QV-029 | question-like semantic query에서 compute submit 이후 resolve 실패 | `MEA라는 물질이 뭐야?` | 사용자는 설명을 원했는데 결국 `Cannot resolve structure` 에러만 받음 | explanation intent에 대한 direct grounded chat lane이 없음 | 미완, 최우선 | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/llm/normalizer.py` |
| QV-030 | 사용자가 “챗봇처럼 유연하다”라고 느끼지 못함 | 전체 대화 UX | 질문형 질의, 설명형 질의, 계산형 질의의 톤과 정책이 분리되지 않음 | 구조적으로 compute 중심 설계가 남아 있음 | 미완, 제품 수준 이슈 | QCViz 전체 chat stack + MolChat interpret policy |

## 우선순위 제안

### P0

- QV-014 single high-confidence semantic candidate는 direct answer로 종료
- QV-015 explanation question은 compute 진입 금지
- QV-016 semantic grounding 결과를 chat-only 응답에 반영
- QV-029 explanation intent가 resolve/compute error로 끝나지 않도록 차단

### P1

- QV-018, QV-019 한국어 mojibake 전체 정리
- QV-020 MolChat interpret 결과 활용 정책 명문화
- QV-024 dropdown label / rationale 표현 정리
- QV-026 query-sensitive test fixture 보강

### P2

- QV-021 event loop cleanup 안정화
- QV-030 전체 conversational UX policy refinement

## 바람직한 최종 사용자 경험

- `MEA라는 물질이 뭐야?`
  - direct answer: “MEA는 보통 Ethanolamine을 의미합니다.”
  - no compute
  - no resolve error
  - optional next-step suggestion

- `MEA HOMO 보여줘`
  - semantic grounding clarification 또는 grounded compute confirmation
  - no raw acronym compute

- `TNT에 들어가는 주물질이 뭐지?`
  - single high-confidence direct answer
  - dropdown 생략 가능
  - 사용자가 원할 때만 계산 제안

- `benzene HOMO 보여줘`
  - immediate compute-ready
  - no extra grounding
