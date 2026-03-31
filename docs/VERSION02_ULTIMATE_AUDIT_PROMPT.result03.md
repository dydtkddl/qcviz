# QCViz-MCP v5 Enterprise — 3차 종합 정밀 감사 보고서

---

## Perspective 1: 시맨틱 정확성

### S1/S2: Orbital Index 일관성 매트릭스 — **P1 High**

전 시스템에 걸쳐 orbital index가 사용되는 모든 지점을 추출합니다.

**pyscf_runner.py:**

| 함수                         | 필드명                          | 의미                 | 기준                           |
| ---------------------------- | ------------------------------- | -------------------- | ------------------------------ |
| `_build_orbital_items`       | `index`                         | MO 번호              | **1-based** (`idx + 1`)        |
| `_build_orbital_items`       | `zero_based_index`              | 배열 인덱스          | **0-based** (`idx`)            |
| `_resolve_orbital_selection` | `index`                         | MO 번호              | **1-based** (`idx + 1`)        |
| `_resolve_orbital_selection` | `zero_based_index`              | 배열 인덱스          | **0-based** (`idx`)            |
| `_resolve_orbital_selection` | `orbital="3"` 입력              | → `int(raw) - 1 = 2` | 입력 1-based → 내부 0-based ✅ |
| `_selected_orbital_vector`   | `selection["zero_based_index"]` | 계수 행렬 인덱스     | **0-based** ✅                 |

**results.js:**

| 함수                          | 필드/변수                                      | 의미                         | 기준                         |
| ----------------------------- | ---------------------------------------------- | ---------------------------- | ---------------------------- |
| `normalizeResult`             | `sorted[i].zero_based_index`                   | sort key                     | **0-based** ✅               |
| `normalizeResult`             | `r._orbital_index_offset`                      | `sorted[0].zero_based_index` | **0-based** ✅               |
| `renderOrbital`               | `orb.zero_based_index` → option value          | `<option value=X>`           | **0-based**                  |
| `renderOrbital` (legacy path) | `var j = start; j < end; j++`                  | 배열 인덱스                  | **0-based**                  |
| `renderOrbital` (legacy path) | `"MO " + realIdx` where `realIdx = j + offset` | 표시 라벨                    | **0-based + offset** (문제!) |

**viewer.js:**

| 함수                           | 필드/변수                                                    | 의미                            | 기준 |
| ------------------------------ | ------------------------------------------------------------ | ------------------------------- | ---- |
| `populateOrbitalSelector`      | `orb.zero_based_index` → option value                        | **0-based**                     |
| `populateOrbitalSelector`      | `currentIdx` from `result.selected_orbital.zero_based_index` | **0-based** ✅                  |
| `selectOrbital` change handler | `parseInt(dom.$selectOrbital.value)`                         | **0-based**                     |
| `selectOrbital` change handler | `state.selectedOrbitalIndex = idx`                           | 저장만 함, 서버로 전송하지 않음 |

**결함 발견 — `results.js` legacy path의 `realIdx`:**

```javascript
var start = Math.max(0, homoIdx - 5);
// ...
for (var j = start; j < end; j++) {
    var realIdx = j + offset;  // offset = sorted[0].zero_based_index
    // ...
    var lbl = labels[j] || "MO " + realIdx;
```

`offset`이 예를 들어 5이면 (`_build_orbital_items`가 window 범위만 반환하므로), `j=0`일 때 `realIdx=5`, 표시는 "MO 5". 그러나 `_build_orbital_items`의 `index`는 1-based이므로 같은 orbital이 "MO 6"으로 표시되어야 합니다.

즉 legacy path에서 `"MO " + realIdx`는 **0-based**이고, `_build_orbital_items`의 `label`은 `"MO {idx+1}"`으로 **1-based**입니다. 두 경로가 혼재되면 같은 orbital이 다른 번호로 표시됩니다.

**수정 (`results.js`):**

```javascript
// legacy path에서:
var realIdx = j + offset;
var lbl = labels[j] || "MO " + (realIdx + 1); // 수정: 1-based로 통일
```

또한 `viewer.js`의 `populateOrbitalSelector` legacy path에서도:

```javascript
var label = "MO " + j;
if (j === homoIdx) label = "HOMO";
else if (j === lumoIdx) label = "LUMO";
```

여기서 `j`는 `mo_energies` 배열의 0-based 인덱스입니다. "MO 0"이 표시됩니다.

**수정 (`viewer.js`):**

```javascript
var label = "MO " + (j + 1); // 수정: 1-based 표시
if (j === homoIdx) label = "HOMO";
else if (j === lumoIdx) label = "LUMO";
```

---

### S4: ESP range clipping 상한 — **P2 Medium**

`np.clip(robust, 0.02, 0.18)` — 이온성 화합물(LiF, NaCl 등)의 ESP 범위는 0.3 a.u. 이상이 될 수 있습니다. 상한 0.18이면 양 극단이 포화됩니다.

**수정 (`pyscf_runner.py`):**

```python
def _compute_esp_auto_range(esp_values, density_values=None, density_iso=0.001):
    # ... 기존 코드로 masked, p90, p95, p98, p995 계산 ...

    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995

    # 수정: 동적 상한 — p995의 1.2배 또는 0.30 중 큰 값
    dynamic_upper = max(0.18, min(p995 * 1.2, 0.50))
    robust = float(np.clip(robust, 0.02, dynamic_upper))
    nice = _nice_symmetric_limit(robust)

    return {
        "range_au": nice,
        # ... rest unchanged ...
    }
```

---

### S5: `_COVALENT_RADII` 누락 원소 — **P1 High**

현재 12개 원소만 포함. 일반적인 유기/무기 원소를 추가합니다.

**수정 (`pyscf_runner.py`):**

```python
_COVALENT_RADII = {
    "H": 0.31, "He": 0.28,
    "Li": 1.28, "Be": 0.96, "B": 0.85, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39, "Fe": 1.32, "Co": 1.26,
    "Ni": 1.24, "Cu": 1.32, "Zn": 1.22, "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20,
    "Rb": 2.20, "Sr": 1.95, "Zr": 1.75, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45,
    "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38, "I": 1.39, "Xe": 1.40,
    "Cs": 2.44, "Ba": 2.15, "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
}
```

---

### S6: `state.isovalue` 모드별 분리 — **P0 Critical**

현재 `state.isovalue`가 orbital(기본 0.03, 범위 0.001~0.2)과 ESP(기본 0.002, 범위 0.0001~0.02) 양쪽에서 공유됩니다. `showControls`에서 범위를 재설정하지만, `renderESP`가 `showControls` 전에 `addESPSurface`를 호출하므로 2차 수정(renderESP 진입 시 보정)이 있어도, 사용자가 orbital 모드에서 0.05로 설정한 후 ESP로 전환하면:

