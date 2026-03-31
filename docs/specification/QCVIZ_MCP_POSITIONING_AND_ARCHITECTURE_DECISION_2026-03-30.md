# QCViz MCP 포지셔닝 및 아키텍처 결정 기록

작성일: 2026-03-30  
대상 프로젝트: `QCViz version03`  
목적: 이 문서는 QCViz의 현재 정체성이 진짜 MCP 프로젝트인지, MCP를 어디까지 써야 하는지, LLM과 direct orchestration의 역할을 어떻게 정의해야 하는지에 대한 판단을 장기 보존용으로 정리한 기록이다.

---

## 1. 결론 요약

가장 먼저 결론부터 정리하면 다음과 같다.

1. 현재 QCViz는 **MCP 서버를 포함하고 있는 하이브리드 구조**다.
2. 하지만 **현재 웹앱의 주 실행 경로는 MCP를 타지 않는다.**
3. 따라서 이 프로젝트를 “완전한 MCP-native 프로젝트”라고 부르는 것은 과장이다.
4. 이 프로젝트의 더 정확한 정체성은 **실험자를 위한 웹 기반 올인원 계산화학 플랫폼**이다.
5. MCP는 이 플랫폼의 본질이라기보다 **외부 연동과 표준 인터페이스를 위한 호환 레이어**로 보는 것이 맞다.
6. 성능, 실패율, 사용자 경험만 본다면 **현재는 direct orchestration이 가장 유리**하다.
7. 장기적으로 가장 좋은 구조는 **공통 코어 서비스 계층 + 웹 어댑터 + MCP 어댑터**다.

한 문장으로 요약하면:

**QCViz는 MCP 프로젝트라기보다 web-first conversational quantum chemistry platform이며, MCP는 그 위에 얹을 수 있는 상호운용성 계층이다.**

---

## 2. 현재 코드 기준 사실 판단

### 2.1 MCP 서버와 MCP 도구는 실제로 존재한다

현재 저장소에는 FastMCP 기반 서버가 실제로 존재한다.

- `src/qcviz_mcp/mcp_server.py`
  - `FastMCP("QCViz-MCP")`로 서버를 초기화한다.
- `src/qcviz_mcp/tools/core.py`
  - `@mcp.tool()`로 핵심 계산 도구들을 등록한다.
- `src/qcviz_mcp/tools/advisor_tools.py`
  - `@mcp.tool()`로 advisor 계열 도구들을 등록한다.

즉, 이 저장소 안에 “이름만 MCP인 파일”이 있는 것이 아니라, **실제 MCP tool surface**가 있다.

### 2.2 하지만 메인 사용자 경로는 MCP가 아니다

현재 웹앱이 실제로 사용자 요청을 처리하는 메인 경로는 FastAPI 웹앱이다.

- `src/qcviz_mcp/app.py`
  - 기본 app export는 `web.app`를 가리킨다.
- `src/qcviz_mcp/web/app.py`
  - 실제 사용자용 웹앱 엔트리다.

그리고 계산 실행은 MCP client를 통해 tool을 부르는 것이 아니라, 내부 Python 함수 호출로 처리된다.

- `src/qcviz_mcp/web/routes/compute.py`
  - `from qcviz_mcp.compute import pyscf_runner`
  - `JOB_TYPE_TO_RUNNER`에서
    - `single_point -> run_single_point`
    - `orbital_preview -> run_orbital_preview`
    - `esp_map -> run_esp_map`
    - `geometry_optimization -> run_geometry_optimization`
    로 직접 매핑한다.

즉 현재 웹 경로는 아래처럼 동작한다.

`User -> FastAPI chat/compute route -> planner/normalizer -> internal Python call -> PySCF/result packaging`

아래처럼 되지는 않는다.

`User -> Web app -> MCP client -> MCP server -> MCP tool -> backend`

따라서 현재 구조는 정확히 말하면:

**MCP server exists + web app exists + main UX path uses direct orchestration**

이다.

---

## 3. 이 프로젝트는 “진짜 MCP 프로젝트”인가?

### 3.1 예라고 할 수 있는 부분

- MCP 서버가 실제로 있다.
- `@mcp.tool()` 기반 tool registration이 실제로 존재한다.
- 외부 MCP-compatible 환경과 연결될 잠재력이 있다.

### 3.2 아니라고 할 수 있는 부분

- 현재 사용자 주 경로는 MCP를 경유하지 않는다.
- 웹앱의 대화 오케스트레이션은 MCP client 기반이 아니라 내부 direct orchestration 기반이다.
- chat / clarification / follow-up / session continuation / result binding은 전부 웹앱 내부 로직이다.

### 3.3 최종 판정

현재 프로젝트는:

