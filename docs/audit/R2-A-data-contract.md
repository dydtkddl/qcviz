---
audit_round: 2
category: A
priority: P0 (Critical), P1 (High)
related_files: [compute.py, pyscf_runner.py, results.js, viewer.js]
defects: "A1 _json_safe numpy, A2 NaN/Inf 방어, A3 NaN 전파, A4 toFixed NaN, A5 빈 virtual orbital"
---

# R2-A: 데이터 계약 심층 검증

> 2차 감사 | 축 A | 결함 5건

---

## A1: `_json_safe`가 numpy 타입을 처리하지 못함 — **P0 Critical**

`numpy.float64`, `numpy.int64`, `numpy.bool_`은 `json.dumps()`에 성공하지만 FastAPI JSON serializer에서 타입 오류를 일으킬 수 있습니다. `numpy.ndarray`는 `str(value)` → `"[1 2 3]"` 문자열이 되어 프론트엔드에서 파싱 불가능합니다. `np.float64(float('nan'))`은 비표준 JSON `NaN`을 출력합니다.

**수정 (`compute.py`):**

```python
def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        import numpy as np
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            if not math.isfinite(v):
                return None  # NaN/Inf → null
            return v
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, np.ndarray):
            return _json_safe(value.tolist())
    except ImportError:
        pass
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)
```

---

## A2: `pyscf_runner.py`의 float 변환에서 NaN/Inf 방어 누락 — **P1 High**

SCF 비수렴 시 `e_tot`이 `NaN`이 될 수 있으며, JSON 직렬화 또는 프론트엔드 표시에 문제를 일으킵니다.

**수정 — 안전한 float 변환 헬퍼:**

```python
def _finite_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except (TypeError, ValueError, OverflowError):
        return default
```

---

## A3: `_finalize_result_contract`에서 NaN 에너지가 전파됨 — **P1 High**

`_safe_float(float('nan'))`이 `NaN`을 그대로 반환합니다.

**수정 — `_safe_float` 강화 (pyscf_runner.py + compute.py):**

```python
def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default
```

---

## A4: `results.js`에서 NaN이 `toFixed()`를 통과하여 "NaN" 문자열로 표시됨 — **P1 High**

**수정 — 안전한 포맷 헬퍼:**

```javascript
function safeFixed(value, digits, fallback) {
  if (value == null) return fallback || "—";
  var n = Number(value);
  if (!isFinite(n)) return fallback || "—";
  return n.toFixed(digits);
}
```

모든 `Number(x).toFixed(n)` 호출을 `safeFixed(x, n)`으로 교체합니다.

---

## A5: `_build_orbital_items` — 빈 virtual orbital LUMO 처리 — **P1 High**

모든 orbital이 occupied인 경우 `lumo`가 `homo`와 같은 인덱스가 되어 LUMO 요청 시 HOMO 데이터가 반환됩니다.

**수정:** `lumo`를 `None`으로 설정하고, LUMO 요청 시 명시적 경고 반환:

```python
elif raw == "LUMO":
    if lumo is not None:
        idx = lumo
        label = "LUMO"
    else:
        idx = homo
        label = "HOMO (no virtual orbitals)"
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
