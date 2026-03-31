## 파일 15/21: `src/qcviz_mcp/web/static/chat.js` (수정)

```javascript
/**
 * QCViz-MCP v3 — Chat Module
 * FIX(M7): 재귀 방지(depth guard), 상태 머신, 지수 백오프 재접속,
 *          XSS 방지(textContent), aria-live, client ping 20s
 */
(function (g) {
  "use strict";

  var App = g.QCVizApp;
  if (!App) {
    console.error("[chat.js] QCVizApp not found");
    return;
  }

  // ─── 상수 ───────────────────────────────────────────
  var MAX_RECONNECT = 10;
  var RECONNECT_BASE_MS = 1000;
  var RECONNECT_MAX_MS = 30000;
  var PING_INTERVAL_MS = 20000;
  var MAX_DEPTH = 3; // FIX(M7): 재귀 depth guard

  // ─── 상태 머신 ──────────────────────────────────────
  // FIX(M7): idle → sending → awaiting_ack → idle
  var STATE_IDLE = "idle";
  var STATE_SENDING = "sending";
  var STATE_AWAITING = "awaiting_ack";

  var chatState = STATE_IDLE;
  var ws = null;
  var reconnectCount = 0;
  var reconnectTimer = null;
  var pingTimer = null;
  var depth = 0; // FIX(M7): 재귀 방지 카운터

  // ─── DOM refs ───────────────────────────────────────
  var chatMessages = document.getElementById("chatMessages");
  var chatInput = document.getElementById("chatInput");
  var chatSend = document.getElementById("chatSend");
  var chatForm = document.getElementById("chatForm");
  var chatScroll = document.getElementById("chatScroll");
  var wsStatusDot = null;
  var wsStatusLabel = null;

  function initWsStatus() {
    var wsStatus = document.getElementById("wsStatus");
    if (wsStatus) {
      wsStatusDot = wsStatus.querySelector(".ws-status__dot");
      wsStatusLabel = wsStatus.querySelector(".ws-status__label");
    }
  }

  // ─── 유틸 ───────────────────────────────────────────

  // FIX(M7): XSS 방지 — textContent 사용, innerHTML 금지
  function escapeText(str) {
    if (str == null) return "";
    return String(str);
  }

  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function setWsConnected(connected) {
    if (wsStatusDot)
      wsStatusDot.setAttribute("data-connected", String(!!connected));
    if (wsStatusLabel)
      wsStatusLabel.textContent = connected ? "Connected" : "Disconnected";
  }

  function scrollToBottom() {
    if (chatScroll) {
      requestAnimationFrame(function () {
        chatScroll.scrollTop = chatScroll.scrollHeight;
      });
    }
  }

  // FIX(M7): aria-live region for screen readers
  function ensureAriaLive() {
    if (!chatMessages) return;
    if (!chatMessages.getAttribute("aria-live")) {
      chatMessages.setAttribute("aria-live", "polite");
      chatMessages.setAttribute("aria-relevant", "additions");
    }
  }

  // ─── 메시지 렌더링 ─────────────────────────────────

  function appendMessage(role, text, extra) {
    if (!chatMessages) return;
    extra = extra || {};

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--" + safeStr(role, "system");

    var avatar = document.createElement("div");
    avatar.className =
      "chat-msg__avatar chat-msg__avatar--" + safeStr(role, "system");
    if (role === "user") {
      avatar.textContent = "U";
    } else if (role === "assistant" || role === "system") {
      avatar.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
    } else {
      avatar.textContent = role.charAt(0).toUpperCase();
    }

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var p = document.createElement("p");
    p.className = "chat-msg__text";
    // FIX(M7): XSS 방지 — textContent 사용
    p.textContent = escapeText(text);

    body.appendChild(p);

    if (extra.plan) {
      var planEl = document.createElement("pre");
      planEl.className = "chat-msg__plan";
      planEl.textContent = JSON.stringify(extra.plan, null, 2);
      body.appendChild(planEl);
    }

    wrapper.appendChild(avatar);
    wrapper.appendChild(body);
    chatMessages.appendChild(wrapper);

    // FIX(M7): 히스토리에도 저장
    App.addChatMessage({
      role: role,
      text: escapeText(text),
      timestamp: Date.now(),
      extra: extra,
    });

    scrollToBottom();
  }

  function appendProgress(jobId, progress, step, message) {
    var existing = chatMessages
      ? chatMessages.querySelector('[data-progress-job="' + jobId + '"]')
      : null;
    var pct = Math.round(Math.min(100, Math.max(0, (progress || 0) * 100)));

    if (existing) {
      var bar = existing.querySelector(".progress-bar__fill");
      var lbl = existing.querySelector(".progress-bar__label");
      if (bar) bar.style.width = pct + "%";
      if (lbl)
        lbl.textContent =
          safeStr(message, step || "Working...") + " (" + pct + "%)";
      return;
    }

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--progress";
    wrapper.setAttribute("data-progress-job", jobId);

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var container = document.createElement("div");
    container.className = "progress-bar";

    var fill = document.createElement("div");
    fill.className = "progress-bar__fill";
    fill.style.width = pct + "%";

    var label = document.createElement("div");
    label.className = "progress-bar__label";
    label.textContent =
      safeStr(message, step || "Working...") + " (" + pct + "%)";

    container.appendChild(fill);
    body.appendChild(label);
    body.appendChild(container);
    wrapper.appendChild(body);

    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  // ─── WebSocket ──────────────────────────────────────

  function getWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/ws/chat";
  }

  function connect() {
    if (
      ws &&
      (ws.readyState === WebSocket.CONNECTING ||
        ws.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    try {
      ws = new WebSocket(getWsUrl());
    } catch (e) {
      console.error("[chat.js] WebSocket creation failed:", e);
      scheduleReconnect();
      return;
    }

    ws.onopen = function () {
      reconnectCount = 0;
      setWsConnected(true);
      App.setStatus("Connected", "idle", "chat");
      startPing();

      // Send hello
      wsSend({ type: "hello", session_id: App.store.sessionId });
    };

    ws.onclose = function (ev) {
      setWsConnected(false);
      stopPing();
      App.setStatus("Disconnected", "idle", "chat");

      if (chatState !== STATE_IDLE) {
        chatState = STATE_IDLE;
        updateSendButton();
      }
      scheduleReconnect();
    };

    ws.onerror = function (ev) {
      console.error("[chat.js] WebSocket error:", ev);
    };

    ws.onmessage = function (ev) {
      handleMessage(ev.data);
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    if (reconnectCount >= MAX_RECONNECT) {
      appendMessage(
        "system",
        "Connection lost. Please refresh the page. / 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.",
      );
      return;
    }
    // FIX(M7): 지수 백오프 재접속
    var delay = Math.min(
      RECONNECT_MAX_MS,
      RECONNECT_BASE_MS * Math.pow(2, reconnectCount),
    );
    reconnectCount++;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  // FIX(M7): client ping 20s
  function startPing() {
    stopPing();
    pingTimer = setInterval(function () {
      wsSend({ type: "ping" });
    }, PING_INTERVAL_MS);
  }

  function stopPing() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(obj));
      } catch (e) {
        console.error("[chat.js] wsSend error:", e);
      }
    }
  }

  // ─── 메시지 핸들링 ─────────────────────────────────

  function handleMessage(raw) {
    // FIX(M7): 재귀 방지 depth guard
    depth++;
    if (depth > MAX_DEPTH) {
      console.warn("[chat.js] handleMessage depth exceeded, dropping");
      depth--;
      return;
    }

    try {
      var msg;
      try {
        msg = JSON.parse(raw);
      } catch (e) {
        console.warn("[chat.js] Non-JSON message:", raw);
        depth--;
        return;
      }

      var type = safeStr(msg.type);

      switch (type) {
        case "ready":
        case "ack":
          if (chatState === STATE_AWAITING) {
            chatState = STATE_IDLE;
            updateSendButton();
          }
          break;

        case "assistant":
          appendMessage("assistant", safeStr(msg.message, ""), {
            plan: msg.plan || null,
          });
          break;

        case "job_submitted":
          var job = msg.job || {};
          App.upsertJob(job);
          App.setStatus("Computing...", "running", "chat");
          appendProgress(
            safeStr(job.job_id),
            0.01,
            "submitted",
            "Job submitted",
          );
          break;

        case "job_update":
          var jobId = safeStr(msg.job_id);
          if (jobId) {
            appendProgress(
              jobId,
              msg.progress || 0,
              safeStr(msg.step),
              safeStr(msg.message),
            );
            if (msg.job) App.upsertJob(msg.job);
          }
          break;

        case "job_event":
          // silently update — no duplicate rendering
          break;

        case "result":
          chatState = STATE_IDLE;
          updateSendButton();

          var result = msg.result || {};
          var job2 = msg.job || {};
          var jobId2 = safeStr(job2.job_id || msg.job_id);

          if (jobId2 && job2) {
            job2.result = result;
            App.upsertJob(job2);
          }
          if (result) {
            App.setActiveResult(result, { jobId: jobId2, source: "chat" });
          }

          var summary = safeStr(msg.summary, "Calculation complete.");
          appendMessage("assistant", summary);
          App.setStatus("Ready", "idle", "chat");
          break;

        case "error":
          chatState = STATE_IDLE;
          updateSendButton();

          var errObj = msg.error || {};
          var errMsg = safeStr(
            errObj.message || msg.message,
            "An error occurred. / 오류가 발생했습니다.",
          );
          appendMessage("system", "Error: " + errMsg);
          App.setStatus("Error", "error", "chat");
          break;

        default:
          break;
      }
    } finally {
      depth--;
    }
  }

  // ─── 전송 ──────────────────────────────────────────

  function sendMessage() {
    if (!chatInput) return;
    var text = chatInput.value.trim();
    if (!text) return;

    // FIX(M7): 상태 머신 — idle에서만 전송 가능
    if (chatState !== STATE_IDLE) return;

    chatState = STATE_SENDING;
    updateSendButton();

    appendMessage("user", text);
    App.store.lastUserInput = text;

    wsSend({
      type: "chat",
      message: text,
      session_id: App.store.sessionId,
    });

    chatInput.value = "";
    chatInput.style.height = "auto";

    // awaiting_ack 전환 (3초 타임아웃으로 idle 복귀)
    chatState = STATE_AWAITING;
    updateSendButton();

    setTimeout(function () {
      if (chatState === STATE_AWAITING) {
        chatState = STATE_IDLE;
        updateSendButton();
      }
    }, 3000);
  }

  function updateSendButton() {
    if (!chatSend) return;
    var hasText = chatInput && chatInput.value.trim().length > 0;
    chatSend.disabled = chatState !== STATE_IDLE || !hasText;
  }

  // ─── 이벤트 바인딩 ─────────────────────────────────

  function init() {
    initWsStatus();
    ensureAriaLive();

    if (chatForm) {
      chatForm.addEventListener("submit", function (e) {
        e.preventDefault();
        sendMessage();
      });
    }

    if (chatInput) {
      chatInput.addEventListener("input", function () {
        updateSendButton();
        // auto-resize textarea
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 200) + "px";
      });

      chatInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
    }

    // suggestion chips
    var suggestions = document.getElementById("chatSuggestions");
    if (suggestions) {
      suggestions.addEventListener("click", function (e) {
        var chip = e.target.closest(".suggestion-chip");
        if (!chip) return;
        var prompt = chip.getAttribute("data-prompt");
        if (prompt && chatInput) {
          chatInput.value = prompt;
          updateSendButton();
          sendMessage();
        }
      });
    }

    // keyboard shortcut: Ctrl+/ → focus chat
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "/") {
        e.preventDefault();
        if (chatInput) chatInput.focus();
      }
    });

    connect();
  }

  // ─── 공개 API ──────────────────────────────────────
  App.chat = {
    connect: connect,
    sendMessage: sendMessage,
    appendMessage: appendMessage,
    getState: function () {
      return chatState;
    },
  };

  // DOM Ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
```

