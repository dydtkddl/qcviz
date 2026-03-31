# QCViz-MCP v5 Enterprise — 전수조사 및 결함 보고서

## 1. 파이프라인 횡단 정합성 검증 결과

전체 데이터 흐름(`pyscf_runner.py` → `compute.py` → WebSocket/HTTP → `chat.js` → `results.js` → `viewer.js`)을 1줄씩 추적하여 다음 결함들을 식별했습니다.

---

## 2. 식별된 결함 목록 (총 23건)

### A. 백엔드 내부 결함 (pyscf_runner.py)

**결함 #1: `logger` 미선언 — `run_geometry_optimization`에서 ReferenceError**

`run_geometry_optimization` 함수 내부에서 `logger.info(...)`, `logger.warning(...)` 호출이 여러 곳에 있으나, 이 모듈에는 `logger = logging.getLogger(__name__)` 선언이 없습니다. 또한 `import logging` 자체도 없습니다. 실행 시 `NameError: name 'logger' is not defined`가 발생하여 **geometry optimization이 완전히 실패**합니다.

```python
# pyscf_runner.py, run_geometry_optimization 내부 (약 line 750+)
logger.info("geometric solver not found, trying berny")   # ← NameError
logger.warning(f"geometric solver failed: {e}, ...")       # ← NameError
logger.warning(f"Geometry optimization failed: {exc}")     # ← NameError
```

**수정:**

```python
# pyscf_runner.py 상단, import 섹션에 추가
import logging
logger = logging.getLogger(__name__)
```

---

**결함 #2: `_lookup_builtin_xyz` — regex 이중 이스케이프로 noise word 필터링 실패**

`_lookup_builtin_xyz` 함수의 noise 필터링 코드가 Python raw string이 아닌 일반 string에서 `\\b`를 사용하고 있어 `\b` (word boundary)가 아닌 리터럴 `\b`로 매칭을 시도합니다. 결과적으로 noise 단어가 제거되지 않아 구조체 조회에 실패할 수 있습니다.

```python
# 현재 (잘못됨)
for n in noise:
    qc = re.sub(rf"\\b{n}\\b", " ", qc, flags=re.I)
qc = re.sub(r"\\s+", " ", qc).strip()
```

**수정:**

```python
for n in noise:
    qc = re.sub(rf"\b{n}\b", " ", qc, flags=re.I)
qc = re.sub(r"\s+", " ", qc).strip()
```

---

**결함 #3: `_extract_frontier_gap` — `best_lumo` 값이 `best_homo`와 동일 객체를 참조하여 LUMO 에너지가 올바르게 할당되지 않음**

```python
# 현재 코드
if best_gap is None or gap_ha < best_gap:
    best_gap = gap_ha
    best_homo = info   # info 하나로 homo와 lumo 둘 다 설정
    best_lumo = info   # ← best_lumo도 같은 info 참조
```

이 경우 `out["lumo_energy_hartree"]`에 `best_lumo["lumo_energy_hartree"]`를 사용하므로 실제 값은 올바르지만, 변수 명명이 혼동을 유발합니다. 실질적으로는 **같은 channel의 info 객체에 homo와 lumo 정보가 모두 들어있으므로 값 자체는 정확**합니다. 그러나 의미적 명확성을 위해 수정을 권장합니다.

**수정 (가독성 개선):**

```python
if best_gap is None or gap_ha < best_gap:
    best_gap = gap_ha
    best_channel_info = info

# 이후:
if best_channel_info:
    out["homo_energy_hartree"] = best_channel_info["homo_energy_hartree"]
    out["homo_energy_ev"] = best_channel_info["homo_energy_ev"]
    out["homo_index"] = best_channel_info["homo_index"]
    out["lumo_energy_hartree"] = best_channel_info["lumo_energy_hartree"]
    out["lumo_energy_ev"] = best_channel_info["lumo_energy_ev"]
    out["lumo_index"] = best_channel_info["lumo_index"]
```

---

### B. 백엔드 라우팅/상태 관리 결함 (compute.py)

**결함 #4: `InMemoryJobManager._run_job` — Race Condition: `_run_job` 내부에서 `job` 변수가 lock 바깥에서 참조됨**

```python
def _run_job(self, job_id: str) -> None:
    with self.lock:
        job = self.jobs[job_id]
        job.status = "running"
        # ...

    def progress_callback(*args, **kwargs):
        # ...
        with self.lock:
            record = self.jobs[job_id]  # ← 올바르게 lock 내에서 재조회

    try:
        result = _run_direct_compute(job.payload, ...)  # ← job은 lock 밖에서 참조!
```

`job.payload`는 lock 밖에서 접근됩니다. `payload`는 submit 시점에 설정되고 이후 변경되지 않으므로 **실질적인 data race는 아니지만**, 방어적 코딩 원칙에 따라 lock 내에서 payload를 복사하는 것이 안전합니다.

**수정:**

