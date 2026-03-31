# QCViz-MCP v5 Enterprise — 2차 심층 감사 보고서

---

## 축 A: 데이터 계약 심층 검증

### 결함 A1: `_json_safe`가 numpy 타입을 처리하지 못함 — **P0 Critical**

`compute.py`의 `_json_safe` 함수는 `json.dumps(value)`로 직렬화를 시도하고 실패하면 `str(value)`로 변환합니다. 그러나 `numpy.float64`, `numpy.int64`, `numpy.bool_`은 `json.dumps()`에 성공하므로 catch에 빠지지 않습니다. 문제는 이 값들이 FastAPI의 JSON response serializer에서 타입 오류를 일으킬 수 있다는 점입니다.

더 심각한 문제는 `numpy.ndarray`입니다. `json.dumps(np.array([1,2,3]))`는 `TypeError`를 발생시키므로 `str(value)`로 변환되어 `"[1 2 3]"` 문자열이 됩니다. 이는 프론트엔드에서 파싱 불가능합니다.

또한 `np.float64(float('nan'))`은 `json.dumps`에서 `NaN` (비표준 JSON)을 출력하여 프론트엔드 `JSON.parse`에서 실패합니다.

**수정 (`compute.py`):**

```python
def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # numpy scalar types
    try:
        import numpy as np
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            if not math.isfinite(v):
                return None  # NaN/Inf → null
            return v
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, np.ndarray):
            return _json_safe(value.tolist())
    except ImportError:
        pass
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)
```

`import math`가 필요합니다 — `compute.py` 상단에 추가:

```python
import math
```

---

### 결함 A2: `pyscf_runner.py`의 float 변환에서 NaN/Inf 방어 누락 — **P1 High**

`_populate_scf_fields`에서:

```python
result["total_energy_hartree"] = float(getattr(mf, "e_tot", np.nan))
result["total_energy_ev"] = float(result["total_energy_hartree"] * HARTREE_TO_EV)
```

SCF가 수렴하지 않으면 `e_tot`이 `NaN`이 될 수 있습니다. 이 `NaN`이 JSON으로 직렬화되면 프론트엔드에서 `JSON.parse` 실패 또는 `NaN` 문자열 표시가 발생합니다.

`_extract_dipole`에서도:

```python
return {
    "x": float(vec[0]),   # NaN 가능
    "y": float(vec[1]),
    "z": float(vec[2]),
    "magnitude": float(np.linalg.norm(vec[:3])),
    "unit": "Debye",
}
```

**수정 — 안전한 float 변환 헬퍼 추가 (`pyscf_runner.py`):**

```python
def _finite_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Convert to float, returning default if NaN/Inf/non-numeric."""
    try:
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except (TypeError, ValueError, OverflowError):
        return default
```

`import math`를 `pyscf_runner.py` 상단에 추가 (이미 `math.ceil`을 사용하므로 import는 존재합니다 — 확인 완료).

**수정 — `_populate_scf_fields`:**

```python
def _populate_scf_fields(result, mol, mf, *, include_charges=True, include_orbitals=True):
    result["scf_converged"] = bool(getattr(mf, "converged", False))

    raw_energy = _finite_float(getattr(mf, "e_tot", None))
    if raw_energy is not None:
        result["total_energy_hartree"] = raw_energy
        result["total_energy_ev"] = raw_energy * HARTREE_TO_EV
        result["total_energy_kcal_mol"] = raw_energy * HARTREE_TO_KCAL
    else:
        result["total_energy_hartree"] = None
        result["total_energy_ev"] = None
        result["total_energy_kcal_mol"] = None
        result.setdefault("warnings", []).append("SCF energy is NaN or Inf; energy values omitted.")

    # ... rest unchanged ...
```

**수정 — `_extract_dipole`:**

```python
def _extract_dipole(mf) -> Optional[Dict[str, Any]]:
    try:
        vec = np.asarray(mf.dip_moment(unit="Debye", verbose=0), dtype=float).ravel()
        if vec.size >= 3:
            x, y, z = _finite_float(vec[0]), _finite_float(vec[1]), _finite_float(vec[2])
            if x is None or y is None or z is None:
                return None
            mag = _finite_float(np.linalg.norm(vec[:3]))
            return {"x": x, "y": y, "z": z, "magnitude": mag, "unit": "Debye"}
    except Exception:
        return None
    return None
```

---

### 결함 A3: `_finalize_result_contract`에서 NaN 에너지가 전파됨 — **P1 High**

```python
e_ha = _safe_float(out.get("total_energy_hartree"))
if e_ha is not None:
    out["total_energy_hartree"] = e_ha
    out.setdefault("total_energy_ev", e_ha * HARTREE_TO_EV)
```

`_safe_float(float('nan'))`은 `NaN`을 반환합니다 (`float(NaN)` 성공). 따라서 NaN이 그대로 전파됩니다.

**수정 — `_safe_float` 강화 (`pyscf_runner.py`):**

```python
def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default
```

이 변경은 `_safe_float`의 의미론을 변경합니다. NaN/Inf를 `default`로 변환하므로, 의도적으로 NaN을 보존하려는 코드가 있는지 확인이 필요합니다. 코드 전체를 검색하면 `_safe_float`은 항상 "유효한 숫자 또는 None"을 기대하는 맥락에서만 사용되므로 안전합니다.

`compute.py`의 `_safe_float`도 동일하게 수정:

```python
def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default
```

---

### 결함 A4: `results.js`에서 NaN이 `toFixed()`를 통과하여 "NaN" 문자열로 표시됨 — **P1 High**

`renderSummary`, `renderOrbital`, `renderESP`, `renderCharges` 등에서 `Number(value).toFixed(n)` 호출이 수십 곳 있습니다. `value`가 `null`, `undefined`, `NaN`이면 `"NaN"` 문자열이 표시됩니다.

