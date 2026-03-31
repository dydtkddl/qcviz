---
audit_round: 2
category: C
priority: P0 (Critical), P2 (Medium)
related_files: [viewer.js, pyscf_runner.py, chat.js]
defects: "C1 switchVizMode race condition, C2 _SCF_CACHE thread safety, C3 WebSocket 재연결 동기화"
---

# R2-C: 동시성 및 상태 관리

> 2차 감사 | 축 C | 결함 3건

---

## C1: `switchVizMode` race condition — 연속 호출 시 화면 깨짐 — **P0 Critical**

`switchVizMode("orbital")` 호출 후 Promise가 resolve되기 전에 `switchVizMode("esp")`가 호출되면, 두 render가 경쟁합니다. `state.mode = "switching"` 이후 두 번째 호출에서 guard에 걸리지 않습니다.

**수정 (`viewer.js`):**

```javascript
var _switchingPromise = null;

function switchVizMode(newMode) {
  if (!state.result) return;
  if (state.mode === newMode) return;
  if (_switchingPromise) {
    console.warn("[Viewer] Mode switch already in progress, ignoring.");
    return;
  }

  var prevMode = state.mode;
  state.mode = "switching";

  var p;
  if (newMode === "orbital") p = renderOrbital(state.result);
  else if (newMode === "esp") p = renderESP(state.result);
  else if (newMode === "molecule") p = renderMolecule(state.result);

  if (p) {
    _switchingPromise = p;
    p.then(function () {
      _switchingPromise = null;
      saveViewerSnapshot();
    }).catch(function (err) {
      _switchingPromise = null;
      state.mode = prevMode;
      showControls(prevMode);
    });
  } else {
    state.mode = prevMode;
  }
}
```

---

## C2: `_SCF_CACHE` thread safety — **P2 Medium**

**수정 (`pyscf_runner.py`):**

```python
import threading

_SCF_CACHE = {}
_SCF_CACHE_LOCK = threading.Lock()
```

모든 `_SCF_CACHE` 접근을 `with _SCF_CACHE_LOCK:` 블록으로 감쌈.

---

## C3: WebSocket 재연결 시 running job 상태 동기화 없음 — **P2 Medium**

**수정 (`chat.js`):** `ws.onopen`에서 active job이 있으면 서버에 상태 조회 후 progress UI 복원.

```javascript
state.ws.onopen = function () {
  // ...
  if (state.activeJobId) {
    fetch(
      App.apiPrefix +
        "/compute/jobs/" +
        state.activeJobId +
        "?include_result=true&include_events=true",
    )
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (snap) {
        if (!snap) return;
        if (snap.status === "completed" && snap.result) {
          handleServerEvent({
            type: "result",
            job_id: snap.job_id,
            result: snap.result,
          });
        } else if (snap.status === "failed") {
          handleServerEvent({
            type: "error",
            job_id: snap.job_id,
            message:
              (snap.error && snap.error.message) ||
              "Job failed while disconnected.",
          });
        } else if (snap.status === "running") {
          var prog = ensureProgressUI();
          prog.addStep("Reconnected — job still running", "active");
          if (snap.progress != null) prog.setProgress(snap.progress * 100);
        }
      });
  }
};
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