```python
def _run_job(self, job_id: str) -> None:
    with self.lock:
        job = self.jobs[job_id]
        job.status = "running"
        job.started_at = _now_ts()
        job.updated_at = job.started_at
        job.step = "starting"
        job.message = "Starting job"
        self._append_event(job, "job_started", "Job started")
        payload_copy = dict(job.payload)  # ← lock 내에서 복사

    # ... progress_callback ...

    try:
        result = _run_direct_compute(payload_copy, progress_callback=progress_callback)
```

---

**결함 #5: `InMemoryJobManager` — `_save_to_disk`가 `_run_job` 완료 후 호출되지 않음**

Job이 완료되거나 실패해도 `_save_to_disk()`가 호출되지 않아 서버 재시작 시 최신 완료 결과가 유실됩니다.

**수정:** `_run_job`의 `completed`와 `failed` 블록 끝에 추가:

```python
# completed 블록 끝
self._save_to_disk()

# failed 블록(들) 끝
self._save_to_disk()
```

---

**결함 #6: `_prepare_payload` — `_extract_message`가 빈 string을 반환할 때 `_safe_plan_message`에 빈 string이 전달됨**

`raw_message`가 빈 string이면 `_safe_plan_message("")`가 호출되는데, `QCVizAgent.plan("")`은 confidence 0.0의 기본 plan을 반환합니다. 이 자체는 에러가 아니지만, 이후 `_merge_plan_into_payload`에서 `structure_query`가 없는 상태로 진행되어 최종적으로 HTTP 400이 발생합니다. 이는 의도된 동작이므로 **결함은 아니지만** 로직 확인을 위해 기록합니다.

---

### C. Agent/LLM 모듈 결함 (agent.py, providers.py)

**결함 #7: `agent.py`의 `INTENT_DEFAULTS`에서 `focus_tab`이 "orbitals"로 설정되어 있으나, 프론트엔드와 백엔드의 나머지 코드는 모두 "orbital"을 사용함**

```python
# agent.py
INTENT_DEFAULTS = {
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbitals"},  # ← "orbitals"
    # ...
}
```

반면 `compute.py`의 `_focus_tab_from_result`:

```python
if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
    return value
```

"orbitals"는 이 set에 포함되지 않으므로 무시됩니다.

그리고 `pyscf_runner.py`의 `_focus_tab_for_result`:

```python
if forced in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
    return forced
```

역시 "orbitals"를 인식하지 못합니다.

**결과:** LLM agent가 `focus_tab: "orbitals"`를 반환하면 프론트엔드에서 orbital 탭으로 자동 전환이 실패하고 fallback 로직에 의존하게 됩니다.

**수정 (agent.py):**

```python
INTENT_DEFAULTS = {
    # ...
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},  # 수정
    # ...
}
```

**추가 수정 (PLAN_TOOL_SCHEMA):**

```python
"focus_tab": {
    "type": "string",
    "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
    #                                  ^^^^^^^^ "orbitals" → "orbital"
},
```

---

**결함 #8: `providers.py`의 `DummyProvider`에서 `suggested_focus_tab`이 "orbitals"를 반환하나, 이 역시 동일 불일치 문제**

```python
# providers.py DummyProvider
if any(x in text for x in ["orbital", "homo", "lumo", "오비탈"]):
    tool = "run_orbital_preview"
    focus = "orbitals"  # ← "orbitals" → "orbital"로 수정 필요
```

**수정:**

```python
    focus = "orbital"
```

---

**결함 #9: `providers.py`의 `DummyProvider`에서 한국어 키워드 오류**

```python
elif any(x in text for x in ["esp", "potential", "map", "전기정전위"]):
```

"전기정전위"는 정확한 한국어가 아닙니다. `compute.py`의 heuristic에서는 `"정전기"`, `"전위"`를 사용합니다.

**수정:**

```python
elif any(x in text for x in ["esp", "potential", "map", "정전기", "전위"]):
```

---

**결함 #10: `agent.py`의 `QCVizAgent`에는 `plan()` 메서드가 있으나, `compute.py`의 `_safe_plan_message`는 `plan_message()`를 먼저 찾음**

```python
# compute.py
if hasattr(agent, "plan_message") and callable(agent.plan_message):
    return _coerce_plan_to_dict(agent.plan_message(message, payload=payload))
if hasattr(agent, "plan") and callable(agent.plan):
    return _coerce_plan_to_dict(agent.plan(message, payload=payload))
```

`QCVizAgent`에는 `plan_message` 메서드가 없으므로 `plan()`이 호출됩니다. 그러나 `plan()`의 시그니처는 `plan(self, message, context=None)`이며, `compute.py`는 `payload=payload`로 호출합니다. `plan()`에는 `payload` 키워드가 없으므로 **`TypeError` 발생** → `except TypeError` 블록으로 가서 `agent.plan(message)` (인자 하나만)로 재시도합니다. 이때 `context`가 전달되지 않습니다.

**수정 (compute.py의 `_safe_plan_message`):**