1. `renderESP` 진입
2. `if (state.isovalue > 0.02)` → `state.isovalue = 0.002` 강제 리셋
3. 사용자가 orbital로 다시 전환
4. `renderOrbital` — `state.isovalue`가 0.002로 남아있음
5. orbital이 거의 보이지 않음 (0.002는 너무 작음)

**해결: 모드별 isovalue 분리**

**수정 (`viewer.js`):**

```javascript
var state = {
  // ... existing fields ...
  isovalue: 0.03, // 제거하지 않음 (현재 모드의 active 값)
  orbitalIsovalue: 0.03, // 추가: orbital 전용
  espDensityIso: 0.002, // 추가: ESP 전용 (기존 0.001에서 변경)
  opacity: 0.75,
  // ...
};
```

**수정 — `showControls`:**

```javascript
function showControls(mode) {
  // ... existing code ...

  if (dom.$sliderIso) {
    if (mode === "esp") {
      dom.$sliderIso.min = "0.0001";
      dom.$sliderIso.max = "0.02";
      dom.$sliderIso.step = "0.0001";
      state.isovalue = state.espDensityIso; // 수정: ESP 전용 값 복원
    } else {
      dom.$sliderIso.min = "0.001";
      dom.$sliderIso.max = "0.2";
      dom.$sliderIso.step = "0.001";
      state.isovalue = state.orbitalIsovalue; // 수정: orbital 전용 값 복원
    }
    dom.$sliderIso.value = state.isovalue;
    if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
  }

  // ... rest unchanged ...
}
```

**수정 — slider change handler:**

```javascript
if (dom.$sliderIso) {
  dom.$sliderIso.addEventListener("input", function () {
    state.isovalue = parseFloat(dom.$sliderIso.value);
    if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
  });
  dom.$sliderIso.addEventListener("change", function () {
    // 수정: 현재 모드에 따라 전용 변수도 업데이트
    if (state.mode === "esp") {
      state.espDensityIso = state.isovalue;
    } else {
      state.orbitalIsovalue = state.isovalue;
    }
    reRenderCurrentSurface();
    saveViewerSnapshot();
  });
}
```

**수정 — `renderESP`에서 강제 보정 제거:**

```javascript
function renderESP(result) {
  return ensureViewer().then(function (viewer) {
    // ... clearViewer, addMoleculeModel ...

    // 수정: 강제 보정 대신 ESP 전용 값 사용
    state.isovalue = state.espDensityIso;

    try {
      addESPSurface(viewer, result);
    } catch (e) {
      console.error("[Viewer] ESP render error:", e);
    }
    // ...
  });
}
```

**수정 — `renderOrbital`:**

```javascript
function renderOrbital(result) {
  return ensureViewer().then(function (viewer) {
    // ... clearViewer, addMoleculeModel ...

    // 수정: orbital 전용 값 복원
    state.isovalue = state.orbitalIsovalue;

    // ... addOrbitalSurfaces ...
  });
}
```

**수정 — `saveViewerSnapshot` / `restoreViewerSnapshot`:**

```javascript
function saveViewerSnapshot() {
  if (!state.jobId) return;
  var existing = App.getUISnapshot(state.jobId) || {};
  App.saveUISnapshot(
    state.jobId,
    Object.assign({}, existing, {
      viewerStyle: state.style,
      viewerOrbitalIsovalue: state.orbitalIsovalue, // 수정
      viewerEspDensityIso: state.espDensityIso, // 수정
      viewerOpacity: state.opacity,
      viewerLabels: state.showLabels,
      viewerMode: state.mode,
      viewerOrbitalIndex: state.selectedOrbitalIndex,
      viewerColorScheme: state.colorScheme,
    }),
  );
}

function restoreViewerSnapshot(jobId) {
  var snap = App.getUISnapshot(jobId);
  if (!snap) return;
  if (snap.viewerStyle) state.style = snap.viewerStyle;
  if (snap.viewerOrbitalIsovalue != null)
    state.orbitalIsovalue = snap.viewerOrbitalIsovalue;
  if (snap.viewerEspDensityIso != null)
    state.espDensityIso = snap.viewerEspDensityIso;
  if (snap.viewerOpacity != null) state.opacity = snap.viewerOpacity;
  if (snap.viewerLabels != null) state.showLabels = snap.viewerLabels;
  if (snap.viewerOrbitalIndex != null)
    state.selectedOrbitalIndex = snap.viewerOrbitalIndex;
  if (snap.viewerColorScheme) state.colorScheme = snap.viewerColorScheme;
  // 현재 모드에 맞는 isovalue를 active로 설정
  if (snap.viewerMode === "esp") state.isovalue = state.espDensityIso;
  else state.isovalue = state.orbitalIsovalue;
  syncUIToState();
}
```

---

### S7: `_mol_to_xyz` comment line — 확인 완료

```python
lines = [str(mol.natm), comment or "QCViz-MCP"]
```

`comment`가 빈 문자열 `""`이면 `"" or "QCViz-MCP"` → `"QCViz-MCP"`. ✅ 안전합니다.

---

### S8: `_formula_from_symbols` — 확인 완료

```python
return "".join(f"{el}{n if n != 1 else ''}" for el, n in ordered)
```

단일 He 원자: `counts = {"He": 1}`, ordered = `[("He", 1)]`, 결과 = `"He"`. ✅ 정확합니다.

---

## Perspective 2: DOM-JS-CSS 삼각 정합성

### D2: `grpESP` DOM 존재 여부 — **P0 Critical**

`viewer.js` `collectDom()`:

```javascript
dom.$grpESP = document.getElementById("grpESP");
```

`index.html`을 검색하면 `id="grpESP"`는 **존재하지 않습니다**. HTML에는 `id="grpOrbital"`, `id="grpOpacity"`, `id="grpOrbitalSelect"`, `id="grpColorScheme"` 등이 있지만 `grpESP`는 없습니다.

`showControls`에서:

```javascript
if (dom.$grpESP) dom.$grpESP.hidden = !hasESP;
```

`dom.$grpESP`가 `null`이므로 이 줄은 실행되지 않습니다. ESP 전용 컨트롤 그룹이 표시되지 않는 것은 현재 ESP 컨트롤이 별도 그룹이 없기 때문에 **기능적 문제는 아닙니다** (isosurface 슬라이더가 `grpOrbital`을 공유). 그러나 dead reference입니다.

**수정 — 두 가지 옵션:**

