"""Build trimmed MCP Architecture Analysis: ~9000 lines, core logic only."""
import os, re

BASE = r"D:\20260305_양자화학시각화MCP서버구축\version03"
SRC = os.path.join(BASE, "src", "qcviz_mcp")
OUT = os.path.join(BASE, "MCP_ARCHITECTURE_ANALYSIS.md")

# (label, path, max_lines_or_None, skip_patterns)
# max_lines=None means include all, otherwise truncate after N lines
# For very large files we take only the first N lines + "... truncated"

CORE_FILES = [
    # Config & entry
    ("pyproject.toml", os.path.join(BASE, "pyproject.toml"), None),
    ("config.py", os.path.join(SRC, "config.py"), None),
    ("mcp_server.py", os.path.join(SRC, "mcp_server.py"), None),

    # MCP Tools — THE core interface
    ("tools/core.py", os.path.join(SRC, "tools", "core.py"), 500),
    ("tools/advisor_tools.py", os.path.join(SRC, "tools", "advisor_tools.py"), None),

    # LLM / Agent — how Gemini is used
    ("llm/agent.py", os.path.join(SRC, "llm", "agent.py"), 500),
    ("llm/bridge.py", os.path.join(SRC, "llm", "bridge.py"), None),
    ("services/gemini_agent.py", os.path.join(SRC, "services", "gemini_agent.py"), None),

    # Structure resolution — where molecule failures happen
    ("services/structure_resolver.py", os.path.join(SRC, "services", "structure_resolver.py"), None),
    ("services/pubchem_client.py", os.path.join(SRC, "services", "pubchem_client.py"), None),
    ("services/molchat_client.py", os.path.join(SRC, "services", "molchat_client.py"), 150),
    ("services/ion_pair_handler.py", os.path.join(SRC, "services", "ion_pair_handler.py"), None),
    ("services/ko_aliases.py", os.path.join(SRC, "services", "ko_aliases.py"), 80),

    # Compute — the "direct call" path (to be replaced)
    ("compute/pyscf_runner.py", os.path.join(SRC, "compute", "pyscf_runner.py"), 600),
    ("compute/job_manager.py", os.path.join(SRC, "compute", "job_manager.py"), 200),

    # Web routes — WebSocket and REST
    ("web/routes/chat.py", os.path.join(SRC, "web", "routes", "chat.py"), 500),
    ("web/routes/compute.py", os.path.join(SRC, "web", "routes", "compute.py"), 700),

    # Backends — actual PySCF wrappers
    ("backends/pyscf_backend.py", os.path.join(SRC, "backends", "pyscf_backend.py"), 300),
    ("backends/viz_backend.py", os.path.join(SRC, "backends", "viz_backend.py"), 200),

    # Security
    ("security.py", os.path.join(SRC, "security.py"), None),

    # Frontend  
    ("web/templates/index.html", os.path.join(SRC, "web", "templates", "index.html"), 350),
    ("web/static/chat.js", os.path.join(SRC, "web", "static", "chat.js"), 500),
    ("web/static/app.js", os.path.join(SRC, "web", "static", "app.js"), 200),
    ("web/static/viewer.js", os.path.join(SRC, "web", "static", "viewer.js"), 300),
    ("web/static/results.js", os.path.join(SRC, "web", "static", "results.js"), 200),
]

def trim_content(content, max_lines):
    """Smart trim: remove consecutive blank lines, docstring bodies, long comments."""
    lines = content.split("\n")
    
    # Remove consecutive blank lines (keep max 1)
    trimmed = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        trimmed.append(line)
        prev_blank = is_blank
    
    # If still too long and max_lines set, truncate
    if max_lines and len(trimmed) > max_lines:
        trimmed = trimmed[:max_lines]
        trimmed.append(f"\n# ... (truncated at {max_lines} lines, {len(lines) - max_lines} lines omitted) ...")
    
    return "\n".join(trimmed)