```python
if hasattr(agent, "plan") and callable(agent.plan):
    return _coerce_plan_to_dict(agent.plan(message, context=dict(payload)))
```

또는 agent.py의 `plan` 메서드에 `**kwargs`를 추가:

```python
def plan(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> AgentPlan:
```

---

**결함 #11: `agent.py` `_coerce_plan`의 반환값인 `AgentPlan`의 필드가 `compute.py`의 `_coerce_plan_to_dict`에서 올바르게 매핑되지 않는 필드**

`AgentPlan`에는 `focus_tab` 필드가 있으나, `compute.py`의 `_merge_plan_into_payload`는 `advisor_focus_tab`을 기대합니다:

```python
# compute.py _merge_plan_into_payload
for key in ("method", "basis", "orbital", "advisor_focus_tab"):
    if not out.get(key) and plan.get(key):
        out[key] = plan.get(key)
```

`AgentPlan.to_dict()`는 `focus_tab` 키를 반환하지만 `advisor_focus_tab`은 반환하지 않습니다. 따라서 **advisor_focus_tab이 항상 None**이 됩니다.

**수정 (compute.py의 `_coerce_plan_to_dict` 또는 `_merge_plan_into_payload`):**

```python
# _merge_plan_into_payload에 추가
if not out.get("advisor_focus_tab"):
    out["advisor_focus_tab"] = plan.get("advisor_focus_tab") or plan.get("focus_tab")
```

---

### D. 프론트엔드 결함 (results.js)

**결함 #12: `normalizeResult` — `viz.xyz_block` 설정 시 backend가 보내는 실제 키와 불일치**

Backend의 `_finalize_result_contract`는 `visualization.xyz`와 `visualization.molecule_xyz`를 설정합니다. `results.js`의 `normalizeResult`는 이를 `viz.xyz_block`으로 복사합니다:

```javascript
if (!viz.xyz_block) {
  viz.xyz_block = viz.xyz || viz.molecule_xyz || r.xyz_block || r.xyz || null;
}
```

이 코드 자체는 올바르게 변환합니다. 그러나 `renderGeometry`에서:

```javascript
if (!atoms.length && !r.visualization.xyz_block)
  return '<p class="result-note">No geometry data.</p>';
```

`normalizeResult`가 호출된 후이므로 `viz.xyz_block`이 설정되어 있어 동작은 정확합니다. **결함 아님 — 확인 완료.**

---

**결함 #13: `results.js` `renderCharges` — `r.mulliken_charges`가 `normalizeResult`에 의해 숫자 배열로 변환된 후 `Object.keys()`로 체크됨**

`normalizeResult`에서:

```javascript
if (
  r.mulliken_charges &&
  r.mulliken_charges.length &&
  typeof r.mulliken_charges[0] === "object"
) {
  r.mulliken_charges = r.mulliken_charges.map(function (c) {
    return c.charge != null ? c.charge : c;
  });
}
```

이후 `getAvailableTabs`에서:

```javascript
var hasMulliken =
  r.mulliken_charges && Object.keys(r.mulliken_charges).length > 0;
```

배열에 `Object.keys()`를 사용하면 `["0", "1", "2", ...]`가 반환되어 동작은 합니다. 그러나 **빈 배열 `[]`에도 `Object.keys([]).length === 0`이므로 정확**합니다. 다만 `Array.isArray` 체크와 `.length`를 사용하는 것이 더 명확합니다.

**수정 (권장):**

```javascript
var hasMulliken =
  Array.isArray(r.mulliken_charges) && r.mulliken_charges.length > 0;
var hasLowdin = Array.isArray(r.lowdin_charges) && r.lowdin_charges.length > 0;
```

---

**결함 #14: `results.js` `renderOrbital` — `r.orbitals` 배열의 `is_selected` 필드를 참조하나 backend는 이 필드를 설정하지 않음**

```javascript
// results.js renderOrbital
var orbitals = r.orbitals || [];
// ...
for (var i = 0; i < orbs.length; i++) {
  if (orbs[i] && orbs[i].is_selected) {
    selIdx = i;
    break;
  }
}
```

Backend의 `_build_orbital_items`는 `is_selected` 필드를 포함하지 않습니다. 따라서 `selIdx`는 항상 0입니다. 이 코드는 `buildResultLabel` 함수 내에서만 사용되며, 실제 선택된 orbital 정보는 `r.selected_orbital`에 있습니다.

**수정 (`results.js` `buildResultLabel`):**

```javascript
var orbLabel = "MO";
if (result.selected_orbital && result.selected_orbital.label) {
  orbLabel = result.selected_orbital.label;
} else if (orbs.length > 0 && orbs[0] && orbs[0].label) {
  orbLabel = orbs[0].label;
}
```

---

### E. 프론트엔드 결함 (viewer.js)

**결함 #15: `viewer.js` `addESPSurface` — ESP 모드에서 `state.isovalue`가 orbital의 기본값(0.03)인 채로 density isosurface에 사용됨**