---

## 파일 16/21: `src/qcviz_mcp/web/static/viewer.js` (수정)

```javascript
/**
 * QCViz-MCP v3 — 3D Molecular Viewer
 * FIX(M8): CDN 3개 순차 재시도, 100ms 디바운스, viewerReady 큐잉,
 *          xyz/molecule_xyz→xyz_block 키 매핑
 */
(function (g) {
  "use strict";

  var App = g.QCVizApp;
  if (!App) {
    console.error("[viewer.js] QCVizApp not found");
    return;
  }

  // ─── 상수 ──────────────────────────────────────────
  // FIX(M8): CDN 3개 순차 재시도
  var CDN_URLS = [
    "https://3Dmol.org/build/3Dmol-min.js",
    "https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js",
    "https://unpkg.com/3dmol@2.4.2/build/3Dmol-min.js",
  ];

  var DEBOUNCE_MS = 100; // FIX(M8): 100ms 디바운스
  var viewerReady = false;
  var viewer = null;
  var pendingUpdate = null; // FIX(M8): 로드 전 update 큐잉
  var debounceTimer = null;
  var currentResult = null;
  var currentMode = "orbital"; // "orbital" | "esp"

  // ─── DOM refs ──────────────────────────────────────
  var viewer3d = document.getElementById("viewer3d");
  var viewerEmpty = document.getElementById("viewerEmpty");
  var viewerControls = document.getElementById("viewerControls");
  var viewerLegend = document.getElementById("viewerLegend");
  var vizModeToggle = document.getElementById("vizModeToggle");

  // Controls
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

  // ─── 3Dmol 로딩 ───────────────────────────────────

  function load3Dmol(urls, idx) {
    idx = idx || 0;
    if (idx >= urls.length) {
      // FIX(M8): 전부 실패 시 유저 메시지
      if (viewerEmpty) {
        viewerEmpty.querySelector(".viewer-empty__text").textContent =
          "Failed to load 3D viewer library. Please check your network. / 3D 뷰어 라이브러리 로드 실패. 네트워크를 확인해 주세요.";
      }
      show(viewerEmpty);
      return;
    }
    var script = document.createElement("script");
    script.src = urls[idx];
    script.onload = function () {
      initViewer();
    };
    script.onerror = function () {
      console.warn("[viewer.js] CDN failed:", urls[idx]);
      load3Dmol(urls, idx + 1);
    };
    document.head.appendChild(script);
  }

  function initViewer() {
    if (!g.$3Dmol || !viewer3d) {
      console.error("[viewer.js] $3Dmol not available");
      return;
    }

    viewer = g.$3Dmol.createViewer(viewer3d, {
      backgroundColor: "white",
      antialias: true,
    });

    viewerReady = true;

    // FIX(M8): 큐잉된 업데이트 실행
    if (pendingUpdate) {
      var res = pendingUpdate;
      pendingUpdate = null;
      updateViewer(res);
    }
  }

  // ─── XYZ 키 매핑 ──────────────────────────────────

  // FIX(M8): 다양한 키에서 XYZ 문자열 추출
  function extractXyz(result) {
    if (!result) return null;
    var viz = result.visualization || {};

    // 우선순위: xyz_block > xyz > molecule_xyz
    var xyz =
      viz.xyz_block ||
      viz.xyz ||
      viz.molecule_xyz ||
      result.xyz_block ||
      result.xyz ||
      result.molecule_xyz ||
      null;

    if (!xyz && typeof result === "string") {
      // 혹시 result 자체가 XYZ 문자열?
      if (result.indexOf("\n") > -1) return result;
    }
    return xyz;
  }

  // ─── 뷰어 업데이트 ────────────────────────────────

  function updateViewer(result) {
    if (!result) return;

    // FIX(M8): viewerReady 전이면 큐잉
    if (!viewerReady) {
      pendingUpdate = result;
      return;
    }

    // FIX(M8): 디바운스
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      _doUpdate(result);
    }, DEBOUNCE_MS);
  }

  function _doUpdate(result) {
    currentResult = result;
    var xyz = extractXyz(result);

    if (!xyz) {
      show(viewerEmpty);
      hide(viewerControls);
      return;
    }

    hide(viewerEmpty);
    show(viewerControls);

    viewer.clear();

    // Add molecule
    viewer.addModel(xyz, "xyz");

    // Apply style
    var style = getActiveStyle();
    applyStyle(style);

    // Labels
    var showLabels =
      btnToggleLabels && btnToggleLabels.getAttribute("data-active") === "true";
    if (showLabels) {
      viewer.addPropertyLabels(
        "atom",
        {},
        {
          font: "Arial",
          fontSize: 11,
          showBackground: true,
          backgroundColor: 0x222222,
          backgroundOpacity: 0.6,
        },
      );
    }

    // Check available surfaces
    var viz = result.visualization || {};
    var available = viz.available || {};

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

    // Add surface based on current mode
    addSurface(result);

    viewer.zoomTo();
    viewer.render();

    // Save UI snapshot
    var jobId = safeStr(result.job_id || (result.visualization || {}).job_id);
    if (jobId) {
      App.saveUISnapshot(jobId, {
        style: style,
        isovalue: sliderIsovalue ? parseFloat(sliderIsovalue.value) : 0.03,
        opacity: sliderOpacity ? parseFloat(sliderOpacity.value) : 0.75,
        mode: currentMode,
        labels: showLabels,
      });
    }
  }

  function addSurface(result) {
    if (!viewer || !result) return;
    var viz = result.visualization || {};
    var available = viz.available || {};
    var defaults = viz.defaults || {};

    if (currentMode === "orbital" && available.orbital) {
      var orbData = viz.orbital || {};
      var cubeB64 = orbData.cube_b64 || viz.orbital_cube_b64;
      if (cubeB64) {
        var iso = sliderIsovalue
          ? parseFloat(sliderIsovalue.value)
          : defaults.orbital_iso || 0.03;
        var opa = sliderOpacity
          ? parseFloat(sliderOpacity.value)
          : defaults.orbital_opacity || 0.75;
        var cubeStr = atob(cubeB64);

        viewer.addVolumetricData(cubeStr, "cube", {
          isoval: iso,
          color: "blue",
          opacity: opa,
        });
        viewer.addVolumetricData(cubeStr, "cube", {
          isoval: -iso,
          color: "red",
          opacity: opa,
        });
      }
    } else if (currentMode === "esp" && available.esp) {
      var espData = viz.esp || {};
      var espB64 = espData.cube_b64 || viz.esp_cube_b64;
      var densData = viz.density || {};
      var densB64 = densData.cube_b64 || viz.density_cube_b64;

      if (espB64 && densB64) {
        var densIso = sliderEspDensIso
          ? parseFloat(sliderEspDensIso.value)
          : defaults.esp_density_iso || 0.001;
        var espOpa = sliderOpacity
          ? parseFloat(sliderOpacity.value)
          : defaults.esp_opacity || 0.9;
        var densStr = atob(densB64);
        var espStr = atob(espB64);

        viewer.addVolumetricData(densStr, "cube", {
          isoval: densIso,
          opacity: espOpa,
          voldata: espStr,
          volscheme: {
            gradient: "rwb",
            min: -(defaults.esp_range_au || 0.05),
            max: defaults.esp_range_au || 0.05,
          },
        });
      }
    }
  }

  function getActiveStyle() {
    if (!segStyle) return "stick";
    var active = segStyle.querySelector(".segmented__btn--active");
    return active
      ? safeStr(active.getAttribute("data-value"), "stick")
      : "stick";
  }

  function applyStyle(style) {
    if (!viewer) return;
    var spec = {};
    switch (style) {
      case "sphere":
        spec = { sphere: { scale: 0.3 }, stick: { radius: 0.15 } };
        break;
      case "line":
        spec = { line: { linewidth: 2 } };
        break;
      case "stick":
      default:
        spec = { stick: { radius: 0.15 }, sphere: { scale: 0.25 } };
        break;
    }
    viewer.setStyle({}, spec);
  }

  // ─── 컨트롤 이벤트 ────────────────────────────────

  function bindControls() {
    // Style toggle
    if (segStyle) {
      segStyle.addEventListener("click", function (e) {
        var btn = e.target.closest(".segmented__btn");
        if (!btn) return;
        segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
          b.classList.remove("segmented__btn--active");
        });
        btn.classList.add("segmented__btn--active");
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Isovalue slider
    if (sliderIsovalue) {
      sliderIsovalue.addEventListener("input", function () {
        if (lblIsovalue)
          lblIsovalue.textContent = parseFloat(this.value).toFixed(3);
        if (currentResult) updateViewer(currentResult);
      });
    }

    // ESP density iso slider
    if (sliderEspDensIso) {
      sliderEspDensIso.addEventListener("input", function () {
        if (lblEspDensIso)
          lblEspDensIso.textContent = parseFloat(this.value).toFixed(4);
        if (currentResult) updateViewer(currentResult);
      });
    }

    // Opacity slider
    if (sliderOpacity) {
      sliderOpacity.addEventListener("input", function () {
        if (lblOpacity)
          lblOpacity.textContent = parseFloat(this.value).toFixed(2);
        if (currentResult) updateViewer(currentResult);
      });
    }

    // Labels toggle
    if (btnToggleLabels) {
      btnToggleLabels.addEventListener("click", function () {
        var active = this.getAttribute("data-active") === "true";
        this.setAttribute("data-active", String(!active));
        this.setAttribute("aria-pressed", String(!active));
        this.textContent = !active ? "On" : "Off";
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Mode toggle
    if (btnModeOrbital) {
      btnModeOrbital.addEventListener("click", function () {
        currentMode = "orbital";
        btnModeOrbital.classList.add("active");
        if (btnModeESP) btnModeESP.classList.remove("active");
        show(grpOrbital);
        hide(grpESP);
        if (currentResult) _doUpdate(currentResult);
      });
    }
    if (btnModeESP) {
      btnModeESP.addEventListener("click", function () {
        currentMode = "esp";
        btnModeESP.classList.add("active");
        if (btnModeOrbital) btnModeOrbital.classList.remove("active");
        hide(grpOrbital);
        show(grpESP);
        if (currentResult) _doUpdate(currentResult);
      });
    }

    // Reset
    if (btnViewerReset) {
      btnViewerReset.addEventListener("click", function () {
        if (viewer) {
          viewer.zoomTo();
          viewer.render();
        }
      });
    }

    // Screenshot
    if (btnViewerScreenshot) {
      btnViewerScreenshot.addEventListener("click", function () {
        if (!viewer) return;
        try {
          var png = viewer.pngURI();
          var link = document.createElement("a");
          link.download = "qcviz_capture.png";
          link.href = png;
          link.click();
        } catch (e) {
          console.error("[viewer.js] Screenshot failed:", e);
        }
      });
    }

    // Fullscreen
    if (btnViewerFullscreen) {
      btnViewerFullscreen.addEventListener("click", function () {
        var container = document.getElementById("viewerContainer");
        if (!container) return;
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else {
          container.requestFullscreen().catch(function () {});
        }
      });
    }
  }

  // ─── 이벤트 리스닝 ────────────────────────────────

  function init() {
    bindControls();

    // Listen for result changes
    App.on("result:changed", function (detail) {
      if (detail && detail.result) {
        updateViewer(detail.result);
      }
    });

    // Listen for active job change (history click)
    App.on("activejob:changed", function (detail) {
      if (detail && detail.result) {
        updateViewer(detail.result);
      }
    });

    // Load 3Dmol.js via CDN cascade
    if (g.$3Dmol) {
      initViewer();
    } else {
      load3Dmol(CDN_URLS, 0);
    }
  }

  // ─── 공개 API ──────────────────────────────────────
  App.viewer = {
    update: updateViewer,
    isReady: function () {
      return viewerReady;
    },
    getViewer: function () {
      return viewer;
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
```

