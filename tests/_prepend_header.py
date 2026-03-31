"""Prepend analysis header to MCP_ARCHITECTURE_ANALYSIS.md"""
import os

BASE = r"D:\20260305_양자화학시각화MCP서버구축\version03"
OUT = os.path.join(BASE, "MCP_ARCHITECTURE_ANALYSIS.md")

HEADER = r'''# QCViz-MCP v3 — MCP-Unified AI Agent Architecture Analysis

> **작업 지시 프롬프트 (Task Instruction Prompt)**
>
> 아래에 QCViz-MCP v3 프로젝트의 **모든 핵심 소스 코드** (43개 파일, 638KB, 18,800+ lines)가 포함되어 있습니다.
> 이 코드를 완전히 이해한 후, 아래 요청사항에 대해 **구체적이고 실행 가능한 분석**을 제공해주세요.

---

## 📋 프로젝트 개요

**QCViz-MCP**는 PySCF 기반 양자화학 계산을 웹 브라우저에서 수행하고 시각화하는 풀스택 애플리케이션입니다.

### 기술 스택
| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla JS, 3Dmol.js, WebSocket |
| **Backend** | FastAPI, Uvicorn, WebSocket |
| **Computation** | PySCF (DFT/HF), NumPy, SciPy |
| **AI Planning** | Gemini API (google-genai) |
| **MCP Server** | FastMCP (`@mcp.tool()` decorator) |
| **Structure Resolution** | PubChem REST, MolChat API |
| **Visualization** | Cube files, 3Dmol.js, ESP maps |

### 핵심 기능
- 단일점 에너지 계산 (Single Point)
- 기하구조 최적화 (Geometry Optimization)
- 오비탈 시각화 (HOMO/LUMO → IBO/Canonical cube)
- ESP 맵 (Electrostatic Potential)
- 부분 전하 (Mulliken/IAO)
- 이온쌍 계산 (Ion Pair)
- AI Advisor (방법론 추천, 신뢰도 평가)

---

## 🔴 현재 아키텍처의 문제점

### 이중 경로 (Dual Path Problem)

현재 시스템에는 **동일한 계산 기능에 대해 2개의 서로 다른 경로**가 존재합니다:

```
경로 1: MCP 클라이언트 (Claude Desktop, Gemini CLI)
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Claude/Gemini│────▶│ MCP Protocol │────▶│ @mcp.tool()  │────▶ PySCF
│   CLI        │     │ (stdio/SSE)  │     │ (core.py)    │
└─────────────┘     └──────────────┘     └──────────────┘

경로 2: 웹 UI (브라우저)
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Browser      │────▶│ WebSocket    │────▶│ Gemini API   │────▶│ 하드코딩된    │────▶ PySCF
│ (chat.js)    │     │ (chat.py)    │     │ (플래너만)    │     │ 직접 호출     │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

### 문제점 상세

1. **코드 중복**: MCP 도구 (`core.py`)와 웹 직접호출 (`compute.py` → `pyscf_runner.py`)이 같은 기능을 다르게 구현
2. **Gemini의 제한된 역할**: 현재 Gemini는 JSON 플래너일 뿐 — "어떤 계산을 할지" 결정만 하고, 실제 도구는 하드코딩된 매핑으로 호출
3. **구조 해석 실패**: PubChem 실패 시 자동 재시도/대안 로직 없음 — Gemini가 실패를 인지하지 못함
4. **도구 체이닝 불가**: "물 HOMO 계산" → 현재는 단일 job만 가능. "구조 해석 → SCF → 오비탈 시각화" 같은 multi-step 불가
5. **하드코딩된 intent→함수 매핑**: `JOB_TYPE_TO_TOOL` 딕셔너리가 intent를 함수로 매핑 — 새 도구 추가 시 매핑도 수정 필요
6. **일관성 없는 동작**: MCP로 실행하면 되는 기능이 웹 UI에서는 안 되는 경우 발생
7. **이온쌍 처리 복잡**: `ion_pair_handler.py`의 로직이 `compute.py`에 직접 결합 — MCP 도구에서는 별도 구현

---

## 🟢 목표: MCP-Unified AI Agent Architecture

### 제안하는 통합 아키텍처

```
[모든 클라이언트]
┌─────────────┐     ┌──────────────┐
│ Claude CLI   │────▶│              │
├─────────────┤     │              │     ┌──────────────┐
│ Gemini CLI   │────▶│  MCP Server  │────▶│ @mcp.tool()  │────▶ PySCF
├─────────────┤     │  (FastMCP)   │     └──────────────┘
│ Web UI       │────▶│              │
│ (chat.js)    │     │              │
└─────────────┘     └──────────────┘

웹 UI 내부 구조 (변경):
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Browser      │────▶│ WebSocket    │────▶│ Gemini API   │────▶│ MCP Tool     │
│ (chat.js)    │     │ (chat.py)    │     │ Function     │     │ In-Process   │
│              │     │              │     │ Calling      │     │ Execution    │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                               │                     │
                                               │  tool_call 결과 반환  │
                                               │◀────────────────────│
                                               │
                                               ▼
                                         Gemini가 결과 해석
                                         + 추가 도구 호출 결정
                                         + 최종 응답 생성
```

### 핵심 변경사항

1. **Gemini를 MCP 클라이언트로 전환**
   - `generate_content()` 호출 시 MCP 도구 스키마를 function declaration으로 전달
   - Gemini가 `tool_call`을 반환하면 → 해당 MCP 도구를 in-process로 직접 실행
   - 실행 결과를 Gemini에게 돌려보내서 판단/요약/추가 호출 결정

2. **compute.py의 직접 호출 제거**
   - `_prepare_payload()`, `JOB_TYPE_TO_TOOL`, `_resolve_structure_async()` 등 하드코딩 제거
   - 모든 계산을 MCP 도구 통해서만 실행

3. **chat.py 단순화**
   - WebSocket 핸들러가 Gemini function calling loop만 관리
   - 구조 해석, 계산 파라미터 결정 등은 모두 Gemini + MCP 도구가 처리

4. **agent.py 리팩토링**
   - `QCVizAgent.plan()` → `QCVizAgent.execute()` (도구 실행까지 포함)
   - Function calling loop 구현 (tool_call → execute → result → continue)

---

## 📝 분석 요청사항

아래 코드를 모두 읽은 후, 다음 항목에 대해 **구체적이고 실행 가능한 분석**을 제공해주세요.

### 1. 아키텍처 분석

- 현재 코드에서 "이중 경로" 문제가 구체적으로 어디에서 발생하는지 파일/함수 단위로 식별
- MCP 도구 (`core.py`, `advisor_tools.py`)와 웹 직접호출 경로 (`compute.py`, `pyscf_runner.py`)의 기능 중복 목록
- 통합 시 제거 가능한 코드량 추정 (라인 수)
- 통합 시 `compute.py`에서 살려야 할 유틸리티 함수 vs 제거할 함수 분류

### 2. 분자 구조 해석 (Structure Resolution) 개선

- 현재 PubChem/MolChat 실패 시 에러가 전파되는 정확한 코드 경로
- MCP 통합 시 Gemini가 자동 재시도할 수 있는 구체적 시나리오들
- `structure_resolver.py` vs `MoleculeResolver` (core.py) — 어떤 것을 MCP 도구로 유지할지
- 한국어 분자명 → 영어 변환이 현재 어디서 처리되고, 어떻게 개선할 수 있는지

### 3. 도구 체이닝 (Tool Chaining) 가능성

- 현재 단일 job으로 제한된 것들 중 multi-step으로 개선 가능한 워크플로우
- 예시: "메탄올 전체 분석" → resolve_structure → single_point → orbital_preview → esp_map → partial_charges
- Gemini function calling의 multi-turn 구조에서 어떻게 구현할 수 있는지
- 각 단계의 결과를 Frontend에 실시간 스트리밍하는 방법

### 4. 에러 핸들링 & 복원력

- 현재 에러 핸들링이 부실한 구체적 코드 위치 (PubChem 실패, MolChat 실패, PySCF 크래시 등)
- MCP 통합 시 Gemini가 에러를 보고 자율적으로 복구할 수 있는 시나리오
- WebSocket 연결 안정성 개선 방안
- 계산 타임아웃/메모리 초과 시 graceful degradation 전략

### 5. 비용 & 레이턴시 최적화

- Gemini function calling에 MCP 도구 스키마를 포함할 때의 토큰 비용 추정
- 현재 단일 API 호출 vs function calling multi-turn의 레이턴시 차이
- 캐싱 전략: 어떤 것을 캐싱해서 반복 호출을 줄일 수 있는지
- 비용 최적화: 도구 스키마 축약, few-shot 예시, 컨텍스트 윈도우 관리

### 6. 보안 & 샌드박싱

- 현재 `security.py`의 보안 검증이 MCP 통합 시에도 유지되는지
- Gemini가 임의의 도구 파라미터를 보낼 수 있으므로, 추가 필요한 검증
- Rate limiting, input sanitization, output size 제한 등

### 7. Frontend 영향도

- `chat.js`에서 변경해야 할 부분 (WebSocket 메시지 프로토콜 변경 등)
- `viewer.js`, `results.js`에 영향이 있는지
- 실시간 progress 스트리밍을 유지하면서 MCP 도구에서 어떻게 progress를 전달할지
- `index.html`의 store 구조 변경 필요성

### 8. 내가 놓치고 있는 관점 (Critical Perspectives I'm Missing)

- MCP-Unified 아키텍처로 전환 시 얻을 수 있는 **내가 미처 생각하지 못한 이점**들
- 이 아키텍처가 열어주는 **새로운 가능성/기능**들 (현재 불가능하지만 통합 후 가능해지는 것)
- 업계 트렌드 관점에서 이 접근법의 위치 (MCP 생태계, AI Agent 프레임워크 등)
- 잠재적 리스크나 함정 (현재 코드에서 구체적으로 어떤 부분이 문제가 될 수 있는지)
- 점진적 마이그레이션 전략: 기존 기능을 깨뜨리지 않으면서 단계별로 전환하는 방법

---

## 📦 기대하는 결과물

1. **현재 상태 진단서** — 이중 경로 문제의 구체적 코드 위치와 영향 분석
2. **MCP 통합 아키텍처 설계** — 파일/함수 단위의 구체적 변경 계획
3. **점진적 마이그레이션 로드맵** — Phase 1~3 단계별 작업 항목
4. **리스크 & 완화 전략** — 발생 가능한 문제와 해결 방안
5. **숨겨진 기회 보고서** — 내가 놓치고 있는 이점/가능성

---

## 📂 소스 코드 (43 files, 638KB, 18,800+ lines)

아래부터 프로젝트의 모든 핵심 소스 코드가 포함되어 있습니다.

'''

# Read existing content
with open(OUT, "r", encoding="utf-8") as f:
    existing = f.read()

# Write header + existing content
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HEADER)
    f.write(existing)

total = os.path.getsize(OUT)
print(f"✅ Final document: {total:,} bytes ({total/1024:.1f} KB)")
