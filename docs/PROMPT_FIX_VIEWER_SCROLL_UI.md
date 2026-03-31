# 🛠️ QCViz-MCP v5: 3D 뷰어 에러 및 채팅 스크롤/캔버스 요동 버그 수정 작업 지시서

현재 프론트엔드 UI(`viewer.js`, `style.css`, `index.html`)에서 몇 가지 불편한 버그들이 발생하고 있습니다. 아래 맥락을 분석하여 문제를 해결해 주세요.

---

## 🛑 문제 상황 1: 3Dmol.js 초기화 에러 (`transparent` 색상 인식 불가)

브라우저 콘솔에 다음과 같은 에러가 지속적으로 발생합니다.
```text
color not found transparent {aliceblue: 15792383, antiquewhite: 16444375, aqua: 65535, aquamarine: 8388564, azure: 15794175, …}
getHex @ 3Dmol-min.js:2
...
ensureViewer @ viewer.js:51
```

### 🔍 원인 파악
`ensureViewer` 함수에서 `window.$3Dmol.createViewer`를 초기화할 때 `backgroundColor: "transparent"`를 넘기고 있는데, 3Dmol.js 내부의 색상 파서가 CSS Named Color 사전에 없는 `"transparent"`를 처리하지 못해 에러를 뱉고 있습니다.

### ✅ 해결 요구사항
- `viewer.js` 내 `createViewer` 옵션에서 `backgroundColor: "transparent"`를 제거하고, 대신 테마에 맞게 `"white"` 또는 `"black"`을 전달하세요.
- 만약 시각적인 투명 효과가 꼭 필요하다면, 뷰어가 생성된 직후 내부 `<canvas>` DOM 요소에 직접 CSS로 `background-color: transparent !important;`를 부여하는 우회 방식을 사용하세요.

---

## 🛑 문제 상황 2: 오비탈 재선택 시 캔버스가 제멋대로 움직이고 확대되는 현상

오비탈 드롭다운(Select Box)에서 다른 오비탈 준위를 선택할 때마다, 3D 뷰어 캔버스 안의 분자가 갑자기 휙 돌아가거나 화면 밖으로 확대되어 튀어나가는(요동치는) 현상이 발생합니다. 사용자가 카메라 시점을 맞춰놓았는데, 다른 오비탈을 볼 때마다 시점이 리셋되어 매우 불편합니다.

### 🔍 원인 파악
`viewer.js`에서 오비탈을 새로 렌더링할 때(예: `renderOrbital` 함수 내부) 매번 `viewer.zoomTo()`가 강제로 호출되고 있을 가능성이 높습니다. 
이미 캔버스에 분자가 로드되어 있는 상태(동일 분자의 다른 오비탈만 교체하는 상황)라면 줌과 카메라 시점을 유지해야 합니다.

### ✅ 해결 요구사항
- `viewer.js`의 렌더링 로직(`renderOrbital`, `renderESP` 등)을 검토하여, **새로운 구조(XYZ)를 처음 로드할 때만 `viewer.zoomTo()`를 실행**하도록 수정하세요.
- 같은 분자의 오비탈 표면(Volumetric Data)만 교체하는 경우에는 `viewer.zoomTo()` 호출을 생략(또는 조건부 실행)하여 사용자가 맞춰둔 카메라 앵글과 줌 레벨이 완벽히 보존되게 만드세요.

---

## 🛑 문제 상황 3: 레이아웃 요동 (채팅창 스크롤 부재)

뷰어가 흔들리는 또 다른 원인으로, 우측 패널(특히 **채팅창이나 히스토리 패널**)에 고정된 스크롤 영역이 없어서, 내용물이 늘어나면 전체 페이지 길이를 밀어내면서 뷰어 패널의 크기와 캔버스 비율이 틀어지고 3Dmol.js가 `resize()`를 트리거하는 레이아웃 불안정(Layout Shift) 문제가 의심됩니다.

### 🔍 원인 파악
`style.css`에서 채팅 로그(`.chat-log`, `.chat-messages` 등) 영역이나 결과 탭 콘텐츠에 최대 높이(`max-height`) 및 `overflow-y: auto;` 제한이 제대로 걸려있지 않아, 부모 컨테이너(Grid/Flex)가 무한정 팽창하고 있습니다.

### ✅ 해결 요구사항
- `style.css` 또는 `index.html` 레이아웃을 점검하세요.
- 우측의 채팅 로그(`.chat-log` 등) 영역이 부모의 남은 공간을 채우되, 일정 높이 이상 커지지 않고 내부에 스크롤바가 생기도록(`flex: 1`, `overflow-y: auto`, `min-height: 0` 등 활용) 구조를 단단히 잡아주세요.
- 좌측 3D 뷰어 패널 역시 화면 스크롤 시 밀려나가지 않게 크기를 견고하게 고정(Lock)해 주세요.

---

위 세 가지 문제를 모두 해결하는 구체적인 코드 스니펫(CSS 및 JavaScript 변경 사항)을 제시하고 어떻게 적용해야 하는지 설명해 주세요!