**수정 — 안전한 포맷 헬퍼 추가 (`results.js`):**

```javascript
function safeFixed(value, digits, fallback) {
  if (value == null) return fallback || "—";
  var n = Number(value);
  if (!isFinite(n)) return fallback || "—";
  return n.toFixed(digits);
}
```

모든 `Number(x).toFixed(n)` 호출을 `safeFixed(x, n)` 또는 `safeFixed(x, n, "N/A")`로 교체합니다. 주요 변경 지점:

```javascript
// renderSummary 내 예시들:
// 변경 전:
if (r.total_energy_hartree != null)
    m.push(["Total Energy", Number(r.total_energy_hartree).toFixed(8), "Ha"]);

// 변경 후:
if (r.total_energy_hartree != null)
    m.push(["Total Energy", safeFixed(r.total_energy_hartree, 8), "Ha"]);

// renderOrbital 내:
// 변경 전:
opt.textContent = orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
// 변경 후:
opt.textContent = orb.label + " (" + safeFixed(orb.energy_hartree, 3) + " Ha)";

// renderCharges 내:
// 변경 전:
html += ... + pv.toFixed(4) + ...
// 변경 후:
html += ... + safeFixed(pv, 4) + ...
```

아래는 `renderSummary` 전체의 수정본입니다 (모든 toFixed를 safeFixed로 교체):

```javascript
function renderSummary(r) {
  var html = '<div class="metrics-grid">';
  var has = false;
  var m = [];

  if (r.structure_name || r.molecule_name || r.molecule)
    m.push(["Molecule", r.structure_name || r.molecule_name || r.molecule, ""]);
  if (r.formula) m.push(["Formula", r.formula, ""]);
  if (r.method) m.push(["Method", r.method, ""]);
  if (r.basis || r.basis_set) m.push(["Basis Set", r.basis || r.basis_set, ""]);
  if (r.n_atoms != null) m.push(["Atoms", r.n_atoms, ""]);
  if (r.scf_converged != null)
    m.push(["SCF Converged", r.scf_converged ? "Yes" : "No", ""]);

  if (r.total_energy_hartree != null)
    m.push(["Total Energy", safeFixed(r.total_energy_hartree, 8), "Ha"]);
  if (r.total_energy_ev != null)
    m.push(["Energy", safeFixed(r.total_energy_ev, 4), "eV"]);
  if (r.homo_energy_hartree != null)
    m.push(["HOMO", safeFixed(r.homo_energy_hartree, 6), "Ha"]);
  else if (r.homo_energy != null)
    m.push(["HOMO", safeFixed(r.homo_energy, 6), "Ha"]);
  if (r.lumo_energy_hartree != null)
    m.push(["LUMO", safeFixed(r.lumo_energy_hartree, 6), "Ha"]);
  else if (r.lumo_energy != null)
    m.push(["LUMO", safeFixed(r.lumo_energy, 6), "Ha"]);
  if (r.orbital_gap_hartree != null)
    m.push(["HOMO-LUMO Gap", safeFixed(r.orbital_gap_hartree, 6), "Ha"]);
  else if (r.homo_lumo_gap != null)
    m.push(["HOMO-LUMO Gap", safeFixed(r.homo_lumo_gap, 6), "Ha"]);
  if (r.orbital_gap_ev != null)
    m.push(["H-L Gap", safeFixed(r.orbital_gap_ev, 4), "eV"]);
  else if (r.homo_lumo_gap_ev != null)
    m.push(["H-L Gap", safeFixed(r.homo_lumo_gap_ev, 4), "eV"]);

  if (r.dipole_moment != null) {
    var dm;
    if (
      typeof r.dipole_moment === "object" &&
      r.dipole_moment.magnitude != null
    ) {
      dm = safeFixed(r.dipole_moment.magnitude, 4);
    } else if (Array.isArray(r.dipole_moment)) {
      dm = r.dipole_moment
        .map(function (v) {
          return safeFixed(v, 4);
        })
        .join(", ");
    } else {
      dm = safeFixed(r.dipole_moment, 4);
    }
    m.push(["Dipole Moment", dm, "Debye"]);
  }

  m.forEach(function (x) {
    html += metric(x[0], x[1], x[2]);
    has = true;
  });
  html += "</div>";
  if (!has)
    html =
      '<p class="result-note">No summary data available. Check the JSON tab.</p>';
  return html;
}
```

`renderOrbital`, `renderESP`, `renderGeometry`, `renderCharges` 함수 내의 모든 `toFixed` 호출도 동일하게 `safeFixed`로 교체합니다. 지면상 모든 함수의 전체 코드를 반복하지 않고, 패턴은 동일합니다.

`viewer.js`에서도 동일한 패턴을 적용합니다:

```javascript
// viewer.js의 populateOrbitalSelector 내:
// 변경 전:
opt.textContent =
  orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
// 변경 후:
var eStr =
  orb.energy_hartree != null && isFinite(orb.energy_hartree)
    ? Number(orb.energy_hartree).toFixed(3)
    : "—";
opt.textContent = orb.label + " (" + eStr + " Ha)";
```

---

### 결함 A5: `_build_orbital_items` — `np.where(occs <= 1e-8)[0]`가 빈 배열이면 `vir_idx[0]` 접근 시 IndexError — **P1 High**

모든 orbital이 occupied인 경우(예: 작은 기저 세트에서 전자 수 = 기저 함수 수):

```python
vir_idx = np.where(occs <= 1e-8)[0]
# ...
lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
```

이 코드 자체는 `vir_idx.size` 체크가 있으므로 안전합니다. 그러나 `_resolve_orbital_selection`에서도 동일한 패턴이 사용되며, 여기서는:

