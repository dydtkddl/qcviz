# [프론트] UI 노이즈 제거 및 기능 버튼/이력 완벽 정상화

**작업 지시서 (Prompt):**
당신은 실리콘밸리 탑티어 프론트엔드 엔지니어이자 UI/UX 디자이너입니다.
현재 양자화학 시각화 SaaS의 최신 프론트엔드 코드(HTML, CSS, JS)가 주어져 있습니다.

**[작업 목표]**
1. **[필수] UI 다이어트 및 노이즈 제거**: 현재 3D Viewer 패널에 있는 불필요한 메트릭(`hero-info`), 중복된 설명 텍스트, 거추장스러운 레이아웃 요소를 과감히 삭제해주세요. 사용자(연구원)가 오직 분자와 데이터에만 집중할 수 있는 미니멀하고 세련된 디자인으로 개편해야 합니다.
2. **[필수] 기능 버튼 완벽 정상화**: 현재 제대로 동작하지 않는 스타일 버튼(Stick, Sphere 등), 오비탈/ESP 토글, 원자/전하 레이블 표시 버튼들을 `viewer.js`와 `index.html`에서 완벽하게 수선해주세요. 모든 인터랙션은 3Dmol.js 인스턴스와 실제 데이터에 즉각적이고 정확하게 반응해야 합니다.
3. **[중요] Job History 센터 구축**: 우측 하단이나 별도 탭에 지금까지의 계산 이력을 보여주는 미려한 UI를 만들어주세요. 
   - 각 항목 클릭 시, 해당 과거 계산의 **3D 시각화(오비탈/ESP 포함)와 결과 데이터가 화면에 즉시 복원**되어야 합니다.
4. 데스크톱 환경에 최적화된 엔터프라이즈급 미학(Glassmorphism, 고품질 그리드, 부드러운 애니메이션)을 적용하여 `style.css`를 대폭 강화해주세요.
5. 복사해서 바로 덮어쓸 수 있도록 각 파일의 전체 코드(Full Code)를 마크다운으로 깔끔하게 제공해주세요.


---

## 📂 최신 소스 코드 컨텍스트 (Current Context)

### `version02/src/qcviz_mcp/web/templates/index.html`
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1, viewport-fit=cover"
  />
  <title>QCViz-MCP — Quantum Chemistry Visualization</title>
  <meta
    name="description"
    content="Natural-language quantum chemistry calculations and visualization with FastAPI, PySCF, 3Dmol.js, WebSocket, and LLM planning."
  />

  <style>
    :root {
      --bg: #f8fafc;
      --panel: #ffffff;
      --panel-2: #fefefe;
      --border: rgba(148, 163, 184, 0.24);
      --border-strong: rgba(100, 116, 139, 0.35);
      --text: #0f172a;
      --text-soft: #334155;
      --text-muted: #64748b;
      --accent: #2563eb;
      --accent-2: #1d4ed8;
      --accent-soft: rgba(37, 99, 235, 0.08);
      --ok: #047857;
      --warn: #b45309;
      --error: #b91c1c;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
      --radius-lg: 18px;
      --radius-md: 14px;
      --radius-sm: 10px;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      margin: 0;
      padding: 0;
      min-height: 100%;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.06), transparent 26%),
        radial-gradient(circle at top right, rgba(16, 185, 129, 0.05), transparent 20%),
        var(--bg);
      font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Helvetica,
        Arial,
        sans-serif;
    }

    a {
      color: inherit;
    }

    button,
    input,
    select,
    textarea {
      font: inherit;
    }

    .app-shell {
      width: 100%;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    .app-header {
      padding: 18px 20px 12px;
    }

    .app-header-card {
      background: rgba(255, 255, 255, 0.86);
      backdrop-filter: blur(10px);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: var(--shadow);
      padding: 18px 20px;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    .brand-wrap {
      min-width: 0;
    }

    .brand-kicker {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
    }

    .brand-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: linear-gradient(135deg, #2563eb, #10b981);
      box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.08);
    }

    .brand-title {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
      letter-spacing: -0.02em;
    }

    .brand-subtitle {
      margin: 8px 0 0;
      color: var(--text-muted);
      font-size: 14px;
      line-height: 1.5;
      max-width: 820px;
    }

    .header-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
    }

    .meta-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text-soft);
      font-size: 13px;
      font-weight: 600;
    }

    .meta-pill .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #94a3b8;
    }

    .qcviz-shell {
      width: 100%;
      padding: 0 20px 20px;
      flex: 1;
    }

    .qcviz-main {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.95fr);
      gap: 18px;
      align-items: start;
    }

    .viewer-panel,
    .side-panel {
      min-width: 0;
    }

    .side-panel {
      display: grid;
      gap: 18px;
    }

    .panel-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid var(--border);
    }

    .panel-title {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      letter-spacing: -0.01em;
    }

    .panel-subtitle {
      margin: 4px 0 0;
      color: var(--text-muted);
      font-size: 13px;
      line-height: 1.45;
    }

    .status-inline {
      display: grid;
      gap: 4px;
      justify-items: end;
      min-width: 160px;
      font-size: 12px;
      color: var(--text-muted);
      text-align: right;
    }

    #viz-status[data-tone="ok"],
    #chatStatus[data-tone="ok"] {
      color: var(--ok);
    }

    #viz-status[data-tone="warn"],
    #chatStatus[data-tone="warn"] {
      color: var(--warn);
    }

    #viz-status[data-tone="error"],
    #chatStatus[data-tone="error"] {
      color: var(--error);
    }

    .hero-info {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 14px 18px 0;
    }

    .hero-metric {
      border: 1px solid var(--border);
      border-radius: 14px;
      background: linear-gradient(to bottom, #ffffff, #f8fafc);
      padding: 12px;
    }

    .hero-metric-label {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 6px;
    }

    .hero-metric-value {
      font-size: 15px;
      font-weight: 700;
      color: var(--text);
    }

    .viewer-toolbar,
    .viewer-subtoolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(to bottom, #ffffff, #fbfdff);
    }

    .toolbar-group {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .tool-btn,
    .prompt-btn,
    .send-btn,
    .result-tab,
    .chip,
    .orbital-chip {
      appearance: none;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 12px;
      padding: 8px 12px;
      cursor: pointer;
      transition: 0.16s ease;
      line-height: 1.2;
      text-decoration: none;
    }

    .tool-btn:hover,
    .prompt-btn:hover,
    .send-btn:hover,
    .result-tab:hover,
    .chip:hover,
    .orbital-chip:hover {
      border-color: rgba(37, 99, 235, 0.42);
      background: var(--accent-soft);
    }

    .tool-btn.is-active,
    .result-tab.is-active,
    .orbital-chip.is-active {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 700;
    }

    .tool-btn:disabled,
    .prompt-btn:disabled,
    .send-btn:disabled,
    .result-tab:disabled,
    .chip:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .tool-select,
    select {
      min-height: 40px;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 8px 10px;
      background: #fff;
      color: var(--text);
    }

    .tool-select:focus,
    select:focus,
    input:focus,
    textarea:focus {
      outline: none;
      border-color: rgba(37, 99, 235, 0.52);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.08);
    }

    .inline-label,
    .check-label,
    .control-item label {
      font-size: 13px;
      color: var(--text-muted);
    }

    .check-label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      padding: 0 2px;
    }

    .control-item {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .control-item input[type="range"] {
      width: 180px;
      accent-color: var(--accent);
    }

    .value-badge {
      min-width: 56px;
      text-align: center;
      padding: 4px 8px;
      border-radius: 999px;
      background: #eef2ff;
      color: #3730a3;
      font-size: 12px;
      font-weight: 700;
    }

    .viewer-canvas {
      width: 100%;
      min-height: 580px;
      height: 66vh;
      background: #fff;
      position: relative;
    }

    .result-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 16px 0;
    }

    .result-content {
      padding: 16px;
    }

    .result-card {
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      background: #fff;
      margin-bottom: 14px;
    }

    .result-card:last-child {
      margin-bottom: 0;
    }

    .result-card-title {
      font-weight: 800;
      margin-bottom: 10px;
      letter-spacing: -0.01em;
    }

    .card-subtitle {
      color: var(--text-muted);
      font-size: 13px;
      line-height: 1.45;
    }

    .summary-grid,
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .metric-card {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      background: linear-gradient(to bottom, #ffffff, #f8fafc);
    }

    .metric-label {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 6px;
    }

    .metric-value {
      font-size: 18px;
      line-height: 1.2;
      font-weight: 800;
      color: var(--text);
      word-break: break-word;
    }

    .chip-row,
    .orbital-chip-row,
    .prompt-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .chip.is-disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .inline-kv {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 16px;
      color: var(--text-soft);
      font-size: 14px;
    }

    .mt-sm {
      margin-top: 8px;
    }

    .orbital-chip {
      display: inline-flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
      min-width: 100px;
    }

    .orbital-chip-label {
      font-weight: 700;
    }

    .orbital-chip-meta {
      font-size: 12px;
      color: var(--text-muted);
    }

    .table-wrap {
      width: 100%;
      overflow: auto;
      border-radius: 12px;
      border: 1px solid var(--border);
    }

    .data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      background: #fff;
    }

    .data-table th,
    .data-table td {
      border-bottom: 1px solid var(--border);
      text-align: left;
      padding: 10px 8px;
      vertical-align: top;
    }

    .data-table th {
      background: #f8fafc;
      color: var(--text-soft);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }

    .mono-text,
    .code-block,
    .code-block code {
      font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        Monaco,
        Consolas,
        "Liberation Mono",
        monospace;
    }

    .code-block {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 14px;
      padding: 12px;
      overflow: auto;
      line-height: 1.5;
      font-size: 13px;
    }

    .warning-card {
      border-color: rgba(180, 83, 9, 0.32);
      background: rgba(251, 191, 36, 0.08);
    }

    .warning-list {
      margin: 8px 0 0;
      padding-left: 18px;
      color: var(--text-soft);
    }

    .empty-state {
      color: var(--text-muted);
      padding: 12px 4px;
      line-height: 1.5;
    }

    .job-events-card {
      border-top: 1px solid var(--border);
      padding: 14px 16px 16px;
    }

    .job-events-title {
      font-weight: 800;
      margin-bottom: 8px;
      letter-spacing: -0.01em;
    }

    .job-events-list {
      max-height: 220px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: #fff;
    }

    .chat-status {
      font-size: 13px;
      color: var(--text-muted);
    }

    .chat-log {
      min-height: 280px;
      max-height: 440px;
      overflow: auto;
      padding: 14px 16px;
      display: grid;
      gap: 10px;
      background:
        linear-gradient(to bottom, rgba(255,255,255,1), rgba(248,250,252,1));
    }

    .chat-message {
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 10px 12px;
      background: #fff;
      box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
    }

    .chat-message.user {
      background: #eff6ff;
      border-color: rgba(37, 99, 235, 0.24);
    }

    .chat-message.assistant {
      background: #f8fafc;
    }

    .chat-message.error {
      background: #fef2f2;
      border-color: rgba(185, 28, 28, 0.24);
    }

    .chat-message.system {
      background: #f8fafc;
      border-style: dashed;
    }

    .chat-message-header {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .chat-role {
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }

    .chat-message-body {
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
      color: var(--text);
    }

    .chat-composer {
      border-top: 1px solid var(--border);
      padding: 14px 16px 16px;
      display: grid;
      gap: 10px;
      background: linear-gradient(to bottom, #ffffff, #fbfdff);
    }

    #chatInput {
      width: 100%;
      resize: vertical;
      min-height: 96px;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      background: #fff;
      color: var(--text);
      line-height: 1.5;
    }

    .chat-composer-row {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }

    .prompt-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .send-btn {
      min-width: 110px;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-color: var(--accent);
      color: #fff;
      font-weight: 800;
    }

    .send-btn:hover {
      background: linear-gradient(135deg, #1d4ed8, #1e40af);
      border-color: #1d4ed8;
    }

    .footer-note {
      padding: 0 20px 22px;
      color: var(--text-muted);
      font-size: 12px;
      text-align: center;
    }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    @media (max-width: 1180px) {
      .qcviz-main {
        grid-template-columns: 1fr;
      }

      .viewer-canvas {
        min-height: 460px;
        height: 54vh;
      }

      .hero-info {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 760px) {
      .app-header {
        padding: 14px 14px 10px;
      }

      .qcviz-shell {
        padding: 0 14px 14px;
      }

      .brand-title {
        font-size: 24px;
      }

      .hero-info {
        grid-template-columns: 1fr;
      }

      .summary-grid,
      .metric-grid {
        grid-template-columns: 1fr;
      }

      .chat-composer-row {
        flex-direction: column;
      }

      .send-btn {
        width: 100%;
      }

      .control-item input[type="range"] {
        width: 140px;
      }

      .status-inline {
        justify-items: start;
        text-align: left;
      }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header-card">
        <div class="brand-wrap">
          <div class="brand-kicker">
            <span class="brand-dot" aria-hidden="true"></span>
            Quantum Chemistry Visualization MCP
          </div>
          <h1 class="brand-title">QCViz-MCP</h1>
          <p class="brand-subtitle">
            Natural-language interface for quantum chemistry calculations,
            orbital rendering, ESP surfaces, geometry analysis, and browser-based
            molecular visualization.
          </p>
        </div>

        <div class="header-meta">
          <div class="meta-pill">
            <span class="dot" aria-hidden="true"></span>
            WebSocket: <span id="top-ws-state">auto</span>
          </div>
          <div class="meta-pill">
            <span class="dot" aria-hidden="true"></span>
            Planner + PySCF + 3Dmol.js
          </div>
        </div>
      </div>
    </header>

    <main class="qcviz-shell">
      <section class="qcviz-main">
        <!-- LEFT: Viewer -->
        <section class="viewer-panel">
          <section class="panel-card">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">3D Viewer</h2>
                <p class="panel-subtitle">
                  Structure, orbital isosurfaces, ESP maps, atom labels, and charge labels
                </p>
              </div>
              <div class="status-inline">
                <span id="viz-status">3D viewer 준비 중…</span>
                <span id="viewer-meta"></span>
              </div>
            </div>

            <div class="hero-info">
              <div class="hero-metric">
                <div class="hero-metric-label">Orbital Rendering</div>
                <div class="hero-metric-value">± Isosurface support</div>
              </div>
              <div class="hero-metric">
                <div class="hero-metric-label">ESP Mapping</div>
                <div class="hero-metric-value">Auto-fit + presets</div>
              </div>
              <div class="hero-metric">
                <div class="hero-metric-label">Input Style</div>
                <div class="hero-metric-value">Natural language / XYZ</div>
              </div>
              <div class="hero-metric">
                <div class="hero-metric-label">Backend Mode</div>
                <div class="hero-metric-value">Chat + Compute jobs</div>
              </div>
            </div>

            <div class="viewer-toolbar">
              <div class="toolbar-group">
                <button type="button" id="btn-style-ballstick" class="tool-btn is-active">
                  Ball+Stick
                </button>
                <button type="button" id="btn-style-stick" class="tool-btn">
                  Stick
                </button>
                <button type="button" id="btn-style-sphere" class="tool-btn">
                  Sphere
                </button>

                <label class="inline-label" for="viewerStyleSelect">Style</label>
                <select id="viewerStyleSelect" class="tool-select" aria-label="Viewer style">
                  <option value="ballstick">Ball+Stick</option>
                  <option value="stick">Stick</option>
                  <option value="sphere">Sphere</option>
                </select>
              </div>

              <div class="toolbar-group">
                <button type="button" id="btn-orbital" class="tool-btn">
                  Show Orbital
                </button>
                <button type="button" id="btn-esp" class="tool-btn">
                  Show ESP
                </button>
                <button type="button" id="btn-clear-surfaces" class="tool-btn">
                  Clear Surfaces
                </button>
                <button type="button" id="btn-reset-view" class="tool-btn">
                  Reset View
                </button>
                <button type="button" id="btn-snapshot" class="tool-btn">
                  Save PNG
                </button>
              </div>

              <div class="toolbar-group">
                <label class="check-label">
                  <input type="checkbox" id="chk-atom-labels" />
                  Atom labels
                </label>
                <button type="button" id="btn-atom-labels" class="tool-btn">
                  Toggle Atom Labels
                </button>

                <label class="check-label">
                  <input type="checkbox" id="chk-charge-labels" />
                  Charge labels
                </label>
                <button type="button" id="btn-charge-labels" class="tool-btn">
                  Toggle Charge Labels
                </button>
              </div>
            </div>

            <div id="orbital-controls" class="viewer-subtoolbar" hidden>
              <div class="control-item">
                <label for="orb-iso-slider">Orbital Iso</label>
                <input
                  id="orb-iso-slider"
                  type="range"
                  min="0.005"
                  max="0.100"
                  step="0.001"
                  value="0.020"
                />
                <span id="orb-iso-value" class="value-badge">0.020</span>
              </div>

              <div class="control-item">
                <label for="orb-opa-slider">Orbital Opacity</label>
                <input
                  id="orb-opa-slider"
                  type="range"
                  min="0.05"
                  max="1.00"
                  step="0.01"
                  value="0.82"
                />
                <span id="orb-opa-value" class="value-badge">0.82</span>
              </div>
            </div>

            <div id="esp-controls" class="viewer-subtoolbar" hidden>
              <div class="control-item">
                <label for="esp-iso-slider">ESP Density Iso</label>
                <input
                  id="esp-iso-slider"
                  type="range"
                  min="0.0005"
                  max="0.0200"
                  step="0.0005"
                  value="0.001"
                />
                <span id="esp-iso-value" class="value-badge">0.001</span>
              </div>

              <div class="control-item">
                <label for="esp-opa-slider">ESP Opacity</label>
                <input
                  id="esp-opa-slider"
                  type="range"
                  min="0.05"
                  max="1.00"
                  step="0.01"
                  value="0.80"
                />
                <span id="esp-opa-value" class="value-badge">0.80</span>
              </div>

              <div class="control-item">
                <label for="esp-range-slider">ESP Range (±Ha)</label>
                <input
                  id="esp-range-slider"
                  type="range"
                  min="0.005"
                  max="0.300"
                  step="0.001"
                  value="0.050"
                />
                <span id="esp-range-value" class="value-badge">0.050</span>
              </div>

              <div class="control-item">
                <label for="sel-esp">ESP Preset</label>
                <select id="sel-esp" class="tool-select" aria-label="ESP preset">
                  <option value="rwb">Red-White-Blue</option>
                  <option value="bwr">Blue-White-Red</option>
                  <option value="viridis">Viridis</option>
                  <option value="inferno">Inferno</option>
                  <option value="spectral">Spectral</option>
                  <option value="nature">Nature Chemistry</option>
                  <option value="acs">ACS/JACS</option>
                  <option value="rsc">RSC</option>
                  <option value="greyscale">Greyscale</option>
                  <option value="high_contrast">High Contrast</option>
                </select>
              </div>
            </div>

            <div id="v3d" class="viewer-canvas" aria-label="3D molecule viewer"></div>
          </section>
        </section>

        <!-- RIGHT: Results + Chat -->
        <section class="side-panel">
          <section id="results-console" class="panel-card results-console">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Results</h2>
                <p class="panel-subtitle">
                  Normalized result contract, tabs, job summaries, and raw JSON
                </p>
              </div>
            </div>

            <div id="result-tabs" class="result-tabs"></div>

            <div id="result-content" class="result-content">
              <div class="empty-state">
                결과 데이터가 없습니다. 아래 채팅창에서 계산을 요청해 보세요.
              </div>
            </div>

            <div class="job-events-card">
              <div class="job-events-title">Job Events</div>
              <div id="jobEvents" class="job-events-list">
                <div class="empty-state">아직 이벤트가 없습니다.</div>
              </div>
            </div>
          </section>

          <section id="chat-panel" class="panel-card chat-panel">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">QCViz Chat</h2>
                <p class="panel-subtitle">
                  Ask for orbital previews, ESP maps, energies, geometry analysis, or partial charges
                </p>
              </div>
              <div id="chatStatus" class="chat-status">채팅 준비 중…</div>
            </div>

            <div id="chatLog" class="chat-log" aria-live="polite"></div>

            <form id="chatForm" class="chat-composer">
              <label for="chatInput" class="sr-only">Chat input</label>
              <textarea
                id="chatInput"
                rows="4"
                placeholder="예: Show HOMO of benzene with B3LYP/def2-SVP&#10;예: Render ESP map for acetone using ACS preset&#10;예: Calculate Mulliken charges for water"
              ></textarea>

              <div class="chat-composer-row">
                <div class="prompt-row">
                  <button
                    type="button"
                    class="prompt-btn"
                    data-prompt="Show HOMO of benzene with B3LYP/def2-SVP"
                  >
                    HOMO of benzene
                  </button>
                  <button
                    type="button"
                    class="prompt-btn"
                    data-prompt="Render ESP map for acetone using ACS preset"
                  >
                    ESP of acetone
                  </button>
                  <button
                    type="button"
                    class="prompt-btn"
                    data-prompt="Calculate Mulliken charges for water"
                  >
                    Charges of water
                  </button>
                  <button
                    type="button"
                    class="prompt-btn"
                    data-prompt="Analyze bond lengths and angles of caffeine"
                  >
                    Geometry of caffeine
                  </button>
                </div>

                <button type="submit" id="chatSend" class="send-btn">
                  Send
                </button>
              </div>
            </form>
          </section>
        </section>
      </section>
    </main>

    <div class="footer-note">
      QCViz-MCP frontend wired for viewer.js, results.js, chat.js, /ws/chat, and /compute/jobs.
    </div>
  </div>

  <noscript>
    <div style="padding:16px; color:#b91c1c; font-weight:700;">
      This page requires JavaScript to render the viewer and connect the chat/compute pipeline.
    </div>
  </noscript>

  <script>
    // 필요하면 서버/템플릿에서 이 값만 덮어써도 됨.
    window.QCVIZ_WS_PATH = window.QCVIZ_WS_PATH || "/ws/chat";

    // 상단 WebSocket 상태 pill 보조 표시
    (function () {
      const el = document.getElementById("top-ws-state");
      if (!el) return;
      el.textContent = window.QCVIZ_WS_PATH || "/ws/chat";
    })();
  </script>

  <!-- 3Dmol.js -->
  <script src="https://3dmol.org/build/3Dmol-min.js"></script>

  <!-- QCViz frontend modules -->
  <script src="/static/viewer.js"></script>
  <script src="/static/results.js"></script>
  <script src="/static/chat.js"></script>
</body>
</html>
```

### `version02/src/qcviz_mcp/web/static/style.css`
```css
/* ─────────────────────────────────────────────
   QCViz Enterprise Web — style.css
   Scientific SaaS + Minimal Enterprise Dashboard
   CSS-only redesign for existing HTML/JS
   ───────────────────────────────────────────── */

/* ── Design Tokens ─────────────────────────── */
:root {
  /* ── 배경 계층 (Surface Hierarchy) ── */
  --bg-app: #f1f5fb;
  --bg-app-gradient: radial-gradient(ellipse at top left, rgba(79, 70, 229, 0.07), transparent 40%),
                     radial-gradient(ellipse at bottom right, rgba(2, 132, 199, 0.05), transparent 35%),
                     linear-gradient(180deg, #f8fbff 0%, #f1f5fb 100%);
  --surface-0: rgba(255, 255, 255, 0.85);
  --surface-1: #ffffff;
  --surface-2: #f8fbff;
  --surface-3: linear-gradient(180deg, #f0f4ff 0%, #e8eeff 100%);

  /* ── 텍스트 ── */
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --text-on-brand: #ffffff;

  /* ── 브랜드 (Indigo 계열) ── */
  --brand: #4f46e5;
  --brand-hover: #4338ca;
  --brand-strong: #3730a3;
  --brand-muted: #e0e7ff;
  --brand-subtle: #eef2ff;

  /* ── 보조 액센트 (Cyan/Sky) ── */
  --accent: #0284c7;
  --accent-hover: #0369a1;
  --accent-muted: #e0f2fe;
  --accent-subtle: #f0f9ff;

  /* ── 상태색 (Status) ── */
  --success: #16a34a;
  --success-bg: #f0fdf4;
  --success-border: #bbf7d0;
  --warning: #d97706;
  --warning-bg: #fffbeb;
  --warning-border: #fde68a;
  --danger: #dc2626;
  --danger-bg: #fef2f2;
  --danger-border: #fecaca;
  --info: #0284c7;
  --info-bg: #f0f9ff;
  --info-border: #bae6fd;

  /* ── 보더 & 구분선 ── */
  --border: #dbe4f0;
  --border-strong: #c7d2fe;
  --border-subtle: #e8edf5;
  --divider: rgba(148, 163, 184, 0.18);

  /* ── 그림자 ── */
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
  --shadow-lg: 0 18px 40px rgba(15, 23, 42, 0.08), 0 6px 16px rgba(15, 23, 42, 0.04);
  --shadow-brand: 0 4px 14px rgba(79, 70, 229, 0.25);

  /* ── 라운딩 ── */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-full: 9999px;

  /* ── 트랜지션 ── */
  --ease-out: cubic-bezier(.2, .8, .2, 1);
  --duration-fast: 150ms;
  --duration-normal: 220ms;
  --duration-slow: 320ms;

  /* ── 타이포그래피 ── */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-base: 14px;
  --font-size-md: 15px;
  --font-size-lg: 18px;
  --font-size-xl: 22px;
  --font-size-2xl: 28px;

  /* ── Supplemental tokens ── */
  --transparent: transparent;
  --focus-ring: rgba(79, 70, 229, 0.15);
  --focus-ring-strong: rgba(79, 70, 229, 0.12);
  --surface-overlay: rgba(255, 255, 255, 0.72);
  --surface-overlay-strong: rgba(248, 251, 255, 0.84);
  --pulse-shadow-success: rgba(22, 163, 74, 0.22);
  --pulse-shadow-brand: rgba(79, 70, 229, 0.18);
  --scrollbar-thumb: #dbe4f0;
  --scrollbar-thumb-hover: #cbd5e1;
  --scrollbar-track: transparent;
  --code-bg: #0f172a;
  --code-border: #334155;
  --code-text: #e2e8f0;
  --code-muted: #94a3b8;
  --code-button-bg: rgba(255, 255, 255, 0.08);
  --code-button-border: rgba(255, 255, 255, 0.14);
  --code-button-hover: rgba(255, 255, 255, 0.16);
  --selection-bg: #e0e7ff;
  --selection-text: #312e81;
}

/* ── Reset / Base ─────────────────────────── */
*,
*::before,
*::after {
  box-sizing: border-box;
}

html {
  font-size: 16px;
  scroll-behavior: smooth;
}

html,
body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  font-family: var(--font-sans);
  background: var(--bg-app-gradient);
  color: var(--text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body {
  min-height: 100vh;
}

img,
svg,
canvas {
  display: block;
  max-width: 100%;
}

button,
input,
select,
textarea {
  font: inherit;
  color: inherit;
}

a {
  color: inherit;
  text-decoration: none;
}

::selection {
  background: var(--selection-bg);
  color: var(--selection-text);
}

:focus {
  outline: none;
}

:focus-visible {
  box-shadow: 0 0 0 3px var(--focus-ring);
  border-color: var(--brand);
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: var(--radius-full);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

hr {
  border: 0;
  border-top: 1px solid var(--divider);
  margin: 16px 0;
}

/* ── Typography ───────────────────────────── */
h1,
h2,
h3,
h4,
h5,
h6 {
  margin: 0;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

p {
  margin: 0;
  color: var(--text-secondary);
}

small,
.text-muted {
  color: var(--text-muted);
}

code,
pre,
.code-block,
.mono,
.result-mono,
.numeric {
  font-family: var(--font-mono);
}

/* ── App Shell / Layout ───────────────────── */
.app-shell,
.workspace,
.layout-container,
.main-area {
  width: 100%;
  min-height: 100vh;
}

.app-shell {
  padding: 18px;
  background: var(--transparent);
}

.workspace,
.layout-container,
.main-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--transparent);
}

.content-row {
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr) minmax(360px, 420px);
  gap: 16px;
  align-items: stretch;
  min-height: calc(100vh - 120px);
}

.content-row > * {
  min-width: 0;
  min-height: 0;
}

/* ── Panel / Card Primitives ──────────────── */
.panel,
.card,
.chat-shell,
.result-shell,
.viewer-shell {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.panel,
.card,
.chat-shell,
.result-shell,
.viewer-shell {
  position: relative;
  overflow: hidden;
}

.chat-shell,
.result-shell,
.viewer-shell {
  display: flex;
  flex-direction: column;
}

.panel,
.card {
  padding: 16px;
}

.panel-title,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.result-card,
.metric-card,
.kpi-card,
.result-section,
.score-card,
.callout {
  background: linear-gradient(180deg, var(--surface-1) 0%, var(--surface-2) 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 16px 18px;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.result-card:hover,
.metric-card:hover,
.kpi-card:hover,
.result-section:hover,
.card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.result-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
}

.result-section-head h3,
.result-section-head h4 {
  font-size: var(--font-size-sm);
  font-weight: 700;
  color: var(--text-primary);
}

.result-subtitle,
.section-subtitle,
.result-caption {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ── Generic Grids / Lists ────────────────── */
.kpi-grid,
.metrics-grid,
.result-grid,
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.stack,
.result-stack,
.info-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pill-row,
.badge-row,
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list,
.warning-list,
.recommendation-list,
.result-list,
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
  color: var(--text-secondary);
}

.list li,
.warning-list li,
.recommendation-list li,
.result-list li {
  color: var(--text-secondary);
}

dl,
.definition-list {
  display: grid;
  grid-template-columns: minmax(0, 140px) minmax(0, 1fr);
  gap: 8px 12px;
  margin: 0;
}

dt {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

dd {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  font-family: var(--font-mono);
}

/* ── Status / Badges ──────────────────────── */
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--success);
  box-shadow: 0 0 0 0 var(--pulse-shadow-success);
  animation: qcviz-pulse 2s infinite;
  flex: 0 0 auto;
}

.status-dot.is-info {
  background: var(--info);
  box-shadow: 0 0 0 0 var(--pulse-shadow-brand);
}

.status-dot.is-warning {
  background: var(--warning);
  box-shadow: none;
  animation: none;
}

.status-dot.is-danger {
  background: var(--danger);
  box-shadow: none;
  animation: none;
}

.status-text {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.badge,
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-secondary);
  white-space: nowrap;
}

.badge::before,
.status-badge::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  flex: 0 0 auto;
}

.badge-success,
.status-success,
.badge.is-success {
  background: var(--success-bg);
  color: var(--success);
  border-color: var(--success-border);
}

.badge-warning,
.status-warning,
.badge.is-warning {
  background: var(--warning-bg);
  color: var(--warning);
  border-color: var(--warning-border);
}

.badge-danger,
.status-error,
.status-danger,
.badge.is-danger,
.badge.is-error {
  background: var(--danger-bg);
  color: var(--danger);
  border-color: var(--danger-border);
}

.badge-info,
.status-info,
.badge.is-info {
  background: var(--info-bg);
  color: var(--info);
  border-color: var(--info-border);
}

/* ── Buttons ──────────────────────────────── */
.btn,
button,
.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-secondary);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.btn:hover,
button:hover,
.copy-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
  transform: translateY(-0.5px);
}

.btn:active,
button:active,
.copy-btn:active {
  transform: translateY(0.5px);
  box-shadow: var(--shadow-xs);
}

.btn:disabled,
button:disabled,
.copy-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: var(--shadow-xs);
}

.btn-primary,
button.btn-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
}

.btn-primary:hover,
button.btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-brand);
}

