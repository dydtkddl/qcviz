# 🛠️ QCViz-MCP v5: 3D 뷰어 렌더링 에러 및 오비탈 재계산(채팅 연동) 버그 수정 작업 지시서

현재 프론트엔드 `viewer.js`에서 두 가지 문제가 발생하고 있습니다. 아래 맥락과 코드를 분석하여 두 문제를 모두 해결하는 업데이트된 코드를 작성해주세요.

---

## 🛑 문제 상황 1: 3Dmol.js 초기화 에러 (`transparent` 색상)

브라우저 콘솔에 다음과 같은 에러가 발생합니다.
```text
color not found transparent {aliceblue: 15792383, antiquewhite: 16444375, aqua: 65535, aquamarine: 8388564, azure: 15794175, …}
getHex @ 3Dmol-min.js:2
...
ensureViewer @ viewer.js:51
```

### 🔍 원인 파악 (`viewer.js`)
`ensureViewer` 함수에서 `3Dmol.createViewer`를 호출할 때 `backgroundColor`를 `"transparent"`로 설정하고 있는데, 3Dmol.js 라이브러리 내부 색상 파서가 이 문자열을 인식하지 못해 터지고 있습니다. (3Dmol.js 버전이나 구현에 따라 투명 배경은 `alpha: 0`을 쓰거나 올바른 Hex 색상, 예: `white` 등을 써야 할 수 있습니다.)

```javascript
  function ensureViewer() {
    if (state.viewer && state.ready) return Promise.resolve(state.viewer);
    return load3Dmol().then(function () {
      if (!state.viewer) {
        state.viewer = window.$3Dmol.createViewer($viewerDiv, {
          backgroundColor: "transparent", // ❌ 에러 발생 지점
          antialias: true,
        });
        state.ready = true;
        updateViewerBg();
// ...
```

---

## 🛑 문제 상황 2: 오비탈 셀렉트 박스 클릭 시 "다시 계산" 및 채팅창 도배

오비탈 드롭다운(`<select class="viewer-select" id="selectOrbital">`)에서 다른 오비탈을 선택하면, 뷰어가 즉시 업데이트되는 것이 아니라 **새로운 채팅 메시지가 발송되면서 다시 계산 사이클을 타는 현상**이 있습니다.
백엔드에 SCF 캐시가 적용되어 있어서 속도는 빠르지만, 사용자는 "왜 이걸 누를 때마다 채팅창이 도배되고 재계산 애니메이션이 도는 거지?" 하며 큰 불편을 느낍니다.

### 🔍 원인 파악 (`viewer.js`)
이벤트 리스너를 보면, 셀렉트 박스 변경 시 `App.chat.submit(...)`을 호출하여 강제로 채팅을 발생시키고 전체 파이프라인을 처음부터 돌리고 있습니다.

```javascript
  /* Orbital selector change */
  if ($selectOrbital) {
    $selectOrbital.addEventListener("change", function () {
      var idx = parseInt($selectOrbital.value, 10);
      if (isNaN(idx)) return;
      state.selectedOrbitalIndex = idx;
      App.emit("orbital:select", { orbital_index: idx });

      /* 자동으로 채팅을 통해 해당 오비탈 요청 */
      if (App.chat && App.chat.submit && state.result) {
        // ... (orbName 및 molName 추출 로직) ...

        // ❌ 문제 지점: 이 코드가 채팅 UI에 메시지를 띄우고 전체 파이프라인을 트리거함.
        App.chat.submit("Show the " + orbName + " orbital of " + molName);
      }
      saveViewerSnapshot();
    });
  }
```

---

## ✅ 해결 요구사항 (Action Items)

당신은 이 코드를 수정해야 합니다.

1.  **배경색 에러 해결:** `createViewer`의 `backgroundColor` 설정을 수정하여 "transparent" 에러가 발생하지 않도록 조치하세요. (`alpha: 0` 등 3Dmol 문서를 고려하거나 `"white"`, `"black"` 등 명시적 색상을 테마에 맞게 안전하게 할당).
2.  **조용한 백그라운드 요청(Silent Fetch) 구현:**
    *   `App.chat.submit` 대신, 채팅 UI를 더럽히지 않고 조용히 백엔드 API를 찔러서 결과를 가져오도록 수정하세요.
    *   현재 백엔드는 REST 기반 폴백 API (`POST /api/compute/jobs` 또는 `POST /api/chat`)를 지원합니다.
    *   `App.chat.submitMessage(prompt, { wait_for_result: true, silent: true })` 같은 방식을 쓰거나 (지원된다면), 직접 `fetch`를 통해 `/api/compute/jobs`에 페이로드를 보내고 결과를 폴링/대기한 뒤 뷰어에 바로 업데이트해주는 로직을 작성하세요.
    *   핵심은 **채팅 로그에 "Show the HOMO-1..." 이라는 사용자의 말이 추가되지 않아야 하고, 프로그레스 바도 거창하게 뜨는 대신 조그만 로딩 스피너 정도로 처리되어야** 한다는 것입니다.

이 두 가지 문제를 모두 해결한 **수정된 `viewer.js` 코드 스니펫과 설명**을 제공해 주세요!