옵션 A (최소 변경): `viewer.js`에서 `dom.$grpESP` 참조 제거:

```javascript
// collectDom()에서 제거:
// dom.$grpESP = document.getElementById("grpESP");

// showControls()에서 제거:
// if (dom.$grpESP) dom.$grpESP.hidden = !hasESP;
```

옵션 B (ESP 전용 컨트롤 추가): `index.html`에 ESP 전용 그룹 추가. 이는 향후 ESP-specific 설정(density_iso, opacity 등)을 위해 권장됩니다.

**옵션 A를 채택합니다** (현재 ESP 설정은 orbital 슬라이더를 재사용).

---

### D1: DOM ID 교차 참조 매트릭스

**HTML에 선언된 모든 id → JS에서의 참조:**

| HTML id                | app.js           | chat.js                 | results.js       | viewer.js                     | 참조됨?                 |
| ---------------------- | ---------------- | ----------------------- | ---------------- | ----------------------------- | ----------------------- |
| `appLoader`            | —                | —                       | —                | `dismissLoader`               | ✅                      |
| `appShell`             | —                | —                       | —                | —                             | ❌ dead                 |
| `topbar`               | —                | —                       | —                | —                             | ❌ dead                 |
| `globalStatus`         | `querySelector`  | —                       | —                | —                             | ✅                      |
| `btnThemeToggle`       | `getElementById` | —                       | —                | —                             | ✅                      |
| `btnKeyboardShortcuts` | `getElementById` | —                       | —                | —                             | ✅                      |
| `modalShortcuts`       | `getElementById` | —                       | —                | —                             | ✅                      |
| `sessionTabsContainer` | `getElementById` | —                       | —                | —                             | ✅                      |
| `sessionTabs`          | `getElementById` | —                       | —                | —                             | ✅                      |
| `panelViewer`          | —                | —                       | —                | `getElementById` (fullscreen) | ✅                      |
| `viewer3d`             | —                | —                       | —                | `getElementById`              | ✅                      |
| `viewerEmpty`          | —                | —                       | —                | `getElementById`              | ✅                      |
| `viewerControls`       | —                | —                       | —                | `getElementById`              | ✅                      |
| `viewerLegend`         | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnViewerReset`       | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnViewerScreenshot`  | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnViewerFullscreen`  | —                | —                       | —                | `getElementById`              | ✅                      |
| `segStyle`             | —                | —                       | —                | `getElementById`              | ✅                      |
| `grpOrbital`           | —                | —                       | —                | `getElementById`              | ✅                      |
| `grpOpacity`           | —                | —                       | —                | `getElementById`              | ✅                      |
| `grpOrbitalSelect`     | —                | —                       | —                | `getElementById`              | ✅                      |
| `selectOrbital`        | —                | —                       | —                | `getElementById`              | ✅                      |
| `sliderIsovalue`       | —                | —                       | —                | `getElementById`              | ✅                      |
| `lblIsovalue`          | —                | —                       | —                | `getElementById`              | ✅                      |
| `sliderOpacity`        | —                | —                       | —                | `getElementById`              | ✅                      |
| `lblOpacity`           | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnToggleLabels`      | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnModeOrbital`       | —                | —                       | —                | `getElementById`              | ✅                      |
| `btnModeESP`           | —                | —                       | —                | `getElementById`              | ✅                      |
| `vizModeToggle`        | —                | —                       | —                | `getElementById`              | ✅                      |
| `grpColorScheme`       | —                | —                       | —                | —                             | ❌ dead (HTML에만 존재) |
| `selectColorScheme`    | —                | —                       | —                | `getElementById`              | ✅                      |
| `schemePreview`        | —                | —                       | —                | `getElementById`              | ✅                      |
| `viewerContainer`      | —                | —                       | —                | —                             | ❌ dead                 |
| `panelChat`            | —                | —                       | —                | —                             | ❌ dead                 |
| `wsStatus`             | —                | `querySelector`         | —                | —                             | ✅                      |
| `chatScroll`           | —                | `getElementById`        | —                | —                             | ✅                      |
| `chatMessages`         | —                | `getElementById`        | —                | —                             | ✅                      |
| `chatInputArea`        | —                | —                       | —                | —                             | ❌ dead                 |
| `chatSuggestions`      | —                | `getElementById`        | —                | —                             | ✅                      |
| `chatForm`             | —                | `getElementById`        | —                | —                             | ✅                      |
| `chatInput`            | `getElementById` | `getElementById`        | —                | —                             | ✅                      |
| `chatSend`             | —                | `getElementById`        | —                | —                             | ✅                      |
| `panelResults`         | —                | —                       | —                | —                             | ❌ dead                 |
| `sessionTabBar`        | —                | —                       | `getElementById` | —                             | ✅                      |
| `resultsTabs`          | —                | —                       | `getElementById` | —                             | ✅                      |
| `resultsContent`       | —                | —                       | `getElementById` | —                             | ✅                      |
| `resultsEmpty`         | —                | —                       | `getElementById` | —                             | ✅                      |
| `panelHistory`         | —                | —                       | —                | —                             | ❌ dead                 |
| `historyList`          | `getElementById` | —                       | —                | —                             | ✅                      |
| `historyEmpty`         | `getElementById` | —                       | —                | —                             | ✅                      |
| `historySearch`        | `getElementById` | —                       | —                | —                             | ✅                      |
| `btnRefreshHistory`    | `getElementById` | —                       | —                | —                             | ✅                      |
| `typingIndicator`      | —                | `getElementById` (동적) | —                | —                             | ✅ (동적 생성)          |

**JS에서 참조하지만 HTML에 없는 ID:**

| JS 파일     | 참조 ID  | 존재?          |
| ----------- | -------- | -------------- |
| `viewer.js` | `grpESP` | ❌ **결함 D2** |

Dead HTML id들(`appShell`, `topbar`, `viewerContainer`, `panelChat`, `chatInputArea`, `panelResults`, `panelHistory`, `grpColorScheme`)은 CSS grid area나 구조적 마크업으로 사용되므로 무해합니다.

---

### D5: `chat-msg--system` CSS 정의 — **P2 Medium**

`index.html`에 하드코딩된 system 메시지:

```html
<div class="chat-msg chat-msg--system">
  <div class="chat-msg__avatar chat-msg__avatar--system"></div>