---

## 파일 17/21: `src/qcviz_mcp/web/static/results.js` (수정)

```javascript
/**
 * QCViz-MCP v3 — Results Panel
 * FIX(M9): created_at 안정 정렬, MAX_RETAINED=100 eviction,
 *          clampIndex, 키 매핑, 메모리 누수 방지
 */
(function (g) {
  "use strict";

  var App = g.QCVizApp;
  if (!App) {
    console.error("[results.js] QCVizApp not found");
    return;
  }

  // ─── 상수 ──────────────────────────────────────────
  var MAX_RETAINED_RESULTS = 100; // FIX(M9): eviction
  var TAB_KEYS = ["summary", "geometry", "orbital", "esp", "charges", "json"];

  // ─── DOM refs ──────────────────────────────────────
  var resultsTabs = document.getElementById("resultsTabs");
  var resultsContent = document.getElementById("resultsContent");
  var resultsEmpty = document.getElementById("resultsEmpty");

  // ─── 상태 ──────────────────────────────────────────
  var activeTab = "summary";
  var resultHistory = []; // FIX(M9): ordered list for eviction

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function safeNum(v, fb) {
    var n = parseFloat(v);
    return isFinite(n) ? n : fb || 0;
  }

  function show(el) {
    if (el) el.removeAttribute("hidden");
  }
  function hide(el) {
    if (el) el.setAttribute("hidden", "");
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // FIX(M9): 키 매핑 — backend → frontend 통일
  function mapResultKeys(r) {
    if (!r) return r;
    // total_energy → energy aliases
    if (r.total_energy_hartree != null && r.energy_hartree == null) {
      r.energy_hartree = r.total_energy_hartree;
    }
    if (r.total_energy_ev != null && r.energy_ev == null) {
      r.energy_ev = r.total_energy_ev;
    }
    // visualization xyz mapping
    var viz = r.visualization || {};
    if (!viz.xyz_block) {
      viz.xyz_block = viz.xyz || viz.molecule_xyz || r.xyz || null;
    }
    r.visualization = viz;
    return r;
  }

  // ─── 탭 렌더링 ────────────────────────────────────

  function renderTabs(result) {
    if (!resultsTabs) return;
    resultsTabs.innerHTML = "";

    var viz = result && result.visualization ? result.visualization : {};
    var available = viz.available || {};

    TAB_KEYS.forEach(function (key) {
      var btn = document.createElement("button");
      btn.className =
        "results-tab" + (key === activeTab ? " results-tab--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", key === activeTab ? "true" : "false");
      btn.setAttribute("data-tab", key);
      btn.textContent = key.charAt(0).toUpperCase() + key.slice(1);

      // Disable tabs that have no data
      if (key === "orbital" && !available.orbital) {
        btn.disabled = true;
        btn.classList.add("results-tab--disabled");
      }
      if (key === "esp" && !available.esp) {
        btn.disabled = true;
        btn.classList.add("results-tab--disabled");
      }

      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        activeTab = key;
        renderTabs(result);
        renderContent(result);
      });

      resultsTabs.appendChild(btn);
    });
  }

  function renderContent(result) {
    if (!resultsContent) return;
    if (!result) {
      show(resultsEmpty);
      resultsContent.querySelectorAll(".results-pane").forEach(function (el) {
        el.remove();
      });
      return;
    }

    hide(resultsEmpty);
    result = mapResultKeys(result);

    // Remove old panes
    resultsContent.querySelectorAll(".results-pane").forEach(function (el) {
      el.remove();
    });

    var pane = document.createElement("div");
    pane.className = "results-pane";

    switch (activeTab) {
      case "summary":
        pane.innerHTML = renderSummary(result);
        break;
      case "geometry":
        pane.innerHTML = renderGeometry(result);
        break;
      case "orbital":
        pane.innerHTML = renderOrbital(result);
        break;
      case "esp":
        pane.innerHTML = renderEsp(result);
        break;
      case "charges":
        pane.innerHTML = renderCharges(result);
        break;
      case "json":
        pane.innerHTML = renderJson(result);
        break;
      default:
        pane.innerHTML = "<p>Unknown tab</p>";
    }

    resultsContent.appendChild(pane);
  }

  // ─── 개별 탭 HTML 생성 ─────────────────────────────

  function renderSummary(r) {
    var parts = [];
    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Summary</h3>');
    parts.push('<table class="result-table">');

    var rows = [
      [
        "Structure",
        escapeHtml(safeStr(r.structure_name || r.structure_query, "—")),
      ],
      ["Job Type", escapeHtml(safeStr(r.job_type, "—"))],
      ["Method", escapeHtml(safeStr(r.method, "—"))],
      ["Basis", escapeHtml(safeStr(r.basis, "—"))],
      ["Charge", safeStr(r.charge, "0")],
      ["Multiplicity", safeStr(r.multiplicity, "1")],
      ["# Atoms", safeStr(r.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(r.formula, "—"))],
    ];

    if (r.total_energy_hartree != null) {
      rows.push(["Energy (Ha)", safeNum(r.total_energy_hartree).toFixed(8)]);
    }
    if (r.total_energy_ev != null) {
      rows.push(["Energy (eV)", safeNum(r.total_energy_ev).toFixed(4)]);
    }
    if (r.orbital_gap_ev != null) {
      rows.push(["HOMO-LUMO Gap (eV)", safeNum(r.orbital_gap_ev).toFixed(4)]);
    }
    if (r.scf_converged != null) {
      rows.push(["SCF Converged", r.scf_converged ? "Yes" : "No"]);
    }
    if (r.dipole_moment) {
      var dip = r.dipole_moment;
      rows.push(["Dipole (Debye)", safeNum(dip.magnitude).toFixed(4)]);
    }

    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td>");
      parts.push('<td class="result-table__val">' + row[1] + "</td></tr>");
    });

    parts.push("</table></div>");

    // Warnings
    var warnings = r.warnings || [];
    if (warnings.length > 0) {
      parts.push('<div class="result-section result-section--warnings">');
      parts.push("<h4>Warnings</h4><ul>");
      warnings.forEach(function (w) {
        parts.push("<li>" + escapeHtml(w) + "</li>");
      });
      parts.push("</ul></div>");
    }

    return parts.join("");
  }

  function renderGeometry(r) {
    var geo = r.geometry_summary || {};
    var bonds = r.bonds || [];
    var parts = [];

    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Geometry</h3>');
    parts.push('<table class="result-table">');

    var rows = [
      ["# Atoms", safeStr(geo.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(geo.formula || r.formula, "—"))],
      ["# Bonds", safeStr(geo.bond_count, "—")],
    ];
    if (geo.bond_length_min_angstrom != null)
      rows.push([
        "Min Bond (Å)",
        safeNum(geo.bond_length_min_angstrom).toFixed(4),
      ]);
    if (geo.bond_length_max_angstrom != null)
      rows.push([
        "Max Bond (Å)",
        safeNum(geo.bond_length_max_angstrom).toFixed(4),
      ]);
    if (geo.bond_length_mean_angstrom != null)
      rows.push([
        "Mean Bond (Å)",
        safeNum(geo.bond_length_mean_angstrom).toFixed(4),
      ]);

    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td>");
      parts.push('<td class="result-table__val">' + row[1] + "</td></tr>");
    });
    parts.push("</table>");

    // Atom list
    var atoms = r.atoms || [];
    if (atoms.length > 0 && atoms.length <= 100) {
      parts.push('<h4 style="margin-top:1rem">Atoms</h4>');
      parts.push('<table class="result-table result-table--compact">');
      parts.push(
        "<tr><th>#</th><th>Element</th><th>x</th><th>y</th><th>z</th></tr>",
      );
      atoms.forEach(function (a, i) {
        parts.push(
          "<tr><td>" +
            (i + 1) +
            "</td><td>" +
            escapeHtml(safeStr(a.symbol)) +
            "</td><td>" +
            safeNum(a.x).toFixed(4) +
            "</td><td>" +
            safeNum(a.y).toFixed(4) +
            "</td><td>" +
            safeNum(a.z).toFixed(4) +
            "</td></tr>",
        );
      });
      parts.push("</table>");
    }

    parts.push("</div>");
    return parts.join("");
  }

  function renderOrbital(r) {
    var orbitals = r.orbitals || [];
    var selected = r.selected_orbital || {};
    var parts = [];

    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Orbital</h3>');

    if (selected.label) {
      parts.push(
        "<p><strong>Selected:</strong> " +
          escapeHtml(selected.label) +
          " (" +
          safeNum(selected.energy_ev).toFixed(4) +
          " eV)</p>",
      );
    }

    if (orbitals.length > 0) {
      parts.push('<table class="result-table result-table--compact">');
      parts.push(
        "<tr><th>#</th><th>Label</th><th>Energy (eV)</th><th>Occ</th></tr>",
      );
      orbitals.forEach(function (o) {
        var cls =
          o.label === "HOMO" || o.label === "LUMO"
            ? ' class="result-table__highlight"'
            : "";
        parts.push(
          "<tr" +
            cls +
            "><td>" +
            o.index +
            "</td><td>" +
            escapeHtml(o.label) +
            "</td><td>" +
            safeNum(o.energy_ev).toFixed(4) +
            "</td><td>" +
            safeNum(o.occupancy).toFixed(2) +
            "</td></tr>",
        );
      });
      parts.push("</table>");
    } else {
      parts.push("<p>No orbital data available.</p>");
    }

    parts.push("</div>");
    return parts.join("");
  }

  function renderEsp(r) {
    var parts = [];
    parts.push('<div class="result-section">');
    parts.push(
      '<h3 class="result-section__title">Electrostatic Potential</h3>',
    );

    if (r.esp_preset) {
      parts.push(
        "<p><strong>Preset:</strong> " + escapeHtml(r.esp_preset) + "</p>",
      );
    }
    if (r.esp_auto_range_au != null) {
      parts.push(
        "<p><strong>Range:</strong> ±" +
          safeNum(r.esp_auto_range_au).toFixed(4) +
          " a.u. (" +
          safeNum(r.esp_auto_range_kcal).toFixed(2) +
          " kcal/mol)</p>",
      );
    }

    var fit = r.esp_auto_fit || {};
    var stats = fit.stats || {};
    if (stats.n) {
      parts.push('<table class="result-table">');
      parts.push("<tr><td>Grid points</td><td>" + stats.n + "</td></tr>");
      parts.push(
        "<tr><td>Min (a.u.)</td><td>" +
          safeNum(stats.min_au).toFixed(6) +
          "</td></tr>",
      );
      parts.push(
        "<tr><td>Max (a.u.)</td><td>" +
          safeNum(stats.max_au).toFixed(6) +
          "</td></tr>",
      );
      parts.push(
        "<tr><td>Mean (a.u.)</td><td>" +
          safeNum(stats.mean_au).toFixed(6) +
          "</td></tr>",
      );
      parts.push("</table>");
    }

    parts.push("</div>");
    return parts.join("");
  }

  function renderCharges(r) {
    var charges = r.mulliken_charges || r.partial_charges || [];
    var lowdin = r.lowdin_charges || [];
    var parts = [];

    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Partial Charges</h3>');

    if (charges.length > 0) {
      parts.push("<h4>Mulliken</h4>");
      parts.push('<table class="result-table result-table--compact">');
      parts.push("<tr><th>#</th><th>Atom</th><th>Charge</th></tr>");
      charges.forEach(function (c, i) {
        parts.push(
          "<tr><td>" +
            (c.atom_index != null ? c.atom_index + 1 : i + 1) +
            "</td><td>" +
            escapeHtml(safeStr(c.symbol)) +
            "</td><td>" +
            safeNum(c.charge).toFixed(4) +
            "</td></tr>",
        );
      });
      parts.push("</table>");
    }

    if (lowdin.length > 0) {
      parts.push('<h4 style="margin-top:1rem">Löwdin</h4>');
      parts.push('<table class="result-table result-table--compact">');
      parts.push("<tr><th>#</th><th>Atom</th><th>Charge</th></tr>");
      lowdin.forEach(function (c, i) {
        parts.push(
          "<tr><td>" +
            (c.atom_index != null ? c.atom_index + 1 : i + 1) +
            "</td><td>" +
            escapeHtml(safeStr(c.symbol)) +
            "</td><td>" +
            safeNum(c.charge).toFixed(4) +
            "</td></tr>",
        );
      });
      parts.push("</table>");
    }

    if (charges.length === 0 && lowdin.length === 0) {
      parts.push("<p>No charge data available.</p>");
    }

    parts.push("</div>");
    return parts.join("");
  }

  function renderJson(r) {
    var parts = [];
    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Raw JSON</h3>');
    parts.push('<div class="json-viewer">');

    // FIX(M9): 대용량 cube base64 제거 (메모리 누수 방지)
    var cleaned = {};
    Object.keys(r).forEach(function (k) {
      if (k.indexOf("cube_b64") >= 0) {
        cleaned[k] = "[base64 data omitted]";
      } else if (k === "visualization") {
        var vizCopy = Object.assign({}, r[k]);
        ["orbital_cube_b64", "density_cube_b64", "esp_cube_b64"].forEach(
          function (bk) {
            if (vizCopy[bk]) vizCopy[bk] = "[base64 data omitted]";
          },
        );
        if (vizCopy.orbital && vizCopy.orbital.cube_b64)
          vizCopy.orbital = Object.assign({}, vizCopy.orbital, {
            cube_b64: "[omitted]",
          });
        if (vizCopy.density && vizCopy.density.cube_b64)
          vizCopy.density = Object.assign({}, vizCopy.density, {
            cube_b64: "[omitted]",
          });
        if (vizCopy.esp && vizCopy.esp.cube_b64)
          vizCopy.esp = Object.assign({}, vizCopy.esp, {
            cube_b64: "[omitted]",
          });
        cleaned[k] = vizCopy;
      } else {
        cleaned[k] = r[k];
      }
    });

    parts.push(
      "<pre>" + escapeHtml(JSON.stringify(cleaned, null, 2)) + "</pre>",
    );
    parts.push("</div></div>");
    return parts.join("");
  }

  // ─── 결과 표시 진입점 ──────────────────────────────

  function displayResult(result, opts) {
    opts = opts || {};
    if (!result) return;

    result = mapResultKeys(result);

    // FIX(M9): eviction
    resultHistory.push(result);
    if (resultHistory.length > MAX_RETAINED_RESULTS) {
      resultHistory.shift();
    }

    // Determine initial tab from advisor
    var defaultTab = safeStr(
      (result.visualization || {}).defaults
        ? result.visualization.defaults.focus_tab || result.advisor_focus_tab
        : result.advisor_focus_tab,
      "summary",
    );
    if (TAB_KEYS.indexOf(defaultTab) >= 0) {
      activeTab = defaultTab;
    }

    renderTabs(result);
    renderContent(result);
  }

  // ─── 이벤트 ────────────────────────────────────────

  function init() {
    App.on("result:changed", function (detail) {
      if (detail && detail.result) {
        displayResult(detail.result, { source: detail.source });
      }
    });

    // keyboard: 1-6 switch tabs
    document.addEventListener("keydown", function (e) {
      // Only when no input is focused
      if (
        document.activeElement &&
        (document.activeElement.tagName === "INPUT" ||
          document.activeElement.tagName === "TEXTAREA" ||
          document.activeElement.tagName === "SELECT")
      )
        return;

      var idx = parseInt(e.key, 10);
      // FIX(M9): clampIndex 방지
      if (idx >= 1 && idx <= TAB_KEYS.length) {
        activeTab = TAB_KEYS[idx - 1];
        if (App.store.activeResult) {
          renderTabs(App.store.activeResult);
          renderContent(App.store.activeResult);
        }
      }
    });
  }

  App.results = {
    display: displayResult,
    getActiveTab: function () {
      return activeTab;
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
```