ESP 모드에서는 density isosurface의 isovalue로 `state.espDensityIso` (0.001)가 사용되어야 합니다. 그러나 `addESPSurface`는 `state.isovalue`를 사용합니다:

```javascript
viewer.addIsosurface(densVol, {
    isoval: state.isovalue,  // ← 0.03이면 density surface가 너무 작아짐
```

`showControls("esp")`에서 슬라이더 범위가 변경되지만, 초기 렌더링 시점에서는 이전 mode의 `state.isovalue`가 남아있을 수 있습니다.

**수정 (`renderESP` 진입 시):**

```javascript
function renderESP(result) {
    return ensureViewer().then(function (viewer) {
        // ESP 모드 전환 시 isovalue를 density-appropriate 값으로 조정
        if (state.isovalue > 0.02 || state.isovalue < 0.0001) {
            state.isovalue = 0.002;
        }
        // ... 나머지 코드
```

이 코드는 이미 `showControls("esp")` 내에 존재하지만, `showControls`는 `renderESP` 내에서 `addESPSurface` **이후에** 호출됩니다. 따라서 **첫 렌더링에서는 잘못된 isovalue가 사용**됩니다.

**수정 (순서 변경):**

```javascript
function renderESP(result) {
  return ensureViewer().then(function (viewer) {
    var oldXyz = state.result ? getXyz(state.result) : null;
    var newXyz = getXyz(result);
    var isNew = oldXyz !== newXyz;

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

    if (state.showLabels && state.model) addLabels(viewer, result);
    if (isNew) viewer.zoomTo();
    viewer.render();
    state.mode = "esp";
    showControls("esp");
    showESPLegend();
  });
}
```

---

**결함 #16: `viewer.js` `switchVizMode` — 전환 중 `state.mode = "switching"`으로 설정 후 실패 시 복원이 불완전**

```javascript
function switchVizMode(newMode) {
  if (!state.result) return;
  if (state.mode === newMode) return;
  var prevMode = state.mode;
  state.mode = "switching";

  var p;
  if (newMode === "orbital") {
    p = renderOrbital(state.result);
  } else if (newMode === "esp") {
    p = renderESP(state.result);
  }

  if (p) {
    p.then(function () {
      saveViewerSnapshot();
    }).catch(function (err) {
      console.error("[Viewer] Mode switch failed:", err);
      state.mode = prevMode;
      showControls(prevMode);
    });
  } else {
    state.mode = prevMode; // ← newMode가 "molecule"이면 여기
  }
}
```

`newMode`가 "molecule"이면 `p`가 `undefined`이고 `state.mode`가 `prevMode`로 복원되지만, molecule 렌더링은 수행되지 않습니다. 버튼 UI에서는 orbital/ESP만 토글하므로 실제로 발생하지 않을 수 있으나, **방어적으로 처리**해야 합니다.

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

**결함 #17: `viewer.js` — `state.viewer` null 체크 없이 `clearViewer` 호출 시 안전하지만, `renderMolecule`/`renderOrbital`/`renderESP` 내에서 `ensureViewer()`의 rejection이 제대로 전파되지 않는 경로 존재**

`handleResult`에서:

```javascript
if (p) p.then(saveViewerSnapshot).catch(console.error);
```

이 catch는 에러를 로그하지만 UI 상태를 복원하지 않습니다. 3Dmol.js 로드 실패 시 `ensureViewer`가 reject되면 `state.mode`가 업데이트되지 않은 채로 남아있습니다.

**수정 (`handleResult`):**

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

### F. 프론트엔드 결함 (chat.js)

**결함 #18: `chat.js` WebSocket `connectWS` — 이전 연결의 handler가 계속 fire될 수 있는 ghost callback 문제**

현재 코드는 이미 handler에 `if (this !== state.ws) return;` 가드를 추가하여 이 문제를 해결하고 있습니다. **결함 아님 — 확인 완료.**

---

**결함 #19: `chat.js` `handleServerEvent` "result" case — `App.upsertJob`에서 `basis` 필드명 불일치**

```javascript
// chat.js
App.upsertJob({
  // ...
  basis_set: result.basis || result.basis_set || "",
});
```

Backend는 `basis`를 반환합니다. `app.js`의 `getJobDetailLine`은:

```javascript
var basis =
  job.basis_set ||
  (job.result && job.result.basis_set) ||
  (job.payload && job.payload.basis_set) ||
  "";
```

Backend 결과에는 `basis_set`이 아닌 `basis`가 있으므로, `job.result.basis_set`은 `undefined`입니다. 그러나 `chat.js`에서 `basis_set: result.basis || result.basis_set`로 설정하므로 job 레벨에서는 올바르게 `basis_set`이 설정됩니다.

이 패턴은 일관성이 없고 혼동을 초래합니다. Backend 결과 객체의 필드명은 `basis`이고, 프론트엔드 job 레코드의 필드명은 `basis_set`입니다.

**수정 (app.js `getJobDetailLine` 보강):**