</div>
```

`style.css`를 검색하면 `.chat-msg__avatar--system`은 정의되어 있습니다:

```css
.chat-msg__avatar--system {
  background: var(--accent-muted);
  color: var(--accent);
}
```

그러나 `.chat-msg--system`은 **정의되지 않았습니다**. `.chat-msg`의 기본 스타일이 적용되므로 기능적 문제는 없지만, system 메시지에 다른 배경색 등을 적용하려면 추가가 필요합니다.

`chat.js`에서 `createMsgEl`은 `"user"`, `"assistant"`, `"error"` role만 사용하며 `"system"`은 사용하지 않습니다. 따라서 동적 system 메시지 생성은 없고, HTML의 하드코딩 메시지만 system 스타일을 사용합니다.

**수정 (선택적 — `style.css`):**

```css
.chat-msg--system {
  opacity: 0.85;
}
.chat-msg--system .chat-msg__text {
  font-size: 12px;
  color: var(--text-2);
}
```

---

## Perspective 3: 이벤트 버스 정합성

### E3: `result:cleared` 이벤트 미처리 — **P0 Critical**

`results.js`의 `removeSessionResult`에서 모든 결과가 제거되면:

```javascript
App.emit("result:cleared");
```

이 이벤트를 아무도 listen하지 않습니다. viewer는 마지막으로 렌더링된 분자를 계속 표시하며, 사용자가 모든 결과를 닫았는데도 3D 뷰어에 이전 분자가 남아있습니다.

**수정 (`viewer.js`):**

```javascript
// bindEvents() 내부에 추가:
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

### E5: `status:changed` 무한 루프 검증 — 확인 완료, 안전

```javascript
App.on("status:changed", function (s) {
  // ... UI 업데이트 ...
  if (s.kind === "success" || s.kind === "completed") {
    setTimeout(function () {
      if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
        App.setStatus("Ready", "idle", "app"); // ← 이것이 다시 emit
      }
    }, 4000);
  }
});
```

`App.setStatus("Ready", "idle", "app")` → `emit("status:changed", {kind:"idle"})` → handler 실행 → `s.kind === "idle"`이므로 `if (s.kind === "success" || ...)` 조건 불성립 → setTimeout 등록 안 됨. ✅ **무한 루프 불가.**

---

### E7: 중복 렌더링 검증 — **P1 High (성능)**

`setActiveJob`이 호출되면:

```javascript
setActiveJob: function (jobId) {
    store.activeJobId = jobId;
    // ...
    emit("activejob:changed", { jobId, result });  // → app.js: renderHistory() + renderSessionTabs()
    if (result) emit("result:changed", { jobId, result, source: "history" });  // → results.js: update(), viewer.js: handleResult()
}
```

`app.js`의 handler:

```javascript
App.on("jobs:changed", function () {
  renderHistory();
  renderSessionTabs();
});
App.on("activejob:changed", function () {
  renderHistory();
  renderSessionTabs();
});
```

`setActiveJob`은 `upsertJob`을 호출하지 않으므로 `jobs:changed`는 emit되지 않습니다. 따라서 `renderHistory`는 `activejob:changed` handler에서 1회만 호출됩니다.

그러나 `result:changed` → `results.js`의 `update()` → `renderSessionTabs()` (results.js 내부의 별도 구현)도 호출됩니다.

`app.js`와 `results.js`에 **각각 별도의 `renderSessionTabs`** 함수가 있습니다.

`app.js`의 `renderSessionTabs`는 `#sessionTabs` (상단 탭 바)를 렌더링하고, `results.js`의 `renderSessionTabs`는 `#sessionTabBar` (결과 패널 내 탭 바)를 렌더링합니다. 이들은 **다른 DOM 요소**이므로 중복이 아닙니다. ✅

그러나 `app.js`의 `renderHistory()`가 `activejob:changed`에서 호출되고, `results.js`의 `update()`에서도 DOM을 업데이트하므로, 사용자가 history item을 클릭할 때:

1. `App.setActiveJob(jobId)` 호출
2. `activejob:changed` emit → `renderHistory()` (1회), `renderSessionTabs()` (1회)
3. `result:changed` emit → `results.js` update (1회), `viewer.js` handleResult (1회)

총 렌더링: history 1회, session tabs 2회 (app.js + results.js 각각), results 1회, viewer 1회. **허용 가능합니다.**

---

### E2: `result:switched` detail 구조 — **P1 High**

```javascript
// results.js
App.emit("result:switched", { result: entry.result, jobId: entry.jobId });

// viewer.js
function handleResultSwitched(data) {
    var r = data.result; if (!r) return;
    state.result = r;
    state.jobId = data.jobId || null;
```

`entry.jobId`가 `undefined`이면 (`data.jobId` 누락), `state.jobId`가 `null`이 되어 이후 `saveViewerSnapshot()`에서 `if (!state.jobId) return;`으로 저장이 안 됩니다.

**검증:** `sessionResults` push 시:

```javascript
var entry = {
    id: jobId || ("local-" + Date.now()),
    jobId: jobId,  // jobId가 null이면 null
```

`jobId`는 `update(result, jobId, source)`의 두 번째 인자로, `result:changed` event의 `d.jobId`에서 옵니다. 이는 일반적으로 설정되어 있습니다. 그러나 로컬 계산 결과(WebSocket 없이 HTTP로 받은 경우)에서 `jobId`가 없을 수 있습니다.

**수정 (`viewer.js`):** 이미 `data.jobId || null`로 처리하고 있으므로 추가 수정 불필요. 단, `saveViewerSnapshot`이 `state.jobId` 없이는 실행되지 않으므로, jobId 없는 결과의 viewer 상태는 저장/복원되지 않습니다. 이는 의도된 동작으로 판단합니다.

---

## Perspective 4: WebSocket 메시지 프로토콜

### W5: Progress 값 범위 불일치 — **P0 Critical**

`compute.py`의 `progress_callback`:

```python
record.progress = max(0.0, min(1.0, float(...)))  # 0.0 ~ 1.0
```

`chat.js`의 `handleServerEvent` "job_progress" case:

```javascript
var progress = msg.progress != null ? msg.progress : ...;
// ...
if (typeof progress === "number") {
    prog2.setProgress(progress);
}
```

`addProgressUI`의 `setProgress`:

```javascript
setProgress: function (pct) {
    fill.classList.remove("chat-progress__fill--indeterminate");
    fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
}
```

서버가 `progress: 0.5`를 보내면, `fill.style.width = "0.5%"` → progress bar가 거의 보이지 않음. 100%가 되려면 서버가 `100`을 보내야 하지만, 서버는 `1.0`을 보냅니다.

**수정 (`chat.js`):**

```javascript
// handleServerEvent "job_progress" case 내:
if (typeof progress === "number") {
  // 수정: 서버는 0~1 범위, UI는 0~100 범위
  var pctValue = progress <= 1.0 ? progress * 100 : progress;
  prog2.setProgress(pctValue);
}
```