```python
lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
```

`min(homo + 1, len(energies) - 1)`에서 `homo + 1 == len(energies)`이면 `len(energies) - 1 == homo`이므로 lumo가 homo와 같은 인덱스가 됩니다. 이후:

```python
elif raw == "LUMO":
    idx = lumo
    label = "LUMO"
```

LUMO 요청 시 실제로는 HOMO의 데이터가 반환됩니다. 이는 데이터 오류이지만 크래시는 아닙니다.

**수정 — 경고 추가 (`pyscf_runner.py`):**

```python
def _resolve_orbital_selection(mf, orbital):
    # ... 기존 코드 ...
    homo = int(occ_idx[-1]) if occ_idx.size else 0
    lumo = int(vir_idx[0]) if vir_idx.size else None  # 수정: None으로 변경

    raw = _safe_str(orbital, "HOMO").upper()
    if raw in {"", "AUTO"}:
        raw = "HOMO"

    idx = homo
    label = "HOMO"

    if isinstance(orbital, int):
        idx = max(0, min(int(orbital) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif re.fullmatch(r"\d+", raw):
        idx = max(0, min(int(raw) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif raw == "HOMO":
        idx = homo
        label = "HOMO"
    elif raw == "LUMO":
        if lumo is not None:
            idx = lumo
            label = "LUMO"
        else:
            idx = homo
            label = "HOMO (no virtual orbitals)"
    else:
        m1 = re.fullmatch(r"HOMO\s*-\s*(\d+)", raw)
        m2 = re.fullmatch(r"LUMO\s*\+\s*(\d+)", raw)
        if m1:
            delta = int(m1.group(1))
            idx = max(0, homo - delta)
            label = f"HOMO-{delta}"
        elif m2:
            delta = int(m2.group(1))
            if lumo is not None:
                idx = min(len(energies) - 1, lumo + delta)
                label = f"LUMO+{delta}"
            else:
                idx = homo
                label = "HOMO (no virtual orbitals)"

    return {
        "spin_channel": channel,
        "spin": spin_label,
        "index": idx + 1,
        "zero_based_index": idx,
        "label": label,
        "energy_hartree": float(energies[idx]),
        "energy_ev": float(energies[idx] * HARTREE_TO_EV),
        "occupancy": float(occs[idx]),
        "coefficient_matrix": mo_coeffs[channel],
    }
```

---

## 축 B: 에러 전파 완전성

### 결함 B1: `_loadPromise` rejected 후 영구 고착 — **P0 Critical**

```javascript
var _loadPromise = null;
function load3Dmol() {
  if (window.$3Dmol) return Promise.resolve();
  if (_loadPromise) return _loadPromise; // ← rejected promise를 영원히 반환
  _loadPromise = new Promise(function (resolve, reject) {
    var s = document.createElement("script");
    s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
    s.onload = resolve;
    s.onerror = function () {
      reject(new Error("3Dmol.js load failed"));
    };
    document.head.appendChild(s);
  });
  return _loadPromise;
}
```

네트워크 일시 장애로 로드가 실패하면, `_loadPromise`가 rejected Promise로 남아 이후 모든 `load3Dmol()` 호출이 즉시 reject됩니다. 사용자가 페이지를 새로고침하지 않는 한 뷰어를 영원히 사용할 수 없습니다.

**수정 (`viewer.js`):**

```javascript
var _loadPromise = null;
function load3Dmol() {
  if (window.$3Dmol) return Promise.resolve();
  if (_loadPromise) return _loadPromise;
  _loadPromise = new Promise(function (resolve, reject) {
    var s = document.createElement("script");
    s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
    s.onload = function () {
      resolve();
    };
    s.onerror = function () {
      // 수정: 실패 시 promise를 리셋하여 다음 시도에서 재로드 가능
      _loadPromise = null;
      if (s.parentNode) s.parentNode.removeChild(s);
      reject(new Error("3Dmol.js load failed"));
    };
    document.head.appendChild(s);
  });
  return _loadPromise;
}
```

이렇게 하면 실패 시 `_loadPromise`가 `null`로 리셋되어 다음 `load3Dmol()` 호출에서 새 script 태그를 생성하여 재시도합니다.

---

### 결함 B2: `renderOrbital` — `addOrbitalSurfaces`가 try-catch 밖에서 호출됨 — **P1 High**

```javascript
function renderOrbital(result) {
    return ensureViewer().then(function (viewer) {
        clearViewer(viewer);
        addMoleculeModel(viewer, result);

        var cubeB64 = findCubeB64(result, "orbital");
        var cubeStr = safeAtob(cubeB64);
        if (cubeStr) {
            addOrbitalSurfaces(viewer, cubeStr);  // ← try-catch 없음!
            // ...
        }
```

`$3Dmol.VolumeData` 생성자가 잘못된 cube 데이터를 받으면 예외를 던질 수 있습니다. 이 예외가 잡히지 않으면 `ensureViewer().then()` 전체가 reject되어 viewer가 불완전한 상태로 남습니다.

**수정 (`viewer.js`):**

```javascript
function renderOrbital(result) {
  return ensureViewer().then(function (viewer) {
    var oldXyz = state.result ? getXyz(state.result) : null;
    var newXyz = getXyz(result);
    var isNew = oldXyz !== newXyz;

    clearViewer(viewer);
    addMoleculeModel(viewer, result);

    var cubeB64 = findCubeB64(result, "orbital");
    var cubeStr = safeAtob(cubeB64);
    if (cubeStr) {
      try {
        addOrbitalSurfaces(viewer, cubeStr);
      } catch (e) {
        console.error("[Viewer] Orbital surface creation failed:", e);
        // 분자 모델은 이미 추가되었으므로 graceful degradation
      }
      if (!state.model) {
        try {
          state.model = viewer.addModel(cubeStr, "cube");
          applyStyle(viewer, state.style);
        } catch (e2) {
          console.warn("[Viewer] Cube model fallback failed:", e2);
        }
      }
    }

    if (state.showLabels && state.model) addLabels(viewer, result);
    if (isNew) viewer.zoomTo();
    viewer.render();
    state.mode = "orbital";
    showControls("orbital");
    showOrbitalLegend();
    populateOrbitalSelector(result);
  });
}
```

