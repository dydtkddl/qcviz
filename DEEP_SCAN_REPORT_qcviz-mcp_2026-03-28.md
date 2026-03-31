# QCViz-MCP Deep Scan Integrated Report

- Project: `qcviz-mcp`
- Repository Root: `D:\20260305_양자화학시각화MCP서버구축\version03`
- Generated At: `2026-03-28 17:29:57 +09:00`
- Scope: Phase 0-10 스캔 결과를 기반으로 작성한 5대 핵심 문서 통합본
- Note: 저장소에 없는 Docker, CI/CD, IaC, `.env.example`, 공식 마이그레이션 파일은 존재하지 않는 것으로 문서화했다.

## Table of Contents

1. [📄 DOCUMENT 1 — ARCHITECTURE.md](#-document-1--architecturemd)
2. [📄 DOCUMENT 2 — DATA_MODEL.md](#-document-2--data_modelmd)
3. [📄 DOCUMENT 3 — API_REFERENCE.md](#-document-3--api_referencemd)
4. [📄 DOCUMENT 4 — DEVELOPMENT_SETUP.md](#-document-4--development_setupmd)
5. [📄 DOCUMENT 5 — PROJECT_CONTEXT.md](#-document-5--project_contextmd)
6. [Scan Metadata](#scan-metadata)

---

# 📄 DOCUMENT 1 — ARCHITECTURE.md

## 1. Executive Summary

### 1.1 프로젝트 한 줄 정의

QCViz-MCP는 자연어 입력을 양자화학 계산 작업으로 변환하고, PySCF 결과를 웹 UI와 3D 시각화로 제공하는 FastAPI 기반 양자화학 워크스페이스다.

### 1.2 핵심 비즈니스 목표

- 사용자가 분자명이나 자연어 요청만으로 계산을 시작할 수 있어야 한다.
- 구조 해석, 계산 제출, 진행률 추적, 결과 설명, 3D 시각화가 하나의 웹 워크스페이스 안에서 이어져야 한다.
- 전문가가 아니어도 HOMO/LUMO, ESP map, 전하, 최적화 같은 대표 분석을 빠르게 수행할 수 있어야 한다.
- 분자 구조 해석 실패 시 MolChat, PubChem, 수동 보정, 후속 질문 흐름을 통해 작업 중단을 줄여야 한다.
- 향후 웹 서버와 계산 워커를 분리 가능한 구조로 유지해 단일 프로세스 개발 모드와 Redis/Arq 운영 모드를 모두 지원해야 한다.

### 1.3 기술적 미션 스테이트먼트

- `src/qcviz_mcp/web`는 브라우저와의 상호작용을 책임진다.
- `src/qcviz_mcp/compute`는 PySCF 실행과 디스크 캐시를 책임진다.
- `src/qcviz_mcp/services`는 MolChat, PubChem, Gemini 등 외부 서비스 연계를 책임진다.
- `src/qcviz_mcp/llm`은 자연어 계획 수립과 follow-up 해석을 책임진다.
- `src/qcviz_mcp/advisor`는 계산 결과의 방법 추천, 신뢰도 평가, 스크립트 제안 같은 후처리 조언을 책임진다.
- 현재 구조는 모듈러 모놀리스이며, 큐 기반 외부 워커는 선택적 확장 모드다.

### 1.4 저장소 기준 현재 아키텍처 상태

- 웹 우선 아키텍처가 현재 주 경로다.
- 레거시 MCP 툴 경로가 병존한다.
- 단일 프로세스 실행이 기본값이다.
- Redis/Arq 백엔드는 선택 사항이다.
- 프런트엔드는 서버 템플릿 + 순수 JavaScript + 3Dmol.js 조합이다.
- 정식 SPA 빌드 시스템은 없다.
- 영속 저장은 SQLite, Redis, 파일시스템, 메모리 저장소가 혼합돼 있다.

## 2. System Context (C4 Level 1)

### 2.1 시스템 컨텍스트 다이어그램

```text
+--------------------+           HTTPS / WS           +---------------------------+
| End User           | <----------------------------> | QCViz-MCP Web Application |
| - Browser user     |                                | - FastAPI                 |
| - Researcher       |                                | - Chat / Compute API      |
+--------------------+                                +-------------+-------------+
                                                                    |
                                                                    |
                                               +--------------------+--------------------+
                                               |                                         |
                                               v                                         v
                                   HTTPS / SDK calls                          Redis protocol (optional)
                           +---------------------------+                    +---------------------------+
                           | External AI / Chem APIs   |                    | Redis / Arq Runtime       |
                           | - MolChat                 |                    | - Job queue               |
                           | - PubChem                 |                    | - Job store               |
                           | - Gemini / OpenAI         |                    | - Worker heartbeat        |
                           +---------------------------+                    +-------------+-------------+
                                                                                          |
                                                                                          v
                                                                                +----------------------+
                                                                                | Arq Worker (optional)|
                                                                                | - PySCF execution    |
                                                                                +----------------------+
```

### 2.2 외부 액터 및 통신 방식

| 외부 액터 | 역할 | 통신 방식 | 실제 코드 접점 |
|---|---|---|---|
| 브라우저 사용자 | 자연어 입력, 계산 제출, 결과 탐색 | HTTP, WebSocket | `src/qcviz_mcp/web/app.py`, `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/routes/compute.py` |
| MolChat API | 분자 이름을 구조/XYZ 후보로 변환 | HTTP via `httpx` | `src/qcviz_mcp/services/molchat_client.py`, `src/qcviz_mcp/services/structure_resolver.py` |
| PubChem API | 구조 해석 폴백 | HTTP via `httpx` | `src/qcviz_mcp/services/pubchem_client.py`, `src/qcviz_mcp/services/structure_resolver.py` |
| Gemini API | 자연어 planning 및 chat response | SDK/API | `src/qcviz_mcp/llm/agent.py`, `src/qcviz_mcp/services/gemini_agent.py` |
| OpenAI API | 선택적 planning 제공자 | SDK/API | `src/qcviz_mcp/llm/agent.py` |
| SQLite 파일 | 사용자/토큰 저장 | 로컬 파일 I/O | `src/qcviz_mcp/web/auth_store.py` |
| Redis | 선택적 잡 저장소와 워커 상태 | Redis protocol | `src/qcviz_mcp/web/redis_job_store.py`, `src/qcviz_mcp/web/arq_backend.py`, `src/qcviz_mcp/worker/arq_worker.py` |
| 파일시스템 캐시 | SCF 체크포인트 및 메타 저장 | 로컬 파일 I/O | `src/qcviz_mcp/compute/disk_cache.py` |
| 3Dmol.js CDN | 브라우저 분자 시각화 | 브라우저 JS 로드 | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/viewer.js` |

### 2.3 시스템 경계

- 시스템 경계 안쪽 핵심은 `src/qcviz_mcp` 패키지다.
- 계산 엔진은 외부 독립 마이크로서비스가 아니라 동일 코드베이스 안의 Python 모듈이다.
- 웹과 워커를 프로세스 단위로 분리할 수 있지만 코드 수준에서는 하나의 모놀리식 저장소다.
- 데이터 저장소 역시 분산 DB 계층이 아니라 목적별 혼합 저장 구조다.

## 3. Container Diagram (C4 Level 2)

### 3.1 컨테이너 배치도

```text
+--------------------------------------------------------------------------------------+
| Browser Container                                                                    |
| - index.html                                                                         |
| - static/app.js                                                                      |
| - static/chat.js                                                                     |
| - static/results.js                                                                  |
| - static/viewer.js                                                                   |
+------------------------------------------+-------------------------------------------+
                                           |
                                           | HTTP / WebSocket
                                           v
+--------------------------------------------------------------------------------------+
| FastAPI Web Container                                                                |
| - src/qcviz_mcp/web/app.py                                                           |
| - src/qcviz_mcp/web/routes/chat.py                                                   |
| - src/qcviz_mcp/web/routes/compute.py                                                |
| - session/auth/admin routes                                                          |
+-------------------------+-------------------------+---------------------+-------------+
                          |                         |                     |
                          | in-process call         | file I/O            | HTTP / SDK
                          v                         v                     v
+-------------------------+--+       +-------------+-------------+   +---+----------------------+
| Compute Container          |       | Local Persistence         |   | External Services        |
| - pyscf_runner.py          |       | - SQLite auth DB          |   | - MolChat               |
| - disk_cache.py            |       | - Session memory store    |   | - PubChem               |
| - advisor_flow.py          |       | - Conversation memory     |   | - Gemini / OpenAI       |
+----------------------------+       | - Disk SCF cache          |   +--------------------------+
                                     +-------------+-------------+
                                                   |
                                                   | optional Redis protocol
                                                   v
                                     +-------------+-------------+
                                     | Redis / Arq Container     |
                                     | - queue                   |
                                     | - job records             |
                                     | - session state           |
                                     | - worker heartbeats       |
                                     +-------------+-------------+
                                                   |
                                                   | worker execution
                                                   v
                                     +-------------+-------------+
                                     | Worker Container          |
                                     | - src/qcviz_mcp/worker    |
                                     | - arq_worker.py           |
                                     +---------------------------+
```

### 3.2 컨테이너별 책임

| 컨테이너 | 책임 | 주요 파일 | 프로토콜 |
|---|---|---|---|
| Browser | 사용자 입력, 상태 보관, 결과 렌더링, 3D 뷰어 | `web/templates/index.html`, `web/static/*.js` | HTTP, WebSocket |
| FastAPI Web | API, 인증, 세션 부트스트랩, 채팅, 계산 제출, 관리자 화면 | `web/app.py`, `web/routes/chat.py`, `web/routes/compute.py` | HTTP, WebSocket |
| Compute Engine | PySCF 계산, 결과 정규화, 오비탈 큐브, 캐시 재사용 | `compute/pyscf_runner.py`, `compute/disk_cache.py` | in-process Python call |
| Local Persistence | 사용자/토큰/세션/대화 상태/파일 캐시 | `web/auth_store.py`, `web/session_auth.py`, `web/conversation_state.py`, `compute/disk_cache.py` | SQLite, memory, filesystem |
| Redis/Arq | 선택적 비동기 큐, 이벤트 저장, 하트비트, 복구 | `web/redis_job_store.py`, `web/arq_backend.py` | Redis protocol |
| Worker | 웹 프로세스와 분리된 계산 실행 | `worker/arq_worker.py` | Arq job execution |
| External Services | 구조 해석 및 LLM planning | `services/*`, `llm/*` | HTTP / SDK |

### 3.3 컨테이너 간 통신 규칙

- 브라우저는 `/chat`, `/compute/jobs`, `/auth/*`, `/session/bootstrap`에 HTTP로 접근한다.
- 브라우저는 `/ws/chat`으로 WebSocket 연결을 유지한다.
- `chat.py`는 내부적으로 `compute.py`의 잡 매니저를 호출한다.
- `compute.py`는 구조 해석을 위해 `structure_resolver.py`와 `ion_pair_handler.py`를 사용한다.
- 계산 실행은 `_run_direct_compute()`를 통해 `pyscf_runner.py`로 내려간다.
- Redis 모드에서는 웹 서버가 직접 결과를 만들지 않고 백엔드 큐에 제출한다.
- 워커는 Redis에서 잡을 가져와 동일한 계산 엔진을 호출한다.

### 3.4 운영 모드

| 모드 | 기본 여부 | 설명 | 관련 코드 |
|---|---|---|---|
| In-memory mode | 기본 | FastAPI 프로세스 내부 스레드풀에서 계산 수행 | `web/routes/compute.py` |
| Redis/Arq mode | 선택 | 웹과 워커를 분리해 Redis에 잡 저장 | `web/job_backend.py`, `web/arq_backend.py`, `worker/arq_worker.py` |

## 4. Component Diagram (C4 Level 3)

### 4.1 핵심 모듈 분해도

```text
[web.app]
  -> mounts templates/static
  -> wires chat router
  -> wires compute router
  -> exposes auth/session/admin endpoints

[web.routes.chat]
  -> session_auth
  -> auth_store
  -> llm.agent / llm.normalizer
  -> web.routes.compute.get_job_manager
  -> conversation_state

[web.routes.compute]
  -> services.structure_resolver
  -> services.ion_pair_handler
  -> compute.pyscf_runner
  -> web.advisor_flow
  -> web.result_explainer
  -> session_auth / auth_store

[compute.pyscf_runner]
  -> PySCF
  -> compute.disk_cache
  -> analysis / validation helpers

[services.structure_resolver]
  -> molchat_client
  -> pubchem_client
  -> charge validation / cache
```

### 4.2 의존성 방향

```text
web/templates + web/static
    |
    v
web/app.py
    |
    +--> web/routes/chat.py
    |        |
    |        +--> llm/agent.py
    |        +--> llm/normalizer.py
    |        +--> web/conversation_state.py
    |        +--> web/routes/compute.py
    |
    +--> web/routes/compute.py
             |
             +--> services/structure_resolver.py
             +--> services/ion_pair_handler.py
             +--> compute/pyscf_runner.py
             +--> web/advisor_flow.py
             +--> web/result_explainer.py
             +--> web/session_auth.py
             +--> web/auth_store.py
```

### 4.3 주요 컴포넌트 카탈로그

| 컴포넌트 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `web.app.create_app()` | FastAPI 앱 조립 | 환경 변수, 라우터, 템플릿 | HTTP/WS 앱 |
| `chat.post_chat()` | REST 채팅 계산 엔드포인트 | 자연어 요청, 세션/토큰 | 계획, 잡, 결과 또는 clarification |
| `chat.websocket_chat()` | 실시간 대화/진행률 스트림 | WS 메시지 | `ready`, `ack`, `assistant`, `clarify`, `job_update`, `result`, `error` |
| `compute.submit_job()` | 계산 잡 제출 | 계산 payload | 잡 스냅샷 또는 완료 결과 |
| `InMemoryJobManager` | 큐, 진행률, 이벤트, 재시도, quota | payload | job snapshot/event/result |
| `structure_resolver` | 분자 구조 해석 | 구조 질의문 | XYZ, atom_spec, charge/multiplicity 힌트 |
| `ion_pair_handler` | 이온쌍/염 분리 및 조합 | 복합 구조 입력 | 병합 구조 |
| `pyscf_runner` | 실질 계산 엔진 | 준비된 payload | 결과 contract |
| `advisor_flow` | 결과 후처리 | result dict | advisor, script, confidence, literature summary |
| `result_explainer` | 사용자 설명 생성 | result dict | 요약/설명 텍스트 |

### 4.4 실제 코드 예시: 라우트 조립

아래 코드는 세션 부트스트랩 응답을 실제로 어떻게 조립하는지 보여준다.

```python
@app.post("/session/bootstrap")
@app.post("/api/session/bootstrap", include_in_schema=False)
async def session_bootstrap(payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
    body = dict(payload or {})
    session_meta = bootstrap_or_validate_session(
        body.get("session_id"),
        body.get("session_token"),
        allow_new=True,
    )
    return {
        "ok": True,
        **session_meta,
        "routes": {
            "chat_ws": "/ws/chat",
            "chat_rest": "/chat",
            "compute_jobs": "/compute/jobs",
        },
    }
```

소스: `src/qcviz_mcp/web/app.py`

### 4.5 실제 코드 예시: 계산 엔드포인트 인증 헤더

```python
@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
    x_qcviz_session_id: Optional[str] = Header(default=None, alias="X-QCViz-Session-Id"),
    x_qcviz_session_token: Optional[str] = Header(default=None, alias="X-QCViz-Session-Token"),
    x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token"),
) -> Dict[str, Any]:
```

소스: `src/qcviz_mcp/web/routes/compute.py`

## 5. Layer Architecture

### 5.1 레이어 정의

이 프로젝트는 엄격한 클린 아키텍처 구현체는 아니지만, 기능상 다음 레이어로 읽는 것이 가장 정확하다.

1. Presentation Layer
2. Application Layer
3. Domain / Compute Layer
4. Infrastructure Layer

### 5.2 Presentation Layer

- 디렉터리: `src/qcviz_mcp/web/templates`, `src/qcviz_mcp/web/static`
- 주요 파일: `index.html`, `app.js`, `chat.js`, `results.js`, `viewer.js`, `style.css`
- 책임:
- HTML shell 제공
- 사용자 입력 수집
- WebSocket 연결 관리
- 결과 탭 렌더링
- 3Dmol.js 시각화
- 세션/토큰의 브라우저 측 유지

### 5.3 Application Layer

- 디렉터리: `src/qcviz_mcp/web`, `src/qcviz_mcp/llm`, `src/qcviz_mcp/services`
- 주요 파일:
- `web/app.py`
- `web/routes/chat.py`
- `web/routes/compute.py`
- `web/advisor_flow.py`
- `llm/agent.py`
- `llm/normalizer.py`
- `services/structure_resolver.py`
- 책임:
- 요청 조립
- 인증/세션 처리
- 계획 생성
- 구조 해석 orchestration
- job manager 제어
- 응답 contract 조립

### 5.4 Domain / Compute Layer

- 디렉터리: `src/qcviz_mcp/compute`, `src/qcviz_mcp/analysis`, `src/qcviz_mcp/validation`, `src/qcviz_mcp/advisor`
- 주요 파일:
- `compute/pyscf_runner.py`
- `compute/disk_cache.py`
- `advisor/preset_recommender.py`
- `advisor/literature_validator.py`
- `advisor/confidence_scorer.py`
- 책임:
- 양자화학 계산 실행
- 결과 수치 가공
- 오비탈/ESP/전하 계산
- 계산 설정 추천
- 신뢰도 및 재현성 가이드 생성

### 5.5 Infrastructure Layer

- 디렉터리: `src/qcviz_mcp/web`, `src/qcviz_mcp/worker`, `src/qcviz_mcp/services`
- 주요 파일:
- `web/auth_store.py`
- `web/session_auth.py`
- `web/redis_job_store.py`
- `web/arq_backend.py`
- `worker/arq_worker.py`
- `services/molchat_client.py`
- `services/pubchem_client.py`
- 책임:
- SQLite 연결
- Redis 저장소
- 파일 캐시
- 외부 HTTP 클라이언트
- 워커 하트비트 및 큐

### 5.6 레이어 간 데이터 흐름

```text
User Message
 -> chat.js
 -> /chat or /ws/chat
 -> chat.py
 -> llm.normalizer / llm.agent
 -> compute.py payload prep
 -> structure_resolver.py
 -> pyscf_runner.py
 -> advisor_flow.py
 -> result_explainer.py
 -> job manager snapshot/result
 -> chat.py or compute.py response
 -> results.js / viewer.js
```

### 5.7 레이어 맵핑 표

| 레이어 | 실제 디렉터리 | 예시 파일 | 비고 |
|---|---|---|---|
| Presentation | `web/templates`, `web/static` | `index.html`, `chat.js` | 프런트엔드 DOM 중심 |
| Application | `web/routes`, `web/app.py`, `llm`, `services` | `compute.py`, `chat.py` | orchestration 중심 |
| Domain/Compute | `compute`, `analysis`, `advisor`, `validation` | `pyscf_runner.py` | 계산 중심 |
| Infrastructure | `web/auth_store.py`, `web/redis_job_store.py`, `worker` | `arq_worker.py` | 저장소 및 외부 연계 |

### 5.8 경계의 현실적 한계

- `web/routes/compute.py`가 application layer와 infrastructure concern을 동시에 가진다.
- `chat.py`가 대화 프로토콜, clarification, planning, job submission을 함께 가진다.
- `pyscf_runner.py`가 계산 엔진과 결과 contract formatting을 동시에 담당한다.
- 즉, 레이어는 개념적으로 분리되지만 파일 수준 결합은 강하다.

## 6. Design Patterns & Principles

### 6.1 실제 사용 중인 패턴 목록

| 패턴 | 구현 위치 | 설명 |
|---|---|---|
| Router pattern | `web/app.py`, `web/routes/*.py` | FastAPI 라우터로 HTTP/WS 엔드포인트 분리 |
| Manual DI / wiring | `web/app.py`, `web/routes/compute.py` | 컨테이너 없이 함수/모듈 싱글턴으로 조립 |
| Strategy-like provider selection | `llm/agent.py` | OpenAI, Gemini, heuristic planner 중 선택 |
| Repository-like store wrapper | `web/auth_store.py`, `web/redis_job_store.py` | SQLite/Redis 저장 로직 캡슐화 |
| Queue / Worker | `web/arq_backend.py`, `worker/arq_worker.py` | Redis/Arq 기반 비동기 잡 처리 |
| Adapter | `web/advisor_flow.py` | 계산 결과를 advisor 서명에 맞춰 변환 |
| Cache-aside | `compute/disk_cache.py`, `services/structure_resolver.py` | 구조/SCF 결과를 필요 시 조회/갱신 |
| Event stream | `chat.py`, `redis_job_store.py` | progress/event/result를 WS로 전달 |
| Session continuation state | `web/conversation_state.py` | 이전 계산 맥락을 follow-up에 재사용 |

### 6.2 SOLID 준수 현황

#### Single Responsibility

- 잘 지킨 곳:
- `session_auth.py`는 세션 토큰 관리에 집중한다.
- `auth_store.py`는 사용자/토큰 저장과 권한 판별에 집중한다.
- `disk_cache.py`는 SCF 디스크 캐시에 집중한다.

#### Single Responsibility 위반 지점

- `web/routes/compute.py`는 job manager, API, quota, payload normalization, batch execution을 함께 가진다.
- `web/routes/chat.py`는 WS 프로토콜, planning, clarification, job streaming을 함께 가진다.
- `compute/pyscf_runner.py`는 계산, 캐시, 결과 변환, 시각화 준비를 함께 가진다.

#### Open/Closed

- LLM provider 추가는 `llm/agent.py`에 확장 포인트가 있다.
- 그러나 많은 분기 로직이 거대 함수 안에 있어서 완전한 개방-폐쇄 구조는 아니다.

#### Dependency Inversion

- 외부 서비스 클라이언트는 부분적으로 모듈 분리돼 있다.
- 하지만 상위 레이어가 구체 구현을 직접 import하는 방식이 많아 DIP는 약하다.

### 6.3 DRY / KISS / Pragmatism

- DRY 장점:
- 공통 `_safe_*` 함수가 광범위하게 재사용된다.
- 세션/토큰 해석 헬퍼가 라우트 공통 동작을 줄인다.

- DRY 약점:
- `_safe_str`, `_safe_int`, `_json_safe`가 여러 파일에 중복 정의된다.
- 레거시 경로와 신규 경로가 공존하면서 중복 기능이 존재한다.

- KISS 장점:
- 프런트엔드가 번들러 없이 순수 JS로 구성되어 개발 단순성이 높다.
- 기본 실행 모드가 single process라 운영 복잡도를 낮춘다.

- KISS 약점:
- 단순성 대가로 거대 파일이 늘어났다.
- 엄격한 타입 모델 대신 dict contract가 많아 추론 난도가 높다.

### 6.4 실제 코드 예시: 저장소 패턴 유사 구현

```python
def get_auth_user(auth_token: Optional[str]) -> Optional[Dict[str, Any]]:
    token = _safe_str(auth_token)
    if not token:
        return None
    init_auth_db()
    now = _now_ts()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))
        row = conn.execute(
            """
            SELECT u.username, u.display_name, u.role, u.created_at, t.expires_at
            FROM auth_tokens t
            JOIN users u ON u.username = t.username
            WHERE t.token = ? AND t.expires_at >= ? AND u.disabled = 0
            """,
            (token, now),
        ).fetchone()
```

소스: `src/qcviz_mcp/web/auth_store.py`

## 7. Cross-Cutting Concerns

### 7.1 인증(Authentication)

- 사용자 인증은 `X-QCViz-Auth-Token` 헤더 기반이다.
- 익명 세션 인증은 `X-QCViz-Session-Id`와 `X-QCViz-Session-Token` 조합이다.
- 구현 위치:
- `src/qcviz_mcp/web/auth_store.py`
- `src/qcviz_mcp/web/session_auth.py`
- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/routes/chat.py`

### 7.2 인가(Authorization)

- 역할 모델은 `user`와 `admin` 두 수준이다.
- 관리자 검사는 `require_admin_user()`가 수행한다.
- 잡 접근은 소유 사용자명 또는 세션 토큰 일치 여부로 결정한다.
- 구현 위치:
- `auth_store.require_admin_user`
- `compute._assert_job_access`
- `app.admin_*` endpoints

### 7.3 에러 핸들링

- FastAPI `HTTPException`이 주된 비즈니스 오류 전달 방식이다.
- WS 경로는 `_ws_send_error()`로 구조화된 에러 이벤트를 보낸다.
- 잡 실행 실패는 `job.error` 필드와 `job_failed` 이벤트로 저장된다.
- 일부 경로는 400/403/404/500을 명시적으로 사용한다.

### 7.4 로깅

- 표준 Python `logging`을 사용한다.
- JSON structured logging 프레임워크는 없다.
- `config.py`에 `log_level`, `log_json` 필드가 있으나 전체 코드베이스에 일관된 JSON 로깅 적용은 보이지 않는다.
- 예외 로깅은 `logger.exception()` 호출이 중심이다.

### 7.5 캐싱

- 구조 해석 캐시:
- `services/structure_resolver.py`
- SCF 디스크 캐시:
- `compute/disk_cache.py`
- 세션 continuation state:
- `web/conversation_state.py`
- Redis 기반 세션 상태:
- `web/redis_job_store.py`

### 7.6 Quota / Throttling

- 전통적 HTTP rate limiting 미들웨어는 없다.
- 대신 active job quota가 있다.
- 세션별/사용자별 동시 활성 잡 수 제한은 `compute.py`와 `worker/arq_worker.py`에서 환경 변수 기반으로 설정된다.
- 이 제한은 사실상 계산 자원 throttling 역할을 한다.

### 7.7 국제화(i18n)

- 공식 i18n 프레임워크는 없다.
- 한국어와 영어 메시지가 코드 안에 공존한다.
- 일부 한국어 문자열은 인코딩 손상(mojibake) 흔적이 있다.
- 결과적으로 다국어 대응은 부분적이며 체계적이지 않다.

### 7.8 보안

- 비밀번호는 PBKDF2-HMAC-SHA256 + salt 방식으로 저장된다.
- 인증 토큰은 만료 시간이 있다.
- 세션 토큰은 메모리 기반이라 서버 재시작 시 사라진다.
- 저장소 루트 `.env`에 실제 API 키가 커밋되어 있어 운영상 중대한 리스크가 있다.
- WebSocket에서 `auth_token`이 query string으로 전달될 수 있다.

### 7.9 관측성

- health endpoint 존재:
- `/health`
- `/chat/health`
- `/compute/health`
- 관리자 overview 존재:
- `/admin/overview`
- 그러나 metrics backend, tracing, external monitoring exporter는 없다.

## 8. Architecture Decision Records (ADR) 요약

### ADR-01: 서버 렌더링 + 순수 JavaScript 프런트엔드 채택

- 배경:
- 3D 시각화와 계산 API를 빠르게 통합해야 했다.
- 대규모 프런트엔드 빌드 체인 없이 배포 단순성을 유지할 필요가 있었다.

- 고려 대안:
- React/Next.js SPA
- Vue/Vite SPA
- 현재 방식인 Jinja2 + static JS

- 결론:
- 현재 저장소는 `index.html` + `app.js`/`chat.js`/`results.js`/`viewer.js` 형태를 채택했다.

- 결과:
- 장점: 의존성 단순, 서버와 UI 연결이 직접적, 빠른 반복 개발 가능
- 단점: UI 상태가 전역 객체와 DOM 조작에 강하게 결합, 파일 대형화, 타입 안정성 부족

### ADR-02: 기본 실행은 In-Memory Job Manager, 운영 확장은 Redis/Arq

- 배경:
- 개발 환경에서는 즉시 실행되는 단일 프로세스 모드가 필요했다.
- 동시에 웹/워커 분리 가능성도 보존해야 했다.

- 고려 대안:
- Celery/RabbitMQ
- 순수 ThreadPool only
- Redis/Arq hybrid

- 결론:
- `QCVIZ_JOB_BACKEND` 환경 변수로 `inmemory`와 Redis/Arq 계열을 분기하는 구조를 사용한다.

- 결과:
- 장점: 로컬 개발 단순성 유지, 확장 경로 확보
- 단점: 두 경로 동시 유지로 코드 drift 위험 증가

### ADR-03: 사용자 인증은 SQLite, 익명 세션은 In-Memory

- 배경:
- 최소한의 계정 기능과 익명 체험 흐름을 동시에 제공해야 했다.
- 외부 Auth 서비스 도입은 과하다고 판단한 것으로 보인다.

- 고려 대안:
- 외부 OIDC/OAuth
- 전부 익명 세션
- SQLite + 세션 메모리 혼합

- 결론:
- `auth_store.py`는 SQLite에 사용자/토큰을 저장하고, `session_auth.py`는 메모리에 익명 세션을 저장한다.

- 결과:
- 장점: 구현 단순, 설정 부담 적음
- 단점: 세션이 재시작 시 소멸, 다중 인스턴스 확장에 불리

### ADR-04: 구조 해석은 MolChat 우선, PubChem 폴백

- 배경:
- 자연어 기반 분자 질의를 높은 성공률로 해석해야 했다.

- 고려 대안:
- PubChem only
- MolChat only
- MolChat + PubChem fallback

- 결론:
- `structure_resolver.py`가 MolChat 우선 후 PubChem fallback을 사용한다.

- 결과:
- 장점: 해석 성공률 향상
- 단점: 외부 API 의존과 응답 편차 증가

## 9. 아키텍처 리스크 및 관찰 메모

### 9.1 복잡도 핫스팟

- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `src/qcviz_mcp/backends/viz_backend.py`
- `src/qcviz_mcp/web/static/chat.js`
- `src/qcviz_mcp/web/static/app.js`
- `src/qcviz_mcp/web/static/viewer.js`

### 9.2 결합도 높은 지점

- `chat.py`가 `compute.py` 내부 job manager에 직접 의존한다.
- `compute.py`가 planning, continuation, resolver, runner, advisor를 모두 직접 조합한다.
- 프런트엔드는 `window.QCVizApp` 전역 상태에 강하게 결합한다.

### 9.3 변경 영향이 큰 지점

- `pyscf_runner.py` 결과 contract를 변경하면 API, WS, 결과 UI, advisor가 함께 영향을 받는다.
- `conversation_state.py` 키 이름을 바꾸면 follow-up 계산 흐름이 깨질 수 있다.
- 인증 헤더 이름 변경은 프런트엔드와 모든 REST/WS 경로에 영향이 간다.

### 9.4 즉시 개선 우선순위

- 레거시 MCP 경로와 현재 웹 경로의 책임을 분리할 것
- `.env` 비밀값 제거 및 `.env.example` 도입
- `compute.py`와 `chat.py` 분해
- 결과 contract에 대한 명시적 Pydantic 모델 도입 검토
- WebSocket query token 전달 방식 축소 검토

---

# 📄 DOCUMENT 2 — DATA_MODEL.md

## 1. Database Overview

### 1.1 저장 계층 요약

이 저장소는 단일 RDBMS 중심 설계가 아니라 목적별 혼합 저장 구조를 사용한다.

| 저장 계층 | 종류 | 기술 | 연결 형태 | 실제 구현 |
|---|---|---|---|---|
| 사용자/토큰 저장 | 관계형 | SQLite | 단일 로컬 파일 | `web/auth_store.py` |
| 익명 세션 저장 | 메모리 | Python dict | 프로세스 내부 | `web/session_auth.py` |
| 대화 continuation 상태 | 메모리 / Redis | Python dict / Redis JSON | 프로세스 내부 또는 Redis | `web/conversation_state.py`, `web/redis_job_store.py` |
| 잡 저장소 | 메모리 / Redis | Python objects / Redis JSON + zset index | 프로세스 내부 또는 Redis | `web/routes/compute.py`, `web/redis_job_store.py` |
| 계산 캐시 | 파일시스템 | HDF5 + JSON | 로컬 디스크 | `compute/disk_cache.py` |

### 1.2 DB / ORM / ODM 상태

- ORM은 사용하지 않는다.
- SQLite는 `sqlite3` 표준 라이브러리로 직접 다룬다.
- Redis는 low-level client를 사용한 key-value + sorted set 인덱스 패턴이다.
- 파일 캐시는 PySCF 체크포인트 파일과 JSON 메타 파일을 조합한다.

### 1.3 연결 구성

- SQLite: 단일 파일 연결, 읽기 레플리카 없음
- Redis: 단일 URL 기준, 클러스터/샤딩 코드 없음
- 세션 메모리: 프로세스 로컬
- 디스크 캐시: 단일 디렉터리

## 2. Complete Entity-Relationship Diagram

### 2.1 ASCII ERD

```text
+---------------------+          1:N           +----------------------+
| users               | ---------------------> | auth_tokens          |
| PK username         |                        | PK token             |
| display_name        |                        | FK username          |
| password_hash       |                        | created_at           |
| salt                |                        | expires_at           |
| role                |                        +----------------------+
| created_at          |
| disabled            |
+---------------------+

+---------------------+          1:N           +----------------------+
| session_record      | ---------------------> | job_record           |
| PK session_id       |                        | PK job_id            |
| session_token       |                        | session_id           |
| created_at          |                        | owner_username       |
| last_seen_at        |                        | status               |
+---------------------+                        | progress             |
                                               | payload              |
                                               | result               |
                                               | error                |
                                               +----------+-----------+
                                                          |
                                                          | 1:N
                                                          v
                                               +----------------------+
                                               | job_event            |
                                               | event_id             |
                                               | ts                   |
                                               | type                 |
                                               | message              |
                                               | data                 |
                                               +----------------------+

+----------------------+         1:1 / latest      +----------------------+
| session_record       | ----------------------->  | conversation_state   |
| session_id           |                           | session_id           |
+----------------------+                           | last_* fields        |
                                                   | analysis_history     |
                                                   | last_resolved_artifact|
                                                   +----------------------+

+----------------------+         1:N              +----------------------+
| worker_heartbeat     | -----------------------> | running job_record   |
| worker_id            |                          | worker_id            |
| timestamp/ttl        |                          | ...                  |
+----------------------+                          +----------------------+

+----------------------+         cache key        +----------------------+
| scf_cache_meta       | <----------------------> | scf_checkpoint       |
| key                  |                          | key.chk              |
| energy               |                          | HDF5 datasets        |
| chkfile path         |                          +----------------------+
+----------------------+
```

### 2.2 관계 해석

- `users`와 `auth_tokens`만이 실제 SQL foreign key 관계를 가진다.
- 그 외 관계는 애플리케이션 레벨 키 참조다.
- `job_record`와 `conversation_state`는 세션 ID를 중심으로 느슨하게 연결된다.
- Redis 저장소에서는 정규화된 관계보다 조회 편의를 위한 인덱스 키가 더 중요하다.

## 3. Entity Catalog

### 3.1 `users`

비즈니스 의미: 로그인 가능한 사용자 계정과 역할 정보를 담는다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `username` | `TEXT` | PK, not null | 로그인 식별자 |
| `display_name` | `TEXT` | not null | UI 표기명 |
| `password_hash` | `TEXT` | not null | PBKDF2 해시 |
| `salt` | `TEXT` | not null | 비밀번호 salt hex |
| `role` | `TEXT` | not null, default `user` | `user` 또는 `admin` |
| `created_at` | `REAL` | not null | 생성 시각 epoch seconds |
| `disabled` | `INTEGER` | not null, default `0` | 비활성 계정 여부 |

### 3.2 `auth_tokens`

비즈니스 의미: 발급된 사용자 인증 토큰을 저장한다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `token` | `TEXT` | PK, not null | 인증 토큰 |
| `username` | `TEXT` | FK -> `users.username`, not null | 토큰 소유자 |
| `created_at` | `REAL` | not null | 발급 시각 |
| `expires_at` | `REAL` | not null | 만료 시각 |

### 3.3 `session_record` (in-memory logical entity)

비즈니스 의미: 익명 또는 비로그인 사용자의 세션 식별과 지속성을 제공한다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `session_id` | `str` | unique, generated | 클라이언트 세션 식별자 |
| `session_token` | `str` | required for existing session | 세션 검증 토큰 |
| `created_at` | `float` | required | 세션 생성 시각 |
| `last_seen_at` | `float` | required | 마지막 접근 시각 |

### 3.4 `conversation_state`

비즈니스 의미: follow-up 요청이 이전 계산 문맥을 재사용하도록 지원한다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `session_id` | `str` | session scope key | 연결된 세션 |
| `updated_at` | `float` | auto-set | 마지막 갱신 시각 |
| `last_job_id` | `str` | optional | 마지막 계산 잡 ID |
| `last_structure_query` | `str` | optional | 마지막 구조 질의 |
| `last_resolved_name` | `str` | optional | 마지막 해석된 분자명 |
| `last_job_type` | `str` | optional | 마지막 계산 유형 |
| `last_method` | `str` | optional | 마지막 계산 방법 |
| `last_basis` | `str` | optional | 마지막 basis |
| `last_charge` | `int/Any` | optional | 마지막 charge |
| `last_multiplicity` | `int/Any` | optional | 마지막 multiplicity |
| `available_result_tabs` | `list[str]` | derived | 결과 탭 availability |
| `analysis_history` | `list[str]` | dedup merged | 수행된 분석 히스토리 |
| `last_resolved_artifact` | `dict` | optional | XYZ, atom_spec, formula, smiles 등 구조 산출물 |

### 3.5 `job_record` (logical snapshot, in-memory or Redis)

비즈니스 의미: 계산 요청의 전체 수명주기를 표현하는 핵심 엔티티다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `job_id` | `str` | unique | 잡 식별자 |
| `session_id` | `str` | derived from payload | 세션 소유자 |
| `owner_username` | `str` | optional | 로그인 사용자 소유자 |
| `owner_display_name` | `str` | optional | 사용자 표기명 |
| `status` | `str` | lifecycle enum | `queued/running/completed/failed/error/cancelled` |
| `user_query` | `str` | optional | 원래 사용자 질의 |
| `job_type` | `str` | optional | 계산 유형 |
| `retry_count` | `int` | non-negative | 재시도 횟수 |
| `max_retries` | `int` | non-negative | 허용 재시도 수 |
| `retry_origin_job_id` | `str` | optional | 최초 원본 잡 |
| `retry_parent_job_id` | `str` | optional | 직전 부모 잡 |
| `molecule_name` | `str` | optional | 구조 질의에서 파생된 이름 |
| `method` | `str` | optional | 계산 method |
| `basis_set` | `str` | optional | 계산 basis |
| `progress` | `float` | 0.0~1.0 | 진행률 |
| `step` | `str` | optional | 현재 단계 |
| `message` | `str` | optional | 사용자/운영 메시지 |
| `created_at` | `float` | required | 생성 시각 |
| `started_at` | `float` | nullable | 시작 시각 |
| `ended_at` | `float` | nullable | 종료 시각 |
| `updated_at` | `float` | required | 마지막 변경 시각 |
| `payload` | `dict` | optional internal | 실행 입력 전체 |
| `result` | `dict` | optional internal | 계산 결과 contract |
| `error` | `dict` | optional internal | 실패 정보 |
| `events` | `list[dict]` | capped | 이벤트 로그 |

### 3.6 `job_event`

비즈니스 의미: 진행률, 완료, 실패, 제출 같은 상태 변화를 시간순으로 기록한다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `event_id` | `int` | per-job increment | 이벤트 순번 |
| `ts` | `float` | required | 이벤트 시각 |
| `type` | `str` | required | `job_submitted`, `job_progress` 등 |
| `message` | `str` | required | 이벤트 메시지 |
| `data` | `dict` | optional | 추가 페이로드 |

### 3.7 `worker_heartbeat`

비즈니스 의미: 외부 워커가 살아 있는지, 어떤 잡을 처리 중인지 추적한다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `worker_id` | `str` | unique key | 워커 식별자 |
| `timestamp` | `float` | TTL 기반 | 마지막 heartbeat |
| `job_id` | `str` | optional | 현재 처리 중인 잡 |
| `queue` | `str` | optional | 연결된 큐 이름 |
| `status` | `str` | inferred | 생존/유휴/실행 상태 판별 기반 |

### 3.8 `scf_cache_meta`

비즈니스 의미: 계산 재사용을 위한 디스크 캐시 메타 정보다.

| 필드명 | 타입 | 제약조건 | 설명 |
|---|---|---|---|
| `key` | `str` | filename-derived | 구조+method+basis 기반 캐시 키 |
| `energy` | `float` | optional | 저장된 총 에너지 |
| `chkfile` | `str` | required | HDF5 체크포인트 경로 |

### 3.9 `scf_checkpoint` HDF5 dataset

비즈니스 의미: PySCF가 생성한 오비탈 계수와 점유 정보를 저장한다.

| 데이터셋 경로 | 타입 | 설명 |
|---|---|---|
| `scf/e_tot` | scalar | total energy |
| `scf/mo_energy` | array | orbital energies |
| `scf/mo_occ` | array | orbital occupancies |
| `scf/mo_coeff` | array | orbital coefficients |
| `scf/converged` | bool | 수렴 여부 |

## 4. Relationships Detail

| From | To | Type | FK | Cascade | 설명 |
|---|---|---|---|---|---|
| `users.username` | `auth_tokens.username` | 1:N | yes | no explicit cascade | 한 사용자가 여러 인증 토큰을 가질 수 있다 |
| `session_record.session_id` | `job_record.session_id` | 1:N | app-level | n/a | 한 세션이 여러 잡을 가진다 |
| `users.username` | `job_record.owner_username` | 1:N | app-level | n/a | 로그인 사용자가 여러 잡을 소유한다 |
| `job_record.job_id` | `job_event.event_id@job` | 1:N | app-level | capped list | 한 잡은 여러 이벤트를 가진다 |
| `session_record.session_id` | `conversation_state.session_id` | 1:1(latest) | app-level | overwrite | 세션당 최신 continuation 상태 저장 |
| `worker_heartbeat.worker_id` | `job_record.worker_id` | 1:N runtime | app-level | TTL expiry | 워커가 현재/최근 잡과 연결된다 |
| `scf_cache_meta.key` | `scf_checkpoint.filename` | 1:1 | filename convention | manual | JSON 메타와 HDF5 체크포인트가 같은 key를 공유한다 |

## 5. Index Strategy

### 5.1 SQLite 인덱스

| 인덱스명 | 대상 | 목적 | 매핑되는 쿼리 |
|---|---|---|---|
| `PRIMARY KEY users(username)` | `users.username` | 사용자 조회 | 로그인 시 사용자 탐색 |
| `PRIMARY KEY auth_tokens(token)` | `auth_tokens.token` | 토큰 단건 조회 | `get_auth_user()` |
| `idx_auth_tokens_username` | `auth_tokens.username` | 사용자별 토큰 집계 | `list_users()` |
| `idx_auth_tokens_expires_at` | `auth_tokens.expires_at` | 만료 토큰 정리 | `DELETE FROM auth_tokens WHERE expires_at < ?` |

### 5.2 Redis 인덱스 키

| 키 패턴 | 구조 | 목적 |
|---|---|---|
| `{prefix}:job:{job_id}` | string JSON | 잡 본문 저장 |
| `{prefix}:jobs:all` | zset | 전체 잡 정렬 조회 |
| `{prefix}:jobs:session:{session_id}` | zset | 세션별 잡 조회 |
| `{prefix}:jobs:owner:{owner_username}` | zset | 사용자별 잡 조회 |
| `{prefix}:jobs:status:{status}` | zset | 상태별 잡 조회 |
| `{prefix}:jobs:status:active` | zset | 활성 잡 추적 |
| `{prefix}:session:{session_id}:state` | string JSON | continuation 상태 저장 |
| `{prefix}:job:{job_id}:cancel` | string/bool flag | 취소 요청 |
| `{prefix}:worker:{worker_id}:heartbeat` | string JSON or TTL key | 워커 생존 추적 |

### 5.3 인덱스 전략 평가

- 조회 패턴이 명확해 단순한 key naming으로 충분하다.
- Redis는 관계형 join 대신 secondary index zset을 사용한다.
- 메모리 잡 매니저는 인덱스 대신 Python dict + 정렬 계산을 사용한다.

## 6. Enum & Type Definitions

### 6.1 Job Status Enum

| 값 | 사용 위치 | 의미 |
|---|---|---|
| `queued` | job manager, Redis store | 제출됨, 아직 시작 전 |
| `running` | job manager, Redis store | 실행 중 |
| `completed` | job manager, Redis store | 성공 완료 |
| `failed` | job manager, Redis store | 비즈니스 또는 런타임 실패 |
| `error` | Redis store bucket constant | 오류 상태 bucket |
| `cancelled` | Redis store bucket constant | 취소됨 |

### 6.2 User Role Enum

| 값 | 의미 |
|---|---|
| `user` | 일반 사용자 |
| `admin` | 관리자 |

### 6.3 Job Event Type Examples

| 값 | 의미 |
|---|---|
| `job_submitted` | 잡 생성 |
| `job_started` | 실행 시작 |
| `job_progress` | 진행률 갱신 |
| `job_completed` | 완료 |
| `job_failed` | 실패 |

### 6.4 기타 타입

| 타입 | 위치 | 의미 |
|---|---|---|
| `SessionRecord` | `web/session_auth.py` | 익명 세션 메모리 레코드 |
| `JobRecord` | `web/routes/compute.py` | 메모리 잡 레코드 |
| `Dict[str, Any]` result contract | `compute/pyscf_runner.py` | 느슨한 결과 스키마 |

## 7. Migration History & Schema Evolution

### 7.1 정식 마이그레이션 파일 상태

- `prisma/migrations`, `alembic`, `migrations/`, `sql/` 같은 정식 마이그레이션 디렉터리는 없다.
- 스키마 변경은 런타임 초기화 코드에 내장돼 있다.

### 7.2 확인 가능한 스키마 진화 흔적

| 위치 | 변경 내용 | 의미 |
|---|---|---|
| `auth_store.py` | `if "role" not in columns: ALTER TABLE users ADD COLUMN role ...` | 기존 사용자 테이블에 role 컬럼이 후속 도입됨 |
| `disk_cache.py` | legacy pickle meta 지원 후 JSON 메타로 마이그레이션 | 캐시 포맷이 안전한 JSON으로 이동 |
| `docs/20260320*`, `20260321*`, `20260324*` | web/worker split 문서 | 실행 아키텍처가 단일 프로세스에서 분리형으로 진화 중임 |

### 7.3 스키마 관리 관찰

- DB migration tool 부재는 초기 민첩성에는 유리하다.
- 그러나 프로덕션 운영에서는 예측 가능한 schema rollout이 어렵다.
- SQLite 스키마 변경이 코드 초기화 시점에 암묵적으로 수행된다.

## 8. Data Flow Diagram

### 8.1 사용자 요청에서 저장까지

```text
User input
 -> chat.py / compute.py payload
 -> session_auth validates or issues session
 -> auth_store resolves optional user
 -> structure_resolver fetches structure
 -> pyscf_runner executes calculation
 -> job manager persists snapshot/events/result
 -> conversation_state saves latest execution context
 -> disk_cache saves SCF checkpoint/meta
 -> API/WS returns result
```

### 8.2 캐싱 포함 상세 흐름

```text
structure_query
 -> structure_resolver cache lookup
 -> miss -> MolChat call
 -> miss/fallback -> PubChem call
 -> resolved xyz
 -> pyscf_runner cache key creation
 -> disk_cache load_from_disk(key)
 -> hit -> reuse SCF artifacts
 -> miss -> run PySCF
 -> save_to_disk(key)
 -> build result contract
 -> advisor_flow enrichment
 -> conversation_state update
```

### 8.3 조회 흐름

- `/compute/jobs`는 세션 또는 사용자 기준으로 잡 목록을 읽는다.
- `/compute/jobs/{job_id}`는 접근 권한을 확인한 뒤 스냅샷을 반환한다.
- `/compute/jobs/{job_id}/result`는 `result`와 `error` 필드를 노출한다.
- `/compute/jobs/{job_id}/events`는 이벤트 배열만 반환한다.
- `/admin/overview`는 사용자 목록, 잡 목록, 큐 요약, 워커 상태를 집계한다.

### 8.4 실제 코드 예시: SQLite 스키마

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at REAL NOT NULL,
        disabled INTEGER NOT NULL DEFAULT 0
    )
    """
)
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        FOREIGN KEY(username) REFERENCES users(username)
    )
    """
)
```

소스: `src/qcviz_mcp/web/auth_store.py`

### 8.5 실제 코드 예시: 디스크 캐시 저장 포맷

```python
chkfile_path = CACHE_DIR / f"{key}.chk"
meta_path = CACHE_DIR / f"{key}.meta.json"
with lib.H5FileWrap(str(chkfile_path), 'w') as fh5:
    fh5['scf/e_tot'] = energy
    if hasattr(mf_obj, 'mo_energy'): fh5['scf/mo_energy'] = mf_obj.mo_energy
```

소스: `src/qcviz_mcp/compute/disk_cache.py`

---

# 📄 DOCUMENT 3 — API_REFERENCE.md

## 1. API Overview

### 1.1 Base URL

- 개발 기본 URL: `http://127.0.0.1:8765`
- `run_dev.py`는 `127.0.0.1:8765`를 사용한다.
- `start_server.sh` 예시는 기본 포트 `8000`을 사용한다.
- `run.sh` 예시는 `0.0.0.0:8223`와 `root-path=/qcviz`를 사용한다.
- 따라서 코드가 강제하는 단일 고정 base URL은 없고, Uvicorn 실행 방식에 따라 달라진다.

### 1.2 버전 관리 전략

- URL 경로에 `v1`, `v2` 같은 정식 API 버전 prefix는 없다.
- 대신 canonical path와 `/api` alias를 병행한다.
- 예:
- `/chat` 와 `/api/chat`
- `/compute/jobs` 와 `/api/compute/jobs`
- `/health` 와 `/api/health`

### 1.3 인증 방식

- 사용자 인증: `X-QCViz-Auth-Token`
- 익명 세션 인증: `X-QCViz-Session-Id`, `X-QCViz-Session-Token`
- WebSocket 인증: query string `session_id`, `session_token`, `auth_token`

### 1.4 공통 응답 형태

- 완전한 단일 envelope 규격은 없다.
- 많은 엔드포인트가 `{"ok": true/false, ...}`를 사용한다.
- compute/job 계열은 `ok` 없이 `job_id`, `status`, `items`, `result`를 직접 반환하기도 한다.
- 오류는 주로 FastAPI 기본 `{"detail": "..."}` 형식이다.

## 2. Authentication & Authorization

### 2.1 인증 흐름 다이어그램

```text
Anonymous client
 -> POST /session/bootstrap
 -> receive session_id + session_token
 -> use headers or WS query params on subsequent calls

Registered client
 -> POST /auth/register or /auth/login
 -> receive auth_token + expires_at
 -> send X-QCViz-Auth-Token on API calls
 -> optional session also coexists for job ownership / continuity
```

### 2.2 토큰 형식과 만료 정책

| 토큰 | 전달 방식 | 저장 위치 | 기본 TTL | 구현 |
|---|---|---|---|---|
| auth token | `X-QCViz-Auth-Token` | SQLite `auth_tokens` | `QCVIZ_AUTH_TOKEN_TTL_SECONDS`, 기본 30일 | `web/auth_store.py` |
| session token | `X-QCViz-Session-Token` | in-memory `SessionRecord` | `QCVIZ_SESSION_TTL_SECONDS`, 기본 7일 | `web/session_auth.py` |

### 2.3 리프레시 전략

- 전용 refresh token API는 없다.
- auth token은 로그인 시 새로 발급받는다.
- session token은 동일 세션 유효 시 재사용한다.
- 세션 미일치 또는 만료 시 새 bootstrap이 필요하다.

### 2.4 권한 모델

| 역할 | 권한 |
|---|---|
| `public` | 세션 bootstrap, health 조회, register/login, 익명 job/chat |
| `user` | 자기 토큰 소유 잡 전체 조회, 자기 계정 정보 조회 |
| `admin` | 관리자 overview, 임의 잡 취소/재큐잉 |

### 2.5 퍼미션 매트릭스

| 엔드포인트 그룹 | Public | User | Admin |
|---|---|---|---|
| Health | yes | yes | yes |
| Session bootstrap | yes | yes | yes |
| Register/Login/Logout | yes | yes | yes |
| Auth Me | no | yes | yes |
| Chat / Compute by session | yes | yes | yes |
| List/Get jobs by auth owner | no | yes | yes |
| Admin overview | no | no | yes |
| Admin cancel/requeue | no | no | yes |

## 3. Common Conventions

### 3.1 HTTP 상태 코드 사용 규칙

| 코드 | 의미 | 실제 사용 예 |
|---|---|---|
| `200` | 성공 | 대부분의 GET/POST 성공 |
| `400` | 잘못된 요청 또는 구조 해석 실패 | chat WS/REST preflight 일부 |
| `401` | 인증 필요 | `require_auth_user()` |
| `403` | 세션 토큰 불일치 또는 admin 권한 부족 | `session_auth.py`, `require_admin_user()` |
| `404` | job not found, cache miss | compute routes, orbital cube |
| `409` | username already exists | `auth_store._create_user()` |
| `500` | 처리되지 않은 예외 | WS unhandled error, runtime failures |
| `501` | backend capability missing | admin cancel/requeue unsupported backend |

### 3.2 에러 응답 스키마

- FastAPI 기본 경로:

```json
{ "detail": "authentication required." }
```

- WebSocket error 이벤트:

```json
{
  "type": "error",
  "session_id": "qcviz-...",
  "error": {
    "message": "Invalid session token.",
    "status_code": 403,
    "detail": {}
  }
}
```

### 3.3 페이지네이션 패턴

- 전통적 offset/limit 페이지네이션은 없다.
- `/compute/jobs`는 필터 후 전체 목록을 반환한다.
- 관리자 overview도 summary 집계형이며 별도 pagination 파라미터가 없다.

### 3.4 필터링/정렬 규약

- `/compute/jobs`는 `session_id`, `session_token` 및 auth token으로 조회 범위를 결정한다.
- include 파라미터:
- `include_payload`
- `include_result`
- `include_events`
- 정렬은 job manager 내부 생성 시각 역순 의미를 가진다.

### 3.5 비즈니스 엔드포인트 외 라우트 inventory

| 경로 | 메서드 | 설명 |
|---|---|---|
| `/` | GET | 메인 HTML |
| `/index.html` | GET | 메인 HTML alias |
| `/api`, `/api/` | GET | route table / API root 정보 |
| `/favicon.ico` | GET | favicon redirect |
| `/static/*` | GET | 정적 자산 |
| `/api/static/*` | GET | 정적 자산 alias |

## 4. Endpoint Catalog

### [GET] `/health`

- Alias: `/api/health`
- 설명: 전체 서비스 health와 route metadata를 반환한다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "service": "qcviz-mcp",
  "routes": {
    "chat_rest": "/chat",
    "compute_jobs": "/compute/jobs"
  }
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 사용 없음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 시 프레임워크 오류 가능

### [POST] `/session/bootstrap`

- Alias: `/api/session/bootstrap`
- 설명: 새 세션을 발급하거나 기존 세션을 검증한다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body 예시:

```json
{ "session_id": "", "session_token": "" }
```

- Response 200 예시:

```json
{
  "ok": true,
  "session_id": "qcviz-1234",
  "session_token": "token-value",
  "created_at": 1710000000.0,
  "last_seen_at": 1710000000.0,
  "issued": true,
  "ttl_seconds": 604800,
  "routes": {
    "chat_ws": "/ws/chat",
    "chat_rest": "/chat",
    "compute_jobs": "/compute/jobs"
  }
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 사용 없음
- `403`: `session_id` 없이 `session_token`만 전달, 또는 기존 세션 토큰 불일치
- `404`: 사용 없음
- `500`: 내부 예외 시 프레임워크 오류 가능

### [POST] `/auth/register`

- Alias: `/api/auth/register`
- 설명: 새 사용자를 만들고 즉시 로그인 토큰을 발급한다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body 예시:

```json
{
  "username": "alice",
  "password": "correct horse battery staple",
  "display_name": "Alice"
}
```

- Response 200 예시:

```json
{
  "ok": true,
  "user": {
    "username": "alice",
    "display_name": "Alice",
    "role": "user",
    "created_at": 1710000000.0
  },
  "auth_token": "token-value",
  "expires_at": 1712592000.0
}
```

- Error Responses:
- `400`: 비밀번호 정책 위반 가능
- `401`: 사용 없음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [POST] `/auth/login`

- Alias: `/api/auth/login`
- 설명: 사용자 이름과 비밀번호로 auth token을 발급받는다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body 예시:

```json
{
  "username": "alice",
  "password": "correct horse battery staple"
}
```

- Response 200 예시:

```json
{
  "ok": true,
  "auth_token": "token-value",
  "expires_at": 1712592000.0
}
```

- Error Responses:
- `400`: 잘못된 입력 형식 가능
- `401`: 인증 실패 시 사용될 수 있음
- `403`: disabled 사용자 시 거부 가능
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [GET] `/auth/me`

- Alias: `/api/auth/me`
- 설명: 현재 auth token의 사용자 정보를 반환한다.
- 인증: Required
- 권한: `user`, `admin`
- Request Headers:
- `X-QCViz-Auth-Token: <token>`
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "authenticated": true,
  "user": {
    "username": "alice",
    "display_name": "Alice",
    "role": "user",
    "created_at": 1710000000.0,
    "expires_at": 1712592000.0
  }
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 토큰이 없거나 무효면 `user`가 `null`일 수 있으며 강제 예외는 route 자체에서 발생하지 않음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [POST] `/auth/logout`

- Alias: `/api/auth/logout`
- 설명: 현재 auth token을 폐기한다.
- 인증: 선택적
- 권한: token 소유자
- Request Headers:
- `X-QCViz-Auth-Token: <token>` 또는 body의 `auth_token`
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body 예시:

```json
{ "auth_token": "token-value" }
```

- Response 200 예시:

```json
{ "ok": true }
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: route 자체는 강제하지 않음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [GET] `/admin/overview`

- Alias: `/api/admin/overview`
- 설명: 사용자, 잡, 큐, 워커 상태의 운영 요약을 반환한다.
- 인증: Required
- 권한: `admin`
- Request Headers:
- `X-QCViz-Auth-Token: <admin-token>`
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "admin_user": { "username": "admin", "role": "admin" },
  "overview": {
    "queue": {},
    "workers": [],
    "status_counts": {},
    "users": []
  }
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 인증 토큰이 없거나 무효
- `403`: admin이 아닌 경우
- `404`: 사용 없음
- `500`: backend summary 실패 시 내부 예외 가능

### [POST] `/admin/jobs/{job_id}/cancel`

- Alias: `/api/admin/jobs/{job_id}/cancel`
- 설명: 관리자가 특정 잡을 취소한다.
- 인증: Required
- 권한: `admin`
- Request Headers:
- `X-QCViz-Auth-Token: <admin-token>`
- Path Parameters:
- `job_id: string`
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "admin_user": "admin",
  "job_id": "job-123"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 인증 실패
- `403`: admin 아님
- `404`: 백엔드에서 job not found 가능
- `500`: 내부 예외 가능

### [POST] `/admin/jobs/{job_id}/requeue`

- Alias: `/api/admin/jobs/{job_id}/requeue`
- 설명: 관리자가 실패/완료 잡을 재큐잉한다.
- 인증: Required
- 권한: `admin`
- Request Headers:
- `X-QCViz-Auth-Token: <admin-token>`
- Path Parameters:
- `job_id: string`
- Query Parameters: 없음
- Request Body 예시:

```json
{ "reason": "admin_requeue", "force": true }
```

- Response 200 예시:

```json
{
  "ok": true,
  "admin_user": "admin",
  "source_job_id": "job-123",
  "job": {
    "job_id": "job-456",
    "status": "queued"
  }
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 인증 실패
- `403`: admin 아님
- `404`: source job 없음 가능
- `500`: 내부 예외 가능

### [GET] `/chat/health`

- Alias: `/api/chat/health`
- 설명: chat subsystem 상태를 반환한다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "service": "chat",
  "websocket": "/ws/chat"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 사용 없음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [POST] `/chat`

- Alias: `/api/chat`
- 설명: 자연어 메시지를 해석해 clarification, job submission, 또는 즉시 결과를 반환한다.
- 인증: Public 또는 User
- 권한: session owner 또는 auth user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters: 없음
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `wait` | boolean | no | `false` | terminal job까지 동기 대기 |
| `wait_for_result` | boolean | no | `false` | `wait`와 유사 |
| `timeout` | float | no | `120.0` | 대기 타임아웃 |

- Request Body 예시:

```json
{
  "message": "Show HOMO of benzene",
  "session_id": "qcviz-1234",
  "session_token": "token-value"
}
```

- Clarification Response 200 예시:

```json
{
  "ok": false,
  "requires_clarification": true,
  "session_id": "qcviz-1234",
  "session_token": "token-value",
  "plan": {},
  "clarification_kind": "structure_disambiguation",
  "clarification": {}
}
```

- Job Submission Response 200 예시:

```json
{
  "ok": true,
  "session_id": "qcviz-1234",
  "session_token": "token-value",
  "message": "Planned calculation",
  "plan": {},
  "job": {
    "job_id": "job-123",
    "status": "queued"
  }
}
```

- Waited Result Response 200 예시:

```json
{
  "ok": true,
  "session_id": "qcviz-1234",
  "session_token": "token-value",
  "message": "Planned calculation",
  "plan": {},
  "job": { "job_id": "job-123", "status": "completed" },
  "result": {},
  "error": null,
  "summary": "Result summary"
}
```

- Error Responses:
- `400`: invalid request, 구조 해석 실패
- `401`: auth token 기반 사용자 강제 경로에서 가능
- `403`: 세션 토큰 불일치
- `404`: waiting 중 job not found
- `500`: 내부 예외

### [GET] `/compute/health`

- Alias: `/api/compute/health`
- 설명: compute subsystem, queue, quota summary를 반환한다.
- 인증: Public
- 권한: 없음
- Request Headers: 없음
- Path Parameters: 없음
- Query Parameters: 없음
- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "service": "compute",
  "queue": {},
  "quota": {}
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: 사용 없음
- `403`: 사용 없음
- `404`: 사용 없음
- `500`: 내부 예외 가능

### [POST] `/compute/jobs`

- Alias: `/api/compute/jobs`
- 설명: 계산 잡을 직접 제출한다.
- 인증: Public 또는 User
- 권한: session owner 또는 auth user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters: 없음
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `sync` | boolean | no | `false` | 즉시 결과 대기 |
| `wait` | boolean | no | `false` | 즉시 결과 대기 |
| `wait_for_result` | boolean | no | `false` | 즉시 결과 대기 |
| `timeout` | float | no | `120.0` | 대기 시간 |

- Request Body 예시:

```json
{
  "message": "Calculate Mulliken charges for water",
  "structure_query": "water",
  "job_type": "charges",
  "method": "B3LYP",
  "basis": "def2-SVP",
  "session_id": "qcviz-1234",
  "session_token": "token-value"
}
```

- Response 200 예시:

```json
{
  "job_id": "job-123",
  "session_id": "qcviz-1234",
  "owner_username": "",
  "status": "queued",
  "user_query": "Calculate Mulliken charges for water",
  "job_type": "charges",
  "molecule_name": "water",
  "method": "B3LYP",
  "basis_set": "def2-SVP",
  "progress": 0.0,
  "step": "",
  "message": "",
  "queue": {},
  "quota": {},
  "session_token": "token-value"
}
```

- Error Responses:
- `400`: invalid payload / structure resolution failure / quota payload issues
- `401`: auth-only path에서 invalid auth
- `403`: invalid session token
- `404`: sync/wait 경로에서 job not found
- `500`: 내부 예외

### [GET] `/compute/jobs`

- Alias: `/api/compute/jobs`
- 설명: 세션 또는 auth 사용자 범위의 잡 목록을 반환한다.
- 인증: Session 또는 User
- 권한: 자기 세션 또는 자기 사용자
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters: 없음
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `include_payload` | boolean | no | `false` | 입력 payload 포함 |
| `include_result` | boolean | no | `false` | 결과 포함 |
| `include_events` | boolean | no | `false` | 이벤트 포함 |
| `session_id` | string | no | `null` | 세션 조회 범위 |
| `session_token` | string | no | `null` | 세션 검증 토큰 |

- Response 200 예시:

```json
{
  "items": [],
  "count": 0,
  "queue": {},
  "quota": {},
  "session_id": "qcviz-1234"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 경로에서 무효 토큰
- `403`: session token 불일치
- `404`: 사용 없음
- `500`: 내부 예외

### [GET] `/compute/jobs/{job_id}`

- Alias: `/api/compute/jobs/{job_id}`
- 설명: 단일 잡 스냅샷을 반환한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `include_payload` | boolean | no | `false` | payload 포함 |
| `include_result` | boolean | no | `false` | result 포함 |
| `include_events` | boolean | no | `false` | events 포함 |
| `session_id` | string | no | `null` | 세션 조회 |
| `session_token` | string | no | `null` | 세션 검증 |

- Response 200 예시:

```json
{
  "job_id": "job-123",
  "session_id": "qcviz-1234",
  "owner_username": "",
  "status": "running",
  "job_type": "charges",
  "progress": 0.4,
  "step": "scf",
  "message": "Running SCF"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 실패
- `403`: job access denied
- `404`: job not found
- `500`: 내부 예외

### [GET] `/compute/jobs/{job_id}/result`

- Alias: `/api/compute/jobs/{job_id}/result`
- 설명: 특정 잡의 `result`와 `error`만 반환한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | no | `null` | 세션 조회 |
| `session_token` | string | no | `null` | 세션 검증 |

- Response 200 예시:

```json
{
  "job_id": "job-123",
  "session_id": "qcviz-1234",
  "status": "completed",
  "result": {},
  "error": null
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 실패
- `403`: job access denied
- `404`: job not found
- `500`: 내부 예외

### [GET] `/compute/jobs/{job_id}/events`

- Alias: `/api/compute/jobs/{job_id}/events`
- 설명: 특정 잡의 이벤트 목록을 반환한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | no | `null` | 세션 조회 |
| `session_token` | string | no | `null` | 세션 검증 |

- Response 200 예시:

```json
{
  "job_id": "job-123",
  "session_id": "qcviz-1234",
  "status": "running",
  "events": [
    { "event_id": 1, "type": "job_submitted", "message": "Job submitted" }
  ]
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 실패
- `403`: job access denied
- `404`: job not found
- `500`: 내부 예외

### [DELETE] `/compute/jobs/{job_id}`

- Alias: `/api/compute/jobs/{job_id}`
- 설명: 특정 잡을 저장소에서 삭제한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | no | `null` | 세션 조회 |
| `session_token` | string | no | `null` | 세션 검증 |

- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "job_id": "job-123",
  "session_id": "qcviz-1234"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 실패
- `403`: job access denied
- `404`: job not found
- `500`: 내부 예외

### [POST] `/compute/jobs/{job_id}/cancel`

- Alias: `/api/compute/jobs/{job_id}/cancel`
- 설명: 실행 중인 잡에 취소 플래그를 설정한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters:

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | no | `null` | 세션 조회 |
| `session_token` | string | no | `null` | 세션 검증 |

- Request Body: 없음
- Response 200 예시:

```json
{
  "ok": true,
  "job_id": "job-123",
  "session_id": "qcviz-1234",
  "message": "Cancellation requested"
}
```

- Error Responses:
- `400`: 명시적 사용 없음
- `401`: auth 실패
- `403`: job access denied
- `404`: job not found
- `500`: 내부 예외

### [POST] `/compute/jobs/{job_id}/orbital_cube`

- Alias: `/api/compute/jobs/{job_id}/orbital_cube`
- 설명: 이미 계산된 잡에 대해 다른 orbital index의 cube 데이터를 생성한다.
- 인증: Session 또는 User
- 권한: job owner session/user
- Request Headers:
- `X-QCViz-Session-Id`
- `X-QCViz-Session-Token`
- `X-QCViz-Auth-Token`
- Path Parameters:
- `job_id: string`
- Query Parameters: 없음
- Request Body 예시:

```json
{
  "orbital_index": 5,
  "session_id": "qcviz-1234",
  "session_token": "token-value"
}
```

- Response 200 예시:

```json
{
  "ok": true,
  "cube_b64": "base64-encoded-cube",
  "orbital_index": 5
}
```

- Error Responses:
- `400`: invalid orbital index/body 가능
- `401`: auth 실패
- `403`: job access denied
- `404`: cache expired 또는 job not found
- `500`: 내부 예외

## 5. WebSocket / Real-time Events

### 5.1 Endpoint

- Canonical: `/ws/chat`
- Alias: `/api/ws/chat`

### 5.2 연결 시 query parameters

| Param | Required | 설명 |
|---|---|---|
| `session_id` | no | 기존 세션 재연결 시 사용 |
| `session_token` | no | 세션 검증 토큰 |
| `auth_token` | no | 로그인 사용자 인증 |

### 5.3 서버가 보내는 주요 이벤트

| 이벤트 | 설명 | 주요 필드 |
|---|---|---|
| `ready` | 연결 확립 및 기본 세션 발급 | `session_id`, `session_token`, `auth_user`, `message`, `timestamp` |
| `ack` | ping/hello 또는 요청 수신 확인 | `session_id`, `status`, `message`, `timestamp` |
| `assistant` | planning 또는 대화 응답 | `message`, `plan`, `payload_preview`, `timestamp` |
| `clarify` | 추가 입력 요청 | `message`, `clarification_kind`, `form`, `fields`, `timestamp` |
| `job_submitted` | 잡 제출 완료 | `job`, `timestamp` |
| `job_update` | 진행률/상태 갱신 | `job_id`, `status`, `progress`, `step`, `message`, `queue`, `quota` |
| `job_event` | 개별 이벤트 로그 | `event` |
| `result` | terminal result 전달 | `job` |
| `error` | 오류 통지 | `error`, `status_code`, `detail` |
| `ping` | keepalive | `ts` |

### 5.4 클라이언트가 보낼 수 있는 메시지 타입

| type | 설명 |
|---|---|
| `hello` | 연결 확인 |
| `ping` / `pong` | keepalive |
| `ack` | 수신 확인 |
| `clarify_response` | clarification 답변 제출 |
| 생략 또는 일반 메시지 | 자연어 질의 본문 |

### 5.5 WS 예시: `ready`

```json
{
  "type": "ready",
  "session_id": "qcviz-1234",
  "session_token": "token-value",
  "auth_user": null,
  "message": "QCViz chat websocket connected.",
  "timestamp": 1710000000.0
}
```

## 6. Rate Limiting & Throttling

### 6.1 구현 현황

- 전통적인 HTTP rate limiting 미들웨어는 없다.
- 대신 active job quota가 사실상의 throttling 역할을 한다.

### 6.2 관련 환경 변수

| 변수 | 의미 |
|---|---|
| `QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION` | 세션당 활성 잡 수 제한 |
| `QCVIZ_MAX_ACTIVE_JOBS_PER_USER` | 사용자당 활성 잡 수 제한 |
| `QCVIZ_MAX_JOBS` | 메모리 잡 보관 상한 |
| `QCVIZ_MAX_JOB_EVENTS` | 잡당 이벤트 저장 상한 |

### 6.3 초과 시 동작

- `JOB_MANAGER.submit()` 경로에서 `HTTPException`이 발생한다.
- REST에서는 4xx 오류로 반환된다.
- WebSocket에서는 `error` 이벤트와 함께 quota summary가 전달될 수 있다.

### 6.4 관련 응답 헤더

- 표준 rate limit 헤더(`X-RateLimit-*`)는 구현돼 있지 않다.

## 7. Middleware Pipeline

### 7.1 글로벌 미들웨어

- CORS only
- 구현 위치: `src/qcviz_mcp/web/app.py`
- 허용 origin: `QCVIZ_CORS_ALLOW_ORIGINS`, 기본 `*`

### 7.2 REST 요청 파이프라인

```text
HTTP request
 -> FastAPI routing
 -> CORS middleware
 -> endpoint function
 -> optional auth token resolution
 -> optional session bootstrap/validation
 -> payload normalization
 -> quota enforcement
 -> business logic / job manager
 -> JSON response
```

### 7.3 WebSocket 요청 파이프라인

```text
WS connect
 -> query param auth token resolve
 -> session bootstrap/validation
 -> websocket.accept()
 -> ready event
 -> incoming message parse
 -> session binding check
 -> clarification or plan generation
 -> job submit / stream terminal
 -> assistant/job_update/result/error events
```

### 7.4 중앙 미들웨어가 아닌 라우트 내 처리

- 인증은 dependency injection 미들웨어가 아니라 route body/header parsing 내에서 처리된다.
- quota 역시 전역 미들웨어가 아니라 job submit 경로에서 처리된다.
- 에러 포맷 역시 REST와 WS가 서로 다르다.

---

# 📄 DOCUMENT 4 — DEVELOPMENT_SETUP.md

## 1. Prerequisites

### 1.1 필수 소프트웨어

| 소프트웨어 | 최소/명시 버전 | 용도 | 근거 |
|---|---|---|---|
| Python | `>=3.10` | 백엔드 실행 | `pyproject.toml` |
| pip | 최신 권장 | 패키지 설치 | `README.md` |
| setuptools | `>=68` | build backend | `pyproject.toml` |
| wheel | 최신 권장 | 패키징 | `pyproject.toml` |
| PySCF | `>=2.4,<3.0` | 양자화학 계산 | `pyproject.toml` |
| FastAPI | `>=0.110,<1.0` | 웹 프레임워크 | `pyproject.toml` |
| Uvicorn | `>=0.29,<1.0` | ASGI 서버 | `pyproject.toml` |
| Redis | 선택 | split-worker 모드 | optional dependency `worker` |
| Node.js | 불필요 | 프런트 빌드가 없으므로 필수 아님 | 저장소 구조 |

### 1.2 OS별 차이점

| OS | 차이점 |
|---|---|
| Windows | `run_dev.py`가 PySCF를 mock 하여 UI/라우팅 검증에 유용하다 |
| macOS | 일반 Python 가상환경 + Uvicorn 실행 경로 사용 가능 |
| Linux | `run.sh`, `start_server.sh`를 그대로 사용하기 쉽다 |

### 1.3 저장소 상태 관련 주의

- `README.md`는 `version02` 경로를 가리키는 등 일부 문구가 최신 저장소명과 어긋난다.
- 루트 `.env`에 실제 비밀값이 존재하므로 개발 환경 복제 시 바로 커밋하지 말아야 한다.
- `.env.example`은 저장소에 없다.
- Docker 개발 환경 파일은 없다.

## 2. Step-by-Step Setup

### 2.1 Editable install 기준

1. 프로젝트 루트로 이동한다.

```powershell
cd D:\20260305_양자화학시각화MCP서버구축\version03
```

2. 가상환경을 만든다.

```powershell
python -m venv .venv
```

3. 가상환경을 활성화한다.

```powershell
.venv\Scripts\Activate.ps1
```

4. 빌드 도구를 업데이트한다.

```powershell
python -m pip install --upgrade pip setuptools wheel
```

5. 기본 패키지를 editable로 설치한다.

```powershell
pip install -e .
```

6. LLM provider가 필요하면 optional extra를 설치한다.

```powershell
pip install -e ".[llm-gemini]"
```

또는

```powershell
pip install -e ".[llm-openai]"
```

7. split-worker 모드가 필요하면 worker extra를 설치한다.

```powershell
pip install -e ".[worker]"
```

8. 개발 테스트 도구가 필요하면 dev extra를 설치한다.

```powershell
pip install -e ".[dev]"
```

9. 서버를 실행한다.

```powershell
uvicorn qcviz_mcp.web.app:app --host 127.0.0.1 --port 8765 --reload
```

10. 브라우저에서 접속한다.

```text
http://127.0.0.1:8765
```

### 2.2 설치 확인 포인트

- `/health`가 200을 반환해야 한다.
- `/session/bootstrap`가 `session_id`, `session_token`을 반환해야 한다.
- 초기 UI가 `index.html`에서 렌더링되어야 한다.
- PySCF가 없는 Windows 환경에서는 실제 계산은 실패할 수 있다.

### 2.3 소스 트리 직접 실행

설치 없이 실행하는 저장소 공식 패턴은 `README.md`와 shell script에 존재한다.

```powershell
$env:PYTHONPATH = "src"
uvicorn qcviz_mcp.web.app:app --reload
```

### 2.4 Windows mock 실행

```powershell
python run_dev.py
```

이 스크립트는 `pyscf` 모듈을 `MagicMock`으로 주입한 뒤 Uvicorn을 띄운다.

## 3. Environment Variables

### 3.1 환경 변수 표

| 변수명 | 필수 | 기본값 | 설명 | 예시 |
|---|---|---|---|---|
| `QCVIZ_HOST` | no | `127.0.0.1` | 서버 host | `0.0.0.0` |
| `QCVIZ_PORT` | no | `8765` | 서버 port | `8223` |
| `QCVIZ_TRANSPORT` | no | `sse` | 서버 transport 표시값 | `stdio` |
| `QCVIZ_MAX_ATOMS` | no | `50` | 계산 허용 원자 수 | `100` |
| `QCVIZ_MAX_WORKERS` | no | `2` | 일반 worker 수 설정 필드 | `4` |
| `QCVIZ_COMPUTATION_TIMEOUT_SECONDS` | no | `300.0` | 계산 timeout | `600` |
| `QCVIZ_DEFAULT_BASIS` | no | `sto-3g` | 기본 basis | `def2-SVP` |
| `QCVIZ_DEFAULT_CUBE_RESOLUTION` | no | `80` | 기본 cube 해상도 | `96` |
| `QCVIZ_CACHE_MAX_SIZE` | no | `50` | 일반 cache size 필드 | `100` |
| `QCVIZ_CACHE_TTL_SECONDS` | no | `3600.0` | 일반 cache ttl | `7200` |
| `QCVIZ_RATE_LIMIT_CAPACITY` | no | `100` | config dataclass의 rate limit 설정 필드 | `200` |
| `QCVIZ_RATE_LIMIT_REFILL_RATE` | no | `1.0` | config dataclass의 refill rate | `2.0` |
| `QCVIZ_ALLOWED_OUTPUT_ROOT` | no | `output/` | 출력 루트 디렉터리 | `D:\output` |
| `QCVIZ_LOG_LEVEL` | no | `INFO` | 로깅 레벨 | `DEBUG` |
| `QCVIZ_LOG_JSON` | no | `False` | JSON 로그 여부 | `true` |
| `QCVIZ_PREFERRED_RENDERER` | no | `auto` | 렌더러 선호 | `playwright` |
| `QCVIZ_GEMINI_API_KEY` | no | 빈 문자열 | Gemini API key | `AIza...` |
| `GEMINI_API_KEY` | no | unset | Gemini API key fallback | `AIza...` |
| `QCVIZ_GEMINI_MODEL` | no | `gemini-2.5-flash` | Gemini 모델 | `gemini-2.5-pro` |
| `GEMINI_MODEL` | no | unset | Gemini 모델 fallback | `gemini-2.5-flash` |
| `QCVIZ_GEMINI_TIMEOUT` | no | `10.0` | Gemini timeout | `20` |
| `GEMINI_TIMEOUT` | no | unset | Gemini timeout fallback | `10` |
| `QCVIZ_GEMINI_TEMPERATURE` | no | `0.1` | Gemini temperature | `0.0` |
| `GEMINI_TEMPERATURE` | no | unset | Gemini temperature fallback | `0.0` |
| `QCVIZ_MOLCHAT_BASE_URL` | no | `http://psid.aizen.co.kr/molchat` | MolChat base URL | `https://example/molchat` |
| `MOLCHAT_BASE_URL` | no | unset | MolChat base URL fallback | `https://example/molchat` |
| `QCVIZ_MOLCHAT_TIMEOUT` | no | `15.0` | MolChat timeout | `30` |
| `MOLCHAT_TIMEOUT` | no | unset | MolChat timeout fallback | `15` |
| `MOLCHAT_API_KEY` | no | unset | MolChat 인증 키 | `secret` |
| `QCVIZ_PUBCHEM_TIMEOUT` | no | `10.0` | PubChem timeout | `20` |
| `PUBCHEM_TIMEOUT` | no | unset | PubChem timeout fallback | `20` |
| `QCVIZ_PUBCHEM_FALLBACK` | no | `true` | PubChem fallback 사용 여부 | `false` |
| `PUBCHEM_FALLBACK` | no | `true` | 구조 해석 fallback 토글 | `false` |
| `QCVIZ_SCF_CACHE_MAX_SIZE` | no | `256` | config 기준 SCF cache size | `512` |
| `SCF_CACHE_MAX_SIZE` | no | `256` | resolver/compute fallback cache size | `512` |
| `QCVIZ_ION_OFFSET_ANGSTROM` | no | `5.0` | 이온쌍 시각화 offset | `7.5` |
| `ION_OFFSET_ANGSTROM` | no | `5.0` | 이온쌍 offset fallback | `7.5` |
| `QCVIZ_APP_TITLE` | no | `QCViz-MCP` | UI 제목 | `QCViz-MCP Enterprise` |
| `QCVIZ_APP_VERSION` | no | `v2` | UI 버전 표기 | `v3` |
| `QCVIZ_CORS_ALLOW_ORIGINS` | no | `*` | CORS origin 목록 | `https://example.com` |
| `QCVIZ_PASSWORD_HASH_ITERATIONS` | no | `240000` | PBKDF2 반복 횟수 | `300000` |
| `QCVIZ_AUTH_TOKEN_TTL_SECONDS` | no | `2592000` | auth token TTL | `604800` |
| `QCVIZ_AUTH_DB` | no | `/tmp/qcviz_auth.sqlite3` | SQLite auth DB 경로 | `D:\data\qcviz_auth.sqlite3` |
| `QCVIZ_ADMIN_USERNAME` | no | unset | 기본 admin 계정명 seed | `admin` |
| `QCVIZ_ADMIN_PASSWORD` | no | unset | 기본 admin 비밀번호 seed | `change-me` |
| `QCVIZ_JOB_BACKEND` | no | `inmemory` | job backend 선택 | `arq` |
| `QCVIZ_JOB_POLL_SECONDS` | no | `0.25` | job polling 주기 | `0.5` |
| `QCVIZ_JOB_MAX_WORKERS` | no | `1` | 계산 worker 수 | `2` |
| `QCVIZ_MAX_JOBS` | no | `200` | 잡 저장 상한 | `500` |
| `QCVIZ_MAX_JOB_EVENTS` | no | `200` | 이벤트 보관 상한 | `500` |
| `QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION` | no | 코드상 기본 `2` | 세션별 동시 활성 잡 제한 | `1` |
| `QCVIZ_MAX_ACTIVE_JOBS_PER_USER` | no | 코드상 기본 `3` | 사용자별 동시 활성 잡 제한 | `2` |
| `QCVIZ_MAX_JOB_RETRIES` | no | worker 기본 `1` | 잡 최대 재시도 횟수 | `3` |
| `QCVIZ_CACHE_DIR` | no | `/tmp/qcviz_scf_cache` | SCF 디스크 캐시 디렉터리 | `D:\cache\qcviz` |
| `QCVIZ_SESSION_TTL_SECONDS` | no | `604800` | 익명 세션 TTL | `86400` |
| `QCVIZ_MAX_SESSIONS` | no | `5000` | 메모리 세션 수 상한 | `10000` |
| `QCVIZ_WS_POLL_SECONDS` | no | `0.25` | WS backend polling 주기 | `0.5` |
| `QCVIZ_WS_PING_INTERVAL` | no | `25` | WS ping interval | `30` |
| `QCVIZ_WS_TIMEOUT` | no | `60` | WS receive timeout | `90` |
| `QCVIZ_LLM_PROVIDER` | no | `auto` | LLM provider 선택 | `gemini` |
| `QCVIZ_OPENAI_MODEL` | no | `gpt-4.1-mini` | OpenAI 모델명 | `gpt-5.4` |
| `OPENAI_API_KEY` | no | unset | OpenAI API key | `sk-...` |
| `QCVIZ_REDIS_URL` | no | `redis://127.0.0.1:6379/0` | Redis 연결 URL | `redis://localhost:6379/1` |
| `QCVIZ_ARQ_QUEUE_NAME` | no | `qcviz-jobs` | Arq queue 이름 | `qcviz-prod` |
| `QCVIZ_STALE_RECOVERY_INTERVAL_SECONDS` | no | `5` | stale recovery 주기 | `10` |
| `QCVIZ_AUTO_RETRY_ENABLED` | no | `1` | 백엔드 auto retry 사용 여부 | `0` |
| `QCVIZ_REDIS_PREFIX` | no | `qcviz` | Redis key prefix | `qcviz-dev` |
| `QCVIZ_WORKER_HEARTBEAT_TTL_SECONDS` | no | `90` | worker heartbeat TTL | `120` |
| `QCVIZ_STALE_RUNNING_AFTER_SECONDS` | no | `180` | stale running 판단 시점 | `300` |
| `QCVIZ_QUEUE_ETA_DEFAULT_SECONDS` | no | `75.0` | 기본 ETA | `120` |
| `QCVIZ_WORKER_ID` | no | hostname:pid | worker id override | `worker-a` |
| `QCVIZ_AUTO_RETRY_ON_FAILURE` | no | `1` | worker 실패 시 auto retry | `0` |
| `QCVIZ_WORKER_HEARTBEAT_SECONDS` | no | `10` | worker heartbeat 간격 | `15` |
| `QCVIZ_ARQ_MAX_JOBS` | no | `QCVIZ_JOB_MAX_WORKERS` fallback | worker 동시 잡 수 | `4` |

### 3.2 저장소 내 `.env.example` 상태

- 실제 `.env.example` 파일은 존재하지 않는다.
- 아래 블록은 저장소 코드에서 읽는 환경 변수만 모은 문서용 reference template이다.
- 즉, "existing file full text"가 아니라 "code-derived reference text"다.

```dotenv
# Server
QCVIZ_HOST=127.0.0.1
QCVIZ_PORT=8765
QCVIZ_LOG_LEVEL=INFO
QCVIZ_CORS_ALLOW_ORIGINS=*

# Auth / Session
QCVIZ_AUTH_DB=/tmp/qcviz_auth.sqlite3
QCVIZ_AUTH_TOKEN_TTL_SECONDS=2592000
QCVIZ_SESSION_TTL_SECONDS=604800
QCVIZ_MAX_SESSIONS=5000

# LLM
QCVIZ_LLM_PROVIDER=auto
QCVIZ_GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=
QCVIZ_OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=

# Chemistry resolution
MOLCHAT_BASE_URL=http://psid.aizen.co.kr/molchat
MOLCHAT_TIMEOUT=15
PUBCHEM_FALLBACK=true
PUBCHEM_TIMEOUT=10

# Jobs / Queue
QCVIZ_JOB_BACKEND=inmemory
QCVIZ_JOB_MAX_WORKERS=1
QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION=2
QCVIZ_MAX_ACTIVE_JOBS_PER_USER=3
QCVIZ_MAX_JOB_EVENTS=200
QCVIZ_MAX_JOB_RETRIES=1

# Cache
QCVIZ_CACHE_DIR=/tmp/qcviz_scf_cache
SCF_CACHE_MAX_SIZE=256

# Redis / Worker
QCVIZ_REDIS_URL=redis://127.0.0.1:6379/0
QCVIZ_ARQ_QUEUE_NAME=qcviz-jobs
QCVIZ_REDIS_PREFIX=qcviz
QCVIZ_WORKER_HEARTBEAT_SECONDS=10
QCVIZ_WORKER_HEARTBEAT_TTL_SECONDS=90
```

## 4. Database Setup

### 4.1 SQLite auth DB

- 별도 migration 명령은 없다.
- 첫 auth 관련 API 호출 시 `init_auth_db()`가 테이블을 자동 생성한다.
- DB 경로는 `QCVIZ_AUTH_DB`로 변경할 수 있다.

### 4.2 세션 저장소

- 세션 저장소는 메모리 기반이므로 별도 초기화가 없다.
- 서버 재시작 시 세션은 초기화된다.

### 4.3 Redis 저장소

- split-worker 모드에서만 필요하다.
- 코드상 기본 URL은 `redis://127.0.0.1:6379/0`다.
- 별도 schema migration은 없다.

### 4.4 테스트 데이터

- 정식 seed script는 없다.
- 선택적 기본 admin seed는 `QCVIZ_ADMIN_USERNAME`, `QCVIZ_ADMIN_PASSWORD`로 가능하다.
- 사용자 데이터는 `/auth/register`로 직접 생성할 수 있다.

## 5. Available Scripts

### 5.1 package.json / Makefile 상태

- `package.json` 없음
- `Makefile` 없음
- `justfile` 없음
- `Taskfile.yml` 없음

### 5.2 실제 실행 가능한 저장소 스크립트

| 명령어 | 설명 | 사용 시점 |
|---|---|---|
| `python run_dev.py` | PySCF mock으로 Windows에서 서버 부팅 | UI/API smoke test |
| `bash start_server.sh 8000` | Linux/macOS 개발 서버 시작 | 쉘 기반 개발 실행 |
| `bash run.sh` | 특정 배포 경로와 루트 패스를 가진 실행 예시 | 배포형 로컬 실행 |
| `uvicorn qcviz_mcp.web.app:app --reload` | 기본 수동 실행 | 일반 개발 |
| `pytest` | 테스트 실행 | dev extra 설치 후 |

### 5.3 테스트 실행 주의

- 현재 작업 환경에서는 `pyscf` 미설치로 인해 대표 pytest 실행이 import 단계에서 실패했다.
- `run_dev.py`는 테스트용 mock 실행에는 유용하지만 실제 계산 검증은 하지 못한다.

## 6. IDE Configuration

### 6.1 저장소에 커밋된 IDE 설정 상태

- `.vscode/launch.json` 없음
- `.editorconfig` 없음
- `ruff.toml`, `.ruff.toml` 없음
- `.eslintrc*` 없음
- `.prettierrc*` 없음

### 6.2 실무적으로 필요한 최소 기능

- Python 문법/가상환경 인식
- JavaScript 문법 강조
- Markdown 미리보기
- PowerShell 또는 Bash 실행
- 긴 Python 파일 탐색을 위한 outline 지원

### 6.3 디버깅 전략

- FastAPI 서버 디버깅은 `uvicorn qcviz_mcp.web.app:app --reload`를 직접 실행하는 방식이 기본이다.
- worker 디버깅은 split-worker 모드에서 별도 프로세스로 `qcviz_mcp.worker.arq_worker`를 띄워야 한다.
- 저장소에 공식 debugger preset은 없다.

## 7. Docker Development

### 7.1 현재 상태

- `Dockerfile` 없음
- `docker-compose.yml` 없음
- Kubernetes manifest 없음

### 7.2 문서화 원칙

- 이 저장소는 현재 Docker 기반 개발환경을 제공하지 않는다.
- 따라서 포트 매핑 표나 compose 서비스 설명을 코드 기반 사실로 작성할 수 없다.
- commit-ready 문서 관점에서는 "부재"를 명시하는 것이 정확하다.

## 8. Troubleshooting

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| `ModuleNotFoundError: No module named 'qcviz_mcp'` | `PYTHONPATH` 또는 editable install 누락 | `pip install -e .` 또는 `PYTHONPATH=src` 설정 |
| `ModuleNotFoundError: No module named 'pyscf'` | PySCF 미설치 | 실제 계산 필요 시 `pip install pyscf` 또는 해당 extra/환경 준비 |
| `/auth/*` 호출 시 SQLite 경로 오류 | `QCVIZ_AUTH_DB` 경로 권한/경로 문제 | 쓰기 가능한 경로로 변경 |
| 세션이 갑자기 무효화됨 | 메모리 기반 세션 저장소 재시작/만료 | `POST /session/bootstrap` 재호출 |
| WebSocket이 `4403`으로 종료됨 | session token 또는 auth token 불일치 | bootstrap된 세션 토큰과 동일 값 사용 |
| Redis 모드에서 worker가 보이지 않음 | `QCVIZ_REDIS_URL` 또는 worker 프로세스 미기동 | Redis 연결 확인 후 worker 실행 |
| README 예제를 그대로 쳤는데 경로가 맞지 않음 | README에 `version02` 흔적이 남아 있음 | 실제 저장소 루트 `version03` 기준으로 실행 |
| `pyproject.toml`의 pytest marker가 깨져 보임 | 인코딩 손상 흔적 | marker 설명 문자열은 무시하고 pytest 설정 핵심 값만 사용 |

## 9. Directory Structure Guide

### 9.1 전체 폴더 트리 요약

```text
version03/
├── src/qcviz_mcp/                 # 메인 패키지
│   ├── web/                       # FastAPI, REST/WS, UI static/template
│   ├── compute/                   # PySCF 실행 및 캐시
│   ├── services/                  # MolChat, PubChem, Gemini 등 외부 연계
│   ├── llm/                       # planning, normalization, provider shim
│   ├── advisor/                   # 방법 추천, confidence, literature validation
│   ├── analysis/                  # 결과 분석 보조 유틸
│   ├── validation/                # charge/orbital validation
│   ├── backends/                  # 레거시 backend 경로
│   ├── tools/                     # 레거시 MCP 도구
│   ├── renderers/                 # 렌더링 도우미
│   ├── execution/                 # 레거시 호환 실행 계층
│   └── worker/                    # Arq worker
├── tests/                         # API/unit/integration tests
├── docs/                          # 설계 변경 기록 및 감사 문서
├── output/                        # 생성 결과 샘플
├── run_dev.py                     # Windows mock 실행
├── start_server.sh                # 일반 shell 실행
├── run.sh                         # 특정 배포 루트 패스 실행
├── pyproject.toml                 # 패키지/의존성/pytest 설정
└── README.md                      # 개요 및 시작 가이드
```

### 9.2 "새 파일은 어디에 만들어야 하나?" 가이드

| 새 코드 유형 | 위치 |
|---|---|
| 새 REST/WS 엔드포인트 | `src/qcviz_mcp/web/routes/` |
| 앱 조립/마운트 변경 | `src/qcviz_mcp/web/app.py` |
| 새 외부 API 클라이언트 | `src/qcviz_mcp/services/` |
| 새 자연어 planning/normalization 로직 | `src/qcviz_mcp/llm/` |
| 새 계산 로직 또는 PySCF 확장 | `src/qcviz_mcp/compute/` |
| 계산 후 설명/추천 로직 | `src/qcviz_mcp/advisor/` 또는 `src/qcviz_mcp/web/advisor_flow.py` |
| 프런트엔드 UI 동작 | `src/qcviz_mcp/web/static/` |
| 프런트엔드 HTML 구조 | `src/qcviz_mcp/web/templates/` |
| 인증/세션 저장 | `src/qcviz_mcp/web/auth_store.py`, `src/qcviz_mcp/web/session_auth.py` 인접 |
| split-worker 런타임 변경 | `src/qcviz_mcp/web/arq_backend.py`, `src/qcviz_mcp/worker/` |

### 9.3 피해야 할 위치

- 신규 핵심 기능을 `backends/`, `tools/`, `execution/`에 추가하는 것은 현재 주 경로 기준으로 권장되지 않는다.
- 레거시 경로는 유지보수 비용을 늘리므로 신규 개발은 `web + compute + services + llm + advisor` 축에 넣는 것이 맞다.

---

# 📄 DOCUMENT 5 — PROJECT_CONTEXT.md

## 1. One-Paragraph Summary

QCViz-MCP는 FastAPI 웹 서버, PySCF 계산 엔진, MolChat/PubChem 구조 해석, Gemini/OpenAI 기반 자연어 planning, 그리고 3Dmol.js 프런트엔드를 결합한 양자화학 시각화 워크스페이스다. 사용자는 자연어로 분자와 원하는 분석을 입력하고, 시스템은 세션/인증을 처리한 뒤 구조를 해석하고 계산 잡을 생성하며, WebSocket으로 진행률과 결과를 스트리밍한다. 계산 결과는 advisor 모듈을 통해 추천, 신뢰도, 재현성 스크립트, 문헌 검증 요약으로 확장된다. 현재 주 경로는 `web`, `compute`, `services`, `llm`, `advisor`이며, Redis/Arq 기반 split-worker 모드는 선택적 확장이다.

## 2. Tech Stack Quick Reference

| Layer | Technology | Version | Config File |
|---|---|---|---|
| Language | Python | `>=3.10` | `pyproject.toml` |
| Web Framework | FastAPI | `>=0.110,<1.0` | `pyproject.toml` |
| ASGI Server | Uvicorn | `>=0.29,<1.0` | `pyproject.toml` |
| Templates | Jinja2 | `>=3.1,<4.0` | `pyproject.toml` |
| Validation | Pydantic | `>=2.6,<3.0` | `pyproject.toml` |
| Chemistry | PySCF | `>=2.4,<3.0` | `pyproject.toml` |
| HTTP client | httpx | `>=0.27,<1.0` | `pyproject.toml` |
| Numeric | numpy, scipy | `>=1.26`, `>=1.11` | `pyproject.toml` |
| Auth DB | SQLite | stdlib | `src/qcviz_mcp/web/auth_store.py` |
| Queue/Store | Redis + Arq | optional | `src/qcviz_mcp/web/arq_backend.py` |
| Frontend | Plain JS + 3Dmol.js | unbundled | `src/qcviz_mcp/web/templates/index.html` |

## 3. Architecture at a Glance

- 브라우저는 REST와 WebSocket으로 FastAPI에 연결된다.
- `chat.py`와 `compute.py`가 애플리케이션 진입점이다.
- 구조 해석은 MolChat 우선, PubChem 폴백이다.
- 계산은 `pyscf_runner.py`가 수행하고 결과는 advisor/result_explainer가 후처리한다.
- 운영 확장이 필요하면 Redis/Arq 워커 분리 모드를 켤 수 있다.

```text
Browser
 -> web/app.py
 -> chat.py / compute.py
 -> services + llm
 -> pyscf_runner.py
 -> advisor_flow.py / result_explainer.py
 -> REST/WS response
```

## 4. Core Business Logic Map

| Module | Path | Purpose | Key Dependencies |
|---|---|---|---|
| Chat route | `src/qcviz_mcp/web/routes/chat.py` | 자연어 입력 해석, WS 스트리밍, clarification | `llm`, `conversation_state`, `compute` |
| Compute route | `src/qcviz_mcp/web/routes/compute.py` | 계산 잡 준비/제출/조회/취소 | `structure_resolver`, `pyscf_runner`, `session_auth` |
| PySCF runner | `src/qcviz_mcp/compute/pyscf_runner.py` | 실제 양자화학 계산 수행 | PySCF, disk cache, analysis helpers |
| Structure resolver | `src/qcviz_mcp/services/structure_resolver.py` | 분자 구조 해석 | MolChat, PubChem |
| Ion pair handler | `src/qcviz_mcp/services/ion_pair_handler.py` | 이온쌍/염 구조 조립 | resolver output, offset config |
| LLM agent | `src/qcviz_mcp/llm/agent.py` | Gemini/OpenAI/heuristic planning | provider keys, schemas |
| Normalizer | `src/qcviz_mcp/llm/normalizer.py` | 자연어에서 구조/방법/의도 추출 | regex/rules |
| Advisor flow | `src/qcviz_mcp/web/advisor_flow.py` | result -> advisor contract 변환 | advisor modules |
| Conversation state | `src/qcviz_mcp/web/conversation_state.py` | follow-up context 유지 | session id, last result |
| Auth store | `src/qcviz_mcp/web/auth_store.py` | 사용자/토큰/role 관리 | SQLite |

## 5. Critical Code Paths

### 5.1 자연어 계산 요청

- Trigger: 사용자가 `/chat` 또는 WS에 자연어 요청을 보낸다.
- Execution Path:
- `web/static/chat.js`
- `web/routes/chat.py`
- `llm/normalizer.py`
- `web/routes/compute.py`
- `services/structure_resolver.py`
- `compute/pyscf_runner.py`
- Output: queued/completed job와 result summary

### 5.2 후속 질문 재사용

- Trigger: 사용자가 "같은 구조로 HOMO 보여줘" 같은 follow-up을 보낸다.
- Execution Path:
- `web/routes/chat.py`
- `web/conversation_state.py`
- `web/routes/compute.py::_apply_session_continuation`
- `compute/pyscf_runner.py`
- Output: 이전 구조를 재사용한 새 계산

### 5.3 구조 해석 폴백

- Trigger: 분자명이 애매하거나 구조가 직접 주어지지 않는다.
- Execution Path:
- `services/structure_resolver.py`
- `services/molchat_client.py`
- `services/pubchem_client.py`
- `services/ion_pair_handler.py`
- Output: resolved XYZ / artifact

### 5.4 split-worker 실행

- Trigger: `QCVIZ_JOB_BACKEND`가 Redis/Arq 모드다.
- Execution Path:
- `web/job_backend.py`
- `web/arq_backend.py`
- `web/redis_job_store.py`
- `worker/arq_worker.py`
- `web/routes/compute.py::_run_direct_compute`
- Output: Redis-backed queued execution

### 5.5 결과 시각화

- Trigger: 결과 또는 진행 이벤트가 브라우저에 도착한다.
- Execution Path:
- `web/static/chat.js`
- `window.QCVizApp`
- `web/static/results.js`
- `web/static/viewer.js`
- Output: 탭 렌더링, 3D 오비탈/ESP 뷰어 업데이트

## 6. Data Model Summary

```text
users --1:N--> auth_tokens
session_record --1:N--> job_record --1:N--> job_event
session_record --1:1(latest)--> conversation_state
worker_heartbeat --runtime--> job_record
scf_cache_meta <--> scf_checkpoint
```

핵심 포인트:

- 유일한 실제 SQL FK는 `auth_tokens.username -> users.username`다.
- 나머지 관계는 앱 레벨 참조다.
- 세션과 사용자 개념이 별도로 존재한다.
- Redis는 정규화보다 index key 전략에 의존한다.

## 7. API Surface Summary

| Area | Route | Summary |
|---|---|---|
| UI | `GET /` | 메인 HTML |
| UI | `GET /index.html` | 메인 HTML alias |
| API root | `GET /api` | API route table |
| Health | `GET /health` | 전체 health |
| Session | `POST /session/bootstrap` | 세션 발급/검증 |
| Auth | `POST /auth/register` | 사용자 생성 + 로그인 |
| Auth | `POST /auth/login` | auth token 발급 |
| Auth | `GET /auth/me` | 내 사용자 정보 |
| Auth | `POST /auth/logout` | auth token 폐기 |
| Admin | `GET /admin/overview` | 운영 요약 |
| Admin | `POST /admin/jobs/{job_id}/cancel` | 관리자 취소 |
| Admin | `POST /admin/jobs/{job_id}/requeue` | 관리자 재큐잉 |
| Chat | `GET /chat/health` | chat subsystem health |
| Chat | `POST /chat` | REST chat/planning/submit |
| Chat | `WS /ws/chat` | 실시간 대화/진행률 |
| Compute | `GET /compute/health` | compute subsystem health |
| Compute | `POST /compute/jobs` | 계산 잡 제출 |
| Compute | `GET /compute/jobs` | 잡 목록 |
| Compute | `GET /compute/jobs/{job_id}` | 잡 스냅샷 |
| Compute | `GET /compute/jobs/{job_id}/result` | 결과 |
| Compute | `GET /compute/jobs/{job_id}/events` | 이벤트 |
| Compute | `DELETE /compute/jobs/{job_id}` | 잡 삭제 |
| Compute | `POST /compute/jobs/{job_id}/cancel` | 잡 취소 |
| Compute | `POST /compute/jobs/{job_id}/orbital_cube` | 추가 큐브 생성 |

## 8. Code Conventions Cheat Sheet

### 8.1 네이밍 규칙

- Python 함수는 `snake_case`
- 클래스는 `PascalCase`
- 상수는 `UPPER_SNAKE_CASE`
- 프런트엔드 전역 store는 `window.QCVizApp`
- 헤더 이름은 `X-QCViz-*`

### 8.2 파일 구조 규칙

- HTTP/WS route는 `web/routes/`
- 저장소/세션/auth는 `web/`
- 계산 엔진은 `compute/`
- 외부 서비스는 `services/`
- planning/normalization은 `llm/`
- 후처리 추천은 `advisor/`

### 8.3 패턴 규칙

- dict contract가 많으므로 키 이름을 함부로 바꾸지 말 것
- follow-up 관련 키는 `conversation_state.py`와 맞춰야 함
- 새로운 API는 session/auth header 규약을 유지해야 함
- 프런트엔드 상태 변경은 `QCVizApp` 이벤트 흐름과 맞춰야 함

### 8.4 DO / DON'T 예시

DO:

```python
x_qcviz_auth_token: Optional[str] = Header(default=None, alias="X-QCViz-Auth-Token")
```

DON'T:

```python
authorization: str = Header(...)
```

DO:

```python
return {"ok": True, "job_id": job_id, "session_id": request_session_id}
```

DON'T:

```python
return JobResponseModel(...)
```

설명:

- 현재 코드베이스는 강한 Pydantic response 모델보다 dict 응답을 일관되게 사용한다.
- 새 코드도 기존 contract와 호환되도록 dict 기반을 우선 고려해야 한다.

## 9. Known Gotchas & Complexity Hotspots

### 9.1 작업 전 반드시 인지할 점

- `compute.py`는 거대하고 다중 책임을 가진다.
- `chat.py`는 WS 프로토콜과 planning을 함께 가진다.
- `pyscf_runner.py`는 결과 contract의 사실상 원천이다.
- 레거시 `backends/`, `tools/`, `execution/` 경로가 여전히 존재한다.
- `.env`에 비밀값이 존재한다.
- `pyproject.toml`의 marker 문자열 일부가 깨져 있다.

### 9.2 특히 취약한 파일

| 파일 | 이유 |
|---|---|
| `src/qcviz_mcp/web/routes/compute.py` | API, manager, quota, continuation, direct compute가 한 파일 |
| `src/qcviz_mcp/web/routes/chat.py` | WS state machine과 REST chat 흐름이 한 파일 |
| `src/qcviz_mcp/compute/pyscf_runner.py` | 계산 결과 구조 변경의 영향 범위가 매우 큼 |
| `src/qcviz_mcp/web/static/chat.js` | 서버 이벤트 contract에 직접 결합 |
| `src/qcviz_mcp/web/static/viewer.js` | result visualization schema에 직접 결합 |

### 9.3 AI 에이전트용 경고

- `result` 딕셔너리 구조를 추측하지 말고 기존 키 사용처를 따라가야 한다.
- job access control을 우회하는 코드를 넣으면 안 된다.
- WebSocket 이벤트 이름을 바꾸면 프런트엔드가 즉시 깨진다.
- session continuation 키(`last_structure_query`, `last_resolved_artifact`)를 유지해야 한다.

## 10. Module Dependency Graph

```text
web/app.py
├─> web/routes/chat.py
│   ├─> web/session_auth.py
│   ├─> web/auth_store.py
│   ├─> llm/agent.py
│   ├─> llm/normalizer.py
│   ├─> web/conversation_state.py
│   └─> web/routes/compute.py
│
└─> web/routes/compute.py
    ├─> web/session_auth.py
    ├─> web/auth_store.py
    ├─> services/structure_resolver.py
    │   ├─> services/molchat_client.py
    │   └─> services/pubchem_client.py
    ├─> services/ion_pair_handler.py
    ├─> compute/pyscf_runner.py
    │   ├─> compute/disk_cache.py
    │   ├─> analysis/*
    │   └─> validation/*
    ├─> web/advisor_flow.py
    │   └─> advisor/*
    └─> web/result_explainer.py
```

## 11. Environment & Deployment Quick Ref

### 11.1 핵심 환경 변수

- `QCVIZ_JOB_BACKEND`
- `QCVIZ_REDIS_URL`
- `QCVIZ_AUTH_DB`
- `QCVIZ_SESSION_TTL_SECONDS`
- `QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION`
- `GEMINI_API_KEY` 또는 `OPENAI_API_KEY`
- `MOLCHAT_BASE_URL`

### 11.2 대표 실행 명령

```powershell
pip install -e ".[dev,llm-gemini]"
$env:PYTHONPATH = "src"
uvicorn qcviz_mcp.web.app:app --host 127.0.0.1 --port 8765 --reload
```

### 11.3 주요 URL

- UI: `http://127.0.0.1:8765/`
- Health: `http://127.0.0.1:8765/health`
- Chat WS: `ws://127.0.0.1:8765/ws/chat`
- Compute jobs: `http://127.0.0.1:8765/compute/jobs`

## 12. "Where Do I Put This?" Decision Tree

```text
새 API 엔드포인트인가?
 -> yes -> src/qcviz_mcp/web/routes/
 -> no

새 인증/세션 저장 로직인가?
 -> yes -> src/qcviz_mcp/web/
 -> no

새 외부 서비스 연동인가?
 -> yes -> src/qcviz_mcp/services/
 -> no

새 자연어 해석/플래닝 규칙인가?
 -> yes -> src/qcviz_mcp/llm/
 -> no

새 양자화학 계산/후처리 로직인가?
 -> yes -> src/qcviz_mcp/compute/ 또는 src/qcviz_mcp/advisor/
 -> no

새 UI 인터랙션인가?
 -> yes -> src/qcviz_mcp/web/static/
 -> no

새 템플릿 마크업인가?
 -> yes -> src/qcviz_mcp/web/templates/
 -> no

새 테스트인가?
 -> yes -> tests/ 또는 tests/v3/
 -> no

레거시 MCP tool 확장인가?
 -> 가능한 한 피하고 현재 web-first 경로에 구현
```

---

## Scan Metadata

| 항목 | 값 |
|---|---|
| Scan Timestamp | `2026-03-28 17:29:57 +09:00` |
| Total Directories | `29` |
| Total Files | `248` |
| Total Lines | `167640` |
| Scan Duration | `Not instrumented in session; Phase 11 report generated after prior scan completion` |
| Report File | `DEEP_SCAN_REPORT_qcviz-mcp_2026-03-28.md` |

### 메타데이터 해설

- 파일 수와 라인 수는 `.git`, `node_modules`, `dist`, `build`, `.next`, `target`, `__pycache__`, `.pytest_cache`, `.ruff_cache`를 제외하고 집계했다.
- 이 통합 보고서는 Phase 0-10에서 축적된 스캔 결과를 바탕으로 작성됐다.
- Phase 11 규칙에 따라 보고서는 이메일 발송 성공 여부와 무관하게 로컬 파일로 저장된다.