- **MCP-compatible**: 예
- **MCP-capable**: 예
- **fully MCP-native end-to-end**: 아니오

따라서 가장 정직한 표현은 다음 중 하나다.

- `MCP-compatible quantum chemistry platform`
- `FastMCP tool server + separate FastAPI conversational interface`
- `web-first platform with an MCP-compatible tool layer`

반대로 아래 표현은 과장에 가깝다.

- `모든 계산 흐름이 MCP로 동작한다`
- `현재 웹앱 전체가 MCP client-server 구조로 통합되어 있다`

---

## 4. 프로젝트의 핵심 정체성은 무엇인가

이 프로젝트의 핵심 목적은 다음과 같다.

- 실험자가 설치 없이 웹에서 접근한다.
- 계산화학 전공자 없이도 초기 계산 탐색을 할 수 있다.
- 구조를 불러오고, 계산을 설정하고, 결과를 시각화하는 복잡한 툴체인을 단일화한다.
- 자연어 또는 쉬운 입력으로 분자와 계산 의도를 전달한다.
- MolChat과 같은 구조 grounding 시스템을 통해 구조를 확인한다.
- PySCF 같은 실제 계산 엔진으로 DFT 계산을 수행한다.
- 별도 전문 시각화 툴 없이 브라우저에서 바로 결과를 확인한다.

이 목표를 가장 정확하게 표현하면 다음과 같다.

- `실험 화학자를 위한 웹 기반 올인원 계산화학 플랫폼`
- `zero-install conversational DFT access platform`
- `web-first conversational quantum chemistry workflow platform`
- `자연어 기반 계산 오케스트레이션 및 시각화 플랫폼`

즉, 이 프로젝트의 본질은 **MCP 프로젝트**가 아니라 **사용자 워크플로우 플랫폼**이다.

MCP는 이 목표를 도울 수는 있지만, 이 목표 자체를 정의하지는 않는다.

---

## 5. MCP를 언제 써야 하고 언제 쓰지 말아야 하는가

### 5.1 MCP를 쓰는 게 좋은 경우

다음 조건에서는 MCP를 쓰는 것이 유리하다.

- 외부 모델이나 외부 클라이언트가 이 기능을 표준 방식으로 호출해야 할 때
- Claude Desktop, 다른 agent, IDE, 외부 툴이 붙을 수 있게 하고 싶을 때
- 도구를 독립적인 capability로 공개하고 싶을 때
- 입력/출력 스키마와 계약을 표준화하고 싶을 때
- 호출 추적성과 도구 사용 이력을 명확히 남기고 싶을 때

QCViz에서 MCP로 두기 좋은 후보는 다음과 같다.

- `resolve_structure`
- `compute_orbital`
- `compute_esp`
- `optimize_geometry`
- `single_point`
- `partial_charges`
- `generate_methods_text`
- `advisor` 계열 도구

즉, **도메인 capability**는 MCP tool로 두기 좋다.

### 5.2 MCP를 억지로 쓰지 않는 게 좋은 경우

다음은 MCP보다 내부 앱 로직으로 두는 편이 더 낫다.

- 웹앱 내부 상태 관리
- 세션 문맥 유지
- clarification UI 생성
- turn/result binding
- follow-up 정책
- direct answer 문구 정책
- 프론트엔드 이벤트 정렬
- 질문형 입력과 계산형 입력의 구분

QCViz에서 내부 로직으로 두는 것이 맞는 대상은 다음과 같다.

- `chat_only / grounding_required / compute_ready` 판정
- clarification lifecycle
- session continuation
- structure lock 이후의 UI 흐름
- chat message rendering policy
- websocket state integrity

즉, **제품 UX/state orchestration**은 MCP보다 내부 로직으로 두는 편이 안정적이다.

### 5.3 실전 원칙

한 줄 원칙으로 줄이면 다음과 같다.

**외부 클라이언트가 독립적으로 호출할 가치가 있는 기능은 MCP 후보이고, 내부 앱 상태를 제어하는 로직은 MCP로 밀어넣지 않는다.**

---

## 6. LLM의 역할은 왜 필요한가

이 프로젝트에서 LLM은 선택적 장식이 아니라 중요한 인터페이스 계층이다.

### 6.1 LLM이 필요한 이유

실험자의 입력은 대부분 불완전하고 애매하다.

예를 들어:

- `벤젠의 HOMO 보여줘`
- `TNT에 들어가는 주물질이 뭐지?`
- `같은 구조로 ESP도`
- `이 구조 최적화해줘`
- `MEA라는 물질이 뭐야?`

이런 입력을 버튼과 정적 폼만으로 처리하면 UX가 곧 딱딱해진다.