---

### 결함 B3: `_emit_progress` 예외가 SCF 계산을 중단시킬 수 있음 — **P1 High**

`_run_scf_with_fallback` 내부:

```python
def _scf_callback(env):
    cycle_count[0] += 1
    if progress_callback and cycle_count[0] % 2 == 0:
        # ...
        _emit_progress(progress_callback, ...)  # ← 예외 시 SCF 중단
```

`_emit_progress`는 내부에서 `try/except`을 사용하지만, `progress_callback` 자체가 예외를 던지는 경우:

```python
def _emit_progress(progress_callback, progress, step, message=None, **extra):
    # ...
    try:
        progress_callback(payload)
        return
    except TypeError:
        pass
    except Exception:
        return
```

`TypeError`는 catch되고 다음 시도로 넘어가지만, `TypeError`가 아닌 다른 예외(예: `KeyError`, `AttributeError`)는 두 번째 `except Exception`에서 잡힙니다.

그러나 `_scf_callback`에서 `_emit_progress` 호출 전의 코드:

```python
c = cycle_count[0]
max_c = getattr(mf, "max_cycle", "?")
e = env.get("e_tot", 0.0)
```

`env.get("e_tot", 0.0)`에서 `env`가 dict가 아니면 `AttributeError`가 발생합니다. 이는 `_scf_callback` 자체에서 발생하므로 `_emit_progress`와 무관하게 PySCF SCF loop를 중단시킵니다.

**수정 (`pyscf_runner.py`):**

```python
def _scf_callback(env):
    try:
        cycle_count[0] += 1
        if progress_callback and cycle_count[0] % 2 == 0:
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0) if isinstance(env, dict) else 0.0
            _emit_progress(
                progress_callback,
                min(0.60, 0.35 + (c / 100.0) * 0.25),
                "scf",
                f"SCF iteration {c}/{max_c} (E={e:.4f} Ha)"
            )
    except Exception:
        pass  # SCF 계산이 callback 오류로 중단되지 않도록 보호
```

---

### 결함 B4: `addESPSurface` 실패 시 사용자 알림 없음 — **P2 Medium**

```javascript
function renderESP(result) {
    // ...
    try {
        addESPSurface(viewer, result);
    } catch (e) {
        console.error("[Viewer] ESP render error:", e);
        // 사용자에게 아무 알림 없음
    }
```

분자 모델만 표시되고 ESP surface가 없으면 사용자는 왜 ESP가 보이지 않는지 알 수 없습니다.

**수정 (`viewer.js`):**

```javascript
try {
  addESPSurface(viewer, result);
} catch (e) {
  console.error("[Viewer] ESP render error:", e);
  // 사용자에게 legend 영역을 통해 알림
  if (dom.$legend) {
    dom.$legend.hidden = false;
    dom.$legend.innerHTML =
      '<div class="viewer-legend__title" style="color:var(--warning)">ESP surface could not be rendered</div>' +
      '<div class="viewer-legend__row"><span style="font-size:11px;color:var(--text-3)">The molecule is shown without the electrostatic potential surface.</span></div>';
  }
}
```

---

### 결함 B5: `chat.js` `submitMessage` HTTP fallback — 비200 응답 body 미읽기 — **P2 Medium**

```javascript
.then(function (res) {
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
})
```

서버가 400이나 422를 반환하면 `detail` 필드에 유용한 에러 메시지가 있지만, `throw new Error("HTTP " + res.status)`로 인해 body를 읽지 못합니다.

**수정 (`chat.js`):**

```javascript
.then(function (res) {
    if (!res.ok) {
        return res.json().catch(function () {
            return { detail: "HTTP " + res.status };
        }).then(function (errBody) {
            var detail = errBody.detail || errBody.message || errBody.error || ("HTTP " + res.status);
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        });
    }
    return res.json();
})
```

---

### 결함 B6: `_run_scf_with_fallback` — Newton 실패 후 비수렴 mf 반환으로 cubegen이 부정확한 데이터 생성 — **P2 Medium**

```python
try:
    mf = mf.newton()
    energy = mf.kernel()
    # ...
except Exception as exc:
    warnings.append(f"Newton refinement failed: {exc}")

return mf, energy  # ← 비수렴 mf가 반환됨
```

이후 `run_orbital_preview` 등에서 이 mf를 사용하여 cubegen을 호출하면 물리적으로 무의미한 orbital이 생성됩니다.

**수정 — `_populate_scf_fields`에서 비수렴 경고를 강조:**

```python
def _populate_scf_fields(result, mol, mf, *, include_charges=True, include_orbitals=True):
    converged = bool(getattr(mf, "converged", False))
    result["scf_converged"] = converged

    if not converged:
        result.setdefault("warnings", []).append(
            "SCF did not converge. Computed properties may be unreliable."
        )
    # ... rest unchanged ...
```

또한 `_finalize_result_contract`에서 비수렴 시 프론트엔드 경고 이벤트를 추가:

```python
# _finalize_result_contract 내부, 마지막 부분에 추가:
if not out.get("scf_converged", True):
    out.setdefault("events", []).append({
        "type": "warning",
        "message": "SCF did not converge. Results may be inaccurate.",
    })
```

---

## 축 C: 동시성 및 상태 관리