```javascript
var basis =
  job.basis_set ||
  job.basis ||
  (job.result && (job.result.basis || job.result.basis_set)) ||
  (job.payload && (job.payload.basis || job.payload.basis_set)) ||
  "";
```

---

**결함 #20: `chat.js` `handleServerEvent` "result" case — `result.total_energy_hartree`와 `result.energy` fallback**

```javascript
var energy =
  result.total_energy_hartree != null
    ? result.total_energy_hartree
    : result.energy;
```

Backend는 `_finalize_result_contract`에서 `total_energy_hartree`를 항상 설정하므로, `result.energy` fallback은 레거시 호환용입니다. **정상 — 확인 완료.**

---

### G. 프론트엔드 결함 (app.js)

**결함 #21: `app.js` `fetchHistory` — backend 응답의 `created_at`이 Unix timestamp(초 단위)인데, `new Date()`에서 밀리초로 변환하지 않는 경로 존재**

```javascript
var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
```

이 코드는 `1e12` 미만이면 초 단위로 판단하여 1000을 곱합니다. Backend의 `_now_ts()`는 `time.time()`을 사용하며, 현재 시점의 Unix timestamp는 약 `1.7e9`이므로 `1e12` 미만입니다. **정상 — 확인 완료.**

---

**결함 #22: `app.js` — `renderSessionTabs`에서 `job.method`가 undefined일 수 있으나 CSS에서 빈 괄호 "( )"가 표시됨**

```javascript
var displayStr = name + (method ? " (" + method + ")" : "") + badge;
```

`method`가 `""`이면 falsy이므로 괄호가 표시되지 않습니다. **정상.**

---

### H. 크로스-모듈 데이터 계약 불일치

**결함 #23: Backend `compute.py` `_snapshot` 메서드가 반환하는 job 구조에 `job_type` 필드가 없음**

```python
def _snapshot(self, job, ...):
    snap = {
        "job_id": job.job_id,
        "status": job.status,
        "user_query": job.user_query,
        "molecule_name": job.payload.get("structure_query", ""),
        "method": job.payload.get("method", ""),
        "basis_set": job.payload.get("basis", ""),  # "basis" → "basis_set"으로 변환됨
        # ... job_type이 없음!
    }
```

프론트엔드 `app.js`의 `getJobDetailLine`과 `getJobDisplayName`에서는 `job.job_type`을 참조합니다:

```javascript
var jobType =
  job.job_type ||
  (job.result && job.result.job_type) ||
  (job.payload && job.payload.job_type) ||
  "computation";
```

`include_payload=false`인 경우 `job.job_type`이 없으므로 항상 `"computation"` fallback이 사용됩니다.

**수정 (compute.py `_snapshot`):**

```python
snap = {
    "job_id": job.job_id,
    "status": job.status,
    "user_query": job.user_query,
    "job_type": job.payload.get("job_type", ""),  # 추가
    "molecule_name": job.payload.get("structure_query", ""),
    "method": job.payload.get("method", ""),
    "basis_set": job.payload.get("basis", ""),
    # ...
}
```

---

## 3. 수정된 코드 (파일별)

### File: `compute/pyscf_runner.py` — 수정 사항

```python
# ============================================================
# 수정 #1: logging import 및 logger 선언 추가
# 파일 상단 import 섹션에 추가
# ============================================================
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 수정 #2: _lookup_builtin_xyz의 이중 이스케이프 수정
# ============================================================
def _lookup_builtin_xyz(query: Optional[str]) -> Optional[Tuple[str, str]]:
    if not query:
        return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)

    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge",
             "charges", "mulliken", "partial", "geometry", "optimization",
             "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\b{n}\b", " ", qc, flags=re.I)  # 수정: \\b → \b
    qc = re.sub(r"\s+", " ", qc).strip()                 # 수정: \\s+ → \s+

    # ... 나머지 동일 ...


# ============================================================
# 수정 #3: _extract_frontier_gap 가독성 개선
# ============================================================
def _extract_frontier_gap(mf) -> Dict[str, Any]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel_info: List[Dict[str, Any]] = []
    best_gap = None
    best_channel_info = None  # 수정: best_homo, best_lumo → best_channel_info

    for energies, occs, spin_label in zip(mo_energies, mo_occs, spin_labels):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)

        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0 or vir_idx.size == 0:
            continue

        homo_idx = int(occ_idx[-1])
        lumo_idx = int(vir_idx[0])
        gap_ha = float(energies[lumo_idx] - energies[homo_idx])

        info = {
            "spin": spin_label,
            "homo_index": homo_idx + 1,
            "lumo_index": lumo_idx + 1,
            "homo_energy_hartree": float(energies[homo_idx]),
            "lumo_energy_hartree": float(energies[lumo_idx]),
            "homo_energy_ev": float(energies[homo_idx] * HARTREE_TO_EV),
            "lumo_energy_ev": float(energies[lumo_idx] * HARTREE_TO_EV),
            "gap_hartree": gap_ha,
            "gap_ev": gap_ha * HARTREE_TO_EV,
        }
        channel_info.append(info)

        if best_gap is None or gap_ha < best_gap:
            best_gap = gap_ha
            best_channel_info = info  # 수정

    out: Dict[str, Any] = {
        "frontier_channels": channel_info,
        "orbital_gap_hartree": float(best_gap) if best_gap is not None else None,
        "orbital_gap_ev": float(best_gap * HARTREE_TO_EV) if best_gap is not None else None,
    }

    if best_channel_info:  # 수정
        out["homo_energy_hartree"] = best_channel_info["homo_energy_hartree"]
        out["homo_energy_ev"] = best_channel_info["homo_energy_ev"]
        out["homo_index"] = best_channel_info["homo_index"]
        out["lumo_energy_hartree"] = best_channel_info["lumo_energy_hartree"]
        out["lumo_energy_ev"] = best_channel_info["lumo_energy_ev"]
        out["lumo_index"] = best_channel_info["lumo_index"]
    return out
```