.btn-secondary,
button.btn-secondary {
  background: var(--surface-1);
  border-color: var(--border);
  color: var(--text-secondary);
}

.btn-secondary:hover,
button.btn-secondary:hover {
  border-color: var(--brand-muted);
  color: var(--brand);
}

.btn-ghost,
button.btn-ghost {
  background: var(--transparent);
  border-color: var(--transparent);
  color: var(--text-muted);
  box-shadow: none;
}

.btn-ghost:hover,
button.btn-ghost:hover {
  background: var(--brand-subtle);
  border-color: var(--brand-muted);
  color: var(--brand);
  box-shadow: none;
}

.copy-btn {
  padding: 6px 10px;
  font-size: var(--font-size-xs);
  font-weight: 600;
}

/* ── Inputs / Controls ────────────────────── */
input,
select,
textarea {
  width: 100%;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 10px 12px;
  box-shadow: var(--shadow-xs);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

input::placeholder,
textarea::placeholder {
  color: var(--text-muted);
}

input:hover,
select:hover,
textarea:hover {
  border-color: var(--border-strong);
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--focus-ring-strong);
}

textarea {
  min-height: 108px;
  resize: vertical;
}

label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.chat-input,
.composer,
.advanced-controls,
.toolbar,
.control-row,
.form-row,
.field-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.control-row,
.form-row,
.field-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.composer .btn,
.chat-input .btn,
.toolbar .btn,
.toolbar button,
.toolbar select {
  min-height: 38px;
}

/* ── Chat Shell ───────────────────────────── */
.chat-shell {
  padding: 16px;
  gap: 14px;
}

.chat-shell .panel-title,
.chat-shell .card-header {
  margin-bottom: 0;
}

.chat-messages {
  flex: 1 1 auto;
  min-height: 320px;
  max-height: calc(100vh - 300px);
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.chat-messages .message,
.chat-messages .chat-message,
.chat-messages .msg,
.chat-messages [data-role],
.chat-messages .bubble {
  max-width: 92%;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
  word-break: break-word;
  animation: qcviz-fade-up var(--duration-normal) var(--ease-out);
}

.chat-messages .message.user,
.chat-messages .chat-message.user,
.chat-messages .msg.user,
.chat-messages [data-role="user"],
.chat-messages .bubble.user {
  margin-left: auto;
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
  border-radius: var(--radius-md) var(--radius-md) 4px var(--radius-md);
  box-shadow: var(--shadow-brand);
}

.chat-messages .message.assistant,
.chat-messages .message.system,
.chat-messages .chat-message.assistant,
.chat-messages .chat-message.system,
.chat-messages .msg.assistant,
.chat-messages .msg.system,
.chat-messages [data-role="assistant"],
.chat-messages [data-role="system"],
.chat-messages .bubble.assistant,
.chat-messages .bubble.system {
  margin-right: auto;
  background: var(--surface-2);
  border-color: var(--border-subtle);
  color: var(--text-primary);
  border-radius: var(--radius-md) var(--radius-md) var(--radius-md) 4px;
}

.chat-messages .message .meta,
.chat-messages .chat-message .meta,
.chat-messages .timestamp {
  margin-top: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.composer {
  border-top: 1px solid var(--divider);
  padding-top: 12px;
}

/* ── Quick Prompts / Chips ────────────────── */
.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip,
.quick-prompt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 500;
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.chip:hover,
.quick-prompt:hover {
  background: var(--brand-subtle);
  border-color: var(--brand-muted);
  color: var(--brand);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.chip:active,
.quick-prompt:active {
  transform: translateY(0.5px);
}

/* ── Viewer ───────────────────────────────── */
.viewer-shell {
  padding: 16px;
  gap: 12px;
}

.viewer-shell .panel-title,
.viewer-shell .card-header {
  margin-bottom: 0;
}

.toolbar {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.viewer-container {
  position: relative;
  flex: 1 1 auto;
  min-height: 560px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  background: var(--surface-1);
}

#v3d {
  width: 100%;
  height: 100%;
  min-height: 560px;
  border-radius: inherit;
  background: var(--surface-1);
  position: relative;
}

.viewer-container canvas,
#v3d canvas {
  width: 100%;
  height: 100%;
}

.viewer-overlay {
  position: absolute;
  inset: 12px 12px auto 12px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  pointer-events: none;
  z-index: 3;
}

.viewer-overlay > * {
  pointer-events: auto;
}

.viewer-overlay .badge,
.viewer-overlay .status-badge,
.viewer-overlay .panel,
.viewer-overlay .card {
  background: var(--surface-overlay-strong);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.viewer-shell .toolbar .btn,
.viewer-shell .toolbar button,
.viewer-shell .toolbar select {
  border-radius: var(--radius-full);
}

/* ── Result Shell ─────────────────────────── */
.result-shell {
  padding: 16px;
  gap: 12px;
}

.result-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
  scrollbar-width: none;
}

.result-tabs::-webkit-scrollbar {
  display: none;
}

.tab-btn,
.result-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 34px;
  padding: 8px 14px;
  border: 1px solid var(--transparent);
  border-radius: var(--radius-full);
  background: var(--transparent);
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: none;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.tab-btn:hover,
.result-tab:hover {
  color: var(--text-secondary);
  border-color: var(--border);
  background: var(--surface-1);
}

.tab-btn.active,
.result-tab.active,
.tab-btn[aria-selected="true"],
.result-tab[aria-selected="true"] {
  background: var(--surface-3);
  color: var(--brand-strong);
  border-color: var(--border-strong);
  box-shadow: inset 0 0 0 1px var(--focus-ring-strong);
  font-weight: 600;
}

.result-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.result-content > * + * {
  margin-top: 12px;
}

.result-content h2,
.result-content h3,
.result-content h4 {
  margin-bottom: 8px;
}

.result-content p + p {
  margin-top: 10px;
}

.metric-card .value,
.kpi-card .value,
.result-kpi-value,
.metric-value,
.kpi-value {
  font-family: var(--font-mono);
  font-size: var(--font-size-xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.03em;
}

.metric-card .label,
.kpi-card .label,
.result-kpi-label,
.metric-label,
.kpi-label {
  font-size: var(--font-size-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

/* ── Tables / Structured Data ─────────────── */
table,
.result-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
}

thead th {
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

th,
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  font-size: var(--font-size-sm);
}

tbody tr:last-child td {
  border-bottom: 0;
}

tbody td {
  color: var(--text-secondary);
}

tbody td.numeric,
tbody td.value,
tbody td code {
  font-family: var(--font-mono);
  color: var(--text-primary);
}

/* ── Callouts / Notes / Alerts ────────────── */
.callout,
.notice,
.warning-box,
.info-box,
.success-box,
.error-box {
  border-left: 4px solid var(--info);
  background: var(--info-bg);
  border-color: var(--info-border);
  color: var(--text-primary);
}

.callout-warning,
.warning-box,
.notice-warning {
  border-left-color: var(--warning);
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.callout-danger,
.error-box,
.notice-danger {
  border-left-color: var(--danger);
  background: var(--danger-bg);
  border-color: var(--danger-border);
}

.callout-success,
.success-box,
.notice-success {
  border-left-color: var(--success);
  background: var(--success-bg);
  border-color: var(--success-border);
}

/* ── Progress ─────────────────────────────── */
.progress-track,
.progress-bar,
.progress {
  width: 100%;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--border-subtle);
  overflow: hidden;
  position: relative;
}

.progress-fill,
.progress-value,
.progress > span {
  display: block;
  height: 100%;
  width: 0%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--brand), var(--accent));
  transition: width var(--duration-slow) var(--ease-out);
}

.progress-fill::after,
.progress-value::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, var(--transparent), var(--surface-overlay), var(--transparent));
  animation: qcviz-shimmer 1.8s linear infinite;
}

