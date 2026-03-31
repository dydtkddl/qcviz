# QCViz-MCP v5 고도화: Color Scheme 적용 버그 수정 및 Charge 시각화 강화

현재 3D 뷰어와 결과 패널에서 다음 세 가지 문제를 해결하고 고도화해야 합니다. 아래의 프론트엔드 코드 전체 컨텍스트를 분석하여 수정된 코드를 작성해 주세요.

---

## 🛑 요구사항 1: Color Scheme 변경 시 뷰어 미반영 버그 수정
**문제 상황:** 하단의 `selectColorScheme`에서 "Jmol"이나 "Viridis" 등 다른 색상 스킴을 골라도 3D 뷰어의 오비탈이나 ESP 맵 색상이 바뀌지 않고 예전 색상으로 고정되어 있습니다.
**원인 추정:** `viewer.js`의 `selectColorScheme` change 이벤트 리스너에서 `state.mode = "none"; switchVizMode(currentMode);`를 호출하고 있으나, 내부의 `tryRenderCachedOrbital`이나 `renderESP`가 제대로 갱신된 `getCurrentColorScheme()` 값을 적용하지 못하거나 렌더링 파이프라인(락 등)에 갇혀있을 가능성이 큽니다.
**지시:** `viewer.js`를 분석하여 Color Scheme을 변경했을 때 즉각적으로 표면 색상이 바뀌도록 렌더링 갱신 로직을 완벽하게 수정하세요.

## 🛑 요구사항 2: 원자 라벨(Atom Label)에 전하량별(+/-) 색상 부여
**문제 상황:** 현재 3D 뷰어에서 Labels(원자 기호 + 전하량)를 켜면 모두 동일한 배경색(흑/백)으로 나옵니다.
**지시:** `viewer.js`의 `addLabels(viewer, result)` 함수를 수정하여, 해당 원자의 전하(Charge) 값이 양수(+)이면 파란색 계열, 음수(-)이면 빨간색 계열의 배경색이나 글자색이 적용되도록 시각적 직관성을 더해주세요. 중성이면 기존 색상을 유지합니다.

## 🛑 요구사항 3: Charges 탭 버터플라이 차트(Butterfly Chart) 시각화
**문제 상황:** `results.js`의 `renderCharges(r)` 함수가 단순히 표(Table) 형태로만 전하량을 나열하고 있어 데이터의 직관적인 비교가 어렵습니다.
**지시:** `results.js`의 `renderCharges` 함수를 전면 개편하여, 0을 기준으로 양수(+)는 오른쪽으로 뻗어나가는 파란색 막대, 음수(-)는 왼쪽으로 뻗어나가는 빨간색 막대를 가지는 아름다운 **수평 버터플라이 차트(Horizontal Bar / Butterfly Chart)**를 순수 HTML/CSS (div 태그 활용)로 구현해 주세요. `style.css`에 필요한 스타일도 추가하세요.

---

## 📄 대상 소스 코드

