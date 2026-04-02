---
audit_round: 2
category: E
priority: P1 (High), P2 (Medium)
related_files: [compute.py, pyscf_runner.py, agent.py]
defects: "E1 KO_STRUCTURE_ALIASES 이중 관리, E2 _normalize_esp_preset 동작 차이, E3 _focus_tab_for_result 로직 중복"
---

# R2-E: 코드 중복 제거

> 2차 감사 | 축 E | 결함 3건

---

## E1: `_KO_STRUCTURE_ALIASES` 이중 관리 — **P1 High**

`pyscf_runner.py`와 `compute.py`에 동일한 dict가 하드코딩되어 있으나 미묘한 차이가 있습니다 (`compute.py`에만 `"에텐": "ethylene"` 존재).

**수정:** `compute.py`에서 `pyscf_runner`의 것을 재사용:

```python
_KO_STRUCTURE_ALIASES = getattr(pyscf_runner, "_KO_STRUCTURE_ALIASES", {})
_KO_STRUCTURE_ALIASES_EXTRA = {"에텐": "ethylene"}
_KO_STRUCTURE_ALIASES = {**_KO_STRUCTURE_ALIASES, **_KO_STRUCTURE_ALIASES_EXTRA}
```

---

## E2: `_normalize_esp_preset` 3개 구현체의 동작 차이 — **P2 Medium**

| 입력          | `pyscf_runner` | `compute.py`    | `agent.py`          |
| ------------- | -------------- | --------------- | ------------------- |
| `"grayscale"` | → `"acs"`      | → `"greyscale"` | → `"greyscale"`     |
| `"hicon"`     | → `"acs"`      | → `"acs"`       | → `"high_contrast"` |

**수정:** `compute.py`에서 `pyscf_runner`의 구현을 재사용하되, 추가 alias 처리.

---

## E3: `_focus_tab_for_result` vs `_focus_tab_from_result` — **P2 Medium**

`compute.py` 버전이 더 robust합니다 (sub-object 내의 cube_b64도 체크).

**수정:** `pyscf_runner.py`를 `compute.py` 수준으로 강화:

```python
def _focus_tab_for_result(result):
    vis = result.get("visualization") or {}
    has_esp = bool(vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
    has_dens = bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
    has_orb = bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"))
    # ...
```

---

### 3단계 정규화 책임 분리 문서

| 단계                            | 위치              | 책임                   |
| ------------------------------- | ----------------- | ---------------------- |
| 1. `_finalize_result_contract`  | `pyscf_runner.py` | 계산 결과의 구조 보장  |
| 2. `_normalize_result_contract` | `compute.py`      | API 계약 보장          |
| 3. `normalizeResult`            | `results.js`      | 프론트엔드 렌더링 호환 |

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
