/**
 * QCViz-MCP v3 — 3D Molecular Viewer
 * FIX(M8): CDN 3개 순차 재시도, 100ms 디바운스, viewerReady 큐잉,
 *          xyz/molecule_xyz→xyz_block 키 매핑
 */
(function (g) {
  "use strict";
  console.log("[viewer.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[viewer.js] ✖ QCVizApp not found — aborting viewer module");
    return;
  }
  console.log("[viewer.js] ✔ QCVizApp found, __v3:", App.__v3);

  // ─── 상수 ──────────────────────────────────────────
  var CDN_URLS = [
    "https://3Dmol.org/build/3Dmol-min.js",
    "https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js",
    "https://unpkg.com/3dmol@2.4.2/build/3Dmol-min.js",
  ];

  var DEBOUNCE_MS = 100;
  var viewerReady = false;
  var viewer = null;
  var pendingUpdate = null;
  var debounceTimer = null;
  var currentResult = null;
  var currentMode = "orbital";

  // ─── DOM refs ──────────────────────────────────────
  var viewer3d = document.getElementById("viewer3d");
  var viewerEmpty = document.getElementById("viewerEmpty");
  var viewerControls = document.getElementById("viewerControls");
  var viewerLegend = document.getElementById("viewerLegend");
  var vizModeToggle = document.getElementById("vizModeToggle");
  var btnViewerReset = document.getElementById("btnViewerReset");
  var btnViewerScreenshot = document.getElementById("btnViewerScreenshot");
  var btnViewerFullscreen = document.getElementById("btnViewerFullscreen");
  var btnModeOrbital = document.getElementById("btnModeOrbital");
  var btnModeESP = document.getElementById("btnModeESP");
  var segStyle = document.getElementById("segStyle");
  var sliderIsovalue = document.getElementById("sliderIsovalue");
  var lblIsovalue = document.getElementById("lblIsovalue");
  var sliderEspDensIso = document.getElementById("sliderEspDensIso");
  var lblEspDensIso = document.getElementById("lblEspDensIso");
  var sliderOpacity = document.getElementById("sliderOpacity");
  var lblOpacity = document.getElementById("lblOpacity");
  var btnToggleLabels = document.getElementById("btnToggleLabels");
  var grpOrbital = document.getElementById("grpOrbital");
  var grpESP = document.getElementById("grpESP");
  var grpOpacity = document.getElementById("grpOpacity");
  var selectColorScheme = document.getElementById("selectColorScheme");
  var grpColorScheme = document.getElementById("grpColorScheme");
  var selectOrbital = document.getElementById("selectOrbital");
  var grpOrbitalSelect = document.getElementById("grpOrbitalSelect");

  // Trajectory controls DOM refs
  var grpTrajectory = document.getElementById("grpTrajectory");
  var btnTrajPlay = document.getElementById("btnTrajPlay");
  var sliderTrajFrame = document.getElementById("sliderTrajFrame");
  var lblTrajFrame = document.getElementById("lblTrajFrame");
  var lblTrajEnergy = document.getElementById("lblTrajEnergy");

  // Trajectory state
  var trajFrames = [];  // array of { step, energy_hartree, grad_norm, xyz }
  var trajPlaying = false;
  var trajInterval = null;

  // Color scheme mapping: name → { pos, neg } for orbital, gradient+invert for ESP
  // 3Dmol supports gradients: "rwb", "roygb", "sinebow"
  var COLOR_SCHEMES = {
    classic: { pos: "blue",    neg: "red",     gradient: "rwb",     invert: false },
    jmol:    { pos: "#3050F8", neg: "#FF8000", gradient: "roygb",   invert: false },  // deep blue / orange
    rwb:     { pos: "#0000CC", neg: "#CC0000", gradient: "rwb",     invert: false },  // darker blue / darker red
    bwr:     { pos: "#CC0000", neg: "#0000CC", gradient: "rwb",     invert: true  },  // swapped: red=pos, blue=neg
    spectral:{ pos: "#2B83BA", neg: "#D7191C", gradient: "sinebow", invert: false },  // teal / crimson
    viridis: { pos: "#21918C", neg: "#FDE725", gradient: "roygb",   invert: true  },  // teal / yellow
    inferno: { pos: "#BB3754", neg: "#FCFFA4", gradient: "sinebow", invert: true  },  // magenta / light yellow
  };

  function getColorScheme() {
    var val = selectColorScheme ? selectColorScheme.value : "classic";
    return COLOR_SCHEMES[val] || COLOR_SCHEMES.classic;
  }

  console.log("[viewer.js] DOM refs:", {
    viewer3d: !!viewer3d, viewerEmpty: !!viewerEmpty,
    viewerControls: !!viewerControls, vizModeToggle: !!vizModeToggle,
    segStyle: !!segStyle, sliderIsovalue: !!sliderIsovalue,
    sliderEspDensIso: !!sliderEspDensIso, sliderOpacity: !!sliderOpacity,
    btnModeOrbital: !!btnModeOrbital, btnModeESP: !!btnModeESP,
    selectColorScheme: !!selectColorScheme, selectOrbital: !!selectOrbital,
  });

  // ─── 유틸 ──────────────────────────────────────────

  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function show(el) {
    if (el) el.removeAttribute("hidden");
  }
  function hide(el) {
    if (el) el.setAttribute("hidden", "");
  }

  // ─── Style helpers ─────────────────────────────────
  function getActiveStyle() {
    if (segStyle) {
      var activeBtn = segStyle.querySelector(".segmented__btn--active");
      if (activeBtn) return activeBtn.getAttribute("data-value") || "stick";
    }
    return "stick";
  }

  function applyStyle(style) {
    if (!viewer) return;
    var styleMap = {
      stick:     { stick: { radius: 0.15 }, sphere: { scale: 0.25 } },
      ball_stick:{ stick: { radius: 0.12 }, sphere: { scale: 0.3 } },
      sphere:    { sphere: { scale: 0.6 } },
      line:      { line: { linewidth: 2 } },
    };
    viewer.setStyle({}, styleMap[style] || styleMap.stick);
  }

  // ─── 3Dmol 로딩 ───────────────────────────────────

  function load3Dmol(urls, idx) {
    idx = idx || 0;
    console.log("[viewer.js] load3Dmol — trying CDN", idx, "of", urls.length, ":", urls[idx]);
    if (idx >= urls.length) {
      console.error("[viewer.js] ✖ All CDN URLs failed, cannot load 3Dmol.js");
      if (viewerEmpty) {
        viewerEmpty.querySelector(".viewer-empty__text").textContent =
          "Failed to load 3D viewer library. / 3D 뷰어 라이브러리 로드 실패.";
      }
      show(viewerEmpty);
      return;
    }
    var script = document.createElement("script");
    script.src = urls[idx];
    script.onload = function () {
      console.log("[viewer.js] ✔ 3Dmol loaded from CDN", idx, ":", urls[idx]);
      initViewer();
    };
    script.onerror = function () {
      console.warn("[viewer.js] ✖ CDN", idx, "failed:", urls[idx], "— trying next");
      load3Dmol(urls, idx + 1);
    };
    document.head.appendChild(script);
  }

  function initViewer() {
    console.log("[viewer.js] initViewer — $3Dmol:", !!g.$3Dmol, "viewer3d:", !!viewer3d);
    if (!g.$3Dmol || !viewer3d) {
      console.error("[viewer.js] ✖ $3Dmol not available or viewer3d element missing");
      return;
    }

    viewer = g.$3Dmol.createViewer(viewer3d, {
      backgroundColor: "white",
      antialias: true,
    });
    viewerReady = true;
    console.log("[viewer.js] ✔ Viewer created, viewerReady=true");

    if (pendingUpdate) {
      console.log("[viewer.js] Processing queued pendingUpdate");
      var res = pendingUpdate;
      pendingUpdate = null;
      updateViewer(res);
    }
  }

  // ─── XYZ 키 매핑 ──────────────────────────────────

  function extractXyz(result) {
    if (!result) {
      console.log("[viewer.js] extractXyz — result is null/undefined");
      return null;
    }
    var viz = result.visualization || {};
    var xyz =
      viz.xyz_block || viz.xyz || viz.molecule_xyz ||
      result.xyz_block || result.xyz || result.molecule_xyz || null;

    console.log("[viewer.js] extractXyz — keys checked:", {
      "viz.xyz_block": !!viz.xyz_block, "viz.xyz": !!viz.xyz,
      "viz.molecule_xyz": !!viz.molecule_xyz,
      "result.xyz_block": !!result.xyz_block, "result.xyz": !!result.xyz,
      "result.molecule_xyz": !!result.molecule_xyz,
      found: !!xyz, length: xyz ? xyz.length : 0,
    });

    if (!xyz && typeof result === "string") {
      if (result.indexOf("\n") > -1) {
        console.log("[viewer.js] extractXyz — result IS a raw XYZ string, length:", result.length);
        return result;
      }
    }
    return xyz;
  }

  // ─── 뷰어 업데이트 ────────────────────────────────

  function updateViewer(result) {
    console.log("[viewer.js] updateViewer called, viewerReady:", viewerReady, "result:", !!result);
    if (!result) return;

    if (!viewerReady) {
      console.log("[viewer.js] updateViewer — viewer not ready, queuing update");
      pendingUpdate = result;
      return;
    }

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      console.log("[viewer.js] updateViewer — debounce fired, calling _doUpdate");
      _doUpdate(result);
    }, DEBOUNCE_MS);
  }

  function _doUpdate(result) {
    console.log("[viewer.js] ─── _doUpdate START ───");
    currentResult = result;
    var xyz = extractXyz(result);

    if (!xyz) {
      console.warn("[viewer.js] _doUpdate — NO xyz found, showing empty placeholder");
      show(viewerEmpty);
      hide(viewerControls);
      return;
    }

    console.log("[viewer.js] _doUpdate — xyz length:", xyz.length, "first 80 chars:", xyz.substring(0, 80));
    hide(viewerEmpty);
    show(viewerControls);

    console.log("[viewer.js] _doUpdate — viewer.clear()");
    viewer.clear();

    console.log("[viewer.js] _doUpdate — viewer.addModel(xyz, 'xyz', {keepH:true})");
    viewer.addModel(xyz, "xyz", { keepH: true });

    var style = getActiveStyle();
    console.log("[viewer.js] _doUpdate — applyStyle:", style);
    applyStyle(style);
    viewer.render();

    var showLabels =
      btnToggleLabels && btnToggleLabels.getAttribute("data-active") === "true";
    console.log("[viewer.js] _doUpdate — labels:", showLabels);
    if (showLabels) {
      viewer.addPropertyLabels("atom", {}, {
        font: "Arial", fontSize: 11, showBackground: true,
        backgroundColor: 0x222222, backgroundOpacity: 0.6,
      });
    }

    var viz = result.visualization || {};
    var available = viz.available || {};
    console.log("[viewer.js] _doUpdate — available surfaces:", JSON.stringify(available));
    console.log("[viewer.js] _doUpdate — viz keys:", Object.keys(viz).join(", "));
    console.log("[viewer.js] _doUpdate — currentMode:", currentMode);

    if (available.orbital || available.esp) {
      show(vizModeToggle);
    } else {
      hide(vizModeToggle);
    }

    if (available.orbital && grpOrbital) show(grpOrbital);
    else hide(grpOrbital);
    if (available.esp && grpESP) show(grpESP);
    else hide(grpESP);
    if ((available.orbital || available.esp) && grpOpacity) show(grpOpacity);
    else hide(grpOpacity);

    console.log("[viewer.js] _doUpdate — calling addSurface");
    addSurface(result);

    // Populate orbital select dropdown
    _populateOrbitalDropdown(result);

    console.log("[viewer.js] _doUpdate — final zoomTo + render");
    viewer.zoomTo();
    viewer.render();

    // Setup trajectory controls if geo_opt result
    setupTrajectory(result);

    var jobId = safeStr(result.job_id || (viz).job_id);
    if (jobId) {
      var snap = {
        style: style,
        isovalue: sliderIsovalue ? parseFloat(sliderIsovalue.value) : 0.03,
        opacity: sliderOpacity ? parseFloat(sliderOpacity.value) : 0.75,
        mode: currentMode, labels: showLabels,
      };
      console.log("[viewer.js] _doUpdate — saveUISnapshot for job:", jobId, snap);
      App.saveUISnapshot(jobId, snap);
    }
    console.log("[viewer.js] ─── _doUpdate END ───");
  }

  // ─── Trajectory Playback ──────────────────────────
  function setupTrajectory(result) {
    if (!result) return;
    var traj = result.trajectory || [];
    trajFrames = traj;

    // Stop any running playback
    if (trajInterval) { clearInterval(trajInterval); trajInterval = null; }
    trajPlaying = false;

    if (traj.length > 1 && grpTrajectory) {
      console.log("[viewer.js] setupTrajectory — found", traj.length, "frames");
      sliderTrajFrame.min = 0;
      sliderTrajFrame.max = traj.length - 1;
      sliderTrajFrame.value = traj.length - 1;  // show optimized (last frame)
      if (lblTrajFrame) lblTrajFrame.textContent = traj.length + "/" + traj.length;
      showTrajectoryEnergy(traj.length - 1);
      show(grpTrajectory);
      btnTrajPlay.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
    } else {
      hide(grpTrajectory);
    }
  }

  function showTrajectoryFrame(idx) {
    if (!viewer || !trajFrames.length || idx < 0 || idx >= trajFrames.length) return;
    var frame = trajFrames[idx];
    if (!frame || !frame.xyz) return;
    var xyzStr = frame.xyz;

    console.log("[viewer.js] showTrajectoryFrame —", idx + 1, "/", trajFrames.length,
      "E=", frame.energy_hartree);

    viewer.removeAllModels();
    viewer.addModel(xyzStr, "xyz");

    var style = getActiveStyle();
    var showLabels = btnToggleLabels ? btnToggleLabels.getAttribute("data-active") === "true" : true;
    viewer.setStyle({}, _buildStyle(style));
    if (showLabels) {
      viewer.addPropertyLabels("elem", {}, {
        font: "bold 11px sans-serif", fontColor: "white",
        backgroundColor: "rgba(0,0,0,0.5)", backgroundPadding: 2,
        showBackground: true, alignment: "center",
      });
    }
    viewer.render();

    if (lblTrajFrame) lblTrajFrame.textContent = (idx + 1) + "/" + trajFrames.length;
    showTrajectoryEnergy(idx);
  }

  function showTrajectoryEnergy(idx) {
    if (!lblTrajEnergy || idx < 0 || idx >= trajFrames.length) return;
    var frame = trajFrames[idx];
    var parts = [];
    if (frame.energy_hartree != null) parts.push("E=" + frame.energy_hartree.toFixed(8) + " Ha");
    if (frame.grad_norm != null) parts.push("|∇|=" + frame.grad_norm.toFixed(6));
    lblTrajEnergy.textContent = parts.join("  ");
  }

  // ─── Orbital Dropdown ─────────────────────────────
  function _populateOrbitalDropdown(result) {
    if (!selectOrbital || !grpOrbitalSelect) return;
    var orbitals = result.orbitals || [];
    var selected = result.selected_orbital || {};
    var selectedIdx = selected.zero_based_index;

    // Clear existing options
    selectOrbital.innerHTML = "";

    if (!orbitals.length) {
      hide(grpOrbitalSelect);
      return;
    }

    console.log("[viewer.js] _populateOrbitalDropdown —", orbitals.length, "orbitals, selected:", selected.label);

    for (var i = 0; i < orbitals.length; i++) {
      var orb = orbitals[i];
      var opt = document.createElement("option");
      opt.value = String(orb.zero_based_index);
      var eV = orb.energy_ev != null ? orb.energy_ev.toFixed(2) : "?";
      opt.textContent = orb.label + " (" + eV + " eV)";
      if (orb.zero_based_index === selectedIdx) opt.selected = true;
      selectOrbital.appendChild(opt);
    }
    show(grpOrbitalSelect);
  }

  // ─── Orbital Switching ──────────────────────────────
  var currentJobId = null;  // Track active job for orbital cube API calls
  var currentOrbitalCubes = {};  // Pre-computed cubes from result

  function _fetchAndSwapOrbital(orbitalIndex) {
    // Try pre-computed cubes first (instant, works after restart)
    var preComputed = currentOrbitalCubes[String(orbitalIndex)];
    if (preComputed) {
      console.log("[viewer.js] Using pre-computed cube for orbital index:", orbitalIndex);
      _swapOrbitalSurface(preComputed);
      return;
    }

    // Fallback: fetch from API (uses SCF cache)
    if (!currentJobId) {
      console.warn("[viewer.js] No job ID for orbital cube fetch");
      return;
    }
    console.log("[viewer.js] Fetching orbital cube for index:", orbitalIndex, "job:", currentJobId);
    fetch(window.__ROOT_PATH + "/compute/jobs/" + currentJobId + "/orbital_cube", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-QCViz-Session-Id": String((window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.sessionId) || ""),
        "X-QCViz-Session-Token": String((window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.sessionToken) || ""),
        "X-QCViz-Auth-Token": String((window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.authToken) || ""),
      },
      body: JSON.stringify({
        orbital_index: orbitalIndex,
        session_id: (window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.sessionId) || "",
        session_token: (window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.sessionToken) || "",
        auth_token: (window.QCVizApp && window.QCVizApp.store && window.QCVizApp.store.authToken) || "",
      }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (data.cube_b64) {
          _swapOrbitalSurface(data.cube_b64);
        }
      })
      .catch(function (err) {
        console.error("[viewer.js] Orbital cube fetch failed:", err);
      });
  }

  function _swapOrbitalSurface(cubeB64) {
    if (!viewer) return;
    try {
      var cubeStr = atob(cubeB64);
      var iso = sliderIsovalue ? parseFloat(sliderIsovalue.value) : 0.03;
      var opa = sliderOpacity ? parseFloat(sliderOpacity.value) : 0.75;
      var cs = getColorScheme();

      // Remove ALL old shapes (volumetric isosurfaces) and surfaces
      viewer.removeAllShapes();
      viewer.removeAllSurfaces();
      viewer.addVolumetricData(cubeStr, "cube", { isoval: iso, color: cs.pos, opacity: opa });
      viewer.addVolumetricData(cubeStr, "cube", { isoval: -iso, color: cs.neg, opacity: opa });
      viewer.render();
      console.log("[viewer.js] ✔ Orbital surface swapped");
    } catch (e) {
      console.error("[viewer.js] Orbital surface swap failed:", e);
    }
  }

  // Dropdown change handler
  if (selectOrbital) {
    selectOrbital.addEventListener("change", function () {
      var idx = parseInt(selectOrbital.value, 10);
      if (!isNaN(idx)) _fetchAndSwapOrbital(idx);
    });
  }

  // Listen for orbital-selected events from results panel
  document.addEventListener("orbital-selected", function (e) {
    var label = (e.detail || {}).label;
    if (!label || !selectOrbital) return;
    console.log("[viewer.js] orbital-selected event:", label);
    for (var i = 0; i < selectOrbital.options.length; i++) {
      if (selectOrbital.options[i].textContent.indexOf(label) === 0) {
        selectOrbital.selectedIndex = i;
        // Trigger the fetch
        var idx = parseInt(selectOrbital.value, 10);
        if (!isNaN(idx)) _fetchAndSwapOrbital(idx);
        break;
      }
    }
  });


  function _buildStyle(style) {
    var map = {
      stick: { stick: { radius: 0.15 }, sphere: { scale: 0.25 } },
      ball_stick: { stick: { radius: 0.12 }, sphere: { scale: 0.3 } },
      sphere: { sphere: { scale: 0.6 } },
      line: { line: { linewidth: 2 } },
    };
    return map[style] || map.stick;
  }

  function addSurface(result) {
    if (!viewer || !result) {
      console.log("[viewer.js] addSurface — skipped (viewer:", !!viewer, "result:", !!result, ")");
      return;
    }
    var viz = result.visualization || {};
    var available = viz.available || {};
    var defaults = viz.defaults || {};

    console.log("[viewer.js] addSurface — mode:", currentMode, "available:", JSON.stringify(available));

    if (currentMode === "orbital" && available.orbital) {
      var orbData = viz.orbital || {};
      var cubeB64 = orbData.cube_b64 || viz.orbital_cube_b64;
      console.log("[viewer.js] addSurface/ORBITAL — cube_b64:", !!cubeB64,
        "b64 length:", cubeB64 ? cubeB64.length : 0);
      if (cubeB64) {
        try {
          var iso = sliderIsovalue ? parseFloat(sliderIsovalue.value) : defaults.orbital_iso || 0.03;
          var opa = sliderOpacity ? parseFloat(sliderOpacity.value) : defaults.orbital_opacity || 0.75;
          var cubeStr = atob(cubeB64);
          var cs = getColorScheme();
          console.log("[viewer.js] addSurface/ORBITAL — decoded cube length:", cubeStr.length,
            "iso:", iso, "opacity:", opa, "colorScheme:", cs);

          viewer.addVolumetricData(cubeStr, "cube", { isoval: iso, color: cs.pos, opacity: opa });
          viewer.addVolumetricData(cubeStr, "cube", { isoval: -iso, color: cs.neg, opacity: opa });
          showColorBar("orbital", cs, defaults);
          console.log("[viewer.js] addSurface/ORBITAL — ✔ both surfaces added (colors:", cs.pos, "/", cs.neg, ")");
        } catch (e) {
          console.error("[viewer.js] addSurface/ORBITAL — ✖ FAILED:", e);
        }
      } else {
        console.warn("[viewer.js] addSurface/ORBITAL — no cube_b64 data found");
      }
    } else if (currentMode === "esp") {
      var espData = viz.esp || {};
      var espB64 = espData.cube_b64 || viz.esp_cube_b64;
      var densData = viz.density || {};
      var densB64 = densData.cube_b64 || viz.density_cube_b64;

      console.log("[viewer.js] addSurface/ESP — espB64:", !!espB64,
        "(len:", espB64 ? espB64.length : 0, ")",
        "densB64:", !!densB64, "(len:", densB64 ? densB64.length : 0, ")",
        "available.esp:", available.esp);

      if (espB64 && densB64) {
        try {
          var densIso = sliderEspDensIso ? parseFloat(sliderEspDensIso.value) : defaults.esp_density_iso || 0.001;
          var espOpa = sliderOpacity ? parseFloat(sliderOpacity.value) : defaults.esp_opacity || 0.9;
          var densStr = atob(densB64);
          var espStr = atob(espB64);

          console.log("[viewer.js] addSurface/ESP — decoded densStr length:", densStr.length,
            "espStr length:", espStr.length, "densIso:", densIso, "opacity:", espOpa);

          var espVolData = new g.$3Dmol.VolumeData(espStr, "cube");
          console.log("[viewer.js] addSurface/ESP — VolumeData created, has getVal:", typeof espVolData.getVal);

          var espCs = getColorScheme();
          var espRange = defaults.esp_range_au || 0.05;
          var espMin = espCs.invert ? espRange : -espRange;
          var espMax = espCs.invert ? -espRange : espRange;
          console.log("[viewer.js] addSurface/ESP — gradient:", espCs.gradient,
            "invert:", espCs.invert, "range:", espMin, "to", espMax);
          viewer.addVolumetricData(densStr, "cube", {
            isoval: densIso, opacity: espOpa, voldata: espVolData,
            volscheme: {
              gradient: espCs.gradient,
              min: espMin,
              max: espMax,
            },
          });
          showColorBar("esp", espCs, defaults);
          console.log("[viewer.js] addSurface/ESP — ✔ ESP surface added");
        } catch (e) {
          console.error("[viewer.js] addSurface/ESP — ✖ FAILED:", e);
        }
      } else if (!available.esp) {
        console.warn("[viewer.js] addSurface/ESP — no ESP data available at all");
        if (viewerLegend) {
          viewerLegend.innerHTML =
            '<p class="viewer-legend__info">ESP 데이터 없음 — ESP 계산을 먼저 실행하세요</p>';
          show(viewerLegend);
        }
      } else {
        console.warn("[viewer.js] addSurface/ESP — partial data: espB64:", !!espB64, "densB64:", !!densB64);
      }
    } else {
      hide(viewerLegend);
      console.log("[viewer.js] addSurface — no surface to add for mode:", currentMode,
        "available:", JSON.stringify(available));
    }
  }

  // ─── 컬러바 표시 ──────────────────────────────────
  function showColorBar(mode, cs, defaults) {
    if (!viewerLegend) return;
    console.log("[viewer.js] showColorBar — mode:", mode, "scheme:", cs);

    if (mode === "orbital") {
      var schemeName = selectColorScheme ? selectColorScheme.value : "classic";
      viewerLegend.innerHTML =
        '<div class="viewer-legend__bar">' +
          '<span class="viewer-legend__swatch" style="background:' + cs.neg + '"></span>' +
          '<span class="viewer-legend__label">−ψ</span>' +
          '<span class="viewer-legend__scheme">' + schemeName.charAt(0).toUpperCase() + schemeName.slice(1) + '</span>' +
          '<span class="viewer-legend__label">+ψ</span>' +
          '<span class="viewer-legend__swatch" style="background:' + cs.pos + '"></span>' +
        '</div>';
      show(viewerLegend);
    } else if (mode === "esp") {
      var range = defaults.esp_range_au || 0.05;
      var rangeKcal = (range * 627.509).toFixed(1);
      // Build gradient CSS based on scheme
      var gradColors = {
        rwb: cs.invert ? "blue, white, red" : "red, white, blue",
        roygb: "red, orange, yellow, green, blue",
        sinebow: "red, orange, yellow, green, cyan, blue, violet",
      };
      var grad = gradColors[cs.gradient] || gradColors.rwb;

      viewerLegend.innerHTML =
        '<div class="viewer-legend__bar">' +
          '<span class="viewer-legend__label">−' + range.toFixed(3) + ' au</span>' +
          '<span class="viewer-legend__gradient" style="background:linear-gradient(to right,' + grad + ')"></span>' +
          '<span class="viewer-legend__label">+' + range.toFixed(3) + ' au</span>' +
        '</div>' +
        '<div class="viewer-legend__subtitle">ESP (±' + rangeKcal + ' kcal/mol)</div>';
      show(viewerLegend);
    }
  }

  function getActiveStyle() {
    if (!segStyle) return "stick";
    var active = segStyle.querySelector(".segmented__btn--active");
    var val = active ? safeStr(active.getAttribute("data-value"), "stick") : "stick";
    return val;
  }

  function applyStyle(style) {
    if (!viewer) return;
    var spec = {};
    switch (style) {
      case "sphere": spec = { sphere: { scale: 0.3 }, stick: { radius: 0.15 } }; break;
      case "line": spec = { line: { linewidth: 2 } }; break;
      case "stick": default: spec = { stick: { radius: 0.15 }, sphere: { scale: 0.25 } }; break;
    }
    console.log("[viewer.js] applyStyle:", style, "→", JSON.stringify(spec));
    viewer.setStyle({}, spec);
  }

  // ─── 컨트롤 이벤트 ────────────────────────────────

  function bindControls() {
    console.log("[viewer.js] bindControls — binding all event listeners");

    if (segStyle) {
      segStyle.addEventListener("click", function (e) {
        var btn = e.target.closest(".segmented__btn");
        if (!btn) return;
        var val = btn.getAttribute("data-value");
        console.log("[viewer.js] 🎛 Style changed to:", val);
        segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
          b.classList.remove("segmented__btn--active");
        });
        btn.classList.add("segmented__btn--active");
        if (currentResult) _doUpdate(currentResult);
      });
    }

    if (sliderIsovalue) {
      sliderIsovalue.addEventListener("input", function () {
        var v = parseFloat(this.value);
        console.log("[viewer.js] 🎛 Isovalue slider:", v);
        if (lblIsovalue) lblIsovalue.textContent = v.toFixed(3);
        if (currentResult) updateViewer(currentResult);
      });
    }

    if (sliderEspDensIso) {
      sliderEspDensIso.addEventListener("input", function () {
        var v = parseFloat(this.value);
        console.log("[viewer.js] 🎛 ESP density iso slider:", v);
        if (lblEspDensIso) lblEspDensIso.textContent = v.toFixed(4);
        if (currentResult) updateViewer(currentResult);
      });
    }

    if (sliderOpacity) {
      sliderOpacity.addEventListener("input", function () {
        var v = parseFloat(this.value);
        console.log("[viewer.js] 🎛 Opacity slider:", v);
        if (lblOpacity) lblOpacity.textContent = v.toFixed(2);
        if (currentResult) updateViewer(currentResult);
      });
    }

    if (btnToggleLabels) {
      btnToggleLabels.addEventListener("click", function () {
        var active = this.getAttribute("data-active") === "true";
        console.log("[viewer.js] 🎛 Labels toggled:", active, "→", !active);
        this.setAttribute("data-active", String(!active));
        this.setAttribute("aria-pressed", String(!active));
        this.textContent = !active ? "On" : "Off";
        if (currentResult) _doUpdate(currentResult);
      });
    }

    if (btnModeOrbital) {
      btnModeOrbital.addEventListener("click", function () {
        console.log("[viewer.js] 🎛 Mode → ORBITAL (was:", currentMode, ")");
        currentMode = "orbital";
        btnModeOrbital.classList.add("active");
        if (btnModeESP) btnModeESP.classList.remove("active");
        show(grpOrbital); hide(grpESP);
        if (currentResult) _doUpdate(currentResult);
      });
    }
    if (btnModeESP) {
      btnModeESP.addEventListener("click", function () {
        console.log("[viewer.js] 🎛 Mode → ESP (was:", currentMode, ")");
        currentMode = "esp";
        btnModeESP.classList.add("active");
        if (btnModeOrbital) btnModeOrbital.classList.remove("active");
        hide(grpOrbital); show(grpESP);
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Color scheme dropdown
    if (selectColorScheme) {
      selectColorScheme.addEventListener("change", function () {
        console.log("[viewer.js] 🎛 Color scheme changed to:", this.value);
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Orbital select dropdown
    if (selectOrbital) {
      selectOrbital.addEventListener("change", function () {
        console.log("[viewer.js] 🎛 Orbital selected:", this.value);
        // TODO: re-render with different orbital cube data if available
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Trajectory controls
    if (sliderTrajFrame) {
      sliderTrajFrame.addEventListener("input", function () {
        var frameIdx = parseInt(this.value, 10);
        console.log("[viewer.js] 🎛 Trajectory frame slider:", frameIdx);
        showTrajectoryFrame(frameIdx);
      });
    }
    if (btnTrajPlay) {
      btnTrajPlay.addEventListener("click", function () {
        if (!trajFrames.length) return;
        trajPlaying = !trajPlaying;
        console.log("[viewer.js] 🎛 Trajectory play toggled:", trajPlaying);
        btnTrajPlay.innerHTML = trajPlaying
          ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>'
          : '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
        if (trajPlaying) {
          trajInterval = setInterval(function () {
            var cur = parseInt(sliderTrajFrame.value, 10);
            var next = (cur + 1) % trajFrames.length;
            sliderTrajFrame.value = next;
            showTrajectoryFrame(next);
            if (next === trajFrames.length - 1) {
              trajPlaying = false;
              clearInterval(trajInterval);
              trajInterval = null;
              btnTrajPlay.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
            }
          }, 200);
        } else {
          clearInterval(trajInterval);
          trajInterval = null;
        }
      });
    }

    if (btnViewerReset) {
      btnViewerReset.addEventListener("click", function () {
        console.log("[viewer.js] 🎛 Reset view");
        if (viewer) { viewer.zoomTo(); viewer.render(); }
      });
    }

    if (btnViewerScreenshot) {
      btnViewerScreenshot.addEventListener("click", function () {
        console.log("[viewer.js] 🎛 Screenshot");
        if (!viewer) return;
        try {
          var png = viewer.pngURI();
          var link = document.createElement("a");
          link.download = "qcviz_capture.png"; link.href = png; link.click();
          console.log("[viewer.js] ✔ Screenshot saved");
        } catch (e) {
          console.error("[viewer.js] ✖ Screenshot failed:", e);
        }
      });
    }

    if (btnViewerFullscreen) {
      btnViewerFullscreen.addEventListener("click", function () {
        var container = document.getElementById("viewerContainer");
        if (!container) return;
        console.log("[viewer.js] 🎛 Fullscreen toggle, current:", !!document.fullscreenElement);
        if (document.fullscreenElement) { document.exitFullscreen(); }
        else { container.requestFullscreen().catch(function () {}); }
      });
    }
    console.log("[viewer.js] ✔ All controls bound");
  }

  // ─── 이벤트 리스닝 ────────────────────────────────

  function init() {
    console.log("[viewer.js] init() — starting initialization");
    bindControls();

    App.on("result:changed", function (detail) {
      console.log("[viewer.js] 📡 Event result:changed, has result:", !!(detail && detail.result),
        "source:", detail ? detail.source : "?", "jobId:", detail ? detail.jobId : "?");
      if (detail && detail.result) {
        // Capture job ID and orbital cubes for orbital switching
        if (detail.jobId) currentJobId = detail.jobId;
        if (detail.result.orbital_cubes) currentOrbitalCubes = detail.result.orbital_cubes;
        updateViewer(detail.result);
      }
    });

    App.on("activejob:changed", function (detail) {
      console.log("[viewer.js] 📡 Event activejob:changed, jobId:", detail ? detail.jobId : "?",
        "has result:", !!(detail && detail.result));
      if (detail && detail.result) {
        if (detail.jobId) currentJobId = detail.jobId;
        if (detail.result.orbital_cubes) currentOrbitalCubes = detail.result.orbital_cubes;
        updateViewer(detail.result);
      }
    });

    if (g.$3Dmol) {
      console.log("[viewer.js] $3Dmol already loaded, calling initViewer immediately");
      initViewer();
    } else {
      console.log("[viewer.js] $3Dmol not loaded, starting CDN cascade");
      load3Dmol(CDN_URLS, 0);
    }
    console.log("[viewer.js] ✔ init() complete");
  }

  // ─── 공개 API ──────────────────────────────────────
  App.viewer = {
    update: updateViewer,
    isReady: function () { return viewerReady; },
    getViewer: function () { return viewer; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  console.log("[viewer.js] ✔ Module loaded");
})(window);