### 1. `viewer.js`
```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — 3D Viewer Module
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;


  var state = {
    trajectoryFrames: [],
    trajectoryPlaying: false,
    trajectoryFrame: 0,
    trajectoryTimer: null,

    viewer: null, model: null, ready: false,
    mode: "none", style: "stick", isovalue: 0.03, opacity: 0.75,
    showLabels: true, result: null, jobId: null, selectedOrbitalIndex: null,
  };

  var $viewerDiv = document.getElementById("viewer3d");
  var $empty = document.getElementById("viewerEmpty");
  var $controls = document.getElementById("viewerControls");
  var $legend = document.getElementById("viewerLegend");
  var $btnReset = document.getElementById("btnViewerReset");
  var $btnScreenshot = document.getElementById("btnViewerScreenshot");
  var $btnFullscreen = document.getElementById("btnViewerFullscreen");
  var $segStyle = document.getElementById("segStyle");
  var $grpOrbital = document.getElementById("grpOrbital");
  var $grpOpacity = document.getElementById("grpOpacity");
  var $grpOrbitalSelect = document.getElementById("grpOrbitalSelect");
  var $selectOrbital = document.getElementById("selectOrbital");
  var $sliderIso = document.getElementById("sliderIsovalue");
  var $lblIso = document.getElementById("lblIsovalue");
  var $sliderOp = document.getElementById("sliderOpacity");
  var $lblOp = document.getElementById("lblOpacity");
  var $btnLabels = document.getElementById("btnToggleLabels");

  /* ─── 3Dmol Loader ─── */
  var _loadPromise = null;
  function load3Dmol() {
    if (window.$3Dmol) return Promise.resolve();
    if (_loadPromise) return _loadPromise;
    _loadPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
      s.onload = resolve;
      s.onerror = function () { reject(new Error("3Dmol.js load failed")); };
      document.head.appendChild(s);
    });
    return _loadPromise;
  }

  function ensureViewer() {
    if (state.viewer && state.ready) return Promise.resolve(state.viewer);
    return load3Dmol().then(function () {
      if (!state.viewer) {
        var isDark = document.body.classList.contains("dark") || window.matchMedia("(prefers-color-scheme: dark)").matches;
        state.viewer = window.$3Dmol.createViewer($viewerDiv, {
          backgroundColor: isDark ? "black" : "white",
          antialias: true,
        });
        
        try {
          var canvas = $viewerDiv.querySelector("canvas");
          if (canvas) {
            canvas.style.backgroundColor = "transparent";
          }
        } catch (_) {}
        
        state.ready = true;
        updateViewerBg();
      }
      return state.viewer;
    }).catch(function (err) {
      if ($empty) {
        $empty.hidden = false;
        var t = $empty.querySelector(".viewer-empty__text");
        if (t) t.textContent = "Failed to load 3Dmol.js — check your network connection.";
      }
      throw err;
    });
  }

  function updateViewerBg() {
    if (!state.viewer) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    state.viewer.setBackgroundColor(isDark ? 0x0c0c0f : 0xfafafa, 1.0);
  }

  /* ─── Helpers ─── */
  
  var COLOR_SCHEMES = {
    classic: { label: "Classic (Blue/Red)", orbPositive: "#3b82f6", orbNegative: "#ef4444", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
    jmol: { label: "Jmol", orbPositive: "#1e40af", orbNegative: "#dc2626", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
    rwb: { label: "RWB (Red-White-Blue)", orbPositive: "#2563eb", orbNegative: "#dc2626", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
    bwr: { label: "BWR (Blue-White-Red)", orbPositive: "#dc2626", orbNegative: "#2563eb", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(max, min); } },
    spectral: { label: "Spectral", orbPositive: "#2b83ba", orbNegative: "#d7191c", espGradient: function (min, max) { return new window.$3Dmol.Gradient.Sinebow(min, max); } },
    viridis: { label: "Viridis", orbPositive: "#21918c", orbNegative: "#fde725", espGradient: function (min, max) { return new window.$3Dmol.Gradient.ROYGB(min, max); } },
    inferno: { label: "Inferno", orbPositive: "#fcffa4", orbNegative: "#420a68", espGradient: function (min, max) { return new window.$3Dmol.Gradient.ROYGB(min, max); } },
    coolwarm: { label: "Cool-Warm", orbPositive: "#4575b4", orbNegative: "#d73027", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
    purplegreen: { label: "Purple-Green", orbPositive: "#1b7837", orbNegative: "#762a83", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
    greyscale: { label: "Greyscale", orbPositive: "#f0f0f0", orbNegative: "#404040", espGradient: function (min, max) { return new window.$3Dmol.Gradient.RWB(min, max); } },
  };

  function getCurrentColorScheme() {
    return COLOR_SCHEMES[state.colorScheme] || COLOR_SCHEMES.classic;
  }

  function updateSchemePreview() {
    var scheme = getCurrentColorScheme();
    var $preview = document.getElementById("schemePreview");
    if (!$preview) return;
    var $pos = $preview.querySelector(".swatch-pos");
    var $neg = $preview.querySelector(".swatch-neg");
    if ($pos) $pos.style.backgroundColor = scheme.orbPositive;
    if ($neg) $neg.style.backgroundColor = scheme.orbNegative;
  }
  
  
  // Fallback to dismiss loader if something hangs
  setTimeout(dismissLoader, 3000);

  function dismissLoader() {
    var $loader = document.getElementById("appLoader");
    if (!$loader) return;
    $loader.classList.add("fade-out");
    setTimeout(function () {
      if ($loader.parentNode) $loader.parentNode.removeChild($loader);
    }, 600);
  }

  function buildXyzFromAtoms(atoms) {
    if (!atoms || !atoms.length) return null;
    var lines = [String(atoms.length), "QCViz"];
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "X";
      var x = Number(a.x != null ? a.x : (a[1] || 0)).toFixed(6);
      var y = Number(a.y != null ? a.y : (a[2] || 0)).toFixed(6);
      var z = Number(a.z != null ? a.z : (a[3] || 0)).toFixed(6);
      lines.push(el + " " + x + " " + y + " " + z);
    });
    return lines.join("\n");
  }

  function getXyz(result) {
  var viz = result.visualization || {};
  /* Backend sends viz.xyz and viz.molecule_xyz, NOT viz.xyz_block */
  var xyz =
    viz.xyz ||
    viz.molecule_xyz ||
    viz.xyz_block ||
    result.xyz_block ||
    result.xyz ||
    null;
  if (!xyz && result.atoms && result.atoms.length) {
    xyz = buildXyzFromAtoms(result.atoms);
  }
  return xyz;
}

  function applyStyle(viewer, style) {
    switch (style) {
      case "stick":
        viewer.setStyle({}, {
          stick: { radius: 0.14, colorscheme: "Jmol" },
          sphere: { scale: 0.25, colorscheme: "Jmol" },
        });
        break;
      case "sphere":
        viewer.setStyle({}, {
          sphere: { scale: 0.6, colorscheme: "Jmol" },
        });
        break;
      case "line":
        viewer.setStyle({}, {
          line: { colorscheme: "Jmol" },
        });
        break;
    }
  }

  function addLabels(viewer, result) {
    var atoms = result.atoms || [];
    if (!atoms.length) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "";
      if (!el) return;
      viewer.addLabel(el, {
        position: {
          x: a.x != null ? a.x : (a[1] || 0),
          y: a.y != null ? a.y : (a[2] || 0),
          z: a.z != null ? a.z : (a[3] || 0),
        },
        fontSize: 11,
        fontColor: isDark ? "white" : "#333",
        backgroundColor: isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.7)",
        borderColor: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)",
        borderThickness: 1,
        backgroundOpacity: 0.6,
        alignment: "center",
        showBackground: true,
      });
    });
  }

  /* 라벨 새로고침 — On/Off 토글과 테마 변경 시 호출 */
  function refreshLabels() {
    if (!state.viewer) return;
    state.viewer.removeAllLabels();
    if (state.showLabels && state.result) {
      addLabels(state.viewer, state.result);
    }
    state.viewer.render();
  }

  /* ─── Clear / Add Model ─── */
  function clearViewer(viewer) {
    viewer.removeAllModels();
    viewer.removeAllSurfaces();
    viewer.removeAllLabels();
    viewer.removeAllShapes();
    state.model = null;
  }

  function addMoleculeModel(viewer, result) {
    var xyz = getXyz(result);
    if (xyz) {
      state.model = viewer.addModel(xyz, "xyz");
      applyStyle(viewer, state.style);
      return true;
    }
    return false;
  }

  /* ─── Render Molecule ─── */
  function renderMolecule(result) {
    return ensureViewer().then(function (viewer) {
      clearViewer(viewer);
      addMoleculeModel(viewer, result);
      if (state.showLabels) addLabels(viewer, result);
      viewer.zoomTo();
      viewer.render();
      state.mode = "molecule";
      showControls("molecule");
      hideLegend();
    });
  }

  /* ─── Render Orbital ─── */
  function renderOrbital(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.model ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNewMolecule = oldXyz !== newXyz;

      clearViewer(viewer);

      /* 분자 모델 먼저 추가 */
      addMoleculeModel(viewer, result);

      var viz = result.visualization || {};
      var cubeB64 = viz.orbital_cube_b64 || result.orbital_cube_b64 || null;

      if (cubeB64) {
        try {
          var cubeData = atob(cubeB64);
          var vol = new window.$3Dmol.VolumeData(cubeData, "cube");

          /* Positive lobe — indigo */
          viewer.addIsosurface(vol, {
            isoval: state.isovalue,
            color: getCurrentColorScheme().orbPositive,
            alpha: state.opacity,
            smoothness: 3,
            wireframe: false,
          });

          /* Negative lobe — amber */
          viewer.addIsosurface(vol, {
            isoval: -state.isovalue,
            color: "#f59e0b",
            alpha: state.opacity,
            smoothness: 3,
            wireframe: false,
          });

          /* 분자 모델이 없었다면 큐브 파일에서 추출 */
          if (!state.model) {
            state.model = viewer.addModel(cubeData, "cube");
            applyStyle(viewer, state.style);
          }
        } catch (e) {
          console.error("[Viewer] Orbital render error:", e);
        }
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNewMolecule) {
          viewer.zoomTo();
      }
      viewer.render();
      state.mode = "orbital";
      showControls("orbital");
      showOrbitalLegend();
      populateOrbitalSelector(result);
    });
  }

  /* ─── Render ESP ─── */
  function renderESP(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.model ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNewMolecule = oldXyz !== newXyz;

      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      var viz = result.visualization || {};
      var densB64 = viz.density_cube_b64 || result.density_cube_b64 || null;
      var espB64 = viz.esp_cube_b64 || result.esp_cube_b64 || null;

      try {
        if (densB64 && espB64) {
          var densVol = new window.$3Dmol.VolumeData(atob(densB64), "cube");
          var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          var range = result.esp_auto_range_au || 0.05;
          viewer.addIsosurface(densVol, {
            isoval: state.isovalue,
            color: "white",
            alpha: state.opacity,
            smoothness: 1,
            voldata: espVol,
            volscheme: getCurrentColorScheme().espGradient(-range, range)
          });
        } else if (espB64) {
          var espVol2 = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          viewer.addIsosurface(espVol2, {
            isoval: state.isovalue,
            volscheme: getCurrentColorScheme().espGradient(-range, range),
            alpha: state.opacity,
            smoothness: 3,
          });
        }
      } catch (e) {
        console.error("[Viewer] ESP render error:", e);
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNewMolecule) {
          viewer.zoomTo();
      }
      viewer.render();
      state.mode = "esp";
      showControls("esp");
      showESPLegend();
    });
  }

  function handleResultSwitched(data) {
    var result = data.result;
    if (!result) return;
    var xyz = result.xyz || result.molecule_xyz || "";
    if (xyz) loadMoleculeXyz(xyz);

    var hasOrb = !!(result.orbital_cube_b64 || result.orbital_cube);
    var hasEsp = !!(result.esp_cube_b64 || result.esp_cube);

    if (hasOrb) switchVizMode("orbital");
    else if (hasEsp) switchVizMode("esp");
    else {
      if (state.viewer) {
        state.viewer.removeAllSurfaces();
        state.viewer.render();
      }
      showControls("molecule");
    }
    initTrajectoryPlayer(result);
  }
  App.on("result:switched", handleResultSwitched);


  /* ─── Controls Visibility ─── */
  function showControls(mode) {
  if ($empty) $empty.hidden = true;
  if ($controls) $controls.hidden = false;
  if ($grpOrbital) $grpOrbital.hidden = mode !== "orbital" && mode !== "esp";
  if ($grpOpacity) $grpOpacity.hidden = mode !== "orbital" && mode !== "esp";

  /* Adjust slider range based on mode */
  if ($sliderIso) {
    if (mode === "esp") {
      $sliderIso.min = "0.0001";
      $sliderIso.max = "0.01";
      $sliderIso.step = "0.0001";
      if (state.isovalue > 0.01) {
        state.isovalue = 0.002;
        $sliderIso.value = state.isovalue;
      }
    } else {
      $sliderIso.min = "0.001";
      $sliderIso.max = "0.1";
      $sliderIso.step = "0.001";
      if (state.isovalue < 0.001) {
        state.isovalue = 0.03;
        $sliderIso.value = state.isovalue;
      }
    }
    if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(4);
  }

  var hasOrb =
    state.result && state.result.orbitals && state.result.orbitals.length > 0;
  if (!hasOrb) {
    hasOrb =
      state.result &&
      state.result.mo_energies &&
      state.result.mo_energies.length > 0;
  }
  if ($grpOrbitalSelect)
    $grpOrbitalSelect.hidden = mode !== "orbital" || !hasOrb;
}

    function showControls(mode) {
    if ($empty) $empty.hidden = true;
    if ($controls) $controls.hidden = false;
    
    var result = state.result || {};
    var hasOrbital = !!(
      result.orbital_cube_b64 ||
      result.orbital_cube ||
      (result.orbitals && result.orbitals.length) ||
      (result.mo_energies && result.mo_energies.length)
    );
    var hasESP = !!(result.esp_cube_b64 || result.esp_cube);
    
    if ($grpOrbital) $grpOrbital.hidden = !hasOrbital;
    var $grpESP = document.getElementById("grpESP");
    if ($grpESP) $grpESP.hidden = !hasESP;
    if ($grpOpacity) $grpOpacity.hidden = !(hasOrbital || hasESP);
    
    var $vizModeToggle = document.getElementById("vizModeToggle");
    if ($vizModeToggle) $vizModeToggle.hidden = !(hasOrbital && hasESP);

    updateToggleHighlight(mode);

    /* Adjust slider range based on mode */
    if ($sliderIso) {
      if (mode === "esp") {
        $sliderIso.min = "0.0001";
        $sliderIso.max = "0.01";
        $sliderIso.step = "0.0001";
        if (state.isovalue > 0.01) {
          state.isovalue = 0.002;
          $sliderIso.value = state.isovalue;
        }
      } else {
        $sliderIso.min = "0.001";
        $sliderIso.max = "0.1";
        $sliderIso.step = "0.001";
        if (state.isovalue < 0.001) {
          state.isovalue = 0.03;
          $sliderIso.value = state.isovalue;
        }
      }
      if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(4);
    }

    if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = (mode !== "orbital" || !hasOrbital);
  }

  function updateToggleHighlight(mode) {
    var $btnOrb = document.getElementById("btnModeOrbital");
    var $btnEsp = document.getElementById("btnModeESP");
    if ($btnOrb) $btnOrb.classList.toggle("active", mode === "orbital");
    if ($btnEsp) $btnEsp.classList.toggle("active", mode === "esp");
  }

  var _vizSwitchLock = false;

  function switchVizMode(newMode) {
    console.log("[Viewer] switchVizMode called:", newMode, "current mode:", state.mode, "lock:", _vizSwitchLock, "result:", !!state.result);
    if (!state.result || state.mode === newMode) return;
    if (_vizSwitchLock) {
        console.warn("[Viewer] switchVizMode blocked by lock!");
        return;
    }
    _vizSwitchLock = true;
    state.mode = newMode;
    
    if (state.viewer) {
      state.viewer.removeAllSurfaces();
      if (typeof state.viewer.removeAllShapes === "function") state.viewer.removeAllShapes();
      state.viewer.render(); // force GPU flush
    }

    setTimeout(function() {
        try {
            var result = state.result;
            var scheme = getCurrentColorScheme();
            if (newMode === "orbital") {
              var cubeB64 = (result.visualization && result.visualization.orbital_cube_b64) || result.orbital_cube_b64 || null;
              if (state.selectedOrbitalIndex != null && tryRenderCachedOrbital(state.selectedOrbitalIndex)) {
                // Handled by cache
              } else if (cubeB64) {
                var vol = new window.$3Dmol.VolumeData(atob(cubeB64), "cube");
                state.viewer.addIsosurface(vol, { isoval: state.isovalue, color: scheme.orbPositive, alpha: state.opacity, smoothness: 2 });
                state.viewer.addIsosurface(vol, { isoval: -state.isovalue, color: scheme.orbNegative, alpha: state.opacity, smoothness: 2 });
              } else if (state.selectedOrbitalIndex != null) {
                  silentFetchOrbital(state.selectedOrbitalIndex);
              }
            } else if (newMode === "esp") {
              var viz = result.visualization || {};
              var densB64 = viz.density_cube_b64 || result.density_cube_b64 || null;
              var espB64 = viz.esp_cube_b64 || result.esp_cube_b64 || null;
              
              if (!espB64) console.warn("[Viewer] ESP mode selected, but no esp_cube_b64 data found.");
              if (espB64) {
                  var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
                  var densVol = densB64 ? new window.$3Dmol.VolumeData(atob(densB64), "cube") : espVol;
                  var range = result.esp_auto_range_au || 0.05;
                  state.viewer.addIsosurface(densVol, {
                    isoval: state.espDensityIso || 0.001,
                    color: "white",
                    alpha: state.opacity,
                    smoothness: 1,
                    voldata: espVol,
                    volscheme: scheme.espGradient(-range, range)
                  });
              }
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

  /* ─── Orbital Selector ─── */
  function populateOrbitalSelector(result) {
    if (!$selectOrbital || !result) return;
    
    var orbitals = result.orbitals || [];
    var moE = result.mo_energies || [];
    var moO = result.mo_occupations || [];
    
    $selectOrbital.innerHTML = "";
    
    if (orbitals.length > 0) {
      var info = (result.visualization && result.visualization.orbital_info) || result.orbital_info || {};
      var currentIdx = info.orbital_index != null ? info.orbital_index : (result.selected_orbital ? result.selected_orbital.zero_based_index : -1);

      orbitals.forEach(function(orb) {
        var opt = document.createElement("option");
        opt.value = orb.zero_based_index;
        opt.textContent = orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
        if (orb.zero_based_index === currentIdx) opt.selected = true;
        $selectOrbital.appendChild(opt);
      });
      state.selectedOrbitalIndex = currentIdx;
      if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = false;
      return;
    }

    if (!moE.length) {
      if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = true;
      return;
    }

    var homoIdx = -1;
    for (var i = 0; i < moE.length; i++) {
      if (moO[i] != null && moO[i] > 0) homoIdx = i;
    }
    var lumoIdx = (homoIdx >= 0 && homoIdx + 1 < moE.length) ? homoIdx + 1 : -1;

    var info = (result.visualization && result.visualization.orbital_info) || result.orbital_info || {};
    var currentIdx = info.orbital_index != null ? info.orbital_index : homoIdx;

    var startIdx = Math.max(0, homoIdx - 4);
    var endIdx = Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 5);

    for (var j = startIdx; j < endIdx; j++) {
      var opt = document.createElement("option");
      opt.value = j;
      var label = "MO " + j;
      if (j === homoIdx) label = "HOMO";
      else if (j === lumoIdx) label = "LUMO";
      else if (j === homoIdx - 1) label = "HOMO-1";
      else if (j === homoIdx - 2) label = "HOMO-2";
      else if (lumoIdx >= 0 && j === lumoIdx + 1) label = "LUMO+1";
      else if (lumoIdx >= 0 && j === lumoIdx + 2) label = "LUMO+2";
      label += " (" + Number(moE[j]).toFixed(3) + " Ha)";
      opt.textContent = label;
      if (j === currentIdx) opt.selected = true;
      $selectOrbital.appendChild(opt);
    }

    state.selectedOrbitalIndex = currentIdx;
    if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = false;
  }

  /* ─── Event Bindings ─── */

  /* ─── Fix #2: 오비탈 셀렉터를 Silent Fetch 방식으로 교체 ── */

  function showMiniSpinner(show) {
    var spinId = "orbital-mini-spinner";
    var existing = document.getElementById(spinId);
    if (!show) {
      if (existing) existing.remove();
      return;
    }
    if (existing) return;
    var el = document.createElement("div");
    el.id = spinId;
    el.style.cssText =
      "position:absolute;top:16px;right:16px;z-index:100;" +
      "width:24px;height:24px;border:3px solid rgba(120,120,120,0.3);" +
      "border-top-color:#4a90d9;border-radius:50%;" +
      "animation:qcviz-spin .6s linear infinite;";
    if (!document.getElementById("qcviz-spin-style")) {
      var style = document.createElement("style");
      style.id = "qcviz-spin-style";
      style.textContent =
        "@keyframes qcviz-spin{to{transform:rotate(360deg)}}";
      document.head.appendChild(style);
    }
    $viewerDiv.style.position = "relative";
    $viewerDiv.appendChild(el);
  }

  function tryRenderCachedOrbital(idx) {
    var orbitals = (state.result && state.result.orbitals) || [];
    var orb = null;
    for (var i=0; i<orbitals.length; i++) {
        if (orbitals[i].zero_based_index === idx) {
            orb = orbitals[i];
            break;
        }
    }
    
    if (orb && orb.cube_data) {
      clearViewer(state.viewer);
      addMoleculeModel(state.viewer, state.result);
      
      try {
        var cubeData = atob(orb.cube_data);
        var vol = new window.$3Dmol.VolumeData(cubeData, "cube");
        state.viewer.addIsosurface(vol, { isoval: state.isovalue, color: getCurrentColorScheme().orbPositive, alpha: state.opacity, smoothness: 2 });
        state.viewer.addIsosurface(vol, { isoval: -state.isovalue, color: getCurrentColorScheme().orbNegative, alpha: state.opacity, smoothness: 2 });
      } catch(e) {}
      if (state.showLabels && state.model) addLabels(state.viewer, state.result);
      state.viewer.render();
      state.mode = "orbital";
      showControls("orbital");
      hideLegend();
      return true;
    }
    return false;
  }

  function silentFetchOrbital(idx) {
    var result = state.result;
    if (!result) return;

    var molName = result.molecule_name || result.structure_name || "molecule";
    var method = result.method || "RHF";
    var basis = result.basis || result.basis_set || "sto-3g";
    
    var orbitals = result.orbitals || [];
    var selectedOrb = null;
    for (var i=0; i<orbitals.length; i++) {
        if (orbitals[i].zero_based_index === idx) {
            selectedOrb = orbitals[i];
            break;
        }
    }
    
    var orbLabel = (selectedOrb ? selectedOrb.label : "MO " + idx);
    var charge = result.charge || 0;
    var mult = result.multiplicity || 1;

    var payload = {
      structure_query: molName,
      job_type: "orbital_preview",
      method: method,
      basis: basis,
      charge: charge,
      multiplicity: mult,
      orbital: orbLabel,
    };

    showMiniSpinner(true);

    fetch("/api/compute/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("Job submit failed: " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        var jobId = data.job_id || data.id;
        if (!jobId) throw new Error("No job_id in response");
        return pollJobResult(jobId);
      })
      .then(function (jobResult) {
        showMiniSpinner(false);
        var viz = jobResult.visualization || {};
        var cubeB64 = viz.orbital_cube_b64 || jobResult.orbital_cube_b64 || null;
        
        if (cubeB64) {
          var orbs = (state.result && state.result.orbitals) || [];
          for (var i=0; i<orbs.length; i++) {
              if (orbs[i].zero_based_index === idx) {
                  orbs[i].cube_data = cubeB64;
                  break;
              }
          }
          
          clearViewer(state.viewer);
          addMoleculeModel(state.viewer, state.result);
          try {
            var cubeData = atob(cubeB64);
            var vol = new window.$3Dmol.VolumeData(cubeData, "cube");
            state.viewer.addIsosurface(vol, { isoval: state.isovalue, color: getCurrentColorScheme().orbPositive, alpha: state.opacity, smoothness: 2 });
            state.viewer.addIsosurface(vol, { isoval: -state.isovalue, color: getCurrentColorScheme().orbNegative, alpha: state.opacity, smoothness: 2 });
          } catch(e) {}
          if (state.showLabels && state.model) addLabels(state.viewer, state.result);
          state.viewer.render();
          state.mode = "orbital";
          showControls("orbital");
          hideLegend();
        }
      })
      .catch(function (err) {
        showMiniSpinner(false);
        console.error("[viewer] Silent orbital fetch failed:", err);
      });
  }

  function pollJobResult(jobId) {
    var MAX_POLL = 60;
    var INTERVAL = 500;
    var count = 0;

    return new Promise(function (resolve, reject) {
      function tick() {
        fetch("/api/compute/jobs/" + jobId + "?include_result=true")
          .then(function (r) {
            return r.json();
          })
          .then(function (job) {
            var status = job.status || "";
            if (status === "completed" || status === "done") {
              return resolve(job.result || job);
            }
            if (status === "failed" || status === "error") {
              return reject(new Error(job.error || "Job failed"));
            }
            count++;
            if (count >= MAX_POLL) {
              return reject(new Error("Poll timeout"));
            }
            setTimeout(tick, INTERVAL);
          })
          .catch(reject);
      }
      tick();
    });
  }

  if ($selectOrbital) {
    $selectOrbital.addEventListener("change", function () {
      var idx = parseInt($selectOrbital.value, 10);
      if (isNaN(idx)) return;
      state.selectedOrbitalIndex = idx;
      App.emit("orbital:select", { orbital_index: idx });

      if (!tryRenderCachedOrbital(idx)) {
        silentFetchOrbital(idx);
      }

      saveViewerSnapshot();
    });
  }

  /* Style segmented control */
  if ($segStyle) {
    $segStyle.addEventListener("click", function (e) {
      var btn = e.target.closest(".segmented__btn");
      if (!btn) return;
      var val = btn.dataset.value;
      if (val === state.style) return;

      state.style = val;
      $segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
        b.classList.toggle("segmented__btn--active", b.dataset.value === val);
      });

      if (state.viewer && state.model) {
        applyStyle(state.viewer, val);
        state.viewer.render();
      }
      saveViewerSnapshot();
    });
  }

  /* Isovalue slider */
  if ($sliderIso) {
    $sliderIso.addEventListener("input", function () {
      state.isovalue = parseFloat($sliderIso.value);
      if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(3);
    });
    $sliderIso.addEventListener("change", function () {
      if (state.mode === "orbital" && state.result) {
        renderOrbital(state.result);
      } else if (state.mode === "esp" && state.result) {
        renderESP(state.result);
      }
      saveViewerSnapshot();
    });
  }

  /* Opacity slider */
  if ($sliderOp) {
    $sliderOp.addEventListener("input", function () {
      state.opacity = parseFloat($sliderOp.value);
      if ($lblOp) $lblOp.textContent = state.opacity.toFixed(2);
    });
    $sliderOp.addEventListener("change", function () {
      if (state.mode === "orbital" && state.result) {
        renderOrbital(state.result);
      } else if (state.mode === "esp" && state.result) {
        renderESP(state.result);
      }
      saveViewerSnapshot();
    });
  }

  /* Labels toggle — 핵심: 확실하게 라벨 On/Off 동작 */
  if ($btnLabels) {
    $btnLabels.addEventListener("click", function () {
      state.showLabels = !state.showLabels;
      $btnLabels.setAttribute("data-active", String(state.showLabels));
      $btnLabels.setAttribute("aria-pressed", String(state.showLabels));
      $btnLabels.textContent = state.showLabels ? "On" : "Off";

      /* 실제로 3Dmol 라벨을 제거/추가 후 render */
      refreshLabels();
      saveViewerSnapshot();
    });
  }

  /* Reset view */
  if ($btnReset) {
    $btnReset.addEventListener("click", function () {
      if (state.viewer) {
        state.viewer.zoomTo();
        state.viewer.render();
      }
    });
  }

  /* Screenshot */
  if ($btnScreenshot) {
    $btnScreenshot.addEventListener("click", function () {
      if (!state.viewer) return;
      try {
        var dataUrl = state.viewer.pngURI();
        var a = document.createElement("a");
        a.href = dataUrl;
        a.download = "qcviz-" + (state.jobId || "capture") + "-" + Date.now() + ".png";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } catch (err) {
        console.error("Screenshot failed:", err);
      }
    });
  }

  /* Fullscreen */
  if ($btnFullscreen) {
    $btnFullscreen.addEventListener("click", function () {
      var panel = document.getElementById("panelViewer");
      if (!panel) return;
      panel.classList.toggle("is-fullscreen");
      setTimeout(function () {
        if (state.viewer) {
          state.viewer.resize();
          state.viewer.render();
        }
      }, 150);
    });
  }

  /* Escape closes fullscreen */
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var panel = document.getElementById("panelViewer");
      if (panel && panel.classList.contains("is-fullscreen")) {
        panel.classList.remove("is-fullscreen");
        setTimeout(function () {
          if (state.viewer) {
            state.viewer.resize();
            state.viewer.render();
          }
        }, 150);
      }
    }
  });

  /* ─── Legends ─── */
  function showOrbitalLegend() {
    if (!$legend) return;
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">Orbital Lobes</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:#6366f1"></span>' +
        '<span>Positive (+' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:#f59e0b"></span>' +
        '<span>Negative (\u2212' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>';
  }

  function showESPLegend() {
    if (!$legend) return;
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">ESP Surface</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:linear-gradient(90deg,#ef4444,#ffffff,#3b82f6);width:60px;height:10px;border-radius:2px;"></span>' +
      '</div>' +
      '<div class="viewer-legend__row" style="justify-content:space-between;width:60px;margin-left:20px;">' +
        '<span style="font-size:10px;color:var(--text-3)">\u2212</span>' +
        '<span style="font-size:10px;color:var(--text-3)">0</span>' +
        '<span style="font-size:10px;color:var(--text-3)">+</span>' +
      '</div>';
  }

  function hideLegend() {
    if (!$legend) return;
    $legend.hidden = true;
    $legend.innerHTML = "";
  }

  /* ─── Snapshot Save/Restore ─── */
  function saveViewerSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(state.jobId, Object.assign({}, existing, {
      viewerStyle: state.style,
      viewerIsovalue: state.isovalue,
      viewerOpacity: state.opacity,
      viewerLabels: state.showLabels,
      viewerMode: state.mode,
      viewerOrbitalIndex: state.selectedOrbitalIndex,
    }));
  }

  function restoreViewerSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (!snap) return;

    if (snap.viewerStyle && snap.viewerStyle !== state.style) {
      state.style = snap.viewerStyle;
      if ($segStyle) {
        $segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
          b.classList.toggle("segmented__btn--active", b.dataset.value === state.style);
        });
      }
    }
    if (snap.viewerIsovalue != null) {
      state.isovalue = snap.viewerIsovalue;
      if ($sliderIso) $sliderIso.value = state.isovalue;
      if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(3);
    }
    if (snap.viewerOpacity != null) {
      state.opacity = snap.viewerOpacity;
      if ($sliderOp) $sliderOp.value = state.opacity;
      if ($lblOp) $lblOp.textContent = state.opacity.toFixed(2);
    }
    if (snap.viewerLabels != null) {
      state.showLabels = snap.viewerLabels;
      if ($btnLabels) {
        $btnLabels.setAttribute("data-active", String(state.showLabels));
        $btnLabels.setAttribute("aria-pressed", String(state.showLabels));
        $btnLabels.textContent = state.showLabels ? "On" : "Off";
      }
    }
    if (snap.viewerOrbitalIndex != null) {
      state.selectedOrbitalIndex = snap.viewerOrbitalIndex;
    }
  }

  /* ─── Main Result Handler ─── */
  function handleResult(detail) {
    var result = detail.result;
    var jobId = detail.jobId;
    var source = detail.source;

    if (!result) {
      if (state.viewer) {
        clearViewer(state.viewer);
        state.viewer.render();
      }
      state.result = null;
      state.jobId = null;
      state.mode = "none";
      if ($empty) $empty.hidden = false;
      if ($controls) $controls.hidden = true;
      hideLegend();
      return;
    }

    state.result = result;
    state.jobId = jobId;

    /* 히스토리에서 복원 시 뷰어 세팅 복원 */
    if (source === "history" && jobId) {
      restoreViewerSnapshot(jobId);
    }

    var viz = result.visualization || {};
    var promise;

    if (viz.orbital_cube_b64 || result.orbital_cube_b64) {
      promise = renderOrbital(result);
    } else if (viz.esp_cube_b64 || result.esp_cube_b64) {
      promise = renderESP(result);
    } else if (getXyz(result)) {
      promise = renderMolecule(result);
    } else {
      /* 시각화 데이터 없음 */
      state.mode = "none";
      if ($empty) {
        $empty.hidden = false;
        var t = $empty.querySelector(".viewer-empty__text");
        if (t) t.textContent = "No visualization data for this result";
      }
      if ($controls) $controls.hidden = true;
      hideLegend();
      return;
    }

    if (promise) {
      promise.then(function () {
        saveViewerSnapshot();
      }).catch(function (err) {
        console.error("[Viewer] Render failed:", err);
      });
    }
  }

  /* ─── Theme Change ─── */
  App.on("theme:changed", function () {
    updateViewerBg();
    refreshLabels();
  });

  /* ─── Window Resize ─── */
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (state.viewer) {
        state.viewer.resize();
        state.viewer.render();
      }
    }, 150);
  });

  /* ─── Listen for Results ─── */
  App.on("result:changed", handleResult);

  /* ─── Expose API ─── */
  App.viewer = {
    getState: function () {
      return Object.assign({}, state, { viewer: undefined, model: undefined });
    },
    reset: function () {
      if (state.viewer) {
        state.viewer.zoomTo();
        state.viewer.render();
      }
    },
    refreshLabels: refreshLabels,
  };






  function initTrajectoryPlayer(result) {
    var $traj = document.getElementById("trajectoryPlayer");
    if (!$traj) return;

    var trajectory = result.trajectory;
    var multiXyz = result.trajectory_xyz;

    if (!trajectory || trajectory.length < 2) {
      $traj.hidden = true;
      state.trajectoryFrames = [];
      return;
    }

    state.trajectoryFrames = trajectory;
    state.trajectoryFrame = trajectory.length - 1;
    state.trajectoryPlaying = false;
    $traj.hidden = false;

    var $slider = document.getElementById("trajSlider");
    var $btnPlay = document.getElementById("trajPlay");
    var $btnPause = document.getElementById("trajPause");

    if ($slider) {
      $slider.min = 0;
      $slider.max = trajectory.length - 1;
      $slider.value = $slider.max;
      $slider.addEventListener("input", function () {
        goToTrajectoryFrame(parseInt($slider.value, 10));
      });
    }

    if ($btnPlay) {
      $btnPlay.onclick = playTrajectory;
    }
    if ($btnPause) {
      $btnPause.onclick = pauseTrajectory;
    }

    updateTrajectoryLabel();
    if (multiXyz && state.viewer) {
      loadTrajectoryMultiModel(multiXyz);
    }
  }

  function loadTrajectoryMultiModel(multiXyz) {
    if (!state.viewer) return;
    state.viewer.removeAllModels();
    state.viewer.addModelsAsFrames(multiXyz, "xyz");
    state.viewer.setStyle({}, { stick: { radius: 0.15 }, sphere: { scale: 0.3 } });
    state.viewer.zoomTo();
    state.viewer.render();
    var nFrames = state.trajectoryFrames.length;
    if (nFrames > 0) {
      state.viewer.setFrame(nFrames - 1);
      state.viewer.render();
    }
  }

  function goToTrajectoryFrame(idx) {
    state.trajectoryFrame = idx;
    if (state.viewer) {
      try {
        state.viewer.setFrame(idx);
        state.viewer.render();
      } catch (_) {
        var frame = state.trajectoryFrames[idx];
        if (frame && frame.xyz) {
          state.viewer.removeAllModels();
          state.viewer.addModel(frame.xyz, "xyz");
          state.viewer.setStyle({}, { stick: { radius: 0.15 }, sphere: { scale: 0.3 } });
          state.viewer.render();
        }
      }
    }
    var $slider = document.getElementById("trajSlider");
    if ($slider) $slider.value = idx;
    updateTrajectoryLabel();
  }

  function updateTrajectoryLabel() {
    var $label = document.getElementById("trajLabel");
    if (!$label) return;
    var frames = state.trajectoryFrames;
    var idx = state.trajectoryFrame;
    var frame = frames[idx] || {};
    var text = "Step " + (idx + 1) + " / " + frames.length;
    if (frame.energy_hartree != null) text += "  |  E = " + frame.energy_hartree.toFixed(8) + " Ha";
    if (frame.grad_norm != null) text += "  |  |∇| = " + frame.grad_norm.toFixed(6);
    $label.textContent = text;
  }

  function playTrajectory() {
    if (state.trajectoryPlaying) return;
    state.trajectoryPlaying = true;
    var frames = state.trajectoryFrames;
    if (!frames.length) return;
    if (state.trajectoryFrame >= frames.length - 1) state.trajectoryFrame = 0;
    
    var $btnPlay = document.getElementById("trajPlay");
    var $btnPause = document.getElementById("trajPause");
    if ($btnPlay) $btnPlay.hidden = true;
    if ($btnPause) $btnPause.hidden = false;

    function nextFrame() {
      if (!state.trajectoryPlaying) return;
      if (state.trajectoryFrame >= frames.length - 1) {
        pauseTrajectory();
        return;
      }
      state.trajectoryFrame++;
      goToTrajectoryFrame(state.trajectoryFrame);
      state.trajectoryTimer = setTimeout(nextFrame, 200);
    }
    nextFrame();
  }

  function pauseTrajectory() {
    state.trajectoryPlaying = false;
    if (state.trajectoryTimer) {
      clearTimeout(state.trajectoryTimer);
      state.trajectoryTimer = null;
    }
    var $btnPlay = document.getElementById("trajPlay");
    var $btnPause = document.getElementById("trajPause");
    if ($btnPlay) $btnPlay.hidden = false;
    if ($btnPause) $btnPause.hidden = true;
  }




  function bindStyleButtons() {
    if ($segStyle) {
      var btns = $segStyle.querySelectorAll(".segmented__btn");
      for (var i = 0; i < btns.length; i++) {
        btns[i].addEventListener("click", function (e) {
          var t = e.currentTarget;
          var val = t.getAttribute("data-value");
          for (var j = 0; j < btns.length; j++) {
            btns[j].classList.remove("segmented__btn--active");
          }
          t.classList.add("segmented__btn--active");
          state.style = val;
          if (state.viewer && state.model) {
            applyStyle(state.viewer, val);
            state.viewer.render();
          }
          saveViewerSnapshot();
        });
      }
    }

    if ($btnToggleLabels) {
      $btnToggleLabels.addEventListener("click", function () {
        state.showLabels = !state.showLabels;
        syncButtonState();
        if (state.viewer && state.model) {
          clearLabels();
          if (state.showLabels) addLabels(state.viewer, state.result);
          state.viewer.render();
        }
        saveViewerSnapshot();
      });
    }

    if ($btnReset) {
      $btnReset.addEventListener("click", function () {
        if (state.viewer) {
          state.viewer.zoomTo();
          state.viewer.render();
        }
      });
    }

    if ($btnScreenshot) {
      $btnScreenshot.addEventListener("click", function () {
        if (!state.viewer) return;
        try {
          var uri = state.viewer.pngURI();
          var a = document.createElement("a");
          a.href = uri;
          a.download = "qcviz-mcp-" + Date.now() + ".png";
          a.click();
        } catch (e) {
          console.warn("Screenshot failed:", e);
        }
      });
    }

    if ($btnFullscreen) {
      $btnFullscreen.addEventListener("click", function () {
        var p = document.getElementById("panelViewer");
        if (p) {
          p.classList.toggle("is-fullscreen");
          if (state.viewer) {
            setTimeout(function () {
              state.viewer.resize();
              state.viewer.render();
            }, 50);
          }
        }
      });
    }
  }

  function bindReactiveControls() {
    if ($sliderIso) {
      $sliderIso.addEventListener("input", function () {
        state.isovalue = parseFloat($sliderIso.value);
        if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(4);
      });
      $sliderIso.addEventListener("change", function () {
        if (state.mode === "orbital" && state.result) {
          renderOrbital(state.result);
        } else if (state.mode === "esp" && state.result) {
          renderESP(state.result);
        }
        saveViewerSnapshot();
      });
    }

    if ($sliderOp) {
      $sliderOp.addEventListener("input", function () {
        state.opacity = parseFloat($sliderOp.value);
        if ($lblOp) $lblOp.textContent = state.opacity.toFixed(2);
      });
      $sliderOp.addEventListener("change", function () {
        if (state.mode === "orbital" && state.result) {
          renderOrbital(state.result);
        } else if (state.mode === "esp" && state.result) {
          renderESP(state.result);
        }
        saveViewerSnapshot();
      });
    }
  }

  function syncButtonState() {
    if ($btnToggleLabels) {
      $btnToggleLabels.setAttribute("data-active", String(state.showLabels));
      $btnToggleLabels.setAttribute("aria-pressed", String(state.showLabels));
      $btnToggleLabels.textContent = state.showLabels ? "On" : "Off";
    }
  }

  function init() {
    bindStyleButtons();
    bindReactiveControls();
    syncButtonState();
    
    var $selectColor = document.getElementById("selectColorScheme");
    if ($selectColor) {
      $selectColor.addEventListener("change", function() {
        if (COLOR_SCHEMES[$selectColor.value]) {
          state.colorScheme = $selectColor.value;
          updateSchemePreview();
          // Trigger a re-render of surfaces
          if (state.mode === "orbital" || state.mode === "esp") {
             var currentMode = state.mode;
             state.mode = "none"; // force switchVizMode to actually do something
             switchVizMode(currentMode);
          }
          saveViewerSnapshot();
        }
      });
      updateSchemePreview();
    }

        var $btnModeOrbital = document.getElementById("btnModeOrbital");
    var $btnModeESP = document.getElementById("btnModeESP");
    console.log("[Viewer] init() - $btnModeOrbital:", $btnModeOrbital, "$btnModeESP:", $btnModeESP);
    if ($btnModeOrbital) {
      $btnModeOrbital.addEventListener("click", function () {
        console.log("[Viewer] Orbital clicked");
        switchVizMode("orbital");
      });
    }
    if ($btnModeESP) {
      $btnModeESP.addEventListener("click", function () {
        console.log("[Viewer] ESP clicked");
        switchVizMode("esp");
      });
    }


    if ($selectOrbital) {
      $selectOrbital.addEventListener("change", function () {
        var idx = parseInt($selectOrbital.value, 10);
        if (isNaN(idx)) return;
        state.selectedOrbitalIndex = idx;
        App.emit("orbital:select", { orbital_index: idx });

        if (!tryRenderCachedOrbital(idx)) {
          silentFetchOrbital(idx);
        }

        saveViewerSnapshot();
      });
    }

    ensureViewer().then(function () {
      var activeJobId = App.store.activeJobId;
      if (activeJobId && App.store.resultsByJobId[activeJobId]) {
        var r = App.store.resultsByJobId[activeJobId];
        loadViewerSnapshot(activeJobId);
        
        var focus = r.advisor_focus_tab || r.default_tab || "";
        if (focus === "esp" && (r.esp_cube_b64 || r.esp_cube)) {
          renderESP(r);
        } else if ((focus === "orbital" || focus === "orbitals") && (r.orbital_cube_b64 || r.orbital_cube)) {
          renderOrbital(r);
        } else {
          renderMolecule(r);
        }
        populateOrbitalSelector(r);
        initTrajectoryPlayer(r);
      }
      dismissLoader();
    }).catch(function() { dismissLoader(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

})();

```

