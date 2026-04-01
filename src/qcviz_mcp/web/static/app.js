/**
 * QCViz-MCP v3 — App Shell Controller
 * FIX(M10): newest-first history, rAF batch rendering,
 *           localStorage 2s throttle, 키보드 접근성, 이벤트 루프 방지
 */
(function (g) {
  "use strict";
  console.log("[app.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[app.js] ✖ QCVizApp not found — aborting app module");
    return;
  }
  console.log("[app.js] ✔ QCVizApp found, theme:", App.store.theme);

  // ─── 상수 ──────────────────────────────────────────
  var LS_THROTTLE_MS = 2000;

  // ─── DOM refs ──────────────────────────────────────
  var globalStatus = document.getElementById("globalStatus");
  var statusDot = globalStatus ? globalStatus.querySelector(".status-indicator__dot") : null;
  var statusText = globalStatus ? globalStatus.querySelector(".status-indicator__text") : null;
  var historyList = document.getElementById("historyList");
  var historyEmpty = document.getElementById("historyEmpty");
  var historySearch = document.getElementById("historySearch");
  var btnRefreshHistory = document.getElementById("btnRefreshHistory");
  var btnNewSession = document.getElementById("btnNewSession");
  var btnThemeToggle = document.getElementById("btnThemeToggle");
  var btnAuthOpen = document.getElementById("btnAuthOpen");
  var quotaChip = document.getElementById("quotaChip");
  var quotaStatusText = document.getElementById("quotaStatusText");
  var quotaMetaText = document.getElementById("quotaMetaText");
  var btnAdminOpen = document.getElementById("btnAdminOpen");
  var btnKeyboardShortcuts = document.getElementById("btnKeyboardShortcuts");
  var modalShortcuts = document.getElementById("modalShortcuts");
  var modalAuth = document.getElementById("modalAuth");
  var modalAdmin = document.getElementById("modalAdmin");
  var authStatusText = document.getElementById("authStatusText");
  var authModalTitle = document.getElementById("authModalTitle");
  var btnAuthModeLogin = document.getElementById("btnAuthModeLogin");
  var btnAuthModeRegister = document.getElementById("btnAuthModeRegister");
  var authForm = document.getElementById("authForm");
  var authUsername = document.getElementById("authUsername");
  var authDisplayName = document.getElementById("authDisplayName");
  var authDisplayNameField = document.getElementById("authDisplayNameField");
  var authPassword = document.getElementById("authPassword");
  var btnAuthSubmit = document.getElementById("btnAuthSubmit");
  var btnAuthLogout = document.getElementById("btnAuthLogout");
  var authStatusMessage = document.getElementById("authStatusMessage");
  var adminOverviewStamp = document.getElementById("adminOverviewStamp");
  var adminOverviewStats = document.getElementById("adminOverviewStats");
  var adminUsersMeta = document.getElementById("adminUsersMeta");
  var adminUsersTable = document.getElementById("adminUsersTable");
  var adminWorkersMeta = document.getElementById("adminWorkersMeta");
  var adminWorkersTable = document.getElementById("adminWorkersTable");
  var adminRecoveryMeta = document.getElementById("adminRecoveryMeta");
  var adminRecoveryTable = document.getElementById("adminRecoveryTable");
  var adminSessionsMeta = document.getElementById("adminSessionsMeta");
  var adminSessionsTable = document.getElementById("adminSessionsTable");
  var adminActiveJobsMeta = document.getElementById("adminActiveJobsMeta");
  var adminActiveJobsTable = document.getElementById("adminActiveJobsTable");
  var adminRecentJobsMeta = document.getElementById("adminRecentJobsMeta");
  var adminRecentJobsTable = document.getElementById("adminRecentJobsTable");
  var appLoader = document.getElementById("appLoader");
  var mobilePanelNav = document.getElementById("mobilePanelNav");

  console.log("[app.js] DOM refs:", {
    globalStatus: !!globalStatus, historyList: !!historyList,
    historySearch: !!historySearch, btnRefreshHistory: !!btnRefreshHistory,
    btnNewSession: !!btnNewSession,
    btnThemeToggle: !!btnThemeToggle, btnAuthOpen: !!btnAuthOpen,
    quotaChip: !!quotaChip, btnAdminOpen: !!btnAdminOpen,
    modalShortcuts: !!modalShortcuts, modalAuth: !!modalAuth, modalAdmin: !!modalAdmin,
    appLoader: !!appLoader, mobilePanelNav: !!mobilePanelNav,
  });

  // ─── 상태 ──────────────────────────────────────────
  var dirtyHistory = false;
  var rafPending = false;
  var lastLsSave = 0;
  var lsTimer = null;
  var eventLoopGuard = false;
  var authMode = "login";
  var adminRefreshTimer = null;

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) { return v == null ? fb || "" : String(v).trim(); }

  function ellipsize(v, maxLen) {
    var text = safeStr(v);
    var cap = Math.max(4, Number(maxLen || 0));
    if (!text || text.length <= cap) return text;
    return text.slice(0, Math.max(1, cap - 1)) + "…";
  }

  function formatTime(ts) {
    if (!ts) return "—";
    try { var d = new Date(ts * 1000); return d.toLocaleTimeString(); }
    catch (_) { return "—"; }
  }

  function formatCompactTime(ts) {
    if (!ts) return "—";
    try {
      var d = new Date(Number(ts) * 1000);
      return d.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return "—";
    }
  }

  function formatDuration(seconds) {
    var value = Number(seconds || 0);
    if (!isFinite(value) || value <= 0) return "0s";
    if (value < 60) return Math.round(value) + "s";
    if (value < 3600) return Math.round(value / 60) + "m";
    return (value / 3600).toFixed(value >= 7200 ? 0 : 1) + "h";
  }

  function show(el) { if (el) el.removeAttribute("hidden"); }
  function hide(el) { if (el) el.setAttribute("hidden", ""); }
  function clearJobsState() {
    App.store.jobsById = {};
    App.store.jobOrder = [];
    App.store.resultsByJobId = {};
    App.store.activeJobId = null;
    App.store.activeResult = null;
  }

  function stopAdminAutoRefresh() {
    if (adminRefreshTimer) {
      clearInterval(adminRefreshTimer);
      adminRefreshTimer = null;
    }
  }

  function syncViewportHeight() {
    var viewport = g.visualViewport;
    var raw = viewport && viewport.height ? viewport.height : g.innerHeight;
    var next = Math.max(360, Math.round(raw || 0));
    document.documentElement.style.setProperty("--app-height", next + "px");
  }

  function setActiveMobilePanel(panelId) {
    if (!mobilePanelNav) return;
    mobilePanelNav.querySelectorAll("[data-panel-target]").forEach(function (btn) {
      var active = btn.getAttribute("data-panel-target") === panelId;
      btn.classList.toggle("mobile-panel-nav__btn--active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function setupMobilePanelNav() {
    if (!mobilePanelNav) return;
    var buttons = mobilePanelNav.querySelectorAll("[data-panel-target]");
    if (!buttons.length) return;

    buttons.forEach(function (btn, idx) {
      if (idx === 0) setActiveMobilePanel(btn.getAttribute("data-panel-target"));
      btn.addEventListener("click", function () {
        var targetId = this.getAttribute("data-panel-target");
        var target = targetId ? document.getElementById(targetId) : null;
        if (!target) return;
        setActiveMobilePanel(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    if (!("IntersectionObserver" in g)) return;
    var observer = new IntersectionObserver(
      function (entries) {
        var best = null;
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          if (!best || entry.intersectionRatio > best.intersectionRatio) best = entry;
        });
        if (best && best.target && best.target.id) {
          setActiveMobilePanel(best.target.id);
        }
      },
      {
        root: null,
        threshold: [0.2, 0.45, 0.7],
        rootMargin: "-20% 0px -45% 0px",
      }
    );

    ["panelViewer", "panelChat", "panelResults", "panelHistory"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  }

  // ─── 상태 표시 ────────────────────────────────────

  function updateStatus(detail) {
    if (!detail) return;
    console.log("[app.js] updateStatus — kind:", detail.kind, "text:", detail.text);
    if (statusDot) statusDot.setAttribute("data-kind", safeStr(detail.kind, "idle"));
    if (statusText) statusText.textContent = safeStr(detail.text, "Ready");
  }

  function renderQuotaState() {
    if (!quotaChip || !quotaStatusText) return;
    var quota = App.store.quota || null;
    var queue = App.store.queue || null;
    var user = App.store.authUser || null;
    var signedIn = !!(user && user.username);
    var count = signedIn && quota && quota.user_limited
      ? Number(quota.active_for_owner || 0)
      : Number((quota && quota.active_for_session) || 0);
    var limit = signedIn && quota && quota.user_limited
      ? Number(quota.max_active_per_user || 0)
      : Number((quota && quota.max_active_per_session) || 0);
    var label = signedIn ? "My Jobs" : "Session";
    var atLimit = !!quota && limit > 0 && count >= limit;
    var title = quota
      ? (
          label + " active jobs " + count + "/" + limit +
          " · session " + Number(quota.active_for_session || 0) + "/" + Number(quota.max_active_per_session || 0) +
          (signedIn && quota.user_limited
            ? " · user " + Number(quota.active_for_owner || 0) + "/" + Number(quota.max_active_per_user || 0)
            : "")
        )
      : "Active job quota";
    quotaChip.classList.toggle("quota-chip--warning", atLimit);
    quotaChip.classList.toggle("quota-chip--healthy", !!quota && !atLimit);
    quotaChip.setAttribute("title", title);
    quotaChip.setAttribute("aria-label", title);
    var labelEl = quotaChip.querySelector(".quota-chip__label");
    if (labelEl) labelEl.textContent = label;
    quotaStatusText.textContent = quota ? (count + "/" + Math.max(0, limit)) : "—/—";
    if (quotaMetaText) {
      var queuedCount = Number((queue && queue.queued_count) || 0);
      var eta = Number((queue && queue.estimated_queue_drain_seconds) || 0);
      quotaMetaText.textContent = queuedCount > 0
        ? ("queue " + queuedCount + " · ETA " + formatDuration(eta))
        : "queue 0";
    }
  }

  function adminFetch(path) {
    return authFetch(path).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  function adminAction(path, payload) {
    return authFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  function renderAdminRows(target, htmlRows, colspan, emptyMessage) {
    if (!target) return;
    if (!htmlRows.length) {
      target.innerHTML = '<tr><td class="admin-table__empty" colspan="' + String(colspan || 1) + '">' +
        escapeHtmlSafe(emptyMessage || "No data") + "</td></tr>";
      return;
    }
    target.innerHTML = htmlRows.join("");
  }

  function renderAdminOverview(data) {
    var overview = (data && data.overview) || {};
    var counts = overview.counts || {};
    var queue = overview.queue || {};
    var quota = overview.quota_config || {};

    if (adminOverviewStamp) {
      adminOverviewStamp.textContent =
        "Updated " + formatCompactTime(overview.generated_at) +
        " · " + Number(queue.running_count || 0) + "/" + Math.max(1, Number(queue.max_workers || 1)) +
        " workers busy · " + Number(queue.queued_count || 0) + " queued";
    }

    if (adminOverviewStats) {
      var statCards = [
        { label: "Active Queue", value: Number(queue.active_count || 0), meta: Number(queue.queued_count || 0) + " queued · ETA " + formatDuration(queue.estimated_queue_drain_seconds || 0) },
        { label: "Registered Users", value: Number(counts.registered_users || 0), meta: Number(counts.sessions_seen || 0) + " sessions tracked" },
        { label: "Completed Jobs", value: Number(((counts.status || {}).completed) || 0), meta: Number(counts.total_jobs || 0) + " total jobs" },
        { label: "Quota", value: Number(quota.max_active_per_session || 0) + "/" + Number(quota.max_active_per_user || 0), meta: "session/user" },
        { label: "Workers", value: Number(counts.workers_seen || 0), meta: Number(counts.stale_workers || 0) + " stale" },
        { label: "Recovered", value: Number(counts.recovered_jobs || 0), meta: "stale jobs auto-failed" },
      ];
      adminOverviewStats.innerHTML = statCards.map(function (card) {
        return (
          '<article class="admin-stat-card">' +
          '<span class="admin-stat-card__label">' + escapeHtmlSafe(card.label) + "</span>" +
          '<strong class="admin-stat-card__value">' + escapeHtmlSafe(String(card.value)) + "</strong>" +
          '<span class="admin-stat-card__meta">' + escapeHtmlSafe(card.meta) + "</span>" +
          "</article>"
        );
      }).join("");
    }

    if (adminUsersMeta) adminUsersMeta.textContent = String((overview.users || []).length) + " users";
    renderAdminRows(
      adminUsersTable,
      (overview.users || []).slice(0, 20).map(function (user) {
        var quotaText = Number(user.active_jobs || 0) + " active";
        return (
          "<tr>" +
          "<td><strong>" + escapeHtmlSafe(ellipsize(user.display_name || user.username, 18)) + "</strong><div class=\"admin-table__sub\">" + escapeHtmlSafe(user.username) + "</div></td>" +
          "<td>" + escapeHtmlSafe(safeStr(user.role, "user")) + "</td>" +
          "<td>" + escapeHtmlSafe(String(Number(user.active_jobs || 0))) + "<div class=\"admin-table__sub\">" + escapeHtmlSafe(quotaText) + "</div></td>" +
          "<td>" + escapeHtmlSafe(String(Number(user.total_jobs || 0))) + "</td>" +
          "<td>" + escapeHtmlSafe(String(Number(user.active_tokens || 0))) + "</td>" +
          "</tr>"
        );
      }),
      5,
      "No registered users"
    );

    if (adminWorkersMeta) adminWorkersMeta.textContent = String((overview.workers || []).length) + " workers";
    renderAdminRows(
      adminWorkersTable,
      (overview.workers || []).slice(0, 20).map(function (worker) {
        return (
          "<tr>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(worker.worker_id || "worker", 18)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(safeStr(worker.status, "unknown")) + (worker.is_stale ? '<div class="admin-table__sub">stale</div>' : "") + "</td>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(worker.job_id || "—", 14)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(formatDuration(worker.age_seconds || 0)) + "</td>" +
          "<td>" + escapeHtmlSafe(formatCompactTime(worker.timestamp)) + "</td>" +
          "</tr>"
        );
      }),
      5,
      "No worker heartbeat seen"
    );

    if (adminRecoveryMeta) adminRecoveryMeta.textContent = String(Number((overview.recovery || {}).recovered_count || 0)) + " recovered";
    renderAdminRows(
      adminRecoveryTable,
      ((overview.recovery || {}).recovered_jobs || []).slice(0, 20).map(function (item) {
        return (
          "<tr>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(item.job_id || "job", 14)) + "</code></td>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(item.worker_id || "—", 14)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(formatDuration(item.stale_for_seconds || 0)) + "</td>" +
          "<td>" + escapeHtmlSafe(safeStr(item.reason, "stale worker heartbeat")) + "</td>" +
          "</tr>"
        );
      }),
      4,
      "No stale job recoveries yet"
    );

    if (adminSessionsMeta) adminSessionsMeta.textContent = String((overview.sessions || []).length) + " sessions";
    renderAdminRows(
      adminSessionsTable,
      (overview.sessions || []).slice(0, 20).map(function (session) {
        return (
          "<tr>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(session.session_id, 18)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(ellipsize(session.owner_display_name || session.owner_username || "anonymous", 16)) + "</td>" +
          "<td>" + escapeHtmlSafe(String(Number(session.active_jobs || 0))) + "</td>" +
          "<td>" + escapeHtmlSafe(String(Number(session.total_jobs || 0))) + "</td>" +
          "<td>" + escapeHtmlSafe(formatCompactTime(session.last_job_at)) + "</td>" +
          "</tr>"
        );
      }),
      5,
      "No tracked sessions"
    );

    if (adminActiveJobsMeta) adminActiveJobsMeta.textContent = String((overview.active_jobs || []).length) + " active";
    renderAdminRows(
      adminActiveJobsTable,
      (overview.active_jobs || []).slice(0, 20).map(function (job) {
        var eta = job.queue && job.queue.estimated_finish_in_seconds
          ? "ETA " + formatDuration(job.queue.estimated_finish_in_seconds)
          : "—";
        return (
          "<tr>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(job.job_id, 12)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(safeStr(job.status, "unknown")) + "<div class=\"admin-table__sub\">" + escapeHtmlSafe(eta) + "</div></td>" +
          "<td>" + escapeHtmlSafe(ellipsize(job.owner_display_name || job.owner_username || "anonymous", 16)) + "</td>" +
          "<td>" + escapeHtmlSafe(ellipsize(job.molecule_name || job.user_query || "—", 18)) + "</td>" +
          "<td>" + escapeHtmlSafe(ellipsize(job.method || "—", 12)) + "</td>" +
          '<td><button class="chip-btn chip-btn--admin admin-action-btn" data-admin-action="cancel" data-job-id="' + escapeHtmlSafe(job.job_id) + '" type="button">Cancel</button></td>' +
          "</tr>"
        );
      }),
      6,
      "No active jobs"
    );

    if (adminRecentJobsMeta) adminRecentJobsMeta.textContent = String((overview.recent_jobs || []).length) + " recent";
    renderAdminRows(
      adminRecentJobsTable,
      (overview.recent_jobs || []).slice(0, 20).map(function (job) {
        var canRequeue = ["failed", "cancelled", "completed", "error"].indexOf(safeStr(job.status).toLowerCase()) >= 0;
        return (
          "<tr>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(job.job_id, 12)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(safeStr(job.status, "unknown")) + "</td>" +
          "<td>" + escapeHtmlSafe(ellipsize(job.owner_display_name || job.owner_username || "anonymous", 16)) + "</td>" +
          "<td><code>" + escapeHtmlSafe(ellipsize(job.session_id || "—", 14)) + "</code></td>" +
          "<td>" + escapeHtmlSafe(formatCompactTime(job.updated_at || job.created_at)) + "</td>" +
          '<td><button class="chip-btn chip-btn--admin admin-action-btn" data-admin-action="requeue" data-job-id="' + escapeHtmlSafe(job.job_id) + '" type="button"' + (canRequeue ? "" : " disabled") + '>Requeue</button></td>' +
          "</tr>"
        );
      }),
      6,
      "No recent jobs"
    );
  }

  function fetchAdminOverview() {
    var user = App.store.authUser || null;
    if (!(user && safeStr(user.role).toLowerCase() === "admin")) {
      return Promise.resolve(null);
    }
    if (adminOverviewStamp) adminOverviewStamp.textContent = "Loading admin overview...";
    return adminFetch("/admin/overview")
      .then(function (res) {
        if (!res.ok) throw new Error(safeStr(res.data && res.data.detail, "Failed to load admin overview."));
        renderAdminOverview(res.data);
        return res.data;
      })
      .catch(function (err) {
        if (adminOverviewStamp) adminOverviewStamp.textContent = safeStr(err && err.message, "Failed to load admin overview.");
        return null;
      });
  }

  function openAdminDashboard() {
    if (!modalAdmin) return;
    openModal(modalAdmin);
    fetchAdminOverview();
    stopAdminAutoRefresh();
    adminRefreshTimer = setInterval(fetchAdminOverview, 5000);
  }

  function handleAdminActionClick(ev) {
    var target = ev.target;
    if (!target || !target.closest) return;
    var btn = target.closest(".admin-action-btn");
    if (!btn) return;
    var action = safeStr(btn.getAttribute("data-admin-action"));
    var jobId = safeStr(btn.getAttribute("data-job-id"));
    if (!action || !jobId) return;
    btn.disabled = true;
    if (adminOverviewStamp) adminOverviewStamp.textContent = (action === "cancel" ? "Cancelling " : "Requeueing ") + jobId + "...";
    var promise = action === "cancel"
      ? adminAction("/admin/jobs/" + encodeURIComponent(jobId) + "/cancel", {})
      : adminAction("/admin/jobs/" + encodeURIComponent(jobId) + "/requeue", { force: true, reason: "admin_dashboard" });
    promise
      .then(function (res) {
        if (!res.ok) throw new Error(safeStr(res.data && res.data.detail, "Admin action failed."));
        if (typeof App.refreshHistory === "function") App.refreshHistory();
        return fetchAdminOverview();
      })
      .catch(function (err) {
        if (adminOverviewStamp) adminOverviewStamp.textContent = safeStr(err && err.message, "Admin action failed.");
      })
      .finally(function () {
        btn.disabled = false;
      });
  }

  // ─── 히스토리 렌더링 ──────────────────────────────

  function renderHistory(filter) {
    if (!historyList) return;

    var jobs = App.store.jobOrder
      .map(function (id) { return App.store.jobsById[id]; })
      .filter(function (j) { return !!j; });

    jobs.sort(function (a, b) { return (b.created_at || 0) - (a.created_at || 0); });

    if (filter) {
      var lf = filter.toLowerCase();
      jobs = jobs.filter(function (j) {
        var name = safeStr(j.molecule_name || j.user_query || "").toLowerCase();
        var jtype = safeStr(j.job_type || "").toLowerCase();
        var status = safeStr(j.status || "").toLowerCase();
        return name.indexOf(lf) >= 0 || jtype.indexOf(lf) >= 0 || status.indexOf(lf) >= 0;
      });
    }

    console.log("[app.js] renderHistory — total jobs:", jobs.length, "filter:", filter || "(none)");

    if (jobs.length === 0) {
      historyList.innerHTML = "";
      show(historyEmpty);
      return;
    }

    hide(historyEmpty);
    var fragment = document.createDocumentFragment();

    jobs.forEach(function (job) {
      var card = document.createElement("div");
      card.className = "history-card";
      card.setAttribute("data-job-id", safeStr(job.job_id));
      card.setAttribute("data-job-type", safeStr(job.job_type || ""));
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-label",
        safeStr(job.molecule_name || job.user_query || job.job_type || "Job"));

      var statusClass = "history-card__status--" + safeStr(job.status, "queued");

      card.innerHTML =
        '<div class="history-card__header">' +
        '<span class="history-card__name">' +
        escapeHtmlSafe(safeStr(job.molecule_name || job.user_query || "Unnamed")) +
        "</span>" +
        '<span class="history-card__status ' + statusClass + '">' +
        safeStr(job.status, "queued") + "</span></div>" +
        '<div class="history-card__meta">' +
        "<span>" + escapeHtmlSafe(safeStr(job.job_type || "")) + "</span>" +
        '<span class="history-card__method">' + escapeHtmlSafe(safeStr(job.method || "")) + "</span>" +
        '<span class="history-card__basis">' + escapeHtmlSafe(safeStr(job.basis_set || job.basis || "")) + "</span>" +
        "<span>" + formatTime(job.created_at) + "</span></div>";

      card.addEventListener("click", function () {
        console.log("[app.js] 🎛 History card clicked — jobId:", job.job_id);
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
    console.log("[app.js] handleHistoryClick — jobId:", jobId);
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
      if (typeof App.persistUISnapshots === "function") {
        App.persistUISnapshots();
      }
      console.log("[app.js] throttledSaveSnapshots — saved to localStorage");
    } catch (_) {}
  }

  // ─── 테마 토글 ────────────────────────────────────

  function toggleTheme() {
    var next = App.store.theme === "dark" ? "light" : "dark";
    console.log("[app.js] 🎛 toggleTheme:", App.store.theme, "→", next);
    App.setTheme(next);
  }

  // ─── 모달 ──────────────────────────────────────────

  function openModal(modal) {
    console.log("[app.js] openModal");
    if (modal && typeof modal.showModal === "function") modal.showModal();
  }
  function closeModal(modal) {
    console.log("[app.js] closeModal");
    if (modal && typeof modal.close === "function") modal.close();
  }

  // ─── 서버 히스토리 로드 ───────────────────────────

  function fetchHistory() {
    var isAuthed = !!safeStr(App.store.authToken);
    var url = App.apiPrefix + "/compute/jobs?include_result=true";
    if (!isAuthed) {
      url += "&session_id=" + encodeURIComponent(safeStr(App.store.sessionId));
    }
    console.log("[app.js] fetchHistory — url:", url);
    return Promise.resolve(typeof App.ensureSession === "function" ? App.ensureSession() : null)
      .then(function () {
        return fetch(url, {
          headers: Object.assign(
            {},
            typeof App.getSessionHeaders === "function" ? App.getSessionHeaders() : {},
            typeof App.getAuthHeaders === "function" ? App.getAuthHeaders() : {}
          ),
        });
      })
      .then(function (r) {
        console.log("[app.js] fetchHistory — response status:", r.status);
        return r.json();
      })
      .then(function (data) {
        var items = data.items || data || [];
        if (typeof App.setQuota === "function") App.setQuota(data.quota || null);
        if (typeof App.setQueue === "function") App.setQueue(data.queue || null);
        console.log("[app.js] fetchHistory — loaded", items.length, "jobs from server");
        items.forEach(function (job) { App.upsertJob(job); });
        scheduleHistoryRender();
      })
      .catch(function (e) {
        console.warn("[app.js] ✖ fetchHistory failed:", e);
      });
  }

  function startNewSession() {
    var oldSessionId = safeStr(App.store.sessionId);
    var oldSessionToken = safeStr(App.store.sessionToken);
    var newSessionId = "qcviz-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);

    clearJobsState();
    if (typeof App.clearChatMessages === "function") {
      App.clearChatMessages();
    } else {
      App.store.chatMessages = [];
      App.store.chatMessagesByJobId = {};
    }

    function removeScopedKeys(storage) {
      if (!storage || !oldSessionId) return;
      try { storage.removeItem("QCVIZ_V3_UI_SNAPSHOTS_" + oldSessionId); } catch (_) {}
      try { storage.removeItem("QCVIZ_CHAT_" + oldSessionId); } catch (_) {}
    }

    removeScopedKeys(g.sessionStorage);
    removeScopedKeys(g.localStorage);
    scheduleHistoryRender();

    App.setSessionAuth(newSessionId, "");
    App.setStatus("Starting new session", "idle", "app");

    if (oldSessionId) {
      fetch(App.apiPrefix + "/session/clear_state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          previous_session_id: oldSessionId,
          previous_session_token: oldSessionToken,
        }),
      }).catch(function (err) {
        console.warn("[app.js] startNewSession — backend clear failed:", err);
      });
    }

    return Promise.resolve(typeof App.ensureSession === "function" ? App.ensureSession() : null)
      .then(function () {
        return fetchHistory();
      })
      .catch(function (err) {
        console.warn("[app.js] startNewSession — bootstrap failed:", err);
      });
  }

  function setAuthStatusMessage(text, isError) {
    if (!authStatusMessage) return;
    authStatusMessage.textContent = safeStr(text);
    authStatusMessage.style.color = isError ? "var(--error)" : "var(--text-secondary)";
  }

  function setAuthMode(mode) {
    authMode = mode === "register" ? "register" : "login";
    var isRegister = authMode === "register";
    if (btnAuthModeLogin) btnAuthModeLogin.classList.toggle("active", !isRegister);
    if (btnAuthModeRegister) btnAuthModeRegister.classList.toggle("active", isRegister);
    if (authModalTitle) authModalTitle.textContent = isRegister ? "Register" : "Sign In";
    if (authDisplayNameField) authDisplayNameField.hidden = !isRegister;
    if (btnAuthSubmit) btnAuthSubmit.textContent = isRegister ? "Register" : "Sign In";
    if (authPassword) authPassword.setAttribute("autocomplete", isRegister ? "new-password" : "current-password");
    setAuthStatusMessage("", false);
  }

  function renderAuthState() {
    var user = App.store.authUser;
    var signedIn = !!(user && user.username);
    if (authStatusText) {
      authStatusText.textContent = signedIn
        ? safeStr(user.display_name || user.username, "Signed In")
        : "Guest";
    }
    if (btnAuthLogout) btnAuthLogout.hidden = !signedIn;
    if (btnAuthSubmit) btnAuthSubmit.hidden = signedIn;
    if (authUsername) authUsername.value = signedIn ? safeStr(user.username) : safeStr(authUsername.value);
    if (authDisplayName) authDisplayName.value = signedIn ? safeStr(user.display_name || user.username) : safeStr(authDisplayName.value);
    if (authUsername) authUsername.disabled = signedIn;
    if (authDisplayName) authDisplayName.disabled = signedIn;
    if (authPassword) authPassword.disabled = signedIn;
    if (btnAuthModeLogin) btnAuthModeLogin.disabled = signedIn;
    if (btnAuthModeRegister) btnAuthModeRegister.disabled = signedIn;
    if (signedIn) {
      show(authDisplayNameField);
      setAuthStatusMessage("Signed in as " + safeStr(user.display_name || user.username), false);
    } else {
      setAuthMode(authMode);
    }
    if (btnAdminOpen) btnAdminOpen.hidden = !(signedIn && safeStr(user.role).toLowerCase() === "admin");
    renderQuotaState();
  }

  function authFetch(path, options) {
    options = options || {};
    options.headers = Object.assign(
      {},
      options.headers || {},
      typeof App.getAuthHeaders === "function" ? App.getAuthHeaders() : {}
    );
    return fetch(App.apiPrefix + path, options);
  }

  function refreshHistoryForIdentityChange() {
    clearJobsState();
    if (typeof App.clearQuota === "function") App.clearQuota();
    if (typeof App.clearQueue === "function") App.clearQueue();
    scheduleHistoryRender();
    fetchHistory();
  }

  function handleAuthSubmit(ev) {
    if (ev) ev.preventDefault();
    if (!authForm || !btnAuthSubmit) return;
    var payload = {
      username: safeStr(authUsername && authUsername.value),
      password: safeStr(authPassword && authPassword.value),
    };
    if (authMode === "register") {
      payload.display_name = safeStr(authDisplayName && authDisplayName.value);
    }
    btnAuthSubmit.disabled = true;
    setAuthStatusMessage(authMode === "register" ? "Creating account..." : "Signing in...", false);
    authFetch(authMode === "register" ? "/auth/register" : "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (resp) { return resp.json().then(function (data) { return { ok: resp.ok, data: data }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(safeStr(res.data && res.data.detail, "Authentication failed."));
        App.setAuthState(res.data.auth_token, res.data.user);
        renderAuthState();
        refreshHistoryForIdentityChange();
        if (modalAuth) closeModal(modalAuth);
      })
      .catch(function (err) {
        setAuthStatusMessage(safeStr(err && err.message, "Authentication failed."), true);
      })
      .finally(function () {
        btnAuthSubmit.disabled = false;
      });
  }

  function handleLogout() {
    if (btnAuthLogout) btnAuthLogout.disabled = true;
    authFetch("/auth/logout", { method: "POST" })
      .finally(function () {
        App.clearAuthState();
        if (authUsername) authUsername.value = "";
        if (authDisplayName) authDisplayName.value = "";
        if (authPassword) authPassword.value = "";
        renderAuthState();
        refreshHistoryForIdentityChange();
        if (btnAuthLogout) btnAuthLogout.disabled = false;
      });
  }

  function verifyStoredAuth() {
    if (!App.store.authToken) {
      renderAuthState();
      return Promise.resolve(null);
    }
    return authFetch("/auth/me")
      .then(function (resp) { return resp.json().then(function (data) { return { ok: resp.ok, data: data }; }); })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.authenticated) {
          App.clearAuthState();
          renderAuthState();
          return null;
        }
        App.setAuthState(App.store.authToken, res.data.user);
        renderAuthState();
        return res.data.user;
      })
      .catch(function () {
        App.clearAuthState();
        renderAuthState();
        return null;
      });
  }

  // ─── 키보드 단축키 ────────────────────────────────

  function setupKeyboard() {
    console.log("[app.js] setupKeyboard — binding shortcuts");
    document.addEventListener("keydown", function (e) {
      var tag = (document.activeElement || {}).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") document.activeElement.blur();
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
        e.preventDefault();
        console.log("[app.js] 🎛 Ctrl+\\ → toggle theme");
        toggleTheme();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        console.log("[app.js] 🎛 Ctrl+K → focus history search");
        if (historySearch) historySearch.focus();
      }
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        console.log("[app.js] 🎛 ? → open shortcuts modal");
        openModal(modalShortcuts);
      }
      if (e.key === "Escape") {
        closeModal(modalShortcuts);
      }
    });
  }

  // ─── 초기화 ────────────────────────────────────────

  function init() {
    console.log("[app.js] init() — starting initialization");

    App.on("status:changed", function (detail) {
      if (eventLoopGuard) return;
      eventLoopGuard = true;
      console.log("[app.js] 📡 Event status:changed — kind:", detail.kind, "text:", detail.text);
      updateStatus(detail);
      eventLoopGuard = false;
    });

    App.on("jobs:changed", function (detail) {
      console.log("[app.js] 📡 Event jobs:changed — jobId:", detail && detail.job ? detail.job.job_id : "?");
      if (detail && detail.job && detail.job.quota && typeof App.setQuota === "function") {
        App.setQuota(detail.job.quota);
      }
      scheduleHistoryRender();
      throttledSaveSnapshots();
    });

    App.on("quota:changed", function () {
      renderQuotaState();
    });

    App.on("queue:changed", function () {
      renderQuotaState();
    });

    if (btnNewSession) {
      btnNewSession.addEventListener("click", function () {
        startNewSession();
      });
    }

    App.on("auth:changed", function () {
      renderAuthState();
      if (!(App.store.authUser && safeStr(App.store.authUser.role).toLowerCase() === "admin")) {
        stopAdminAutoRefresh();
        if (modalAdmin && modalAdmin.open) closeModal(modalAdmin);
      }
    });

    App.on("activejob:changed", function (detail) {
      console.log("[app.js] 📡 Event activejob:changed — jobId:", detail ? detail.jobId : "?",
        "has result:", !!(detail && detail.result));
      if (!historyList) return;
      historyList.querySelectorAll(".history-card").forEach(function (card) {
        card.classList.toggle("history-card--active",
          card.getAttribute("data-job-id") === safeStr(detail.jobId));
      });
    });

    if (btnThemeToggle) {
      btnThemeToggle.addEventListener("click", toggleTheme);
      console.log("[app.js] ✔ theme toggle bound");
    }

    if (btnAuthOpen) {
      btnAuthOpen.addEventListener("click", function () { openModal(modalAuth); });
    }
    if (quotaChip) {
      quotaChip.addEventListener("click", function () { fetchHistory(); });
    }
    if (btnAdminOpen) {
      btnAdminOpen.addEventListener("click", openAdminDashboard);
    }

    if (btnKeyboardShortcuts) {
      btnKeyboardShortcuts.addEventListener("click", function () { openModal(modalShortcuts); });
    }

    [modalShortcuts, modalAuth, modalAdmin].forEach(function (modal) {
      if (!modal) return;
      modal.querySelectorAll("[data-close]").forEach(function (el) {
        el.addEventListener("click", function () { closeModal(modal); });
      });
    });
    if (modalAdmin) {
      modalAdmin.addEventListener("close", stopAdminAutoRefresh);
      modalAdmin.addEventListener("cancel", stopAdminAutoRefresh);
      modalAdmin.addEventListener("click", handleAdminActionClick);
    }

    if (btnAuthModeLogin) btnAuthModeLogin.addEventListener("click", function () { setAuthMode("login"); });
    if (btnAuthModeRegister) btnAuthModeRegister.addEventListener("click", function () { setAuthMode("register"); });
    if (authForm) authForm.addEventListener("submit", handleAuthSubmit);
    if (btnAuthLogout) btnAuthLogout.addEventListener("click", handleLogout);

    if (historySearch) {
      historySearch.addEventListener("input", function () {
        console.log("[app.js] 🎛 History search:", this.value);
        scheduleHistoryRender();
      });
    }

    if (btnRefreshHistory) {
      btnRefreshHistory.addEventListener("click", function () {
        console.log("[app.js] 🎛 Refresh history button clicked");
        fetchHistory();
      });
    }

    syncViewportHeight();
    setupMobilePanelNav();
    g.addEventListener("resize", syncViewportHeight);
    g.addEventListener("orientationchange", syncViewportHeight);
    if (g.visualViewport) {
      g.visualViewport.addEventListener("resize", syncViewportHeight);
      g.visualViewport.addEventListener("scroll", syncViewportHeight);
    }

    setupKeyboard();
    scheduleHistoryRender();
    renderAuthState();
    renderQuotaState();
    App.refreshHistory = fetchHistory;
    App.startNewSession = startNewSession;
    Promise.resolve(typeof App.ensureSession === "function" ? App.ensureSession() : null)
      .then(function () { return verifyStoredAuth(); })
      .then(function () {
        fetchHistory();
      })
      .catch(function (err) {
        console.warn("[app.js] ✖ session bootstrap failed:", err);
        App.setStatus("Session setup failed", "error", "app");
      });

    if (appLoader) {
      appLoader.classList.add("fade-out");
      setTimeout(function () {
        if (appLoader.parentNode) appLoader.parentNode.removeChild(appLoader);
      }, 600);
    }

    console.log("[app.js] ✔ init() complete — all listeners bound");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  console.log("[app.js] ✔ Module loaded");
})(window);
