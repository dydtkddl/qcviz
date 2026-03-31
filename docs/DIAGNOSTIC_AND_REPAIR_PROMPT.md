# QCViz-MCP v5 프론트엔드 총체적 붕괴 진단 및 복구 작업 지시서

현재 시스템은 여러 차례의 파편화된 프론트엔드 스크립트(`viewer.js`, `app.js`, `results.js`, `style.css`) 수정 과정을 거치면서, 렌더링 파이프라인의 타이밍 충돌, 전역 변수 참조 오류(`ReferenceError`), 그리고 DOM 요소 바인딩 순서가 뒤엉키며 **완전히 먹통**이 된 상태입니다.

다음 증상들을 완벽하게 진단하고, 꼬여버린 프론트엔드 코드를 하나의 우아한 흐름으로 재작성해 줄 LLM에게 전달할 프롬프트입니다.

---

## 🚨 현재 치명적 증상 (사용자 리포트)
1. **무한 로딩**: 앱 처음에 접속하면 로딩 스피너가 사라지지 않고 무한 루프 돎.
2. **ESP 버튼 먹통**: ESP 버튼을 아무리 눌러도 반응이 없고, Orbital을 눌렀다가 다시 돌아와야 간헐적으로 나옴. 게다가 ESP와 Orbital 표면이 렌더링 시 **계속 겹쳐서(Overlapping) 중첩**됨.
3. **Color Scheme 미적용**: Color Scheme(색상 스킴)을 바꾸면 Orbital에는 반영되지만, ESP 표면과 ESP의 범례(Legend) 그라디언트에는 적용되지 않거나 서로 따로 돎.
4. **History 증발**: 새로고침하면 `InMemoryJobManager`에 저장했던 작업 목록이 화면에 전혀 렌더링되지 않음.
5. **세션 연속성 붕괴**: 새로운 분자를 계산하면 예전 결과가 완전히 날아가버림 (상단 세션 탭 로직 붕괴).
6. **뷰어 찌그러짐**: 데이터가 많아지면 아래쪽 패널이 무식하게 커지며 상단 3D 뷰어를 찌그러뜨림.

---

## 📂 파일별 코드 스니펫 및 문제 진단 포인트 (전수조사)

아래는 현재 `version02/src/qcviz_mcp/web/static/` 내의 핵심 파일들에서 문제가 되는 부분들의 원문입니다. 이 코드를 분석하고 처음부터 끝까지 깨끗하게 재구조화해 주세요.

### 1. `app.js` (무한 로딩 & History 증발 이슈)
```javascript
// [원인 진단] fetchHistory가 비동기로 돌고 있는데, DOMContentLoaded 전에 실행되거나 
// renderSessionTabs()나 renderHistory()에서 DOM 객체가 없어서 에러가 발생하여 전체 앱 초기화가 멈추는 것으로 강하게 의심됨.

  function fetchHistory() {
    return fetch(PREFIX + "/compute/jobs?include_result=true")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var jobs = Array.isArray(data) ? data : (data.items || []);
        var sortedJobs = jobs.sort(function(a, b) { return a.created_at - b.created_at; });
        sortedJobs.forEach(function (j) { App.upsertJob(j); });
        renderHistory(); // DOM이 준비되지 않은 상태에서 호출되면?
      });
  }

  // Session Tabs 렌더링 로직
  function renderSessionTabs() {
    if (!$sessionTabs || !$sessionTabsContainer) return; // 전역 변수 타이밍 이슈?
    // ...
  }
```