LLM은 다음 역할에 강하다.

- 자연어 의도 파악
- 계산 종류 식별
- 구조 후보와 질문 목적 구분
- follow-up 맥락 유지
- clarification 문구 생성
- direct answer와 compute request 구분

즉, 이 프로젝트에서 LLM의 핵심 역할은:

**사용자의 자연어를 계산 가능한 구조화 요청으로 번역하는 것**

이다.

### 6.2 하지만 LLM은 계산 엔진이 아니다

LLM이 해도 되는 일:

- 의도 해석
- semantic grounding 보조
- clarification
- 후속 질문 맥락 관리
- 결과 설명

LLM이 하면 안 되는 일:

- 실제 에너지값 생성
- 계산을 하지 않았는데 계산한 것처럼 말하기
- 계산 결과를 근거 없이 단정하기
- 구조를 임의로 확정하기

따라서 건강한 역할 분담은 다음과 같다.

- **LLM**: 사람과 시스템 사이 번역기
- **MolChat / structure resolver**: 구조 grounding
- **PySCF / DFT engine**: 실제 계산
- **웹앱**: 사용자 경험과 결과 전달

이 구조는 과학 도구로서도 정직하다.

---

## 7. “LLM의 계산 번역을 PySCF로 넘기는 것”은 MCP인가

정확히는 다음과 같이 구분해야 한다.

### 7.1 넓은 개념

LLM이 의도를 해석하고, 그 해석 결과를 실제 도구 실행으로 넘기는 것은 넓게 보면:

**tool orchestration**

이다.

### 7.2 MCP인 경우

그 orchestration이

- MCP client
- MCP server
- MCP tool

구조를 통해 이루어지면, 그건 MCP 기반 orchestration이다.

### 7.3 MCP가 아닌 경우

그 orchestration이

- 웹앱 내부 route
- planner
- internal function call

로 바로 이어지면, 그것은 tool orchestration이지만 MCP는 아니다.

### 7.4 현재 QCViz의 위치

현재 QCViz는:

- LLM-to-tool 전이는 존재한다.
- 하지만 그 전이가 MCP 프로토콜을 타지는 않는다.

즉 현재 구조는:

**LLM-mediated direct orchestration**

으로 보는 것이 가장 정확하다.

---

## 8. 성능, 실패율, 사용자 경험만 보면 무엇이 최선인가

이 기준만 놓고 보면 답은 명확하다.

### 8.1 direct orchestration이 가장 유리하다

현재 사용자 경험 기준으로는 다음 경로가 제일 유리하다.

`LLM -> web route -> internal service/function -> PySCF`

이유는:

- hop 수가 적다
- 직렬화/역직렬화 비용이 적다
- 프로토콜 mismatch 가능성이 적다
- 디버깅이 쉽다
- 실패 지점이 적다
- clarification / follow-up / state management를 내부에서 세밀하게 제어하기 쉽다

### 8.2 full MCP 전환의 한계

내부까지 전부 MCP로 보내면:

- 호출 단계가 늘어난다
- schema mismatch 지점이 늘어난다
- transport / protocol / registration 오류면이 커진다
- UX 문제를 자동으로 해결해주지 않는다

즉:

- 장기적 아키텍처 정리는 좋아질 수 있어도
- 지금 당장의 성능, 실패율, UX에는 반드시 이득이 되는 것은 아니다

### 8.3 정리

성능, 실패율, 사용자 경험만 보면 순위는 대체로 다음과 같다.

1. **direct orchestration**
2. **hybrid**
3. **full MCP-native**

---

## 9. 그러면 무엇을 선택하는 게 가장 좋은가

현재 프로젝트 기준으로 가장 좋은 선택은:

**공통 코어 서비스 계층 + 웹 어댑터 + MCP 어댑터**

이다.

### 9.1 추천 구조

먼저 공통 코어를 만든다.

- structure resolution
- semantic grounding
- compute dispatch
- result packaging
- clarification policy

그 위에 어댑터를 둔다.

- 웹 채팅 어댑터
- MCP tool 어댑터

### 9.2 이 구조의 장점

- 사용자 경험을 해치지 않는다
- 현재 UX 문제를 계속 풀 수 있다
- 웹과 MCP가 같은 진실 원천을 쓰게 만들 수 있다
- 중복 로직을 줄일 수 있다
- 외부 연동성도 유지된다
- 발표/논문에서도 정직하게 설명할 수 있다

### 9.3 왜 full MCP-native가 아닌가

full MCP-native는 지금 시점에서는 과투자에 가깝다.

- 모든 대화 상태를 tool call 중심으로 재설계해야 한다
- clarification / follow-up / session continuation이 더 복잡해진다
- 현재의 실제 문제는 protocol보다 UX/state orchestration 쪽이다

