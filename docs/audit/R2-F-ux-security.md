---
audit_round: 2
category: F
priority: P2, P3, 확인완료
related_files:
  [viewer.js, chat.js, compute.py, pyscf_runner.py, agent.py, providers.py]
defects: "F1 stripped cube 감지, F4 XSS (안전확인), F6 Provider 중복, F7 PySCF 미설치"
---

# R2-F: UX 연속성 및 Graceful Degradation

> 2차 감사 | 축 F | 결함 4건 (1건 안전 확인)

---

## F1: 서버 재시작 후 복원 — stripped cube placeholder 감지 — **P2 Medium**

D1 수정 후, cube base64는 `"__stripped__"`로 저장됩니다. `findCubeB64`에서 이를 감지해야 합니다.

**수정 (`viewer.js`):**

```javascript
function findCubeB64(result, type) {
  var viz = result.visualization || {};
  var key = type + "_cube_b64";
  var val =
    viz[key] || result[key] || (viz[type] && viz[type].cube_b64) || null;
  if (val === "__stripped__" || val === "[omitted]") return null;
  return val;
}
```

---

## F4: XSS 검증 — `formatMarkdown` — **확인 완료 (안전)**

`escHtml`이 먼저 모든 HTML entity를 이스케이프한 후, `**bold**`와 `` `code` ``만 태그로 변환합니다. `$1` 캡처 그룹의 내용은 이미 이스케이프되어 있으므로 XSS 벡터는 존재하지 않습니다.

---

## F6: `agent.py` ↔ `providers.py` 중복 — **P3 (아키텍처)**

`DummyProvider`의 routing 로직이 `QCVizAgent._heuristic_plan`과 기능적으로 동일합니다. `providers.py`의 `DummyProvider`가 `QCVizAgent._heuristic_plan`을 위임 호출하거나, 하나의 시스템으로 통합해야 합니다.

---

## F7: PySCF 미설치 환경 — **P2 Medium**

`pyscf_runner.py` 상단의 `from pyscf import ...`이 실패하면 서버가 크래시합니다.

**수정:** lazy import + 503 반환:

```python
# compute.py 상단
try:
    from qcviz_mcp.compute import pyscf_runner
    _HAS_PYSCF = True
except ImportError:
    pyscf_runner = None
    _HAS_PYSCF = False

def _run_direct_compute(payload, progress_callback=None):
    if not _HAS_PYSCF:
        raise HTTPException(status_code=503, detail="PySCF is not installed.")
```

---

## 2차 감사 최종 체크리스트

| 접합부                                      | 정합성 | 비고                      |
| ------------------------------------------- | ------ | ------------------------- |
| `pyscf_runner` → `compute.py`: JSON 직렬화  | ✅     | A1 수정 (numpy 타입 변환) |
| `pyscf_runner` → `compute.py`: NaN/Inf 방어 | ✅     | A2, A3 수정               |
| `compute.py` → WebSocket: 에러 형식         | ✅     | B5 수정                   |
| `viewer.js`: 3Dmol 로드 실패 복원           | ✅     | B1 수정                   |
| `viewer.js`: mode 전환 race condition       | ✅     | C1 수정                   |
| Thread safety: SCF cache                    | ✅     | C2 수정                   |
| 메모리: 서버 cube 누적                      | ✅     | D1 수정                   |
| 메모리: 프론트엔드 session 누적             | ✅     | D2 수정                   |
| XSS 안전성                                  | ✅     | F4 확인                   |
| PySCF 미설치                                | ✅     | F7 수정                   |

### 잔존 리스크

| 리스크                        | 심각도 | 설명                                         |
| ----------------------------- | ------ | -------------------------------------------- |
| `disk_cache` 파일 락 미구현   | Medium | 동시 파일 접근 안전성 미확인                 |
| `MoleculeResolver` 미검증     | Low    | import 실패 시 graceful fallback 존재        |
| WebSocket handler 코드 미제공 | Medium | 서버 측 chat handler 미확인                  |
| 대용량 분자 OOM               | Medium | 100+ 원자에서 cubegen 수 GB 메모리 사용 가능 |

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
