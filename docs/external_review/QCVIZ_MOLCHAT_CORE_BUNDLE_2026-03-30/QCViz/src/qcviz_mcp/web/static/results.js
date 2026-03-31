/**
 * QCViz-MCP v3 — Results Panel
 * FIX(M9): created_at 안정 정렬, MAX_RETAINED=100 eviction,
 *          clampIndex, 키 매핑, 메모리 누수 방지
 */
(function (g) {
  "use strict";
  console.log("[results.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[results.js] ✖ QCVizApp not found — aborting results module");
    return;
  }
  console.log("[results.js] ✔ QCVizApp found");

  // ─── 상수 ──────────────────────────────────────────
  var MAX_RETAINED_RESULTS = 100;
  var TAB_KEYS = ["summary", "geometry", "orbital", "esp", "charges", "json"];
  var HARTREE_TO_EV = 27.211386245988;
  var HARTREE_TO_KCAL = 627.5094740631;
  var ENERGY_UNIT_OPTIONS = [
    { value: "ev", label: "eV" },
    { value: "hartree", label: "Ha" },
    { value: "kcal_mol", label: "kcal/mol" },
  ];
  var ESP_UNIT_OPTIONS = [
    { value: "au", label: "a.u." },
    { value: "kcal_mol", label: "kcal/mol" },
  ];

  // ─── DOM refs ──────────────────────────────────────
  var resultsTabs = document.getElementById("resultsTabs");
  var resultsContent = document.getElementById("resultsContent");
  var resultsEmpty = document.getElementById("resultsEmpty");

  console.log("[results.js] DOM refs:", {
    resultsTabs: !!resultsTabs, resultsContent: !!resultsContent, resultsEmpty: !!resultsEmpty,
  });

  // ─── 상태 ──────────────────────────────────────────
  var activeTab = "summary";
  var resultHistory = [];
  var unitState = { energy: "ev", esp: "au" };

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) { return v == null ? fb || "" : String(v).trim(); }
  function safeNum(v, fb) { var n = parseFloat(v); return isFinite(n) ? n : fb || 0; }
  function finiteNum(v) { var n = parseFloat(v); return isFinite(n) ? n : null; }
  function show(el) { if (el) el.removeAttribute("hidden"); }
  function hide(el) { if (el) el.setAttribute("hidden", ""); }
  function escapeHtml(str) { var div = document.createElement("div"); div.textContent = str; return div.innerHTML; }
  function formatMaybeNum(v, precision) {
    var n = finiteNum(v);
    return n == null ? "—" : n.toFixed(precision);
  }

  function energyUnitLabel(unit) {
    if (unit === "hartree") return "Ha";
    if (unit === "kcal_mol") return "kcal/mol";
    return "eV";
  }

  function espUnitLabel(unit) {
    return unit === "kcal_mol" ? "kcal/mol" : "a.u.";
  }

  function buildEnergySpec(hartreeValue, evValue, kcalValue) {
    var ha = finiteNum(hartreeValue);
    var ev = finiteNum(evValue);
    var kcal = finiteNum(kcalValue);
    if (ha == null && ev != null) ha = ev / HARTREE_TO_EV;
    if (ha == null && kcal != null) ha = kcal / HARTREE_TO_KCAL;
    if (ha == null) return null;
    return {
      hartree: ha,
      ev: ev != null ? ev : ha * HARTREE_TO_EV,
      kcal_mol: kcal != null ? kcal : ha * HARTREE_TO_KCAL,
    };
  }

  function formatEnergySpec(spec, unit) {
    if (!spec) return "—";
    if (unit === "hartree") return spec.hartree.toFixed(8);
    if (unit === "kcal_mol") return spec.kcal_mol.toFixed(2);
    return spec.ev.toFixed(4);
  }

  function buildEspSpec(auValue, kcalValue) {
    var au = finiteNum(auValue);
    var kcal = finiteNum(kcalValue);
    if (au == null && kcal != null) au = kcal / HARTREE_TO_KCAL;
    if (au == null) return null;
    return {
      au: au,
      kcal_mol: kcal != null ? kcal : au * HARTREE_TO_KCAL,
    };
  }

  function formatEspSpec(spec, unit) {
    if (!spec) return "—";
    if (unit === "kcal_mol") return spec.kcal_mol.toFixed(2);
    return spec.au.toFixed(6);
  }

  function renderUnitToggle(kind, options, selected) {
    var html = ['<div class="result-toolbar"><div class="unit-toggle" data-unit-kind="' + kind + '">'];
    html.push('<span class="unit-toggle__label">Units</span>');
    options.forEach(function (opt) {
      var cls = "unit-toggle__btn" + (opt.value === selected ? " unit-toggle__btn--active" : "");
      html.push(
        '<button type="button" class="' + cls + '" data-unit-kind="' + kind + '" data-unit-value="' + opt.value + '">' +
        escapeHtml(opt.label) +
        "</button>"
      );
    });
    html.push("</div></div>");
    return html.join("");
  }

  function buildScfChartSvg(history) {
    var points = [];
    var useDelta = false;
    (history || []).forEach(function (entry) {
      var cycle = finiteNum(entry.cycle);
      if (cycle == null) return;
      var dE = finiteNum(entry.dE);
      if (dE != null && Math.abs(dE) > 0) {
        useDelta = true;
        points.push({ x: cycle, y: Math.log10(Math.abs(dE)) });
        return;
      }
      var energy = finiteNum(entry.energy);
      if (energy != null) {
        points.push({ x: cycle, y: energy });
      }
    });
    if (points.length < 2) return "";

    var width = 360;
    var height = 140;
    var pad = 16;
    var minX = points[0].x;
    var maxX = points[points.length - 1].x;
    var minY = points[0].y;
    var maxY = points[0].y;

    points.forEach(function (point) {
      if (point.y < minY) minY = point.y;
      if (point.y > maxY) maxY = point.y;
    });
    if (maxY === minY) {
      maxY += 1;
      minY -= 1;
    }

    var polyline = points.map(function (point) {
      var x = pad + ((point.x - minX) / Math.max(1, (maxX - minX))) * (width - pad * 2);
      var y = height - pad - ((point.y - minY) / (maxY - minY)) * (height - pad * 2);
      return x.toFixed(2) + "," + y.toFixed(2);
    }).join(" ");

    var threshold = "";
    if (useDelta && minY <= -6 && maxY >= -6) {
      var yThresh = height - pad - (((-6) - minY) / (maxY - minY)) * (height - pad * 2);
      threshold = '<line x1="' + pad + '" y1="' + yThresh.toFixed(2) + '" x2="' + (width - pad) + '" y2="' + yThresh.toFixed(2) + '" class="scf-chart__threshold"></line>';
    }

    return [
      '<div class="scf-chart">',
      '<div class="scf-chart__meta">', useDelta ? "log10|dE|" : "SCF energy", " vs cycle</div>",
      '<svg class="scf-chart__svg" viewBox="0 0 ', width, " ", height, '" preserveAspectRatio="none">',
      '<rect x="0" y="0" width="', width, '" height="', height, '" class="scf-chart__bg"></rect>',
      threshold,
      '<polyline points="', polyline, '" class="scf-chart__line"></polyline>',
      "</svg></div>",
    ].join("");
  }

  function mapResultKeys(r) {
    if (!r) return r;
    if (r.total_energy_hartree != null && r.energy_hartree == null) r.energy_hartree = r.total_energy_hartree;
    if (r.total_energy_ev != null && r.energy_ev == null) r.energy_ev = r.total_energy_ev;
    if (r.total_energy_hartree != null && r.total_energy_kcal_mol == null) r.total_energy_kcal_mol = r.total_energy_hartree * HARTREE_TO_KCAL;
    if (r.homo_energy_hartree == null && r.selected_orbital && safeStr(r.selected_orbital.label).toUpperCase() === "HOMO") {
      r.homo_energy_hartree = r.selected_orbital.energy_hartree;
      r.homo_energy_ev = r.selected_orbital.energy_ev;
    }
    var viz = r.visualization || {};
    if (!viz.xyz_block) viz.xyz_block = viz.xyz || viz.molecule_xyz || r.xyz || null;
    r.visualization = viz;
    console.log("[results.js] mapResultKeys — energy_ha:", r.energy_hartree,
      "viz_xyz:", !!viz.xyz_block, "viz.available:", JSON.stringify(viz.available || {}));
    return r;
  }

  // ─── 탭 렌더링 ────────────────────────────────────

  function renderTabs(result) {
    if (!resultsTabs) return;
    console.log("[results.js] renderTabs — activeTab:", activeTab);
    resultsTabs.innerHTML = "";

    var viz = result && result.visualization ? result.visualization : {};
    var available = viz.available || {};

    TAB_KEYS.forEach(function (key) {
      var btn = document.createElement("button");
      btn.className = "results-tab" + (key === activeTab ? " results-tab--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", key === activeTab ? "true" : "false");
      btn.setAttribute("data-tab", key);
      btn.textContent = key.charAt(0).toUpperCase() + key.slice(1);

      if (key === "orbital" && !available.orbital) {
        btn.disabled = true; btn.classList.add("results-tab--disabled");
      }
      if (key === "esp" && !available.esp) {
        btn.disabled = true; btn.classList.add("results-tab--disabled");
      }

      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        console.log("[results.js] 🎛 Tab clicked:", key);
        activeTab = key;
        renderTabs(result);
        renderContent(result);
      });

      resultsTabs.appendChild(btn);
    });
  }

  function renderContent(result) {
    if (!resultsContent) return;
    console.log("[results.js] renderContent — tab:", activeTab, "has result:", !!result);

    if (!result) {
      show(resultsEmpty);
      resultsContent.querySelectorAll(".results-pane").forEach(function (el) { el.remove(); });
      return;
    }

    hide(resultsEmpty);
    result = mapResultKeys(result);

    resultsContent.querySelectorAll(".results-pane").forEach(function (el) { el.remove(); });

    var pane = document.createElement("div");
    pane.className = "results-pane";

    switch (activeTab) {
      case "summary": pane.innerHTML = renderSummary(result); break;
      case "geometry": pane.innerHTML = renderGeometry(result); break;
      case "orbital": pane.innerHTML = renderOrbital(result); break;
      case "esp": pane.innerHTML = renderEsp(result); break;
      case "charges": pane.innerHTML = renderCharges(result); break;
      case "json": pane.innerHTML = renderJson(result); break;
      default: pane.innerHTML = "<p>Unknown tab</p>";
    }

    resultsContent.appendChild(pane);

    pane.querySelectorAll("table.result-table").forEach(function (table) {
      var parent = table.parentNode;
      if (!parent || (parent.classList && parent.classList.contains("result-table-wrap"))) return;
      var wrap = document.createElement("div");
      wrap.className = "result-table-wrap";
      parent.insertBefore(wrap, table);
      wrap.appendChild(table);
    });

    // Bind orbital table row clicks → dispatch orbital-selected event
    pane.querySelectorAll("tr[data-orbital-label]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        var label = this.getAttribute("data-orbital-label");
        console.log("[results.js] orbital row clicked:", label);
        document.dispatchEvent(new CustomEvent("orbital-selected", { detail: { label: label } }));
        // Highlight selected row
        pane.querySelectorAll("tr[data-orbital-label]").forEach(function (r) {
          r.classList.remove("result-table__highlight");
        });
        this.classList.add("result-table__highlight");
      });
    });

    pane.querySelectorAll("[data-unit-kind][data-unit-value]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var kind = this.getAttribute("data-unit-kind");
        var value = this.getAttribute("data-unit-value");
        if (!kind || !value) return;
        unitState[kind] = value;
        renderContent(result);
      });
    });

    console.log("[results.js] renderContent — done for tab:", activeTab);
  }

  // ─── 개별 탭 HTML 생성 ─────────────────────────────

  function renderTextList(title, items) {
    if (!items || !items.length) return "";
    var html = ['<div class="result-subsection"><h4 class="result-subsection__title">' + escapeHtml(title) + "</h4><ul class=\"result-list\">"];
    items.forEach(function (item) {
      html.push("<li>" + escapeHtml(safeStr(item)) + "</li>");
    });
    html.push("</ul></div>");
    return html.join("");
  }

  function renderExplanationBlock(explanation) {
    if (!explanation || !explanation.summary) return "";
    var html = ['<div class="result-section">'];
    html.push('<h3 class="result-section__title">Interpretation</h3>');
    html.push('<p class="result-copy">' + escapeHtml(safeStr(explanation.summary)) + "</p>");
    html.push(renderTextList("Key Findings", explanation.key_findings || []));
    html.push(renderTextList("Interpretation", explanation.interpretation || []));
    html.push(renderTextList("Cautions", explanation.cautions || []));
    html.push(renderTextList("Next Actions", explanation.next_actions || []));
    html.push("</div>");
    return html.join("");
  }

  function renderAdvisorBlock(summary) {
    if (!summary) return "";
    var rows = [];
    if (summary.recommended_functional || summary.recommended_basis) {
      rows.push(["Recommended Level", safeStr(summary.recommended_functional, "—") + " / " + safeStr(summary.recommended_basis, "—")]);
    }
    if (summary.confidence_score != null) {
      rows.push(["Confidence", formatMaybeNum(summary.confidence_score, 2) + " (" + safeStr(summary.confidence_label, "n/a") + ")"]);
    }
    if (summary.literature_status) {
      rows.push(["Literature", escapeHtml(safeStr(summary.literature_status))]);
    }
    if (!rows.length && !summary.methods_preview && !summary.script_preview && !(summary.recommendations || []).length) {
      return "";
    }

    var html = ['<div class="result-section">'];
    html.push('<h3 class="result-section__title">Advisor</h3>');
    if (rows.length) {
      html.push('<table class="result-table">');
      rows.forEach(function (row) {
        html.push('<tr><td class="result-table__key">' + row[0] + '</td><td class="result-table__val">' + row[1] + "</td></tr>");
      });
      html.push("</table>");
    }
    if (summary.preset_rationale) {
      html.push('<p class="result-copy">' + escapeHtml(summary.preset_rationale) + "</p>");
    }
    if (summary.literature_summary) {
      html.push('<div class="result-subsection"><h4 class="result-subsection__title">Literature Summary</h4><p class="result-copy">' + escapeHtml(summary.literature_summary) + "</p></div>");
    }
    if (summary.methods_preview) {
      html.push('<div class="result-subsection"><h4 class="result-subsection__title">Methods Draft Preview</h4><p class="result-copy">' + escapeHtml(summary.methods_preview) + "</p></div>");
    }
    if (summary.script_preview) {
      html.push('<div class="result-subsection"><h4 class="result-subsection__title">Script Preview</h4><pre class="result-code">' + escapeHtml(summary.script_preview) + "</pre></div>");
    }
    html.push(renderTextList("Recommendations", summary.recommendations || []));
    html.push("</div>");
    return html.join("");
  }

  function renderSummary(r) {
    console.log("[results.js] renderSummary — structure:", r.structure_name || r.structure_query,
      "job_type:", r.job_type, "method:", r.method, "basis:", r.basis);
    var parts = [];
    var totalEnergy = buildEnergySpec(r.total_energy_hartree, r.total_energy_ev, r.total_energy_kcal_mol);
    var gapEnergy = buildEnergySpec(r.orbital_gap_hartree, r.orbital_gap_ev, null);
    var homoEnergy = buildEnergySpec(r.homo_energy_hartree, r.homo_energy_ev, null);
    var lumoEnergy = buildEnergySpec(r.lumo_energy_hartree, r.lumo_energy_ev, null);
    var scfHistory = r.scf_history || [];
    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Summary</h3>');
    parts.push(renderUnitToggle("energy", ENERGY_UNIT_OPTIONS, unitState.energy));
    parts.push('<table class="result-table">');

    var rows = [
      ["Structure", escapeHtml(safeStr(r.structure_name || r.structure_query, "—"))],
      ["Job Type", escapeHtml(safeStr(r.job_type, "—"))],
      ["Method", escapeHtml(safeStr(r.method, "—"))],
      ["Basis", escapeHtml(safeStr(r.basis, "—"))],
      ["Charge", safeStr(r.charge, "0")],
      ["Multiplicity", safeStr(r.multiplicity, "1")],
      ["# Atoms", safeStr(r.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(r.formula, "—"))],
    ];

    if (totalEnergy) rows.push(["Energy (" + energyUnitLabel(unitState.energy) + ")", formatEnergySpec(totalEnergy, unitState.energy)]);
    if (gapEnergy) rows.push(["HOMO-LUMO Gap (" + energyUnitLabel(unitState.energy) + ")", formatEnergySpec(gapEnergy, unitState.energy)]);
    if (homoEnergy) rows.push(["HOMO (" + energyUnitLabel(unitState.energy) + ")", formatEnergySpec(homoEnergy, unitState.energy)]);
    if (lumoEnergy) rows.push(["LUMO (" + energyUnitLabel(unitState.energy) + ")", formatEnergySpec(lumoEnergy, unitState.energy)]);
    if (r.scf_converged != null) rows.push(["SCF Converged", r.scf_converged ? "Yes" : "No"]);
    if (r.n_scf_cycles != null) rows.push(["SCF Cycles", safeStr(r.n_scf_cycles, "—")]);
    if (r.scf_elapsed_s != null) rows.push(["SCF Time (s)", formatMaybeNum(r.scf_elapsed_s, 2)]);
    if (r.scf_final_delta_e_hartree != null) rows.push(["Final dE (Ha)", formatMaybeNum(r.scf_final_delta_e_hartree, 8)]);
    if (r.dipole_moment) rows.push(["Dipole (Debye)", safeNum(r.dipole_moment.magnitude).toFixed(4)]);

    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td>");
      parts.push('<td class="result-table__val">' + row[1] + "</td></tr>");
    });
    parts.push("</table></div>");

    parts.push(renderExplanationBlock(r.explanation));
    parts.push(renderAdvisorBlock(r.advisor_summary));

    if (scfHistory.length > 1) {
      parts.push('<div class="result-section">');
      parts.push('<h3 class="result-section__title">SCF Convergence</h3>');
      parts.push(buildScfChartSvg(scfHistory));
      parts.push("</div>");
    }

    var warnings = r.warnings || [];
    if (warnings.length > 0) {
      console.log("[results.js] renderSummary — warnings:", warnings.length);
      parts.push('<div class="result-section result-section--warnings">');
      parts.push("<h4>Warnings</h4><ul>");
      warnings.forEach(function (w) { parts.push("<li>" + escapeHtml(w) + "</li>"); });
      parts.push("</ul></div>");
    }
    return parts.join("");
  }

  function renderGeometry(r) {
    console.log("[results.js] renderGeometry — atoms:", (r.atoms||[]).length, "bonds:", (r.bonds||[]).length);
    var geo = r.geometry_summary || {};
    var parts = [];
    parts.push('<div class="result-section"><h3 class="result-section__title">Geometry</h3>');
    parts.push('<table class="result-table">');
    var rows = [
      ["# Atoms", safeStr(geo.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(geo.formula || r.formula, "—"))],
      ["# Bonds", safeStr(geo.bond_count, "—")],
    ];
    if (geo.bond_length_min_angstrom != null) rows.push(["Min Bond (Å)", safeNum(geo.bond_length_min_angstrom).toFixed(4)]);
    if (geo.bond_length_max_angstrom != null) rows.push(["Max Bond (Å)", safeNum(geo.bond_length_max_angstrom).toFixed(4)]);
    if (geo.bond_length_mean_angstrom != null) rows.push(["Mean Bond (Å)", safeNum(geo.bond_length_mean_angstrom).toFixed(4)]);
    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td><td class=\"result-table__val\">" + row[1] + "</td></tr>");
    });
    parts.push("</table>");
    var atoms = r.atoms || [];
    if (atoms.length > 0 && atoms.length <= 100) {
      parts.push('<h4 style="margin-top:1rem">Atoms</h4>');
      parts.push('<table class="result-table result-table--compact">');
      parts.push("<tr><th>#</th><th>Element</th><th>x</th><th>y</th><th>z</th></tr>");
      atoms.forEach(function (a, i) {
        parts.push("<tr><td>" + (i+1) + "</td><td>" + escapeHtml(safeStr(a.symbol)) +
          "</td><td>" + safeNum(a.x).toFixed(4) + "</td><td>" + safeNum(a.y).toFixed(4) +
          "</td><td>" + safeNum(a.z).toFixed(4) + "</td></tr>");
      });
      parts.push("</table>");
    }
    parts.push("</div>");
    return parts.join("");
  }

  function renderOrbital(r) {
    var orbitals = r.orbitals || [];
    var selected = r.selected_orbital || {};
    console.log("[results.js] renderOrbital — orbitals:", orbitals.length,
      "selected:", selected.label || "none");
    var parts = [];
    parts.push('<div class="result-section"><h3 class="result-section__title">Orbital</h3>');
    parts.push(renderUnitToggle("energy", ENERGY_UNIT_OPTIONS, unitState.energy));
    if (selected.label) {
      var selectedEnergy = buildEnergySpec(selected.energy_hartree, selected.energy_ev, null);
      parts.push("<p><strong>Selected:</strong> " + escapeHtml(selected.label) +
        " (" + formatEnergySpec(selectedEnergy, unitState.energy) + " " + energyUnitLabel(unitState.energy) + ")</p>");
    }
    if (orbitals.length > 0) {
      parts.push('<table class="result-table result-table--compact">');
      parts.push("<tr><th>#</th><th>Label</th><th>Energy (" + energyUnitLabel(unitState.energy) + ")</th><th>Occ</th></tr>");
      orbitals.forEach(function (o) {
        var cls = (o.label === "HOMO" || o.label === "LUMO") ? ' class="result-table__highlight"' : "";
        var orbitalEnergy = buildEnergySpec(o.energy_hartree, o.energy_ev, null);
        parts.push("<tr" + cls + ' data-orbital-label="' + escapeHtml(o.label) + '" style="cursor:pointer" title="Click to select ' + escapeHtml(o.label) + '">' +
          "<td>" + o.index + "</td><td>" + escapeHtml(o.label) +
          "</td><td>" + formatEnergySpec(orbitalEnergy, unitState.energy) + "</td><td>" +
          safeNum(o.occupancy).toFixed(2) + "</td></tr>");
      });
      parts.push("</table>");
    } else {
      parts.push("<p>No orbital data available.</p>");
    }
    parts.push("</div>");
    return parts.join("");
  }

  function renderEsp(r) {
    console.log("[results.js] renderEsp — esp_preset:", r.esp_preset,
      "range_au:", r.esp_auto_range_au);
    var parts = [];
    var rangeSpec = buildEspSpec(r.esp_auto_range_au, r.esp_auto_range_kcal);
    parts.push('<div class="result-section"><h3 class="result-section__title">Electrostatic Potential</h3>');
    parts.push(renderUnitToggle("esp", ESP_UNIT_OPTIONS, unitState.esp));
    if (r.esp_preset) parts.push("<p><strong>Preset:</strong> " + escapeHtml(r.esp_preset) + "</p>");
    if (rangeSpec) {
      parts.push("<p><strong>Range:</strong> ±" + formatEspSpec(rangeSpec, unitState.esp) +
        " " + espUnitLabel(unitState.esp) + "</p>");
    }
    var fit = r.esp_auto_fit || {};
    var stats = fit.stats || {};
    if (stats.n) {
      parts.push('<table class="result-table">');
      parts.push("<tr><td>Grid points</td><td>" + stats.n + "</td></tr>");
      if (stats.min_au != null) parts.push("<tr><td>Min (" + espUnitLabel(unitState.esp) + ")</td><td>" + formatEspSpec(buildEspSpec(stats.min_au, null), unitState.esp) + "</td></tr>");
      if (stats.max_au != null) parts.push("<tr><td>Max (" + espUnitLabel(unitState.esp) + ")</td><td>" + formatEspSpec(buildEspSpec(stats.max_au, null), unitState.esp) + "</td></tr>");
      if (stats.mean_au != null) parts.push("<tr><td>Mean (" + espUnitLabel(unitState.esp) + ")</td><td>" + formatEspSpec(buildEspSpec(stats.mean_au, null), unitState.esp) + "</td></tr>");
      if (stats.p95_abs_au != null) parts.push("<tr><td>P95 |V| (" + espUnitLabel(unitState.esp) + ")</td><td>" + formatEspSpec(buildEspSpec(stats.p95_abs_au, null), unitState.esp) + "</td></tr>");
      parts.push("</table>");
    }
    parts.push("</div>");
    return parts.join("");
  }

  function renderCharges(r) {
    var charges = r.mulliken_charges || r.partial_charges || [];
    var lowdin = r.lowdin_charges || [];
    console.log("[results.js] renderCharges — mulliken:", charges.length, "lowdin:", lowdin.length);
    var parts = [];
    parts.push('<div class="result-section"><h3 class="result-section__title">Partial Charges</h3>');
    if (charges.length > 0) {
      parts.push("<h4>Mulliken</h4>");
      parts.push('<table class="result-table result-table--compact"><tr><th>#</th><th>Atom</th><th>Charge</th></tr>');
      charges.forEach(function (c, i) {
        parts.push("<tr><td>" + (c.atom_index != null ? c.atom_index + 1 : i + 1) +
          "</td><td>" + escapeHtml(safeStr(c.symbol)) + "</td><td>" +
          safeNum(c.charge).toFixed(4) + "</td></tr>");
      });
      parts.push("</table>");
    }
    if (lowdin.length > 0) {
      parts.push('<h4 style="margin-top:1rem">Löwdin</h4>');
      parts.push('<table class="result-table result-table--compact"><tr><th>#</th><th>Atom</th><th>Charge</th></tr>');
      lowdin.forEach(function (c, i) {
        parts.push("<tr><td>" + (c.atom_index != null ? c.atom_index + 1 : i + 1) +
          "</td><td>" + escapeHtml(safeStr(c.symbol)) + "</td><td>" +
          safeNum(c.charge).toFixed(4) + "</td></tr>");
      });
      parts.push("</table>");
    }
    if (charges.length === 0 && lowdin.length === 0) parts.push("<p>No charge data available.</p>");
    parts.push("</div>");
    return parts.join("");
  }

  function renderJson(r) {
    console.log("[results.js] renderJson — keys:", Object.keys(r).join(","));
    var parts = [];
    parts.push('<div class="result-section"><h3 class="result-section__title">Raw JSON</h3><div class="json-viewer">');
    var cleaned = {};
    Object.keys(r).forEach(function (k) {
      if (k.indexOf("cube_b64") >= 0) { cleaned[k] = "[base64 data omitted]"; }
      else if (k === "visualization") {
        var vizCopy = Object.assign({}, r[k]);
        ["orbital_cube_b64", "density_cube_b64", "esp_cube_b64"].forEach(function (bk) {
          if (vizCopy[bk]) vizCopy[bk] = "[base64 data omitted]";
        });
        if (vizCopy.orbital && vizCopy.orbital.cube_b64) vizCopy.orbital = Object.assign({}, vizCopy.orbital, { cube_b64: "[omitted]" });
        if (vizCopy.density && vizCopy.density.cube_b64) vizCopy.density = Object.assign({}, vizCopy.density, { cube_b64: "[omitted]" });
        if (vizCopy.esp && vizCopy.esp.cube_b64) vizCopy.esp = Object.assign({}, vizCopy.esp, { cube_b64: "[omitted]" });
        cleaned[k] = vizCopy;
      } else { cleaned[k] = r[k]; }
    });
    parts.push("<pre>" + escapeHtml(JSON.stringify(cleaned, null, 2)) + "</pre>");
    parts.push("</div></div>");
    return parts.join("");
  }

  // ─── 결과 표시 진입점 ──────────────────────────────

  function displayResult(result, opts) {
    opts = opts || {};
    console.log("[results.js] displayResult — has result:", !!result,
      "source:", opts.source || "?",
      "result keys:", result ? Object.keys(result).join(",") : "none");
    if (!result) return;

    result = mapResultKeys(result);

    resultHistory.push(result);
    if (resultHistory.length > MAX_RETAINED_RESULTS) {
      console.log("[results.js] displayResult — evicting oldest result (count:", resultHistory.length, ")");
      resultHistory.shift();
    }

    var defaultTab = safeStr(
      (result.visualization || {}).defaults
        ? result.visualization.defaults.focus_tab || result.advisor_focus_tab
        : result.advisor_focus_tab,
      "summary",
    );
    if (TAB_KEYS.indexOf(defaultTab) >= 0) {
      activeTab = defaultTab;
    }
    console.log("[results.js] displayResult — defaultTab:", defaultTab, "activeTab:", activeTab);

    renderTabs(result);
    renderContent(result);
  }

  // ─── 이벤트 ────────────────────────────────────────

  function init() {
    console.log("[results.js] init() — starting initialization");

    App.on("result:changed", function (detail) {
      console.log("[results.js] 📡 Event result:changed — has result:", !!(detail && detail.result),
        "source:", detail ? detail.source : "?");
      if (detail && detail.result) {
        displayResult(detail.result, { source: detail.source });
      }
    });

    document.addEventListener("keydown", function (e) {
      if (document.activeElement &&
        (document.activeElement.tagName === "INPUT" ||
          document.activeElement.tagName === "TEXTAREA" ||
          document.activeElement.tagName === "SELECT")) return;

      var idx = parseInt(e.key, 10);
      if (idx >= 1 && idx <= TAB_KEYS.length) {
        console.log("[results.js] 🎛 Key shortcut:", e.key, "→ tab:", TAB_KEYS[idx - 1]);
        activeTab = TAB_KEYS[idx - 1];
        if (App.store.activeResult) {
          renderTabs(App.store.activeResult);
          renderContent(App.store.activeResult);
        }
      }
    });

    console.log("[results.js] ✔ init() complete");
  }

  App.results = {
    display: displayResult,
    getActiveTab: function () { return activeTab; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  console.log("[results.js] ✔ Module loaded");
})(window);
