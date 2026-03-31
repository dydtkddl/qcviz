# 🚨 QCViz-MCP v5 프론트엔드 전면 재작성 및 총체적 진단/복구 작업 지시서

현재 시스템의 프론트엔드는 이전 AI 요원의 반복된 패치 실패와 땜질식 대응으로 인해 **모든 주요 기능이 완전히 붕괴된 상태**입니다. "ALL PASS"라고 선언했던 보고는 모두 거짓(거짓 양성)이었으며, 현재 다음과 같은 치명적인 상태입니다.

---

## 💥 1. 현재 직면한 치명적 버그 (User Report)
1. **ESP 버튼 먹통 및 지연 렌더링**: 초기 화면에서 ESP 버튼을 누르면 전혀 반응하지 않음. Orbital 버튼을 누른 후 다시 ESP로 돌아와야만 억지로 렌더링됨.
2. **Color Scheme 분리 현상**: Color Scheme 콤보박스를 변경해도 현재 보고 있는 ESP나 Orbital 화면에 즉시 적용되지 않고 서로 격리되어 놀고 있음.
3. **ESP 표면 중첩 (Overlapping)**: ESP와 Orbital 버튼을 번갈아 누르면 이전 프레임의 3D 표면이 지워지지 않고 계속 누적되어 화면이 떡칠됨.
4. **무한 로딩 및 History 소실**: 처음 앱 접속 시 로딩 스피너가 무한정 도는 경우가 생기며, 페이지 새로고침 시 기존에 수행했던 작업 내역(History)이 날아가고 복원되지 않음.
5. **세션 연속성 붕괴**: 여러 개의 분자 또는 여러 타입(HOMO, ESP)을 연속으로 질의하면 기존 결과를 덮어써버려 한 세션 내에서의 작업 비교가 불가능함.
6. **뷰어 비율 파괴 (Layout 찌그러짐)**: 결과가 로드되면 하단 패널들이 비대해져 정작 가장 중요한 3D Molecular Viewer가 위쪽으로 납작하게 찌그러짐.

---

## 🔎 2. 잠재적 문제 파헤치기 (Your Mission)
이전 AI 요원이 남긴 "조각난 코드들"을 전면 분석하여, **겉으로 드러난 현상 이면의 진짜 원인과 아직 터지지 않은 잠재적 버그를 낱낱이 파헤쳐야 합니다.**

*   **상태 관리(State)의 불일치**: `state.mode`, `state.result`, `state.viewer` 간의 동기화가 완전히 깨져있을 확률이 높습니다.
*   **3Dmol.js API 오용**: `voldata`, `volscheme`, `colorschememap` 등을 혼용하며 발생한 조용한 `TypeError`나 WebGL 컨텍스트 블로킹.
*   **비동기/이벤트 리스너 경쟁 상태**: `init()` 함수가 `DOMContentLoaded` 전에 호출되거나, WebSocket 이벤트(`jobs:changed`)가 DOM이 그려지기 전에 들어와 터지는 Race Condition.
*   **DOM 참조 에러**: `getElementById`로 가져온 객체가 `null`인데 예외 처리 없이 `addEventListener`를 붙이려다 전체 스크립트가 죽어버리는 현상 (무한 로딩의 주 원인).

---

## 📁 3. 전수조사를 위한 핵심 파일 소스 코드 덤프

아래에 현재 붕괴된 시스템의 핵심 프론트엔드 파일 3종의 **전체 코드**를 덤프해 두었습니다. 
이 코드를 바탕으로 문제를 진단하고, **완전히 새롭고 견고한 코드**로 다시 작성하여 제공해 주십시오.

