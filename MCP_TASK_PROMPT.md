# MCP-Unified AI Agent Architecture — 분석 및 마이그레이션 설계 작업지시

> **Prompt Purpose**: QCViz-MCP v3 프로젝트의 아키텍처를 "Gemini-as-Planner"에서 "Gemini-as-MCP-Client"로 전환하기 위한 분석·설계·로드맵 생성
>
> **Target LLM**: 이 프롬프트를 받는 당신은 소프트웨어 아키텍트이자 양자화학 도메인에 정통한 시니어 엔지니어입니다.
>
> **Input**: 이 프롬프트와 함께 `MCP_ARCHITECTURE_ANALYSIS.md` 파일이 제공됩니다 (7,000+ lines, 25개 핵심 소스 파일 포함).

---

## 🧭 CONTEXT (맥락)

### 프로젝트 정체성

QCViz-MCP는 PySCF 기반 양자화학 계산 웹 애플리케이션입니다:

- **Backend**: FastAPI + WebSocket + PySCF
- **Frontend**: Vanilla JS + 3Dmol.js
- **AI**: Gemini API (google-genai)
- **MCP Server**: FastMCP (`@mcp.tool()`)

### 현재 아키텍처의 핵심 결함

시스템에 **동일 기능에 대한 2개의 독립 경로**가 존재합니다:

|               | 경로 1: MCP 클라이언트        | 경로 2: 웹 UI                      |
| ------------- | ----------------------------- | ---------------------------------- |
| **진입점**    | Claude/Gemini CLI             | 브라우저 WebSocket                 |
| **AI 역할**   | MCP 프로토콜로 도구 직접 호출 | JSON 플래너만 (도구 호출 안 함)    |
| **계산 실행** | `@mcp.tool()` → PySCF         | 하드코딩 매핑 → `pyscf_runner.py`  |
| **구조 해석** | 도구 내부에서 자체 처리       | `compute.py`에서 PubChem 직접 호출 |
| **에러 복구** | AI가 에러 보고 재시도 가능    | 에러 → WS 크래시 → 재연결 폭풍     |

이 이중 경로 때문에:

- 분자 이름 해석 실패 시 자동 복구 불가 (Gemini가 실패를 인지 못함)
- 도구 체이닝 불가 (resolve → SCF → orbital 같은 multi-step)
- 새 기능 추가 시 MCP 도구 + 웹 직접호출 양쪽 수정 필요
- MCP 도구에서 되는 기능이 웹 UI에서 안 되는 불일치

---

## 🎯 OBJECTIVE (목표)

웹 UI의 Gemini를 **MCP 클라이언트로 전환**하여 모든 클라이언트가 동일한 `@mcp.tool()` 경로를 사용하게 합니다.

**Before (현재)**:

```
Web UI → Gemini(플래너) → JSON → 하드코딩 직접호출 → PySCF
```

**After (목표)**:

```
Web UI → Gemini(function calling) → MCP tool in-process 실행 → PySCF
           │                              │
           ◀── 결과 반환 ── 에러면 자동 재시도/대안 시도
           │
           ▼ 추가 도구 호출 결정 or 최종 응답 생성
```

---

## 📋 TASK (작업 지시)

아래 5개 섹션을 **순서대로** 수행하세요. 각 섹션은 이전 섹션의 결과에 의존합니다.

### Task 1: 현재 상태 진단 (Current State Diagnosis)

소스 코드를 분석하여 다음을 **파일명:함수명** 수준으로 식별하세요:

1. **이중 경로 매핑 테이블**: MCP 도구와 웹 직접호출의 1:1 기능 대응 목록

   ```
   예시 형식:
   | 기능 | MCP 도구 (core.py) | 웹 직접호출 (compute.py/pyscf_runner.py) |
   |------|---------------------|----------------------------------------|
   | 단일점 계산 | run_single_point() | _sync_compute_impl() |
   ```

2. **구조 해석 경로 차이**: `MoleculeResolver` (core.py) vs `StructureResolver` (structure_resolver.py) vs `_resolve_structure_async` (compute.py) — 세 가지 해석 경로의 차이점과 호출 관계

3. **에러 전파 맵**: PubChem 실패 → ... → WebSocket 크래시까지의 정확한 콜스택

4. **제거 가능 코드**: 통합 시 삭제 가능한 함수/클래스 목록과 예상 라인 수

5. **보존 필수 코드**: `compute.py`에서 MCP 통합 후에도 필요한 유틸리티 함수

> **출력 형식**: 마크다운 테이블 + 코드 참조 (파일:라인번호)

---