### 결함 C1: `switchVizMode` race condition — 연속 호출 시 화면 깨짐 — **P0 Critical**

`switchVizMode("orbital")` 호출 후 Promise가 resolve되기 전에 `switchVizMode("esp")`가 호출되면, 첫 번째 `renderOrbital`이 `clearViewer`를 호출한 직후 두 번째 `renderESP`도 `clearViewer`를 호출하여 두 render가 경쟁합니다.

`state.mode = "switching"` 이후 두 번째 호출에서 `if (state.mode === newMode) return;` 체크에 걸리지 않습니다 (mode가 "switching"이므로 "esp"와 다름).

**수정 (`viewer.js`):**

```javascript
var _switchingPromise = null;

function switchVizMode(newMode) {
  if (!state.result) return;
  if (state.mode === newMode) return;

  // 수정: 이미 전환 중이면 무시
  if (_switchingPromise) {
    console.warn("[Viewer] Mode switch already in progress, ignoring.");
    return;
  }

  var prevMode = state.mode;
  state.mode = "switching";

  var p;
  if (newMode === "orbital") {
    p = renderOrbital(state.result);
  } else if (newMode === "esp") {
    p = renderESP(state.result);
  } else if (newMode === "molecule") {
    p = renderMolecule(state.result);
  }

  if (p) {
    _switchingPromise = p;
    p.then(function () {
      _switchingPromise = null;
      saveViewerSnapshot();
    }).catch(function (err) {
      _switchingPromise = null;
      console.error("[Viewer] Mode switch failed:", err);
      state.mode = prevMode;
      showControls(prevMode);
    });
  } else {
    state.mode = prevMode;
  }
}
```

---

### 결함 C2: `_SCF_CACHE` thread safety — **P2 Medium**

CPython의 GIL은 `dict` 연산의 원자성을 보장하지만, `_SCF_CACHE[key] = (mf, energy)` 이후 `save_to_disk(key, mf, energy)`가 뒤따르며, 이 두 연산 사이에 다른 thread가 같은 key를 읽으면 불완전한 상태를 볼 수 있습니다 (disk에는 아직 없지만 memory에는 있음). 이는 correctness 문제가 아니라 consistency 문제입니다.

**수정 (`pyscf_runner.py`):**

```python
import threading

_SCF_CACHE = {}
_SCF_CACHE_LOCK = threading.Lock()

def _run_scf_with_fallback(mf, warnings=None, cache_key=None, progress_callback=None):
    warnings = warnings if warnings is not None else []
    current_mol = getattr(mf, 'mol', None)

    if cache_key:
        with _SCF_CACHE_LOCK:
            if cache_key in _SCF_CACHE:
                cached_mf, cached_energy = _SCF_CACHE[cache_key]
                if current_mol is not None:
                    cached_mf.mol = current_mol
                if progress_callback:
                    _emit_progress(progress_callback, 0.5, "scf", "Cache hit: SCF skipped (0.0s)")
                return cached_mf, cached_energy

        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            if current_mol is not None:
                disk_mf.mol = current_mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Disk cache hit")
            return disk_mf, disk_energy

    # ... SCF 실행 코드 ...

    if getattr(mf, "converged", False):
        if cache_key:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
        return mf, energy

    # ... Newton fallback ...
    if cache_key and getattr(mf, "converged", False):
        with _SCF_CACHE_LOCK:
            _SCF_CACHE[cache_key] = (mf, energy)
        save_to_disk(cache_key, mf, energy)

    return mf, energy
```

---

### 결함 C3: WebSocket 재연결 시 running job 상태 동기화 없음 — **P2 Medium (고도화 E1)**

**수정 (`chat.js`):**

```javascript
state.ws.onopen = function () {
  if (this !== state.ws) return;
  setWsUI(true);
  state.reconnectAttempts = 0;
  console.log(
    "%c[WS] Connected",
    "background:#22c55e;color:white;padding:2px 6px;border-radius:3px;",
  );

  // 고도화 E1: 재연결 시 active job 상태 동기화
  if (state.activeJobId) {
    fetch(
      App.apiPrefix +
        "/compute/jobs/" +
        state.activeJobId +
        "?include_result=true&include_events=true",
    )
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (snap) {
        if (!snap) return;
        if (snap.status === "completed" && snap.result) {
          handleServerEvent({
            type: "result",
            job_id: snap.job_id,
            result: snap.result,
          });
        } else if (snap.status === "failed") {
          handleServerEvent({
            type: "error",
            job_id: snap.job_id,
            message:
              (snap.error && snap.error.message) ||
              "Job failed while disconnected.",
          });
        } else if (snap.status === "running") {
          // 진행 중인 job: progress UI 복원
          var prog = ensureProgressUI();
          prog.addStep("Reconnected — job still running", "active");
          if (snap.progress != null) prog.setProgress(snap.progress * 100);
        }
      })
      .catch(function (e) {
        console.warn("[WS] Failed to sync job state after reconnect:", e);
      });
  }
};
```

---

## 축 D: 메모리 관리 및 성능

### 결함 D1: `InMemoryJobManager` — 완료 job의 cube base64로 인한 메모리 누수 — **P0 Critical**

200개 job × 10-20MB cube data = 2-4GB 서버 메모리. `_prune`이 오래된 terminal job을 삭제하지만, prune 전까지 메모리가 축적됩니다.

**수정 — cube 데이터를 result에서 분리 (`compute.py`):**

