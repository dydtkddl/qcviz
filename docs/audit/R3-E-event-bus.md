---
audit_round: 3
category: E (Event Bus)
priority: P0 (Critical), P1 (High, 확인완료)
related_files: [viewer.js, results.js, app.js]
defects: "E3 result:cleared 미처리, E5 status:changed 무한루프 (안전확인), E7 중복 렌더링 (허용), E2 result:switched detail"
---

# R3-E: 이벤트 버스 정합성

> 3차 감사 | Perspective 3 | 결함 4건 (2건 확인완료)

---

## E3: `result:cleared` 이벤트 미처리 — **P0 Critical**

`results.js`의 `removeSessionResult`에서 모든 결과가 제거되면 `App.emit("result:cleared")`를 발생시키지만, 아무도 listen하지 않습니다. viewer는 마지막 분자를 계속 표시합니다.

**수정 (`viewer.js`):**

```javascript
App.on("result:cleared", function () {
  if (state.viewer) {
    clearViewer(state.viewer);
    state.viewer.render();
  }
  state.result = null;
  state.jobId = null;
  state.mode = "none";
  if (dom.$empty) dom.$empty.hidden = false;
  if (dom.$controls) dom.$controls.hidden = true;
  hideLegend();
});
```

---

## E5: `status:changed` 무한 루프 검증 — **확인 완료 (안전)**

`App.setStatus("Ready", "idle")` → `emit("status:changed", {kind:"idle"})` → `s.kind === "idle"`이므로 setTimeout 조건 불성립. 무한 루프 불가.

---

## E7: 중복 렌더링 검증 — **P1 → 확인완료 (허용)**

`setActiveJob` 호출 시: history 1회, session tabs 2회 (app.js + results.js 각각 다른 DOM), results 1회, viewer 1회. **허용 가능.**

---

## E2: `result:switched` detail 구조 — **P1 High**

`entry.jobId`가 `undefined`이면 `state.jobId = null`이 되어 `saveViewerSnapshot()`이 실행되지 않습니다. jobId 없는 결과의 viewer 상태는 저장/복원되지 않으며, 이는 의도된 동작으로 판단합니다.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