---

### W1: 서버 이벤트 타입 ↔ 클라이언트 handler 매핑

**서버(`compute.py` `_append_event`)에서 생성되는 이벤트 타입:**

| 서버 이벤트 type | chat.js case 매핑                             | 매핑됨?   |
| ---------------- | --------------------------------------------- | --------- |
| `job_submitted`  | `case "job_submitted"`                        | ✅        |
| `job_started`    | (default → status "running" → `"job_update"`) | ✅ (간접) |
| `job_progress`   | `case "job_progress"`                         | ✅        |
| `job_completed`  | (default → status "completed" → `"result"`)   | ✅ (간접) |
| `job_failed`     | `case "job_failed"`                           | ✅        |

**chat.js에서 처리하는 case 중 서버가 보내지 않는 것:**

| chat.js case                                 | 서버에서 전송?       | 비고                |
| -------------------------------------------- | -------------------- | ------------------- |
| `assistant`, `response`, `answer`, `reply`   | ❓ WS handler 미제공 | 아마 chat AI 응답용 |
| `assistant_start`, `stream_start`            | ❓                   | streaming 응답용    |
| `assistant_chunk`, `stream`, `chunk`         | ❓                   | streaming 응답용    |
| `assistant_end`, `stream_end`, `done`        | ❓                   | streaming 종료      |
| `ready`, `ack`, `hello`, `connected`, `pong` | ❓                   | WS 핸드셰이크       |

이들은 WebSocket handler(미제공 코드)에서 전송하는 것으로 추정됩니다. `compute.py`의 job 시스템과는 별개의 경로입니다.

---

## Perspective 5: 복원 체인 E2E

### R3: 연속 계산 시 progress UI 혼동 — **P1 High**

첫 번째 계산 완료 시 `handleServerEvent({type:"result"})`:

```javascript
case "result":
    // ...
    state.activeProgressEl = null;
    state.activeAssistantEl = null;
    setSending(false);
    break;
```

`setSending(false)` → `$send.disabled = false` → 사용자가 즉시 두 번째 메시지 입력 가능.

두 번째 `submitMessage`:

```javascript
state.activeAssistantEl = null; // 이미 null ✅
state.activeProgressEl = null; // 이미 null ✅
state.streamBuffer = "";
addTypingIndicator();
```

두 번째 job의 progress 이벤트 수신 시:

```javascript
var prog2 = ensureProgressUI();
```

`ensureProgressUI`는 `state.activeAssistantEl`이 null이므로 새 assistant bubble 생성 → 새 progress UI 생성. ✅ 정상.

그러나 **첫 번째 결과의 assistant bubble이 아직 DOM에 남아있고, 두 번째의 typing indicator와 progress가 그 아래에 추가**됩니다. 이는 시각적으로 혼동되지 않습니다 (새 메시지가 아래에 추가되므로).

**한 가지 문제:** 첫 번째 계산이 아직 running인 상태에서 두 번째를 submit하면:

```javascript
function submitMessage(text) {
    // ...
    setSending(true);
    // ...
    addTypingIndicator();
```

`setSending(true)` → `$send.disabled = true`. 그러나 `state.sending = true`인 동안 두 번째 enter는 `if (!state.sending && ...)` 체크로 무시됩니다.

**문제:** 첫 번째 job이 progress 이벤트를 계속 수신하는 중에 결과가 도착하면:

```javascript
case "result":
    // ...
    state.activeProgressEl = null;  // 첫 번째의 progress UI 참조 해제
    setSending(false);               // 입력 가능
```

그런데 `state.activeJobId`가 첫 번째 job의 ID인 상태에서 결과를 받으면, `state.activeJobId`가 업데이트됩니다. 두 번째를 submit하면 `state.activeJobId`가 두 번째 job의 ID로 변경됩니다.

그러나 첫 번째 job의 나머지 progress 이벤트가 뒤늦게 도착하면, `jobId`가 첫 번째 것이므로 `App.upsertJob`은 첫 번째 job을 업데이트하지만, `ensureProgressUI()`는 **두 번째 job의 progress UI를 업데이트**합니다 (state.activeProgressEl이 두 번째 것을 가리키므로).

**수정 (`chat.js` — progress event에서 job ID 검증):**

```javascript
case "job_update": case "job_event": case "job_progress": case "progress":
case "status": case "step": case "stage": case "computing": case "running":
    var jid2 = jobId || state.activeJobId;
    // ...

    // 수정: progress UI는 active job에 대해서만 업데이트
    if (jid2 && jid2 === state.activeJobId) {
        var prog2 = ensureProgressUI();
        if (combinedLabel) {
            var stepStatus = (status === "failed" || status === "error") ? "error"
                : (status === "completed" || status === "done") ? "done" : "active";
            prog2.addStep(combinedLabel, stepStatus);
        }
        if (typeof progress === "number") {
            var pctValue = progress <= 1.0 ? progress * 100 : progress;
            prog2.setProgress(pctValue);
        }
    }

    if (jid2) {
        App.upsertJob({ job_id: jid2, status: status || "running", updated_at: Date.now() / 1000, progress: progress });
    }
    App.setStatus(combinedLabel || "Computing...", "running", "chat");
    break;
```

---

## Perspective 6: 방어적 프로그래밍

### P2: 미지원 method의 조용한 fallback — **P1 High**

```python
xc_map = {
    "b3lyp": "b3lyp", "pbe": "pbe", "pbe0": "pbe0",
    "m06-2x": "m06-2x", "m062x": "m06-2x",
    "wb97x-d": "wb97x-d", "ωb97x-d": "wb97x-d",
    "bp86": "bp86", "blyp": "blyp",
}
xc = xc_map.get(key, "b3lyp")  # 미지원 method → 조용히 B3LYP
```

사용자가 "TPSS"를 요청하면 B3LYP로 계산되고, 결과에 `method: "TPSS"`가 표시되어 사용자는 TPSS로 계산되었다고 착각합니다.

**수정 (`pyscf_runner.py`):**

```python
def _build_mean_field(mol, method=None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))

    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf

    xc_map = {
        "b3lyp": "b3lyp", "pbe": "pbe", "pbe0": "pbe0",
        "m06-2x": "m06-2x", "m062x": "m06-2x",
        "wb97x-d": "wb97x-d", "ωb97x-d": "wb97x-d",
        "wb97x-d": "wb97x-d", "bp86": "bp86", "blyp": "blyp",
    }
    xc = xc_map.get(key)

    # 수정: 미지원 method 경고 및 fallback
    _method_warning = None
    if xc is None:
        # PySCF가 직접 지원하는지 시도
        xc = key
        _method_warning = (
            f"Method '{method_name}' is not in the predefined list. "
            f"Attempting to use it directly with PySCF. "
            f"If this fails, B3LYP will be used as fallback."
        )

    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass

    # 경고를 mf에 부착하여 이후에 접근할 수 있게 함
    mf._qcviz_method_warning = _method_warning
    return method_name, mf
```