.progress-meta,
.progress-label,
.progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

/* ── Scores / Confidence Bars ─────────────── */
.score-grid,
.confidence-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.score-bar {
  width: 100%;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--border-subtle);
  overflow: hidden;
}

.score-fill {
  height: 100%;
  width: 0%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--brand), var(--accent));
}

.score-label,
.confidence-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.score-value,
.confidence-value {
  font-family: var(--font-mono);
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--text-primary);
}

/* ── Code Blocks ──────────────────────────── */
pre,
.code-block {
  position: relative;
  margin: 0;
  padding: 16px 20px;
  border-radius: var(--radius-md);
  background: var(--code-bg);
  color: var(--code-text);
  border: 1px solid var(--code-border);
  overflow-x: auto;
  box-shadow: var(--shadow-sm);
}

pre code,
.code-block code {
  display: block;
  padding: 0;
  background: var(--transparent);
  border: 0;
  color: inherit;
  font-size: var(--font-size-sm);
  line-height: 1.7;
}

code {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--brand-subtle);
  color: var(--brand-strong);
  font-size: 0.95em;
}

pre code,
.code-block code {
  background: var(--transparent);
  color: inherit;
}

.code-block .copy-btn,
pre .copy-btn,
.code-toolbar .copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  min-height: 30px;
  padding: 6px 10px;
  background: var(--code-button-bg);
  border-color: var(--code-button-border);
  color: var(--code-muted);
  box-shadow: none;
}

.code-block .copy-btn:hover,
pre .copy-btn:hover,
.code-toolbar .copy-btn:hover {
  background: var(--code-button-hover);
  border-color: var(--code-button-border);
  color: var(--surface-1);
  box-shadow: none;
}

/* ── JSON / Jobs / Event Stream ───────────── */
.json-view,
.json-block,
pre.json {
  white-space: pre-wrap;
  word-break: break-word;
}

#jobEvents,
.job-events,
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
  padding-right: 4px;
}

.job-event,
.job-item,
.event-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  box-shadow: var(--shadow-xs);
}

.job-event .time,
.job-item .time,
.event-item .time {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.empty-state,
.result-empty,
.placeholder-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  justify-content: center;
  min-height: 120px;
  padding: 18px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  color: var(--text-secondary);
}

/* ── Accordion / Advanced Controls ────────── */
.advanced-controls {
  border-top: 1px solid var(--divider);
  padding-top: 12px;
}

.accordion-trigger,
.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 0;
  border: 0;
  background: var(--transparent);
  color: var(--text-muted);
  box-shadow: none;
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
}

.accordion-trigger:hover,
.advanced-toggle:hover {
  color: var(--brand);
  background: var(--transparent);
  box-shadow: none;
  transform: none;
}

.accordion-trigger[aria-expanded="true"],
.advanced-toggle[aria-expanded="true"],
.advanced-toggle.is-open {
  color: var(--brand);
}

.accordion-content {
  overflow: hidden;
  transition: max-height var(--duration-normal) var(--ease-out),
              opacity var(--duration-fast) var(--ease-out),
              padding var(--duration-fast) var(--ease-out);
  padding-top: 12px;
}

.accordion-content[hidden] {
  display: none;
}

/* ── Toast Notifications ──────────────────── */
.toast-root,
#qcviz-toast-root {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 1100;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast-root > *,
#qcviz-toast-root > * {
  pointer-events: auto;
}

.toast {
  min-width: 280px;
  max-width: 420px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  border-left: 4px solid var(--info);
  background: var(--surface-0);
  color: var(--text-primary);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  animation: qcviz-toast-in 220ms var(--ease-out);
}

.toast.is-success,
.toast.toast-success,
.toast[data-type="success"] {
  border-left-color: var(--success);
}

.toast.is-warning,
.toast.toast-warning,
.toast[data-type="warning"] {
  border-left-color: var(--warning);
}

.toast.is-danger,
.toast.is-error,
.toast.toast-error,
.toast[data-type="error"] {
  border-left-color: var(--danger);
}

.toast.is-info,
.toast.toast-info,
.toast[data-type="info"] {
  border-left-color: var(--info);
}

.toast.is-leaving {
  animation: qcviz-toast-out 180ms ease forwards;
}

/* ── Utility Helpers ──────────────────────── */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

.text-right {
  text-align: right;
}

.text-center {
  text-align: center;
}

.hidden {
  display: none;
}

/* ── Animations ───────────────────────────── */
@keyframes qcviz-pulse {
  0% {
    box-shadow: 0 0 0 0 var(--pulse-shadow-success);
  }
  70% {
    box-shadow: 0 0 0 10px var(--transparent);
  }
  100% {
    box-shadow: 0 0 0 0 var(--transparent);
  }
}

@keyframes qcviz-fade-up {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes qcviz-shimmer {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(100%);
  }
}

@keyframes qcviz-toast-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes qcviz-toast-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(8px) scale(.985);
  }
}

/* ── Responsive: Tablet ───────────────────── */
@media (max-width: 1024px) {
  .app-shell {
    padding: 14px;
  }

  .content-row {
    grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  }

  .result-shell {
    grid-column: 1 / -1;
  }

  .viewer-container,
  #v3d {
    min-height: 500px;
  }
}

/* ── Responsive: Mobile / Narrow ──────────── */
@media (max-width: 768px) {
  .app-shell {
    padding: 12px;
  }

  .content-row {
    display: flex;
    flex-direction: column;
  }

  .viewer-shell {
    order: 1;
  }

  .result-shell {
    order: 2;
  }

  .chat-shell {
    order: 3;
  }

  .chat-messages {
    max-height: 340px;
  }

  .viewer-container,
  #v3d {
    min-height: 420px;
  }

  .result-tabs {
    padding-bottom: 6px;
  }

  .toast-root,
  #qcviz-toast-root {
    top: auto;
    right: 12px;
    left: 12px;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  }

  .toast {
    min-width: 0;
    max-width: none;
    width: 100%;
  }
}

/* ── Responsive: Compact Mobile ───────────── */
@media (max-width: 640px) {
  :root {
    --font-size-base: 13px;
    --font-size-md: 14px;
    --font-size-lg: 17px;
    --font-size-xl: 20px;
    --font-size-2xl: 24px;
  }

  .panel,
  .card,
  .chat-shell,
  .result-shell,
  .viewer-shell,
  .result-card,
  .metric-card,
  .kpi-card,
  .result-section {
    border-radius: var(--radius-sm);
  }

  .chat-shell,
  .result-shell,
  .viewer-shell,
  .panel,
  .card {
    padding: 12px;
  }

  .result-card,
  .metric-card,
  .kpi-card,
  .result-section,
  .callout {
    padding: 14px;
  }

  .control-row,
  .form-row,
  .field-row,
  .kpi-grid,
  .metrics-grid,
  .result-grid,
  .card-grid,
  .score-grid,
  .confidence-grid {
    grid-template-columns: 1fr;
  }

  .tab-btn,
  .result-tab {
    padding: 8px 12px;
  }

  .viewer-container,
  #v3d {
    min-height: 340px;
  }

  .toast-root,
  #qcviz-toast-root {
    left: 12px;
    right: 12px;
    top: auto;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  }
}

/* ── Reduced Motion ───────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}

/* ── QCViz-MCP Enterprise Web Classes Mapping ── */

.app-shell-enterprise {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-app-gradient);
}

.enterprise-header {
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  background: var(--surface-overlay);
  border-bottom: 1px solid var(--divider);
}

.enterprise-header-inner {
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--brand), var(--accent));
  color: white;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  box-shadow: var(--shadow-brand);
}

.brand-title {
  font-weight: 700;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.brand-badge {
  background: var(--brand-subtle);
  color: var(--brand-strong);
  border: 1px solid var(--brand-muted);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 800;
}

.brand-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.enterprise-main {
  padding: 18px;
  flex: 1 1 auto;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

.enterprise-grid {
  display: grid;
  grid-template-columns: minmax(360px, 420px) minmax(0, 1fr);
  gap: 18px;
}

.enterprise-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.enterprise-card {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.enterprise-card-header {
  padding: 18px 18px 14px;
  border-bottom: 1px solid var(--divider);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.enterprise-card-title {
  font-size: var(--font-size-md);
  font-weight: 800;
  color: var(--text-primary);
  margin: 0;
}

.enterprise-card-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  margin-top: 4px;
}

.enterprise-card-body {
  padding: 16px 18px 18px;
  flex: 1 1 auto;
  overflow: auto;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.header-action {
  background: var(--surface-1);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius-md);
  font-weight: 600;
  padding: 8px 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.header-action.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-brand);
}

.header-action:hover {
  border-color: var(--brand-muted);
  color: var(--brand);
  background: var(--brand-subtle);
}

.header-action.primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: white;
}

.chat-log-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--surface-2);
  border-radius: var(--radius-md);
  min-height: 400px;
  max-height: 600px;
  overflow-y: auto;
}

.msg {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  max-width: 92%;
  margin-bottom: 12px;
  box-shadow: var(--shadow-xs);
  font-size: var(--font-size-sm);
  word-break: break-word;
}

.msg.bot {
  background: var(--surface-1);
  color: var(--text-primary);
  margin-right: auto;
}

.msg.user {
  background: var(--brand);
  color: var(--text-on-brand);
  border-color: var(--brand);
  margin-left: auto;
}

.chat-composer {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-chip {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  text-align: left;
  transition: all var(--duration-fast) var(--ease-out);
  cursor: pointer;
  display: flex;
  flex-direction: column;
}

.quick-chip:hover {
  border-color: var(--brand);
  background: var(--brand-subtle);
  transform: translateY(-1px);
}

.quick-chip-title {
  font-weight: 700;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.quick-chip-desc {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.composer-box {
  display: flex;
  gap: 10px;
  position: relative;
}

.composer-textarea {
  flex: 1 1 auto;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 12px 48px 12px 14px;
  box-shadow: var(--shadow-xs);
  resize: none;
  min-height: 46px;
  max-height: 200px;
  outline: none;
}

.composer-textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--focus-ring-strong);
}

.composer-submit {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 32px;
  height: 32px;
  background: var(--brand);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.composer-submit:hover {
  background: var(--brand-hover);
}

.viewer-stage-shell {
  height: 560px;
  background: white;
  position: relative;
  overflow: hidden;
}

#viewer {
  width: 100%;
  height: 100%;
}

.viewer-actions {
  display: flex;
  gap: 8px;
}

.viewer-style-select {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  font-size: var(--font-size-xs);
  font-weight: 600;
  background: var(--surface-1);
}

.viewer-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface-1);
  cursor: pointer;
  color: var(--text-secondary);
}

.viewer-btn:hover {
  color: var(--brand);
  border-color: var(--brand-muted);
  background: var(--brand-subtle);
}

/* Results Tab Styling */
.result-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}

.result-tab {
  padding: 8px 16px;
  border-radius: var(--radius-full);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-weight: 700;
  font-size: var(--font-size-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--duration-fast);
}

.result-tab:hover {
  color: var(--text-primary);
  background: var(--surface-2);
}

.result-tab.active {
  background: var(--brand-subtle);
  color: var(--brand-strong);
  border-color: var(--brand-muted);
}

.results-content-shell {
  min-height: 300px;
}

/* Toast root mapping */
.qcviz-toast-root {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}


/* ── QCViz Viewer / Results Patch Tokens ───────────────────────────── */
:root {
  --qv-line: rgba(148, 163, 184, 0.24);
  --qv-line-strong: rgba(148, 163, 184, 0.38);
  --qv-surface: #ffffff;
  --qv-surface-soft: #f8fbff;
  --qv-surface-tint: #f1f6ff;
  --qv-text: #0f172a;
  --qv-muted: #64748b;
  --qv-primary: #2563eb;
  --qv-primary-strong: #1d4ed8;
  --qv-success: #059669;
  --qv-warn: #d97706;
  --qv-danger: #dc2626;
  --qv-radius-sm: 10px;
  --qv-radius-md: 14px;
  --qv-radius-lg: 18px;
  --qv-shadow-sm: 0 6px 18px rgba(15, 23, 42, 0.05);
  --qv-shadow-md: 0 14px 36px rgba(15, 23, 42, 0.08);
  --qv-shadow-lg: 0 24px 56px rgba(15, 23, 42, 0.12);
}

/* ── Viewer Toolbar ───────────────────────────────────────────────── */
.viewer-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 0 0 12px;
  padding: 12px 14px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-lg);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 251, 255, 0.94));
  box-shadow: var(--qv-shadow-md);
  backdrop-filter: blur(10px);
}

.toolbar-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.toolbar-group-right {
  margin-left: auto;
}

.toolbar-label {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--qv-surface-tint);
  border: 1px solid rgba(37, 99, 235, 0.12);
  color: var(--qv-primary-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

/* ── Toolbar Controls ─────────────────────────────────────────────── */
.control-inline {
  display: grid;
  grid-template-columns: auto minmax(112px, 168px) auto;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 7px 10px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: var(--qv-surface);
  color: var(--qv-text);
  box-shadow: var(--qv-shadow-sm);
}

.control-inline > span:first-child {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.control-value {
  min-width: 44px;
  text-align: right;
  color: var(--qv-text);
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.viewer-toolbar input[type="range"] {
  width: 100%;
  accent-color: var(--qv-primary);
  cursor: pointer;
}

.viewer-toolbar select {
  height: 36px;
  min-width: 152px;
  padding: 0 12px;
  border: 1px solid var(--qv-line-strong);
  border-radius: 10px;
  background: var(--qv-surface);
  color: var(--qv-text);
  font: inherit;
  box-shadow: var(--qv-shadow-sm);
}

.viewer-toolbar select:focus,
.viewer-toolbar input[type="range"]:focus,
.viewer-toolbar .btn:focus {
  outline: none;
}

.viewer-toolbar select:focus-visible,
.viewer-toolbar .btn:focus-visible {
  box-shadow:
    0 0 0 3px rgba(37, 99, 235, 0.16),
    var(--qv-shadow-sm);
}

/* ── Toolbar Buttons ──────────────────────────────────────────────── */
.viewer-toolbar .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 36px;
  padding: 0 13px;
  border: 1px solid var(--qv-line-strong);
  border-radius: 10px;
  background: var(--qv-surface);
  color: var(--qv-text);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    background-color 0.16s ease,
    color 0.16s ease;
}

.viewer-toolbar .btn:hover {
  transform: translateY(-1px);
  border-color: rgba(37, 99, 235, 0.26);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.10);
}

.viewer-toolbar .btn:active {
  transform: translateY(0);
}

.viewer-toolbar .btn-primary {
  border-color: rgba(37, 99, 235, 0.22);
  background: linear-gradient(180deg, #3775ff, #2563eb);
  color: #fff;
}

.viewer-toolbar .btn-primary:hover {
  border-color: rgba(29, 78, 216, 0.35);
  background: linear-gradient(180deg, #3b82f6, #1d4ed8);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.22);
}

.viewer-toolbar .btn-secondary {
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-text);
}

.viewer-toolbar .btn.is-active,
.viewer-toolbar .btn[aria-pressed="true"] {
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.14), rgba(37, 99, 235, 0.08));
  color: var(--qv-primary-strong);
}

/* ── Viewer Status ───────────────────────────────────────────────── */
.viz-status {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  margin: 0 0 14px;
  padding: 10px 14px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-md);
  background: var(--qv-surface-soft);
  color: var(--qv-muted);
  box-shadow: var(--qv-shadow-sm);
  font-size: 13px;
  font-weight: 500;
}

.viz-status::before {
  content: "";
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.45);
  box-shadow: 0 0 0 4px rgba(100, 116, 139, 0.10);
  flex: 0 0 auto;
}

.viz-status[data-tone="ok"] {
  color: #065f46;
  border-color: rgba(5, 150, 105, 0.18);
  background: rgba(236, 253, 245, 0.92);
}
.viz-status[data-tone="ok"]::before {
  background: var(--qv-success);
  box-shadow: 0 0 0 4px rgba(5, 150, 105, 0.14);
}

.viz-status[data-tone="warn"] {
  color: #92400e;
  border-color: rgba(217, 119, 6, 0.18);
  background: rgba(255, 251, 235, 0.96);
}
.viz-status[data-tone="warn"]::before {
  background: var(--qv-warn);
  box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.14);
}

.viz-status[data-tone="error"] {
  color: #991b1b;
  border-color: rgba(220, 38, 38, 0.18);
  background: rgba(254, 242, 242, 0.96);
}
.viz-status[data-tone="error"]::before {
  background: var(--qv-danger);
  box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.14);
}

/* ── Result Tabs ─────────────────────────────────────────────────── */
.result-tabs,
#result-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 14px;
  padding: 0;
}

.result-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease,
    background-color 0.16s ease;
  box-shadow: var(--qv-shadow-sm);
}

.result-tab:hover {
  transform: translateY(-1px);
  color: var(--qv-text);
  border-color: rgba(37, 99, 235, 0.20);
}

.result-tab.is-active {
  color: #fff;
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(180deg, #3b82f6, #2563eb);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.20);
}

/* ── Result Cards / Layout ───────────────────────────────────────── */
.result-content,
#result-content {
  display: grid;
  gap: 14px;
}

.result-card {
  position: relative;
  overflow: hidden;
  padding: 16px 18px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-lg);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.96));
  box-shadow: var(--qv-shadow-md);
}

.result-card::after {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, rgba(37, 99, 235, 0), rgba(37, 99, 235, 0.22), rgba(37, 99, 235, 0));
  pointer-events: none;
}

