# 🛠️ QCViz-MCP v5: 고급 시각화 및 멀티-결과 탭 UI 구현 작업 지시서

현재 시스템의 활용성을 극대화하기 위해 다음 4가지 핵심 문제를 해결하고 고급 기능을 추가하려 합니다.
아래 지시사항과 관련 소스코드 맥락을 분석하여 프론트엔드 및 백엔드 코드를 업그레이드해 주세요.

---

## 🛑 요구사항 1: `base_filter` 로직 점검 (데이터 필터링)
**맥락:** 사용자가 `base_filter` 함수를 언급했습니다.
```python
def base_filter(df):
    return df[
        (df["gas"].isin(["He","Ar","H2","N2","O2"])) &
        (df["temperature_K"] == 293) &
        (df["lp_bar"] == 0.01) &
        (df["hp_bar"] == 5.0) &
        (df["status"] == "OK")
    ].copy()
```
**지시:** 이 코드는 아마도 다른 흡착/기체 분석 모듈의 코드인 것으로 보입니다. QCViz-MCP 프로젝트 내부에 이 코드가 있다면 확인하여 반영하고, 없다면 이 요구사항은 QCViz 맥락 밖(데이터 후처리 스크립트 등)에 해당하므로 어떻게 통합할지 방안을 제시하거나 패스하세요. (프로젝트 소스 내 검색 결과 이 코드는 현재 저장소에 없는 것으로 보입니다.)

---

## 🛑 요구사항 2: ESP 맵과 Orbital 동시/전환 시각화 문제
**문제:** 현재 UI에서는 한 번의 계산 결과에 대해 ESP가 렌더링되면 Orbital(오비탈) 렌더링 뷰로 넘어갈 수 없고, 반대로 오비탈이 렌더링되면 ESP를 볼 수 없습니다 (서로 상태를 덮어씀).
**원인:** `viewer.js` 내의 툴바 로직과 상태 전이 로직이 한 번에 하나의 볼륨 데이터 모드(`state.mode = 'esp'` 또는 `'orbital'`)만 고집하고 있으며, UI 상에서 이 둘을 자유롭게 토글(Toggle)할 수 있는 명확한 스위칭 버튼이 비활성화되거나 덮어써집니다.
**해결:**
1. `viewer.js`의 `showControls` 함수를 수정하여, 결과(`state.result`) 안에 `orbital_cube_b64`와 `esp_cube_b64`가 모두 존재한다면 ESP 버튼과 Orbital 버튼을 모두 노출시키고 클릭 시 즉시 렌더링 모드를 전환(`renderOrbital` ↔ `renderESP`)할 수 있게 만드세요.
2. 3Dmol 뷰어 상단 툴바에 "Orbital" / "ESP" 토글 버튼 그룹을 확실하게 활성화하세요.

---

## 🛑 요구사항 3: Geometry 최적화(Optimization) Trajectory 시각화
**문제:** Geometry Optimization (구조 최적화) 계산이 끝난 뒤, 초기 구조에서 최종 구조로 분자가 어떻게 변해갔는지(Trajectory/Animation)를 볼 수 없습니다.
**해결:**
1. **백엔드 (`pyscf_runner.py`):** `run_geometry_optimization` 과정에서 매 스텝(step)마다의 분자 좌표를 리스트에 담아, 최종 결과 객체에 `trajectory: [ { step: 1, xyz: "..." }, { step: 2, xyz: "..." } ... ]` 또는 다중 프레임 XYZ 문자열 형태로 반환하세요.
2. **프론트엔드 (`viewer.js` / `results.js`):** `result.trajectory`가 존재할 경우, 3Dmol 뷰어에 다중 프레임(Multi-model) 애니메이션 모드를 켜거나, 하단에 재생(Play) 버튼 / 타임라인 슬라이더를 추가하여 사용자가 최적화 궤적을 애니메이션으로 감상할 수 있게 만드세요.

---

## 🛑 요구사항 4: 단일 대화창 내 "다중 계산 결과" 탭(토글) UI 구현
**문제:** 하나의 대화창(채팅 세션) 안에서 A 계산을 하고 이어서 B 계산을 하면, 우측 Results 패널이 B 결과로 완전히 덮어씌워져서 A 결과를 다시 보려면 히스토리 패널을 눌러야만 하는 불편함이 있습니다.
**해결:**
1. **프론트엔드 (`results.js` / `index.html`):** Results 패널의 최상단에 **"Session Jobs" (또는 "계산 이력 탭")** 영역을 만드세요.
2. 이 탭은 현재 채팅 세션(또는 화면을 새로고침하기 전까지)에서 파생된 여러 결과들 (예: `[Job 1: Water HOMO]`, `[Job 2: Water LUMO]`)을 브라우저 탭처럼 가로로 나열합니다.
3. 사용자가 이 탭을 클릭하면 화면 전환(페이지 리로드) 없이 즉시 `state.result`를 교체하고 뷰어와 데이터 패널을 과거 계산 내용으로 스왑(Swap)할 수 있게 만드세요.

---

## 📄 참고 코드 컨텍스트

### `viewer.js` (모드 제어 부분)
```javascript
  /* ─── Render Orbital ─── */
  function renderOrbital(result) { ... state.mode = "orbital"; showControls("orbital"); }
  
  /* ─── Render ESP ─── */
  function renderESP(result) { ... state.mode = "esp"; showControls("esp"); }

  function showControls(mode) {
    if ($empty) $empty.hidden = true;
    if ($controls) $controls.hidden = false;
    // ❌ 현재 문제: mode가 orbital이 아니면 orbital 컨트롤을 아예 숨겨버려서 전환이 안 됨
    if ($grpOrbital) $grpOrbital.hidden = (mode !== "orbital" && mode !== "esp"); 
    if ($grpOpacity) $grpOpacity.hidden = (mode !== "orbital" && mode !== "esp");
    // ...
  }
```

### `pyscf_runner.py` (최적화 궤적 추출 포인트)
```python
def run_geometry_optimization(...):
    # ...
    try:
        _emit_progress(progress_callback, 0.45, "optimize", "Running geometry optimization")
        # 💡 이곳에서 PySCF geometric 최적화 엔진의 콜백을 활용하거나,
        # 최적화 과정을 추적하여 trajectory 배열을 만들어내야 함.
        opt_mol = geometric_optimize(mf0)
        optimization_performed = True
    except Exception as exc:
    # ...
    final_result = _make_base_result(...)
    # 💡 final_result["trajectory"] = trajectory_data 추가 필요
```

### `results.js` (결과 덮어쓰기 로직)
```javascript
  function update(result, jobId, source) {
    var normalized = normalizeResult(result);
    state.result = normalized; // ❌ 이전 결과를 완전히 날려버림
    state.jobId = jobId || null;
    // 💡 여러 결과를 배열로 담아두고(Session Jobs), 탭 UI를 통해 
    // 선택된 결과만 state.result에 넣어서 렌더링하는 로직(Multi-tab state)으로 개편 필요.
    // ...
```

---
**지시사항:** 위 4가지 요구사항을 충족하기 위해 수정되어야 할 Python 및 JavaScript 코드를 작성하고, 적용 방법을 구체적으로 제시하세요.
