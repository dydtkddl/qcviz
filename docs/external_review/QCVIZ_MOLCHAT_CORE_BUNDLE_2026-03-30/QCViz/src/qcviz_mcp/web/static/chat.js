/**
 * QCViz-MCP v3 — Chat Module
 * FIX(M7): 재귀 방지(depth guard), 상태 머신, 지수 백오프 재접속,
 *          XSS 방지(textContent), aria-live, client ping 20s
 */
(function (g) {
  "use strict";
  console.log("[chat.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[chat.js] ✖ QCVizApp not found — aborting chat module");
    return;
  }
  console.log("[chat.js] ✔ QCVizApp found");

  // ─── 상수 ───────────────────────────────────────────
  var MAX_RECONNECT = 10;
  var RECONNECT_BASE_MS = 1000;
  var RECONNECT_MAX_MS = 30000;
  var PING_INTERVAL_MS = 20000;
  var MAX_DEPTH = 3;
  var SCF_CHART_ASPECT = 7 / 2;
  var SCF_CHART_MIN_CSS_HEIGHT = 120;

  // ─── 상태 머신 ──────────────────────────────────────
  var STATE_IDLE = "idle";
  var STATE_SENDING = "sending";
  var STATE_AWAITING = "awaiting_ack";

  var chatState = STATE_IDLE;
  var ws = null;
  var reconnectCount = 0;
  var reconnectTimer = null;
  var pingTimer = null;
  var depth = 0;
  var activeJobIdForChat = null;  // Track current job for per-job chat storage
  var pendingTurnId = null;
  var currentTurnId = null;
  var messageCounter = 0;
  var renderedMessageIds = {};
  var activeClarifyCard = null;
  var activeConfirmCard = null;
  var historyRestored = false;

  // ─── DOM refs ───────────────────────────────────────
  var chatMessages = document.getElementById("chatMessages");
  var chatInput = document.getElementById("chatInput");
  var chatSend = document.getElementById("chatSend");
  var chatForm = document.getElementById("chatForm");
  var chatScroll = document.getElementById("chatScroll");
  var wsStatusDot = null;
  var wsStatusLabel = null;
  var initialChatMarkup = chatMessages ? chatMessages.innerHTML : "";

  console.log("[chat.js] DOM refs:", {
    chatMessages: !!chatMessages, chatInput: !!chatInput,
    chatSend: !!chatSend, chatForm: !!chatForm, chatScroll: !!chatScroll,
  });

  function initWsStatus() {
    var wsStatus = document.getElementById("wsStatus");
    if (wsStatus) {
      wsStatusDot = wsStatus.querySelector(".ws-status__dot");
      wsStatusLabel = wsStatus.querySelector(".ws-status__label");
    }
    console.log("[chat.js] initWsStatus — dot:", !!wsStatusDot, "label:", !!wsStatusLabel);
  }

  // ─── 유틸 ───────────────────────────────────────────

  function escapeText(str) {
    if (str == null) return "";
    return String(str);
  }

  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function nextTurnId() {
    return "turn-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
  }

  function nextMessageId() {
    messageCounter += 1;
    return "msg-" + Date.now().toString(36) + "-" + String(messageCounter);
  }

  function clearRenderedMessageIds() {
    renderedMessageIds = {};
  }

  function retireInteractiveCard(kind, reason) {
    var card = kind === "confirm" ? activeConfirmCard : activeClarifyCard;
    if (!card) return;
    if (card.parentNode) {
      card.setAttribute("data-state", reason || "retired");
      card.classList.add("chat-msg--stale");
      card.parentNode.removeChild(card);
    }
    if (kind === "confirm") activeConfirmCard = null;
    else activeClarifyCard = null;
  }

  function retireAllInteractiveCards(reason) {
    retireInteractiveCard("clarify", reason);
    retireInteractiveCard("confirm", reason);
  }

  function setActiveInteractiveCard(kind, node) {
    if (kind === "clarify") {
      retireInteractiveCard("clarify", "superseded");
      activeClarifyCard = node;
      return;
    }
    retireInteractiveCard("confirm", "superseded");
    activeConfirmCard = node;
  }

  function setWsConnected(connected) {
    console.log("[chat.js] setWsConnected:", connected);
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

  function clearChatSurface() {
    if (!chatMessages) return;
    retireAllInteractiveCards("reset");
    chatMessages.innerHTML = "";
    clearRenderedMessageIds();
    activeClarifyCard = null;
    activeConfirmCard = null;
  }

  function resetChatMessagesToBase() {
    if (!chatMessages) return;
    clearChatSurface();
    if (initialChatMarkup) {
      chatMessages.innerHTML = initialChatMarkup;
    }
  }

  function ensureAriaLive() {
    if (!chatMessages) return;
    if (!chatMessages.getAttribute("aria-live")) {
      chatMessages.setAttribute("aria-live", "polite");
      chatMessages.setAttribute("aria-relevant", "additions");
    }
  }

  // ─── 메시지 렌더링 ─────────────────────────────

  function _renderMarkdown(text) {
    // Escape HTML first for XSS safety
    var html = escapeText(text);

    // Code blocks (```...```)
    html = html.replace(/```([\s\S]*?)```/g, function (_, code) {
      return '<pre class="chat-code"><code>' + code.trim() + '</code></pre>';
    });

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');

    // Headers
    html = html.replace(/^### (.+)$/gm, '<strong class="chat-h3">$1</strong>');
    html = html.replace(/^## (.+)$/gm, '<strong class="chat-h2">$1</strong>');
    html = html.replace(/^# (.+)$/gm, '<strong class="chat-h1">$1</strong>');

    // Bold + italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(?<![*])\*([^*]+?)\*(?![*])/g, '<em>$1</em>');

    // Bullet lists (lines starting with - or * )
    html = html.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li class="chat-li">$1</li>');
    html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, function (m) {
      return '<ul class="chat-ul">' + m + '</ul>';
    });

    // Numbered lists (lines starting with 1. 2. etc.)
    html = html.replace(/^\s*(\d+)\.\s+(.+)$/gm, '<li class="chat-li" value="$1">$2</li>');
    html = html.replace(/(<li class="chat-li" value="\d+">.*<\/li>\n?)+/g, function (m) {
      return '<ol class="chat-ol">' + m + '</ol>';
    });

    // Line breaks (preserve double newlines as paragraphs)
    html = html.replace(/\n\n/g, '</p><p class="chat-p">');
    html = html.replace(/\n/g, '<br>');

    return '<p class="chat-p">' + html + '</p>';
  }

  function appendMessage(role, text, extra) {
    console.log("[chat.js] appendMessage — role:", role, "text length:", (text||"").length,
      "extra:", extra ? Object.keys(extra).join(",") : "none");
    if (!chatMessages) return;
    extra = extra || {};
    var messageId = safeStr(extra.messageId) || nextMessageId();
    if (renderedMessageIds[messageId]) return;
    renderedMessageIds[messageId] = true;
    var turnId = safeStr(extra.turnId || pendingTurnId || currentTurnId);
    var explicitJobId = safeStr(extra.jobId);
    var resolvedJobId = explicitJobId || safeStr(activeJobIdForChat);

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--" + safeStr(role, "system");
    wrapper.setAttribute("data-message-id", messageId);
    if (turnId) wrapper.setAttribute("data-turn-id", turnId);
    if (resolvedJobId) wrapper.setAttribute("data-job-id", resolvedJobId);

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

    var p = document.createElement("div");
    p.className = "chat-msg__text";
    if (role === "assistant" || role === "system") {
      p.innerHTML = _renderMarkdown(text);
    } else {
      p.textContent = escapeText(text);
    }

    body.appendChild(p);

    if (extra.plan) {
      console.log("[chat.js] appendMessage — attaching plan JSON");
      var planEl = document.createElement("pre");
      planEl.className = "chat-msg__plan";
      planEl.textContent = JSON.stringify(extra.plan, null, 2);
      body.appendChild(planEl);
    }

    wrapper.appendChild(avatar);
    wrapper.appendChild(body);
    chatMessages.appendChild(wrapper);

    if (!extra.suppressPersist) {
      App.addChatMessage({
        id: messageId,
        role: role, text: text, jobId: resolvedJobId || null,
        turnId: turnId || null,
        timestamp: Date.now(), extra: extra,
      });
    }

    scrollToBottom();
  }

  function _syncQuota(quota) {
    if (quota && typeof App.setQuota === "function") {
      App.setQuota(quota);
    }
  }

  function _syncQueue(queue) {
    if (queue && typeof App.setQueue === "function") {
      App.setQueue(queue);
    }
  }

  function appendQuotaWarning(message, quota) {
    if (!chatMessages) return;
    _syncQuota(quota);

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--system";

    var avatar = document.createElement("div");
    avatar.className = "chat-msg__avatar chat-msg__avatar--system";
    avatar.textContent = "!";

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var card = document.createElement("div");
    card.className = "quota-alert";
    var title = document.createElement("strong");
    title.className = "quota-alert__title";
    title.textContent = "Active job quota reached";
    var text = document.createElement("p");
    text.className = "quota-alert__body";
    text.textContent = safeStr(message);
    var meta = document.createElement("div");
    meta.className = "quota-alert__meta";
    var sessionText = quota ? (Number(quota.active_for_session || 0) + "/" + Number(quota.max_active_per_session || 0)) : "—/—";
    var userLimited = !!(quota && quota.user_limited);
    var userText = userLimited ? (Number(quota.active_for_owner || 0) + "/" + Number(quota.max_active_per_user || 0)) : "";
    var sessionEl = document.createElement("span");
    sessionEl.textContent = "session " + sessionText;
    meta.appendChild(sessionEl);
    if (userLimited) {
      var userEl = document.createElement("span");
      userEl.textContent = "user " + userText;
      meta.appendChild(userEl);
    }
    var hintEl = document.createElement("span");
    hintEl.textContent = "기존 작업이 끝나거나 취소되면 다시 제출할 수 있습니다.";
    meta.appendChild(hintEl);
    card.appendChild(title);
    card.appendChild(text);
    card.appendChild(meta);

    body.appendChild(card);
    wrapper.appendChild(avatar);
    wrapper.appendChild(body);
    chatMessages.appendChild(wrapper);
    scrollToBottom();

    App.addChatMessage({
      role: "system",
      text: "Quota reached: " + safeStr(message),
      jobId: activeJobIdForChat || null,
      timestamp: Date.now(),
      extra: { quota: quota || null, kind: "quota_warning" },
    });

    if (typeof App.refreshHistory === "function") {
      App.refreshHistory();
    }
  }

  function _buildQueueSummary(queue, status) {
    if (!queue) return null;
    var running = Math.max(0, Number(queue.running_count || 0));
    var queued = Math.max(0, Number(queue.queued_count || 0));
    var maxWorkers = Math.max(1, Number(queue.max_workers || 1));
    var queuedAhead = Math.max(0, Number(queue.queued_ahead || 0));
    var queuePosition = queue.queue_position == null ? null : Number(queue.queue_position);
    var effectiveStatus = safeStr(queue.job_status || status || "");
    var lines = null;

    if (effectiveStatus === "queued") {
      lines = {
        tone: "queued",
        title: queuedAhead > 0 ? "대기열 앞 " + queuedAhead + "개" : "다음 차례",
        meta:
          "실행 중 " + running + "/" + maxWorkers +
          (queued ? " · 전체 대기 " + queued + "개" : "") +
          (queuePosition ? " · 내 순번 " + queuePosition : ""),
      };
    } else if (effectiveStatus === "running") {
      lines = {
        tone: "running",
        title: "지금 계산 중",
        meta:
          "실행 중 " + running + "/" + maxWorkers +
          (queued ? " · 뒤 대기 " + queued + "개" : ""),
      };
    } else if (effectiveStatus === "completed") {
      lines = {
        tone: "done",
        title: "계산 완료",
        meta: queued ? "남은 대기 " + queued + "개" : "대기열 비어 있음",
      };
    } else if (running || queued) {
      lines = {
        tone: "queued",
        title: "대기열 갱신",
        meta: "실행 중 " + running + "/" + maxWorkers + " · 전체 대기 " + queued + "개",
      };
    }

    return lines;
  }

  function _updateQueueMeta(container, queue, status) {
    if (!container) return;
    var badge = container.querySelector(".progress-queue");
    var title = container.querySelector(".progress-queue__title");
    var meta = container.querySelector(".progress-queue__meta");
    if (!badge || !title || !meta) return;

    var summary = _buildQueueSummary(queue, status);
    if (!summary) {
      badge.style.display = "none";
      badge.classList.remove("progress-queue--queued", "progress-queue--running", "progress-queue--done");
      return;
    }

    badge.style.display = "flex";
    badge.classList.remove("progress-queue--queued", "progress-queue--running", "progress-queue--done");
    badge.classList.add("progress-queue--" + summary.tone);
    title.textContent = summary.title;
    meta.textContent = summary.meta;
  }

  function appendProgress(jobId, progress, step, message, extra) {
    var pct = Math.round(Math.min(100, Math.max(0, (progress || 0) * 100)));
    console.log("[chat.js] appendProgress — jobId:", jobId, "pct:", pct, "step:", step, "msg:", message);

    var existing = chatMessages
      ? chatMessages.querySelector('[data-progress-job="' + jobId + '"]')
      : null;

    if (existing) {
      var bar = existing.querySelector(".progress-bar__fill");
      var lbl = existing.querySelector(".progress-bar__label");
      if (bar) bar.style.width = pct + "%";
      if (lbl)
        lbl.textContent =
          safeStr(message, step || "Working...") + " (" + pct + "%)";
      _syncQueue(extra && extra.queue);
      _updateQueueMeta(existing, extra && extra.queue, extra && extra.status);

      // Update SCF convergence chart if available
      if (extra && extra.scf_history && extra.scf_history.length > 1) {
        _renderScfChart(existing, extra.scf_history);
      }
      return;
    }

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--progress";
    wrapper.setAttribute("data-progress-job", jobId);

    var body = document.createElement("div");
    body.className = "chat-msg__body progress-card";

    var queueBadge = document.createElement("div");
    queueBadge.className = "progress-queue";
    queueBadge.style.display = "none";
    var queueTitle = document.createElement("div");
    queueTitle.className = "progress-queue__title";
    var queueMeta = document.createElement("div");
    queueMeta.className = "progress-queue__meta";
    queueBadge.appendChild(queueTitle);
    queueBadge.appendChild(queueMeta);
    body.appendChild(queueBadge);

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

    // Add cancel button
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "scf-cancel-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.title = "Cancel this computation";
    cancelBtn.onclick = function () {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelling...";
      var sessionId = encodeURIComponent(safeStr(App.store.sessionId));
      fetch(window.__ROOT_PATH + "/compute/jobs/" + jobId + "/cancel?session_id=" + sessionId, {
        method: "POST",
        headers: Object.assign(
          { "X-QCViz-Session-Id": safeStr(App.store.sessionId) },
          typeof App.getAuthHeaders === "function" ? App.getAuthHeaders() : {},
          typeof App.getSessionHeaders === "function" ? App.getSessionHeaders() : {},
        )
      })
        .then(function () { cancelBtn.textContent = "Cancelled"; })
        .catch(function () { cancelBtn.textContent = "Cancel"; cancelBtn.disabled = false; });
    };
    body.appendChild(cancelBtn);

    // Add SCF chart area
    var chartArea = document.createElement("div");
    chartArea.className = "scf-chart-area";
    chartArea.style.display = "none";
    var canvas = document.createElement("canvas");
    canvas.className = "scf-chart-canvas";
    canvas.width = 280;
    canvas.height = 80;
    chartArea.appendChild(canvas);
    body.appendChild(chartArea);

    wrapper.appendChild(body);

    if (chatMessages) chatMessages.appendChild(wrapper);
    _syncQueue(extra && extra.queue);
    _updateQueueMeta(wrapper, extra && extra.queue, extra && extra.status);
    if (extra && extra.scf_history && extra.scf_history.length > 1) {
      _renderScfChart(wrapper, extra.scf_history);
    }
    scrollToBottom();
  }

  // Mini convergence chart: log|dE| vs cycle
  function _prepareHiDpiCanvas(canvas) {
    if (!canvas) return null;
    var rect = canvas.getBoundingClientRect();
    var cssWidth = Math.max(320, Math.round(rect.width || canvas.clientWidth || 420));
    var cssHeight = Math.max(
      SCF_CHART_MIN_CSS_HEIGHT,
      Math.round(rect.height || (cssWidth / SCF_CHART_ASPECT))
    );
    var dpr = Math.max(1, Math.min(3, g.devicePixelRatio || 1));

    canvas.style.height = cssHeight + "px";
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);

    var ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, width: cssWidth, height: cssHeight, dpr: dpr };
  }

  function _renderScfChart(container, history) {
    var chartArea = container.querySelector(".scf-chart-area");
    var canvas = container.querySelector(".scf-chart-canvas");
    if (!chartArea || !canvas) return;
    chartArea.style.display = "block";

    var prepared = _prepareHiDpiCanvas(canvas);
    if (!prepared) return;
    var ctx = prepared.ctx;
    var W = prepared.width;
    var H = prepared.height;
    var padX = 16;
    var padTop = 14;
    var padBottom = 18;
    var plotW = Math.max(1, W - padX * 2);
    var plotH = Math.max(1, H - padTop - padBottom);

    // Filter entries with dE
    var pts = [];
    for (var i = 0; i < history.length; i++) {
      if (history[i].dE != null && history[i].dE !== 0) {
        pts.push({ c: history[i].cycle, v: Math.log10(Math.abs(history[i].dE)) });
      }
    }
    if (pts.length < 2) return;

    var minV = pts[0].v, maxV = pts[0].v;
    for (var j = 0; j < pts.length; j++) {
      if (pts[j].v < minV) minV = pts[j].v;
      if (pts[j].v > maxV) maxV = pts[j].v;
    }
    var rangeV = maxV - minV || 1;

    // Background
    ctx.fillStyle = "rgba(15, 23, 42, 0.05)";
    ctx.fillRect(0, 0, W, H);

    // Plot frame
    ctx.strokeStyle = "rgba(148, 163, 184, 0.30)";
    ctx.lineWidth = 1;
    ctx.strokeRect(padX, padTop, plotW, plotH);

    // Convergence threshold line (1e-9)
    var threshY = padTop + (1 - (((-9) - minV) / rangeV)) * plotH;
    if (threshY > padTop && threshY < H - padBottom) {
      ctx.strokeStyle = "rgba(239,68,68,0.4)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padX, threshY);
      ctx.lineTo(W - padX, threshY);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Plot line
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    for (var k = 0; k < pts.length; k++) {
      var x = padX + (k / Math.max(1, (pts.length - 1))) * plotW;
      var y = padTop + (1 - ((pts[k].v - minV) / rangeV)) * plotH;
      if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    for (var m = 0; m < pts.length; m++) {
      var px = padX + (m / Math.max(1, (pts.length - 1))) * plotW;
      var py = padTop + (1 - ((pts[m].v - minV) / rangeV)) * plotH;
      ctx.fillStyle = "#16a34a";
      ctx.beginPath();
      ctx.arc(px, py, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Labels
    ctx.fillStyle = "#64748b";
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    ctx.fillText("log|dE|", padX, 11);
    ctx.textAlign = "right";
    ctx.fillText(maxV.toFixed(1), W - padX, 11);
    ctx.fillText(minV.toFixed(1), W - padX, H - 4);
    ctx.textAlign = "left";
    ctx.fillText("cycle 1", padX, H - 4);
    ctx.textAlign = "right";
    ctx.fillText("cycle " + pts[pts.length - 1].c, W - padX, H - 4);
    ctx.textAlign = "start";
  }

  // ─── Clarification Form ──────────────────────────────
  function _renderClarifyHelp(text) {
    if (!text) return null;
    var help = document.createElement("div");
    help.className = "clarify-field__help";
    help.textContent = text;
    return help;
  }

  function _renderClarifyField(group, form, field) {
    if (field.type === "radio" && field.options) {
      field.options.forEach(function (opt) {
        var radioWrap = document.createElement("label");
        radioWrap.className = "clarify-radio";
        var radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "clarify_" + field.id;
        radio.value = opt.value;
        if (opt.value === field.default) radio.checked = true;
        radioWrap.appendChild(radio);
        radioWrap.appendChild(document.createTextNode(" " + opt.label));
        group.appendChild(radioWrap);
      });
      return;
    }

  if (field.type === "select" && field.options) {
    var sel = document.createElement("select");
    sel.className = "clarify-select";
    sel.setAttribute("data-field-id", field.id);
    field.options.forEach(function (opt) {
        var option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.label;
        if (opt.value === field.default) option.selected = true;
        sel.appendChild(option);
      });
      group.appendChild(sel);
      return;
    }

    if (field.type === "multiselect" && field.options) {
      var multi = document.createElement("select");
      multi.className = "clarify-multiselect";
      multi.setAttribute("data-field-id", field.id);
      multi.multiple = true;
      multi.size = Math.min(field.options.length, 5);
      field.options.forEach(function (opt) {
        var option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.label;
        if (Array.isArray(field.default) && field.default.includes(opt.value)) {
          option.selected = true;
        }
        multi.appendChild(option);
      });
      group.appendChild(multi);
      return;
    }

    if (field.type === "textarea") {
      var textarea = document.createElement("textarea");
      textarea.className = "clarify-input";
      textarea.setAttribute("data-field-id", field.id);
      textarea.placeholder = field.placeholder || "";
      if (field.default) textarea.value = field.default;
      group.appendChild(textarea);
      return;
    }

    if (field.type === "number") {
      var numInput = document.createElement("input");
      numInput.type = "number";
      numInput.className = "clarify-input";
      numInput.setAttribute("data-field-id", field.id);
      numInput.value = field.default != null ? field.default : 0;
      group.appendChild(numInput);
      return;
    }

    if (field.type === "checkbox") {
      var checkboxWrap = document.createElement("label");
      checkboxWrap.className = "clarify-radio";
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.setAttribute("data-field-id", field.id);
      checkbox.checked = !!field.default;
      checkboxWrap.appendChild(checkbox);
      checkboxWrap.appendChild(document.createTextNode(" " + (field.help_text || field.label)));
      group.appendChild(checkboxWrap);
      return;
    }

    var txtInput = document.createElement("input");
    txtInput.type = "text";
    txtInput.className = "clarify-input";
    txtInput.setAttribute("data-field-id", field.id);
    txtInput.placeholder = field.placeholder || "";
    if (field.default) txtInput.value = field.default;
    group.appendChild(txtInput);
  }

  function _collectClarifyAnswers(form, fields) {
    var answers = {};
    var invalid = [];

    fields.forEach(function (field) {
      var value;
      if (field.type === "radio") {
        var checked = form.querySelector('input[name="clarify_' + field.id + '"]:checked');
        value = checked ? checked.value : field.default;
      } else if (field.type === "checkbox") {
        var checkbox = form.querySelector('[data-field-id="' + field.id + '"]');
        value = checkbox ? !!checkbox.checked : !!field.default;
      } else {
      if (field.type === "multiselect") {
        var multi = form.querySelector('[data-field-id="' + field.id + '"]');
        if (multi) {
          value = Array.from(multi.selectedOptions || []).map(function (opt) {
            return opt.value;
          });
        } else {
          value = Array.isArray(field.default) ? field.default : [];
        }
      } else {
        var el = form.querySelector('[data-field-id="' + field.id + '"]');
        value = el ? el.value : field.default;
      }
      }

      var isEmptyArray = Array.isArray(value) && value.length === 0;
      if (
        field.required &&
        (
          value == null ||
          (Array.isArray(value) ? isEmptyArray : String(value).trim() === "")
        )
      ) {
        invalid.push(field.label || field.id);
      }
      answers[field.id] = value;
    });

    return { answers: answers, invalid: invalid };
  }

  function _renderClarifyForm(formObj, fallbackFields, sessionId, turnId) {
    var clarifyForm = formObj || {};
    var fields = clarifyForm.fields || fallbackFields || [];
    var titleText = clarifyForm.title || "Need more information";
    var message = clarifyForm.message || "Please clarify:";

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--clarify";
    if (turnId) wrapper.setAttribute("data-turn-id", turnId);

    var body = document.createElement("div");
    body.className = "chat-msg__body clarify-form";

    var title = document.createElement("p");
    title.className = "clarify-form__title";
    title.textContent = titleText;
    body.appendChild(title);

    if (message) {
      var subtitle = document.createElement("p");
      subtitle.className = "chat-msg__text";
      subtitle.textContent = message;
      body.appendChild(subtitle);
    }

    var form = document.createElement("div");
    form.className = "clarify-form__fields";

    fields.forEach(function (f) {
      var group = document.createElement("div");
      group.className = "clarify-field";

      var lbl = document.createElement("label");
      lbl.className = "clarify-field__label";
      lbl.textContent = f.label;
      group.appendChild(lbl);

      _renderClarifyField(group, form, f);

      var help = _renderClarifyHelp(f.help_text);
      if (help) {
        group.appendChild(help);
      }
      form.appendChild(group);
    });

    body.appendChild(form);

    var btnRow = document.createElement("div");
    btnRow.className = "clarify-form__actions";
    var submitBtn = document.createElement("button");
    submitBtn.className = "clarify-btn clarify-btn--primary";
    submitBtn.textContent = "확인 / Submit";
    submitBtn.onclick = function () {
      var collected = _collectClarifyAnswers(form, fields);
      var answers = collected.answers;
      if (collected.invalid.length) {
        appendMessage("system", "필수 항목을 먼저 입력해 주세요: " + collected.invalid.join(", "));
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "전송 중...";
      wsSend({
        type: "clarify_response",
        session_id: sessionId || App.store.sessionId,
        session_token: App.store.sessionToken,
        auth_token: App.store.authToken,
        answers: answers,
        turn_id: turnId || currentTurnId || pendingTurnId || "",
      });
    };
    btnRow.appendChild(submitBtn);
    body.appendChild(btnRow);
    wrapper.appendChild(body);

    retireInteractiveCard("confirm", "superseded");
    setActiveInteractiveCard("clarify", wrapper);
    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  function _renderConfirmCard(message, pendingPlan, sessionId, turnId) {
    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--confirm";
    if (turnId) wrapper.setAttribute("data-turn-id", turnId);

    var body = document.createElement("div");
    body.className = "chat-msg__body confirm-card";

    var msgEl = document.createElement("div");
    msgEl.className = "confirm-card__message";
    msgEl.innerHTML = (message || "").replace(/\n/g, "<br>").replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    body.appendChild(msgEl);

    var btnRow = document.createElement("div");
    btnRow.className = "confirm-card__actions";

    var computeBtn = document.createElement("button");
    computeBtn.className = "clarify-btn clarify-btn--primary";
    computeBtn.textContent = "🚀 계산하기 / Compute";
    computeBtn.onclick = function () {
      computeBtn.disabled = true;
      computeBtn.textContent = "제출 중...";
      wsSend({
        type: "confirm",
        session_id: sessionId || App.store.sessionId,
        session_token: App.store.sessionToken,
        auth_token: App.store.authToken,
        turn_id: turnId || currentTurnId || pendingTurnId || "",
      });
    };

    var editBtn = document.createElement("button");
    editBtn.className = "clarify-btn clarify-btn--secondary";
    editBtn.textContent = "✏️ 수정하기 / Edit";
    editBtn.onclick = function () {
      // Re-trigger clarification
      wsSend({
        type: "clarify_response",
        session_id: sessionId || App.store.sessionId,
        session_token: App.store.sessionToken,
        auth_token: App.store.authToken,
        answers: {},
        turn_id: turnId || currentTurnId || pendingTurnId || "",
      });
    };

    btnRow.appendChild(computeBtn);
    btnRow.appendChild(editBtn);
    body.appendChild(btnRow);
    wrapper.appendChild(body);

    retireInteractiveCard("clarify", "superseded");
    setActiveInteractiveCard("confirm", wrapper);
    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  // ─── WebSocket ──────────────────────────────────────

  function getWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var qs = new URLSearchParams();
    qs.set("session_id", safeStr(App.store.sessionId));
    qs.set("session_token", safeStr(App.store.sessionToken));
    if (safeStr(App.store.authToken)) qs.set("auth_token", safeStr(App.store.authToken));
    var url = proto + "//" + location.host + (window.__ROOT_PATH || "") + "/ws/chat?" + qs.toString();
    return url;
  }

  function connect() {
    console.log("[chat.js] connect() — ws state:",
      ws ? ["CONNECTING","OPEN","CLOSING","CLOSED"][ws.readyState] : "null",
      "reconnectCount:", reconnectCount);

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      console.log("[chat.js] connect — already connected/connecting, skipping");
      return;
    }

    var url = getWsUrl();
    console.log("[chat.js] connect — opening WebSocket:", url);

    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.error("[chat.js] ✖ WebSocket creation failed:", e);
      scheduleReconnect();
      return;
    }

    ws.onopen = function () {
      console.log("[chat.js] ✔ WebSocket OPEN");
      reconnectCount = 0;
      setWsConnected(true);
      App.setStatus("Connected", "idle", "chat");
      startPing();
      wsSend({ type: "hello", session_id: App.store.sessionId, session_token: App.store.sessionToken, auth_token: App.store.authToken });
    };

    ws.onclose = function (ev) {
      console.log("[chat.js] WebSocket CLOSED — code:", ev.code, "reason:", ev.reason, "clean:", ev.wasClean);
      setWsConnected(false);
      stopPing();
      App.setStatus("Disconnected", "idle", "chat");

      if (chatState !== STATE_IDLE) {
        console.log("[chat.js] Resetting chatState to IDLE after close");
        chatState = STATE_IDLE;
        updateSendButton();
      }
      scheduleReconnect();
    };

    ws.onerror = function (ev) {
      console.error("[chat.js] ✖ WebSocket error event:", ev);
    };

    ws.onmessage = function (ev) {
      console.log("[chat.js] 📨 WS message received, length:", ev.data ? ev.data.length : 0);
      handleMessage(ev.data);
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    if (reconnectCount >= MAX_RECONNECT) {
      console.error("[chat.js] ✖ Max reconnect attempts reached:", MAX_RECONNECT);
      appendMessage("system", "Connection lost. Please refresh the page. / 연결이 끊어졌습니다.");
      return;
    }
    var delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * Math.pow(2, reconnectCount));
    console.log("[chat.js] scheduleReconnect — attempt:", reconnectCount + 1, "delay:", delay, "ms");
    reconnectCount++;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function startPing() {
    stopPing();
    console.log("[chat.js] startPing — interval:", PING_INTERVAL_MS, "ms");
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
        var s = JSON.stringify(obj);
        console.log("[chat.js] 📤 wsSend:", obj.type, "length:", s.length);
        ws.send(s);
      } catch (e) {
        console.error("[chat.js] ✖ wsSend error:", e);
      }
    } else {
      console.warn("[chat.js] wsSend — WS not open, dropping message type:", obj.type);
    }
  }

  // ─── 메시지 핸들링 ─────────────────────────────────

  function handleMessage(raw) {
    depth++;
    if (depth > MAX_DEPTH) {
      console.warn("[chat.js] handleMessage depth exceeded:", depth, "dropping");
      depth--;
      return;
    }

    try {
      var msg;
      try {
        msg = JSON.parse(raw);
      } catch (e) {
        console.warn("[chat.js] Non-JSON message:", raw.substring(0, 100));
        depth--;
        return;
      }

      var type = safeStr(msg.type);
      console.log("[chat.js] handleMessage — type:", type, "keys:", Object.keys(msg).join(","));

      switch (type) {
        case "ready":
        case "ack":
          if (msg.session_id && msg.session_token && typeof App.setSessionAuth === "function") {
            App.setSessionAuth(msg.session_id, msg.session_token);
          }
          if (msg.auth_user && typeof App.setAuthState === "function" && safeStr(App.store.authToken)) {
            App.setAuthState(App.store.authToken, msg.auth_user);
          }
          console.log("[chat.js] ← ACK/ready, chatState:", chatState, "→ idle");
          if (chatState === STATE_AWAITING) {
            chatState = STATE_IDLE;
            updateSendButton();
          }
          break;

        case "assistant":
          if (msg.turn_id) {
            currentTurnId = safeStr(msg.turn_id);
            pendingTurnId = null;
          }
          console.log("[chat.js] ← assistant message, length:", (msg.message||"").length,
            "has plan:", !!msg.plan);
          appendMessage("assistant", safeStr(msg.message, ""), {
            plan: msg.plan || null,
            turnId: msg.turn_id,
            jobId: msg.job_id,
          });
          break;

        case "job_submitted":
          var job = msg.job || {};
          var submittedTurnId = safeStr(msg.turn_id || pendingTurnId || currentTurnId);
          console.log("[chat.js] ← job_submitted, job_id:", job.job_id, "job_type:", job.payload ? job.payload.job_type : "?");
          activeJobIdForChat = safeStr(job.job_id) || null;
          if (submittedTurnId) {
            currentTurnId = submittedTurnId;
            pendingTurnId = null;
          }
          if (submittedTurnId && activeJobIdForChat && typeof App.bindChatTurnToJob === "function") {
            App.bindChatTurnToJob(submittedTurnId, activeJobIdForChat);
          }
          _syncQuota(job.quota || msg.quota || null);
          _syncQueue(job.queue || msg.queue || null);
          App.upsertJob(job);
          App.setStatus("Computing...", "running", "chat");
          appendProgress(safeStr(job.job_id), 0.01, "submitted", "Job submitted", { queue: job.queue, status: job.status || "queued" });
          break;

        case "job_update":
          var jobId = safeStr(msg.job_id);
          console.log("[chat.js] ← job_update, jobId:", jobId, "progress:", msg.progress,
            "step:", msg.step, "msg:", msg.message);
          if (jobId) {
            _syncQuota((msg.job && msg.job.quota) || msg.quota || null);
            _syncQueue((msg.queue || (msg.job && msg.job.queue)) || null);
            appendProgress(jobId, msg.progress || 0, safeStr(msg.step), safeStr(msg.message),
              {
                scf_history: msg.scf_history,
                scf_dE: msg.scf_dE,
                scf_cycle: msg.scf_cycle,
                scf_energy: msg.scf_energy,
                queue: msg.queue || (msg.job && msg.job.queue) || null,
                status: msg.status || (msg.job && msg.job.status) || null,
              });
            if (msg.preview_result) {
              console.log("[chat.js] ← structure preview ready for job:", jobId);
              App.setActiveResult(msg.preview_result, { jobId: jobId, source: "preview" });
            }
            if (msg.job) App.upsertJob(msg.job);
          }
          break;

        case "job_event":
          console.log("[chat.js] ← job_event");
          var evt = msg.event || {};
          var evtData = evt.data || {};
          var evtJobId = safeStr(msg.job_id);
          if (evtJobId && evtData && evtData.scf_history && evtData.scf_history.length > 1) {
            appendProgress(
              evtJobId,
              evtData.progress || msg.progress || 0,
              safeStr(evtData.step, evt.type || "progress"),
              safeStr(evt.message || msg.message, "SCF update"),
              {
                scf_history: evtData.scf_history,
                scf_dE: evtData.scf_dE,
                scf_cycle: evtData.scf_cycle,
                scf_energy: evtData.scf_energy,
                queue: msg.queue || null,
                status: msg.status || null,
              }
            );
          }
          if (evtJobId && evtData && evtData.preview_result) {
            App.setActiveResult(evtData.preview_result, { jobId: evtJobId, source: "preview-event" });
          }
          break;

        case "result":
          console.log("[chat.js] ← result received");
          chatState = STATE_IDLE;
          updateSendButton();

          var result = msg.result || {};
          var job2 = msg.job || {};
          var jobId2 = safeStr(job2.job_id || msg.job_id);
          var resultTurnId = safeStr(msg.turn_id || currentTurnId || pendingTurnId);
          if (resultTurnId) {
            currentTurnId = resultTurnId;
            pendingTurnId = null;
          }
          if (jobId2) activeJobIdForChat = jobId2;
          console.log("[chat.js] result — jobId:", jobId2, "result keys:",
            Object.keys(result).join(","),
            "has visualization:", !!result.visualization);

          if (result.visualization) {
            var viz = result.visualization;
            console.log("[chat.js] result.visualization keys:", Object.keys(viz).join(","));
            console.log("[chat.js] result.visualization.available:", JSON.stringify(viz.available || {}));
            if (viz.orbital) console.log("[chat.js] viz.orbital keys:", Object.keys(viz.orbital).join(","),
              "has cube_b64:", !!viz.orbital.cube_b64);
            if (viz.esp) console.log("[chat.js] viz.esp keys:", Object.keys(viz.esp).join(","),
              "has cube_b64:", !!viz.esp.cube_b64);
            if (viz.density) console.log("[chat.js] viz.density keys:", Object.keys(viz.density).join(","),
              "has cube_b64:", !!viz.density.cube_b64);
          }

          if (jobId2 && job2) {
            _syncQuota(job2.quota || msg.quota || null);
            job2.result = result;
            App.upsertJob(job2);
          }
          if (jobId2 && result && result.scf_history && result.scf_history.length > 1) {
            appendProgress(jobId2, 1.0, "done", "Completed", {
              scf_history: result.scf_history,
              scf_dE: result.scf_final_delta_e_hartree,
              scf_cycle: result.n_scf_cycles,
              queue: job2.queue || msg.queue || null,
              status: (job2 && job2.status) || "completed",
            });
          }
          if (result) {
            App.setActiveResult(result, { jobId: jobId2, source: "chat" });
          }

          var summary = safeStr(msg.summary, "Calculation complete.");
          appendMessage("assistant", summary, { turnId: resultTurnId, jobId: jobId2 });
          retireAllInteractiveCards("completed");
          App.setStatus("Ready", "idle", "chat");
          break;

        case "error":
          chatState = STATE_IDLE;
          updateSendButton();
          var errObj = msg.error || {};
          var errMsg = safeStr(errObj.message || msg.message, "An error occurred.");
          var errTurnId = safeStr(msg.turn_id || currentTurnId || pendingTurnId);
          if (errTurnId) {
            currentTurnId = errTurnId;
            pendingTurnId = null;
          }
          var quota = msg.quota || errObj.quota || (errObj.detail && errObj.detail.quota) || null;
          console.error("[chat.js] ← error:", errMsg);
          if (/quota exceeded/i.test(errMsg) || Number(errObj.status_code || 0) === 429) {
            appendQuotaWarning(errMsg, quota);
          } else {
            appendMessage("system", "Error: " + errMsg, { turnId: errTurnId, jobId: msg.job_id });
          }
          retireAllInteractiveCards("error");
          App.setStatus("Error", "error", "chat");
          break;

        case "clarify":
          console.log("[chat.js] ← clarify, fields:", ((msg.form && msg.form.fields) || msg.fields || []).length);
          chatState = STATE_IDLE;
          updateSendButton();
          currentTurnId = safeStr(msg.turn_id || currentTurnId || pendingTurnId);
          pendingTurnId = null;
          _renderClarifyForm(msg.form || { message: msg.message, fields: msg.fields || [] }, msg.fields || [], msg.session_id, currentTurnId);
          break;

        case "confirm":
          console.log("[chat.js] ← confirm");
          chatState = STATE_IDLE;
          updateSendButton();
          currentTurnId = safeStr(msg.turn_id || currentTurnId || pendingTurnId);
          pendingTurnId = null;
          _renderConfirmCard(msg.message, msg.pending_plan, msg.session_id, currentTurnId);
          break;

        default:
          console.log("[chat.js] ← unknown message type:", type);
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
    if (!text) {
      console.log("[chat.js] sendMessage — empty text, skipping");
      return;
    }

    if (chatState !== STATE_IDLE) {
      console.warn("[chat.js] sendMessage — not idle (state:", chatState, "), ignoring");
      return;
    }

    console.log("[chat.js] 📤 sendMessage:", text.substring(0, 80), "...");
    chatState = STATE_SENDING;
    updateSendButton();
    retireAllInteractiveCards("new-turn");
    activeJobIdForChat = null;
    pendingTurnId = nextTurnId();
    currentTurnId = pendingTurnId;

    appendMessage("user", text, { turnId: currentTurnId });
    App.store.lastUserInput = text;

    wsSend({
      type: "chat", message: text,
      session_id: App.store.sessionId,
      session_token: App.store.sessionToken,
      auth_token: App.store.authToken,
      turn_id: currentTurnId,
    });

    chatInput.value = "";
    chatInput.style.height = "auto";

    chatState = STATE_AWAITING;
    updateSendButton();

    setTimeout(function () {
      if (chatState === STATE_AWAITING) {
        console.log("[chat.js] sendMessage — awaiting_ack timeout, resetting to idle");
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

  // ─── 채팅 히스토리 복원 ────────────────────────────

  function _restoreChatHistory(force) {
    if (!chatMessages || !App.getChatMessages) return;
    if (historyRestored && !force) return;
    var saved = App.getChatMessages() || [];
    console.log("[chat.js] Restoring", saved.length, "chat messages from localStorage");
    resetChatMessagesToBase();
    historyRestored = true;
    if (!saved.length) {
      scrollToBottom();
      return;
    }

    saved
      .slice()
      .sort(function (a, b) {
        return Number(a && a.timestamp || 0) - Number(b && b.timestamp || 0);
      })
      .forEach(function (msg) {
        var role = safeStr(msg && msg.role, "system");
        var text = safeStr(msg && msg.text, "");
        if (!text) return;
        appendMessage(role, text, {
          messageId: safeStr(msg && msg.id),
          jobId: safeStr(msg && msg.jobId),
          turnId: safeStr(msg && msg.turnId),
          plan: msg && msg.extra ? msg.extra.plan || null : null,
          suppressPersist: true,
        });
      });
    scrollToBottom();
    return;

    for (var i = 0; i < saved.length; i++) {
      var msg = saved[i];
      var role = safeStr(msg.role, "system");
      var text = safeStr(msg.text, "");
      if (!text) continue;

      var wrapper = document.createElement("div");
      wrapper.className = "chat-msg chat-msg--" + role;

      var avatar = document.createElement("div");
      avatar.className = "chat-msg__avatar chat-msg__avatar--" + role;
      if (role === "user") {
        avatar.textContent = "U";
      } else {
        avatar.innerHTML =
          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
          '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
      }

      var body = document.createElement("div");
      body.className = "chat-msg__body";
      var p = document.createElement("div");
      p.className = "chat-msg__text";
      if (role === "assistant" || role === "system") {
        p.innerHTML = _renderMarkdown(text);
      } else {
        p.textContent = text;
      }
      body.appendChild(p);
      wrapper.appendChild(avatar);
      wrapper.appendChild(body);
      chatMessages.appendChild(wrapper);
    }

    // Add separator
    if (saved.length > 0) {
      var sep = document.createElement("div");
      sep.className = "chat-msg chat-msg--system";
      sep.innerHTML = '<div class="chat-msg__body" style="opacity:0.5;text-align:center;font-size:0.75rem;padding:4px 8px;">── 이전 대화 ──</div>';
      chatMessages.appendChild(sep);
    }
    scrollToBottom();
  }

  // ─── 특정 Job 채팅 복원 ────────────────────────────

  function _showChatForJob(jobId) {
    if (!chatMessages || !App.getChatMessagesForJob) return;
    var msgs = App.getChatMessagesForJob(jobId);
    console.log("[chat.js] _showChatForJob —", jobId, "messages:", msgs.length);
    if (!msgs.length) return;

    clearChatSurface();

    var rebuiltHeader = document.createElement("div");
    rebuiltHeader.className = "chat-msg chat-msg--system";
    rebuiltHeader.innerHTML = '<div class="chat-msg__body" style="opacity:0.6;text-align:center;font-size:0.75rem;padding:4px 8px;">Job ' + jobId.substring(0, 8) + ' chat history</div>';
    chatMessages.appendChild(rebuiltHeader);

    msgs
      .slice()
      .sort(function (a, b) {
        return Number(a && a.timestamp || 0) - Number(b && b.timestamp || 0);
      })
      .forEach(function (msg) {
        var role = safeStr(msg && msg.role, "system");
        var text = safeStr(msg && msg.text, "");
        if (!text) return;
        appendMessage(role, text, {
          messageId: safeStr(msg && msg.id),
          jobId: safeStr(msg && msg.jobId),
          turnId: safeStr(msg && msg.turnId),
          plan: msg && msg.extra ? msg.extra.plan || null : null,
          suppressPersist: true,
        });
      });
    scrollToBottom();
    return;

    // Clear current chat
    chatMessages.innerHTML = '';

    // Show job header
    var header = document.createElement("div");
    header.className = "chat-msg chat-msg--system";
    header.innerHTML = '<div class="chat-msg__body" style="opacity:0.6;text-align:center;font-size:0.75rem;padding:4px 8px;">── Job: ' + jobId.substring(0, 8) + '... 대화 기록 ──</div>';
    chatMessages.appendChild(header);

    // Render messages
    for (var i = 0; i < msgs.length; i++) {
      var msg = msgs[i];
      var role = safeStr(msg.role, "system");
      var text = safeStr(msg.text, "");
      if (!text) continue;

      var wrapper = document.createElement("div");
      wrapper.className = "chat-msg chat-msg--" + role;

      var avatar = document.createElement("div");
      avatar.className = "chat-msg__avatar chat-msg__avatar--" + role;
      if (role === "user") {
        avatar.textContent = "U";
      } else {
        avatar.innerHTML =
          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
          '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
      }

      var body = document.createElement("div");
      body.className = "chat-msg__body";
      var p = document.createElement("div");
      p.className = "chat-msg__text";
      if (role === "assistant" || role === "system") {
        p.innerHTML = _renderMarkdown(text);
      } else {
        p.textContent = text;
      }
      body.appendChild(p);
      wrapper.appendChild(avatar);
      wrapper.appendChild(body);
      chatMessages.appendChild(wrapper);
    }
    scrollToBottom();
  }

  // ─── 이벤트 바인딩 ─────────────────────────────────

  function init() {
    console.log("[chat.js] init() — starting initialization");
    initWsStatus();
    ensureAriaLive();

    historyRestored = false;

    if (chatForm) {
      chatForm.addEventListener("submit", function (e) {
        e.preventDefault();
        console.log("[chat.js] 🎛 Form submit event");
        sendMessage();
      });
    }

    if (chatInput) {
      chatInput.addEventListener("input", function () {
        updateSendButton();
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 200) + "px";
      });

      chatInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          console.log("[chat.js] 🎛 Enter key pressed (no shift)");
          sendMessage();
        }
      });
    }

    var suggestions = document.getElementById("chatSuggestions");
    if (suggestions) {
      suggestions.addEventListener("click", function (e) {
        var chip = e.target.closest(".suggestion-chip");
        if (!chip) return;
        var prompt = chip.getAttribute("data-prompt");
        console.log("[chat.js] 🎛 Suggestion chip clicked:", prompt);
        if (prompt && chatInput) {
          chatInput.value = prompt;
          updateSendButton();
          sendMessage();
        }
      });
    }

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "/") {
        e.preventDefault();
        console.log("[chat.js] 🎛 Ctrl+/ → focus chat");
        if (chatInput) chatInput.focus();
      }
    });

    console.log("[chat.js] init — bootstrapping session then connecting WebSocket");
    Promise.resolve(typeof App.ensureSession === "function" ? App.ensureSession() : null)
      .then(function () {
        _restoreChatHistory(true);
        connect();
      })
      .catch(function (err) {
        console.error("[chat.js] ✖ session bootstrap/connect failed:", err);
        appendMessage("system", "세션 초기화에 실패했습니다. 새로고침 후 다시 시도해 주세요.");
      });

    // Listen for history card clicks to restore per-job chat
    App.on("activejob:changed", function (detail) {
      if (detail && detail.jobId) {
        console.log("[chat.js] 📡 activejob:changed — switching chat to job:", detail.jobId);
        activeJobIdForChat = detail.jobId;
        _showChatForJob(detail.jobId);
      }
    });

    App.on("session:changed", function (detail) {
      var changed = !!(detail && detail.changed);
      if (changed) {
        historyRestored = false;
        pendingTurnId = null;
        currentTurnId = null;
        activeJobIdForChat = null;
        resetChatMessagesToBase();
      }
      if (!historyRestored || changed) {
        _restoreChatHistory(true);
      }
    });

    App.on("auth:changed", function () {
      console.log("[chat.js] 📡 auth:changed — reconnecting WebSocket");
      stopPing();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1000, "auth_changed");
      } else {
        connect();
      }
    });

    console.log("[chat.js] ✔ init() complete");
  }

  // ─── 공개 API ──────────────────────────────────────
  App.chat = {
    connect: connect,
    sendMessage: sendMessage,
    appendMessage: appendMessage,
    getState: function () { return chatState; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  console.log("[chat.js] ✔ Module loaded");
})(window);