.result-card-title {
  margin: 0 0 10px;
  color: var(--qv-text);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.card-subtitle {
  margin: -2px 0 12px;
  color: var(--qv-muted);
  font-size: 13px;
  line-height: 1.55;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.summary-grid > div {
  padding: 12px 13px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: rgba(241, 246, 255, 0.54);
  color: var(--qv-text);
  line-height: 1.55;
}

.summary-grid strong {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

/* ── Metrics ─────────────────────────────────────────────────────── */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  padding: 14px;
  border: 1px solid var(--qv-line);
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.08), transparent 42%),
    linear-gradient(180deg, #ffffff, #f8fbff);
  box-shadow: var(--qv-shadow-sm);
}

.metric-label {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.metric-value {
  margin-top: 8px;
  color: var(--qv-text);
  font-size: 20px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

/* ── Chips / Quick Actions ───────────────────────────────────────── */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: #fff;
  color: var(--qv-text);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease;
}

.chip:hover {
  transform: translateY(-1px);
  border-color: rgba(37, 99, 235, 0.22);
  color: var(--qv-primary-strong);
}

.chip.is-disabled,
.chip:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* ── Orbital Chip Grid ───────────────────────────────────────────── */
.orbital-chip-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(188px, 1fr));
  gap: 10px;
}

.orbital-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-height: 72px;
  padding: 12px 14px;
  border: 1px solid var(--qv-line);
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(37, 99, 235, 0.06), transparent 45%),
    linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background-color 0.16s ease;
}

.orbital-chip:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.24);
  box-shadow: 0 16px 34px rgba(37, 99, 235, 0.12);
}

.orbital-chip.is-active {
  border-color: rgba(37, 99, 235, 0.28);
  background:
    radial-gradient(circle at top right, rgba(37, 99, 235, 0.16), transparent 45%),
    linear-gradient(180deg, rgba(239, 246, 255, 0.98), rgba(219, 234, 254, 0.86));
  box-shadow: 0 18px 36px rgba(37, 99, 235, 0.16);
}

.orbital-chip-label {
  color: var(--qv-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.3;
}

.orbital-chip-meta {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ── Inline KV / Notes ───────────────────────────────────────────── */
.inline-kv {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.inline-kv > div {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  background: rgba(241, 246, 255, 0.60);
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
}

.inline-kv strong {
  margin-left: 4px;
  color: var(--qv-text);
}

/* ── Tables ──────────────────────────────────────────────────────── */
.table-wrap {
  width: 100%;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: #fff;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 520px;
  background: #fff;
}

.data-table th,
.data-table td {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  text-align: left;
  vertical-align: middle;
  font-size: 13px;
}

.data-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: rgba(248, 251, 255, 0.98);
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.data-table tbody tr:hover {
  background: rgba(241, 246, 255, 0.56);
}

.data-table td code {
  color: var(--qv-primary-strong);
  font-weight: 700;
}

/* ── Color Swatches ──────────────────────────────────────────────── */
.color-swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.color-swatch {
  width: 18px;
  height: 18px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.24);
}

/* ── Warnings / Empty / Rich Text ───────────────────────────────── */
.warning-card {
  border-color: rgba(217, 119, 6, 0.22);
  background:
    linear-gradient(180deg, rgba(255, 251, 235, 0.98), rgba(255, 247, 237, 0.96));
}

.warning-list,
.bullet-list {
  margin: 0;
  padding-left: 18px;
  color: var(--qv-text);
}

.warning-list li,
.bullet-list li {
  margin: 6px 0;
  line-height: 1.6;
}

.empty-state {
  padding: 16px;
  border: 1px dashed rgba(148, 163, 184, 0.34);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.86);
  color: var(--qv-muted);
  text-align: center;
  font-size: 13px;
  line-height: 1.6;
}

.rich-text {
  color: var(--qv-text);
  line-height: 1.72;
}

/* ── Code Blocks ─────────────────────────────────────────────────── */
.code-block {
  margin: 0;
  overflow: auto;
  padding: 14px 16px;
  border: 1px solid rgba(30, 41, 59, 0.08);
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.08), transparent 34%),
    linear-gradient(180deg, #0f172a, #111827);
  color: #e5eefc;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  font-size: 12.5px;
  line-height: 1.7;
}