### 2. `results.js` (관련 부분 발췌 또는 전체)
```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Results Module
   (Fixed: field name alignment with backend)
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var TAB_ORDER = [
    ["summary", "Summary"],
    ["geometry", "Geometry"],
    ["orbital", "Orbital"],
    ["esp", "ESP"],
    ["charges", "Charges"],
    ["json", "JSON"],
  ];

  var state = { result: null, jobId: null, activeTab: "summary", tabs: [] };

  var sessionResults = [];
  var activeSessionIdx = -1;

  function buildResultLabel(result, index) {
    var mol = result.molecule_name || result.structure_name || "Mol";
    var type = "";

    if (result.optimization_performed) {
      type = "Opt";
    } else if (result.orbital_cube_b64 || result.orbital_cube) {
      var orbs = result.orbitals || [];
      var selIdx = 0;
      for (var i = 0; i < orbs.length; i++) {
        if (orbs[i] && orbs[i].is_selected) { selIdx = i; break; }
      }
      var orbLabel = (orbs[selIdx] && orbs[selIdx].label) || "MO";
      type = orbLabel;
    } else if (result.esp_cube_b64 || result.esp_cube) {
      type = "ESP";
    } else {
      type = result.method || "SCF";
    }
    return "#" + index + " " + mol + " " + type;
  }

  function renderSessionTabs() {
    var $bar = document.getElementById("sessionTabBar");
    if (!$bar) return;
    $bar.innerHTML = "";
    $bar.hidden = sessionResults.length <= 1;

    for (var i = 0; i < sessionResults.length; i++) {
      (function(idx) {
        var entry = sessionResults[idx];
        var $tab = document.createElement("button");
        $tab.className = "session-tab" + (idx === activeSessionIdx ? " active" : "");
        $tab.textContent = entry.label;
        $tab.title = new Date(entry.timestamp).toLocaleTimeString();
        $tab.setAttribute("data-idx", idx);

        $tab.addEventListener("click", function () {
          switchToSessionResult(idx);
        });

        var $close = document.createElement("span");
        $close.className = "session-tab-close";
        $close.textContent = "×";
        $close.title = "이 결과 닫기";
        $close.addEventListener("click", function (e) {
          e.stopPropagation();
          removeSessionResult(idx);
        });

        $tab.appendChild($close);
        $bar.appendChild($tab);
      })(i);
    }
  }

  function switchToSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    if (idx === activeSessionIdx) return;
    activeSessionIdx = idx;
    var entry = sessionResults[idx];
    state.result = entry.result;
    state.jobId = entry.jobId;
    
    var available = getAvailableTabs(entry.result);
    state.tabs = available;
    if (available.indexOf(state.activeTab) === -1) {
        state.activeTab = decideFocusTab(entry.result, available);
    }
    
    renderSessionTabs();
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, entry.result);
    App.emit("result:switched", { result: entry.result, jobId: entry.jobId });
  }

  function removeSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    sessionResults.splice(idx, 1);
    if (sessionResults.length === 0) {
      activeSessionIdx = -1;
      state.result = null;
      state.jobId = null;
      renderSessionTabs();
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      App.emit("result:cleared");
      return;
    }
    if (idx === activeSessionIdx) {
      activeSessionIdx = Math.min(idx, sessionResults.length - 1);
      var entry = sessionResults[activeSessionIdx];
      state.result = entry.result;
      state.jobId = entry.jobId;
      var available = getAvailableTabs(entry.result);
      state.tabs = available;
      if (available.indexOf(state.activeTab) === -1) {
          state.activeTab = decideFocusTab(entry.result, available);
      }
      renderTabs(available, state.activeTab);
      renderContent(state.activeTab, entry.result);
    } else if (idx < activeSessionIdx) {
      activeSessionIdx--;
    }
    renderSessionTabs();
  }



  var $tabs = document.getElementById("resultsTabs");
  var $content = document.getElementById("resultsContent");
  var $empty = document.getElementById("resultsEmpty");

  function normalizeResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    var r = App.clone(raw);

    /* ── energy aliases ── */
    if (r.total_energy_hartree == null && r.energy != null)
      r.total_energy_hartree = r.energy;

    /* ── visualization normalization ── */
    if (!r.visualization) r.visualization = {};
    var viz = r.visualization;

    /* Backend sends viz.xyz and viz.molecule_xyz, NOT viz.xyz_block */
    if (!viz.xyz_block) {
      viz.xyz_block =
        viz.xyz || viz.molecule_xyz || r.xyz_block || r.xyz || null;
    }

    if (!viz.orbital_cube_b64 && r.orbital_cube_b64)
      viz.orbital_cube_b64 = r.orbital_cube_b64;
    if (!viz.orbital_info && r.orbital_info) viz.orbital_info = r.orbital_info;
    if (!viz.esp_cube_b64 && r.esp_cube_b64) viz.esp_cube_b64 = r.esp_cube_b64;
    if (!viz.density_cube_b64 && r.density_cube_b64)
      viz.density_cube_b64 = r.density_cube_b64;

    /* ── orbital sub-objects ── */
    if (!viz.orbital_cube_b64 && viz.orbital && viz.orbital.cube_b64) {
      viz.orbital_cube_b64 = viz.orbital.cube_b64;
    }
    if (!viz.esp_cube_b64 && viz.esp && viz.esp.cube_b64) {
      viz.esp_cube_b64 = viz.esp.cube_b64;
    }
    if (!viz.density_cube_b64 && viz.density && viz.density.cube_b64) {
      viz.density_cube_b64 = viz.density.cube_b64;
    }

    /* ── selected_orbital → orbital_info ── */
    if (!viz.orbital_info && r.selected_orbital) {
      viz.orbital_info = r.selected_orbital;
    }

    /* ── charges: backend returns [{atom_index, symbol, charge}, ...] ── */
    /* Normalize to parallel arrays for easy rendering */
    if (
      r.mulliken_charges &&
      r.mulliken_charges.length &&
      typeof r.mulliken_charges[0] === "object"
    ) {
      r._mulliken_raw = r.mulliken_charges;
      r.mulliken_charges = r.mulliken_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.lowdin_charges &&
      r.lowdin_charges.length &&
      typeof r.lowdin_charges[0] === "object"
    ) {
      r._lowdin_raw = r.lowdin_charges;
      r.lowdin_charges = r.lowdin_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.partial_charges &&
      r.partial_charges.length &&
      typeof r.partial_charges[0] === "object"
    ) {
      r.partial_charges = r.partial_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }

    /* ── fallback aliases for old-style keys ── */
    if (!r.mulliken_charges && r.charges) r.mulliken_charges = r.charges;
    if (!r.atoms && r.geometry) r.atoms = r.geometry;

    /* ── Build mo_energies / mo_occupations from orbitals array ── */
    if (
      (!r.mo_energies || !r.mo_energies.length) &&
      r.orbitals &&
      r.orbitals.length
    ) {
      var sorted = r.orbitals.slice().sort(function (a, b) {
        return a.zero_based_index - b.zero_based_index;
      });
      r.mo_energies = sorted.map(function (o) {
        return o.energy_hartree;
      });
      r.mo_occupations = sorted.map(function (o) {
        return o.occupancy;
      });
      r._orbital_index_offset = sorted[0] ? sorted[0].zero_based_index : 0;
      r._orbital_labels = sorted.map(function (o) {
        return o.label;
      });
    }

    return r;
  }

  function getAvailableTabs(r) {
    if (!r) return [];
    var a = ["summary"];
    if (r.visualization.xyz_block || (r.atoms && r.atoms.length))
      a.push("geometry");
    if (
      r.visualization.orbital_cube_b64 ||
      (r.mo_energies && r.mo_energies.length) ||
      (r.orbitals && r.orbitals.length)
    )
      a.push("orbital");
    if (r.visualization.esp_cube_b64) a.push("esp");
    if (
      (r.mulliken_charges && r.mulliken_charges.length) ||
      (r.lowdin_charges && r.lowdin_charges.length)
    )
      a.push("charges");
    a.push("json");
    return a;
  }

  function decideFocusTab(r, a) {
    /* Use backend's advisor_focus_tab if valid */
    var advised =
      r.advisor_focus_tab ||
      r.default_tab ||
      (r.visualization &&
        r.visualization.defaults &&
        r.visualization.defaults.focus_tab);
    if (advised && a.indexOf(advised) !== -1) return advised;
    if (a.indexOf("orbital") !== -1) return "orbital";
    if (a.indexOf("esp") !== -1) return "esp";
    if (a.indexOf("geometry") !== -1) return "geometry";
    return "summary";
  }

  function renderTabs(available, active) {
    if (!$tabs) return;
    $tabs.innerHTML = "";
    TAB_ORDER.forEach(function (pair) {
      if (available.indexOf(pair[0]) === -1) return;
      var btn = document.createElement("button");
      btn.className =
        "tab-btn" + (pair[0] === active ? " tab-btn--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("data-tab", pair[0]);
      btn.textContent = pair[1];
      btn.addEventListener("click", function () {
        switchTab(pair[0]);
      });
      $tabs.appendChild(btn);
    });
  }

  function switchTab(key) {
    if (key === state.activeTab) return;
    state.activeTab = key;
    if ($tabs)
      $tabs.querySelectorAll(".tab-btn").forEach(function (b) {
        b.classList.toggle("tab-btn--active", b.dataset.tab === key);
      });
    renderContent(key, state.result);
    saveSnapshot();
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function metric(label, value, unit) {
    return (
      '<div class="result-metric"><span class="result-metric__label">' +
      esc(label) +
      '</span><span class="result-metric__value">' +
      esc(String(value)) +
      (unit
        ? '<span class="result-metric__unit"> ' + esc(unit) + "</span>"
        : "") +
      "</span></div>"
    );
  }

  function renderContent(tab, r) {
    if (!r || !$content) {
      if ($content) $content.innerHTML = "";
      return;
    }
    var html = '<div class="result-card">';
    switch (tab) {
      case "summary":
        html += renderSummary(r);
        break;
      case "geometry":
        html += renderGeometry(r);
        break;
      case "orbital":
        html += renderOrbital(r);
        break;
      case "esp":
        html += renderESP(r);
        break;
      case "charges":
        html += renderCharges(r);
        break;
      case "json":
        html += renderJSON(r);
        break;
    }
    html += "</div>";
    $content.innerHTML = html;
  }

  function renderSummary(r) {
    var html = '<div class="metrics-grid">';
    var has = false;
    var m = [];

    if (r.structure_name || r.molecule_name || r.molecule)
      m.push([
        "Molecule",
        r.structure_name || r.molecule_name || r.molecule,
        "",
      ]);
    if (r.formula) m.push(["Formula", r.formula, ""]);
    if (r.method) m.push(["Method", r.method, ""]);
    /* Backend sends "basis", not "basis_set" */
    if (r.basis || r.basis_set)
      m.push(["Basis Set", r.basis || r.basis_set, ""]);
    if (r.n_atoms != null) m.push(["Atoms", r.n_atoms, ""]);
    if (r.scf_converged != null)
      m.push(["SCF Converged", r.scf_converged ? "Yes" : "No", ""]);

    if (r.total_energy_hartree != null)
      m.push(["Total Energy", Number(r.total_energy_hartree).toFixed(8), "Ha"]);
    if (r.total_energy_ev != null)
      m.push(["Energy", Number(r.total_energy_ev).toFixed(4), "eV"]);

    /* Backend sends homo_energy_hartree / homo_energy_ev, NOT homo_energy */
    if (r.homo_energy_hartree != null)
      m.push(["HOMO", Number(r.homo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.homo_energy != null)
      m.push(["HOMO", Number(r.homo_energy).toFixed(6), "Ha"]);

    if (r.lumo_energy_hartree != null)
      m.push(["LUMO", Number(r.lumo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.lumo_energy != null)
      m.push(["LUMO", Number(r.lumo_energy).toFixed(6), "Ha"]);

    /* Backend sends orbital_gap_hartree / orbital_gap_ev, NOT homo_lumo_gap */
    if (r.orbital_gap_hartree != null)
      m.push(["HOMO-LUMO Gap", Number(r.orbital_gap_hartree).toFixed(6), "Ha"]);
    else if (r.homo_lumo_gap != null)
      m.push(["HOMO-LUMO Gap", Number(r.homo_lumo_gap).toFixed(6), "Ha"]);

    if (r.orbital_gap_ev != null)
      m.push(["H-L Gap", Number(r.orbital_gap_ev).toFixed(4), "eV"]);
    else if (r.homo_lumo_gap_ev != null)
      m.push(["H-L Gap", Number(r.homo_lumo_gap_ev).toFixed(4), "eV"]);

    if (r.dipole_moment != null) {
      var dm;
      if (
        typeof r.dipole_moment === "object" &&
        r.dipole_moment.magnitude != null
      ) {
        dm = Number(r.dipole_moment.magnitude).toFixed(4);
      } else if (Array.isArray(r.dipole_moment)) {
        dm = r.dipole_moment
          .map(function (v) {
            return Number(v).toFixed(4);
          })
          .join(", ");
      } else {
        dm = Number(r.dipole_moment).toFixed(4);
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

  function renderGeometry(r) {
    var atoms = r.atoms || [];
    if (!atoms.length && !r.visualization.xyz_block)
      return '<p class="result-note">No geometry data.</p>';
    var html = "";

    /* Geometry summary from backend */
    var gs = r.geometry_summary;
    if (gs) {
      html += '<div class="metrics-grid" style="margin-bottom:var(--sp-4)">';
      if (gs.formula) html += metric("Formula", gs.formula, "");
      if (gs.n_atoms != null) html += metric("Atoms", gs.n_atoms, "");
      if (gs.bond_count != null) html += metric("Bonds", gs.bond_count, "");
      if (gs.bond_length_mean_angstrom != null)
        html += metric(
          "Avg Bond",
          Number(gs.bond_length_mean_angstrom).toFixed(4),
          "\u00C5",
        );
      html += "</div>";
    }

    if (atoms.length) {
      html +=
        '<table class="result-table"><thead><tr><th>#</th><th>Element</th><th>X (\u00C5)</th><th>Y (\u00C5)</th><th>Z (\u00C5)</th></tr></thead><tbody>';
      atoms.forEach(function (a, i) {
        var el = a.element || a.symbol || a[0] || "?";
        html +=
          "<tr><td>" +
          (i + 1) +
          "</td><td>" +
          esc(el) +
          "</td><td>" +
          Number(a.x != null ? a.x : a[1] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.y != null ? a.y : a[2] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.z != null ? a.z : a[3] || 0).toFixed(6) +
          "</td></tr>";
      });
      html += "</tbody></table>";
    }
    if (r.visualization.xyz_block) {
      html +=
        '<details style="margin-top:var(--sp-4)"><summary>Raw XYZ Block</summary><pre class="result-json" style="margin-top:var(--sp-2)">' +
        esc(r.visualization.xyz_block) +
        "</pre></details>";
    }
    return html;
  }

  function renderOrbital(r) {
    var info =
      (r.visualization && r.visualization.orbital_info) ||
      r.selected_orbital ||
      r.orbital_info ||
      {};
    var html = '<div class="metrics-grid">';
    if (info.label) html += metric("Selected", info.label, "");
    if (info.energy_hartree != null)
      html += metric("Energy", Number(info.energy_hartree).toFixed(6), "Ha");
    if (info.energy_ev != null)
      html += metric("Energy", Number(info.energy_ev).toFixed(4), "eV");
    if (info.occupancy != null) html += metric("Occupancy", info.occupancy, "");
    if (info.spin) html += metric("Spin", info.spin, "");
    html += "</div>";

    /* Use orbitals array from backend if available */
    var orbitals = r.orbitals || [];
    var moE = r.mo_energies || [];
    var moO = r.mo_occupations || [];
    var offset = r._orbital_index_offset || 0;
    var labels = r._orbital_labels || [];

    if (orbitals.length > 0 || moE.length > 0) {
      html +=
        '<div class="energy-diagram"><div class="energy-diagram__title">MO Energy Levels</div>';

      if (orbitals.length > 0 && moE.length === 0) {
        /* Render directly from orbitals array */
        orbitals.forEach(function (orb) {
          var occ = orb.occupancy || 0;
          var cls = "energy-level";
          var lbl = orb.label || "MO " + orb.index;
          if (lbl === "HOMO") cls += " energy-level--homo";
          else if (lbl === "LUMO") cls += " energy-level--lumo";
          else if (occ > 0) cls += " energy-level--occupied";
          else cls += " energy-level--virtual";
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(orb.energy_hartree).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        });
      } else {
        /* Legacy path: mo_energies + mo_occupations arrays */
        var homoIdx = -1;
        for (var i = 0; i < moE.length; i++) {
          if (moO[i] != null && moO[i] > 0) homoIdx = i;
        }
        var lumoIdx =
          homoIdx >= 0 && homoIdx + 1 < moE.length ? homoIdx + 1 : -1;
        var start = moE.length > 16 ? Math.max(0, homoIdx - 5) : 0;
        var end =
          moE.length > 16
            ? Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 6)
            : moE.length;
        for (var j = start; j < end; j++) {
          var realIdx = j + offset;
          var occ = moO[j] != null ? moO[j] : 0;
          var cls = "energy-level";
          var lbl = labels[j] || "MO " + realIdx;
          if (lbl === "HOMO") {
            cls += " energy-level--homo";
          } else if (lbl === "LUMO") {
            cls += " energy-level--lumo";
          } else if (lbl.indexOf("HOMO") === 0) {
            cls += " energy-level--occupied";
          } else if (lbl.indexOf("LUMO") === 0) {
            cls += " energy-level--virtual";
          } else if (occ > 0) {
            cls += " energy-level--occupied";
          } else {
            cls += " energy-level--virtual";
          }
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(moE[j]).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        }
      }
      html += "</div>";
    }
    html +=
      '<p class="result-note">The orbital is rendered in the 3D viewer. Use the controls to adjust isosurface and select orbitals.</p>';
    return html;
  }

  function renderESP(r) {
    var html = '<div class="metrics-grid">';
    if (r.esp_auto_range_au != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_au).toFixed(4),
        "a.u.",
      );
    }
    if (r.esp_auto_range_kcal != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_kcal).toFixed(2),
        "kcal/mol",
      );
    }
    if (r.esp_preset) {
      html += metric("Color Scheme", r.esp_preset, "");
    }
    /* Legacy */
    if (r.esp_range && !r.esp_auto_range_au) {
      html +=
        metric("ESP Min", Number(r.esp_range[0]).toFixed(4), "a.u.") +
        metric("ESP Max", Number(r.esp_range[1]).toFixed(4), "a.u.");
    }
    html += "</div>";
    html +=
      '<p class="result-note">The ESP surface is rendered in the 3D viewer. Use opacity slider to adjust.</p>';
    return html;
  }

  function renderCharges(r) {
    var mull = r.mulliken_charges || [];
    var lowd = r.lowdin_charges || [];
    var atoms = r.atoms || [];
    if (!mull.length && !lowd.length)
      return '<p class="result-note">No charge data.</p>';
    var html =
      '<table class="result-table"><thead><tr><th>#</th><th>Element</th>';
    if (mull.length) html += "<th>Mulliken</th>";
    if (lowd.length) html += "<th>L\u00F6wdin</th>";
    html += "</tr></thead><tbody>";
    var n = Math.max(mull.length, lowd.length);
    for (var i = 0; i < n; i++) {
      var el = atoms[i]
        ? atoms[i].element || atoms[i].symbol || atoms[i][0] || "?"
        : "?";
      html += "<tr><td>" + (i + 1) + "</td><td>" + esc(el) + "</td>";
      if (mull.length) {
        var mv = mull[i];
        /* Handle both number and object forms */
        var mval = mv != null && typeof mv === "object" ? mv.charge : mv;
        html +=
          "<td>" +
          (mval != null ? Number(mval).toFixed(6) : "\u2014") +
          "</td>";
      }
      if (lowd.length) {
        var lv = lowd[i];
        var lval = lv != null && typeof lv === "object" ? lv.charge : lv;
        html +=
          "<td>" +
          (lval != null ? Number(lval).toFixed(6) : "\u2014") +
          "</td>";
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    return html;
  }

  function renderJSON(r) {
    var json;
    /* Remove huge base64 fields for readability */
    var cleaned = App.clone(r);
    var viz = cleaned.visualization || {};
    if (viz.orbital_cube_b64)
      viz.orbital_cube_b64 =
        "[base64 data omitted, " + viz.orbital_cube_b64.length + " chars]";
    if (viz.esp_cube_b64)
      viz.esp_cube_b64 =
        "[base64 data omitted, " + viz.esp_cube_b64.length + " chars]";
    if (viz.density_cube_b64)
      viz.density_cube_b64 =
        "[base64 data omitted, " + viz.density_cube_b64.length + " chars]";
    if (cleaned.orbital_cube_b64) cleaned.orbital_cube_b64 = "[omitted]";
    if (cleaned.esp_cube_b64) cleaned.esp_cube_b64 = "[omitted]";
    if (cleaned.density_cube_b64) cleaned.density_cube_b64 = "[omitted]";
    if (viz.orbital && viz.orbital.cube_b64) viz.orbital.cube_b64 = "[omitted]";
    if (viz.esp && viz.esp.cube_b64) viz.esp.cube_b64 = "[omitted]";
    if (viz.density && viz.density.cube_b64) viz.density.cube_b64 = "[omitted]";
    delete cleaned._mulliken_raw;
    delete cleaned._lowdin_raw;
    delete cleaned._orbital_index_offset;
    delete cleaned._orbital_labels;
    try {
      json = JSON.stringify(cleaned, null, 2);
    } catch (_) {
      json = String(r);
    }
    return '<pre class="result-json">' + esc(json) + "</pre>";
  }

  function saveSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(
      state.jobId,
      Object.assign({}, existing, {
        activeTab: state.activeTab,
        timestamp: Date.now(),
      }),
    );
  }

  function restoreSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (snap && snap.activeTab) state.activeTab = snap.activeTab;
  }

  function update(result, jobId, source) {
    var normalized = normalizeResult(result);
    
    if (normalized) {
      var label = buildResultLabel(normalized, sessionResults.length + 1);
      var entry = {
        id: jobId || ("local-" + Date.now()),
        label: label,
        result: normalized,
        jobId: jobId,
        timestamp: Date.now(),
      };
      
      // Check if it's an update to an existing job in the session
      var existingIdx = -1;
      if (jobId) {
          for(var i=0; i<sessionResults.length; i++){
              if (sessionResults[i].jobId === jobId) { existingIdx = i; break; }
          }
      }
      
      if (existingIdx >= 0) {
          sessionResults[existingIdx] = entry;
          if (activeSessionIdx === existingIdx) {
              state.result = normalized;
          }
      } else {
          sessionResults.push(entry);
          activeSessionIdx = sessionResults.length - 1;
          state.result = normalized;
          state.jobId = jobId || null;
      }
    } else {
        state.result = null;
        state.jobId = null;
    }
    
    renderSessionTabs();
    if (!normalized) {
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      return;
    }
    if ($empty) $empty.hidden = true;
    var available = getAvailableTabs(normalized);
    state.tabs = available;
    if (source === "history" && jobId) {
      restoreSnapshot(jobId);
      if (available.indexOf(state.activeTab) === -1)
        state.activeTab = decideFocusTab(normalized, available);
    } else {
      state.activeTab = decideFocusTab(normalized, available);
    }
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, normalized);
    saveSnapshot();
  }

  App.on("result:changed", function (d) {
    update(d.result, d.jobId, d.source);
  });

  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var num = parseInt(e.key, 10);
    if (
      num >= 1 &&
      num <= 6 &&
      state.tabs.length > 0 &&
      num - 1 < state.tabs.length
    ) {
      switchTab(state.tabs[num - 1]);
    }
  });

  App.results = {
    getState: function () {
      return Object.assign({}, state);
    },
    switchTab: switchTab,
  };
})();
```