### Task 2: MCP 통합 아키텍처 설계 (Architecture Design)

구체적인 파일/함수 단위의 변경 계획을 설계하세요:

1. **Gemini Function Calling 레이어** (`agent.py` 리팩토링)
   - MCP 도구 스키마 → Gemini function declaration 변환 방법
   - Function calling loop 구현 (`tool_call → execute → result → continue/finish`)
   - 현재 `plan()` 메서드를 `execute()` 로 전환하는 구체적 설계
   - Multi-turn conversation context 관리

2. **MCP 도구 In-Process 실행** (새 모듈 또는 bridge.py 확장)
   - FastMCP 도구를 in-process로 직접 호출하는 방법 (MCP 프로토콜 오버헤드 없이)
   - `@mcp.tool()` 데코레이터로 등록된 함수를 직접 import하여 실행하는 전략
   - 도구 실행 결과를 Gemini에게 돌려보내는 포맷

3. **chat.py 단순화**
   - 현재 750+ 라인의 `handleMessage`를 어떻게 축소할 수 있는지
   - WebSocket 메시지 프로토콜 변경 (필요시)
   - 실시간 progress 스트리밍 유지 방법

4. **compute.py 정리**
   - 어떤 함수를 삭제하고 어떤 함수를 유지할지
   - `_prepare_payload`, `_merge_plan_into_payload` 등 중간 레이어 제거 계획

> **출력 형식**: 각 파일별 `[NEW]` / `[MODIFY]` / `[DELETE]` 태그 + 변경 내용 요약

---

### Task 3: 점진적 마이그레이션 로드맵 (Migration Roadmap)

기존 기능을 **깨뜨리지 않으면서** 단계별로 전환하는 계획:

**Phase 1 — Foundation (기존 기능 유지)**

- Gemini function calling + MCP 도구 매핑 레이어만 구축
- 기존 직접호출 경로는 폴백으로 유지
- 양쪽 경로 모두 동작하는 "이중 모드" 상태

**Phase 2 — Migration (경로 전환)**

- 기능별로 하나씩 MCP 경로로 전환
- 각 전환마다 테스트 검증
- 직접호출 경로에 deprecation warning 추가

**Phase 3 — Cleanup (레거시 제거)**

- 모든 기능이 MCP 경로로 전환된 후
- 직접호출 경로 코드 삭제
- 테스트 스위트 정리

> 각 Phase에 대해: **구체적 작업 항목**, **예상 소요 시간**, **검증 방법**, **롤백 전략**을 명시하세요.

---

### Task 4: 리스크 분석 & 완화 전략

| 리스크 | 가능성 | 영향도 | 완화 전략 |
| ------ | ------ | ------ | --------- |

위 형식으로 다음 리스크를 분석하세요:

1. **Gemini API 비용 증가** — 도구 스키마 토큰 비용, multi-turn 비용
2. **레이턴시 증가** — 단일 API 호출 vs function calling 왕복
3. **Gemini API 다운** — 현재 heuristic 폴백이 있는데, 통합 후에도 유지되는지
4. **잘못된 도구 호출** — Gemini가 엉뚱한 파라미터로 도구 호출
5. **보안** — Gemini가 임의 파라미터를 보낼 수 있으므로 추가 검증 필요
6. **Frontend 호환성** — WebSocket 메시지 프로토콜 변경 시 프론트엔드 영향
7. **테스트 커버리지** — 기존 102개 pytest가 깨질 가능성

---

### Task 5: 숨겨진 기회 보고서 (Hidden Opportunities)

내가 아직 인식하지 못한 관점에서, MCP 통합이 열어주는 가능성을 분석하세요:

1. **도구 체이닝으로 가능해지는 새 워크플로우**
   - 예: "이 분자의 HOMO-LUMO gap이 왜 이렇게 큰지 분석해줘" → resolve → SCF → orbital → Gemini가 결과 해석 → 추가 basis 계산 → 비교 분석
   - 현재 불가능하지만 통합 후 가능해지는 구체적 시나리오 5개 이상

2. **AI Agent 자율성**
   - Gemini가 스스로 판단하여 도구를 체이닝할 수 있는 시나리오
   - 에러 복구, 파라미터 자동 조정, 결과 해석 등

3. **확장 가능성**
   - 새 도구 추가가 얼마나 쉬워지는지 (before vs after)
   - 다른 AI 모델 (Claude, GPT 등)이 동일 MCP 도구를 쓸 수 있는 가능성
   - MCP 생태계와의 통합 가능성