.code-block code {
  color: inherit;
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Hidden State Compatibility ──────────────────────────────────── */
[hidden] {
  display: none !important;
}

/* ── Motion Polish ───────────────────────────────────────────────── */
.viewer-toolbar,
.viz-status,
.result-card,
.result-tab,
.chip,
.orbital-chip {
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    border-color 0.18s ease,
    background-color 0.18s ease,
    color 0.18s ease,
    opacity 0.18s ease;
}

/* ── Responsive ≤1024px ─────────────────────────────────────────── */
@media (max-width: 1024px) {
  .viewer-toolbar {
    gap: 10px;
    padding: 12px;
  }

  .toolbar-group,
  .toolbar-group-right {
    width: 100%;
    margin-left: 0;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* ── Responsive ≤768px ──────────────────────────────────────────── */
@media (max-width: 768px) {
  .viewer-toolbar {
    border-radius: 16px;
  }

  .toolbar-group {
    gap: 8px;
  }

  .control-inline {
    grid-template-columns: auto minmax(110px, 1fr) auto;
    width: 100%;
    border-radius: 14px;
  }

  .viewer-toolbar select {
    width: 100%;
    min-width: 0;
  }

  .viewer-toolbar .btn {
    flex: 1 1 auto;
  }

  .orbital-chip-row {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }

  .metric-card,
  .result-card {
    padding: 14px;
  }
}

/* ── Responsive ≤640px ──────────────────────────────────────────── */
@media (max-width: 640px) {
  .viewer-toolbar {
    gap: 10px;
    padding: 10px;
    margin-bottom: 10px;
  }

  .toolbar-group {
    width: 100%;
  }

  .toolbar-label {
    width: 100%;
    justify-content: center;
    border-radius: 12px;
  }

  .control-inline {
    grid-template-columns: auto 1fr auto;
    width: 100%;
    min-height: 40px;
    padding: 8px 10px;
    border-radius: 12px;
  }

  .viewer-toolbar .btn,
  .chip,
  .result-tab {
    min-height: 40px;
  }

  .toolbar-group-right .btn,
  .viewer-toolbar .btn {
    flex: 1 1 calc(50% - 5px);
  }

  .viz-status {
    margin-bottom: 12px;
    padding: 10px 12px;
  }

  .result-tabs,
  #result-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: thin;
  }

  .result-tab {
    flex: 0 0 auto;
  }

  .metric-grid,
  .summary-grid,
  .orbital-chip-row {
    grid-template-columns: 1fr;
  }

  .result-card {
    padding: 14px 13px;
    border-radius: 16px;
  }

  .data-table {
    min-width: 460px;
  }
}

/* ── Reduced Motion ──────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .viewer-toolbar,
  .viz-status,
  .result-card,
  .result-tab,
  .chip,
  .orbital-chip,
  .viewer-toolbar .btn {
    transition: none;
  }

  .viewer-toolbar .btn:hover,
  .result-tab:hover,
  .chip:hover,
  .orbital-chip:hover {
    transform: none;
  }
}

/* ── Ultra Polish ───────────────────────── */
.viewer-toolbar { position: sticky; top: 10px; z-index: 30; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
.result-tab.is-active { position: relative; overflow: hidden; }
.result-tab.is-active::after { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(255,255,255,.26), transparent 48%); pointer-events: none; }

.orbital-chip { position: relative; overflow: hidden; }
.orbital-chip.is-active::before { content: ""; position: absolute; inset: -1px; border-radius: inherit; background: radial-gradient(circle at 12% 18%, rgba(37,99,235,.20), transparent 34%), radial-gradient(circle at 88% 82%, rgba(239,68,68,.18), transparent 32%); pointer-events: none; }
.orbital-chip.is-active { box-shadow: 0 18px 40px rgba(37,99,235,.18), 0 0 0 1px rgba(37,99,235,.16); }
.orbital-chip.is-active .orbital-chip-label { color: #0b57d0; }

#result-tabs, .result-tabs { scroll-padding-left: 10px; }
#result-content, .result-content { padding-bottom: 6px; }

@media (max-width: 640px) {
  .viewer-toolbar { top: 8px; margin-inline: -2px; border-radius: 14px; }
  #result-tabs, .result-tabs { margin-top: 12px; padding-bottom: 4px; }
  .orbital-chip-row { gap: 8px; }
}



/* ── Last Polish Patch ─────────────────── */
.result-card { transform: translateZ(0); }
.result-card:hover { transform: translateY(-2px); box-shadow: 0 20px 44px rgba(15,23,42,.10); border-color: rgba(37,99,235,.18); }

.viewer-toolbar .btn, .chip, .result-tab, .orbital-chip { position: relative; overflow: hidden; }
.viewer-toolbar .btn::after, .chip::after, .result-tab::after { content:""; position:absolute; inset:0; background:linear-gradient(180deg, rgba(255,255,255,.20), transparent 46%); opacity:0; transition:opacity .18s ease; pointer-events:none; }
.viewer-toolbar .btn:hover::after, .chip:hover::after, .result-tab:hover::after, .viewer-toolbar .btn.is-active::after, .result-tab.is-active::after { opacity:1; }

#qcviz-toast-root, .qcviz-toast-root, .toast-root { position: fixed; top: 16px; right: 16px; z-index: 1200; display: grid; gap: 10px; }
#qcviz-toast-root .toast, .qcviz-toast-root .toast, .toast-root .toast, .toast {
  min-width: 280px; max-width: min(420px, calc(100vw - 32px)); padding: 12px 14px; border-radius: 14px;
  border: 1px solid rgba(148,163,184,.20); background: rgba(15,23,42,.82); color: #f8fafc;
  box-shadow: 0 20px 48px rgba(2,6,23,.28); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  animation: qcviz-toast-in .18s ease;
}
.toast.is-leaving { animation: qcviz-toast-out .18s ease forwards; }
.toast[data-tone="success"] { background: rgba(5,150,105,.92); }
.toast[data-tone="warn"] { background: rgba(217,119,6,.92); }
.toast[data-tone="error"] { background: rgba(220,38,38,.92); }

@keyframes qcviz-toast-in { from { opacity: 0; transform: translate3d(0,-8px,0) scale(.98); } to { opacity: 1; transform: translate3d(0,0,0) scale(1); } }
@keyframes qcviz-toast-out { from { opacity: 1; transform: translate3d(0,0,0) scale(1); } to { opacity: 0; transform: translate3d(0,-6px,0) scale(.98); } }

@media (max-width: 640px) {
  #qcviz-toast-root, .qcviz-toast-root, .toast-root { left: 12px; right: 12px; top: auto; bottom: calc(env(safe-area-inset-bottom, 0px) + 12px); }
  #qcviz-toast-root .toast, .qcviz-toast-root .toast, .toast-root .toast, .toast { min-width: 0; max-width: 100%; }
}


```

### `version02/src/qcviz_mcp/web/static/viewer.js`
```javascript
(function () {
  "use strict";

  const state = {
    viewer: null,
    model: null,
    ready: false,
    initializing: false,
    result: null,
    xyz: "",
    style: "stick",
    labels: false,
    labelRefs: [],
    orbitalShapes: [],
    espObjects: [],
    mode: "none", // none | orbital | esp
    volumeCache: new Map(),
    scriptSrcResolved: null,
    lastRenderKey: null,
  };

  const els = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function pickEl(ids) {
    for (const id of ids) {
      const el = byId(id);
      if (el) return el;
    }
    return null;
  }

  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function safeStr(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    return String(value).trim();
  }

  function safeNum(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function unique(arr) {
    const out = [];
    const seen = new Set();
    (arr || []).forEach((item) => {
      const key = safeStr(item);
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push(key);
    });
    return out;
  }

  function normalizePrefix(prefix) {
    let p = safeStr(prefix, "");
    if (!p) return "";
    if (!p.startsWith("/")) p = "/" + p;
    p = p.replace(/\/+$/, "");
    return p;
  }

  function setStatus(text, kind) {
    const t = safeStr(text, "Viewer ready");
    if (els.status) {
      els.status.textContent = t;
      els.status.dataset.state = safeStr(kind, "idle");
    }
  }

  function findViewerScriptSrc() {
    if (state.scriptSrcResolved) return state.scriptSrcResolved;

    if (document.currentScript && document.currentScript.src) {
      state.scriptSrcResolved = document.currentScript.src;
      return state.scriptSrcResolved;
    }

    const scripts = Array.from(document.scripts || []);
    for (const s of scripts.reverse()) {
      const src = safeStr(s.src);
      if (src && /\/viewer\.js(\?.*)?$/.test(src)) {
        state.scriptSrcResolved = src;
        return src;
      }
    }

    return "";
  }

  function inferStaticPrefixes() {
    const out = [];

    const configuredStatic = normalizePrefix(window.QCVIZ_STATIC_PREFIX || "");
    const configuredApi = normalizePrefix(window.QCVIZ_API_PREFIX || "");

    if (configuredStatic) out.push(configuredStatic);
    if (configuredApi) out.push(configuredApi + "/static");

    out.push("/api/static");
    out.push("/static");

    const scriptSrc = findViewerScriptSrc();
    if (scriptSrc) {
      try {
        const u = new URL(scriptSrc, window.location.origin);
        const path = u.pathname.replace(/\/viewer\.js(\?.*)?$/, "");
        if (path) out.push(path);
      } catch (_) {}
    }

    return unique(out);
  }

  function threeDMolCandidates() {
    const roots = inferStaticPrefixes();
    const candidates = [];

    if (safeStr(window.QCVIZ_3DMOL_SRC)) {
      candidates.push(window.QCVIZ_3DMOL_SRC);
    }

    roots.forEach((root) => {
      candidates.push(root.replace(/\/+$/, "") + "/3Dmol-min.js");
    });

    candidates.push("https://3dmol.org/build/3Dmol-min.js");

    return unique(candidates);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = Array.from(document.scripts || []).find((s) => s.src === src);
      if (existing) {
        if (window.$3Dmol) {
          resolve(src);
        } else {
          existing.addEventListener("load", () => resolve(src), { once: true });
          existing.addEventListener("error", () => reject(new Error("Failed to load " + src)), { once: true });
        }
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = () => resolve(src);
      script.onerror = () => reject(new Error("Failed to load " + src));
      document.head.appendChild(script);
    });
  }

  async function ensure3DmolLoaded() {
    if (window.$3Dmol) return true;

    const candidates = threeDMolCandidates();
    let lastError = null;

    for (const src of candidates) {
      try {
        await loadScript(src);
        if (window.$3Dmol) {
          setStatus("3Dmol loaded: " + src, "ok");
          return true;
        }
      } catch (err) {
        lastError = err;
        console.warn("[QCVizViewer] 3Dmol load failed:", src, err);
      }
    }

    setStatus("Failed to load 3Dmol.js", "error");
    if (lastError) throw lastError;
    return false;
  }

  function qcvizNormalizeB64(input) {
    let s = safeStr(input, "");
    if (!s) return "";
    const comma = s.indexOf(",");
    if (s.startsWith("data:") && comma >= 0) {
      s = s.slice(comma + 1);
    }
    s = s.replace(/\s+/g, "");
    const pad = s.length % 4;
    if (pad) {
      s += "=".repeat(4 - pad);
    }
    return s;
  }

  function decodeB64ToText(b64) {
    const normalized = qcvizNormalizeB64(b64);
    if (!normalized) return "";
    const bin = atob(normalized);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) {
      bytes[i] = bin.charCodeAt(i);
    }
    try {
      return new TextDecoder("utf-8").decode(bytes);
    } catch (_) {
      let out = "";
      for (let i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
      return out;
    }
  }

  function makeVolumeDataFromB64(b64, format) {
    const fmt = safeStr(format, "cube");
    const normalized = qcvizNormalizeB64(b64);
    const key = fmt + "::" + normalized.slice(0, 120);

    if (state.volumeCache.has(key)) {
      return state.volumeCache.get(key);
    }

    const text = decodeB64ToText(normalized);
    const entry = {
      text: text,
      volumeData: null,
      format: fmt,
    };

    try {
      if (window.$3Dmol && typeof window.$3Dmol.VolumeData === "function") {
        entry.volumeData = new window.$3Dmol.VolumeData(text, fmt);
      }
    } catch (err) {
      console.warn("[QCVizViewer] VolumeData parse failed:", err);
      entry.volumeData = null;
    }

    state.volumeCache.set(key, entry);
    return entry;
  }

  function normalizeResult(result) {
    const r = Object.assign({}, result || {});
    const vis = Object.assign({}, r.visualization || {});
    const defaults = Object.assign({}, vis.defaults || {});

    defaults.style = defaults.style || "stick";
    defaults.labels = !!defaults.labels;
    defaults.orbital_iso = safeNum(defaults.orbital_iso, 0.05);
    defaults.orbital_opacity = safeNum(defaults.orbital_opacity, 0.85);
    defaults.esp_density_iso = safeNum(defaults.esp_density_iso, 0.001);
    defaults.esp_opacity = safeNum(defaults.esp_opacity, 0.9);
    defaults.esp_range = safeNum(
      defaults.esp_range_au != null ? defaults.esp_range_au : defaults.esp_range,
      0.05
    );
    defaults.esp_preset = safeStr(defaults.esp_preset || r.esp_preset || "acs", "acs");

    vis.xyz = vis.xyz || vis.molecule_xyz || r.xyz || "";
    vis.molecule_xyz = vis.molecule_xyz || vis.xyz || r.xyz || "";

    vis.orbital_cube_b64 = vis.orbital_cube_b64 || (vis.orbital && vis.orbital.cube_b64) || r.orbital_cube_b64 || null;
    vis.density_cube_b64 = vis.density_cube_b64 || (vis.density && vis.density.cube_b64) || r.density_cube_b64 || null;
    vis.esp_cube_b64 = vis.esp_cube_b64 || (vis.esp && vis.esp.cube_b64) || r.esp_cube_b64 || null;

    if (!vis.orbital && vis.orbital_cube_b64) vis.orbital = { cube_b64: vis.orbital_cube_b64 };
    if (!vis.density && vis.density_cube_b64) vis.density = { cube_b64: vis.density_cube_b64 };
    if (!vis.esp && vis.esp_cube_b64) vis.esp = { cube_b64: vis.esp_cube_b64 };

    vis.defaults = defaults;
    vis.available = {
      orbital: !!vis.orbital_cube_b64,
      density: !!vis.density_cube_b64,
      esp: !!(vis.esp_cube_b64 && vis.density_cube_b64),
    };

    r.visualization = vis;
    return r;
  }

  function collectDom() {
    els.host = pickEl(["v3d", "viewer", "viewer3d"]);
    els.status = pickEl(["viz-status", "viewer-status"]);
    els.btnStick = pickEl(["btn-style-stick", "btn-stick"]);
    els.btnLine = pickEl(["btn-style-line", "btn-line"]);
    els.btnSphere = pickEl(["btn-style-sphere", "btn-sphere"]);
    els.btnLabels = pickEl(["btn-labels", "toggle-labels"]);
    els.btnReset = pickEl(["btn-reset-view", "btn-reset"]);
    els.btnScreenshot = pickEl(["btn-screenshot", "btn-save-image"]);
    els.btnOrbital = pickEl(["btn-orbital"]);
    els.btnESP = pickEl(["btn-esp"]);
    els.orbitalControls = pickEl(["orbital-controls"]);
    els.espControls = pickEl(["esp-controls"]);
    els.orbitalIso = pickEl(["orbital-iso", "orbitalIso", "orb-iso-slider"]);
    els.orbitalOpacity = pickEl(["orbital-opacity", "orbitalOpacity", "orb-opa-slider"]);
    els.orbitalIndex = pickEl(["orbital-index", "orbitalIndex"]);
    els.orbitalLabel = pickEl(["orbital-label", "orbitalLabel"]);
    els.espPreset = pickEl(["esp-preset", "espPreset", "sel-esp"]);
    els.espRange = pickEl(["esp-range", "espRange", "esp-range-slider"]);
    els.espOpacity = pickEl(["esp-opacity", "espOpacity", "esp-opa-slider"]);
    els.espDensityIso = pickEl(["esp-density-iso", "espDensityIso", "esp-iso-slider"]);
  }

  async function ensureViewer() {
    if (state.viewer && state.ready) return state.viewer;
    if (state.initializing) return null;

    state.initializing = true;
    collectDom();

    if (!els.host) {
      setStatus("Viewer host not found (#v3d)", "error");
      state.initializing = false;
      return null;
    }

    try {
      await ensure3DmolLoaded();
      if (!window.$3Dmol || typeof window.$3Dmol.createViewer !== "function") {
        throw new Error("3Dmol API unavailable after load.");
      }

      if (!state.viewer) {
        state.viewer = window.$3Dmol.createViewer(els.host, {
          backgroundColor: "white",
          antialias: true,
        });
      }

      state.ready = true;
      setStatus("Viewer ready", "ok");
      window.addEventListener("resize", debounce(handleResize, 120));
      return state.viewer;
    } catch (err) {
      console.error("[QCVizViewer] init failed:", err);
      setStatus("Viewer init failed", "error");
      return null;
    } finally {
      state.initializing = false;
    }
  }

  function debounce(fn, ms) {
    let timer = null;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  function handleResize() {
    if (!state.viewer) return;
    try {
      state.viewer.resize();
      state.viewer.render();
    } catch (_) {}
  }

  function applyStyle(styleName) {
    if (!state.viewer || !state.model) return;

    const style = safeStr(styleName || state.style || "stick", "stick").toLowerCase();
    state.style = style;

    try {
      state.viewer.setStyle({}, {});
      if (style === "line") {
        state.viewer.setStyle({}, { line: { linewidth: 2 } });
      } else if (style === "sphere") {
        state.viewer.setStyle({}, { sphere: { scale: 0.30 } });
      } else {
        state.viewer.setStyle({}, { stick: { radius: 0.18 }, sphere: { scale: 0.23 } });
      }
      rebuildLabels();
      state.viewer.render();
    } catch (err) {
      console.warn("[QCVizViewer] applyStyle failed:", err);
    }

    syncButtonState();
  }

  function clearLabels() {
    if (!state.viewer) return;
    (state.labelRefs || []).forEach((lbl) => {
      try {
        state.viewer.removeLabel(lbl);
      } catch (_) {}
    });
    state.labelRefs = [];
  }

  function rebuildLabels() {
    clearLabels();
    if (!state.viewer || !state.model || !state.labels) return;

    try {
      const atoms = state.model.selectedAtoms({}) || [];
      atoms.forEach((atom, idx) => {
        if (!atom) return;
        const label = state.viewer.addLabel(
          safeStr(atom.elem || atom.atom || idx),
          {
            position: { x: atom.x, y: atom.y, z: atom.z },
            fontSize: 12,
            backgroundOpacity: 0.35,
            fontColor: "black",
            backgroundColor: "white",
            inFront: true,
          }
        );
        if (label) state.labelRefs.push(label);
      });
      state.viewer.render();
    } catch (err) {
      console.warn("[QCVizViewer] rebuildLabels failed:", err);
    }
  }

  function clearOrbitalShapes() {
    if (!state.viewer) return;
    (state.orbitalShapes || []).forEach((shape) => {
      try {
        state.viewer.removeShape(shape);
      } catch (_) {}
    });
    state.orbitalShapes = [];
  }

  function clearESPObjects() {
    if (!state.viewer) return;
    (state.espObjects || []).forEach((obj) => {
      try {
        if (typeof state.viewer.removeSurface === "function") {
          state.viewer.removeSurface(obj);
        } else if (typeof state.viewer.removeShape === "function") {
          state.viewer.removeShape(obj);
        }
      } catch (_) {}
    });
    state.espObjects = [];
  }

  function clearVisualizationOverlays() {
    clearOrbitalShapes();
    clearESPObjects();
    state.mode = "none";
    syncButtonState();
    if (state.viewer) {
      try {
        state.viewer.render();
      } catch (_) {}
    }
  }

  function loadXYZ(xyzText, result) {
    const xyz = safeStr(xyzText || (result && (result.xyz || (result.visualization || {}).xyz)) || "", "");
    state.xyz = xyz;
    state.result = result ? normalizeResult(result) : state.result;

    if (!state.viewer) return false;

    try {
      state.viewer.clear();
      clearLabels();
      state.orbitalShapes = [];
      state.espObjects = [];
      state.lastRenderKey = null;

      if (!xyz) {
        state.model = null;
        state.viewer.render();
        setStatus("Viewer cleared", "idle");
        return true;
      }

      state.model = state.viewer.addModel(xyz, "xyz");
      applyStyle((state.result && state.result.visualization && state.result.visualization.defaults && state.result.visualization.defaults.style) || state.style || "stick");
      state.labels = !!(state.result && state.result.visualization && state.result.visualization.defaults && state.result.visualization.defaults.labels);
      rebuildLabels();
      state.viewer.zoomTo();
      state.viewer.render();
      setStatus("Geometry loaded", "ok");
      return true;
    } catch (err) {
      console.error("[QCVizViewer] loadXYZ failed:", err);
      setStatus("Failed to load geometry", "error");
      return false;
    }
  }

  function syncButtonState() {
    const mode = state.mode;
    const style = state.style;

    toggleActive(els.btnStick, style === "stick");
    toggleActive(els.btnLine, style === "line");
    toggleActive(els.btnSphere, style === "sphere");
    toggleActive(els.btnLabels, !!state.labels);
    toggleActive(els.btnOrbital, mode === "orbital");
    toggleActive(els.btnESP, mode === "esp");

    if (els.orbitalControls) {
      els.orbitalControls.hidden = mode !== "orbital";
    }
    if (els.espControls) {
      els.espControls.hidden = mode !== "esp";
    }
  }

  function toggleActive(el, active) {
    if (!el) return;
    el.classList.toggle("is-active", !!active);
    el.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function getOrbitalCubeB64(result) {
    const r = normalizeResult(result || state.result || {});
    const vis = r.visualization || {};
    return vis.orbital_cube_b64 || (vis.orbital && vis.orbital.cube_b64) || null;
  }

  function getDensityCubeB64(result) {
    const r = normalizeResult(result || state.result || {});
    const vis = r.visualization || {};
    return vis.density_cube_b64 || (vis.density && vis.density.cube_b64) || null;
  }

  function getEspCubeB64(result) {
    const r = normalizeResult(result || state.result || {});
    const vis = r.visualization || {};
    return vis.esp_cube_b64 || (vis.esp && vis.esp.cube_b64) || null;
  }

  function currentOrbitalIso() {
    return safeNum(els.orbitalIso && els.orbitalIso.value, ((state.result || {}).visualization || {}).defaults?.orbital_iso || 0.05);
  }

  function currentOrbitalOpacity() {
    return safeNum(els.orbitalOpacity && els.orbitalOpacity.value, ((state.result || {}).visualization || {}).defaults?.orbital_opacity || 0.85);
  }

  function currentESPDensityIso() {
    return safeNum(els.espDensityIso && els.espDensityIso.value, ((state.result || {}).visualization || {}).defaults?.esp_density_iso || 0.001);
  }

  function currentESPOpacity() {
    return safeNum(els.espOpacity && els.espOpacity.value, ((state.result || {}).visualization || {}).defaults?.esp_opacity || 0.90);
  }

  function currentESPRange() {
    const vis = ((state.result || {}).visualization || {});
    const defaults = vis.defaults || {};
    const val = els.espRange && els.espRange.value;
    return safeNum(val, defaults.esp_range_au != null ? defaults.esp_range_au : (defaults.esp_range != null ? defaults.esp_range : 0.05));
  }

  function currentESPPreset() {
    const vis = ((state.result || {}).visualization || {});
    const defaults = vis.defaults || {};
    return safeStr(
      (els.espPreset && els.espPreset.value) ||
        ((vis.esp || {}).preset) ||
        defaults.esp_preset ||
        (state.result || {}).esp_preset ||
        "acs",
      "acs"
    );
  }

  function presetToSchemeName(preset, result) {
    const p = safeStr(preset, "acs").toLowerCase();
    const vis = (result && result.visualization) || {};
    const esp = vis.esp || {};

    if (esp.surface_scheme) return safeStr(esp.surface_scheme, "rwb");

    if (["acs", "rwb"].includes(p)) return "rwb";
    if (["rsc", "bwr"].includes(p)) return "bwr";
    if (["nature", "spectral"].includes(p)) return "spectral";
    if (["inferno"].includes(p)) return "inferno";
    if (["viridis"].includes(p)) return "viridis";
    if (["greyscale", "grayscale"].includes(p)) return "greyscale";
    if (["high_contrast", "contrast"].includes(p)) return "high_contrast";
    return "rwb";
  }

  function gradientForScheme(scheme, range) {
    if (!window.$3Dmol || !window.$3Dmol.Gradient) return null;
    const lo = -Math.abs(range || 0.05);
    const hi = Math.abs(range || 0.05);
    const G = window.$3Dmol.Gradient;
    const s = safeStr(scheme, "rwb").toLowerCase();

    try {
      if ((s === "rwb" || s === "acs") && typeof G.RWB === "function") return new G.RWB(lo, hi);
      if ((s === "bwr" || s === "rsc") && typeof G.ROYGB === "function") return new G.ROYGB(lo, hi);
      if ((s === "spectral" || s === "nature") && typeof G.Sinebow === "function") return new G.Sinebow(lo, hi);
      if ((s === "inferno" || s === "viridis" || s === "greyscale" || s === "high_contrast") && typeof G.RWB === "function") {
        return new G.RWB(lo, hi);
      }
      if (typeof G.RWB === "function") return new G.RWB(lo, hi);
    } catch (_) {}

    return null;
  }

  function setControlValueUI(id, val, textId, dec) {
      const el = byId(id);
      const textEl = textId ? byId(textId) : null;
      if (el) el.value = String(val);
      if (textEl) {
          const n = Number(val);
          textEl.textContent = Number.isFinite(n) ? n.toFixed(dec || 2) : String(val);
      }
  }

  function syncControlsFromResult(result) {
    const r = normalizeResult(result || state.result || {});
    const vis = r.visualization || {};
    const defaults = vis.defaults || {};
    const selectedOrbital = r.selected_orbital || vis.orbital || {};
    const esp = vis.esp || {};

    setControlValueUI("orb-iso-slider", safeNum(defaults.orbital_iso, 0.05), "orb-iso-value", 3);
    setControlValueUI("orb-opa-slider", safeNum(defaults.orbital_opacity, 0.85), "orb-opa-value", 2);

    if (els.orbitalIndex && selectedOrbital.index != null) els.orbitalIndex.value = String(selectedOrbital.index);
    if (els.orbitalLabel) els.orbitalLabel.textContent = safeStr(selectedOrbital.label || "");

    if (els.espPreset) {
        const p = safeStr(esp.preset || defaults.esp_preset || r.esp_preset || "acs", "acs");
        if ([...els.espPreset.options].some((o) => o.value === p)) {
            els.espPreset.value = p;
        }
    }

    const range = safeNum(
        r.esp_auto_range_au != null ? r.esp_auto_range_au :
        (esp.range_au != null ? esp.range_au :
        (defaults.esp_range_au != null ? defaults.esp_range_au : defaults.esp_range)),
        0.05
    );
    setControlValueUI("esp-range-slider", range, "esp-range-value", 3);
    setControlValueUI("esp-opa-slider", safeNum(esp.opacity != null ? esp.opacity : defaults.esp_opacity, 0.90), "esp-opa-value", 2);
    setControlValueUI("esp-iso-slider", safeNum(esp.density_iso != null ? esp.density_iso : defaults.esp_density_iso, 0.001), "esp-iso-value", 3);

    state.style = safeStr(defaults.style || state.style || "stick", "stick").toLowerCase();
    state.labels = !!defaults.labels;
    syncButtonState();
  }

  function renderOrbital(result) {
    const r = normalizeResult(result || state.result || {});
    if (!state.viewer || !state.model) {
      setStatus("Load a molecule first.", "warn");
      return false;
    }

    const cubeB64 = getOrbitalCubeB64(r);
    if (!cubeB64) {
      setStatus("No orbital cube available.", "warn");
      return false;
    }

    const iso = Math.abs(currentOrbitalIso());
    const opacity = Math.max(0.05, Math.min(1.0, currentOrbitalOpacity()));
    const renderKey = ["orbital", iso, opacity, cubeB64.length].join("::");
    if (state.lastRenderKey === renderKey && state.mode === "orbital") {
      return true;
    }

    clearOrbitalShapes();
    clearESPObjects();

    try {
      const entry = makeVolumeDataFromB64(cubeB64, "cube");
      if (!entry.text) throw new Error("Decoded orbital cube is empty.");

      const posShape = state.viewer.addVolumetricData(entry.text, "cube", {
        isoval: iso,
        color: "blue",
        opacity: opacity,
      });
      const negShape = state.viewer.addVolumetricData(entry.text, "cube", {
        isoval: -iso,
        color: "red",
        opacity: opacity,
      });

      if (posShape) state.orbitalShapes.push(posShape);
      if (negShape) state.orbitalShapes.push(negShape);

      state.mode = "orbital";
      state.lastRenderKey = renderKey;
      state.viewer.render();
      const lbl = (r.visualization?.defaults?.orbital_label || "Orbital");
      setStatus(`Rendered ${lbl} (±${iso.toFixed(3)})`, "ok");
      syncButtonState();
      return true;
    } catch (err) {
      console.error("[QCVizViewer] renderOrbital failed:", err);
      setStatus("Failed to render orbital", "error");
      return false;
    }
  }

  function renderESP(result) {
    const r = normalizeResult(result || state.result || {});
    if (!state.viewer || !state.model) {
      setStatus("Load a molecule first.", "warn");
      return false;
    }

    const densityB64 = getDensityCubeB64(r);
    const espB64 = getEspCubeB64(r);

    if (!densityB64 || !espB64) {
      setStatus("ESP or density cube missing.", "warn");
      return false;
    }

    const densityIso = Math.max(0.0001, currentESPDensityIso());
    const opacity = Math.max(0.05, Math.min(1.0, currentESPOpacity()));
    const range = Math.max(0.001, Math.abs(currentESPRange()));
    const preset = currentESPPreset();
    const scheme = presetToSchemeName(preset, r);
    const renderKey = ["esp", densityIso, opacity, range, preset, densityB64.length, espB64.length].join("::");

    if (state.lastRenderKey === renderKey && state.mode === "esp") {
      return true;
    }

    clearESPObjects();
    clearOrbitalShapes();

    try {
      const densityEntry = makeVolumeDataFromB64(densityB64, "cube");
      const espEntry = makeVolumeDataFromB64(espB64, "cube");
      const gradient = gradientForScheme(scheme, range);

      let rendered = false;

      if (!rendered && typeof state.viewer.addIsosurface === "function" && densityEntry.volumeData) {
        try {
          const isoSpec = {
            isoval: densityIso,
            opacity: opacity,
            color: "white",
            smoothness: 1,
          };

          if (espEntry.volumeData) {
            isoSpec.voldata = espEntry.volumeData;
            if (gradient) isoSpec.volscheme = gradient;
          }

          const surf = state.viewer.addIsosurface(densityEntry.volumeData, isoSpec);
          if (surf) {
            state.espObjects.push(surf);
            rendered = true;
          }
        } catch (err) {
          console.warn("[QCVizViewer] addIsosurface ESP mapping failed:", err);
        }
      }

      if (!rendered && typeof state.viewer.addSurface === "function" && window.$3Dmol && window.$3Dmol.SurfaceType) {
        try {
          const surfaceType =
            window.$3Dmol.SurfaceType.SAS ||
            window.$3Dmol.SurfaceType.VDW;

          const spec = {
            opacity: opacity,
          };

          if (espEntry.volumeData) {
            spec.voldata = espEntry.volumeData;
            if (gradient) spec.volscheme = gradient;
          }

          const surf = state.viewer.addSurface(surfaceType, spec, {});
          if (surf) {
            state.espObjects.push(surf);
            rendered = true;
          }
        } catch (err) {
          console.warn("[QCVizViewer] addSurface ESP mapping failed:", err);
        }
      }

      if (!rendered && espEntry.text) {
        try {
          const pos = state.viewer.addVolumetricData(espEntry.text, "cube", {
            isoval: range * 0.5,
            color: "red",
            opacity: opacity * 0.70,
          });
          const neg = state.viewer.addVolumetricData(espEntry.text, "cube", {
            isoval: -range * 0.5,
            color: "blue",
            opacity: opacity * 0.70,
          });

          if (pos) state.espObjects.push(pos);
          if (neg) state.espObjects.push(neg);
          rendered = true;
        } catch (err) {
          console.warn("[QCVizViewer] volumetric ESP fallback failed:", err);
        }
      }

      if (!rendered) {
        throw new Error("No compatible ESP rendering path succeeded.");
      }

      state.mode = "esp";
      state.lastRenderKey = renderKey;
      state.viewer.render();
      setStatus(`Rendered ESP Map (±${range.toFixed(3)} Ha)`, "ok");
      syncButtonState();
      return true;
    } catch (err) {
      console.error("[QCVizViewer] renderESP failed:", err);
      setStatus("Failed to render ESP", "error");
      return false;
    }
  }

  function refreshVisualization() {
    if (!state.result) return false;
    if (state.mode === "orbital") return renderOrbital(state.result);
    if (state.mode === "esp") return renderESP(state.result);
    return true;
  }

  function resetView() {
    if (!state.viewer) return;
    try {
      state.viewer.zoomTo();
      state.viewer.render();
      setStatus("View reset", "ok");
    } catch (err) {
      console.warn("[QCVizViewer] resetView failed:", err);
    }
  }

  function screenshot() {
    if (!state.viewer || typeof state.viewer.pngURI !== "function") {
      setStatus("Screenshot unavailable", "warn");
      return null;
    }

    try {
      const uri = state.viewer.pngURI();
      const a = document.createElement("a");
      a.href = uri;
      a.download = "qcviz-view.png";
      a.click();
      setStatus("Screenshot saved", "ok");
      return uri;
    } catch (err) {
      console.warn("[QCVizViewer] screenshot failed:", err);
      setStatus("Screenshot failed", "error");
      return null;
    }
  }

  function setResult(result) {
    const r = normalizeResult(result || {});
    state.result = r;

    syncControlsFromResult(r);
    const xyz = safeStr((r.visualization || {}).xyz || r.xyz || "", "");

    if (!state.viewer) {
      ensureViewer().then(() => {
        if (!state.viewer) return;
        loadXYZ(xyz, r);
        autoActivatePreferredMode(r);
      });
      return r;
    }

    loadXYZ(xyz, r);
    autoActivatePreferredMode(r);
    return r;
  }

  function autoActivatePreferredMode(result) {
    const r = normalizeResult(result || state.result || {});
    const focus = safeStr(
      r.advisor_focus_tab || r.default_tab || ((r.visualization || {}).defaults || {}).focus_tab || "",
      ""
    ).toLowerCase();

    if (focus === "esp" && getDensityCubeB64(r) && getEspCubeB64(r)) {
      renderESP(r);
      return;
    }
    if ((focus === "orbital" || focus === "orbitals") && getOrbitalCubeB64(r)) {
      renderOrbital(r);
      return;
    }

    clearVisualizationOverlays();
    if (state.viewer) {
      try {
        state.viewer.render();
      } catch (_) {}
    }
  }

  function clearResult() {
    state.result = null;
    state.xyz = "";
    state.mode = "none";
    state.lastRenderKey = null;
    clearVisualizationOverlays();

    if (state.viewer) {
      try {
        state.viewer.clear();
        state.viewer.render();
      } catch (_) {}
    }

    setStatus("Viewer cleared", "idle");
  }

  function bindStyleButtons() {
    if (els.btnStick) els.btnStick.addEventListener("click", () => applyStyle("stick"));
    if (els.btnLine) els.btnLine.addEventListener("click", () => applyStyle("line"));
    if (els.btnSphere) els.btnSphere.addEventListener("click", () => applyStyle("sphere"));

    if (els.btnLabels) {
      els.btnLabels.addEventListener("click", () => {
        state.labels = !state.labels;
        rebuildLabels();
        syncButtonState();
      });
    }

    if (els.btnReset) els.btnReset.addEventListener("click", resetView);
    if (els.btnScreenshot) els.btnScreenshot.addEventListener("click", screenshot);
  }

  function bindVisualizationButtons() {
    if (els.btnOrbital) {
      els.btnOrbital.addEventListener("click", () => {
        if (state.mode === "orbital") {
          clearVisualizationOverlays();
        } else {
          renderOrbital(state.result);
        }
      });
    }

    if (els.btnESP) {
      els.btnESP.addEventListener("click", () => {
        if (state.mode === "esp") {
          clearVisualizationOverlays();
        } else {
          renderESP(state.result);
        }
      });
    }
  }

  function bindReactiveControls() {
    const rerenderOrbital = () => {
      if (state.mode === "orbital") renderOrbital(state.result);
    };
    const rerenderESP = () => {
      if (state.mode === "esp") renderESP(state.result);
    };

    const binds = [
        [els.orbitalIso, rerenderOrbital, "orb-iso-value", 3],
        [els.orbitalOpacity, rerenderOrbital, "orb-opa-value", 2],
        [els.espRange, rerenderESP, "esp-range-value", 3],
        [els.espOpacity, rerenderESP, "esp-opa-value", 2],
        [els.espDensityIso, rerenderESP, "esp-iso-value", 3],
    ];

    binds.forEach(([el, handler, textId, dec]) => {
        if (!el) return;
        el.addEventListener("input", (e) => {
            setControlValueUI(el.id, e.target.value, textId, dec);
        });
        el.addEventListener("change", handler);
    });

    if (els.espPreset) {
      els.espPreset.addEventListener("change", rerenderESP);
    }
  }

  async function init() {
    collectDom();
    bindStyleButtons();
    bindVisualizationButtons();
    bindReactiveControls();
    syncButtonState();

    await ensureViewer();

    if (state.result) {
      setResult(state.result);
    }
  }

  window.QCVizViewer = {
    init: init,
    setResult: setResult,
    loadResult: setResult,
    setData: setResult,
    clearResult: clearResult,
    clear: clearResult,
    loadXYZ: function (xyz, result) {
      if (result) state.result = normalizeResult(result);
      return loadXYZ(xyz, result || state.result);
    },
    applyStyle: applyStyle,
    setStyle: applyStyle,
    renderOrbital: function () {
      return renderOrbital(state.result);
    },
    renderESP: function () {
      return renderESP(state.result);
    },
    resetView: resetView,
    screenshot: screenshot,
    setStatus: setStatus,
    qcvizNormalizeB64: qcvizNormalizeB64,
    makeVolumeDataFromB64: makeVolumeDataFromB64,
    getState: function () {
      return {
        ready: state.ready,
        style: state.style,
        labels: state.labels,
        mode: state.mode,
        hasViewer: !!state.viewer,
        hasModel: !!state.model,
        hasResult: !!state.result,
        staticPrefixes: inferStaticPrefixes(),
        threeDMolCandidates: threeDMolCandidates(),
      };
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

```

### `version02/src/qcviz_mcp/web/static/results.js`
```javascript
(function () {
  "use strict";

  const state = {
    result: null,
    rawResult: null,
    jobs: [],
    activeTab: "summary",
    statusText: "Ready",
    statusKind: "idle",
    resolved: {
      computeJobsPath: null,
    },
    selectedJobId: null,
  };

  const TAB_ORDER = [
    ["summary", "Summary"],
    ["geometry", "Geometry"],
    ["orbital", "Orbital"],
    ["esp", "ESP"],
    ["charges", "Charges"],
    ["jobs", "Jobs"],
    ["json", "JSON"],
  ];

  const els = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function pickEl(ids) {
    for (const id of ids) {
      const el = byId(id);
      if (el) return el;
    }
    return null;
  }

  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function on(el, type, handler) {
    if (el) el.addEventListener(type, handler);
  }

  function safeStr(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    return String(value).trim();
  }

  function safeNum(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function escapeHtml(text) {
    return safeStr(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function prettyJson(obj) {
    try {
      return JSON.stringify(obj, null, 2);
    } catch (_) {
      return String(obj);
    }
  }

  function unique(arr) {
    const out = [];
    const seen = new Set();
    (arr || []).forEach((item) => {
      const key = safeStr(item);
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push(key);
    });
    return out;
  }

  function normalizePrefix(prefix) {
    let p = safeStr(prefix, "");
    if (!p) return "";
    if (!p.startsWith("/")) p = "/" + p;
    p = p.replace(/\/+$/, "");
    return p;
  }

  function joinPath(base, suffix) {
    if (!suffix) return base;
    if (suffix.startsWith("?")) return base + suffix;
    return base.replace(/\/+$/, "") + suffix;
  }

  function absoluteHttpUrl(path) {
    return new URL(path, window.location.origin).toString();
  }

  function computeJobsCandidates() {
    const pref = normalizePrefix(window.QCVIZ_API_PREFIX || "");
    return unique([
      safeStr(window.QCVIZ_COMPUTE_JOBS_PATH || ""),
      pref ? pref + "/compute/jobs" : "",
      "/api/compute/jobs",
      "/compute/jobs",
    ]);
  }

  async function fetchJsonWithFallback(kind, candidates, suffix, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign({ Accept: "application/json" }, opts.headers || {});

    const bases = unique([state.resolved[kind]].concat(candidates || []).filter(Boolean));
    let lastError = null;

    for (const base of bases) {
      const url = joinPath(base, suffix || "");
      try {
        const res = await fetch(url, opts);
        if (!res.ok) {
          let detail = "";
          try {
            const ct = res.headers.get("content-type") || "";
            detail = ct.includes("application/json")
              ? JSON.stringify(await res.json())
              : await res.text();
          } catch (_) {}

          const err = new Error("HTTP " + res.status + " for " + url + (detail ? " :: " + detail : ""));
          err.status = res.status;
          err.url = url;

          if (res.status === 404 || res.status === 405) {
            lastError = err;
            continue;
          }
          throw err;
        }

        let data = null;
        try {
          data = await res.json();
        } catch (_) {
          const text = await res.text();
          try {
            data = JSON.parse(text);
          } catch (_) {
            data = { text: text };
          }
        }

        state.resolved[kind] = base;
        return { data, base, url, response: res };
      } catch (err) {
        if (err && (err.status === 404 || err.status === 405)) {
          lastError = err;
          continue;
        }
        if (err && String(err.message || "").includes("Failed to fetch")) {
          lastError = err;
          continue;
        }
        throw err;
      }
    }

    throw lastError || new Error("All fallback endpoints failed for " + kind);
  }

  function viewerApi() {
    return window.QCVizViewer || null;
  }

  function tryPushToViewer(result) {
    const api = viewerApi();
    if (!api || !result) return;

    try {
      if (typeof api.setResult === "function") {
        api.setResult(result);
        return;
      }
    } catch (_) {}

    try {
      if (typeof api.loadResult === "function") {
        api.loadResult(result);
        return;
      }
    } catch (_) {}

    try {
      if (typeof api.setData === "function") {
        api.setData(result);
        return;
      }
    } catch (_) {}

    try {
      const vis = result.visualization || {};
      const xyz = vis.xyz || vis.molecule_xyz || result.xyz;
      if (xyz && typeof api.loadXYZ === "function") {
        api.loadXYZ(xyz, result);
      }
    } catch (_) {}
  }

  function setStatus(text, kind) {
    state.statusText = safeStr(text, "Ready");
    state.statusKind = safeStr(kind, "idle");

    if (els.resultStatus) {
      els.resultStatus.textContent = state.statusText;
      els.resultStatus.dataset.state = state.statusKind;
    }
    if (els.vizStatus && !els.vizStatus.textContent) {
      els.vizStatus.textContent = state.statusText;
    }
  }

  function normalizeResult(input) {
    const result = Object.assign({}, input || {});
    const vis = Object.assign({}, result.visualization || {});
    const defaults = Object.assign({}, vis.defaults || {});

    if (result.mulliken_charges && !result.partial_charges) {
      result.partial_charges = result.mulliken_charges;
    }
    if (result.partial_charges && !result.mulliken_charges) {
      result.mulliken_charges = result.partial_charges;
    }

    defaults.style = defaults.style || "stick";
    defaults.labels = !!defaults.labels;
    defaults.orbital_iso = safeNum(defaults.orbital_iso, 0.05);
    defaults.orbital_opacity = safeNum(defaults.orbital_opacity, 0.85);
    defaults.esp_density_iso = safeNum(defaults.esp_density_iso, 0.001);
    defaults.esp_opacity = safeNum(defaults.esp_opacity, 0.9);
    defaults.esp_preset = safeStr(defaults.esp_preset || result.esp_preset || "acs", "acs");

    const orbitalCube = vis.orbital_cube_b64 || (vis.orbital && vis.orbital.cube_b64) || result.orbital_cube_b64 || null;
    const densityCube = vis.density_cube_b64 || (vis.density && vis.density.cube_b64) || result.density_cube_b64 || null;
    const espCube = vis.esp_cube_b64 || (vis.esp && vis.esp.cube_b64) || result.esp_cube_b64 || null;

    vis.defaults = defaults;
    vis.xyz = vis.xyz || vis.molecule_xyz || result.xyz || null;
    vis.molecule_xyz = vis.molecule_xyz || vis.xyz || result.xyz || null;
    vis.orbital_cube_b64 = orbitalCube;
    vis.density_cube_b64 = densityCube;
    vis.esp_cube_b64 = espCube;

    if (!vis.orbital && orbitalCube) vis.orbital = { cube_b64: orbitalCube };
    if (!vis.density && densityCube) vis.density = { cube_b64: densityCube };
    if (!vis.esp && espCube) vis.esp = { cube_b64: espCube };

    vis.available = {
      orbital: !!orbitalCube,
      density: !!densityCube,
      esp: !!(espCube && densityCube),
    };

    result.visualization = vis;

    const focus = safeStr(
      result.advisor_focus_tab || result.default_tab || result.focus_tab || defaults.focus_tab,
      ""
    );
    if (focus) {
      result.advisor_focus_tab = focus;
      result.default_tab = focus;
    } else if (vis.available.esp) {
      result.advisor_focus_tab = "esp";
      result.default_tab = "esp";
    } else if (vis.available.orbital) {
      result.advisor_focus_tab = "orbital";
      result.default_tab = "orbital";
    } else if ((result.partial_charges || []).length) {
      result.advisor_focus_tab = "charges";
      result.default_tab = "charges";
    } else if (result.geometry_summary) {
      result.advisor_focus_tab = "geometry";
      result.default_tab = "geometry";
    } else {
      result.advisor_focus_tab = "summary";
      result.default_tab = "summary";
    }

    return result;
  }

  function normalizeJob(job) {
    const j = Object.assign({}, job || {});
    j.job_id = safeStr(j.job_id);
    j.status = safeStr(j.status || "queued", "queued");
    j.progress = safeNum(j.progress, 0);
    j.step = safeStr(j.step || "");
    j.message = safeStr(j.message || "");
    if (j.result && typeof j.result === "object") {
      j.result = normalizeResult(j.result);
    }
    if (!Array.isArray(j.events)) j.events = [];
    return j;
  }

  function normalizeJobsInput(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) return payload.map(normalizeJob);
    if (Array.isArray(payload.items)) return payload.items.map(normalizeJob);
    if (payload.job_id) return [normalizeJob(payload)];
    return [];
  }

  function summaryRows(result) {
    if (!result) return [];
    return [
      ["Job type", result.job_type],
      ["Structure", result.structure_name || result.structure_query],
      ["Formula", result.formula],
      ["Method", result.method],
      ["Basis", result.basis],
      ["Charge", result.charge],
      ["Multiplicity", result.multiplicity],
      ["SCF converged", result.scf_converged],
      ["Total energy (Ha)", finiteText(result.total_energy_hartree, 8)],
      ["Total energy (eV)", finiteText(result.total_energy_ev, 6)],
      ["HOMO-LUMO gap (eV)", finiteText(result.orbital_gap_ev, 4)],
    ].filter((row) => row[1] !== undefined && row[1] !== null && row[1] !== "");
  }

  function finiteText(value, digits) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits || 4) : "";
  }

  function kvTable(rows) {
    return `
      <table class="qcviz-table qcviz-kv">
        <tbody>
          ${rows.map(([k, v]) => `
            <tr>
              <th>${escapeHtml(k)}</th>
              <td>${escapeHtml(String(v))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function summaryTab(result) {
    if (!result) {
      return emptyCard("No result yet.");
    }

    const dip = result.dipole_moment || {};
    const warnings = Array.isArray(result.warnings) ? result.warnings : [];

    const extraRows = [];
    if (dip && dip.magnitude !== undefined && dip.magnitude !== null) {
      extraRows.push(["Dipole magnitude (Debye)", finiteText(dip.magnitude, 4)]);
    }
    if (result.homo_energy_ev !== undefined && result.homo_energy_ev !== null) {
      extraRows.push(["HOMO (eV)", finiteText(result.homo_energy_ev, 4)]);
    }
    if (result.lumo_energy_ev !== undefined && result.lumo_energy_ev !== null) {
      extraRows.push(["LUMO (eV)", finiteText(result.lumo_energy_ev, 4)]);
    }

    return `
      <section class="result-panel">
        <h3>Summary</h3>
        ${kvTable(summaryRows(result).concat(extraRows))}
        ${
          warnings.length
            ? `<div class="result-block">
                <h4>Warnings</h4>
                <ul>${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>
              </div>`
            : ""
        }
      </section>
    `;
  }

  function geometryTab(result) {
    if (!result) return emptyCard("No geometry available.");

    const g = result.geometry_summary || {};
    const atoms = Array.isArray(result.atoms) ? result.atoms : [];
    const bonds = Array.isArray(result.bonds) ? result.bonds : [];

    return `
      <section class="result-panel">
        <h3>Geometry</h3>
        ${kvTable([
          ["Atoms", g.n_atoms != null ? g.n_atoms : atoms.length],
          ["Formula", g.formula || result.formula || ""],
          ["Bond count", g.bond_count != null ? g.bond_count : bonds.length],
          ["Mean bond length (Å)", finiteText(g.bond_length_mean_angstrom, 4)],
          ["Min bond length (Å)", finiteText(g.bond_length_min_angstrom, 4)],
          ["Max bond length (Å)", finiteText(g.bond_length_max_angstrom, 4)],
        ].filter((x) => x[1] !== ""))}
        ${
          atoms.length
            ? `<div class="result-block">
                <h4>Atoms</h4>
                <div class="result-scroll">
                  <table class="qcviz-table">
                    <thead>
                      <tr><th>#</th><th>Atom</th><th>X</th><th>Y</th><th>Z</th></tr>
                    </thead>
                    <tbody>
                      ${atoms.map((a, idx) => `
                        <tr>
                          <td>${idx}</td>
                          <td>${escapeHtml(a.symbol || "")}</td>
                          <td>${finiteText(a.x, 4)}</td>
                          <td>${finiteText(a.y, 4)}</td>
                          <td>${finiteText(a.z, 4)}</td>
                        </tr>
                      `).join("")}
                    </tbody>
                  </table>
                </div>
              </div>`
            : ""
        }
        ${
          result.xyz
            ? `<div class="result-block">
                <h4>XYZ</h4>
                <pre class="result-pre">${escapeHtml(result.xyz)}</pre>
              </div>`
            : ""
        }
      </section>
    `;
  }

  function orbitalTab(result) {
    if (!result) return emptyCard("No orbital result yet.");

    const vis = result.visualization || {};
    const selected = result.selected_orbital || ((vis.orbital || {}));
    const orbitals = Array.isArray(result.orbitals) ? result.orbitals : [];
    const hasCube = !!(vis.orbital_cube_b64 || (vis.orbital && vis.orbital.cube_b64));

    return `
      <section class="result-panel">
        <h3>Orbital</h3>
        ${kvTable([
          ["Selected orbital", selected.label || ""],
          ["Index", selected.index != null ? selected.index : ""],
          ["Spin", selected.spin || ""],
          ["Occupancy", selected.occupancy != null ? selected.occupancy : ""],
          ["Energy (Ha)", finiteText(selected.energy_hartree, 6)],
          ["Energy (eV)", finiteText(selected.energy_ev, 4)],
          ["Cube available", hasCube ? "Yes" : "No"],
        ].filter((x) => x[1] !== ""))}
        ${
          orbitals.length
            ? `<div class="result-block">
                <h4>Nearby orbitals</h4>
                <div class="result-scroll">
                  <table class="qcviz-table">
                    <thead>
                      <tr><th>Label</th><th>Index</th><th>Spin</th><th>Occ</th><th>eV</th></tr>
                    </thead>
                    <tbody>
                      ${orbitals.map((o) => `
                        <tr>
                          <td>${escapeHtml(o.label || "")}</td>
                          <td>${o.index != null ? escapeHtml(String(o.index)) : ""}</td>
                          <td>${escapeHtml(o.spin || "")}</td>
                          <td>${o.occupancy != null ? escapeHtml(String(o.occupancy)) : ""}</td>
                          <td>${finiteText(o.energy_ev, 4)}</td>
                        </tr>
                      `).join("")}
                    </tbody>
                  </table>
                </div>
              </div>`
            : ""
        }
      </section>
    `;
  }

  function espTab(result) {
    if (!result) return emptyCard("No ESP result yet.");

    const vis = result.visualization || {};
    const esp = vis.esp || {};
    const defaults = vis.defaults || {};
    const fit = result.esp_auto_fit || {};
    const stats = fit.stats || {};
    const hasEsp = !!(vis.esp_cube_b64 || esp.cube_b64);
    const hasDensity = !!(vis.density_cube_b64 || (vis.density && vis.density.cube_b64));

    return `
      <section class="result-panel">
        <h3>ESP</h3>
        ${kvTable([
          ["Preset", esp.preset || result.esp_preset || defaults.esp_preset || ""],
          ["Scheme", esp.surface_scheme || defaults.esp_scheme || ""],
          ["Range (a.u.)", finiteText(result.esp_auto_range_au || esp.range_au || defaults.esp_range_au || defaults.esp_range, 4)],
          ["Range (kcal/mol)", finiteText(result.esp_auto_range_kcal || esp.range_kcal || defaults.esp_range_kcal, 3)],
          ["Density iso", finiteText(esp.density_iso || defaults.esp_density_iso, 4)],
          ["ESP cube", hasEsp ? "Yes" : "No"],
          ["Density cube", hasDensity ? "Yes" : "No"],
          ["Auto-fit strategy", fit.strategy || esp.fit_strategy || ""],
        ].filter((x) => x[1] !== ""))}
        ${
          Object.keys(stats).length
            ? `<div class="result-block">
                <h4>Auto-fit stats</h4>
                ${kvTable(
                  Object.keys(stats).map((k) => [k, Number.isFinite(Number(stats[k])) ? Number(stats[k]).toFixed(6) : String(stats[k])])
                )}
              </div>`
            : ""
        }
      </section>
    `;
  }

  function chargesTab(result) {
    if (!result) return emptyCard("No charge result yet.");

    const charges = Array.isArray(result.partial_charges)
      ? result.partial_charges
      : Array.isArray(result.mulliken_charges)
        ? result.mulliken_charges
        : [];

    if (!charges.length) {
      return emptyCard("No partial charges available.");
    }

    return `
      <section class="result-panel">
        <h3>Charges</h3>
        <div class="result-scroll">
          <table class="qcviz-table">
            <thead>
              <tr><th>#</th><th>Atom</th><th>Charge</th></tr>
            </thead>
            <tbody>
              ${charges.map((c, idx) => `
                <tr>
                  <td>${c.atom_index != null ? c.atom_index : idx}</td>
                  <td>${escapeHtml(c.symbol || "")}</td>
                  <td>${finiteText(c.charge, 6)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function jsonTab(result) {
    if (!result) return emptyCard("No JSON payload yet.");
    const safe = Object.assign({}, result);
    if (safe.visualization) {
      safe.visualization = Object.assign({}, safe.visualization);
      if (safe.visualization.orbital_cube_b64) safe.visualization.orbital_cube_b64 = "[BASE64_TRUNCATED]";
      if (safe.visualization.density_cube_b64) safe.visualization.density_cube_b64 = "[BASE64_TRUNCATED]";
      if (safe.visualization.esp_cube_b64) safe.visualization.esp_cube_b64 = "[BASE64_TRUNCATED]";
      if (safe.visualization.orbital) safe.visualization.orbital.cube_b64 = "[BASE64_TRUNCATED]";
      if (safe.visualization.density) safe.visualization.density.cube_b64 = "[BASE64_TRUNCATED]";
      if (safe.visualization.esp) safe.visualization.esp.cube_b64 = "[BASE64_TRUNCATED]";
    }

    const txt = JSON.stringify(safe, null, 2);
    return `<div class="result-card">
      <div class="result-card-title">Raw Result Payload</div>
      <pre class="code-block" style="max-height: 400px;"><code>${escapeHtml(txt)}</code></pre>
    </div>`;
  }

  function statusBadge(status) {
    const s = safeStr(status, "unknown").toLowerCase();
    return `<span class="job-status job-status-${escapeHtml(s)}">${escapeHtml(s)}</span>`;
  }

  function jobsTab() {
    const items = Array.isArray(state.jobs) ? state.jobs : [];
    const selectedJob = items.find((j) => j.job_id === state.selectedJobId) || null;

    return `
      <section class="result-panel">
        <div class="result-toolbar" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="margin:0;">Jobs</h3>
          <div class="result-toolbar-actions">
            <button type="button" id="results-jobs-refresh" class="tool-btn">Refresh</button>
          </div>
        </div>

        ${
          items.length
            ? `<div class="result-scroll">
                <table class="data-table" style="width:100%;">
                  <thead>
                    <tr>
                      <th>Job ID</th>
                      <th>Status</th>
                      <th>Progress</th>
                      <th>Step</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${items.map((job) => {
                      const id = escapeHtml(String(job.job_id || "").substring(0, 8));
                      const stat = escapeHtml(job.status || "unknown");
                      const step = escapeHtml(job.step || "—");
                      const pct = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0))));
                      
                      let badgeStyle = "background: #f1f5f9; color: #475569;";
                      if (stat === "completed") badgeStyle = "background: #ecfdf5; color: #047857;";
                      if (stat === "failed" || stat === "error") badgeStyle = "background: #fef2f2; color: #b91c1c;";
                      if (stat === "running") badgeStyle = "background: #eff6ff; color: #1d4ed8;";

                      return `<tr data-job-row="${escapeHtml(job.job_id)}" class="${job.job_id === state.selectedJobId ? "is-selected" : ""}">
                        <td><span class="mono-text" title="${escapeHtml(job.job_id)}">${id}</span></td>
                        <td><span style="padding:2px 6px; border-radius:4px; font-size:11px; font-weight:600; ${badgeStyle}">${stat}</span></td>
                        <td>${pct}%</td>
                        <td>${step}</td>
                        <td style="display:flex; gap:4px;">
                          <button type="button" class="tool-btn" style="padding:4px 8px; font-size:11px;" data-job-open="${escapeHtml(job.job_id)}">Open</button>
                          ${
                            job.status === "completed"
                              ? `<button type="button" class="tool-btn" style="padding:4px 8px; font-size:11px;" data-job-load-result="${escapeHtml(job.job_id)}">Load result</button>`
                              : ""
                          }
                        </td>
                      </tr>`;
                    }).join("")}
                  </tbody>
                </table>
              </div>`
            : `<div class="empty-state">No jobs yet.</div>`
        }

        ${
          selectedJob
            ? `
              <div class="result-card mt-sm">
                <div class="result-card-title">Selected job</div>
                <div class="summary-grid">
                  <div class="metric-card">
                    <div class="metric-label">Job ID</div>
                    <div class="metric-value" style="font-size:13px;">${escapeHtml(selectedJob.job_id)}</div>
                  </div>
                  <div class="metric-card">
                    <div class="metric-label">Status</div>
                    <div class="metric-value">${escapeHtml(selectedJob.status)}</div>
                  </div>
                  <div class="metric-card">
                    <div class="metric-label">Progress</div>
                    <div class="metric-value">${Math.round(safeNum(selectedJob.progress, 0))}%</div>
                  </div>
                  <div class="metric-card">
                    <div class="metric-label">Step</div>
                    <div class="metric-value">${escapeHtml(selectedJob.step || "")}</div>
                  </div>
                </div>
              </div>

              ${
                Array.isArray(selectedJob.events) && selectedJob.events.length
                  ? `<div class="result-card mt-sm">
                      <div class="result-card-title">Events</div>
                      <div class="job-events-list" style="max-height:180px;">
                        ${selectedJob.events.map((ev) => `
                          <div style="padding:8px 12px; border-bottom:1px solid var(--border); font-size:12px;">
                            <strong>${escapeHtml(ev.type || "")}</strong>
                            ${ev.message ? ` <span style="color:var(--muted)">— ${escapeHtml(ev.message)}</span>` : ""}
                          </div>
                        `).join("")}
                      </div>
                    </div>`
                  : ""
              }

              ${
                selectedJob.error
                  ? `<div class="result-card mt-sm warning-card">
                      <div class="result-card-title" style="color:var(--danger)">Error</div>
                      <pre class="code-block">${escapeHtml(prettyJson(selectedJob.error))}</pre>
                    </div>`
                  : ""
              }
            `
            : ""
        }
      </section>
    `;
  }

  function emptyCard(text) {
    return `<div class="empty-state">${escapeHtml(text)}</div>`;
  }

  function renderTabBody(tab) {
    switch (tab) {
      case "summary":
        return summaryTab(state.result);
      case "geometry":
        return geometryTab(state.result);
      case "orbital":
      case "orbitals":
        return orbitalTab(state.result);
      case "esp":
        return espTab(state.result);
      case "charges":
        return chargesTab(state.result);
      case "jobs":
        return jobsTab();
      case "json":
        return jsonTab(state.result);
      default:
        return summaryTab(state.result);
    }
  }

  function renderTabs() {
    if (!els.resultTabs) return;
    els.resultTabs.innerHTML = TAB_ORDER.map(([key, label]) => {
      const active = key === state.activeTab ? "is-active active" : "";
      return `
        <button
          type="button"
          class="result-tab tab-btn ${active}"
          data-result-tab="${escapeHtml(key)}"
        >
          ${escapeHtml(label)}
        </button>
      `;
    }).join("");

    qsa("[data-result-tab]", els.resultTabs).forEach((btn) => {
      btn.addEventListener("click", () => {
        selectTab(btn.getAttribute("data-result-tab"));
      });
    });
  }

  function bindJobsTabActions() {
    if (!els.resultContent) return;

    const refreshBtn = byId("results-jobs-refresh");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        refreshJobs(true);
      });
    }

    qsa("[data-job-open]", els.resultContent).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = safeStr(btn.getAttribute("data-job-open"));
        if (!jobId) return;
        state.selectedJobId = jobId;
        renderActiveTab();
        try {
          const job = await fetchJob(jobId);
          upsertJob(job);
          renderActiveTab();
        } catch (err) {
          console.warn("[QCVizResults] failed to open job:", err);
          setStatus("Failed to load job detail.", "warn");
        }
      });
    });

    qsa("[data-job-load-result]", els.resultContent).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = safeStr(btn.getAttribute("data-job-load-result"));
        if (!jobId) return;
        try {
          const job = await fetchJob(jobId);
          upsertJob(job);
          if (job && job.result) {
            setResult(job.result, { preserveTab: false });
            state.selectedJobId = jobId;
            renderActiveTab();
            setStatus("Loaded result from job " + jobId, "ok");
          } else {
            setStatus("This job does not have a result yet.", "warn");
          }
        } catch (err) {
          console.warn("[QCVizResults] failed to load job result:", err);
          setStatus("Failed to load job result.", "error");
        }
      });
    });
  }

  function renderActiveTab() {
    renderTabs();

    if (!els.resultContent) return;
    els.resultContent.innerHTML = renderTabBody(state.activeTab);
    bindJobsTabActions();
  }

  function selectTab(tab) {
    const key = safeStr(tab, "summary").toLowerCase();
    state.activeTab = TAB_ORDER.some(([k]) => k === key) ? key : "summary";
    renderActiveTab();
  }

  function upsertJob(job) {
    const normalized = normalizeJob(job);
    if (!normalized.job_id) return;

    const idx = state.jobs.findIndex((x) => x.job_id === normalized.job_id);
    if (idx >= 0) {
      state.jobs[idx] = Object.assign({}, state.jobs[idx], normalized);
    } else {
      state.jobs.unshift(normalized);
    }

    state.jobs.sort((a, b) => {
      const ta = Number(a.created_at || 0);
      const tb = Number(b.created_at || 0);
      return tb - ta;
    });
  }

  function updateJobs(payload) {
    const items = normalizeJobsInput(payload);
    if (!items.length) {
      renderActiveTab();
      return state.jobs;
    }

    items.forEach(upsertJob);
    if (!state.selectedJobId && state.jobs.length) {
      state.selectedJobId = state.jobs[0].job_id;
    }
    renderActiveTab();
    return state.jobs;
  }

  async function fetchJob(jobId) {
    const suffix = "/" + encodeURIComponent(jobId) + "?include_result=true&include_events=true&include_payload=true";
    const res = await fetchJsonWithFallback(
      "computeJobsPath",
      computeJobsCandidates(),
      suffix,
      { method: "GET" }
    );
    return normalizeJob(res.data || {});
  }

  async function refreshJobs(silent) {
    try {
      const res = await fetchJsonWithFallback(
        "computeJobsPath",
        computeJobsCandidates(),
        "",
        { method: "GET" }
      );
      const items = normalizeJobsInput(res.data);
      state.jobs = items;
      if (!state.selectedJobId && items.length) {
        state.selectedJobId = items[0].job_id;
      }
      renderActiveTab();
      if (!silent) setStatus("Jobs refreshed.", "ok");
      return items;
    } catch (err) {
      console.warn("[QCVizResults] refreshJobs failed:", err);
      if (!silent) setStatus("Failed to refresh jobs.", "warn");
      throw err;
    }
  }

  function clearResult(opts) {
    const options = opts || {};
    state.result = null;
    state.rawResult = null;
    if (!options.keepTab) {
      state.activeTab = "summary";
    }
    renderActiveTab();
  }

  function setResult(result, opts) {
    state.rawResult = result || null;
    state.result = normalizeResult(result || {});
    tryPushToViewer(state.result);

    const options = opts || {};
    if (!options.preserveTab) {
      state.activeTab = safeStr(
        state.result.advisor_focus_tab || state.result.default_tab || "summary",
        "summary"
      ).toLowerCase();
      if (!TAB_ORDER.some(([k]) => k === state.activeTab)) {
        state.activeTab = "summary";
      }
    }

    renderActiveTab();
    setStatus("Result loaded.", "ok");
    return state.result;
  }

  function collectDom() {
    els.resultTabs = pickEl(["result-tabs", "resultTabs"]);
    els.resultContent = pickEl(["result-content", "resultContent", "result-panel-content"]);
    els.resultStatus = pickEl(["result-status", "results-status", "chatStatus"]);
    els.vizStatus = pickEl(["viz-status"]);
  }

  function init() {
    collectDom();
    renderTabs();
    renderActiveTab();
    refreshJobs(true).catch(() => {});
  }

  window.QCVizResults = {
    init,
    setResult,
    clearResult,
    updateJobs,
    refreshJobs,
    selectTab,
    renderTabs,
    renderActiveTab,
    setStatus,
    getState: function () {
      return {
        result: state.result,
        rawResult: state.rawResult,
        jobs: state.jobs.slice(),
        activeTab: state.activeTab,
        statusText: state.statusText,
        statusKind: state.statusKind,
        selectedJobId: state.selectedJobId,
        resolved: Object.assign({}, state.resolved),
        endpointCandidates: {
          computeJobs: computeJobsCandidates().map(absoluteHttpUrl),
        },
      };
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

```

### `version02/src/qcviz_mcp/web/static/chat.js`
```javascript
(function () {
  "use strict";

  const state = {
    sessionId: null,
    ws: null,
    wsConnected: false,
    wsConnecting: false,
    wsPath: null,
    activeJobId: null,
    activeJobTerminal: false,
    pollTimer: null,
    submitting: false,
    resolved: {
      wsPath: null,
      computeJobsPath: null,
      chatPath: null,
    },
    seenEventIds: new Set(),
    lastProgressKey: null,
    lastAssistantText: "",
  };

  const els = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function nowTs() {
    return Date.now();
  }

  function safeStr(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    return String(value).trim();
  }

  function escapeHtml(text) {
    return safeStr(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function unique(arr) {
    const out = [];
    const seen = new Set();
    (arr || []).forEach((item) => {
      const key = safeStr(item);
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push(key);
    });
    return out;
  }

  function normalizePrefix(prefix) {
    let p = safeStr(prefix, "");
    if (!p) return "";
    if (!p.startsWith("/")) p = "/" + p;
    p = p.replace(/\/+$/, "");
    return p;
  }

  function absoluteHttpUrl(path) {
    return new URL(path, window.location.origin).toString();
  }

  function absoluteWsUrl(path) {
    const url = new URL(path, window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }

  function joinPath(base, suffix) {
    if (!suffix) return base;
    if (suffix.startsWith("?")) return base + suffix;
    return base.replace(/\/+$/, "") + suffix;
  }

  function resultApi() {
    return window.QCVizResults || null;
  }

  function viewerApi() {
    return window.QCVizViewer || null;
  }

  function setResultsStatus(text, kind) {
    const api = resultApi();
    if (!api || typeof api.setStatus !== "function") return;
    try {
      api.setStatus(text, kind);
    } catch (_) {}
  }

  function updateResultsJobs(payload) {
    const api = resultApi();
    if (!api || typeof api.updateJobs !== "function") return;
    try {
      api.updateJobs(payload);
    } catch (_) {
      try {
        api.updateJobs(Array.isArray(payload) ? payload : [payload]);
      } catch (_) {}
    }
  }

  function setResultPayload(result) {
    const api = resultApi();
    if (!api || typeof api.setResult !== "function") return;
    try {
      api.setResult(result);
    } catch (err) {
      console.warn("[QCVizChat] result rendering failed:", err);
    }
  }

  function clearResultPayload() {
    const api = resultApi();
    if (!api || typeof api.clearResult !== "function") return;
    try {
      api.clearResult();
    } catch (_) {}
  }

  function setViewerStatus(text, kind) {
    const api = viewerApi();
    if (!api || typeof api.setStatus !== "function") return;
    try {
      api.setStatus(text, kind);
    } catch (_) {}
  }

  function formatClock(ts) {
    const d = ts ? new Date(ts) : new Date();
    return d.toLocaleTimeString();
  }

  function ensureSessionId() {
    if (!state.sessionId) {
      state.sessionId = "sess-" + nowTs() + "-" + Math.random().toString(36).slice(2, 10);
    }
    return state.sessionId;
  }

  function setStatus(text, kind) {
    const label = safeStr(text, "Ready");
    if (els.chatStatus) {
      els.chatStatus.textContent = label;
      els.chatStatus.dataset.state = safeStr(kind, "idle");
    }
    setResultsStatus(label, kind || "info");
    setViewerStatus(label, kind || "info");
  }

  function setBusy(isBusy) {
    state.submitting = !!isBusy;
    if (els.chatSend) {
      els.chatSend.disabled = !!isBusy;
    }
    if (els.chatInput) {
      els.chatInput.disabled = false;
    }
    if (els.chatForm) {
      els.chatForm.dataset.busy = isBusy ? "1" : "0";
    }
  }

  function ensureLogHost() {
    if (els.chatLog) return els.chatLog;
    return null;
  }

  function appendMessage(role, text, opts) {
    const host = ensureLogHost();
    const content = safeStr(text);
    if (!host || !content) return null;

    const meta = opts || {};
    const row = document.createElement("div");
    row.className = "chat-msg chat-msg-" + safeStr(role, "system");

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";

    const body = document.createElement("div");
    body.className = "chat-body";
    body.innerHTML = escapeHtml(content).replace(/\n/g, "<br>");

    const foot = document.createElement("div");
    foot.className = "chat-meta";
    foot.textContent = [
      meta.label || role,
      meta.time || formatClock(meta.ts || Date.now()),
    ].filter(Boolean).join(" · ");

    bubble.appendChild(body);
    bubble.appendChild(foot);
    row.appendChild(bubble);
    host.appendChild(row);
    host.scrollTop = host.scrollHeight;

    return row;
  }

  function appendUser(text) {
    return appendMessage("user", text, { label: "You" });
  }

  function appendAssistant(text) {
    const clean = safeStr(text);
    if (!clean) return null;
    if (state.lastAssistantText === clean) return null;
    state.lastAssistantText = clean;
    return appendMessage("assistant", clean, { label: "Assistant" });
  }

  function appendSystem(text) {
    return appendMessage("system", text, { label: "System" });
  }

  function appendError(text) {
    return appendMessage("error", text, { label: "Error" });
  }

  function summarizeResult(result) {
    if (!result || typeof result !== "object") return "Job completed.";
    const structure = safeStr(result.structure_name || result.structure_query || "molecule");
    const jobType = safeStr(result.job_type || "calculation");
    const parts = [jobType + " completed for " + structure];
    if (result.total_energy_hartree !== undefined && result.total_energy_hartree !== null) {
      const e = Number(result.total_energy_hartree);
      if (Number.isFinite(e)) parts.push("E=" + e.toFixed(8) + " Ha");
    }
    if (result.orbital_gap_ev !== undefined && result.orbital_gap_ev !== null) {
      const g = Number(result.orbital_gap_ev);
      if (Number.isFinite(g)) parts.push("gap=" + g.toFixed(3) + " eV");
    }
    return parts.join(" | ");
  }

  function computeJobsCandidates() {
    const pref = normalizePrefix(window.QCVIZ_API_PREFIX || "");
    return unique([
      safeStr(window.QCVIZ_COMPUTE_JOBS_PATH || ""),
      pref ? pref + "/compute/jobs" : "",
      "/api/compute/jobs",
      "/compute/jobs",
    ]);
  }

  function chatCandidates() {
    const pref = normalizePrefix(window.QCVIZ_API_PREFIX || "");
    return unique([
      safeStr(window.QCVIZ_CHAT_PATH || ""),
      pref ? pref + "/chat" : "",
      "/api/chat",
      "/chat",
    ]);
  }

  function wsCandidates() {
    const pref = normalizePrefix(window.QCVIZ_API_PREFIX || "");
    return unique([
      safeStr(window.QCVIZ_WS_PATH || ""),
      pref ? pref + "/ws/chat" : "",
      "/api/ws/chat",
      "/ws/chat",
    ]);
  }

  async function fetchJsonWithFallback(kind, candidates, suffix, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign(
      {
        Accept: "application/json",
      },
      opts.headers || {}
    );

    const cachedBase = state.resolved[kind];
    const bases = unique([cachedBase].concat(candidates || []).filter(Boolean));

    let lastError = null;

    for (const base of bases) {
      const url = joinPath(base, suffix || "");
      try {
        const response = await fetch(url, opts);

        if (!response.ok) {
          const contentType = response.headers.get("content-type") || "";
          let detailText = "";
          try {
            if (contentType.includes("application/json")) {
              detailText = JSON.stringify(await response.json());
            } else {
              detailText = await response.text();
            }
          } catch (_) {}

          const err = new Error("HTTP " + response.status + " for " + url + (detailText ? " :: " + detailText : ""));
          err.status = response.status;
          err.url = url;

          // Only keep falling back for route/path mismatch or method mismatch
          if (response.status === 404 || response.status === 405) {
            lastError = err;
            continue;
          }

          throw err;
        }

        const contentType = response.headers.get("content-type") || "";
        let data;
        if (contentType.includes("application/json")) {
          data = await response.json();
        } else {
          const text = await response.text();
          try {
            data = JSON.parse(text);
          } catch (_) {
            data = { text: text };
          }
        }

        state.resolved[kind] = base;
        return { data, base, url, response };
      } catch (err) {
        if (err && (err.status === 404 || err.status === 405)) {
          lastError = err;
          continue;
        }
        if (err && String(err.message || "").includes("Failed to fetch")) {
          lastError = err;
          continue;
        }
        throw err;
      }
    }

    throw lastError || new Error("All fallback endpoints failed for " + kind);
  }

  function resetActiveJob(jobId) {
    if (state.activeJobId !== jobId) {
      state.activeJobId = jobId || null;
      state.activeJobTerminal = false;
      state.seenEventIds = new Set();
      state.lastProgressKey = null;
    }
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function pollJobOnce(jobId) {
    if (!jobId) return null;
    const suffix = "/" + encodeURIComponent(jobId) + "?include_result=true&include_events=true";
    const result = await fetchJsonWithFallback(
      "computeJobsPath",
      computeJobsCandidates(),
      suffix,
      { method: "GET" }
    );
    return result.data;
  }

  function emitJobEventsFromSnapshot(job) {
    const events = (job && job.events) || [];
    events.forEach((ev) => {
      const eventId = ev && ev.event_id;
      if (eventId && state.seenEventIds.has(eventId)) return;
      if (eventId) state.seenEventIds.add(eventId);

      const type = safeStr(ev && ev.type);
      const msg = safeStr(ev && ev.message);

      if (!msg) return;

      if (type === "job_progress") {
        const prog = ev && ev.data && ev.data.progress;
        const step = safeStr(ev && ev.data && ev.data.step);
        const key = step + "::" + prog + "::" + msg;
        if (state.lastProgressKey === key) return;
        state.lastProgressKey = key;
        setStatus(msg, "working");
        return;
      }

      if (type === "job_failed") {
        appendError(msg);
      } else if (type === "job_completed") {
        appendSystem(msg);
      } else if (type === "job_started") {
        appendSystem(msg);
      } else {
        appendSystem(msg);
      }
    });
  }

  function processTerminalJob(job) {
    if (!job) return;
    if (job.status === "completed") {
      state.activeJobTerminal = true;
      stopPolling();

      if (job.result) {
        setResultPayload(job.result);
        const summary = summarizeResult(job.result);
        appendAssistant(summary);
        setStatus(summary, "ok");
      } else {
        appendAssistant("Job completed.");
        setStatus("Job completed.", "ok");
      }

      setBusy(false);
      updateResultsJobs(job);
      return;
    }

    if (job.status === "failed" || job.status === "error") {
      state.activeJobTerminal = true;
      stopPolling();
      const error = job.error || {};
      const msg = safeStr(error.message || job.message || "Job failed.");
      appendError(msg);
      setStatus(msg, "error");
      setBusy(false);
      updateResultsJobs(job);
    }
  }

  function processJobSnapshot(job) {
    if (!job || typeof job !== "object") return;

    if (job.job_id) {
      resetActiveJob(job.job_id);
    }

    updateResultsJobs(job);

    const status = safeStr(job.status, "running");
    const step = safeStr(job.step, "");
    const message = safeStr(job.message, step || status);

    if (status && status !== "completed" && status !== "failed" && status !== "error") {
      setStatus(message || ("Job " + status), "working");
    }

    emitJobEventsFromSnapshot(job);

    if (status === "completed" || status === "failed" || status === "error") {
      processTerminalJob(job);
    }
  }

  async function startPolling(jobId) {
    if (!jobId) return;
    resetActiveJob(jobId);
    stopPolling();

    const tick = async () => {
      try {
        const job = await pollJobOnce(jobId);
        processJobSnapshot(job);
        if (job && (job.status === "completed" || job.status === "failed" || job.status === "error")) {
          stopPolling();
        }
      } catch (err) {
        console.warn("[QCVizChat] polling failed:", err);
        setStatus("Polling failed; retrying…", "warn");
      }
    };

    await tick();
    if (!state.activeJobTerminal) {
      state.pollTimer = setInterval(tick, 1200);
    }
  }

  function handleServerEvent(msg) {
    if (!msg || typeof msg !== "object") return;

    const type = safeStr(msg.type);
    if (!type) return;

    if (msg.session_id) {
      state.sessionId = safeStr(msg.session_id);
    }

    switch (type) {
      case "ready":
        setStatus("Connected via " + (state.wsPath || "websocket"), "ok");
        if (msg.message) appendSystem(msg.message);
        break;

      case "ack":
        setStatus("Request acknowledged.", "working");
        break;

      case "assistant":
        if (msg.message) appendAssistant(msg.message);
        break;

      case "job_submitted":
        if (msg.job && msg.job.job_id) {
          resetActiveJob(msg.job.job_id);
          appendSystem("Job submitted: " + msg.job.job_id);
          updateResultsJobs(msg.job);
          setStatus("Job submitted.", "working");
        }
        break;

      case "job_update":
        if (msg.job) {
          processJobSnapshot(msg.job);
        }
        break;

      case "job_event":
        if (msg.event) {
          const eventId = msg.event.event_id;
          if (eventId && state.seenEventIds.has(eventId)) break;
          if (eventId) state.seenEventIds.add(eventId);

          const evType = safeStr(msg.event.type);
          const evMessage = safeStr(msg.event.message);

          if (evType === "job_failed") {
            appendError(evMessage || "Job failed.");
          } else if (evType === "job_completed") {
            appendSystem(evMessage || "Job completed.");
          } else if (evType !== "job_progress" && evMessage) {
            appendSystem(evMessage);
          }
        }
        break;

      case "result":
        state.activeJobTerminal = true;
        stopPolling();
        if (msg.job) updateResultsJobs(msg.job);
        if (msg.result) {
          setResultPayload(msg.result);
          appendAssistant(msg.summary || summarizeResult(msg.result));
          setStatus(msg.summary || "Result ready.", "ok");
        } else {
          appendAssistant(msg.summary || "Result ready.");
          setStatus(msg.summary || "Result ready.", "ok");
        }
        setBusy(false);
        break;

      case "error": {
        const err = msg.error || {};
        const text = safeStr(err.message || msg.message || "Request failed.");
        appendError(text);
        setStatus(text, "error");
        setBusy(false);
        break;
      }

      case "heartbeat":
        break;

      default:
        console.debug("[QCVizChat] unhandled event:", msg);
    }
  }

  async function connectWebSocket() {
    if (state.wsConnected && state.ws) return true;
    if (state.wsConnecting) return false;

    state.wsConnecting = true;
    const candidates = wsCandidates();

    for (const path of candidates) {
      const wsUrl = absoluteWsUrl(path);

      try {
        const ok = await new Promise((resolve) => {
          let settled = false;
          let socket = null;
          let timeout = null;

          function done(value) {
            if (settled) return;
            settled = true;
            if (timeout) clearTimeout(timeout);
            resolve(value);
          }

          try {
            socket = new WebSocket(wsUrl);
          } catch (err) {
            console.warn("[QCVizChat] websocket ctor failed:", wsUrl, err);
            done(false);
            return;
          }

          timeout = setTimeout(() => {
            try {
              socket.close();
            } catch (_) {}
            done(false);
          }, 3500);

          socket.addEventListener("open", function () {
            state.ws = socket;
            state.wsConnected = true;
            state.wsPath = path;
            state.resolved.wsPath = path;
            setStatus("WebSocket connected: " + path, "ok");

            socket.addEventListener("message", function (ev) {
              try {
                const data = JSON.parse(ev.data);
                handleServerEvent(data);
              } catch (err) {
                console.warn("[QCVizChat] WS message parse failed:", err, ev.data);
              }
            });

            socket.addEventListener("close", function () {
              if (state.ws === socket) {
                state.ws = null;
                state.wsConnected = false;
                setStatus("WebSocket disconnected; REST fallback enabled.", "warn");
                if (state.activeJobId && !state.activeJobTerminal) {
                  startPolling(state.activeJobId);
                }
              }
            });

            socket.addEventListener("error", function () {
              // keep silent; close handler/promise covers fallback behavior
            });

            done(true);
          });

          socket.addEventListener("error", function () {
            done(false);
          });

          socket.addEventListener("close", function () {
            if (!settled) done(false);
          });
        });

        if (ok) {
          state.wsConnecting = false;
          return true;
        }
      } catch (err) {
        console.warn("[QCVizChat] websocket candidate failed:", path, err);
      }
    }

    state.wsConnecting = false;
    state.wsConnected = false;
    state.ws = null;
    setStatus("WebSocket unavailable; using REST fallback.", "warn");
    return false;
  }

  function sendOverWebSocket(payload) {
    if (!state.ws || !state.wsConnected) {
      throw new Error("WebSocket is not connected.");
    }
    state.ws.send(JSON.stringify(payload));
  }

  async function submitViaChatRest(payload) {
    const res = await fetchJsonWithFallback(
      "chatPath",
      chatCandidates(),
      "",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );

    const data = res.data || {};
    if (data.message) appendAssistant(data.message);
    if (data.plan) {
      // planner info is already reflected in message, so just keep for debug if needed
      console.debug("[QCVizChat] plan:", data.plan);
    }

    if (data.job && data.job.job_id) {
      resetActiveJob(data.job.job_id);
      updateResultsJobs(data.job);
      setStatus("Job submitted via REST chat.", "working");

      if (data.result) {
        setResultPayload(data.result);
        appendAssistant(data.summary || summarizeResult(data.result));
        setBusy(false);
      } else {
        await startPolling(data.job.job_id);
      }
      return data;
    }

    if (data.result) {
      setResultPayload(data.result);
      appendAssistant(data.summary || summarizeResult(data.result));
      setStatus("Result ready.", "ok");
      setBusy(false);
      return data;
    }

    return data;
  }

  async function submitViaComputeRest(payload) {
    const res = await fetchJsonWithFallback(
      "computeJobsPath",
      computeJobsCandidates(),
      "",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );

    const data = res.data || {};
    const job = data.job_id ? data : data.job || data;

    if (job && job.job_id) {
      resetActiveJob(job.job_id);
      updateResultsJobs(job);
      appendSystem("Job submitted via REST: " + job.job_id);
      setStatus("Job submitted via REST.", "working");
      await startPolling(job.job_id);
      return data;
    }

    throw new Error("Compute REST submission did not return a job_id.");
  }

  async function submitMessage(message, extraPayload) {
    const text = safeStr(message);
    if (!text || state.submitting) return;

    ensureSessionId();
    appendUser(text);
    state.lastAssistantText = "";
    setBusy(true);
    clearResultPayload();

    const payload = Object.assign(
      {
        message: text,
        user_message: text,
        session_id: state.sessionId,
      },
      extraPayload || {}
    );

    try {
      const connected = await connectWebSocket();
      if (connected && state.ws && state.wsConnected) {
        sendOverWebSocket(payload);
        return;
      }
    } catch (err) {
      console.warn("[QCVizChat] websocket submit failed, falling back to REST:", err);
    }

    // 1st REST fallback: /api/chat -> /chat
    try {
      await submitViaChatRest(payload);
      return;
    } catch (chatErr) {
      console.warn("[QCVizChat] REST chat fallback failed:", chatErr);
    }

    // 2nd REST fallback: /api/compute/jobs -> /compute/jobs
    try {
      await submitViaComputeRest(payload);
      return;
    } catch (computeErr) {
      console.error("[QCVizChat] all submission paths failed:", computeErr);
      appendError(computeErr.message || "Submission failed.");
      setStatus("Submission failed.", "error");
      setBusy(false);
    }
  }

  async function refreshJobs() {
    try {
      const res = await fetchJsonWithFallback(
        "computeJobsPath",
        computeJobsCandidates(),
        "",
        { method: "GET" }
      );
      const data = res.data || {};
      if (Array.isArray(data.items)) {
        updateResultsJobs(data.items);
      } else {
        updateResultsJobs(data);
      }
      return data;
    } catch (err) {
      console.warn("[QCVizChat] refreshJobs failed:", err);
      return null;
    }
  }

  function bindForm() {
    if (!els.chatForm || !els.chatInput) return;

    els.chatForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const text = safeStr(els.chatInput.value);
      if (!text) return;
      submitMessage(text);
      els.chatInput.value = "";
      els.chatInput.focus();
    });
  }

  function bindQuickPrompts() {
    qsa("[data-chat-prompt], .chat-quick-prompt, .prompt-btn").forEach((btn) => {
      btn.addEventListener("click", function () {
        const prompt = safeStr(
          btn.getAttribute("data-chat-prompt") ||
            btn.dataset.chatPrompt ||
            btn.dataset.prompt ||
            btn.textContent
        );
        if (!prompt) return;
        if (els.chatInput) {
          els.chatInput.value = prompt;
          els.chatInput.focus();
        }
        submitMessage(prompt);
      });
    });
  }

  function bindKeyboard() {
    if (!els.chatInput) return;
    els.chatInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        if (els.chatForm) {
          els.chatForm.requestSubmit();
        }
      }
    });
  }

  function collectDom() {
    els.chatForm = byId("chatForm");
    els.chatInput = byId("chatInput");
    els.chatSend = byId("chatSend");
    els.chatLog = byId("chatLog");
    els.chatStatus = byId("chatStatus");
  }

  function init() {
    collectDom();
    ensureSessionId();
    bindForm();
    bindQuickPrompts();
    bindKeyboard();
    setStatus("Connecting…", "working");

    connectWebSocket()
      .then(function (ok) {
        if (!ok) {
          setStatus("REST fallback mode.", "warn");
        }
      })
      .catch(function () {
        setStatus("REST fallback mode.", "warn");
      });

    refreshJobs().catch(function () {});
  }

  window.QCVizChat = {
    init: init,
    connect: connectWebSocket,
    sendMessage: submitMessage,
    submitMessage: submitMessage,
    refreshJobs: refreshJobs,
    pollJob: startPolling,
    getState: function () {
      return {
        sessionId: state.sessionId,
        wsConnected: state.wsConnected,
        wsPath: state.wsPath,
        activeJobId: state.activeJobId,
        activeJobTerminal: state.activeJobTerminal,
        resolved: Object.assign({}, state.resolved),
      };
    },
    getEndpointCandidates: function () {
      return {
        websocket: wsCandidates().map(absoluteWsUrl),
        computeJobs: computeJobsCandidates().map(absoluteHttpUrl),
        chat: chatCandidates().map(absoluteHttpUrl),
      };
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

```

