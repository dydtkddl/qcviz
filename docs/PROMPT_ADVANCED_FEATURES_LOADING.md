# QCViz-MCP v5 고도화: 로딩 화면 및 색상 스킴 선택 UI 작업 지시서

현재 시스템의 사용성을 높이기 위해 다음 사항을 구현해야 합니다. 아래의 코드 컨텍스트와 요구사항을 바탕으로 프론트엔드(`viewer.js`, `index.html`, `style.css`)를 수정해 주세요.

---

## 🛑 요구사항 1: 초기 로딩 화면 (Loading Overlay) 추가
**문제:** 앱을 처음 열거나 새로고침하면, 초기화 및 라이브러리(3Dmol.js 등) 로딩에 몇 초가 걸리는데 화면이 정지된 것처럼 보여 사용자가 답답해합니다.
**해결:**
1. `index.html`의 최상단(또는 `.app-shell`을 덮는 위치)에 풀스크린 로딩 오버레이(`.app-loader`)를 추가하세요. 로딩 스피너와 "Initializing QCViz-MCP..." 등의 텍스트를 포함합니다.
2. `viewer.js`나 `app.js`에서 앱 초기화가 끝나면 (예: `init()` 마지막 또는 `ensureViewer()` 완료 시점) 이 로딩 오버레이를 페이드아웃(`opacity: 0` -> `display: none`) 처리하는 로직을 추가하세요.

---

## 🛑 요구사항 2: Orbital ↔ ESP 연속 토글 시 표면 중첩 버그
**문제:** Orbital 모드에서 ESP 모드로 바꾸고 다시 Orbital을 누르면(Orbital > ESP > Orbital > ESP), 이전 큐브 서페이스들이 지워지지 않고 누적되어 화면이 엉망이 됩니다.
**원인:** `switchVizMode` 내부에서 렌더링 전 `state.viewer.removeAllSurfaces()`를 호출하긴 하나, 캐시나 비동기 로딩 타이밍 때문에 이전 표면이 제대로 정리되지 않을 수 있습니다.
**해결:**
- `switchVizMode` 안에서 새로운 서페이스를 `addIsosurface`하기 직전에 **확실하게** `viewer.removeAllSurfaces()` (또는 `clearViewer` 중 모델은 남기고 표면만 지우는 로직)가 동작하도록 타이밍을 맞추거나 로직을 강화하세요.

---

## 🛑 요구사항 3: Orbital 및 ESP 다양한 Color Scheme (색상 테마) 선택 UI
**문제:** 현재 오비탈은 "파랑/빨강" 고정, ESP는 "RWB(빨강-흰-파랑)" 고정입니다. 사용자가 논문이나 발표 자료에 맞게 약 10가지의 다양한 컬러 스킴을 고를 수 있어야 합니다.
**해결:**
1. **프론트엔드 (`index.html`):** 뷰어 컨트롤 패널(`#viewerControls`) 내부에 Color Scheme을 고를 수 있는 `<select>` 박스를 추가하세요.
   - 예시 옵션: Jmol, RWB, BWR, Spectral, Viridis, Inferno, Greyscale 등
2. **프론트엔드 (`viewer.js`):** 
   - `renderOrbital`과 `renderESP` (그리고 `switchVizMode`의 렌더링 부분)에서 사용자가 선택한 Color Scheme을 반영하도록 수정하세요.
   - Orbital의 양/음 로브(lobe) 색상을 스킴에 따라 다르게 지정하거나(예: Jmol 스킴이면 특정 색상 세트), ESP의 `volscheme: { gradient: "RWB" }` 부분을 선택한 스킴 이름으로 동적으로 교체하세요.

---

## 📄 참고 코드 컨텍스트

### `viewer.js` (표면 중첩 버그 의심 부분 - `switchVizMode`)
```javascript
  function switchVizMode(newMode) {
    if (!state.result || state.mode === newMode) return;
    state.mode = newMode;
    // 이 부분이 항상 확실하게 동작해야 함
    if (state.viewer) state.viewer.removeAllSurfaces();

    if (newMode === "orbital") {
       // ...
       state.viewer.addIsosurface(vol, { isoval: state.isovalue, color: "#6366f1", alpha: state.opacity, smoothness: 2 });
       state.viewer.addIsosurface(vol, { isoval: -state.isovalue, color: "#f43f5e", alpha: state.opacity, smoothness: 2 });
    } else if (newMode === "esp") {
       // ...
       state.viewer.addIsosurface(densVol, { isoval: 0.001, color: "white", alpha: state.opacity, smoothness: 1, voldata: espVol, volscheme: new window.$3Dmol.Gradient.RWB(-range, range) });
    }
    state.viewer.render();
    // ...
  }
```

이 지시서를 바탕으로 1) 로딩 창, 2) 렌더링 겹침 버그 픽스, 3) 10가지 컬러 스킴 선택 기능을 모두 구현한 코드를 제시해 주세요!
