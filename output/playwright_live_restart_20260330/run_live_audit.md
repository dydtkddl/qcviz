이 코드는 **QCViz-MCP 웹 앱의 자동화된 E2E(End-to-End) 통합 테스트 스위트**입니다. Playwright(브라우저 자동화)를 사용해서 실제 브라우저를 띄우고, 사용자처럼 채팅 입력을 하고, 결과를 검증합니다.

---

## 전체 구조

크게 3단계로 나뉩니다: **헬스체크 → 20개 테스트 케이스 실행 → 결과 리포트 생성**

---

## 테스트 케이스 룩업 테이블

| Case   | 입력 프롬프트                                      | 테스트 목적                        | 판정 기준                          |
| ------ | -------------------------------------------------- | ---------------------------------- | ---------------------------------- |
| **01** | _(페이지 로드)_                                    | QCViz 부팅 확인                    | 타이틀이 "QCViz-MCP v3"인지        |
| **02** | _(페이지 로드)_                                    | MolChat 백엔드/프론트 가용성       | health 200 + 타이틀에 "MolChat"    |
| **03** | `benzene HOMO 보여줘`                              | 직접 계산 (오비탈)                 | benzene 구조 + orbital 시각화 생성 |
| **04** | `Render ESP map for acetone using ACS preset`      | 직접 계산 (ESP)                    | acetone 구조 + ESP 시각화 생성     |
| **05** | `water optimize geometry`                          | 구조 최적화                        | water 구조 활성화                  |
| **06** | `benzene and toluene HOMO`                         | 복수 분자 → clarification 발생     | clarify 카드 ≥1, 계산 안 됨        |
| **07** | `HOMO가 뭐야?`                                     | 개념 질문 → 채팅만                 | clarify 없음 + "homo" 텍스트 존재  |
| **08** | `MEA 알아?`                                        | 약어 시맨틱 그라운딩               | clarify 없음 + "ethanolamine" 언급 |
| **09** | `MEA HOMO 보여줘`                                  | 약어+계산 → 그라운딩 clarification | clarify ≥1 + 옵션에 raw "MEA" 없음 |
| **10** | `DMA 알아?`                                        | 모호한 약어 → clarification        | clarify ≥1                         |
| **11** | `main component of TNT HOMO 보여줘` → clarify 제출 | 그라운딩 후 계산까지               | "trinitrotoluene" 언급             |
| **12** | `MEA 알아?` → `ㅇㅇ 그거 HOMO 보여줘`              | 대명사("그거") 후속 요청           | Ethanolamine + orbital 시각화      |
| **13** | `그거 ESP도`                                       | 같은 세션 대명사 ESP 후속          | Ethanolamine + ESP                 |
| **14** | `ESP도`                                            | 초단문 후속                        | Ethanolamine 유지                  |
| **15** | `이번엔 LUMO`                                      | 오비탈 변경 후속                   | Ethanolamine + orbital             |
| **16** | `basis만 더 키워봐`                                | 파라미터만 변경 후속               | Ethanolamine 유지 + clarify 없음   |
| **17** | `method를 B3LYP로 바꿔`                            | 메소드 변경 후속                   | Ethanolamine 유지 + clarify 없음   |
| **18** | `그거 HOMO 보여줘` _(새 세션)_                     | 새 세션에서 대명사 → clarify       | clarify ≥1 + "그거" 옵션 없음      |
| **19** | `basis 더 키워` _(새 세션)_                        | 새 세션 파라미터 후속 → clarify    | clarify ≥1                         |
| **20** | `"; DROP TABLE...` (SQL인젝션+유니코드)            | 레드팀 악성 입력                   | 앱 크래시 없이 WS 연결 유지        |

---

## 테스트가 검증하는 5개 레이어

| 레이어                                  | 해당 케이스            |
| --------------------------------------- | ---------------------- |
| **Boot** (서버 기동)                    | 01, 02                 |
| **Job lifecycle** (계산 실행/완료)      | 03, 04, 05, 12, 13     |
| **Prompt routing** (채팅 vs 계산 분류)  | 06, 07, 16, 17, 19, 20 |
| **Semantic grounding** (약어/별칭 해석) | 08, 09, 10, 11         |
| **Continuation state** (세션 문맥 유지) | 12–18                  |

---

## 핵심 헬퍼 함수 요약

`send_prompt`는 채팅창에 텍스트를 입력하고 전송 버튼을 클릭한 뒤 서버 응답(clarify 카드, confirm 카드, 새 메시지)이 올 때까지 대기합니다. `wait_for_terminal_state`는 여기서 더 나아가 job이 completed/failed/cancelled 상태가 될 때까지 기다립니다. `qcviz_state`는 현재 DOM과 JS store에서 메시지 목록, clarify/confirm 카드, 활성 결과, job 상태 등을 한 번에 스냅샷으로 추출합니다.

결국 이 스크립트를 한 번 실행하면 20개 시나리오를 자동으로 돌리고, 각 케이스별 스크린샷 + 상태 JSON + PASS/FAIL 판정을 `live_case_results.json`에 모아서 저장합니다.