HEADER = """# QCViz-MCP v3 — MCP-Unified AI Agent Architecture Analysis

> **작업 지시 프롬프트 (Task Instruction Prompt)**
>
> 아래에 QCViz-MCP v3 프로젝트의 **핵심 소스 코드**가 포함되어 있습니다.
> 이 코드를 완전히 이해한 후, 아래 요청사항에 대해 **구체적이고 실행 가능한 분석**을 제공해주세요.

---

## 📋 프로젝트 개요

**QCViz-MCP**는 PySCF 기반 양자화학 계산을 웹 브라우저에서 수행하고 시각화하는 풀스택 애플리케이션입니다.

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla JS, 3Dmol.js, WebSocket |
| **Backend** | FastAPI, Uvicorn, WebSocket |
| **Computation** | PySCF (DFT/HF), NumPy, SciPy |
| **AI Planning** | Gemini API (google-genai) |
| **MCP Server** | FastMCP (`@mcp.tool()` decorator) |
| **Structure Resolution** | PubChem REST, MolChat API |

---

## 🔴 현재 아키텍처의 문제점: 이중 경로 (Dual Path)

```
경로 1 — MCP 클라이언트 (Claude Desktop, Gemini CLI):
  Client → MCP Protocol → @mcp.tool() (core.py) → PySCF

경로 2 — 웹 UI (브라우저):
  Browser → WebSocket → Gemini API (플래너만) → 하드코딩 직접호출 (compute.py) → PySCF
```

문제점:
1. MCP 도구(`core.py`)와 웹 직접호출(`compute.py`→`pyscf_runner.py`)이 같은 기능을 다르게 구현
2. Gemini는 JSON 플래너일 뿐 — 도구를 직접 호출하지 않음
3. PubChem 실패 시 자동 재시도 없음 — Gemini가 실패를 모름
4. "구조해석→SCF→시각화" 같은 multi-step 도구 체이닝 불가
5. intent→함수 하드코딩 매핑 — 새 도구 추가 시 양쪽 다 수정 필요

---

## 🟢 목표: MCP-Unified AI Agent Architecture

```
통합 후:
  모든 클라이언트 → Gemini Function Calling → MCP @mcp.tool() → PySCF

웹 UI 플로우:
  Browser → WebSocket(chat.py) → Gemini(function calling) → MCP tool in-process
      ↑                                    │
      └── 실시간 스트리밍 ◀── Gemini 결과 해석 + 추가 도구 호출 결정
```

핵심 변경:
1. Gemini에 MCP 도구 스키마를 function declaration으로 전달
2. tool_call 반환 → MCP 도구 in-process 실행 → 결과 Gemini에 반환
3. compute.py 직접호출 경로 제거, chat.py 단순화
4. agent.py: plan() → execute() (function calling loop)

---

## 📝 분석 요청사항

### 1. 아키텍처 분석
- 이중 경로 문제의 파일/함수 단위 식별
- MCP 도구 vs 웹 직접호출 기능 중복 목록
- 통합 시 제거 가능한 코드량, 살릴 유틸 함수 분류

### 2. 분자 구조 해석 개선
- PubChem/MolChat 실패 에러 전파 경로
- MCP 통합 시 Gemini 자동 재시도 시나리오
- `structure_resolver.py` vs `MoleculeResolver`(core.py) — 어떤 것을 유지?

### 3. 도구 체이닝 가능성
- multi-step 워크플로우 (resolve → SCF → orbital → ESP)
- Gemini function calling multi-turn에서 구현 방법
- Frontend 실시간 스트리밍 방법

### 4. 에러 핸들링 & 복원력
- 에러 핸들링 부실한 코드 위치
- Gemini 자율 복구 시나리오
- 타임아웃/메모리 초과 graceful degradation

### 5. 비용 & 레이턴시
- 도구 스키마 포함 토큰 비용 추정
- 캐싱 전략, 컨텍스트 윈도우 관리

### 6. 보안
- security.py 검증 유지 여부
- Gemini 임의 파라미터 추가 검증 필요성

### 7. Frontend 영향도
- chat.js 변경, progress 스트리밍 방법

### 8. 내가 놓치고 있는 관점
- 미처 생각하지 못한 이점, 새로운 가능성
- 업계 트렌드 관점, 잠재적 리스크
- 점진적 마이그레이션 전략

---

## 📦 기대 결과물

1. 현재 상태 진단서 — 이중 경로 코드 위치 + 영향
2. MCP 통합 설계 — 파일/함수 단위 변경 계획
3. 마이그레이션 로드맵 — Phase 1~3
4. 리스크 & 완화 전략
5. 숨겨진 기회 보고서

---

## 📂 핵심 소스 코드

"""

lang_map = {"py": "python", "js": "javascript", "html": "html", "css": "css", "toml": "toml"}
parts = [HEADER]
total_lines = 0
count = 0

for item in CORE_FILES:
    label, path = item[0], item[1]
    max_lines = item[2] if len(item) > 2 else None
    
    if not os.path.isfile(path):
        continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    
    content = trim_content(raw, max_lines)
    ext = os.path.splitext(path)[1].lstrip(".")
    lang = lang_map.get(ext, ext)
    n_lines = content.count("\n") + 1
    
    parts.append(f"\n---\n\n## 📄 `{label}` ({n_lines} lines)\n\n")
    parts.append(f"```{lang}\n{content}\n```\n")
    total_lines += n_lines
    count += 1

doc = "".join(parts)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)

sz = os.path.getsize(OUT)
print(f"✅ {OUT}")
print(f"   Files: {count}")
print(f"   Total lines: {total_lines:,}")
print(f"   Document: {sz:,} bytes ({sz//1024} KB)")