### [1] `viewer.js` (3D 렌더링 및 모드 전환 핵심 결함 파일)
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
    classic: { label: "Classic (Blue/Red)", orbPositive: "#3b82f6", orbNegative: "#ef4444", espGradient: "rwb" },
    jmol: { label: "Jmol", orbPositive: "#1e40af", orbNegative: "#dc2626", espGradient: "rwb" },
    rwb: { label: "RWB (Red-White-Blue)", orbPositive: "#2563eb", orbNegative: "#dc2626", espGradient: "rwb" },
    bwr: { label: "BWR (Blue-White-Red)", orbPositive: "#dc2626", orbNegative: "#2563eb", espGradient: "rwb", reverse: true },
    spectral: { label: "Spectral", orbPositive: "#2b83ba", orbNegative: "#d7191c", espGradient: "sinebow" },
    viridis: { label: "Viridis", orbPositive: "#21918c", orbNegative: "#fde725", espGradient: "roygb" },
    inferno: { label: "Inferno", orbPositive: "#fcffa4", orbNegative: "#420a68", espGradient: "roygb" },
    coolwarm: { label: "Cool-Warm", orbPositive: "#4575b4", orbNegative: "#d73027", espGradient: "rwb" },
    purplegreen: { label: "Purple-Green", orbPositive: "#1b7837", orbNegative: "#762a83", espGradient: "rwb" },
    greyscale: { label: "Greyscale", orbPositive: "#f0f0f0", orbNegative: "#404040", espGradient: "rwb" },
  };

  function createGradient(type, min, max) {
      if (!window.$3Dmol) return null;
      if (type === "sinebow" && window.$3Dmol.Gradient.Sinebow) return new window.$3Dmol.Gradient.Sinebow(min, max);
      if (type === "roygb" && window.$3Dmol.Gradient.ROYGB) return new window.$3Dmol.Gradient.ROYGB(min, max);
      return new window.$3Dmol.Gradient.RWB(min, max);
  }

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

    var isDark = document.body.classList.contains("dark") || window.matchMedia("(prefers-color-scheme: dark)").matches;

    var charges = result.mulliken_charges || result.lowdin_charges || [];

    var maxAbs = 0;
    for (var k = 0; k < charges.length; k++) {
      var cv = charges[k];
      var cval = (cv != null && typeof cv === "object") ? cv.charge : cv;
      if (cval != null && isFinite(cval)) {
        var abs = Math.abs(cval);
        if (abs > maxAbs) maxAbs = abs;
      }
    }
    if (maxAbs < 0.001) maxAbs = 1; 

    atoms.forEach(function (a, i) {
      var el = a.element || a.symbol || a[0] || "";
      if (!el) return;

      var rawCharge = charges[i];
      var chargeVal = null;
      if (rawCharge != null) {
        chargeVal = (typeof rawCharge === "object") ? rawCharge.charge : rawCharge;
        if (chargeVal != null && !isFinite(chargeVal)) chargeVal = null;
      }

      var labelText = el;
      if (chargeVal != null) {
        var sign = chargeVal >= 0 ? "+" : "";
        labelText += " (" + sign + chargeVal.toFixed(3) + ")";
      }

      var bgColor, fontColor, borderColor;

      if (chargeVal != null && Math.abs(chargeVal) > 0.005) {
        var intensity = Math.min(Math.abs(chargeVal) / maxAbs, 1.0);
        var alpha = 0.25 + intensity * 0.55; 

        if (chargeVal > 0) {
          bgColor = "rgba(59, 130, 246, " + alpha.toFixed(2) + ")";
          fontColor = isDark ? "#dbeafe" : "#1e3a5f";
          borderColor = "rgba(59, 130, 246, 0.4)";
        } else {
          bgColor = "rgba(239, 68, 68, " + alpha.toFixed(2) + ")";
          fontColor = isDark ? "#fee2e2" : "#7f1d1d";
          borderColor = "rgba(239, 68, 68, 0.4)";
        }
      } else {
        fontColor = isDark ? "white" : "#333";
        bgColor = isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.7)";
        borderColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
      }

      viewer.addLabel(labelText, {
        position: {
          x: a.x != null ? a.x : (a[1] || 0),
          y: a.y != null ? a.y : (a[2] || 0),
          z: a.z != null ? a.z : (a[3] || 0),
        },
        fontSize: 11,
        fontColor: fontColor,
        backgroundColor: bgColor,
        borderColor: borderColor,
        borderThickness: 1,
        backgroundOpacity: 0.85,
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
      var cubeB64 = viz.orbital_cube_b64 || result.orbital_cube_b64 || (viz.orbital && viz.orbital.cube_b64) || null;

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
            color: scheme.orbNegative,
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
      var densB64 = viz.density_cube_b64 || result.density_cube_b64 || (viz.density && viz.density.cube_b64) || null;
      var espB64 = viz.esp_cube_b64 || result.esp_cube_b64 || (viz.esp && viz.esp.cube_b64) || null;

      try {
        if (densB64 && espB64) {
          var densVol = new window.$3Dmol.VolumeData(atob(densB64), "cube");
          var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          var range = result.esp_auto_range_au || 0.05;
          var scheme = getCurrentColorScheme();
          var minVal = scheme.reverse ? range : -range;
          var maxVal = scheme.reverse ? -range : range;
          var grad = createGradient(scheme.espGradient, minVal, maxVal);
          viewer.addIsosurface(densVol, {
            isoval: state.espDensityIso || 0.001,
            color: "white",
            alpha: state.opacity,
            smoothness: 1,
            voldata: espVol,
            volscheme: grad
          });
        } else if (espB64) {
          var espVol2 = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          var scheme2 = getCurrentColorScheme();
          var minVal2 = scheme2.reverse ? 0.05 : -0.05;
          var maxVal2 = scheme2.reverse ? -0.05 : 0.05;
          var grad2 = createGradient(scheme2.espGradient, minVal2, maxVal2);
          viewer.addIsosurface(espVol2, {
            isoval: state.espDensityIso || 0.001,
            volscheme: grad2,
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

    if (mode === "orbital") showOrbitalLegend();
    else if (mode === "esp") showESPLegend();
    else if ($legend) $legend.hidden = true;
  }

  function updateToggleHighlight(mode) {
    var $btnOrb = document.getElementById("btnModeOrbital");
    var $btnEsp = document.getElementById("btnModeESP");
    if ($btnOrb) $btnOrb.classList.toggle("active", mode === "orbital");
    if ($btnEsp) $btnEsp.classList.toggle("active", mode === "esp");
  }

  var _vizSwitchLock = false;

  var _vizSwitchLock = false;

  function switchVizMode(newMode) {
    if (!state.result) return;
    if (_vizSwitchLock) return;
    
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
          var viz = result.visualization || {};
          var cubeB64 = viz.orbital_cube_b64 || result.orbital_cube_b64 || (viz.orbital && viz.orbital.cube_b64) || null;
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
          
          if (espB64) {
              var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
              var densVol = densB64 ? new window.$3Dmol.VolumeData(atob(densB64), "cube") : espVol;
              var range = result.esp_auto_range_au || 0.05;
              var minVal = scheme.reverse ? range : -range;
              var maxVal = scheme.reverse ? -range : range;
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
  
  function getGradientCSS(schemeObj) {
    var grad = schemeObj.espGradient;
    var rev = schemeObj.reverse;
    if (grad === "rwb") {
        return rev ? "linear-gradient(90deg, #3b82f6, #ffffff, #ef4444)" : "linear-gradient(90deg, #ef4444, #ffffff, #3b82f6)";
    }
    if (grad === "bwr") {
        return rev ? "linear-gradient(90deg, #ef4444, #ffffff, #3b82f6)" : "linear-gradient(90deg, #3b82f6, #ffffff, #ef4444)";
    }
    if (grad === "sinebow") {
        return rev ? "linear-gradient(90deg, #ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff)" : "linear-gradient(90deg, #ff0000, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)";
    }
    if (grad === "roygb") {
        return rev ? "linear-gradient(90deg, #0000ff, #00ff00, #ffff00, #ff0000)" : "linear-gradient(90deg, #ff0000, #ffff00, #00ff00, #0000ff)";
    }
    // fallback
    return "linear-gradient(90deg, #ef4444, #ffffff, #3b82f6)";
  }

  function updateLegendColors() {
    if (!$legend || $legend.hidden) return;
    var scheme = getCurrentColorScheme();
    if (state.mode === "orbital") {
      var swatches = $legend.querySelectorAll(".viewer-legend__swatch");
      if (swatches[0]) swatches[0].style.background = scheme.orbPositive;
      if (swatches[1]) swatches[1].style.background = scheme.orbNegative;
    } else if (state.mode === "esp") {
      var swatch = $legend.querySelector(".viewer-legend__swatch");
      if (swatch) {
          swatch.style.background = getGradientCSS(scheme);
      }
    }
  }

  function showOrbitalLegend() {
    if (!$legend) return;
    var scheme = getCurrentColorScheme();
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">Orbital Lobes</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:' + scheme.orbPositive + '"></span>' +
        '<span>Positive (+' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:' + scheme.orbNegative + '"></span>' +
        '<span>Negative (−' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>';
  }
  function showESPLegend() {
    if (!$legend) return;
    var scheme = getCurrentColorScheme();
    var gradCSS = getGradientCSS(scheme);
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">ESP Surface</div>' +
      '<div class="viewer-legend__row" style="display:flex; justify-content:center; width:100%; margin-top:4px;">' +
        '<span class="viewer-legend__swatch" style="background:' + gradCSS + ';width:100px;height:12px;border-radius:3px;box-shadow:inset 0 0 2px rgba(0,0,0,0.2);"></span>' +
      '</div>' +
      '<div class="viewer-legend__row" style="display:flex; justify-content:space-between; width:100px; margin:2px auto 0 auto;">' +
        '<span style="font-size:11px;font-weight:600;color:var(--text-3)">−</span>' +
        '<span style="font-size:10px;font-weight:500;color:var(--text-4)">0</span>' +
        '<span style="font-size:11px;font-weight:600;color:var(--text-3)">+</span>' +
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

    if ($btnLabels) {
      $btnLabels.addEventListener("click", function () {
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
    if ($btnLabels) {
      $btnLabels.setAttribute("data-active", String(state.showLabels));
      $btnLabels.setAttribute("aria-pressed", String(state.showLabels));
      $btnLabels.textContent = state.showLabels ? "On" : "Off";
    }
  }

  function init() {
    bindStyleButtons();
    bindReactiveControls();
    syncButtonState();
    
    var $selectColor = document.getElementById("selectColorScheme");
    if ($selectColor) {
      $selectColor.addEventListener("change", function () {
        if (!COLOR_SCHEMES[$selectColor.value]) return;

        state.colorScheme = $selectColor.value;
        updateSchemePreview();
        updateLegendColors();

        if (state.result) {
          var currentMode = state.mode;
          if (currentMode === "orbital" || currentMode === "esp") {
            state.mode = "none";
            switchVizMode(currentMode);
          }
        }
        saveViewerSnapshot();
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

### [2] `app.js` (앱 초기화, History, 세션 탭 결함 파일)
```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — App Orchestrator
   Theme, shortcuts, history, status sync, init
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var PREFIX = App.apiPrefix || "/api";

  /* ─── DOM ─── */
  var $statusDot = document.querySelector("#globalStatus .status-indicator__dot");
  var $statusText = document.querySelector("#globalStatus .status-indicator__text");
  var $themeBtn = document.getElementById("btnThemeToggle");
  var $shortcutsBtn = document.getElementById("btnKeyboardShortcuts");
  var $shortcutsModal = document.getElementById("modalShortcuts");
  var $historyList = document.getElementById("historyList");
  var $historyEmpty = document.getElementById("historyEmpty");
  var $historySearch = document.getElementById("historySearch");
  var $btnRefresh = document.getElementById("btnRefreshHistory");
  var $chatInput = document.getElementById("chatInput");

  /* ─── Global Status ─── */
  App.on("status:changed", function (s) {
    if ($statusDot) $statusDot.setAttribute("data-kind", s.kind || "idle");
    if ($statusText) $statusText.textContent = s.text || "Ready";

    if (s.kind === "success" || s.kind === "completed") {
      setTimeout(function () {
        if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
          App.setStatus("Ready", "idle", "app");
        }
      }, 4000);
    }
  });

  /* ─── Theme Toggle ─── */
  if ($themeBtn) {
    $themeBtn.addEventListener("click", function () {
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
    });
  }

  /* ─── Modal Helpers ─── */
  function openModal(dialog) {
    if (!dialog) return;
    dialog.showModal();
  }
  function closeModal(dialog) {
    if (!dialog) return;
    dialog.close();
  }

  if ($shortcutsBtn) {
    $shortcutsBtn.addEventListener("click", function () { openModal($shortcutsModal); });
  }

  if ($shortcutsModal) {
    $shortcutsModal.addEventListener("click", function (e) {
      if (e.target.hasAttribute("data-close") || e.target.closest("[data-close]")) {
        closeModal($shortcutsModal);
      }
    });
  }

  /* ─── Keyboard Shortcuts ─── */
  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    var isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    // Ctrl+/ → Focus chat
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      if ($chatInput) $chatInput.focus();
      return;
    }

    // Ctrl+K → Focus history search
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if ($historySearch) $historySearch.focus();
      return;
    }

    // Ctrl+\ → Toggle theme
    if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
      e.preventDefault();
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
      return;
    }

    // Escape
    if (e.key === "Escape") {
      if ($shortcutsModal && $shortcutsModal.open) {
        closeModal($shortcutsModal);
        return;
      }
      if (isTyping) {
        document.activeElement.blur();
        return;
      }
    }

    // ? → Show shortcuts
    if (e.key === "?" && !isTyping) {
      openModal($shortcutsModal);
    }
  });

  /* ─── History Panel ─── */
  var historyFilter = "";

  function getJobDisplayName(job) {
    if (job.user_query && typeof job.user_query === "string" && job.user_query.trim()) {
      var q = job.user_query.trim();
      return q.length > 40 ? q.substring(0, 40) + "\u2026" : q;
    }
    
    var molName = job.molecule_name || job.molecule || (job.result && (job.result.structure_name || job.result.structure_query)) || (job.payload && (job.payload.structure_query || job.payload.molecule_name || job.payload.molecule));
    var method = job.method || (job.result && job.result.method) || (job.payload && job.payload.method) || "";
    var basis = job.basis_set || (job.result && job.result.basis_set) || (job.payload && job.payload.basis_set) || "";
    var jobType = job.job_type || (job.result && job.result.job_type) || (job.payload && job.payload.job_type) || "computation";

    if (molName) {
        var name = molName;
        if (jobType === "orbital_preview" || jobType === "orbital") {
             var orb = job.orbital || (job.payload && job.payload.orbital);
             if (orb) name = orb + " of " + name;
             else name = "Orbital of " + name;
        } else if (jobType === "esp_map" || jobType === "esp") {
             name = "ESP of " + name;
        }
        return name.length > 40 ? name.substring(0, 40) + "\u2026" : name;
    }
    
    if (method || basis) return [method, basis].filter(Boolean).join(" / ");
    
    // Nice fallback instead of ugly ID
    var prettyType = jobType.replace(/_/g, " ");
    return prettyType.charAt(0).toUpperCase() + prettyType.slice(1);
  }

  function getJobDetailLine(job) {
    var parts = [];
    var jobType = job.job_type || (job.payload && job.payload.job_type) || "";
    if (jobType) parts.push(jobType);
    var method = job.method || job.result && job.result.method || (job.payload && job.payload.method) || "";
    if (method) parts.push(method);
    var basis = job.basis_set || job.result && job.result.basis_set || (job.payload && job.payload.basis_set) || "";
    if (basis) parts.push(basis);
    if (parts.length > 0) return parts.join(" \u00B7 ");

    // Fallback to timestamp
    var ts = job.submitted_at || job.created_at || job.updated_at;
    if (ts) {
      var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " +
        d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }
    return "\u2014";
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function escAttr(s) {
    return String(s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderHistory() {
    if (!$historyList) return;

    var jobs = App.store.jobOrder.map(function (id) { return App.store.jobsById[id]; }).filter(Boolean);

    var filtered = jobs;
    if (historyFilter) {
      var q = historyFilter.toLowerCase();
      filtered = jobs.filter(function (j) {
        var searchable = [
          j.user_query || "",
          j.molecule_name || "",
          j.molecule || "",
          j.method || "",
          j.basis_set || "",
          j.job_id || "",
          (j.payload && j.payload.molecule) || "",
          (j.payload && j.payload.method) || "",
        ].join(" ").toLowerCase();
        return searchable.indexOf(q) !== -1;
      });
    }

    // Remove old items
    var oldItems = $historyList.querySelectorAll(".history-item");
    oldItems.forEach(function (el) { el.remove(); });

    if (filtered.length === 0) {
      if ($historyEmpty) {
        $historyEmpty.hidden = false;
        var p = $historyEmpty.querySelector("p");
        if (p) p.textContent = historyFilter ? "No matching jobs" : "No previous computations";
      }
      return;
    }

    if ($historyEmpty) $historyEmpty.hidden = true;

    var activeJobId = App.store.activeJobId;
    var html = "";

    filtered.forEach(function (job) {
      var id = job.job_id || "";
      var status = job.status || "queued";
      var name = getJobDisplayName(job);
      var detail = getJobDetailLine(job);
      var energy = job.result ? (job.result.total_energy_hartree != null ? job.result.total_energy_hartree : job.result.energy) : null;
      var energyStr = energy != null ? Number(energy).toFixed(4) + " Ha" : "";
      var isActive = id === activeJobId;

      html += '<div class="history-item' + (isActive ? ' history-item--active' : '') + '" data-job-id="' + escAttr(id) + '">' +
        '<span class="history-item__status history-item__status--' + escAttr(status) + '"></span>' +
        '<div class="history-item__info">' +
        '<div class="history-item__title">' + esc(name) + '</div>' +
        '<div class="history-item__detail">' + esc(detail) + '</div>' +
        '</div>' +
        (energyStr ? '<span class="history-item__energy">' + esc(energyStr) + '</span>' : '') +
        '</div>';
    });

    if ($historyEmpty) {
      $historyEmpty.insertAdjacentHTML("beforebegin", html);
    } else {
      $historyList.innerHTML = html;
    }
  }

  // History click
  if ($historyList) {
    $historyList.addEventListener("click", function (e) {
      var item = e.target.closest(".history-item");
      if (!item) return;
      var jobId = item.dataset.jobId;
      if (!jobId) return;
      App.setActiveJob(jobId);
      renderHistory();
    });
  }

  // History search
  if ($historySearch) {
    $historySearch.addEventListener("input", function () {
      historyFilter = $historySearch.value.trim();
      renderHistory();
    });
  }

  // Fetch history from server
  function fetchHistory() {
    return fetch(PREFIX + "/compute/jobs?include_result=true")
      .then(function (res) {
        if (!res.ok) return;
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        var jobs = Array.isArray(data) ? data : (data.items || data.jobs || []);
        
        // Reverse array to insert oldest first so that prepend keeps the newest at the top
        // OR simply call upsertJob which manages sorting internally via store.jobOrder.
        var sortedJobs = jobs.sort(function(a, b) { return a.created_at - b.created_at; });
        sortedJobs.forEach(function (j) { App.upsertJob(j); });
        
        // Ensure UI catches up
        renderHistory();
      })
      .catch(function (e) {
        console.error("fetchHistory error:", e);
      });
  }

  if ($btnRefresh) {
    $btnRefresh.addEventListener("click", function () {
      $btnRefresh.classList.add("is-spinning");
      fetchHistory().then(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      }).catch(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      });
    });
  }


  /* ─── Session Tabs ─── */
  var $sessionTabsContainer = document.getElementById("sessionTabsContainer");
  var $sessionTabs = document.getElementById("sessionTabs");

  function renderSessionTabs() {
    if (!$sessionTabs || !$sessionTabsContainer) return;
    var maxTabs = 15;
    var order = App.store.jobOrder.slice(0, maxTabs);
    
    if (order.length === 0) {
      $sessionTabsContainer.hidden = true;
      return;
    }
    
    $sessionTabsContainer.hidden = false;
    var html = "";
    
    order.forEach(function (id) {
      var job = App.store.jobsById[id];
      if (!job) return;
      
      var isActive = id === App.store.activeJobId;
      var name = job.molecule_name || job.user_query || id;
      if (name.length > 20) name = name.substring(0, 20) + "...";
      
      var method = job.method || "";
      var badge = "";
      if (job.status === "running") badge = " ⏳";
      else if (job.status === "failed") badge = " ❌";
      
      var displayStr = name + (method ? " (" + method + ")" : "") + badge;
      
      html += '<div class="session-tab' + (isActive ? ' session-tab--active' : '') + '" data-job-id="' + escAttr(id) + '" title="' + escAttr(job.user_query || "") + '">' +
              esc(displayStr) +
              '</div>';
    });
    
    $sessionTabs.innerHTML = html;
  }

  if ($sessionTabs) {
    $sessionTabs.addEventListener("click", function(e) {
      var tab = e.target.closest(".session-tab");
      if (!tab) return;
      var jid = tab.getAttribute("data-job-id");
      if (jid && jid !== App.store.activeJobId) {
        App.setActiveJob(jid);
      }
    });
  }

  App.on("jobs:changed", function () {
    renderHistory();
    renderSessionTabs();
  });

  App.on("activeJob:changed", function () {
    renderHistory();
    renderSessionTabs();
  });


  /* ─── Init ─── */
  fetchHistory();
  renderHistory();

  console.log(
    "%c QCViz-MCP Enterprise v5 %c Loaded ",
    "background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-weight:bold;padding:3px 8px;border-radius:4px 0 0 4px;",
    "background:#18181b;color:#a1a1aa;padding:3px 8px;border-radius:0 4px 4px 0;"
  );

})();
```

### [3] `style.css` (레이아웃 찌그러짐 및 범례 디자인 결함 파일)
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
.dashboard{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(450px,1.8fr) minmax(200px,0.6fr);grid-template-areas:"viewer chat" "results history";gap:var(--sp-3);flex:1;min-height:0;}
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

/* ═══════════════════════════════════════════════════════════
   Butterfly Chart — Charges Visualization
   ═══════════════════════════════════════════════════════════ */

.butterfly-legend { display: flex; align-items: center; gap: var(--sp-4); padding: var(--sp-2) 0; margin-bottom: var(--sp-3); font-size: 11px; color: var(--text-2); }
.butterfly-legend__item { display: inline-flex; align-items: center; gap: var(--sp-1); }
.butterfly-legend__swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--border-0); }
.butterfly-legend__swatch--neg { background: var(--error); }
.butterfly-legend__swatch--pos { background: var(--info); }
.butterfly-chart { display: flex; flex-direction: column; gap: 3px; }
.butterfly-row { display: grid; grid-template-columns: 1fr 56px 1fr; align-items: center; gap: 0; min-height: 26px; transition: background var(--duration-fast); border-radius: var(--radius-xs); padding: 1px 0; }
.butterfly-row:hover { background: var(--surface-1); }
.butterfly-label { display: flex; align-items: center; justify-content: center; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-0); text-align: center; padding: 0 4px; background: var(--surface-0); border-left: 1px solid var(--border-1); border-right: 1px solid var(--border-1); min-height: 26px; z-index: 1; }
.butterfly-label__idx { font-size: 10px; font-weight: 400; color: var(--text-4); font-family: var(--font-mono); }
.butterfly-label__el { font-family: var(--font-sans); }
.butterfly-bar-area { position: relative; display: flex; flex-direction: column; gap: 1px; height: 100%; justify-content: center; }
.butterfly-bar-area--neg { align-items: flex-end; padding-right: 0; }
.butterfly-bar-area--pos { align-items: flex-start; padding-left: 0; }
.butterfly-bar { height: 16px; border-radius: 2px; min-width: 2px; max-width: 100%; position: relative; transition: width var(--duration-base) var(--ease-out), opacity var(--duration-fast); cursor: default; }
.butterfly-bar:hover { opacity: 0.85; }
.butterfly-bar--neg-primary { background: linear-gradient(270deg, var(--error), rgba(239, 68, 68, 0.6)); border-radius: 2px 0 0 2px; }
.butterfly-bar--neg-secondary { background: rgba(239, 68, 68, 0.3); border: 1px solid rgba(239, 68, 68, 0.4); height: 8px; border-radius: 2px 0 0 2px; }
.butterfly-bar--pos-primary { background: linear-gradient(90deg, var(--info), rgba(59, 130, 246, 0.6)); border-radius: 0 2px 2px 0; }
.butterfly-bar--pos-secondary { background: rgba(59, 130, 246, 0.3); border: 1px solid rgba(59, 130, 246, 0.4); height: 8px; border-radius: 0 2px 2px 0; }
.butterfly-bar__val { position: absolute; top: 50%; transform: translateY(-50%); font-size: 10px; font-family: var(--font-mono); color: var(--text-0); white-space: nowrap; pointer-events: none; text-shadow: 0 0 3px var(--bg-0); }
.butterfly-bar-area--neg .butterfly-bar__val { left: 4px; }
.butterfly-bar-area--pos .butterfly-bar__val { right: 4px; }
.butterfly-bar[style*="width:0"] .butterfly-bar__val, .butterfly-bar[style*="width:1"] .butterfly-bar__val, .butterfly-bar[style*="width:2"] .butterfly-bar__val, .butterfly-bar[style*="width:3"] .butterfly-bar__val { color: var(--text-2); }
@media (max-width: 600px) { .butterfly-row { grid-template-columns: 1fr 44px 1fr; } .butterfly-label { font-size: 11px; } .butterfly-bar__val { font-size: 9px; } }

.butterfly-axis { display: grid; grid-template-columns: 1fr 1fr 56px 1fr 1fr; margin-bottom: 4px; padding: 0; }
.axis-tick { font-size: 10px; color: var(--text-4); font-family: var(--font-mono); position: relative; }
.axis-tick:nth-child(1) { text-align: left; }
.axis-tick:nth-child(2) { text-align: right; margin-right: 4px;}
.center-tick { text-align: center; color: var(--text-3); font-weight: bold; border-left: 1px dashed var(--border-1); border-right: 1px dashed var(--border-1); background: var(--surface-0); border-radius: 2px;}
.axis-tick:nth-child(4) { text-align: left; margin-left: 4px; }
.axis-tick:nth-child(5) { text-align: right; }

.butterfly-chart {
  border-top: 1px dashed var(--border-1);
  padding-top: 4px;
}

/* Session Tabs */
.session-tabs-container {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--surface-0);
  border-bottom: 1px solid var(--border-0);
  overflow-x: auto;
  white-space: nowrap;
}
.session-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-full);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.session-tab:hover {
  background: var(--surface-2);
  color: var(--text-1);
}
.session-tab--active {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.4);
  color: var(--accent);
}
.session-tab__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-left: 2px;
}
.session-tab__close:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--error);
}
```


---

## 🛠️ 4. 새로운 AI 요원을 위한 최종 지시사항 (Action Directives)

당신(새로운 LLM)은 이 처참한 코드를 건네받았습니다. 땜질식 처방을 버리고 다음 5대 원칙을 기반으로 **견고한 코드를 재설계**하여 주십시오.

1.  **3D 렌더링 파이프라인의 재구축 (`viewer.js`)**: 
    - `switchVizMode`와 `renderESP`, `renderOrbital`의 역할을 명확히 분리하십시오. 
    - 이전 표면을 확실하게 제거하는 로직(`removeAllSurfaces`, 강제 `render`)을 동기적으로 보장하고, 3Dmol.js의 최신/안전한 Gradient API 규격에 맞춰 Color Scheme이 ESP와 Orbital 양쪽에 즉각 반영되도록 작성하십시오.
2.  **안전한 앱 초기화 및 상태 동기화 (`app.js`)**: 
    - 무한 로딩을 유발하는 모든 `ReferenceError` 가능성을 차단하고, DOMContentLoaded와 데이터 Fetch의 순서를 엄격히 제어하십시오.
    - History가 로컬에 정상적으로 캐싱 및 복원되게 하며, 상단의 Session Tabs를 클릭할 때마다 뷰어와 하단 결과 탭이 꼬임 없이 동기화되게 하십시오.
3.  **반응형 레이아웃 방어 (`style.css`)**: 
    - 화면 크기가 줄어들거나 하단 탭 내용이 길어져도 상단의 3D 분자 뷰어가 최소 50% 이상의 면적을 유지하도록 Grid/Flex 비율(`1.8fr` 등)과 `min-height`를 철통같이 설정하십시오.
4.  **강건성(Robustness) 및 엣지 케이스 방어**: 
    - 널 포인터, 정의되지 않은 객체 참조, 데이터 중첩 구조(`viz.esp.cube_b64` 등) 파싱 누락 등의 잠재적 폭탄을 남김없이 찾아내고, `try-catch`와 옵셔널 체이닝, 기본값 폴백(`||`)으로 방어하십시오.
5. **결과물 제공 방식**:
    - 문제를 진단한 **원인 분석 리포트**를 먼저 작성하고.
    - 그 아래에 교체해야 할 `viewer.js`, `app.js`, `style.css`의 **전체 코드(또는 핵심 교체 블록)**를 마크다운 코드 블록으로 깨끗하게 제공해 주십시오.