4. **업계 트렌드 관점**
   - MCP 프로토콜의 현재 위치와 미래
   - AI Agent 프레임워크 (LangChain, CrewAI, AutoGen 등)와의 관계
   - 이 아키텍처가 학술/산업 양자화학 커뮤니티에서 갖는 의미

5. **내가 놓치고 있을 수 있는 함정**
   - 대규모 cube 데이터를 Gemini 컨텍스트로 반환할 때의 토큰 문제
   - 장시간 계산 (5분+) 중 Gemini API 타임아웃
   - 동시 사용자 시 Gemini API rate limiting

---

## 📐 CONSTRAINTS (제약 조건)

1. **기술 스택 유지**: FastAPI, PySCF, FastMCP, Gemini API (google-genai). 새 프레임워크 도입 최소화.
2. **테스트 호환**: 기존 102개 pytest 통과 유지.
3. **점진적 전환**: Big-bang 리팩토링 금지. Phase별 단계적 전환.
4. **Frontend 최소 변경**: chat.js, viewer.js 변경 최소화. WebSocket 프로토콜은 가급적 유지.
5. **비용 의식**: Gemini API 비용이 현재 대비 3배를 넘지 않도록.
6. **보안 유지**: security.py의 모든 검증 로직 보존.

---

## 📦 OUTPUT FORMAT (출력 형식)

다음 구조의 마크다운 문서로 출력하세요:

```markdown
# QCViz-MCP v3 — MCP 통합 아키텍처 분석 보고서

## 1. 현재 상태 진단

### 1.1 이중 경로 매핑 테이블

### 1.2 구조 해석 경로 차이

### 1.3 에러 전파 맵

### 1.4 제거 가능 코드

### 1.5 보존 필수 코드

## 2. MCP 통합 아키텍처 설계

### 2.1 Gemini Function Calling 레이어

### 2.2 MCP 도구 In-Process 실행

### 2.3 chat.py 단순화

### 2.4 compute.py 정리

## 3. 점진적 마이그레이션 로드맵

### Phase 1: Foundation

### Phase 2: Migration

### Phase 3: Cleanup

## 4. 리스크 분석 & 완화 전략

## 5. 숨겨진 기회 보고서

### 5.1 새 워크플로우

### 5.2 AI Agent 자율성

### 5.3 확장 가능성

### 5.4 업계 트렌드

### 5.5 잠재적 함정
```

---

## ⚡ CHAIN-OF-THOUGHT GUIDANCE

분석 시 다음 순서로 사고하세요:

1. **먼저** 소스 코드에서 `@mcp.tool()` 데코레이터가 붙은 모든 함수를 찾으세요 → 이것이 MCP 도구의 전체 목록입니다.
2. **그 다음** `compute.py`의 `JOB_TYPE_TO_TOOL` 매핑과 `_prepare_payload()` 함수를 보세요 → 이것이 웹 UI의 하드코딩된 경로입니다.
3. **비교**하여 어떤 MCP 도구가 웹 직접호출과 중복되는지 매핑하세요.
4. **agent.py**의 `_plan_with_gemini()` 메서드를 보세요 → 현재 Gemini가 JSON만 반환하고 도구를 호출하지 않는 것을 확인하세요.
5. **chat.py**의 `handleMessage()` 흐름을 따라가세요 → plan → prepare → submit → stream 순서에서 어떤 것이 Gemini function calling으로 대체될 수 있는지.
6. **결론**을 도출하세요 → 구체적 변경 계획.

---

## 🔑 KEY FILES TO FOCUS ON

| 우선순위 | 파일                             | 이유                                              |
| -------- | -------------------------------- | ------------------------------------------------- |
| ⭐⭐⭐   | `llm/agent.py`                   | Gemini 호출 로직 — function calling으로 전환 대상 |
| ⭐⭐⭐   | `tools/core.py`                  | MCP 도구 정의 — 통합의 "진실의 원천"              |
| ⭐⭐⭐   | `web/routes/chat.py`             | WebSocket 핸들러 — 단순화 대상                    |
| ⭐⭐⭐   | `web/routes/compute.py`          | 하드코딩 직접호출 — 제거 대상                     |
| ⭐⭐     | `mcp_server.py`                  | FastMCP 서버 엔트리포인트                         |
| ⭐⭐     | `compute/pyscf_runner.py`        | 실제 PySCF 계산 — MCP 도구가 이미 이걸 호출       |
| ⭐⭐     | `services/gemini_agent.py`       | GeminiAgent 클래스 — function calling 스키마      |
| ⭐       | `services/structure_resolver.py` | 구조 해석 — MCP 도구 통합 대상                    |
| ⭐       | `web/static/chat.js`             | Frontend — 프로토콜 변경 영향 확인                |
