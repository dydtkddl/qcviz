# 🛠️ QCViz-MCP v5: Color Scheme 변경 시 렌더링 미반영 버그 수정 작업 지시서

현재 3D 뷰어 하단에서 사용자가 10가지 다양한 Color Scheme(예: Jmol, BWR, Inferno 등)을 셀렉트 박스에서 선택할 수 있으나, **바꾼 색상이 3D 뷰어 화면에 즉시 적용되지 않고 무시되는 치명적인 버그**가 있습니다.

아래 원인 분석과 수정 지침을 바탕으로 프론트엔드 코드(`viewer.js`)를 꼼꼼히 수정해 주세요.

---

## 🛑 문제 상황: Color Scheme 변경 무시

### 🔍 원인 분석 (`viewer.js` 내 캐시 재사용 로직의 허점)

`viewer.js`에 Color Scheme 변경 시 이벤트를 감지하는 로직은 제대로 들어있습니다:
```javascript
  var $selectColor = document.getElementById("selectColorScheme");
  if ($selectColor) {
    $selectColor.addEventListener("change", function() {
      // ... (생략)
      if (state.mode === "orbital" || state.mode === "esp") {
         var currentMode = state.mode;
         state.mode = "none"; // 강제 재진입 트리거용
         switchVizMode(currentMode); // 뷰어 표면 다시 그리기
      }
    });
  }
```

그러나 **가장 치명적인 문제**는 `switchVizMode` 안에서 동작하는 **조용한 캐시 렌더링 로직(`tryRenderCachedOrbital`)**에 있습니다.

```javascript
    if (newMode === "orbital") {
      // ❌ 치명적 원인: 이전에 캐시에 저장된 큐브 데이터가 있으면 이걸 그리는데,
      // 여기서 렌더링할 때는 `getCurrentColorScheme()`을 반영하지 않고
      // 무조건 옛날 하드코딩된 색상(#6366f1, #f43f5e)을 쓰고 있을 가능성이 100% 입니다!
      if (state.selectedOrbitalIndex != null && tryRenderCachedOrbital(state.selectedOrbitalIndex)) {
        // Handled completely by cache
      } else if (cubeB64) {
         // ...
```

`tryRenderCachedOrbital(idx)` 함수 안쪽을 살펴보면:
```javascript
  function tryRenderCachedOrbital(idx) {
    // ...
    if (orb && orb.cube_data) {
      // ...
      try {
        var cubeData = atob(orb.cube_data);
        var vol = new window.$3Dmol.VolumeData(cubeData, "cube");
        // ❌ 문제 지점: 여기서 하드코딩된 색상을 여전히 쓰고 있습니다!!
        state.viewer.addIsosurface(vol, { isoval: state.isovalue, color: "#6366f1", alpha: state.opacity, smoothness: 2 });
        state.viewer.addIsosurface(vol, { isoval: -state.isovalue, color: "#f43f5e", alpha: state.opacity, smoothness: 2 });
      } catch(e) {}
```
이 때문에 사용자가 아무리 Color Scheme을 바꿔서 `switchVizMode`를 다시 태워도, `tryRenderCachedOrbital`이 호출되면서 **무조건 기본 파란색/빨간색으로만 다시 그려버리는 것**입니다.

### ✅ 해결 요구사항 (Action Items)

1. **`tryRenderCachedOrbital` 함수 수정:**
   해당 함수 내의 `addIsosurface` 옵션에 있는 고정 색상(`#6366f1`, `#f43f5e`)을 모두 지우고, 반드시 `var scheme = getCurrentColorScheme();`를 호출한 뒤 `color: scheme.orbPositive`, `color: scheme.orbNegative`를 매핑하도록 교체하세요.

2. **`renderOrbital` 함수 수정 (초기 로딩 시):**
   `renderOrbital` 내부에서도 큐브 데이터를 처음 그릴 때 하드코딩된 색상을 사용하고 있는지 점검하고, 무조건 `getCurrentColorScheme()`을 사용하도록 수정하세요.

3. **`renderESP` 함수 수정:**
   ESP 맵을 처음 그릴 때(`renderESP`)에도 `volscheme: new window.$3Dmol.Gradient.RWB(-range, range)` 처럼 하드코딩된 부분이 없는지 점검하고, `getCurrentColorScheme().espGradient(-range, range)`로 완벽하게 교체하세요.

이 세 가지 함수(`tryRenderCachedOrbital`, `renderOrbital`, `renderESP`) 모두에서 **절대로 색상을 하드코딩하지 않게** 코드를 변경한 JavaScript 스니펫을 작성해 주세요!