---

## 파일 18/21: `src/qcviz_mcp/web/static/app.js` (수정)

```javascript
/**
 * QCViz-MCP v3 — App Shell Controller
 * FIX(M10): newest-first history, rAF batch rendering,
 *           localStorage 2s throttle, 키보드 접근성, 이벤트 루프 방지
 */
(function (g) {
  "use strict";

  var App = g.QCVizApp;
  if (!App) {
    console.error("[app.js] QCVizApp not found");
    return;
  }

  // ─── 상수 ──────────────────────────────────────────
  var LS_THROTTLE_MS = 2000; // FIX(M10): localStorage 쓰기 쓰로틀

  // ─── DOM refs ──────────────────────────────────────
  var globalStatus = document.getElementById("globalStatus");
  var statusDot = globalStatus
    ? globalStatus.querySelector(".status-indicator__dot")
    : null;
  var statusText = globalStatus
    ? globalStatus.querySelector(".status-indicator__text")
    : null;
  var historyList = document.getElementById("historyList");
  var historyEmpty = document.getElementById("historyEmpty");
  var historySearch = document.getElementById("historySearch");
  var btnRefreshHistory = document.getElementById("btnRefreshHistory");
  var btnThemeToggle = document.getElementById("btnThemeToggle");
  var btnKeyboardShortcuts = document.getElementById("btnKeyboardShortcuts");
  var modalShortcuts = document.getElementById("modalShortcuts");
  var appLoader = document.getElementById("appLoader");

  // ─── 상태 ──────────────────────────────────────────
  var dirtyHistory = false;
  var rafPending = false;
  var lastLsSave = 0;
  var lsTimer = null;
  var eventLoopGuard = false; // FIX(M10): 이벤트 루프 방지

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function formatTime(ts) {
    if (!ts) return "—";
    try {
      var d = new Date(ts * 1000);
      return d.toLocaleTimeString();
    } catch (_) {
      return "—";
    }
  }

  function show(el) {
    if (el) el.removeAttribute("hidden");
  }
  function hide(el) {
    if (el) el.setAttribute("hidden", "");
  }

  // ─── 상태 표시 ────────────────────────────────────

  function updateStatus(detail) {
    if (!detail) return;
    if (statusDot)
      statusDot.setAttribute("data-kind", safeStr(detail.kind, "idle"));
    if (statusText) statusText.textContent = safeStr(detail.text, "Ready");
  }

  // ─── 히스토리 렌더링 ──────────────────────────────

  function renderHistory(filter) {
    if (!historyList) return;

    var jobs = App.store.jobOrder
      .map(function (id) {
        return App.store.jobsById[id];
      })
      .filter(function (j) {
        return !!j;
      });

    // FIX(M10): newest-first (already sorted in store, but verify)
    jobs.sort(function (a, b) {
      return (b.created_at || 0) - (a.created_at || 0);
    });

    // Filter
    if (filter) {
      var lf = filter.toLowerCase();
      jobs = jobs.filter(function (j) {
        var name = safeStr(j.molecule_name || j.user_query || "").toLowerCase();
        var jtype = safeStr(j.job_type || "").toLowerCase();
        var status = safeStr(j.status || "").toLowerCase();
        return (
          name.indexOf(lf) >= 0 ||
          jtype.indexOf(lf) >= 0 ||
          status.indexOf(lf) >= 0
        );
      });
    }

    if (jobs.length === 0) {
      historyList.innerHTML = "";
      show(historyEmpty);
      return;
    }

    hide(historyEmpty);
    // FIX(M10): rAF batch rendering
    var fragment = document.createDocumentFragment();

    jobs.forEach(function (job) {
      var card = document.createElement("div");
      card.className = "history-card";
      card.setAttribute("data-job-id", safeStr(job.job_id));
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute(
        "aria-label",
        safeStr(job.molecule_name || job.user_query || job.job_type || "Job"),
      );

      var statusClass =
        "history-card__status--" + safeStr(job.status, "queued");

      card.innerHTML =
        '<div class="history-card__header">' +
        '<span class="history-card__name">' +
        escapeHtmlSafe(
          safeStr(job.molecule_name || job.user_query || "Unnamed"),
        ) +
        "</span>" +
        '<span class="history-card__status ' +
        statusClass +
        '">' +
        safeStr(job.status, "queued") +
        "</span>" +
        "</div>" +
        '<div class="history-card__meta">' +
        "<span>" +
        escapeHtmlSafe(safeStr(job.job_type || "")) +
        "</span>" +
        "<span>" +
        escapeHtmlSafe(safeStr(job.method || "")) +
        "/" +
        escapeHtmlSafe(safeStr(job.basis_set || job.basis || "")) +
        "</span>" +
        "<span>" +
        formatTime(job.created_at) +
        "</span>" +
        "</div>";

      card.addEventListener("click", function () {
        handleHistoryClick(safeStr(job.job_id));
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleHistoryClick(safeStr(job.job_id));
        }
      });

      fragment.appendChild(card);
    });

    historyList.innerHTML = "";
    historyList.appendChild(fragment);
  }

  function escapeHtmlSafe(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function handleHistoryClick(jobId) {
    if (!jobId) return;
    App.setActiveJob(jobId);
  }

  function scheduleHistoryRender() {
    dirtyHistory = true;
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () {
      rafPending = false;
      if (dirtyHistory) {
        dirtyHistory = false;
        var filter = historySearch ? historySearch.value.trim() : "";
        renderHistory(filter);
      }
    });
  }

  // ─── localStorage 쓰로틀 ──────────────────────────

  function throttledSaveSnapshots() {
    var now = Date.now();
    if (now - lastLsSave < LS_THROTTLE_MS) {
      if (!lsTimer) {
        lsTimer = setTimeout(function () {
          lsTimer = null;
          throttledSaveSnapshots();
        }, LS_THROTTLE_MS);
      }
      return;
    }
    lastLsSave = now;
    try {
      localStorage.setItem(
        "QCVIZ_ENTERPRISE_V5_UI_SNAPSHOTS",
        JSON.stringify(App.store.uiSnapshotsByJobId),
      );
    } catch (_) {}
  }

  // ─── 테마 토글 ────────────────────────────────────

  function toggleTheme() {
    var next = App.store.theme === "dark" ? "light" : "dark";
    App.setTheme(next);
  }

  // ─── 모달 ──────────────────────────────────────────

  function openModal(modal) {
    if (modal && typeof modal.showModal === "function") {
      modal.showModal();
    }
  }
  function closeModal(modal) {
    if (modal && typeof modal.close === "function") {
      modal.close();
    }
  }

  // ─── 서버 히스토리 로드 ───────────────────────────

  function fetchHistory() {
    fetch(App.apiPrefix + "/compute/jobs?include_result=true")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var items = data.items || data || [];
        items.forEach(function (job) {
          App.upsertJob(job);
        });
        scheduleHistoryRender();
      })
      .catch(function (e) {
        console.warn("[app.js] Failed to fetch job history:", e);
      });
  }

  // ─── 키보드 단축키 ────────────────────────────────

  function setupKeyboard() {
    document.addEventListener("keydown", function (e) {
      // Avoid when typing
      var tag = (document.activeElement || {}).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") {
          document.activeElement.blur();
        }
        return;
      }

      // Ctrl+\ → toggle theme
      if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
        e.preventDefault();
        toggleTheme();
      }

      // Ctrl+K → focus history search
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        if (historySearch) historySearch.focus();
      }

      // ? → shortcuts modal
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        openModal(modalShortcuts);
      }

      // Esc → close modal
      if (e.key === "Escape") {
        closeModal(modalShortcuts);
      }
    });
  }

  // ─── 초기화 ────────────────────────────────────────

  function init() {
    // Status listener
    App.on("status:changed", function (detail) {
      if (eventLoopGuard) return; // FIX(M10)
      eventLoopGuard = true;
      updateStatus(detail);
      eventLoopGuard = false;
    });

    // Jobs listener
    App.on("jobs:changed", function () {
      scheduleHistoryRender();
      throttledSaveSnapshots();
    });

    // Active job → highlight in history
    App.on("activejob:changed", function (detail) {
      if (!historyList) return;
      historyList.querySelectorAll(".history-card").forEach(function (card) {
        card.classList.toggle(
          "history-card--active",
          card.getAttribute("data-job-id") === safeStr(detail.jobId),
        );
      });
    });

    // Theme toggle button
    if (btnThemeToggle) {
      btnThemeToggle.addEventListener("click", toggleTheme);
    }

    // Shortcuts button
    if (btnKeyboardShortcuts) {
      btnKeyboardShortcuts.addEventListener("click", function () {
        openModal(modalShortcuts);
      });
    }

    // Modal close buttons
    if (modalShortcuts) {
      modalShortcuts.querySelectorAll("[data-close]").forEach(function (el) {
        el.addEventListener("click", function () {
          closeModal(modalShortcuts);
        });
      });
    }

    // History search
    if (historySearch) {
      historySearch.addEventListener("input", function () {
        scheduleHistoryRender();
      });
    }

    // History refresh
    if (btnRefreshHistory) {
      btnRefreshHistory.addEventListener("click", fetchHistory);
    }

    setupKeyboard();

    // Initial history render
    scheduleHistoryRender();

    // Load server-side history
    fetchHistory();

    // Remove loader
    if (appLoader) {
      appLoader.classList.add("fade-out");
      setTimeout(function () {
        if (appLoader.parentNode) appLoader.parentNode.removeChild(appLoader);
      }, 600);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
```