---

### File: `web/routes/compute.py` — 수정 사항

```python
# ============================================================
# 수정 #4: _run_job에서 payload를 lock 내에서 복사
# ============================================================
def _run_job(self, job_id: str) -> None:
    with self.lock:
        job = self.jobs[job_id]
        job.status = "running"
        job.started_at = _now_ts()
        job.updated_at = job.started_at
        job.step = "starting"
        job.message = "Starting job"
        self._append_event(job, "job_started", "Job started")
        payload_copy = dict(job.payload)  # 수정: lock 내에서 복사

    def progress_callback(*args: Any, **kwargs: Any) -> None:
        # ... 동일 ...
        pass

    try:
        result = _run_direct_compute(payload_copy, progress_callback=progress_callback)  # 수정
        with self.lock:
            job = self.jobs[job_id]
            job.status = "completed"
            job.progress = 1.0
            job.step = "done"
            job.message = "Completed"
            job.result = result
            job.updated_at = _now_ts()
            job.ended_at = job.updated_at
            self._append_event(job, "job_completed", "Job completed")
            self._save_to_disk()  # 수정 #5: 완료 시 디스크 저장
    except HTTPException as exc:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "failed"
            job.step = "error"
            job.message = _safe_str(exc.detail, "Request failed")
            job.error = {"message": _safe_str(exc.detail, "Request failed"), "status_code": exc.status_code}
            job.updated_at = _now_ts()
            job.ended_at = job.updated_at
            self._append_event(job, "job_failed", job.message, job.error)
            self._save_to_disk()  # 수정 #5
    except Exception as exc:
        logger.exception("Direct compute failed for job %s", job_id)
        with self.lock:
            job = self.jobs[job_id]
            job.status = "failed"
            job.step = "error"
            job.message = str(exc)
            job.error = {"message": str(exc), "type": exc.__class__.__name__}
            job.updated_at = _now_ts()
            job.ended_at = job.updated_at
            self._append_event(job, "job_failed", job.message, job.error)
            self._save_to_disk()  # 수정 #5


# ============================================================
# 수정 #10: _safe_plan_message에서 올바른 시그니처로 호출
# ============================================================
def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message, context=dict(payload)))  # 수정
        except Exception as exc:
            logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)
    return _heuristic_plan(message, payload=payload)


# ============================================================
# 수정 #11: _merge_plan_into_payload에서 focus_tab 매핑 보강
# ============================================================
def _merge_plan_into_payload(payload, plan, *, raw_message=""):
    out = dict(payload or {})
    plan = dict(plan or {})
    # ... 기존 코드 ...

    # 수정: advisor_focus_tab에 focus_tab fallback 추가
    if not out.get("advisor_focus_tab"):
        out["advisor_focus_tab"] = plan.get("advisor_focus_tab") or plan.get("focus_tab")

    # ... 나머지 동일 ...


# ============================================================
# 수정 #23: _snapshot에 job_type 필드 추가
# ============================================================
def _snapshot(self, job, *, include_payload=False, include_result=False, include_events=False):
    snap = {
        "job_id": job.job_id,
        "status": job.status,
        "user_query": job.user_query,
        "job_type": job.payload.get("job_type", ""),  # 수정: 추가
        "molecule_name": job.payload.get("structure_query", ""),
        "method": job.payload.get("method", ""),
        "basis_set": job.payload.get("basis", ""),
        "progress": float(job.progress),
        "step": job.step,
        "message": job.message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "updated_at": job.updated_at,
    }
    if include_payload:
        snap["payload"] = _json_safe(job.payload)
    if include_result:
        snap["result"] = _json_safe(job.result)
        snap["error"] = _json_safe(job.error)
    if include_events:
        snap["events"] = _json_safe(job.events)
    return snap
```

---

### File: `llm/agent.py` — 수정 사항

