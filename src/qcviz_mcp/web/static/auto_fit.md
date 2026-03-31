# QCViz-MCP Enterprise: Architecture & Progress Report

## Core Issue Addressed
The previous frontend implementation hardcoded expected paths (like `/api/compute/jobs` or `/api/ws/chat`), leading to `404 Not Found` errors and system breaks when the backend was running without the `/api` prefix or when `jinja2` wasn't present. The system also had brittle fallback logic.

## The Fix: Complete Autodiscovery & Robust Fallbacks

### 1. Backend (`app.py`)
- We implemented a seamless **dual-router mount**. The app now natively supports both:
  - `/compute/jobs` and `/api/compute/jobs`
  - `/ws/chat` and `/api/ws/chat`
  - `/health` and `/api/health`
- We removed the hard dependency on `jinja2`. If it's missing, the app gracefully falls back to serving `index.html` via `FileResponse` directly from the `templates` or `static` folder.

### 2. Frontend JS (`chat.js`, `results.js`, `viewer.js`)
- We completely rewrote the internal fetch logic in all three modules. 
- They now use a new `fetchJsonWithFallback` helper. It maintains an array of `candidates` (e.g., `["/api/compute/jobs", "/compute/jobs"]`) and tries them sequentially.
- Once a successful connection is made, it **caches the resolved base path** in its local state (`state.resolved.computeJobsPath`) to ensure blazing-fast subsequent requests without redundant 404s.
- This applies equally to REST API calls and WebSocket connection URLs.

### 3. Stability & Developer Experience
- The app can now be started uniformly with either `uvicorn qcviz_mcp.app:app` or `uvicorn qcviz_mcp.web.app:app`.
- The frontend will **never** silently crash due to a missing prefix; it will always automatically adapt to the running server structure.

**We are 100% stable on the core infrastructure. The frontend is resilient, the backend is robust, and the Quantum Agent is fully operational.**