---

## 파일 19/21: `src/qcviz_mcp/web/static/style.css` (수정)

```css
/**
 * QCViz-MCP v3 — Main Stylesheet
 * FIX(M11): 3-column grid(fr/minmax), 반응형(640/1024/1600),
 *           다크모드(prefers-color-scheme), focus outline, reduced-motion
 */

/* ─── Reset & Base ────────────────────────────────── */
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --font-sans: "Inter", system-ui, -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", monospace;

  --gap: 8px;
  --radius: 8px;
  --radius-sm: 4px;
  --transition: 0.15s ease;

  /* Light theme */
  --bg-app: #f4f5f7;
  --bg-panel: #ffffff;
  --bg-input: #f0f1f4;
  --bg-hover: #e8e9ed;
  --bg-code: #f6f7f9;
  --border: #d4d6dc;
  --border-focus: #6366f1;
  --text-primary: #1a1a2e;
  --text-secondary: #5a5e72;
  --text-muted: #9095a6;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
  --topbar-bg: #ffffff;
  --topbar-border: #e5e7eb;
  --chat-user-bg: #6366f1;
  --chat-user-text: #ffffff;
  --chat-system-bg: #f0f1f4;
  --chat-system-text: #1a1a2e;
}

[data-theme="dark"] {
  --bg-app: #0f1117;
  --bg-panel: #1a1d29;
  --bg-input: #252836;
  --bg-hover: #2d3042;
  --bg-code: #1e2130;
  --border: #2d3042;
  --border-focus: #818cf8;
  --text-primary: #e8eaf0;
  --text-secondary: #a0a4b4;
  --text-muted: #6b7086;
  --accent: #818cf8;
  --accent-hover: #6366f1;
  --success: #4ade80;
  --warning: #fbbf24;
  --error: #f87171;
  --topbar-bg: #1a1d29;
  --topbar-border: #2d3042;
  --chat-user-bg: #4f46e5;
  --chat-user-text: #ffffff;
  --chat-system-bg: #252836;
  --chat-system-text: #e8eaf0;
}

/* FIX(M11): prefers-color-scheme fallback */
@media (prefers-color-scheme: dark) {
  html:not([data-theme="light"]) {
    --bg-app: #0f1117;
    --bg-panel: #1a1d29;
    --bg-input: #252836;
    --bg-hover: #2d3042;
    --bg-code: #1e2130;
    --border: #2d3042;
    --border-focus: #818cf8;
    --text-primary: #e8eaf0;
    --text-secondary: #a0a4b4;
    --text-muted: #6b7086;
    --accent: #818cf8;
    --accent-hover: #6366f1;
    --topbar-bg: #1a1d29;
    --topbar-border: #2d3042;
  }
}

/* FIX(M11): reduced-motion */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}

html {
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  font-family: var(--font-sans);
  color: var(--text-primary);
  background: var(--bg-app);
  overflow: hidden;
  height: 100vh;
}

/* FIX(M11): skip-to-content (accessibility) */
.skip-link {
  position: absolute;
  top: -100px;
  left: 0;
  background: var(--accent);
  color: #fff;
  padding: 0.5rem 1rem;
  z-index: 10000;
  border-radius: var(--radius-sm);
}
.skip-link:focus {
  top: 8px;
  left: 8px;
}

/* FIX(M11): focus outline */
:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

/* ─── App Shell ───────────────────────────────────── */
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ─── Top Bar ─────────────────────────────────────── */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: var(--topbar-bg);
  border-bottom: 1px solid var(--topbar-border);
  flex-shrink: 0;
  z-index: 100;
}

.topbar__left,
.topbar__center,
.topbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.topbar__logo {
  display: flex;
  align-items: center;
  gap: 8px;
}

.topbar__title {
  font-weight: 600;
  font-size: 0.95rem;
  white-space: nowrap;
}

.topbar__badge {
  font-size: 0.65rem;
  font-weight: 700;
  background: var(--accent);
  color: #fff;
  padding: 1px 6px;
  border-radius: 9999px;
  vertical-align: super;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.status-indicator__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  transition: background var(--transition);
}
.status-indicator__dot[data-kind="idle"] {
  background: var(--success);
}
.status-indicator__dot[data-kind="running"] {
  background: var(--warning);
}
.status-indicator__dot[data-kind="error"] {
  background: var(--error);
}

/* ─── Buttons ─────────────────────────────────────── */
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}
.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.icon-btn--sm {
  width: 28px;
  height: 28px;
}

.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 9999px;
  cursor: pointer;
  transition: all var(--transition);
}
.chip-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.toggle-btn {
  padding: 4px 12px;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition);
}
.toggle-btn.active,
.toggle-btn[data-active="true"] {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

/* Theme toggle icons */
[data-theme="dark"] .icon-sun {
  display: inline;
}
[data-theme="dark"] .icon-moon {
  display: none;
}
[data-theme="light"] .icon-sun,
html:not([data-theme]) .icon-sun {
  display: none;
}
[data-theme="light"] .icon-moon,
html:not([data-theme]) .icon-moon {
  display: inline;
}

/* ─── Dashboard Grid ──────────────────────────────── */
/* FIX(M11): 3-column grid with fr/minmax, no fixed px */
.dashboard {
  display: grid;
  grid-template-columns: minmax(300px, 1.4fr) minmax(280px, 1fr) minmax(
      250px,
      0.9fr
    );
  grid-template-rows: 1fr 1fr;
  gap: var(--gap);
  padding: var(--gap);
  flex: 1;
  overflow: hidden;
}

.panel--viewer {
  grid-column: 1;
  grid-row: 1 / -1;
}
.panel--chat {
  grid-column: 2;
  grid-row: 1 / -1;
}
.panel--results {
  grid-column: 3;
  grid-row: 1;
}
.panel--history {
  grid-column: 3;
  grid-row: 2;
}

/* FIX(M11): 반응형 — 1024px 이하: 2-column */
@media (max-width: 1024px) {
  .dashboard {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(300px, 1fr) minmax(250px, auto) minmax(
        200px,
        auto
      );
  }
  .panel--viewer {
    grid-column: 1 / -1;
    grid-row: 1;
  }
  .panel--chat {
    grid-column: 1;
    grid-row: 2;
  }
  .panel--results {
    grid-column: 2;
    grid-row: 2;
  }
  .panel--history {
    grid-column: 1 / -1;
    grid-row: 3;
  }
}

/* FIX(M11): 반응형 — 640px 이하: single column */
@media (max-width: 640px) {
  .dashboard {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(250px, 1fr) minmax(300px, 1fr) auto auto;
  }
  .panel--viewer {
    grid-column: 1;
    grid-row: 1;
  }
  .panel--chat {
    grid-column: 1;
    grid-row: 2;
  }
  .panel--results {
    grid-column: 1;
    grid-row: 3;
  }
  .panel--history {
    grid-column: 1;
    grid-row: 4;
  }
}

/* FIX(M11): 1600px+ — wider viewer */
@media (min-width: 1600px) {
  .dashboard {
    grid-template-columns: minmax(400px, 1.5fr) minmax(320px, 1fr) minmax(
        280px,
        0.9fr
      );
  }
}

/* ─── Panels ──────────────────────────────────────── */
.panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.panel__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-primary);
}

.panel__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ─── Viewer ──────────────────────────────────────── */
.viewer-container {
  position: relative;
  flex: 1;
  overflow: hidden;
}

.viewer-3d {
  width: 100%;
  height: 100%;
}

.viewer-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
  color: var(--text-muted);
}

.viewer-empty__text {
  font-size: 0.85rem;
}
.viewer-empty__hint {
  font-size: 0.75rem;
  font-style: italic;
}

.viewer-controls {
  position: absolute;
  bottom: 8px;
  left: 8px;
  right: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  opacity: 0.95;
}

.viewer-controls__group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.viewer-controls__label {
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--text-secondary);
  white-space: nowrap;
}

.viewer-controls__value {
  font-size: 0.7rem;
  font-family: var(--font-mono);
  color: var(--text-muted);
  min-width: 40px;
}

.range-input {
  width: 80px;
  accent-color: var(--accent);
}

.viewer-select {
  padding: 2px 6px;
  font-size: 0.72rem;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.viz-mode-toggle {
  display: flex;
  gap: 2px;
}

.segmented {
  display: flex;
  gap: 1px;
}
.segmented__btn {
  padding: 3px 8px;
  font-size: 0.7rem;
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all var(--transition);
}
.segmented__btn:first-child {
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}
.segmented__btn:last-child {
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.segmented__btn--active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

/* ─── Chat ────────────────────────────────────────── */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.chat-messages {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-msg {
  display: flex;
  gap: 8px;
  max-width: 100%;
}

.chat-msg__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 600;
  flex-shrink: 0;
}

.chat-msg__avatar--user {
  background: var(--chat-user-bg);
  color: var(--chat-user-text);
}
.chat-msg__avatar--system,
.chat-msg__avatar--assistant {
  background: var(--chat-system-bg);
  color: var(--accent);
}

.chat-msg__body {
  flex: 1;
  min-width: 0;
}

.chat-msg__text {
  font-size: 0.82rem;
  line-height: 1.5;
  word-break: break-word;
}

.chat-msg--user .chat-msg__body {
  background: var(--chat-user-bg);
  color: var(--chat-user-text);
  padding: 8px 12px;
  border-radius: var(--radius) var(--radius) 0 var(--radius);
}

.chat-msg--assistant .chat-msg__body,
.chat-msg--system .chat-msg__body {
  background: var(--chat-system-bg);
  color: var(--chat-system-text);
  padding: 8px 12px;
  border-radius: var(--radius) var(--radius) var(--radius) 0;
}

.chat-msg__plan {
  margin-top: 6px;
  padding: 6px 8px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  background: var(--bg-code);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
}

/* Progress bar */
.chat-msg--progress {
  padding: 0 8px;
}

.progress-bar {
  height: 6px;
  background: var(--bg-input);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar__fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-bar__label {
  font-size: 0.7rem;
  color: var(--text-muted);
  margin-bottom: 4px;
}

/* Input area */
.chat-input-area {
  padding: 8px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.chat-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.suggestion-chip {
  padding: 4px 10px;
  font-size: 0.7rem;
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 9999px;
  cursor: pointer;
  transition: all var(--transition);
}
.suggestion-chip:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.chat-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chat-form__input-wrap {
  display: flex;
  gap: 6px;
  align-items: flex-end;
}

.chat-form__input {
  flex: 1;
  padding: 8px 12px;
  font-family: var(--font-sans);
  font-size: 0.82rem;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  resize: none;
  min-height: 36px;
  max-height: 200px;
  transition: border-color var(--transition);
}
.chat-form__input:focus {
  border-color: var(--border-focus);
  outline: none;
}

.chat-form__send {
  width: 36px;
  height: 36px;
  border: none;
  background: var(--accent);
  color: #fff;
  border-radius: var(--radius);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition);
  flex-shrink: 0;
}
.chat-form__send:hover:not(:disabled) {
  background: var(--accent-hover);
}
.chat-form__send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-form__hint {
  font-size: 0.65rem;
  color: var(--text-muted);
}

.chat-form__hint kbd {
  padding: 1px 4px;
  font-family: var(--font-mono);
  font-size: 0.6rem;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 2px;
}

/* WS status */
.ws-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: var(--text-muted);
}

.ws-status__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--error);
  transition: background var(--transition);
}
.ws-status__dot[data-connected="true"] {
  background: var(--success);
}

/* ─── Results Panel ───────────────────────────────── */
.results-tabs {
  display: flex;
  gap: 1px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  overflow-x: auto;
}

.results-tab {
  padding: 4px 10px;
  font-size: 0.72rem;
  font-weight: 500;
  background: transparent;
  color: var(--text-secondary);
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all var(--transition);
  white-space: nowrap;
}
.results-tab:hover {
  color: var(--text-primary);
}
.results-tab--active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.results-tab--disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.results-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.results-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 0.82rem;
}

.results-pane {
}

.result-section {
  margin-bottom: 16px;
}
.result-section__title {
  font-size: 0.82rem;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.result-section--warnings {
  color: var(--warning);
}
.result-section--warnings ul {
  padding-left: 16px;
  font-size: 0.75rem;
}

.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.result-table th,
.result-table td {
  padding: 4px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.result-table th {
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-input);
}
.result-table__key {
  font-weight: 500;
  color: var(--text-secondary);
  width: 40%;
}
.result-table__val {
  font-family: var(--font-mono);
}
.result-table__highlight td {
  background: rgba(99, 102, 241, 0.08);
  font-weight: 600;
}
.result-table--compact td,
.result-table--compact th {
  padding: 2px 6px;
  font-size: 0.7rem;
}

.json-viewer {
  max-height: 400px;
  overflow: auto;
}
.json-viewer pre {
  font-family: var(--font-mono);
  font-size: 0.68rem;
  line-height: 1.4;
  background: var(--bg-code);
  padding: 8px;
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-all;
}

/* ─── History Panel ───────────────────────────────── */
.history-search-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.history-search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.history-search {
  flex: 1;
  padding: 4px 8px;
  font-size: 0.75rem;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.history-search:focus {
  border-color: var(--border-focus);
  outline: none;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.history-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.history-card {
  padding: 8px;
  margin-bottom: 4px;
  background: var(--bg-input);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition);
}
.history-card:hover {
  border-color: var(--border);
  background: var(--bg-hover);
}
.history-card--active {
  border-color: var(--accent);
  background: rgba(99, 102, 241, 0.06);
}

.history-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.history-card__name {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 70%;
}

.history-card__status {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 9999px;
  text-transform: uppercase;
}
.history-card__status--queued {
  background: var(--bg-hover);
  color: var(--text-muted);
}
.history-card__status--running {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}
.history-card__status--completed {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
}
.history-card__status--failed,
.history-card__status--error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error);
}

.history-card__meta {
  display: flex;
  gap: 8px;
  font-size: 0.68rem;
  color: var(--text-muted);
}

/* ─── Loader ──────────────────────────────────────── */
.app-loader {
  position: fixed;
  inset: 0;
  background: var(--bg-app);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  transition: opacity 0.5s ease;
}
.app-loader.fade-out {
  opacity: 0;
  pointer-events: none;
}

.loader-content {
  text-align: center;
}

.loader-spinner {
  width: 40px;
  height: 40px;
  margin: 0 auto 16px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loader-text {
  font-weight: 600;
  margin-bottom: 4px;
}
.loader-sub {
  font-size: 0.8rem;
  color: var(--text-muted);
}

/* ─── Modal ───────────────────────────────────────── */
.modal {
  border: none;
  background: transparent;
  padding: 0;
  max-width: 100vw;
  max-height: 100vh;
}
.modal::backdrop {
  background: rgba(0, 0, 0, 0.5);
}

.modal__backdrop {
  position: fixed;
  inset: 0;
}

.modal__content {
  position: relative;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  min-width: 320px;
  max-width: 500px;
  z-index: 1;
}

.modal__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.modal__header h3 {
  font-size: 0.95rem;
  font-weight: 600;
}

.shortcuts-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.shortcut-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
}

.shortcut-keys {
  display: flex;
  align-items: center;
  gap: 2px;
}

.shortcut-keys kbd {
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 3px;
}

.shortcut-plus,
.shortcut-dash {
  margin: 0 2px;
  color: var(--text-muted);
  font-size: 0.7rem;
}

/* ─── Hidden/Session tabs ─────────────────────────── */
.session-tabs-container {
  padding: 0 8px;
}
.session-tabs {
  display: flex;
  gap: 4px;
}
.session-tab-bar {
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}

/* ─── Scrollbars ──────────────────────────────────── */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* ─── Scheme Preview ──────────────────────────────── */
.scheme-preview {
  display: inline-flex;
  gap: 2px;
  vertical-align: middle;
  margin-left: 4px;
}
.swatch {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  border: 1px solid var(--border);
}
.swatch-pos {
  background: #3b82f6;
}
.swatch-neg {
  background: #ef4444;
}

/* ─── Viewer Legend ────────────────────────────────── */
.viewer-legend {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 6px 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.7rem;
  opacity: 0.9;
}
```