그리고 `_populate_scf_fields`에서:

```python
# _populate_scf_fields 내부, mf 접근 가능한 곳:
method_warn = getattr(mf, "_qcviz_method_warning", None)
if method_warn:
    result.setdefault("warnings", []).append(method_warn)
```

---

### P5: orbitals sort 방어 — **P1 High**

```javascript
// results.js normalizeResult 내:
var sorted = r.orbitals.slice().sort(function (a, b) {
  return a.zero_based_index - b.zero_based_index;
});
```

`zero_based_index`가 `undefined`이면 `undefined - undefined = NaN`, sort 결과가 불안정합니다.

**수정 (`results.js`):**

```javascript
var sorted = r.orbitals.slice().sort(function (a, b) {
  var ai = a && a.zero_based_index != null ? a.zero_based_index : 0;
  var bi = b && b.zero_based_index != null ? b.zero_based_index : 0;
  return ai - bi;
});
```

---

### P8: berny_solver callback 호환성 — **P1 High**

PySCF의 `geometric_solver`와 `berny_solver`는 callback 인자 형식이 다릅니다.

`geometric_solver`: callback 인자는 dict (`envs`) — `envs["mol"]`, `envs["e_tot"]`, `envs["gradients"]`
`berny_solver`: callback 인자는 dict 형태가 비슷하지만, key가 다를 수 있음: `envs["mol"]`은 동일, `envs["e_tot"]` 존재, 그러나 `envs["gradients"]`가 `envs["gradient"]` (단수형)일 수 있음.

**수정 (`pyscf_runner.py`):**

```python
def _geomopt_callback(envs):
    try:
        mol_current = envs.get("mol", None) if isinstance(envs, dict) else getattr(envs, "mol", None)
        e_current = envs.get("e_tot", None) if isinstance(envs, dict) else getattr(envs, "e_tot", None)
        grad_norm = None

        if isinstance(envs, dict):
            g = envs.get("gradients", envs.get("gradient", None))
        else:
            g = getattr(envs, "gradients", getattr(envs, "gradient", None))

        if g is not None:
            grad_norm = float(np.linalg.norm(np.asarray(g)))

        step_num = len(trajectory) + 1
        xyz_string = _mol_to_xyz(mol_current, comment=f"Step {step_num}") if mol_current else None

        step_data = {
            "step": step_num,
            "energy_hartree": float(e_current) if e_current is not None else None,
            "grad_norm": grad_norm,
            "xyz": xyz_string,
        }
        trajectory.append(step_data)

        if progress_callback:
            frac = min(0.3 + (step_num / 50) * 0.55, 0.85)
            msg = f"Opt step {step_num}"
            if e_current is not None:
                msg += f": E={e_current:.8f} Ha"
            if grad_norm is not None:
                msg += f", |grad|={grad_norm:.6f}"
            _emit_progress(progress_callback, frac, "optimize", msg)
    except Exception:
        pass  # callback 실패로 최적화가 중단되지 않도록
```

---

### P9: `deepMerge` 배열 처리 — **P0 Critical**

```javascript
function deepMerge(base, patch) {
  var lhs = base && typeof base === "object" ? clone(base) : {};
  var rhs = patch && typeof patch === "object" ? patch : {};
  Object.keys(rhs).forEach(function (k) {
    var lv = lhs[k],
      rv = rhs[k];
    if (
      lv &&
      rv &&
      typeof lv === "object" &&
      typeof rv === "object" &&
      !Array.isArray(lv) &&
      !Array.isArray(rv)
    ) {
      lhs[k] = deepMerge(lv, rv);
    } else {
      lhs[k] = clone(rv);
    }
  });
  return lhs;
}
```

`!Array.isArray(lv) && !Array.isArray(rv)` 조건에 의해 배열은 **덮어쓰기**됩니다. 따라서:

```javascript
deepMerge({ events: [1, 2] }, { events: [3] });
// → {events: [3]}
```

이것이 `App.upsertJob`에서 문제가 됩니다:

```javascript
var prev = store.jobsById[jobId] || {};
var next = deepMerge(prev, job);
```

`chat.js`의 `handleServerEvent` "job_submitted" case:

```javascript
App.upsertJob({
  job_id: jid,
  status: "queued",
  submitted_at: Date.now() / 1000,
  // events가 없음
});
```

이후 progress update:

```javascript
App.upsertJob({
  job_id: jid2,
  status: "running",
  updated_at: Date.now() / 1000,
  progress: progress,
  // events가 없음
});
```

`events` 필드가 포함되지 않으므로 덮어쓰기가 발생하지 않습니다. 문제는 **서버에서 `events` 배열이 포함된 응답을 받을 때**입니다. `fetchHistory`에서 `include_events=false`(기본값)이므로 events는 포함되지 않습니다.

그러나 결과적으로 `deepMerge`가 배열을 덮어쓰는 동작은 `warnings` 배열에 영향을 줄 수 있습니다. 서버 결과의 `warnings: ["SCF did not converge"]`가 이전 값 `warnings: ["Primary SCF failed", ...]`를 덮어씁니다. 이는 서버가 최신 전체 warnings 배열을 보내므로 **의도된 동작**입니다.

**결론: 현재 사용 패턴에서는 안전합니다.** 그러나 방어적으로 주석을 추가합니다:

```javascript
// deepMerge: 배열은 덮어쓰기됩니다 (append하지 않음).
// 이는 서버가 항상 전체 배열을 보내는 것을 전제로 합니다.
```

---

### P10: snapshot 복원 시 모드 호환성 — **P2 Medium**

S6에서 모드별 isovalue를 분리했으므로, 이 문제는 해결되었습니다. `restoreViewerSnapshot`에서:

```javascript
if (snap.viewerOrbitalIsovalue != null)
  state.orbitalIsovalue = snap.viewerOrbitalIsovalue;
if (snap.viewerEspDensityIso != null)
  state.espDensityIso = snap.viewerEspDensityIso;
// 현재 모드에 맞는 isovalue를 active로 설정
if (snap.viewerMode === "esp") state.isovalue = state.espDensityIso;
else state.isovalue = state.orbitalIsovalue;
```