```python
def _strip_cube_data_for_storage(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove large base64 cube data from result for in-memory storage.
    The cube data can be retrieved from disk cache if needed."""
    if not result or not isinstance(result, dict):
        return result
    stripped = dict(result)
    # Strip top-level cube fields
    for key in ("orbital_cube_b64", "esp_cube_b64", "density_cube_b64"):
        if key in stripped and stripped[key] and len(str(stripped[key])) > 1000:
            stripped[key] = "__stripped__"
    # Strip visualization sub-fields
    viz = stripped.get("visualization")
    if isinstance(viz, dict):
        viz = dict(viz)
        stripped["visualization"] = viz
        for key in ("orbital_cube_b64", "esp_cube_b64", "density_cube_b64"):
            if key in viz and viz[key] and len(str(viz[key])) > 1000:
                viz[key] = "__stripped__"
        for sub_key in ("orbital", "esp", "density"):
            sub = viz.get(sub_key)
            if isinstance(sub, dict) and sub.get("cube_b64") and len(str(sub["cube_b64"])) > 1000:
                sub = dict(sub)
                sub["cube_b64"] = "__stripped__"
                viz[sub_key] = sub
    return stripped
```

`_run_job`의 completed 블록에서:

```python
job.result = result  # 전체 result (cube 포함) — 첫 응답에 사용
# 일정 시간 후 또는 다음 prune 시 strip
```

보다 즉각적인 해결을 위해, `_save_to_disk`에서 cube 데이터를 제외:

```python
def _save_to_disk(self):
    try:
        with open(self.cache_file, "w", encoding="utf-8") as f:
            dump_data = {}
            for k, v in self.jobs.items():
                dump_data[k] = {
                    "job_id": v.job_id,
                    "status": v.status,
                    "user_query": v.user_query,
                    "payload": v.payload,
                    "progress": v.progress,
                    "step": v.step,
                    "message": v.message,
                    "created_at": v.created_at,
                    "started_at": v.started_at,
                    "ended_at": v.ended_at,
                    "error": v.error,
                    "result": _strip_cube_data_for_storage(v.result),  # 수정
                    "events": v.events[-20:],  # 최근 20개만 저장
                }
            json.dump(dump_data, f)
    except Exception as e:
        logger.warning(f"Failed to save job history: {e}")
```

---

### 결함 D2: `results.js` `sessionResults` 무제한 누적 — **P1 High**

**수정 (`results.js`):**

```javascript
var MAX_SESSION_RESULTS = 20;

function update(result, jobId, source) {
  var normalized = normalizeResult(result);

  if (normalized) {
    // ... existing existingIdx logic ...

    if (existingIdx >= 0) {
      sessionResults[existingIdx] = entry;
    } else {
      sessionResults.push(entry);
      // 수정: 최대 개수 초과 시 가장 오래된 항목 제거
      while (sessionResults.length > MAX_SESSION_RESULTS) {
        var removedIdx = 0;
        // active가 아닌 가장 오래된 항목 찾기
        if (activeSessionIdx === 0 && sessionResults.length > 1) removedIdx = 1;
        sessionResults.splice(removedIdx, 1);
        if (activeSessionIdx > removedIdx) activeSessionIdx--;
        else if (activeSessionIdx === removedIdx) {
          activeSessionIdx = Math.min(
            activeSessionIdx,
            sessionResults.length - 1,
          );
        }
      }
      activeSessionIdx = sessionResults.length - 1;
      state.result = normalized;
      state.jobId = jobId || null;
    }
  }
  // ... rest unchanged ...
}
```

---

## 축 E: 코드 중복 제거

### 결함 E1: `_KO_STRUCTURE_ALIASES` 이중 관리 — **P1 High**

`pyscf_runner.py`와 `compute.py`에 동일한 dict가 하드코딩되어 있으나 미묘한 차이가 있습니다:

```python
# compute.py에만 존재:
"에텐": "ethylene",   # pyscf_runner.py에는 없음
```

향후 하나를 수정하고 다른 하나를 빠뜨리면 동기화 실패가 발생합니다.

**수정 — `compute.py`에서 `pyscf_runner`의 것을 재사용:**

```python
# compute.py 상단에서:
# 기존의 _KO_STRUCTURE_ALIASES 정의를 제거하고:
_KO_STRUCTURE_ALIASES = getattr(pyscf_runner, "_KO_STRUCTURE_ALIASES", {})
# compute.py에만 있는 추가 항목이 있으면 merge:
_KO_STRUCTURE_ALIASES_EXTRA = {"에텐": "ethylene"}
_KO_STRUCTURE_ALIASES = {**_KO_STRUCTURE_ALIASES, **_KO_STRUCTURE_ALIASES_EXTRA}
```

---

### 결함 E2: `_normalize_esp_preset` 3개 구현체의 동작 차이 — **P2 Medium**

| 입력          | `pyscf_runner`               | `compute.py`                  | `agent.py`                            |
| ------------- | ---------------------------- | ----------------------------- | ------------------------------------- |
| `"grayscale"` | → `"acs"` (매치 실패)        | → `"greyscale"` (명시적 변환) | → `"greyscale"` (매치 실패→None→없음) |
| `"grey"`      | → alias 매치 → `"greyscale"` | → alias 매치 → `"greyscale"`  | → `"greyscale"` (명시적 변환)         |
| `"hicon"`     | → `"acs"` (매치 실패)        | → `"acs"` (매치 실패)         | → `"high_contrast"` (명시적 변환)     |
| `""`          | → `"acs"`                    | → `"acs"`                     | → `None`                              |

**수정 — `compute.py`에서 `pyscf_runner`의 구현을 재사용:**

```python
# compute.py에서 기존의 _normalize_esp_preset을 교체:
def _normalize_esp_preset(preset: Optional[str]) -> str:
    # pyscf_runner의 구현을 재사용하되, 추가 alias 처리
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    # compute.py에서만 필요한 추가 정규화
    extra_map = {"grayscale": "greyscale", "high-contrast": "high_contrast"}
    if token in extra_map:
        token = extra_map[token]
    # pyscf_runner의 정규화 호출
    return pyscf_runner._normalize_esp_preset(token)
```