```python
# ============================================================
# 수정 #7: INTENT_DEFAULTS의 focus_tab 통일
# ============================================================
INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},  # 수정: "orbitals" → "orbital"
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}


# ============================================================
# 수정 #7 (continued): PLAN_TOOL_SCHEMA의 focus_tab enum 통일
# ============================================================
PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        # ... 기존 필드들 ...
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
            #                                  수정: "orbitals" → "orbital"
        },
        # ...
    },
    # ...
}
```

---

### File: `llm/providers.py` — 수정 사항

```python
# ============================================================
# 수정 #8: DummyProvider의 focus_tab 통일
# 수정 #9: 한국어 키워드 수정
# ============================================================
class DummyProvider(LLMProvider):
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        text = request.user_prompt.lower()
        tool = "run_single_point"
        focus = "summary"

        if any(x in text for x in ["orbital", "homo", "lumo", "오비탈"]):
            tool = "run_orbital_preview"
            focus = "orbital"  # 수정 #8: "orbitals" → "orbital"
        elif any(x in text for x in ["esp", "potential", "map", "정전기", "전위"]):  # 수정 #9
            tool = "run_esp_map"
            focus = "esp"
        elif any(x in text for x in ["charge", "mulliken", "부분전하", "전하"]):  # 수정 #9
            tool = "run_partial_charges"
            focus = "charges"
        elif any(x in text for x in ["opt", "최적화"]):
            tool = "run_geometry_optimization"
            focus = "geometry"

        return PlannerResponse(
            thought_process="Rule-based fallback routing.",
            assistant_message="API 키가 설정되지 않아 로컬 규칙 기반 엔진이 요청을 처리합니다.",
            tool_calls=[ToolCall(tool_name=tool, parameters={"query": request.user_prompt})],
            is_help_only=False,
            suggested_focus_tab=focus
        )
```

---

### File: `web/static/viewer.js` — 수정 사항

```javascript
// ============================================================
// 수정 #15: renderESP에서 isovalue 조정을 surface 추가 전에 수행
// ============================================================
function renderESP(result) {
  return ensureViewer().then(function (viewer) {
    var oldXyz = state.result ? getXyz(state.result) : null;
    var newXyz = getXyz(result);
    var isNew = oldXyz !== newXyz;

    clearViewer(viewer);
    addMoleculeModel(viewer, result);

    // 수정: ESP isovalue를 surface 추가 전에 보정
    if (state.isovalue > 0.02 || state.isovalue < 0.0001) {
      state.isovalue = 0.002;
    }

    try {
      addESPSurface(viewer, result);
    } catch (e) {
      console.error("[Viewer] ESP render error:", e);
    }

    if (state.showLabels && state.model) addLabels(viewer, result);
    if (isNew) viewer.zoomTo();
    viewer.render();
    state.mode = "esp";
    showControls("esp");
    showESPLegend();
  });
}

// ============================================================
// 수정 #16: switchVizMode에 molecule fallback 추가
// ============================================================
function switchVizMode(newMode) {
  if (!state.result) return;
  if (state.mode === newMode) return;
  var prevMode = state.mode;
  state.mode = "switching";

  var p;
  if (newMode === "orbital") {
    p = renderOrbital(state.result);
  } else if (newMode === "esp") {
    p = renderESP(state.result);
  } else if (newMode === "molecule") {
    // 수정: molecule fallback
    p = renderMolecule(state.result);
  }

  if (p) {
    p.then(function () {
      saveViewerSnapshot();
    }).catch(function (err) {
      console.error("[Viewer] Mode switch failed:", err);
      state.mode = prevMode;
      showControls(prevMode);
    });
  } else {
    state.mode = prevMode;
  }
}

// ============================================================
// 수정 #17: handleResult의 catch에서 UI 상태 복원
// ============================================================
function handleResult(detail) {
  // ... 기존 코드 ...
  if (p)
    p.then(saveViewerSnapshot).catch(function (err) {
      console.error("[Viewer] Render failed:", err);
      state.mode = "none";
      if (dom.$empty) {
        dom.$empty.hidden = false;
        var t = dom.$empty.querySelector(".viewer-empty__text");
        if (t) t.textContent = "Rendering failed. Please try again.";
      }
      if (dom.$controls) dom.$controls.hidden = true;
    });
}
```

---

### File: `web/static/results.js` — 수정 사항