### 3. `style.css`
```css
html, body { height: 100vh; overflow: hidden; }
/* ═══════════════════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Design System
   ═══════════════════════════════════════════════════════ */

:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-full: 9999px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-8: 32px; --sp-10: 40px;
  --blur-sm: 8px; --blur-md: 16px; --blur-lg: 32px; --blur-xl: 48px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-smooth: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 120ms; --duration-base: 200ms; --duration-slow: 350ms;
  --z-base: 1; --z-sticky: 10; --z-controls: 20; --z-overlay: 100; --z-modal: 1000;
}

[data-theme="dark"] {
  --bg-0: #09090b; --bg-1: #0c0c0f; --bg-2: #111115; --bg-3: #18181b; --bg-4: #1f1f23; --bg-5: #27272a;
  --surface-0: rgba(17,17,21,0.72); --surface-1: rgba(24,24,27,0.65);
  --surface-2: rgba(31,31,35,0.60); --surface-raised: rgba(39,39,42,0.55);
  --surface-overlay: rgba(9,9,11,0.88);
  --border-0: rgba(255,255,255,0.06); --border-1: rgba(255,255,255,0.09);
  --border-2: rgba(255,255,255,0.12); --border-3: rgba(255,255,255,0.16);
  --border-focus: rgba(99,102,241,0.5);
  --text-0: #fafafa; --text-1: #e4e4e7; --text-2: #a1a1aa; --text-3: #71717a; --text-4: #52525b;
  --accent: #6366f1; --accent-hover: #818cf8;
  --accent-muted: rgba(99,102,241,0.15); --accent-subtle: rgba(99,102,241,0.08); --accent-2: #8b5cf6;
  --success: #22c55e; --success-muted: rgba(34,197,94,0.12);
  --warning: #f59e0b; --warning-muted: rgba(245,158,11,0.12);
  --error: #ef4444; --error-muted: rgba(239,68,68,0.12);
  --info: #3b82f6; --info-muted: rgba(59,130,246,0.12);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3); --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.5); --shadow-xl: 0 24px 64px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.06);
  color-scheme: dark;
}

[data-theme="light"] {
  --bg-0: #ffffff; --bg-1: #fafafa; --bg-2: #f4f4f5; --bg-3: #e4e4e7; --bg-4: #d4d4d8; --bg-5: #a1a1aa;
  --surface-0: rgba(255,255,255,0.82); --surface-1: rgba(250,250,250,0.78);
  --surface-2: rgba(244,244,245,0.72); --surface-raised: rgba(255,255,255,0.92);
  --surface-overlay: rgba(255,255,255,0.92);
  --border-0: rgba(0,0,0,0.05); --border-1: rgba(0,0,0,0.08);
  --border-2: rgba(0,0,0,0.12); --border-3: rgba(0,0,0,0.16);
  --border-focus: rgba(99,102,241,0.4);
  --text-0: #09090b; --text-1: #18181b; --text-2: #52525b; --text-3: #71717a; --text-4: #a1a1aa;
  --accent: #6366f1; --accent-hover: #4f46e5;
  --accent-muted: rgba(99,102,241,0.10); --accent-subtle: rgba(99,102,241,0.05); --accent-2: #7c3aed;
  --success: #16a34a; --success-muted: rgba(22,163,74,0.08);
  --warning: #d97706; --warning-muted: rgba(217,119,6,0.08);
  --error: #dc2626; --error-muted: rgba(220,38,38,0.08);
  --info: #2563eb; --info-muted: rgba(37,99,235,0.08);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04); --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.08); --shadow-xl: 0 24px 64px rgba(0,0,0,0.10);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.03);
  color-scheme: light;
}

/* Reset */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;}
html{font-family:var(--font-sans);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;scroll-behavior:smooth;}
body{background:var(--bg-0);color:var(--text-1);min-height:100dvh;overflow-x:hidden;transition:background var(--duration-slow) var(--ease-smooth),color var(--duration-base) var(--ease-smooth);}
a{color:var(--accent);text-decoration:none;transition:color var(--duration-fast);}a:hover{color:var(--accent-hover);}
::selection{background:var(--accent-muted);color:var(--text-0);}
:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px;}
::-webkit-scrollbar{width:6px;height:6px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:var(--radius-full);}::-webkit-scrollbar-thumb:hover{background:var(--text-4);}

/* App Shell */
.app-shell { display: grid; gap: 18px; padding: 18px; height: 100vh; overflow: hidden; box-sizing: border-box; }

/* Top Bar */
.topbar{display:flex;align-items:center;justify-content:space-between;height:52px;padding:0 var(--sp-4);background:var(--surface-0);backdrop-filter:blur(var(--blur-lg));-webkit-backdrop-filter:blur(var(--blur-lg));border:1px solid var(--border-0);border-radius:var(--radius-lg);position:sticky;top:var(--sp-3);z-index:var(--z-sticky);transition:box-shadow var(--duration-base) var(--ease-out);}
.topbar:hover{box-shadow:var(--shadow-sm);}
.topbar__left,.topbar__center,.topbar__right{display:flex;align-items:center;gap:var(--sp-3);}
.topbar__left{flex:1;}.topbar__center{flex:0 0 auto;}.topbar__right{flex:1;justify-content:flex-end;}
.topbar__logo{display:flex;align-items:center;gap:var(--sp-2);}
.topbar__title{font-weight:600;font-size:15px;color:var(--text-0);letter-spacing:-0.02em;}
.topbar__badge{font-size:10px;font-weight:600;padding:1px 6px;border-radius:var(--radius-full);background:var(--accent-muted);color:var(--accent);letter-spacing:0.02em;text-transform:uppercase;vertical-align:super;}

/* Status */
.status-indicator{display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-1) var(--sp-3);border-radius:var(--radius-full);background:var(--surface-1);border:1px solid var(--border-0);font-size:12px;color:var(--text-2);user-select:none;}
.status-indicator__dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:background var(--duration-base),box-shadow var(--duration-base);}
.status-indicator__dot[data-kind="idle"]{background:var(--text-4);}
.status-indicator__dot[data-kind="running"],.status-indicator__dot[data-kind="computing"]{background:var(--info);box-shadow:0 0 8px rgba(59,130,246,0.4);animation:pulse-dot 1.5s ease-in-out infinite;}
.status-indicator__dot[data-kind="success"],.status-indicator__dot[data-kind="completed"]{background:var(--success);box-shadow:0 0 8px rgba(34,197,94,0.3);}
.status-indicator__dot[data-kind="error"],.status-indicator__dot[data-kind="failed"]{background:var(--error);box-shadow:0 0 8px rgba(239,68,68,0.3);}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.5;transform:scale(1.4);}}

/* Buttons */
.icon-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:1px solid var(--border-1);border-radius:var(--radius-md);background:transparent;color:var(--text-2);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);flex-shrink:0;}
.icon-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);transform:translateY(-1px);}
.icon-btn:active{transform:translateY(0);}
.icon-btn--sm{width:28px;height:28px;}
[data-theme="dark"] .icon-moon{display:none;}[data-theme="light"] .icon-sun{display:none;}
.chip-btn{display:inline-flex;align-items:center;gap:var(--sp-1);height:28px;padding:0 var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-2);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.chip-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);}
.icon-btn.is-spinning svg{animation:spin 0.6s linear infinite;}
@keyframes spin{from{transform:rotate(0deg);}to{transform:rotate(360deg);}}

/* Dashboard Grid */
.dashboard{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(400px,1.1fr) minmax(220px,0.75fr);grid-template-areas:"viewer chat" "results history";gap:var(--sp-3);flex:1;min-height:0;}
@media(max-width:1100px){.dashboard{grid-template-columns:1fr;grid-template-rows:auto;grid-template-areas:"viewer" "chat" "results" "history";}.panel--viewer .viewer-container{min-height:320px;}.panel--chat{min-height:350px;}}
@media(min-width:1500px){.dashboard{grid-template-columns:1.3fr 0.9fr 0.8fr;grid-template-rows:1fr auto;grid-template-areas:"viewer chat history" "results results history";}}
.panel--viewer{grid-area:viewer;}.panel--chat{grid-area:chat;}.panel--results{grid-area:results;}.panel--history{grid-area:history;}

/* Panel */
.panel{display:flex;flex-direction:column;background:var(--surface-0);backdrop-filter:blur(var(--blur-md));-webkit-backdrop-filter:blur(var(--blur-md));border:1px solid var(--border-0);border-radius:var(--radius-lg);overflow:hidden;transition:box-shadow var(--duration-slow) var(--ease-out),border-color var(--duration-base) var(--ease-out);min-height:0;}
.panel:hover{border-color:var(--border-1);box-shadow:var(--shadow-sm),var(--shadow-glow);}
.panel__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border-0);flex-shrink:0;min-height:44px;}
.panel__title{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-weight:600;color:var(--text-3);letter-spacing:0.04em;text-transform:uppercase;}
.panel__title svg{color:var(--text-4);flex-shrink:0;}
.panel__actions{display:flex;align-items:center;gap:var(--sp-2);}


/* Viewer Panel */
.viewer-container{position:relative;flex:1;min-height:300px;background:var(--bg-1);overflow:hidden;transition:background var(--duration-slow) var(--ease-smooth);}
.viewer-3d{position:absolute;inset:0;width:100%;height:100%;z-index:var(--z-base);overflow:hidden;}
.viewer-empty{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--sp-3);pointer-events:none;animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-empty[hidden]{display:none;}
.viewer-empty__icon{color:var(--text-4);}
.viewer-empty__text{font-size:14px;color:var(--text-3);text-align:center;}
.viewer-empty__hint{font-size:12px;color:var(--text-4);font-family:var(--font-mono);}

.viewer-controls{position:absolute;bottom:var(--sp-3);left:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);display:flex;align-items:center;gap:var(--sp-4);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);animation:slideUp var(--duration-slow) var(--ease-out);flex-wrap:wrap;overflow-x:auto;}
.viewer-controls[hidden]{display:none;}
.viewer-controls::-webkit-scrollbar{display:none;}
.viewer-controls__group{display:flex;align-items:center;gap:var(--sp-2);flex-shrink:0;}
.viewer-controls__group[hidden]{display:none;}
.viewer-controls__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;white-space:nowrap;}
.viewer-controls__value{font-size:11px;font-family:var(--font-mono);color:var(--text-2);min-width:36px;text-align:right;}

.viewer-legend{position:absolute;top:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);font-size:11px;color:var(--text-2);animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-legend[hidden]{display:none;}
.viewer-legend__title{font-weight:600;color:var(--text-1);margin-bottom:var(--sp-1);font-size:11px;letter-spacing:0.02em;}
.viewer-legend__row{display:flex;align-items:center;gap:var(--sp-2);margin-top:3px;}
.viewer-legend__swatch{width:12px;height:12px;border-radius:3px;flex-shrink:0;border:1px solid var(--border-0);}

/* Segmented */
.segmented{display:inline-flex;background:var(--bg-3);border-radius:var(--radius-sm);padding:2px;gap:1px;}
.segmented__btn{padding:3px 10px;border:none;border-radius:var(--radius-xs);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.segmented__btn:hover{color:var(--text-1);}
.segmented__btn--active{background:var(--surface-raised);color:var(--text-0);box-shadow:var(--shadow-sm);}

/* Range */
.range-input{-webkit-appearance:none;appearance:none;width:80px;height:4px;background:var(--bg-4);border-radius:var(--radius-full);outline:none;cursor:pointer;}
.range-input:hover{background:var(--bg-5);}
.range-input::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;background:var(--accent);border-radius:50%;box-shadow:0 0 6px rgba(99,102,241,0.3);border:2px solid var(--bg-0);transition:transform var(--duration-fast) var(--ease-spring);}
.range-input::-webkit-slider-thumb:hover{transform:scale(1.2);}
.range-input::-moz-range-thumb{width:14px;height:14px;background:var(--accent);border:2px solid var(--bg-0);border-radius:50%;}

/* Toggle */
.toggle-btn{padding:3px 10px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);}
.toggle-btn[data-active="true"]{background:var(--accent-muted);color:var(--accent);border-color:rgba(99,102,241,0.3);}
.toggle-btn:hover{border-color:var(--border-2);}

/* Viewer select */
.viewer-select{padding:3px 8px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:var(--bg-3);color:var(--text-1);font-size:11px;font-family:var(--font-mono);cursor:pointer;outline:none;max-width:160px;transition:border-color var(--duration-fast);}
.viewer-select:focus{border-color:var(--accent);}
.viewer-select option{background:var(--bg-2);color:var(--text-1);}

/* Chat Panel */
.panel--chat{display:flex;flex-direction:column;}
.ws-status{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-3);}
.ws-status__dot{width:6px;height:6px;border-radius:50%;transition:background var(--duration-base),box-shadow var(--duration-base);}
.ws-status__dot[data-connected="false"]{background:var(--error);}
.ws-status__dot[data-connected="true"]{background:var(--success);box-shadow:0 0 6px rgba(34,197,94,0.4);}

.chat-scroll{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;scroll-behavior:smooth;}
.chat-messages{display:flex;flex-direction:column;gap:var(--sp-1);padding:var(--sp-3) var(--sp-4);}

.chat-msg{display:flex;gap:var(--sp-3);padding:var(--sp-3);border-radius:var(--radius-md);transition:background var(--duration-fast);animation:chatMsgIn var(--duration-slow) var(--ease-out);}
.chat-msg:hover{background:var(--surface-1);}
@keyframes chatMsgIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}

.chat-msg__avatar{width:28px;height:28px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:12px;font-weight:600;}
.chat-msg__avatar--system{background:var(--accent-muted);color:var(--accent);}
.chat-msg__avatar--user{background:var(--surface-2);color:var(--text-2);}
.chat-msg__avatar--assistant{background:linear-gradient(135deg,var(--accent-muted),rgba(139,92,246,0.15));color:var(--accent);}
.chat-msg__avatar--error{background:var(--error-muted);color:var(--error);}

.chat-msg__body{flex:1;min-width:0;}
.chat-msg__meta{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:2px;}
.chat-msg__name{font-size:12px;font-weight:600;color:var(--text-1);}
.chat-msg__time{font-size:11px;color:var(--text-4);}
.chat-msg__text{font-size:13px;line-height:1.65;color:var(--text-1);word-break:break-word;}
.chat-msg__text strong{font-weight:600;color:var(--text-0);}
.chat-msg__text code{font-family:var(--font-mono);font-size:12px;padding:1px 5px;background:var(--surface-2);border:1px solid var(--border-0);border-radius:var(--radius-xs);color:var(--accent);}

/* Chat progress */
.chat-progress{margin-top:var(--sp-2);display:flex;flex-direction:column;gap:var(--sp-2);}
.chat-progress__bar{height:3px;background:var(--bg-4);border-radius:var(--radius-full);overflow:hidden;margin-top:var(--sp-1);}
.chat-progress__fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:var(--radius-full);transition:width var(--duration-slow) var(--ease-out);width:0%;}
.chat-progress__fill--indeterminate{width:40%!important;animation:indeterminate 1.5s ease-in-out infinite;}
@keyframes indeterminate{0%{transform:translateX(-100%);}100%{transform:translateX(350%);}}
.chat-progress__steps{display:flex;flex-direction:column;gap:2px;}
.chat-progress__step{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-family:var(--font-mono);color:var(--text-3);transition:color var(--duration-fast);animation:fadeIn var(--duration-base) var(--ease-out);}
.chat-progress__step--active{color:var(--info);}
.chat-progress__step--done{color:var(--success);}
.chat-progress__step--error{color:var(--error);}
.chat-progress__icon{width:16px;height:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}

/* Typing */
.chat-typing{display:flex;align-items:center;gap:4px;padding:var(--sp-2) 0;}
.chat-typing__dot{width:5px;height:5px;border-radius:50%;background:var(--text-4);animation:typingBounce 1.4s ease-in-out infinite;}
.chat-typing__dot:nth-child(2){animation-delay:0.2s;}
.chat-typing__dot:nth-child(3){animation-delay:0.4s;}
@keyframes typingBounce{0%,60%,100%{transform:translateY(0);opacity:0.3;}30%{transform:translateY(-6px);opacity:1;}}

/* Chat input */
.chat-input-area{border-top:1px solid var(--border-0);padding:var(--sp-3) var(--sp-4);flex-shrink:0;}
.chat-suggestions{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-3);flex-wrap:wrap;}
.chat-suggestions:empty,.chat-suggestions[hidden]{display:none;}
.suggestion-chip{padding:var(--sp-1) var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-3);font-size:12px;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.suggestion-chip:hover{background:var(--accent-muted);border-color:rgba(99,102,241,0.3);color:var(--accent);}

.chat-form{position:relative;}
.chat-form__input-wrap{display:flex;align-items:flex-end;gap:var(--sp-2);background:var(--surface-1);border:1px solid var(--border-1);border-radius:var(--radius-md);padding:var(--sp-2) var(--sp-3);transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.chat-form__input-wrap:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.chat-form__input{flex:1;border:none;background:transparent;color:var(--text-0);font-family:var(--font-sans);font-size:13px;line-height:1.5;resize:none;outline:none;min-height:20px;max-height:120px;}
.chat-form__input::placeholder{color:var(--text-4);}
.chat-form__send{display:flex;align-items:center;justify-content:center;width:32px;height:32px;border:none;border-radius:var(--radius-sm);background:var(--accent);color:white;cursor:pointer;flex-shrink:0;transition:all var(--duration-fast) var(--ease-out);}
.chat-form__send:disabled{opacity:0.3;cursor:not-allowed;}
.chat-form__send:not(:disabled):hover{background:var(--accent-hover);transform:scale(1.05);}
.chat-form__send:not(:disabled):active{transform:scale(0.98);}
.chat-form__hint{font-size:11px;color:var(--text-4);margin-top:var(--sp-2);text-align:right;}
.chat-form__hint kbd{font-family:var(--font-mono);font-size:10px;padding:1px 4px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:3px;color:var(--text-3);}

/* Results Panel */
.panel--results{min-height:200px;}
.results-tabs{display:flex;gap:0;padding:0 var(--sp-4);border-bottom:1px solid var(--border-0);overflow-x:auto;flex-shrink:0;}
.results-tabs:empty{display:none;}
.results-tabs::-webkit-scrollbar{display:none;}
.tab-btn{position:relative;padding:var(--sp-2) var(--sp-3);border:none;background:transparent;color:var(--text-3);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;white-space:nowrap;transition:color var(--duration-fast);}
.tab-btn:hover{color:var(--text-1);}
.tab-btn--active{color:var(--text-0);}
.tab-btn--active::after{content:'';position:absolute;bottom:-1px;left:var(--sp-3);right:var(--sp-3);height:2px;background:var(--accent);border-radius:1px 1px 0 0;animation:tabLine var(--duration-base) var(--ease-out);}
@keyframes tabLine{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.results-content{flex:1;overflow-y:auto;padding:var(--sp-4);min-height:0;}
.results-empty{display:flex;align-items:center;justify-content:center;height:100%;min-height:120px;color:var(--text-4);font-size:13px;text-align:center;}
.results-empty[hidden]{display:none;}
.result-card{animation:fadeIn var(--duration-slow) var(--ease-out);}
.metrics-grid{display:flex;flex-wrap:wrap;gap:var(--sp-2);}
.result-metric{display:inline-flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);min-width:130px;flex:1 1 130px;max-width:220px;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.result-metric:hover{border-color:var(--border-2);box-shadow:var(--shadow-sm);}
.result-metric__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;}
.result-metric__value{font-size:18px;font-weight:700;color:var(--text-0);font-family:var(--font-mono);letter-spacing:-0.03em;line-height:1.3;}
.result-metric__unit{font-size:11px;color:var(--text-3);font-weight:400;}

/* Energy diagram */
.energy-diagram{display:flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);margin-top:var(--sp-3);max-height:300px;overflow-y:auto;}
.energy-diagram__title{font-size:11px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:var(--sp-2);}
.energy-level{display:flex;align-items:center;gap:var(--sp-2);padding:3px var(--sp-2);border-radius:var(--radius-xs);font-size:11px;font-family:var(--font-mono);transition:background var(--duration-fast);}
.energy-level:hover{background:var(--surface-2);}
.energy-level--occupied{color:var(--accent);}
.energy-level--virtual{color:var(--text-3);}
.energy-level--homo{color:var(--accent);font-weight:600;background:var(--accent-muted);}
.energy-level--lumo{color:var(--warning);font-weight:600;background:var(--warning-muted);}
.energy-level__bar{width:24px;height:3px;border-radius:2px;flex-shrink:0;}
.energy-level--occupied .energy-level__bar{background:var(--accent);}
.energy-level--virtual .energy-level__bar{background:var(--text-4);}
.energy-level--homo .energy-level__bar{background:var(--accent);height:4px;}
.energy-level--lumo .energy-level__bar{background:var(--warning);height:4px;}
.energy-level__label{min-width:60px;}
.energy-level__energy{flex:1;text-align:right;}
.energy-level__occ{min-width:28px;text-align:center;color:var(--text-4);font-size:10px;}

.result-table{width:100%;border-collapse:collapse;font-size:12px;}
.result-table th{text-align:left;font-weight:600;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;font-size:11px;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-1);position:sticky;top:0;background:var(--bg-2);}
.result-table td{padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);color:var(--text-1);font-family:var(--font-mono);font-size:12px;}
.result-table tr:hover td{background:var(--surface-1);}
.result-json{background:var(--bg-2);border:1px solid var(--border-0);border-radius:var(--radius-md);padding:var(--sp-4);overflow:auto;max-height:400px;font-family:var(--font-mono);font-size:12px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all;}
.result-note{font-size:12px;color:var(--text-3);margin-top:var(--sp-3);line-height:1.5;}

/* History */
.panel--history{min-height:200px;}
.history-search-wrap{position:relative;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);}
.history-search-icon{position:absolute;left:var(--sp-5);top:50%;transform:translateY(-50%);color:var(--text-4);pointer-events:none;}
.history-search{width:100%;padding:var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-8);border:1px solid var(--border-0);border-radius:var(--radius-sm);background:var(--surface-1);color:var(--text-1);font-size:12px;font-family:var(--font-sans);outline:none;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.history-search:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.history-search::placeholder{color:var(--text-4);}
.history-list{flex:1;overflow-y:auto;padding:var(--sp-2);}
.history-empty{display:flex;align-items:center;justify-content:center;min-height:80px;color:var(--text-4);font-size:12px;}
.history-empty[hidden]{display:none;}
.history-item{display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-2) var(--sp-3);border-radius:var(--radius-md);cursor:pointer;transition:background var(--duration-fast),border-color var(--duration-fast);border:1px solid transparent;animation:slideIn var(--duration-slow) var(--ease-out);}
.history-item:hover{background:var(--surface-1);}
.history-item--active{background:var(--accent-muted);border-color:rgba(99,102,241,0.25);}
.history-item__status{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.history-item__status--completed{background:var(--success);}
.history-item__status--running{background:var(--info);animation:pulse-dot 1.5s ease-in-out infinite;}
.history-item__status--failed{background:var(--error);}
.history-item__status--queued{background:var(--warning);}
.history-item__info{flex:1;min-width:0;}
.history-item__title{font-size:12px;font-weight:500;color:var(--text-1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__detail{font-size:11px;color:var(--text-4);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__energy{font-size:11px;font-family:var(--font-mono);color:var(--text-3);white-space:nowrap;flex-shrink:0;}

/* Modal */
.modal{border:none;background:transparent;padding:0;max-width:100vw;max-height:100vh;overflow:visible;}
.modal::backdrop{background:transparent;}
.modal__backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);z-index:0;animation:fadeIn var(--duration-base) var(--ease-out);}
.modal__content{position:relative;z-index:1;background:var(--bg-2);border:1px solid var(--border-1);border-radius:var(--radius-lg);box-shadow:var(--shadow-xl);width:440px;max-width:90vw;margin:15vh auto;animation:modalIn var(--duration-slow) var(--ease-out);}
.modal__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-4) var(--sp-5);border-bottom:1px solid var(--border-0);}
.modal__header h3{font-size:15px;font-weight:600;color:var(--text-0);}
.modal__body{padding:var(--sp-5);}
.shortcuts-grid{display:flex;flex-direction:column;gap:var(--sp-3);}
.shortcut-row{display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--text-2);}
.shortcut-keys{display:flex;align-items:center;gap:3px;}
.shortcut-plus,.shortcut-dash{font-size:11px;color:var(--text-4);}
.shortcut-row kbd{font-family:var(--font-mono);font-size:11px;padding:2px 6px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:var(--radius-xs);color:var(--text-1);min-width:22px;text-align:center;}
@keyframes modalIn{from{opacity:0;transform:translateY(-12px) scale(0.97);}to{opacity:1;transform:translateY(0) scale(1);}}

/* Animations */
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
@keyframes slideIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
@keyframes slideUp{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}

/* Fullscreen */
.panel--viewer.is-fullscreen{position:fixed;inset:0;z-index:var(--z-overlay);border-radius:0;margin:0;border:none;}
.panel--viewer.is-fullscreen .viewer-container{min-height:100%;}

/* Utils */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.mono{font-family:var(--font-mono);}
details{border:1px solid var(--border-0);border-radius:var(--radius-sm);padding:var(--sp-2) var(--sp-3);}
details summary{cursor:pointer;color:var(--text-3);font-size:12px;font-weight:500;user-select:none;}
details summary:hover{color:var(--text-1);}
details[open] summary{margin-bottom:var(--sp-2);}

/* ═══ 요구사항 2: Orbital/ESP 토글 버튼 ═══ */
.viz-mode-toggle { display: inline-flex; gap: 0; border: 1px solid var(--border-1); border-radius: 6px; overflow: hidden; margin: 0 8px; }
.viz-mode-toggle .toggle-btn { padding: 4px 14px; font-size: 12px; font-weight: 600; border: none; background: var(--bg-2); color: var(--text-2); cursor: pointer; transition: background 0.15s, color 0.15s; }
.viz-mode-toggle .toggle-btn:not(:last-child) { border-right: 1px solid var(--border-1); }
.viz-mode-toggle .toggle-btn.active { background: var(--accent); color: #fff; }
.viz-mode-toggle .toggle-btn:hover:not(.active) { background: var(--bg-3); }

/* ═══ 요구사항 3: Trajectory Player ═══ */
.trajectory-player { padding: 6px 12px; border-top: 1px solid var(--border-1); background: var(--bg-2); flex: 0 0 auto; z-index: 10; position: relative;}
.traj-controls { display: flex; align-items: center; gap: 8px; }
.traj-btn { width: 32px; height: 32px; border: 1px solid var(--border-1); border-radius: 6px; background: var(--bg-1); cursor: pointer; font-size: 14px; display: flex; align-items: center; justify-content: center; transition: background 0.15s; color: var(--text-1); }
.traj-btn:hover { background: var(--bg-3); }
.traj-slider { flex: 1; min-width: 100px; cursor: pointer; }
.traj-label { font-size: 11px; color: var(--text-3); white-space: nowrap; min-width: 220px; font-family: var(--font-mono); }

/* ═══ 요구사항 4: Session Tab Bar ═══ */
.session-tab-bar { display: flex; flex-wrap: nowrap; gap: 0; padding: 4px 8px 0; border-bottom: 1px solid var(--border-1); background: var(--bg-2); overflow-x: auto; overflow-y: hidden; flex: 0 0 auto; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }
.session-tab { position: relative; padding: 5px 26px 5px 10px; font-size: 11px; font-weight: 500; white-space: nowrap; border: 1px solid var(--border-1); border-bottom: none; border-radius: 6px 6px 0 0; background: var(--bg-3); color: var(--text-2); cursor: pointer; transition: background 0.15s, color 0.15s; flex: 0 0 auto; }
.session-tab.active { background: var(--bg-1); color: var(--text-1); border-bottom: 1px solid var(--bg-1); margin-bottom: -1px; font-weight: 600; }
.session-tab:hover:not(.active) { background: var(--bg-4); }
.session-tab-close { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; line-height: 14px; text-align: center; font-size: 13px; color: var(--text-3); border-radius: 3px; cursor: pointer; transition: background 0.1s, color 0.1s; }
.session-tab-close:hover { background: rgba(200, 50, 50, 0.15); color: #f43f5e; }

/* ═══ 요구사항 1: Loading Overlay ═══ */
.app-loader { position: fixed; inset: 0; z-index: 99999; display: flex; align-items: center; justify-content: center; background: var(--bg-1); transition: opacity 0.45s ease, visibility 0.45s ease; }
.app-loader.fade-out { opacity: 0; visibility: hidden; pointer-events: none; }
.loader-content { text-align: center; }
.loader-spinner { width: 48px; height: 48px; margin: 0 auto 18px; border: 4px solid var(--border-1); border-top-color: var(--accent); border-radius: 50%; animation: qcviz-loader-spin 0.75s linear infinite; }
@keyframes qcviz-loader-spin { to { transform: rotate(360deg); } }
.loader-text { font-size: 16px; font-weight: 600; color: var(--text-1); margin: 0 0 6px; }
.loader-sub { font-size: 12px; color: var(--text-3); margin: 0; }

/* ═══ 요구사항 3: Color Scheme 선택 UI ═══ */
.scheme-preview { display: inline-flex; gap: 3px; margin-left: 8px; vertical-align: middle; }
.swatch { display: inline-block; width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--border-1); }

```

이 지시서를 바탕으로 위 3가지 요구사항을 완벽하게 충족하는 수정된 코드 스니펫들을 작성하고, 기존 코드 어디에 덮어써야 할지 정확히 알려주세요.