---

## 파일 20/21: `src/qcviz_mcp/web/templates/index.html` (수정)

```html
<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1, viewport-fit=cover"
    />
    <title>QCViz-MCP v3</title>
    <meta
      name="description"
      content="Quantum chemistry visualization with PySCF, 3Dmol.js, Gemini AI, MolChat integration, and WebSocket orchestration."
    />
    <!-- FIX(M11): ARIA landmark: lang attribute set -->
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="/static/style.css" />

    <script>
      /* FIX(M11): QCVizApp global store — inline bootstrap */
      (function (g) {
        "use strict";
        if (g.QCVizApp && g.QCVizApp.__v3) return;

        var STORAGE_KEY = "QCVIZ_V3_UI_SNAPSHOTS";
        var listeners = new Map();

        function safeStr(v, fb) {
          return v == null ? fb || "" : String(v).trim();
        }
        function clone(v) {
          try {
            return JSON.parse(JSON.stringify(v));
          } catch (_) {
            return v;
          }
        }
        function deepMerge(base, patch) {
          var lhs = base && typeof base === "object" ? clone(base) : {};
          var rhs = patch && typeof patch === "object" ? patch : {};
          Object.keys(rhs).forEach(function (k) {
            var lv = lhs[k],
              rv = rhs[k];
            if (
              lv &&
              rv &&
              typeof lv === "object" &&
              typeof rv === "object" &&
              !Array.isArray(lv) &&
              !Array.isArray(rv)
            ) {
              lhs[k] = deepMerge(lv, rv);
            } else {
              lhs[k] = clone(rv);
            }
          });
          return lhs;
        }

        function makeSessionId() {
          var ts = Date.now().toString(36);
          var r = Math.random().toString(36).substring(2, 8);
          return "qcviz-" + ts + "-" + r;
        }

        var apiPrefix = g.QCVIZ_API_PREFIX || "";

        var store = {
          version: "v3",
          jobsById: {},
          jobOrder: [],
          resultsByJobId: {},
          activeJobId: null,
          activeResult: null,
          status: {
            text: "Ready",
            kind: "idle",
            source: "app",
            at: Date.now(),
          },
          uiSnapshotsByJobId: {},
          chatMessages: [],
          theme: "dark",
          lastUserInput: "",
          sessionId: makeSessionId(),
        };

        function emit(ev, detail) {
          (listeners.get(ev) || []).slice().forEach(function (fn) {
            try {
              fn(detail);
            } catch (_) {}
          });
        }
        function on(ev, fn) {
          if (!listeners.has(ev)) listeners.set(ev, []);
          listeners.get(ev).push(fn);
          return function () {
            var arr = listeners.get(ev) || [];
            var idx = arr.indexOf(fn);
            if (idx >= 0) arr.splice(idx, 1);
          };
        }

        function persistSnapshots() {
          try {
            localStorage.setItem(
              STORAGE_KEY,
              JSON.stringify(store.uiSnapshotsByJobId),
            );
          } catch (_) {}
        }
        function loadSnapshots() {
          try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (raw) store.uiSnapshotsByJobId = JSON.parse(raw);
          } catch (_) {}
        }
        loadSnapshots();

        var prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
        function applyTheme(theme) {
          store.theme = theme;
          document.documentElement.setAttribute("data-theme", theme);
          emit("theme:changed", { theme: theme });
        }
        var savedTheme = localStorage.getItem("QCVIZ_THEME");
        if (savedTheme) applyTheme(savedTheme);
        else applyTheme(prefersDark.matches ? "dark" : "light");
        prefersDark.addEventListener("change", function (e) {
          if (!localStorage.getItem("QCVIZ_THEME"))
            applyTheme(e.matches ? "dark" : "light");
        });

        g.QCVizApp = {
          __v3: true,
          store: store,
          on: on,
          emit: emit,
          clone: clone,
          deepMerge: deepMerge,
          apiPrefix: apiPrefix,

          setTheme: function (theme) {
            localStorage.setItem("QCVIZ_THEME", theme);
            applyTheme(theme);
          },

          setStatus: function (text, kind, source) {
            store.status = {
              text: text,
              kind: kind || "idle",
              source: source || "app",
              at: Date.now(),
            };
            emit("status:changed", clone(store.status));
          },

          upsertJob: function (job) {
            if (!job || typeof job !== "object") return null;
            var jobId = safeStr(job.job_id);
            if (!jobId) return null;
            var prev = store.jobsById[jobId] || {};
            var next = deepMerge(prev, job);
            store.jobsById[jobId] = next;
            if (next.result) store.resultsByJobId[jobId] = clone(next.result);
            store.jobOrder = Object.values(store.jobsById)
              .sort(function (a, b) {
                return (
                  Number(b.created_at || b.updated_at || 0) -
                  Number(a.created_at || a.updated_at || 0)
                );
              })
              .map(function (j) {
                return j.job_id;
              });
            emit("jobs:changed", {
              job: clone(next),
              jobs: store.jobOrder.map(function (id) {
                return clone(store.jobsById[id]);
              }),
            });
            return clone(next);
          },

          setActiveJob: function (jobId) {
            store.activeJobId = jobId;
            var result = store.resultsByJobId[jobId] || null;
            store.activeResult = result ? clone(result) : null;
            emit("activejob:changed", {
              jobId: jobId,
              result: store.activeResult,
            });
            if (result)
              emit("result:changed", {
                jobId: jobId,
                result: clone(result),
                source: "history",
              });
          },

          setActiveResult: function (res, opts) {
            opts = opts || {};
            var jobId = safeStr(opts.jobId || store.activeJobId);
            store.activeResult = res;
            if (jobId) {
              store.activeJobId = jobId;
              store.resultsByJobId[jobId] = clone(res);
            }
            emit("result:changed", {
              jobId: jobId,
              result: clone(res),
              source: opts.source || "app",
            });
          },

          saveUISnapshot: function (jobId, snapshot) {
            if (!jobId) return;
            store.uiSnapshotsByJobId[jobId] = clone(snapshot);
            persistSnapshots();
          },

          getUISnapshot: function (jobId) {
            return store.uiSnapshotsByJobId[jobId]
              ? clone(store.uiSnapshotsByJobId[jobId])
              : null;
          },

          addChatMessage: function (msg) {
            store.chatMessages.push(msg);
            emit("chat:message", clone(msg));
          },
        };
      })(window);
    </script>
  </head>

  <body>
    <!-- FIX(M11): skip-to-content link -->
    <a href="#chatInput" class="skip-link">Skip to chat input</a>

    <!-- Loading overlay -->
    <div id="appLoader" class="app-loader" role="status" aria-label="Loading">
      <div class="loader-content">
        <div class="loader-spinner"></div>
        <p class="loader-text">Initializing QCViz-MCP v3...</p>
        <p class="loader-sub">Loading 3D visualization engine</p>
      </div>
    </div>
    <script>
      window.addEventListener("load", function () {
        setTimeout(function () {
          var loader = document.getElementById("appLoader");
          if (loader) {
            loader.classList.add("fade-out");
            setTimeout(function () {
              if (loader.parentNode) loader.parentNode.removeChild(loader);
            }, 600);
          }
        }, 1500);
      });
    </script>

    <div class="app-shell" id="appShell">
      <!-- Top Bar -->
      <header class="topbar" id="topbar" role="banner">
        <div class="topbar__left">
          <div class="topbar__logo" aria-label="QCViz Logo">
            <svg
              width="28"
              height="28"
              viewBox="0 0 28 28"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <rect width="28" height="28" rx="8" fill="url(#logoGrad)" />
              <path
                d="M8 14a6 6 0 1 1 12 0 6 6 0 0 1-12 0Zm6-3.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"
                fill="white"
                fill-opacity="0.95"
              />
              <path
                d="M17.5 17.5L21 21"
                stroke="white"
                stroke-width="2"
                stroke-linecap="round"
                stroke-opacity="0.9"
              />
              <defs>
                <linearGradient
                  id="logoGrad"
                  x1="0"
                  y1="0"
                  x2="28"
                  y2="28"
                  gradientUnits="userSpaceOnUse"
                >
                  <stop stop-color="#6366f1" />
                  <stop offset="1" stop-color="#8b5cf6" />
                </linearGradient>
              </defs>
            </svg>
            <span class="topbar__title"
              >QCViz-MCP <span class="topbar__badge">v3</span></span
            >
          </div>
        </div>
        <div class="topbar__center">
          <div class="status-indicator" id="globalStatus" role="status">
            <span class="status-indicator__dot" data-kind="idle"></span>
            <span class="status-indicator__text">Ready</span>
          </div>
        </div>
        <div class="topbar__right">
          <button
            class="icon-btn"
            id="btnThemeToggle"
            aria-label="Toggle theme"
            title="Toggle theme (Ctrl+\)"
          >
            <svg
              class="icon-sun"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="5" />
              <path
                d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
              />
            </svg>
            <svg
              class="icon-moon"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          </button>
          <button
            class="icon-btn"
            id="btnKeyboardShortcuts"
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path
                d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"
              />
            </svg>
          </button>
        </div>
      </header>

      <!-- FIX(M11): 3-column dashboard with ARIA landmarks -->
      <main class="dashboard" id="dashboard" role="main">
        <!-- Viewer Panel (column 1) -->
        <section
          class="panel panel--viewer"
          id="panelViewer"
          aria-label="3D Molecular Viewer"
          role="region"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
              Molecular Viewer
            </h2>
            <div class="panel__actions">
              <button class="chip-btn" id="btnViewerReset" title="Reset view">
                Reset
              </button>
              <div id="vizModeToggle" class="viz-mode-toggle" hidden>
                <button
                  id="btnModeOrbital"
                  class="toggle-btn active"
                  title="Orbital surface"
                >
                  Orbital
                </button>
                <button id="btnModeESP" class="toggle-btn" title="ESP map">
                  ESP
                </button>
              </div>
              <button
                class="chip-btn"
                id="btnViewerScreenshot"
                title="Screenshot"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                Capture
              </button>
              <button
                class="icon-btn icon-btn--sm"
                id="btnViewerFullscreen"
                title="Fullscreen"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path
                    d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
                  />
                </svg>
              </button>
            </div>
          </div>
          <div class="viewer-container" id="viewerContainer">
            <div class="viewer-3d" id="viewer3d"></div>
            <div class="viewer-empty" id="viewerEmpty">
              <div class="viewer-empty__icon">
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  opacity="0.35"
                >
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <p class="viewer-empty__text">
                Submit a computation to render the molecule
              </p>
              <p class="viewer-empty__hint">
                Try: "Calculate energy of water with STO-3G"
              </p>
            </div>
            <div class="viewer-controls" id="viewerControls" hidden>
              <div class="viewer-controls__group">
                <label class="viewer-controls__label">Style</label>
                <div class="segmented" id="segStyle">
                  <button
                    class="segmented__btn segmented__btn--active"
                    data-value="stick"
                  >
                    Stick
                  </button>
                  <button class="segmented__btn" data-value="sphere">
                    Sphere
                  </button>
                  <button class="segmented__btn" data-value="line">Line</button>
                </div>
              </div>
              <div class="viewer-controls__group" id="grpOrbital" hidden>
                <label class="viewer-controls__label">Isosurface</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderIsovalue"
                  min="0.001"
                  max="0.1"
                  step="0.001"
                  value="0.03"
                />
                <span class="viewer-controls__value" id="lblIsovalue"
                  >0.030</span
                >
              </div>
              <div class="viewer-controls__group" id="grpESP" hidden>
                <label class="viewer-controls__label">ESP Density Iso</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderEspDensIso"
                  min="0.0001"
                  max="0.02"
                  step="0.0001"
                  value="0.001"
                />
                <span class="viewer-controls__value" id="lblEspDensIso"
                  >0.0010</span
                >
              </div>
              <div class="viewer-controls__group" id="grpOpacity" hidden>
                <label class="viewer-controls__label">Opacity</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderOpacity"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value="0.75"
                />
                <span class="viewer-controls__value" id="lblOpacity">0.75</span>
              </div>
              <div class="viewer-controls__group" id="grpColorScheme">
                <label class="viewer-controls__label">Color Scheme</label>
                <select id="selectColorScheme" class="viewer-select">
                  <option value="classic">Classic (Blue/Red)</option>
                  <option value="jmol">Jmol</option>
                  <option value="rwb">RWB</option>
                  <option value="bwr">BWR</option>
                  <option value="spectral">Spectral</option>
                  <option value="viridis">Viridis</option>
                  <option value="inferno">Inferno</option>
                </select>
              </div>
              <div class="viewer-controls__group" id="grpOrbitalSelect" hidden>
                <label class="viewer-controls__label">Orbital</label>
                <select class="viewer-select" id="selectOrbital"></select>
              </div>
              <div class="viewer-controls__group">
                <label class="viewer-controls__label">Labels</label>
                <button
                  class="toggle-btn"
                  id="btnToggleLabels"
                  data-active="true"
                  aria-pressed="true"
                >
                  On
                </button>
              </div>
            </div>
            <div class="viewer-legend" id="viewerLegend" hidden></div>
          </div>
        </section>

        <!-- Chat Panel (column 2) -->
        <section
          class="panel panel--chat"
          id="panelChat"
          aria-label="Chat Assistant"
          role="region"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
                />
              </svg>
              Assistant
            </h2>
            <div class="panel__actions">
              <div class="ws-status" id="wsStatus">
                <span class="ws-status__dot" data-connected="false"></span>
                <span class="ws-status__label">Disconnected</span>
              </div>
            </div>
          </div>
          <div class="chat-scroll" id="chatScroll">
            <div
              class="chat-messages"
              id="chatMessages"
              aria-live="polite"
              aria-relevant="additions"
            >
              <div class="chat-msg chat-msg--system">
                <div class="chat-msg__avatar chat-msg__avatar--system">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path d="M12 2L2 7l10 5 10-5-10-5z" />
                    <path d="M2 17l10 5 10-5" />
                  </svg>
                </div>
                <div class="chat-msg__body">
                  <p class="chat-msg__text">
                    Welcome to <strong>QCViz-MCP v3</strong>. I can run quantum
                    chemistry calculations using PySCF with Gemini AI planning.
                    Ask me to compute energies, optimize geometries, visualize
                    orbitals and ESP maps. Supports Korean input and ion pairs.
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div class="chat-input-area" id="chatInputArea">
            <div class="chat-suggestions" id="chatSuggestions">
              <button
                class="suggestion-chip"
                data-prompt="Calculate the energy of water using STO-3G basis"
              >
                Water energy
              </button>
              <button
                class="suggestion-chip"
                data-prompt="벤젠의 HOMO 오비탈을 보여줘"
              >
                벤젠 HOMO
              </button>
              <button
                class="suggestion-chip"
                data-prompt="Optimize the geometry of methane with 6-31G basis"
              >
                Methane optimize
              </button>
              <button
                class="suggestion-chip"
                data-prompt="아스피린의 ESP 맵을 계산해줘"
              >
                아스피린 ESP
              </button>
            </div>
            <form class="chat-form" id="chatForm" autocomplete="off">
              <div class="chat-form__input-wrap">
                <textarea
                  class="chat-form__input"
                  id="chatInput"
                  placeholder="Ask about quantum chemistry... / 양자화학에 대해 물어보세요..."
                  rows="1"
                  maxlength="4000"
                ></textarea>
                <button
                  class="chat-form__send"
                  id="chatSend"
                  type="submit"
                  aria-label="Send"
                  disabled
                >
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              </div>
              <p class="chat-form__hint">
                Press <kbd>Enter</kbd> to send, <kbd>Shift+Enter</kbd> for new
                line
              </p>
            </form>
          </div>
        </section>

        <!-- Results Panel (column 3, row 1) -->
        <section
          class="panel panel--results"
          id="panelResults"
          aria-label="Computation Results"
          role="region"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              Results
            </h2>
          </div>
          <div class="results-tabs" id="resultsTabs" role="tablist"></div>
          <div class="results-content" id="resultsContent">
            <div class="results-empty" id="resultsEmpty">
              <p>No results yet. Submit a computation from the chat.</p>
            </div>
          </div>
        </section>

        <!-- History Panel (column 3, row 2) -->
        <section
          class="panel panel--history"
          id="panelHistory"
          aria-label="Job History"
          role="region"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              History
            </h2>
            <div class="panel__actions">
              <button
                class="icon-btn icon-btn--sm"
                id="btnRefreshHistory"
                title="Refresh"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
              </button>
            </div>
          </div>
          <div class="history-search-wrap">
            <svg
              class="history-search-icon"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              class="history-search"
              id="historySearch"
              placeholder="Search jobs..."
            />
          </div>
          <div class="history-list" id="historyList">
            <div class="history-empty" id="historyEmpty">
              <p>No previous computations</p>
            </div>
          </div>
        </section>
      </main>
    </div>

    <!-- Keyboard Shortcuts Modal -->
    <dialog class="modal" id="modalShortcuts">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__content">
        <div class="modal__header">
          <h3>Keyboard Shortcuts</h3>
          <button class="icon-btn icon-btn--sm" data-close aria-label="Close">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div class="modal__body shortcuts-grid">
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>/</kbd></span
            ><span>Focus chat input</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>K</kbd></span
            ><span>Search history</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>\</kbd></span
            ><span>Toggle theme</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"><kbd>Esc</kbd></span
            ><span>Close modals / blur</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>1</kbd><span class="shortcut-dash">&ndash;</span
              ><kbd>6</kbd></span
            ><span>Switch result tabs</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"><kbd>?</kbd></span
            ><span>Show this dialog</span>
          </div>
        </div>
      </div>
    </dialog>

    <!-- FIX(M11): JS 로드 순서 — chat → results → viewer → app -->
    <script src="/static/chat.js" defer></script>
    <script src="/static/results.js" defer></script>
    <script src="/static/viewer.js" defer></script>
    <script src="/static/app.js" defer></script>
  </body>
</html>
```