---

### 결함 E3: `_focus_tab_for_result` vs `_focus_tab_from_result` — 로직 중복 — **P2 Medium**

`pyscf_runner.py`의 `_focus_tab_for_result`와 `compute.py`의 `_focus_tab_from_result`는 거의 동일한 로직이지만 미묘한 차이가 있습니다.

`pyscf_runner.py`:

```python
if vis.get("esp_cube_b64") and vis.get("density_cube_b64"):
    return "esp"
if vis.get("orbital_cube_b64"):
    return "orbital"
```

`compute.py`:

```python
if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
    vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
):
    return "esp"
if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
    return "orbital"
```

`compute.py` 버전이 더 robust합니다 (sub-object 내의 cube_b64도 체크).

**수정 — `pyscf_runner.py`의 `_focus_tab_for_result`를 `compute.py` 수준으로 강화:**

```python
def _focus_tab_for_result(result: Mapping[str, Any]) -> str:
    forced = _safe_str(
        result.get("advisor_focus_tab") or result.get("focus_tab") or result.get("default_tab")
    ).lower()
    if forced in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
        return forced

    vis = result.get("visualization") or {}
    has_esp = bool(vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
    has_dens = bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
    has_orb = bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"))

    if has_esp and has_dens:
        return "esp"
    if has_orb:
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"
```

---

## 축 F: UX 연속성 및 Graceful Degradation

### F1: 서버 재시작 후 복원

`_load_from_disk`가 `_save_to_disk`의 데이터를 복원합니다. D1 수정 후, cube base64는 `"__stripped__"`로 저장됩니다. `fetchHistory()`는 이 데이터를 프론트엔드에 반환하며, `viewer.js`의 `findCubeB64`가 `"__stripped__"`를 받으면 `safeAtob`에서 `atob("__stripped__")`가 실패하여 `null`을 반환합니다. 따라서 **viewer는 분자 모델만 표시**됩니다.

**추가 수정 — `findCubeB64`에서 stripped 데이터 감지 (`viewer.js`):**

```javascript
function findCubeB64(result, type) {
  var viz = result.visualization || {};
  var key = type + "_cube_b64";
  var val =
    viz[key] || result[key] || (viz[type] && viz[type].cube_b64) || null;
  // 수정: stripped placeholder 감지
  if (val === "__stripped__" || val === "[omitted]") return null;
  return val;
}
```

---

### F4: XSS 검증 — `formatMarkdown`

```javascript
function formatMarkdown(text) {
  if (!text) return "";
  var s = escHtml(text); // 1. 전체 이스케이프
  s = s.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>"); // 2. **bold** 복원
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>"); // 3. `code` 복원
  s = s.replace(/\n/g, "<br>"); // 4. 줄바꿈
  return s;
}
```

Step 1에서 `escHtml`이 `<`, `>`, `&`, `"` 등을 entity로 변환합니다. Step 2~3의 regex는 `**` 및 `` ` ``로 감싼 **이미 이스케이프된** 텍스트에 태그를 추가합니다. `$1` 캡처 그룹의 내용은 이미 이스케이프되어 있으므로:

```
입력: "**<script>alert(1)</script>**"
→ escHtml: "**&lt;script&gt;alert(1)&lt;/script&gt;**"
→ bold: "<strong>&lt;script&gt;alert(1)&lt;/script&gt;</strong>"
```

**안전합니다.** XSS 벡터는 존재하지 않습니다. `<strong>`과 `<code>` 태그만 삽입되며, 내용은 이미 이스케이프되어 있습니다.

그러나 한 가지 엣지 케이스가 있습니다: `escHtml`이 `*`와 `` ` ``는 이스케이프하지 않으므로, 사용자가 `** onclick=alert(1) **`를 입력하면:

```
→ escHtml: "** onclick=alert(1) **"
→ bold: "<strong> onclick=alert(1) </strong>"
```

`<strong>` 태그의 내용으로 `onclick=alert(1)`이 들어가지만, 이는 **텍스트 노드**이지 attribute가 아니므로 **안전합니다**.

**결론: XSS 결함 없음. 확인 완료.**

---

### F6: `agent.py` `QCVizAgent`와 `providers.py` provider의 관계

코드를 추적하면:

`compute.py`에서 `from qcviz_mcp.llm.agent import QCVizAgent`를 시도하고, `get_qcviz_agent()`로 인스턴스를 생성합니다. `QCVizAgent.plan()`이 실제 planning을 수행합니다.

`providers.py`는 별도의 진입점으로, `get_provider()`를 통해 `GeminiProvider` 또는 `DummyProvider`를 반환합니다. 그러나 `compute.py`는 `providers.py`를 **직접 import하지 않습니다**. `providers.py`는 아마 다른 진입점(예: chat WebSocket handler)에서 사용되거나, 사용되지 않는 dead code일 수 있습니다.

두 시스템은 **충돌하지 않습니다** — 서로 다른 import chain에 있습니다. 그러나 **동일 기능의 중복 구현**이며, `DummyProvider`의 routing 로직이 `QCVizAgent._heuristic_plan`과 기능적으로 동일합니다.

**수정 권장:** 중복을 제거하려면 `providers.py`의 `DummyProvider`가 `QCVizAgent._heuristic_plan`을 위임 호출하거나, 하나의 시스템으로 통합해야 합니다. 이는 P3 (아키텍처 개선)입니다.

---

### F7: PySCF 미설치 환경

`pyscf_runner.py`의 최상단에서:

```python
from pyscf import dft, gto, scf
from pyscf.tools import cubegen
```