### 2. `viewer.js` (ESP 중첩, 컬러 스킴 렌더링 락 데드락)
```javascript
// [원인 진단] GPU 버퍼를 지우기 위한 setTimeout과 _vizSwitchLock이 존재하지만,
// 내부의 예외(ReferenceError 등) 발생 시 finally 블록으로 가기 전에 Promise 체인이 깨지거나
// 혹은 3Dmol.js의 createGradient 호출 시 voldata, volscheme 파라미터가 꼬여서 렌더링 자체가 터짐.

  var _vizSwitchLock = false;
  function switchVizMode(newMode) {
    if (!state.result || state.mode === newMode) return;
    if (_vizSwitchLock) return;
    _vizSwitchLock = true;
    state.mode = newMode;

    if (state.viewer) {
      state.viewer.removeAllSurfaces();
      if (typeof state.viewer.removeAllShapes === "function") state.viewer.removeAllShapes();
      state.viewer.render();
    }

    setTimeout(function() {
      try {
        var result = state.result;
        var scheme = getCurrentColorScheme();
        
        if (newMode === "esp") {
          var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          var densVol = densB64 ? new window.$3Dmol.VolumeData(atob(densB64), "cube") : espVol;
          var minVal = scheme.reverse ? range : -range;
          var maxVal = scheme.reverse ? -range : range;
          
          // ⚠️ 여기서 grad 생성이나 addIsosurface 파라미터에서 충돌 발생!
          var grad = createGradient(scheme.espGradient, minVal, maxVal);
          state.viewer.addIsosurface(densVol, {
            isoval: state.espDensityIso || 0.001,
            color: "white",
            alpha: state.opacity,
            smoothness: 1,
            voldata: espVol,
            volscheme: grad 
          });
        }
        if (state.viewer) state.viewer.render();
      } catch(e) {
          console.error("[Viewer] Surface render error:", e);
      } finally {
          showControls(newMode);
          saveViewerSnapshot();
          _vizSwitchLock = false;
      }
    }, 30);
  }
```

### 3. `style.css` (레이아웃 찌그러짐)
```css
/* [원인 진단] grid-template-rows의 minmax 설정값이 내부 콘텐츠 크기에 의해 
   유연하게 줄어들지 못하고 강제로 뷰어를 밀어내는 중 */
.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  /* ⚠️ 450px 최소 고정이 작은 모니터에서 문제를 일으킴 */
  grid-template-rows: minmax(450px, 1.8fr) minmax(200px, 0.6fr);
  grid-template-areas: "viewer chat" "results history";
  gap: var(--sp-3);
  flex: 1;
  min-height: 0;
}
```

---

## ✅ LLM에게 요구하는 최종 미션 (Action Items)

새로운 LLM 환경(Claude 등)은 위 코드들의 총체적 난국을 파악하고, 아래의 5대 원칙을 지켜 완벽한 복구 코드를 작성하시오.

1. **안전한 초기화 파이프라인 구축**: `app.js`와 `viewer.js`의 DOM 변수 할당(`document.getElementById`)과 이벤트 리스너 바인딩, 데이터 패치가 반드시 `DOMContentLoaded` 완료 이후 순차적으로(에러 없이) 실행되게 구조를 다시 짜라. (무한 로딩 및 먹통 해결)
2. **렌더링 락(Lock) 무결성 확보**: ESP ↔ Orbital 전환 시, 이전 표면이 절대 남지 않도록 `removeAllSurfaces()`를 처리하고, 3Dmol.js `Gradient` 생성 API(`voldata`, `volscheme`)를 한 치의 오차 없이 호환되도록 구성하라. (ESP 표면 겹침 및 색상 미적용 해결)
3. **색상 스킴 100% 동기화**: `viewer.js`의 `selectColorScheme` 핸들러가 발동할 때 분자 구조를 파괴하지 않고, 락 메커니즘을 거쳐 Orbital 로브와 ESP 그라디언트, 그리고 우측 상단의 CSS 범례(Legend)까지 완벽하게 색깔을 맞춰라.
4. **Session Tabs 및 History 방어**: 백엔드에서 내려주는 작업 내역을 렌더링할 때, 상단의 세션 탭 배열과 우측 하단 History 리스트 DOM이 중복 에러나 런타임 오류로 죽지 않도록 방어 로직(`try-catch`, `if(!dom) return`)을 촘촘히 두어라.
5. **반응형 대시보드 리팩토링**: `style.css`에서 하단 패널이 커지더라도 상단 `viewer-container` 영역이 최소 50% 이상의 공간을 확보하도록 Grid 혹은 Flexbox 비율을 영리하게 수정하라.