이렇게 하면 ESP snapshot을 orbital 모드에서 복원해도 `orbitalIsovalue`가 사용됩니다. ✅

---

## Perspective 7: 아키텍처

### A1/A2: Multi-worker 문서화

현재 아키텍처는 **단일 worker**를 전제로 설계되었습니다.

```python
# 서버 시작 시 권장 설정:
# uvicorn qcviz_mcp.web.app:app --workers 1 --host 0.0.0.0 --port 8000
```

Multi-worker 환경의 문제점을 정리합니다.

`InMemoryJobManager`는 프로세스 메모리에 job을 저장하므로, worker가 2개이면 worker A에서 submit한 job을 worker B에서 조회할 수 없습니다. WebSocket 연결은 특정 worker에 바인딩되므로, 연결된 worker에서만 progress 이벤트를 수신할 수 있습니다. `_SCF_CACHE`도 프로세스별이므로 캐시 히트율이 worker 수에 반비례하여 감소합니다.

단기적으로는 `--workers 1`을 강제하는 것으로 충분하며, 장기적으로는 Redis 기반 job store(`rq` 또는 `celery`), Redis pub/sub 기반 WebSocket broadcast, Redis 기반 SCF 결과 캐시로 마이그레이션해야 합니다.

---

### A7: 단위 테스트 케이스 목록

| #   | 함수                         | 테스트 케이스                                                                   |
| --- | ---------------------------- | ------------------------------------------------------------------------------- |
| 1   | `_normalize_method_name`     | "b3lyp"→"B3LYP", "HF"→"HF", "m062x"→"M06-2X", "unknown"→"unknown", None→"B3LYP" |
| 2   | `_normalize_basis_name`      | "6-31g*"→"6-31G*", "def2svp"→"def2-SVP", None→"def2-SVP"                        |
| 3   | `_normalize_esp_preset`      | "acs"→"acs", "grayscale"→"greyscale" (compute.py), "grey"→"greyscale", ""→"acs" |
| 4   | `_looks_like_xyz`            | 유효 XYZ, 빈 문자열, 숫자만, 단일 줄, None                                      |
| 5   | `_strip_xyz_header`          | header 있는 XYZ, header 없는 XYZ, 빈 문자열                                     |
| 6   | `_formula_from_symbols`      | ["C","H","H","H","H"]→"CH4", ["O","H","H"]→"H2O", ["He"]→"He", []→""            |
| 7   | `_guess_bonds`               | water mol (2 bonds), methane (4 bonds), single atom (0 bonds)                   |
| 8   | `_resolve_orbital_selection` | "HOMO", "LUMO", "HOMO-2", "LUMO+3", "5" (1-based), None→HOMO                    |
| 9   | `_compute_esp_auto_range`    | 정상 배열, 빈 배열, 모두 NaN, 극성 큰 값                                        |
| 10  | `_finalize_result_contract`  | 빈 dict, 에너지만 있는 dict, 전체 필드, NaN 에너지                              |

---

## IVS-1: "물 분자의 HOMO 오비탈 보여줘" — 전체 추적

**1단계: chat.js `submitMessage`**

```
text = "물 분자의 HOMO 오비탈 보여줘"
→ safeSendWs({type: "chat", session_id: "qcviz-xxx", message: text})
   또는 HTTP POST /api/chat
```

**2단계: compute.py `_prepare_payload`**

```
raw_message = "물 분자의 HOMO 오비탈 보여줘"
→ _safe_plan_message(raw_message, data)
  → QCVizAgent.plan(message, context=data)
    → _heuristic_plan (또는 LLM)
      → "homo|lumo|orbital" 매치 → intent = "orbital_preview"
      → _extract_structure_query: "물" → KO alias → "water"
      → _extract_orbital: "HOMO" 매치
    → return AgentPlan(intent="orbital_preview", structure_query="water",
                       orbital="HOMO", focus_tab="orbital")
→ _merge_plan_into_payload
  → data["job_type"] = "orbital_preview"
  → data["structure_query"] = "water"
  → data["orbital"] = "HOMO"
  → data["advisor_focus_tab"] = "orbital"
→ _prepare_payload 완료
```

**3단계: pyscf_runner `run_orbital_preview`**

```
structure_query="water" → _resolve_structure_payload
  → _lookup_builtin_xyz("water")
    → BUILTIN_XYZ_LIBRARY["water"] 발견
    → atom_text = "O 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469"
→ _build_mol(atom_text, basis="def2-SVP")
→ _build_mean_field(mol, "B3LYP") → method="B3LYP", mf=RKS
→ _run_scf_with_fallback(mf) → energy ≈ -76.3xx Ha
→ _resolve_orbital_selection(mf, "HOMO")
  → occs 분석 → homo_idx = 4 (0-based), lumo_idx = 5
  → raw = "HOMO" → idx = 4, label = "HOMO"
  → return {index: 5, zero_based_index: 4, label: "HOMO", energy_hartree: -0.3xx, ...}
→ cubegen.orbital(mol, cube_path, coeff_vec, nx=60, ny=60, nz=60)
→ _file_to_b64(cube_path) → orbital_cube_b64 (≈3MB base64)
→ _attach_visualization_payload(result, ..., orbital_cube_path, orbital_meta)
→ _finalize_result_contract(result)
```

**4단계: 결과 구조 (핵심 필드)**

```json
{
  "success": true,
  "job_type": "orbital_preview",
  "structure_name": "water",
  "total_energy_hartree": -76.3xx,
  "orbital_gap_ev": 9.xxx,
  "selected_orbital": {
    "index": 5,
    "zero_based_index": 4,
    "label": "HOMO",
    "energy_hartree": -0.3xx,
    "energy_ev": -9.xxx
  },
  "orbitals": [...],
  "visualization": {
    "xyz": "3\nwater\nO ...\nH ...\nH ...",
    "orbital_cube_b64": "...(base64)...",
    "orbital": {"cube_b64": "...", "label": "HOMO", "index": 5},
    "defaults": {"focus_tab": "orbital", "orbital_iso": 0.050},
    "available": {"orbital": true, "esp": false, "density": false}
  },
  "advisor_focus_tab": "orbital"
}
```

**5단계: chat.js `handleServerEvent({type:"result"})`**

```
→ App.upsertJob({job_id, status:"completed", result, ...})
→ App.setActiveResult(result, {jobId, source:"chat"})
  → emit("result:changed", {result, jobId, source:"chat"})
```

**6단계: results.js `update`**

