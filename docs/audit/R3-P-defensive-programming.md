---
audit_round: 3
category: P (Defensive Programming)
priority: P0 (Critical → 확인완료 안전), P1 (High), P2 (Medium)
related_files: [pyscf_runner.py, results.js, app.js]
defects: "P2 미지원 method fallback, P5 orbitals sort 방어, P8 berny callback, P9 deepMerge 배열 (안전확인), P10 snapshot 모드 (S6 해결)"
---

# R3-P: 방어적 프로그래밍

> 3차 감사 | Perspective 6 | 결함 5건 (2건 확인완료/해결)

---

## P2: 미지원 method의 조용한 fallback — **P1 High**

사용자가 "TPSS"를 요청하면 B3LYP로 계산되고, 결과에 `method: "TPSS"`가 표시되어 사용자가 착각합니다.

**수정 (`pyscf_runner.py`):**

```python
xc = xc_map.get(key)
if xc is None:
    xc = key  # PySCF가 직접 지원하는지 시도
    _method_warning = (
        f"Method '{method_name}' is not in the predefined list. "
        f"Attempting to use it directly with PySCF."
    )
mf._qcviz_method_warning = _method_warning
```

---

## P5: orbitals sort 방어 — **P1 High**

`zero_based_index`가 `undefined`이면 sort 결과가 불안정합니다.

**수정:**

```javascript
var sorted = r.orbitals.slice().sort(function (a, b) {
  var ai = a && a.zero_based_index != null ? a.zero_based_index : 0;
  var bi = b && b.zero_based_index != null ? b.zero_based_index : 0;
  return ai - bi;
});
```

---

## P8: berny_solver callback 호환성 — **P1 High**

`geometric_solver`와 `berny_solver`의 callback 인자 형식이 다릅니다 (`envs["gradients"]` vs `envs["gradient"]`).

**수정:**

```python
def _geomopt_callback(envs):
    try:
        if isinstance(envs, dict):
            g = envs.get("gradients", envs.get("gradient", None))
        else:
            g = getattr(envs, "gradients", getattr(envs, "gradient", None))
        # ...
    except Exception:
        pass  # callback 실패로 최적화가 중단되지 않도록
```

---

## P9: `deepMerge` 배열 처리 — **P0 → 확인완료 (안전)**

배열은 덮어쓰기됩니다 (append하지 않음). 서버가 항상 전체 배열을 보내므로 현재 사용 패턴에서 안전합니다.

---

## P10: snapshot 복원 시 모드 호환성 — **P2 → S6에서 해결**

S6에서 모드별 isovalue를 분리했으므로 해결됨.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
