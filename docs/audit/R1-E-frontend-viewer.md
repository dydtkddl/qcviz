---
audit_round: 1
category: E
priority: P1 (High), Low, Medium
related_files: [viewer.js]
defects: "#15 ESP isovalue 순서, #16 switchVizMode molecule fallback, #17 3Dmol 로드 실패 시 UI 미복원"
---

# R1-E: 프론트엔드 결함 — viewer.js

> 1차 감사 | 카테고리 E | 결함 3건

---

## 결함 #15: `renderESP` — ESP isovalue 순서 오류 — **P1 High**

ESP 모드에서는 density isosurface의 isovalue로 `state.espDensityIso` (0.001)가 사용되어야 하지만, `addESPSurface`는 `state.isovalue`(orbital 기본값 0.03)를 사용합니다. `showControls`가 isovalue를 재설정하지만, `showControls`는 `renderESP` 내에서 `addESPSurface` **이후에** 호출되어 첫 렌더링에서 잘못된 isovalue가 사용됩니다.

**수정 (순서 변경):**

```javascript
function renderESP(result) {
  return ensureViewer().then(function (viewer) {
    clearViewer(viewer);
    addMoleculeModel(viewer, result);

    // ESP isovalue 조정을 surface 추가 전에 수행
    if (state.isovalue > 0.02 || state.isovalue < 0.0001) {
      state.isovalue = 0.002;
    }

    try {
      addESPSurface(viewer, result);
    } catch (e) {
      console.error("[Viewer] ESP render error:", e);
    }

    // ... 나머지 코드
    state.mode = "esp";
    showControls("esp");
    showESPLegend();
  });
}
```

---

## 결함 #16: `switchVizMode` — molecule fallback 누락 — **Low**

`newMode`가 `"molecule"`이면 `p`가 `undefined`이고 molecule 렌더링이 수행되지 않습니다.

**수정:**

```javascript
if (p) {
  // ... existing code
} else if (newMode === "molecule") {
  renderMolecule(state.result);
} else {
  state.mode = prevMode;
}
```

---

## 결함 #17: `handleResult` — 3Dmol 로드 실패 시 UI 미복원 — **Medium**

`ensureViewer()`가 reject되면 `state.mode`가 업데이트되지 않은 채로 남아있습니다.

**수정:**

```javascript
if (p)
  p.then(saveViewerSnapshot).catch(function (err) {
    console.error("[Viewer] Render failed:", err);
    state.mode = "none";
    if (dom.$empty) dom.$empty.hidden = false;
    if (dom.$controls) dom.$controls.hidden = true;
  });
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
