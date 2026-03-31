# QCViz-MCP v5 Enterprise (Version 02) — Context Prompt

> **목적:** 이 프롬프트를 먼저 읽은 AI Agent는 이후 전달받는 감사 문서들을 각각 개별 Markdown 파일로 저장할 때, 프로젝트의 전체 맥락·구조·용어를 이미 이해한 상태에서 작업할 수 있습니다.

---

## 1. 프로젝트 정체성

**QCViz-MCP v5 Enterprise**는 브라우저 기반의 양자화학 시각화 플랫폼입니다. 사용자가 분자 이름이나 구조를 자연어로 입력하면, 서버가 PySCF 엔진으로 양자화학 계산(SCF 에너지, 기하 최적화, 오비탈/ESP 큐브 데이터)을 수행하고, 그 결과를 WebSocket으로 프론트엔드에 실시간 전달하여 3Dmol.js로 3D 렌더링합니다. LLM Agent(Planner/Advisor)가 사용자 의도를 해석하고 결과에 대한 자연어 해설을 제공합니다.

**핵심 데이터 파이프라인:**

```
사용자 입력 → chat.js → FastAPI(compute.py)
  → LLM Agent(agent.py / providers.py) → pyscf_runner.py(PySCF)
  → WebSocket push → results.js(파싱) → viewer.js(3Dmol 렌더링)
```

---

## 2. 핵심 파일 맵

| 파일              | 계층        | 역할                                                                            |
| ----------------- | ----------- | ------------------------------------------------------------------------------- |
| `pyscf_runner.py` | 백엔드 코어 | PySCF 래퍼. SCF, geom-opt, 큐브 생성, 오비탈 에너지 추출, NaN/Inf 방어          |
| `compute.py`      | 백엔드 API  | FastAPI 라우터. 작업 큐, payload 관리, 결과 직렬화, 디스크 캐시, WebSocket emit |
| `agent.py`        | LLM 계층    | Planner/Advisor 에이전트. focus_tab 결정, 계산 파라미터 해석                    |
| `providers.py`    | LLM 계층    | LLM 프로바이더 추상화, 스키마 정의                                              |
| `chat.js`         | 프론트엔드  | 사용자 입력 처리, HTTP/WS 통신, 상태 관리                                       |
| `app.js`          | 프론트엔드  | 앱 초기화, basis/basis_set 정규화, 이벤트 버스 설정                             |
| `results.js`      | 프론트엔드  | 서버 결과 수신·파싱, 세션 이력 관리, 오비탈 목록 구성                           |
| `viewer.js`       | 프론트엔드  | 3Dmol.js 래퍼. 분자/오비탈/ESP 렌더링, isovalue 제어                            |
| `index.html`      | 프론트엔드  | DOM 구조. 모든 JS가 참조하는 요소 ID 정의                                       |

---

## 3. 감사 이력 — 세 차례 누적

Version 02는 **3라운드의 심층 감사**를 거쳐 총 **44건의 결함/개선**을 식별·수정했습니다.
"D:\20260305\_양자화학시각화MCP서버구축\version02\docs\VERSION02_ULTIMATE_AUDIT_PROMPT.md"

### 1차 감사 — 기본 동작 결함 (23건)

"D:\20260305\_양자화학시각화MCP서버구축\version02\docs\VERSION02_ULTIMATE_AUDIT_PROMPT.result01.md"
핵심 수정 사항: `pyscf_runner.py`에 누락된 logger 선언 추가(NameError 해소), regex 이중 이스케이프 수정, `compute.py` payload race condition 해소 및 디스크 저장 추가, `focus_tab` 매핑 통일, `basis` vs `basis_set` 필드명 정규화, `results.js`의 `Array.isArray` 검증 수정, `viewer.js` ESP isovalue 순서 및 분자 fallback 추가, snapshot에 `job_type` 포함.

### 2차 감사 — 엣지케이스·복원력 (약 20건, 카테고리 A~F)

"D:\20260305\_양자화학시각화MCP서버구축\version02\docs\VERSION02_ULTIMATE_AUDIT_PROMPT.result02.md"
**A. 데이터 계약 강화**: numpy scalar 직렬화(`_json_safe`), NaN/Inf → `None` 변환(`_finite_float`, `_safe_float`), 프론트엔드 `safeFixed` 헬퍼, 빈 virtual-orbital LUMO 처리.
**B. 오류 전파·복구**: 3Dmol 로드 실패 시 promise 리셋, `renderOrbital` try/catch, SCF 콜백 예외 격리, ESP 실패 알림, `chat.js` HTTP 오류 상세화, SCF 비수렴 경고.
**C. 동시성·상태**: `switchVizMode` 레이스컨디션 해소, `_SCF_CACHE` thread-safe lock, WebSocket 재연결 시 상태 복원.
**D. 메모리·성능**: 큐브 Base64 메모리 누수 방지(`_strip_cube_data_for_storage`), `sessionResults` 최대 20건 제한.
**E. 코드 중복 제거**: 구조 alias/ESP 프리셋 정규화를 `pyscf_runner.py` 단일 소스로 통합, `_focus_tab_for_result` 강화.
**F. UX·보안**: stripped cube placeholder 감지, XSS 안전 확인, PySCF 미설치 시 lazy import + 503 반환.

### 3차 감사 — 7개 관점 정밀 검증 (약 15건, 카테고리 S/D/E/W/P/R/A)