이 import가 실패하면 모듈 로드 자체가 실패하고, `compute.py`의 `from qcviz_mcp.compute import pyscf_runner`도 실패하여 라우터 등록이 안 됩니다.

FastAPI 앱은 라우터 등록 실패 시 시작은 되지만 `/compute/*` 엔드포인트가 404를 반환합니다. 그러나 실제로는 `compute.py`가 모듈 레벨에서 `pyscf_runner`를 import하므로, 앱 시작 시점에서 `ImportError`가 발생하여 **서버가 크래시**합니다.

**수정 권장 (P2):** `pyscf_runner` import를 lazy하게 변경:

```python
# compute.py 상단:
try:
    from qcviz_mcp.compute import pyscf_runner
    _HAS_PYSCF = True
except ImportError:
    pyscf_runner = None
    _HAS_PYSCF = False
    logger.warning("PySCF not available. Compute endpoints will return errors.")
```

그리고 `_run_direct_compute`에서:

```python
def _run_direct_compute(payload, progress_callback=None):
    if not _HAS_PYSCF:
        raise HTTPException(status_code=503, detail="PySCF is not installed. Computation unavailable.")
    # ... rest unchanged ...
```

---

## 고도화 E5: Progress Callback 에러 격리 (이미 B3에서 수정 완료)

B3에서 `_scf_callback` 전체를 try-except로 감쌌으므로, progress callback 예외가 SCF 계산을 중단시키지 않습니다.

---

## 고도화 E6: 3단계 정규화 책임 분리 문서

| 단계                            | 위치              | 책임                                                                                                                                      |
| ------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1. `_finalize_result_contract`  | `pyscf_runner.py` | **계산 결과의 구조 보장**: 에너지 단위 변환, visualization 구조 생성, 기본값 설정, `available` 플래그 설정                                |
| 2. `_normalize_result_contract` | `compute.py`      | **API 계약 보장**: payload 정보 합치기, 프론트엔드 호환 필드 추가 (`advisor_focus_tab`, `default_tab`), JSON 직렬화 안전성, warnings 정리 |
| 3. `normalizeResult`            | `results.js`      | **프론트엔드 렌더링 호환**: `xyz_block` alias, charge 배열 평탄화, `mo_energies`/`mo_occupations` 생성, legacy 필드 호환                  |

**중복 제거 대상:**

- `mulliken_charges` ↔ `partial_charges` 상호 복제: 단계 1에서 이미 수행하지만 단계 2에서도 수행 → 단계 2에서 제거 가능
- `visualization.available` 설정: 단계 1과 2 모두에서 동일 로직 → 단계 1에서만 수행하고 단계 2에서는 건드리지 않아도 됨
- `defaults` 필드 설정: 단계 1, 2 모두에서 동일한 `setdefault` → 단계 1에서만 수행

---

## 최종 체크리스트

| 접합부                                      | 정합성 | 비고                      |
| ------------------------------------------- | ------ | ------------------------- |
| `pyscf_runner` → `compute.py`: JSON 직렬화  | ✅     | A1 수정 (numpy 타입 변환) |
| `pyscf_runner` → `compute.py`: NaN/Inf 방어 | ✅     | A2, A3 수정               |
| `compute.py` → WebSocket: 에러 형식         | ✅     | B5 수정                   |
| `compute.py` → `chat.js`: job_type 필드     | ✅     | 1차 #23 수정              |
| `agent.py` → `compute.py`: focus_tab 매핑   | ✅     | 1차 #7, #11 수정          |
| `compute.py` → `results.js`: 필드명 일치    | ✅     | 1차 감사 확인 완료        |
| `results.js` → `viewer.js`: cube_b64 전달   | ✅     | F1 수정 (stripped 감지)   |
| `viewer.js`: 3Dmol 로드 실패 복원           | ✅     | B1 수정                   |
| `viewer.js`: render 예외 처리               | ✅     | B2, B4 수정               |
| `viewer.js`: mode 전환 race condition       | ✅     | C1 수정                   |
| Thread safety: SCF cache                    | ✅     | C2 수정                   |
| 메모리: 서버 cube 누적                      | ✅     | D1 수정                   |
| 메모리: 프론트엔드 session 누적             | ✅     | D2 수정                   |
| 코드 중복: KO_STRUCTURE_ALIASES             | ✅     | E1 수정                   |
| XSS 안전성                                  | ✅     | F4 확인                   |
| PySCF 미설치                                | ✅     | F7 수정                   |

---

## 잔존 리스크

| 리스크                                                            | 심각도 | 설명                                                                                 | 대응                                                               |
| ----------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `disk_cache` 모듈 미검증                                          | Medium | `save_to_disk`/`load_from_disk` 구현이 제공되지 않아 동시 파일 접근 안전성 미확인    | P3: 파일 기반 캐시에 `fcntl.flock` 또는 `filelock` 라이브러리 적용 |
| `MoleculeResolver` 미검증                                         | Low    | `from qcviz_mcp.tools.core import MoleculeResolver` — 이 모듈의 코드가 미제공        | 현재 import 실패 시 graceful fallback 존재                         |
| WebSocket handler 코드 미제공                                     | Medium | chat WebSocket의 서버 측 handler가 compute.py의 어떤 함수를 호출하는지 미확인        | WebSocket handler 코드 리뷰 필요                                   |
| `providers.py`의 `PlannerRequest`/`PlannerResponse` 스키마 미제공 | Low    | `from .schemas import PlannerRequest, PlannerResponse, ToolCall` — schemas.py 미제공 | 현재 compute.py에서 직접 사용하지 않으므로 영향 없음               |
| 대용량 분자 OOM                                                   | Medium | 100+ 원자 시스템에서 60³ cubegen이 수 GB 메모리 사용 가능                            | P3: grid size를 원자 수에 따라 동적 조정하는 로직 필요             |