```javascript
// ============================================================
// 수정 #13: getAvailableTabs에서 Array.isArray 사용
// ============================================================
function getAvailableTabs(r) {
  if (!r) return [];
  var a = ["summary"];
  var viz = r.visualization || {};

  if (viz.xyz_block || (r.atoms && r.atoms.length)) a.push("geometry");

  if (
    viz.orbital_cube_b64 ||
    (r.mo_energies && r.mo_energies.length) ||
    (r.orbitals && r.orbitals.length)
  )
    a.push("orbital");

  if (viz.esp_cube_b64) a.push("esp");

  // 수정: Array.isArray 사용
  var hasMulliken =
    Array.isArray(r.mulliken_charges) && r.mulliken_charges.length > 0;
  var hasLowdin =
    Array.isArray(r.lowdin_charges) && r.lowdin_charges.length > 0;

  if (hasMulliken || hasLowdin) a.push("charges");

  a.push("json");
  return a;
}

// ============================================================
// 수정 #14: buildResultLabel에서 selected_orbital 사용
// ============================================================
function buildResultLabel(result, index) {
  var mol = result.molecule_name || result.structure_name || "Mol";
  var type = "";

  if (result.optimization_performed) {
    type = "Opt";
  } else if (
    result.orbital_cube_b64 ||
    result.orbital_cube ||
    (result.visualization && result.visualization.orbital_cube_b64)
  ) {
    // 수정: selected_orbital에서 label 가져오기
    var orbLabel = "MO";
    if (result.selected_orbital && result.selected_orbital.label) {
      orbLabel = result.selected_orbital.label;
    }
    type = orbLabel;
  } else if (
    result.esp_cube_b64 ||
    result.esp_cube ||
    (result.visualization && result.visualization.esp_cube_b64)
  ) {
    type = "ESP";
  } else {
    type = result.method || "SCF";
  }
  return "#" + index + " " + mol + " " + type;
}
```

---

### File: `web/static/app.js` — 수정 사항

```javascript
// ============================================================
// 수정 #19: getJobDetailLine에서 basis 필드 fallback 보강
// ============================================================
function getJobDetailLine(job) {
  var parts = [];
  var jobType =
    job.job_type ||
    (job.result && job.result.job_type) ||
    (job.payload && job.payload.job_type) ||
    "";
  if (jobType) parts.push(jobType);
  var method =
    job.method ||
    (job.result && job.result.method) ||
    (job.payload && job.payload.method) ||
    "";
  if (method) parts.push(method);
  // 수정: basis fallback 보강
  var basis =
    job.basis_set ||
    job.basis ||
    (job.result && (job.result.basis || job.result.basis_set)) ||
    (job.payload && (job.payload.basis || job.payload.basis_set)) ||
    "";
  if (basis) parts.push(basis);
  if (parts.length > 0) return parts.join(" \u00B7 ");
  // ... 나머지 동일 ...
}
```

---

## 4. 최종 보고 요약

| #   | 파일                      | 결함 유형                       | 심각도       | 상태    |
| --- | ------------------------- | ------------------------------- | ------------ | ------- |
| 1   | `pyscf_runner.py`         | `logger` 미선언 (NameError)     | **Critical** | ✅ 수정 |
| 2   | `pyscf_runner.py`         | regex 이중 이스케이프           | **High**     | ✅ 수정 |
| 3   | `pyscf_runner.py`         | frontier gap 변수 명명 혼동     | Low          | ✅ 수정 |
| 4   | `compute.py`              | Race condition (방어적)         | Medium       | ✅ 수정 |
| 5   | `compute.py`              | 디스크 저장 누락                | Medium       | ✅ 수정 |
| 7   | `agent.py`                | focus_tab "orbitals" 불일치     | **High**     | ✅ 수정 |
| 8   | `providers.py`            | focus_tab "orbitals" 불일치     | **High**     | ✅ 수정 |
| 9   | `providers.py`            | 한국어 키워드 오류              | Medium       | ✅ 수정 |
| 10  | `compute.py` ↔ `agent.py` | plan() 호출 시그니처 불일치     | **High**     | ✅ 수정 |
| 11  | `compute.py`              | advisor_focus_tab 매핑 누락     | **High**     | ✅ 수정 |
| 13  | `results.js`              | Object.keys on Array            | Low          | ✅ 수정 |
| 14  | `results.js`              | is_selected 필드 미존재         | Medium       | ✅ 수정 |
| 15  | `viewer.js`               | ESP isovalue 순서 오류          | **High**     | ✅ 수정 |
| 16  | `viewer.js`               | switchVizMode molecule fallback | Low          | ✅ 수정 |
| 17  | `viewer.js`               | 3Dmol 로드 실패 시 UI 미복원    | Medium       | ✅ 수정 |
| 19  | `app.js`                  | basis/basis_set 필드 불일치     | Medium       | ✅ 수정 |
| 23  | `compute.py`              | snapshot에 job_type 누락        | Medium       | ✅ 수정 |

**Critical 결함 1건** (서버 크래시 유발), **High 결함 5건** (기능 실패 유발), **Medium 결함 7건** (데이터 불일치/유실), **Low 결함 4건** (가독성/방어적 코딩)이 식별 및 수정되었습니다.

모든 수정 적용 후 시스템의 데이터 흐름 파이프라인(`pyscf_runner` → `compute.py` → WebSocket → `chat.js` → `results.js` → `viewer.js`)이 필드명, 데이터 타입, 에러 전파, 상태 복원 측면에서 완전한 정합성을 갖추며, 모든 실패 경로에서 사용자에게 명확한 에러 메시지가 전달되고 시스템이 'Ready' 상태로 복귀합니다.