"D:\20260305\_양자화학시각화MCP서버구축\version02\docs\VERSION02_ULTIMATE_AUDIT_PROMPT.result03.md"
**S(시맨틱)**: 0-based vs 1-based 오비탈 인덱스 불일치 수정, ESP 클리핑 동적 상한(`max(0.18, p995*1.2)`), `_COVALENT_RADII` 확장(Li, Na, K, Mg, Ca, Fe, Zn 등), `state.isovalue`를 모드별(`orbitalIsovalue` / `espDensityIso`) 분리.
**D(DOM-JS-CSS)**: `grpESP` DOM 요소 누락 → 추가, `.chat-msg--system` CSS 규칙 보완.
**E(이벤트 버스)**: `result:cleared` 리스너 구현(뷰어 상태 리셋).
**W(WebSocket)**: progress 스케일 0-1 → 0-100 변환, job-ID 가드 추가.
**P(방어적 프로그래밍)**: `deepMerge` 배열 덮어쓰기 동작 문서화, 미지원 method 경고, 오비탈 정렬 안전성, `berny_solver` 콜백 보강.
**R(E2E 추적)**: HOMO 오비탈 요청의 전 구간 흐름 검증 완료.
**A(아키텍처)**: in-memory job store의 다중 워커 불가 → Redis 기반 마이그레이션 제안.

---

## 4. 우선순위 체계

| 등급   | 의미                                              | 대응 시점 |
| ------ | ------------------------------------------------- | --------- |
| **P0** | 즉시 수정. 미적용 시 핵심 기능 장애               | 즉시      |
| **P1** | 금일 내 수정. 데이터 정합성 또는 사용자 경험 영향 | 당일      |
| **P2** | 금주 내. 개선 사항 또는 비핵심 경로               | 주간      |
| **P3** | 다음 스프린트. 아키텍처 문서, 테스트 설계 등      | 차기      |

---

## 5. 핵심 용어 사전

| 용어                   | 설명                                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| **SCF**                | Self-Consistent Field. 양자화학 기본 계산. 수렴 여부가 모든 후속 결과의 유효성을 결정              |
| **HOMO / LUMO**        | 최고 점유 / 최저 비점유 분자 오비탈. 프론트엔드 기본 선택 대상                                     |
| **큐브 데이터 (Cube)** | 3D 그리드 상의 오비탈 또는 전자밀도 값. Base64로 인코딩되어 전송                                   |
| **ESP**                | 정전기 포텐셜(Electrostatic Potential). 분자 표면에 매핑되는 색상 데이터                           |
| **isovalue**           | 등치면(isosurface) 임계값. 오비탈과 ESP에서 각각 다른 값이 적절                                    |
| **focus_tab**          | 결과 유형에 따라 UI 탭을 결정하는 문자열. "orbital" / "esp" / "energy" 등                          |
| **payload**            | 계산 요청 전체를 담는 딕셔너리. backend 전 구간에서 공유·변형됨                                    |
| **3Dmol.js**           | 브라우저 기반 분자 3D 뷰어 라이브러리                                                              |
| **이벤트 버스**        | 프론트엔드 모듈 간 커스텀 이벤트 통신 채널 (`result:ready`, `result:cleared`, `status:changed` 등) |
| **\_json_safe**        | Python 객체를 JSON 직렬화 가능하게 변환하는 유틸리티. numpy/NaN 처리 핵심                          |

---

## 6. 잔존 리스크

세 차례 감사 후에도 다음 항목은 완전히 해소되지 않았으므로, 문서 저장 시 관련 섹션에 주의가 필요합니다.

첫째, **디스크 캐시 파일 락**이 미구현 상태여서 다중 프로세스 환경에서 캐시 파일 충돌이 발생할 수 있습니다. 둘째, **MoleculeResolver** 모듈의 코드가 부재하여 import 실패 시 graceful fallback이 필요합니다. 셋째, 대형 분자 시스템에서 **cubegen 메모리 과다 사용**이 가능하며, 그리드 크기 동적 조정이 아직 미구현입니다. 넷째, **다중 워커 배포** 시 in-memory job store가 작동하지 않으므로 Redis 등 외부 상태 저장소로의 마이그레이션이 필요합니다.

---

## 7. 문서 저장 가이드라인

이후 전달되는 감사 문서들을 개별 MD 파일로 저장할 때 다음 규칙을 따라 주십시오.

파일명은 `[라운드]-[카테고리]-[제목].md` 형식을 권장합니다 (예: `R3-S-semantic-correctness.md`, `R2-B-error-propagation.md`). 각 파일 상단에는 해당 문서가 어느 감사 라운드에 속하는지, 관련 파일과 우선순위가 무엇인지를 YAML frontmatter 또는 메타 섹션으로 포함해 주십시오. 코드 패치가 포함된 문서는 반드시 원본 코드 블록과 수정 코드 블록을 모두 유지해야 합니다. 교차 참조 매트릭스(DOM-JS-CSS, 이벤트 버스, WebSocket 프로토콜, 오비탈 인덱스)는 표 형식을 그대로 보존하십시오. 각 문서 말미에는 이 Context Prompt 파일에 대한 링크(`→ context-prompt.md 참조`)를 삽입하여 항상 전체 맥락으로 돌아올 수 있게 해 주십시오.

---

**이 Context Prompt 자체도 `00-context-prompt.md`로 저장하여, 모든 문서의 진입점으로 사용하십시오.**
