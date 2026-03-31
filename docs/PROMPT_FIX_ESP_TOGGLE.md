# 🛠️ QCViz-MCP v5: ESP 맵 보기 토글 버튼 먹통 버그 해결 작업 지시서

현재 3D 뷰어의 툴바에 있는 "Orbital" / "ESP" 토글 버튼 중 **"ESP" 버튼을 클릭해도 아무런 반응이 없는(먹통인) 문제**가 발생하고 있습니다.
아래 원인 분석과 수정 지침을 바탕으로 프론트엔드 코드(`viewer.js`)를 수정해 주세요.

---

## 🛑 문제 상황: ESP 토글 버튼 무반응

### 🔍 원인 분석 (`viewer.js` 내 이벤트 바인딩 누락/오류)

`viewer.js` 하단에서 DOM 요소들에 이벤트 리스너를 붙여주는 부분을 살펴보면, 새롭게 추가된 `btnModeOrbital`과 `btnModeESP` 버튼에 대한 클릭 이벤트 바인딩이 누락되어 있거나, DOM 트리 초기화(DOMContentLoaded) 이전에 실행되어 `document.getElementById("btnModeESP")`가 `null`을 반환했을 가능성이 매우 큽니다.

또는 `switchVizMode("esp")` 함수 내부에 런타임 에러(try/catch에 먹힌 에러)가 숨어있어 조용히 실패하고 있을 수도 있습니다.

### ✅ 해결 요구사항 (Action Items)

1. **이벤트 바인딩 위치 점검:**
   `viewer.js` 내의 `btnModeOrbital`과 `btnModeESP` 이벤트 리스너 등록 코드가 화면의 모든 HTML(특히 `btnModeESP` 요소)이 로드된 시점(예: `init` 함수 내부)에 실행되도록 확실하게 위치를 이동시키세요.

2. **DOM 요소 동적 탐색:**
   전역 공간에 `var $btnModeESP = document.getElementById("btnModeESP");` 처럼 꺼내두지 말고, 클릭 이벤트가 필요할 때 또는 `init()` 블록 내부에서 요소 존재 여부를 확인하고 바인딩하게 수정하세요.

3. **switchVizMode 로직 점검 (ESP 렌더링):**
   `switchVizMode("esp")` 호출 시, `state.result` 객체 안에 있는 ESP 큐브 데이터(`esp_cube_b64`)를 찾아 렌더링하는 부분이 있습니다. 만약 데이터가 없어서 조용히 리턴(`return`)해버린다면 콘솔에 명시적인 `console.warn`을 남기도록 예외 처리를 강화하세요.

---

## 📄 참고 코드 (수정 포인트)

### `viewer.js` (문제의 이벤트 바인딩 부분)
```javascript
// ❌ 전역 스코프에 덩그러니 놓여 있으면, 스크립트 로드 시점에 버튼이 아직 렌더 안 됐을 수 있음.
  var $btnModeOrbital = document.getElementById("btnModeOrbital");
  var $btnModeESP = document.getElementById("btnModeESP");
  if ($btnModeOrbital) $btnModeOrbital.addEventListener("click", function() { switchVizMode("orbital"); });
  if ($btnModeESP) $btnModeESP.addEventListener("click", function() { switchVizMode("esp"); });
```

이 코드를 `init()` 함수 안쪽, 즉 모든 DOM이 준비된 시점(예: `collectDom()` 같은 초기화 함수)으로 옮겨야 버튼이 정상적으로 작동합니다.

이 지시서를 바탕으로 `viewer.js`의 이벤트 바인딩 구조를 개선하고 ESP 버튼 활성화 패치를 진행해 주세요!