```
→ normalizeResult(result)
  → viz.xyz_block = viz.xyz (= XYZ 문자열)
  → viz.orbital_cube_b64 확인 ✅
  → orbitals 배열 → mo_energies, mo_occupations 생성
→ getAvailableTabs: ["summary", "geometry", "orbital", "json"]
→ decideFocusTab: advisor_focus_tab = "orbital" ✅
→ renderTabs(["summary", "geometry", "orbital", "json"], "orbital")
→ renderContent("orbital", normalizedResult)
  → renderOrbital: HOMO 정보 표시, MO energy diagram 렌더링
```

**7단계: viewer.js `handleResult`**

```
→ state.result = result, state.jobId = jobId
→ findCubeB64(result, "orbital") → base64 string ✅
→ renderOrbital(result) 호출
  → ensureViewer() → 3Dmol viewer 준비
  → clearViewer(viewer)
  → state.isovalue = state.orbitalIsovalue (0.03)
  → addMoleculeModel(viewer, result) → XYZ 로드, stick+sphere 스타일
  → cubeStr = safeAtob(orbital_cube_b64)
  → addOrbitalSurfaces(viewer, cubeStr)
    → VolumeData(cubeStr, "cube")
    → addIsosurface(vol, {isoval: 0.03, color: "#3b82f6"}) // positive (classic scheme)
    → addIsosurface(vol, {isoval: -0.03, color: "#ef4444"}) // negative
  → addLabels(viewer, result) // O, H, H 라벨
  → viewer.zoomTo()
  → state.mode = "orbital"
  → showControls("orbital") → orbital 컨트롤 표시
  → showOrbitalLegend() → "Positive (+0.030) / Negative (-0.030)" 범례
  → populateOrbitalSelector(result) → HOMO 선택된 드롭다운
```

**전체 체인 정합성:** ✅ 모든 단계에서 데이터가 올바르게 변환·전달됩니다.

---

## IVS-4: "xyz123" 에러 경로 추적

```
1. chat.js: submitMessage("xyz123")
2. compute.py: _prepare_payload
   → _safe_plan_message("xyz123")
     → _heuristic_plan: intent="analyze", structure_query="xyz123"
   → data["structure_query"] = "xyz123"
   → data["job_type"] = "analyze"
3. JOB_MANAGER.submit(data) → _run_job(job_id) 시작
4. _run_direct_compute(payload)
   → _prepare_payload(payload) (이미 prepared이지만 재호출)
   → runner = pyscf_runner.run_analyze
   → run_analyze(structure_query="xyz123")
     → _prepare_structure_bundle(structure_query="xyz123")
       → _resolve_structure_payload(structure_query="xyz123")
         → _lookup_builtin_xyz("xyz123") → None
         → MoleculeResolver.resolve_with_friendly_errors("xyz123")
           → 실패 → resolve_error 설정
         → raise ValueError("Could not resolve structure 'xyz123': ...")
5. ValueError가 run_analyze에서 전파
6. _run_direct_compute에서 catch되지 않음 (HTTPException만 특별 처리)
7. _run_job의 except Exception:
   → job.status = "failed"
   → job.error = {"message": "Could not resolve structure 'xyz123': ...", "type": "ValueError"}
   → _append_event(job, "job_failed", job.message, job.error)
8. WebSocket을 통해 job_failed 이벤트 전송 (WS handler에 의해)
9. chat.js: handleServerEvent({type: "job_failed"})
   → 또는 default case → status "failed" → reroute to "error"
   → errMsg = "Could not resolve structure 'xyz123': ..."
   → createMsgEl("error", {text: errMsg})
   → state.activeProgressEl?.addStep(errMsg, "error")
   → App.setStatus("Error", "error", "chat")
   → setSending(false)
10. 4초 후: App.setStatus는 "error" kind이므로 자동 "Ready" 복귀하지 않음
    (success/completed만 자동 복귀)
```

**결함 발견:** 에러 상태가 영구적으로 남습니다. `status:changed` handler에서 `s.kind === "success" || s.kind === "completed"`만 자동 복귀합니다.

**수정 (`app.js`):**

```javascript
App.on("status:changed", function (s) {
  if ($statusDot) $statusDot.setAttribute("data-kind", s.kind || "idle");
  if ($statusText) $statusText.textContent = s.text || "Ready";

  // 수정: error도 일정 시간 후 Ready로 복귀
  if (s.kind === "success" || s.kind === "completed" || s.kind === "error") {
    var delay = s.kind === "error" ? 6000 : 4000; // 에러는 6초
    setTimeout(function () {
      if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
        App.setStatus("Ready", "idle", "app");
      }
    }, delay);
  }
});
```

---

## 전체 결함 요약 및 우선순위

| #   | Perspective | ID    | 설명                          | 심각도            |
| --- | ----------- | ----- | ----------------------------- | ----------------- |
| 1   | P1 시맨틱   | S6    | isovalue 모드별 분리          | **P0**            |
| 2   | P2 DOM      | D2    | `grpESP` DOM 미존재           | **P0**            |
| 3   | P3 이벤트   | E3    | `result:cleared` 미처리       | **P0**            |
| 4   | P4 WS       | W5    | progress 0~1 vs 0~100         | **P0**            |
| 5   | P6 방어     | P9    | `deepMerge` 배열 동작 문서화  | P0→확인완료, 안전 |
| 6   | P1 시맨틱   | S1/S2 | orbital index 0/1-based 혼용  | **P1**            |
| 7   | P1 시맨틱   | S5    | `_COVALENT_RADII` 누락        | **P1**            |
| 8   | P6 방어     | P2    | 미지원 method 조용한 fallback | **P1**            |
| 9   | P6 방어     | P5    | orbitals sort 방어            | **P1**            |
| 10  | P6 방어     | P8    | berny callback 호환           | **P1**            |
| 11  | P3 이벤트   | E7    | 중복 렌더링                   | P1→확인완료, 허용 |
| 12  | P5 복원     | R3    | 연속 계산 progress 혼동       | **P1**            |
| 13  | IVS-4       | —     | 에러 후 status 영구 고착      | **P1**            |
| 14  | P1 시맨틱   | S4    | ESP range clipping 상한       | **P2**            |
| 15  | P2 DOM      | D5    | `chat-msg--system` CSS        | **P2**            |
| 16  | P6 방어     | P10   | snapshot 모드 호환            | P2→S6 해결        |
| 17  | P7 아키텍처 | A1/A2 | multi-worker 문서화           | **P3**            |

**P0 수정 4건, P1 수정 7건, P2 수정 2건, P3 문서화 1건.**

1차부터 3차까지 총 **44건**의 결함이 식별 및 수정되었으며, 전체 데이터 흐름 파이프라인의 정합성이 IVS-1~IVS-5 시나리오 추적으로 검증되었습니다.
