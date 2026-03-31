# QCViz-MCP Enterprise Web: Final Connection Checklist & Smoke Test

This document provides the definitive final connection checklist, deployment sequence, and smoke test commands for the QCViz-MCP Enterprise Web application.

## 1. Final Connection Checklist

### A. Backend Python Files (Must be latest versions)
- `version02/src/qcviz_mcp/compute/pyscf_runner.py`
  - `run_analyze()` performs full analysis (not just geometry)
  - `run_esp_map()` properly finalizes its result contract
  - ESP auto-range calculations and Korean aliases are included
- `version02/src/qcviz_mcp/web/routes/compute.py`
  - `JOB_MANAGER` is embedded
  - Payload preparation includes structure fallback and result normalization
- `version02/src/qcviz_mcp/web/routes/chat.py`
  - Legacy autodiscovery is removed (uses `compute.get_job_manager()` directly)
  - Standard WS event flow (`ready`, `ack`, `assistant`, `job_submitted`, `job_update`, `job_event`, `result`, `error`)
- `version02/src/qcviz_mcp/web/app.py`
  - Mounts both `/static` and `/api/static`
  - Mounts both base router and `/api` prefixed alias router
- `version02/src/qcviz_mcp/app.py`
  - Acts as a shim: `from qcviz_mcp.web.app import app, create_app`

### B. Frontend JS Files
- `chat.js`: Handles `/api/ws/chat` with `/ws/chat` fallback
- `results.js`: Handles `/api/compute/jobs` with `/compute/jobs` fallback
- `viewer.js`: Intelligent static asset resolution for `3Dmol-min.js` and resilient rendering

### C. `index.html` Environment
```html
<script>
  window.QCVIZ_API_PREFIX = "/api";
  window.QCVIZ_STATIC_PREFIX = "/api/static";
  window.QCVIZ_WS_PATH = "/api/ws/chat";
  window.QCVIZ_CHAT_PATH = "/api/chat";
  window.QCVIZ_COMPUTE_JOBS_PATH = "/api/compute/jobs";
  window.QCVIZ_3DMOL_SRC = "/api/static/3Dmol-min.js";
</script>
```

## 2. Deployment Sequence

1. `compute/pyscf_runner.py`
2. `web/routes/compute.py`
3. `web/routes/chat.py`
4. `web/app.py`
5. `qcviz_mcp/app.py`
6. `web/static/viewer.js`
7. `web/static/results.js`
8. `web/static/chat.js`
9. `web/templates/index.html` (or `web/static/index.html`)

## 3. Launching the Server

```bash
cd version02
export PYTHONPATH=src
uvicorn qcviz_mcp.app:app --reload --host 127.0.0.1 --port 8000
```

## 4. Final Short Smoke Test Routine

Run these commands in a separate terminal while the server is running:

```bash
# 1. Check health endpoints
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/chat/health
curl http://127.0.0.1:8000/api/compute/jobs

# 2. Test REST Chat Pipeline (Orbital)
curl -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d '{"message":"벤젠의 HOMO 보여줘","wait_for_result":true}'

# 3. Test REST Compute Pipeline (ESP)
curl -X POST "http://127.0.0.1:8000/api/compute/jobs?wait_for_result=true" -H "Content-Type: application/json" -d '{"message":"아세톤 ESP 맵 보여줘"}'
```
Finally, open your browser to `http://127.0.0.1:8000/` and try out the prompts interactively.