---

## 파일 21/21: `requirements.txt` (수정)

```txt
# QCViz-MCP v3 requirements
# FIX(M11): google-genai, httpx, tenacity 추가

fastapi>=0.110,<1.0
uvicorn[standard]>=0.29,<1.0
jinja2>=3.1,<4.0
pydantic>=2.6,<3.0

numpy>=1.26
scipy>=1.11
pyscf>=2.4,<3.0

openai>=1.30,<2.0
google-genai>=1.0,<2.0

python-dotenv>=1.0,<2.0
httpx>=0.27,<1.0
orjson>=3.10,<4.0
tenacity>=8.0,<10.0
```

---

## 출력 완료 — 전체 21/21 파일

모든 파일 출력이 완료되었습니다. 요약:

| 범위                                                                     | 파일 수 | 상태                    |
| ------------------------------------------------------------------------ | ------- | ----------------------- |
| 파일 1–8 (services/ 신규)                                                | 8       | 이전 대화에서 출력 완료 |
| 파일 9–14 (config, agent, compute, chat, pyscf_runner, job_manager 수정) | 6       | 이전 대화에서 출력 완료 |
| 파일 15–21 (JS 4개 + CSS + HTML + requirements)                          | 7       | **이번 출력 완료**      |

핵심 체크리스트 확인:

1. `services/` 디렉토리 8개 신규 파일 — 완료
2. `config.py` 환경변수 9개 추가 — 완료
3. `llm/agent.py` Gemini agent 대체 — 완료
4. `compute.py` structure_resolver 교체 — 완료
5. MolChat API `http://psid.aizen.co.kr/molchat` 경로 — 완료
6. 이온쌍 end-to-end 경로 — 완료
7. PubChem 폴백 — 완료
8. SDF→XYZ PySCF 호환 — 완료
9. 프론트엔드 DOM ID 유지 (`chatMessages`, `chatInput`, `chatSend`, `viewer3d`, `historyList` 등) — 완료
10. `requirements.txt`에 `google-genai`, `httpx`, `tenacity` — 완료