따라서 현재는:

**웹 중심 direct orchestration을 유지하되, 공통 코어와 MCP 어댑터를 정리하는 하이브리드 전략이 가장 현실적이다.**

---

## 10. direct orchestration이면 논문화 가치가 떨어지는가

그렇지 않다.

### 10.1 왜 논문화 가치가 유지되는가

당신 프로젝트의 핵심 기여는 다음에 있다.

- 설치 없는 웹 접근성
- 실험자 대상 UX
- 자연어 기반 계산 진입
- 구조 grounding
- 타당한 계산 설정 자동화
- 실제 DFT 실행
- 결과 시각화 단일화
- 후속 질문과 세션 연속성

이건 **workflow/platform contribution**이다.

리뷰어는 보통 다음을 본다.

- 문제를 얼마나 잘 풀었는가
- 사용자 접근성을 얼마나 바꿨는가
- 계산 워크플로우를 얼마나 단순화했는가
- 실제 사용성/안정성을 어떻게 보여줬는가

이 기준에서는 내부가 direct orchestration인지 MCP인지가 본질은 아니다.

### 10.2 오히려 direct orchestration의 장점

- 실패율이 낮다
- 응답 속도가 좋다
- 시스템 설명이 단순하다
- 사용자 연구와 UX 평가가 더 깔끔하다

즉, 논문의 중심을

- `MCP 기반 scientific architecture`

로 잡는다면 direct orchestration은 약점이 될 수 있다.

하지만 논문의 중심을

- `실험자를 위한 웹 기반 올인원 계산화학 플랫폼`

으로 잡는다면 direct orchestration은 오히려 더 강할 수 있다.

### 10.3 최종 판단

**당신 프로젝트의 진짜 논문화 가치는 MCP 여부가 아니라, 실험자의 질문을 실제 계산과 해석 가능한 결과로 얼마나 자연스럽고 안정적으로 연결하느냐에 있다.**

---

## 11. 발표와 논문에서 어떻게 말하는 것이 가장 정직한가

### 11.1 추천 표현

- `실험 화학자를 위한 웹 기반 올인원 양자화학 플랫폼`
- `zero-install conversational quantum chemistry platform`
- `web-first platform with an MCP-compatible tool interface`
- `자연어 기반 계산 오케스트레이션 및 시각화 플랫폼`

### 11.2 피해야 할 표현

- `모든 계산 흐름이 MCP로 동작한다`
- `완전히 MCP-native end-to-end 시스템이다`
- `MCP 자체가 이 프로젝트의 핵심 기여다`

### 11.3 발표용 한 줄

다음 한 줄이 가장 정직하고 강하다.

**QCViz는 실험 연구자가 설치 없이 웹에서 계산에 접근하고, 구조 grounding부터 DFT 실행, 시각화까지 한 번에 연결할 수 있게 만든 web-first 계산화학 플랫폼이며, MCP는 그 위에 얹을 수 있는 호환형 도구 인터페이스다.**

---

## 12. 최종 의사결정

현재 기준 최종 의사결정은 다음과 같다.

1. 프로젝트의 정체성은 **MCP 프로젝트**가 아니라 **웹 기반 올인원 계산화학 플랫폼**으로 둔다.
2. 현재 웹 요청 경로는 MCP를 내부적으로 쓰지 않는다고 정직하게 기록한다.
3. 성능, 실패율, 사용자 경험을 위해 메인 경로는 당분간 **direct orchestration**을 유지한다.
4. 장기적으로는 **공통 코어 + 웹 어댑터 + MCP 어댑터** 구조로 정리한다.
5. 발표와 논문에서는 MCP를 본질이 아니라 **호환성과 확장성의 기술 요소**로 위치시킨다.
6. LLM은 계산 엔진이 아니라 **자연어를 계산 가능한 요청으로 번역하는 인터페이스 계층**으로 정의한다.

---

## 13. 앞으로 이 문서를 다시 볼 때 확인할 질문

향후 다시 판단이 필요할 때는 다음 질문들로 점검한다.

1. 현재 웹앱이 정말 direct orchestration을 유지하는 것이 사용자 경험에 가장 유리한가?
2. 외부 에이전트 연동 수요가 실제로 얼마나 커졌는가?
3. 웹과 MCP 사이의 코드 중복이 심해졌는가?
4. 공통 코어 서비스 계층이 충분히 분리되었는가?
5. 발표/논문에서 MCP를 강조하는 것이 여전히 도움이 되는가, 아니면 플랫폼 가치를 더 앞세워야 하는가?

이 질문에 대한 답이 크게 달라질 때만 MCP 전략을 다시 재검토한다.

