---
audit_round: 2
category: D
priority: P0 (Critical), P1 (High)
related_files: [compute.py, results.js]
defects: "D1 cube base64 메모리 누수, D2 sessionResults 무제한 누적"
---

# R2-D: 메모리 관리 및 성능

> 2차 감사 | 축 D | 결함 2건

---

## D1: `InMemoryJobManager` — 완료 job의 cube base64로 인한 메모리 누수 — **P0 Critical**

200개 job × 10-20MB cube data = 2-4GB 서버 메모리. `_prune`이 오래된 terminal job을 삭제하지만, prune 전까지 메모리가 축적됩니다.

**수정 — cube 데이터를 result에서 분리 (`compute.py`):**

```python
def _strip_cube_data_for_storage(result):
    if not result or not isinstance(result, dict):
        return result
    stripped = dict(result)
    for key in ("orbital_cube_b64", "esp_cube_b64", "density_cube_b64"):
        if key in stripped and stripped[key] and len(str(stripped[key])) > 1000:
            stripped[key] = "__stripped__"
    viz = stripped.get("visualization")
    if isinstance(viz, dict):
        viz = dict(viz)
        stripped["visualization"] = viz
        for key in ("orbital_cube_b64", "esp_cube_b64", "density_cube_b64"):
            if key in viz and viz[key] and len(str(viz[key])) > 1000:
                viz[key] = "__stripped__"
    return stripped
```

---

## D2: `results.js` `sessionResults` 무제한 누적 — **P1 High**

**수정 (`results.js`):**

```javascript
var MAX_SESSION_RESULTS = 20;

function update(result, jobId, source) {
  // ... existing code ...
  while (sessionResults.length > MAX_SESSION_RESULTS) {
    sessionResults.splice(0, 1);
    if (activeSessionIdx > 0) activeSessionIdx--;
  }
}
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
