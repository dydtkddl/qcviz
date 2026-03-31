# [백엔드] Job 이력 및 데이터 정규화 고도화

**작업 지시서 (Prompt):**
당신은 최고 수준의 파이썬 백엔드 엔지니어이자 양자화학 AI 시스템 아키텍트입니다.
현재 시스템은 FastAPI, PySCF, 그리고 LLM(Gemini/OpenAI) 기반 Planner가 결합된 QCViz-MCP 엔터프라이즈 서버입니다.

**[작업 목표]**
1. 현재 시스템의 최신 백엔드 소스 코드를 완벽히 분석해주세요. (구조 해석 로직, JobManager, 결과 정규화 등)
2. **'Job History(계산 이력) 관리 기능'**을 최우선으로 강화해주세요. 
   - `InMemoryJobManager`가 과거 모든 작업(성공/실패 포함)을 안정적으로 유지하고, `/api/compute/jobs`를 통해 이를 프론트엔드에 정확히 전달해야 합니다.
   - 특히, 과거 작업의 결과물(Molecule XYZ, Cube 데이터 등)을 다시 조회할 때 유실 없이 반환되도록 보장하세요.
3. **'Charge Labels'** 기능이 프론트에서 완벽히 작동하도록, `pyscf_runner.py`의 결과 페이로드에 원자별 좌표와 전하량이 매핑된 데이터를 정밀하게 포함시켜주세요.
4. 기존의 'Multiwfn급 ESP 스케일링', '한국어/복합어 구조 추출' 등 최신 픽스들을 유지하며 전체적인 코드 품질을 엔터프라이즈급으로 리팩토링해주세요.
5. 수정이 필요한 부분에 대한 완벽한 교체(Replacement) 코드 블록을 마크다운으로 제공해주세요.


---

## 📂 최신 소스 코드 컨텍스트 (Current Context)

### `version02/src/qcviz_mcp/web/app.py`
```python
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from qcviz_mcp.web.routes.chat import router as chat_router
from qcviz_mcp.web.routes.compute import router as compute_router

logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

DEFAULT_TITLE = os.getenv("QCVIZ_APP_TITLE", "QCViz-MCP")
DEFAULT_VERSION = os.getenv("QCVIZ_APP_VERSION", "v2")
DEFAULT_CORS = os.getenv("QCVIZ_CORS_ALLOW_ORIGINS", "*")


def _now_ts() -> float:
    return time.time()


def _split_csv_env(value: str) -> List[str]:
    parts = [x.strip() for x in (value or "").split(",")]
    return [x for x in parts if x] or ["*"]


def _build_templates() -> Any:
    try:
        from fastapi.templating import Jinja2Templates
        if TEMPLATES_DIR.exists() and TEMPLATES_DIR.is_dir():
            return Jinja2Templates(directory=str(TEMPLATES_DIR))
    except Exception:
        pass
    return None


def _fallback_index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>QCViz-MCP</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #0b1020; color: #e6edf3; }
    a { color: #7cc7ff; }
    code { background: rgba(255,255,255,.08); padding: .15rem .35rem; border-radius: 6px; }
    .card { max-width: 960px; padding: 1.25rem 1.5rem; border-radius: 14px; background: #11182d; }
    ul { line-height: 1.7; }
  </style>
</head>
<body>
  <div class="card">
    <h1>QCViz-MCP</h1>
    <p>The template <code>web/templates/index.html</code> was not found.</p>
    <p>Core endpoints are still live:</p>
    <ul>
      <li><a href="/health">/health</a></li>
      <li><a href="/api/health">/api/health</a></li>
      <li><a href="/chat/health">/chat/health</a></li>
      <li><a href="/api/chat/health">/api/chat/health</a></li>
      <li><a href="/compute/health">/compute/health</a></li>
      <li><a href="/api/compute/health">/api/compute/health</a></li>
      <li><code>WS /ws/chat</code></li>
      <li><code>WS /api/ws/chat</code></li>
    </ul>
  </div>
</body>
</html>
"""


def _route_table() -> Dict[str, Any]:
    return {
        "http": {
            "index": "/",
            "health": "/health",
            "chat_health": "/chat/health",
            "compute_health": "/compute/health",
            "chat_rest": "/chat",
            "compute_jobs": "/compute/jobs",
        },
        "api_alias": {
            "health": "/api/health",
            "chat_health": "/api/chat/health",
            "compute_health": "/api/compute/health",
            "chat_rest": "/api/chat",
            "compute_jobs": "/api/compute/jobs",
        },
        "websocket": {
            "chat": "/ws/chat",
            "chat_api_alias": "/api/ws/chat",
        },
        "static": {
            "root": "/static",
            "api_alias": "/api/static",
        },
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title=DEFAULT_TITLE,
        version=DEFAULT_VERSION,
    )

    cors_origins = _split_csv_env(DEFAULT_CORS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    templates = _build_templates()
    app.state.templates = templates

    if STATIC_DIR.exists() and STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        # /api/static/* alias도 같이 제공
        app.mount("/api/static", StaticFiles(directory=str(STATIC_DIR)), name="api-static")
    else:
        logger.warning("Static directory not found: %s", STATIC_DIR)

    # 기본 라우터
    app.include_router(chat_router)
    app.include_router(compute_router)

    # /api alias 라우터
    api_router = APIRouter(prefix="/api")
    api_router.include_router(chat_router)
    api_router.include_router(compute_router)
    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        if templates is not None and (TEMPLATES_DIR / "index.html").exists():
            return templates.TemplateResponse("index.html", {"request": request})
        elif (TEMPLATES_DIR / "index.html").exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(TEMPLATES_DIR / "index.html"))
        elif (STATIC_DIR / "index.html").exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(STATIC_DIR / "index.html"))
        return HTMLResponse(_fallback_index_html())

    @app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
    async def index_html(request: Request):
        return await index(request)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/", include_in_schema=False)
    async def api_root():
        return JSONResponse(
            {
                "ok": True,
                "name": DEFAULT_TITLE,
                "version": DEFAULT_VERSION,
                "timestamp": _now_ts(),
                "routes": _route_table(),
            }
        )

    @app.get("/health")
    @app.get("/api/health", include_in_schema=False)
    async def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "name": DEFAULT_TITLE,
            "version": DEFAULT_VERSION,
            "timestamp": _now_ts(),
            "static_dir": str(STATIC_DIR),
            "templates_dir": str(TEMPLATES_DIR),
            "has_static": STATIC_DIR.exists(),
            "has_templates": TEMPLATES_DIR.exists(),
            "routes": _route_table(),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_redirect():
        # favicon 없어서 404 나는 경우 잡기
        if STATIC_DIR.exists() and (STATIC_DIR / "favicon.ico").exists():
            return RedirectResponse(url="/static/favicon.ico")
        from fastapi.responses import Response
        return Response(status_code=204)

    return app


app = create_app()

__all__ = ["app", "create_app"]
```

### `version02/src/qcviz_mcp/web/routes/chat.py`
```python
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect

from qcviz_mcp.web.routes.compute import (
    TERMINAL_FAILURE,
    TERMINAL_STATES,
    _extract_message,
    _extract_session_id,
    _merge_plan_into_payload,
    _prepare_payload,
    _public_plan_dict,
    _safe_plan_message,
    get_job_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter()

WS_POLL_SECONDS = float(os.getenv("QCVIZ_WS_POLL_SECONDS", "0.25"))


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _parse_client_message(text: str) -> Dict[str, Any]:
    raw = _safe_str(text)
    if not raw:
        return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"message": raw}


def _plan_status_message(plan: Optional[Mapping[str, Any]], payload: Optional[Mapping[str, Any]] = None) -> str:
    plan = dict(plan or {})
    payload = dict(payload or {})

    job_type = _safe_str(payload.get("job_type") or plan.get("job_type") or "analyze")
    structure = _safe_str(payload.get("structure_query") or plan.get("structure_query"))
    method = _safe_str(payload.get("method") or plan.get("method"))
    basis = _safe_str(payload.get("basis") or plan.get("basis"))
    orbital = _safe_str(payload.get("orbital") or plan.get("orbital"))
    esp_preset = _safe_str(payload.get("esp_preset") or plan.get("esp_preset"))
    confidence = plan.get("confidence")

    parts = [f"Plan: {job_type}"]
    if structure:
        parts.append(f"structure={structure}")
    if method:
        parts.append(f"method={method}")
    if basis:
        parts.append(f"basis={basis}")
    if orbital and job_type in {"orbital_preview", "analyze"}:
        parts.append(f"orbital={orbital}")
    if esp_preset and job_type in {"esp_map", "analyze"}:
        parts.append(f"esp_preset={esp_preset}")
    if confidence is not None:
        try:
            parts.append(f"confidence={float(confidence):.2f}")
        except Exception:
            parts.append(f"confidence={confidence}")
    return " | ".join(parts)


def _result_summary(result: Optional[Mapping[str, Any]]) -> str:
    if not result:
        return "Job completed."

    structure = _safe_str(result.get("structure_name") or result.get("structure_query") or "molecule")
    job_type = _safe_str(result.get("job_type") or "calculation")
    energy = result.get("total_energy_hartree")
    gap = result.get("orbital_gap_ev")

    parts = [f"{job_type} completed for {structure}"]
    if energy is not None:
        try:
            parts.append(f"E={float(energy):.8f} Ha")
        except Exception:
            pass
    if gap is not None:
        try:
            parts.append(f"gap={float(gap):.3f} eV")
        except Exception:
            pass
    return " | ".join(parts)


async def _ws_send(websocket: WebSocket, event_type: str, **payload: Any) -> None:
    body = {"type": event_type, **_json_safe(payload)}
    await websocket.send_json(body)


async def _ws_send_error(
    websocket: WebSocket,
    *,
    message: str,
    detail: Optional[Any] = None,
    status_code: int = 400,
    session_id: Optional[str] = None,
) -> None:
    await _ws_send(
        websocket,
        "error",
        session_id=session_id,
        error={
            "message": _safe_str(message, "Request failed"),
            "detail": _json_safe(detail),
            "status_code": status_code,
            "timestamp": _now_ts(),
        },
    )


async def _stream_backend_job_until_terminal(
    websocket: WebSocket,
    *,
    job_id: str,
    session_id: str,
) -> None:
    manager = get_job_manager()
    seen_event_ids = set()
    last_state = None

    while True:
        snap = manager.get(job_id, include_result=False, include_events=True)
        if snap is None:
            await _ws_send_error(
                websocket,
                message="Job not found while streaming.",
                status_code=404,
                session_id=session_id,
            )
            return

        state_key = (
            snap.get("status"),
            snap.get("progress"),
            snap.get("step"),
            snap.get("message"),
        )
        if state_key != last_state:
            await _ws_send(
                websocket,
                "job_update",
                session_id=session_id,
                job=snap,
            )
            last_state = state_key

        for event in snap.get("events", []) or []:
            event_id = event.get("event_id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            await _ws_send(
                websocket,
                "job_event",
                session_id=session_id,
                job_id=job_id,
                event=event,
            )

        if snap.get("status") in TERMINAL_STATES:
            terminal = manager.get(job_id, include_result=True, include_events=True)
            if terminal is None:
                await _ws_send_error(
                    websocket,
                    message="Job disappeared before terminal fetch.",
                    status_code=404,
                    session_id=session_id,
                )
                return

            if terminal.get("status") in TERMINAL_FAILURE:
                await _ws_send_error(
                    websocket,
                    message=((terminal.get("error") or {}).get("message") or terminal.get("message") or "Job failed."),
                    detail=terminal.get("error"),
                    status_code=int(((terminal.get("error") or {}).get("status_code")) or 500),
                    session_id=session_id,
                )
                return

            result = terminal.get("result") or {}
            await _ws_send(
                websocket,
                "result",
                session_id=session_id,
                job=terminal,
                result=result,
                summary=_result_summary(result),
            )
            return

        await asyncio.sleep(WS_POLL_SECONDS)


@router.get("/chat/health")
def chat_health() -> Dict[str, Any]:
    manager = get_job_manager()
    return {
        "ok": True,
        "route": "/chat",
        "ws_route": "/ws/chat",
        "job_backend": manager.__class__.__name__,
        "timestamp": _now_ts(),
    }


@router.post("/chat")
def post_chat(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    raw_message = _extract_message(body)

    plan = _safe_plan_message(raw_message, body) if raw_message else {}
    merged = _merge_plan_into_payload(body, plan, raw_message=raw_message)
    prepared = _prepare_payload(merged)

    plan_message = _plan_status_message(plan, prepared)

    manager = get_job_manager()
    submitted = manager.submit(prepared)

    should_wait = bool(
        wait
        or wait_for_result
        or body.get("wait")
        or body.get("wait_for_result")
        or body.get("sync")
    )

    if should_wait:
        terminal = manager.wait(submitted["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        ok = terminal.get("status") not in TERMINAL_FAILURE
        return {
            "ok": ok,
            "message": plan_message,
            "plan": _public_plan_dict(plan),
            "job": terminal,
            "result": terminal.get("result"),
            "error": terminal.get("error"),
            "summary": _result_summary(terminal.get("result") or {}),
        }

    return {
        "ok": True,
        "message": plan_message,
        "plan": _public_plan_dict(plan),
        "job": submitted,
    }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    default_session_id = f"ws-{int(_now_ts() * 1000)}"
    await _ws_send(
        websocket,
        "ready",
        session_id=default_session_id,
        message="QCViz chat websocket connected.",
        timestamp=_now_ts(),
    )

    try:
        while True:
            raw_text = await websocket.receive_text()
            incoming = _parse_client_message(raw_text)

            session_id = _extract_session_id(incoming) or default_session_id
            user_message = _extract_message(incoming)

            await _ws_send(
                websocket,
                "ack",
                session_id=session_id,
                message=user_message or "Request received.",
                payload=incoming,
                timestamp=_now_ts(),
            )

            plan = _safe_plan_message(user_message, incoming) if user_message else {}
            merged = _merge_plan_into_payload(incoming, plan, raw_message=user_message)

            try:
                prepared = _prepare_payload(merged)
            except HTTPException as exc:
                await _ws_send_error(
                    websocket,
                    message=_safe_str(exc.detail, "Invalid request."),
                    detail={"payload": merged},
                    status_code=exc.status_code,
                    session_id=session_id,
                )
                continue

            await _ws_send(
                websocket,
                "assistant",
                session_id=session_id,
                message=_plan_status_message(plan, prepared),
                plan=_public_plan_dict(plan),
                payload_preview={
                    "job_type": prepared.get("job_type"),
                    "structure_query": prepared.get("structure_query"),
                    "method": prepared.get("method"),
                    "basis": prepared.get("basis"),
                    "orbital": prepared.get("orbital"),
                    "esp_preset": prepared.get("esp_preset"),
                    "advisor_focus_tab": prepared.get("advisor_focus_tab"),
                },
                timestamp=_now_ts(),
            )

            manager = get_job_manager()
            try:
                submitted = manager.submit(prepared)
            except Exception as exc:
                logger.exception("Job submission failed.")
                await _ws_send_error(
                    websocket,
                    message="Job submission failed.",
                    detail={"type": exc.__class__.__name__, "message": str(exc)},
                    status_code=500,
                    session_id=session_id,
                )
                continue

            await _ws_send(
                websocket,
                "job_submitted",
                session_id=session_id,
                job=submitted,
                timestamp=_now_ts(),
            )

            await _stream_backend_job_until_terminal(
                websocket,
                job_id=submitted["job_id"],
                session_id=session_id,
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as exc:
        logger.exception("Unhandled websocket error.")
        try:
            await _ws_send_error(
                websocket,
                message="Unhandled websocket error.",
                detail={"type": exc.__class__.__name__, "message": str(exc)},
                status_code=500,
                session_id=default_session_id,
            )
        except Exception:
            pass


__all__ = ["router"]

```

### `version02/src/qcviz_mcp/web/routes/compute.py`
```python
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:  # pragma: no cover
    QCVizAgent = None  # type: ignore


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])


INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "analyze": "analyze",
    "full_analysis": "analyze",
    "single_point": "single_point",
    "energy": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "optimize": "geometry_optimization",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_ALIASES: Dict[str, str] = {
    "analyze": "analyze",
    "analysis": "analyze",
    "full_analysis": "analyze",
    "singlepoint": "single_point",
    "single_point": "single_point",
    "sp": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "geom": "geometry_analysis",
    "charge": "partial_charges",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "mulliken": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "mo": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "electrostatic_potential": "esp_map",
    "opt": "geometry_optimization",
    "optimize": "geometry_optimization",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "resolve": "resolve_structure",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_TO_RUNNER: Dict[str, str] = {
    "analyze": "run_analyze",
    "single_point": "run_single_point",
    "geometry_analysis": "run_geometry_analysis",
    "partial_charges": "run_partial_charges",
    "orbital_preview": "run_orbital_preview",
    "esp_map": "run_esp_map",
    "geometry_optimization": "run_geometry_optimization",
    "resolve_structure": "run_resolve_structure",
}

TERMINAL_SUCCESS = {"completed"}
TERMINAL_FAILURE = {"failed", "error"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE

DEFAULT_POLL_SECONDS = float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25"))
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "4"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "에텐": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_PAT = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|ωb97x-?d|bp86|blyp)\b",
    re.IGNORECASE,
)
_BASIS_PAT = re.compile(
    r"\b(sto-?3g|3-21g|6-31g\*\*?|6-31g\(d,p\)|6-31g\(d\)|def2-?svp|def2-?tzvp|cc-pvdz|cc-pvtz)\b",
    re.IGNORECASE,
)
_CHARGE_PAT = re.compile(r"(?:charge|전하)\s*[:=]?\s*([+-]?\d+)", re.IGNORECASE)
_MULT_PAT = re.compile(r"(?:multiplicity|spin multiplicity|다중도)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_ORBITAL_PAT = re.compile(
    r"\b(homo(?:\s*-\s*\d+)?|lumo(?:\s*\+\s*\d+)?|mo\s*\d+|orbital\s*\d+)\b",
    re.IGNORECASE,
)
_ESP_PRESET_PAT = re.compile(
    r"\b(acs|rsc|nature|spectral|inferno|viridis|rwb|bwr|greyscale|grayscale|high[_ -]?contrast)\b",
    re.IGNORECASE,
)


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _public_plan_dict(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    return {
        "intent": out.get("intent"),
        "confidence": out.get("confidence"),
        "provider": out.get("provider"),
        "notes": out.get("notes"),
        "job_type": out.get("job_type"),
        "structure_query": out.get("structure_query"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
    }


def _normalize_text_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s가-힣+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "user_message", "text", "prompt", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_session_id(payload: Mapping[str, Any]) -> str:
    for key in ("session_id", "conversation_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_job_type(job_type: Optional[str], intent: Optional[str] = None) -> str:
    jt = _normalize_text_token(job_type).replace(" ", "_")
    if jt in JOB_TYPE_ALIASES:
        return JOB_TYPE_ALIASES[jt]
    intent_key = _normalize_text_token(intent).replace(" ", "_")
    if intent_key in INTENT_TO_JOB_TYPE:
        return INTENT_TO_JOB_TYPE[intent_key]
    return "analyze"


def _normalize_esp_preset(preset: Optional[str]) -> str:
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    if token == "grayscale":
        token = "greyscale"
    if token == "high-contrast":
        token = "high_contrast"
    if token in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}):
        return token
    for key, meta in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}).items():
        aliases = [_normalize_text_token(x).replace(" ", "_") for x in meta.get("aliases", [])]
        if token == key or token in aliases:
            return key
    return "acs"


def _extract_xyz_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    raw = str(text).strip()

    fence = re.search(r"```(?:xyz)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fence:
        block = fence.group(1).strip()
        if block:
            return block

    if "\n" not in raw:
        return None

    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None

    atom_line = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
    if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 3:
        candidate = "\n".join(lines)
        body = lines[2:]
        if body and all(atom_line.match(x.strip()) for x in body):
            return candidate

    atom_lines = [ln for ln in lines if atom_line.match(ln.strip())]
    if len(atom_lines) >= 1 and len(atom_lines) == len(lines):
        return "\n".join(lines)

    return None


def _iter_runner_structure_names() -> Iterable[str]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = getattr(pyscf_runner, name, None)
        if isinstance(lib, Mapping):
            for key in lib.keys():
                s = _safe_str(key)
                if s and s not in seen:
                    seen.add(s)
                    yield s


def _fallback_extract_structure_query(message: str) -> Optional[str]:
    if not message:
        return None
    if _extract_xyz_block(message):
        return None

    normalized = _normalize_text_token(message)

    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in normalized:
            return en_name

    structure_names = list(_iter_runner_structure_names())
    for name in sorted(structure_names, key=len, reverse=True):
        if _normalize_text_token(name) in normalized:
            return name

    patterns = [
        r"(?i)(?:for|of|on|about|analyze|show|render|preview|compute|optimize|calculate)\s+([a-zA-Z][a-zA-Z0-9_\- ]{1,60})",
        r"(?i)([a-zA-Z][a-zA-Z0-9_\- ]{1,60})\s+(?:molecule|structure|system)",
        r"([가-힣A-Za-z0-9_\- ]+?)\s*(?:의)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
        r"([가-힣A-Za-z0-9_\- ]+?)\s+(?:분자|구조)",
    ]
    for pat in patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if not m:
            continue
        candidate = _safe_str(m.group(1))
        candidate_norm = _normalize_text_token(candidate)
        if candidate_norm in _KO_STRUCTURE_ALIASES:
            return _KO_STRUCTURE_ALIASES[candidate_norm]
        for name in structure_names:
            if _normalize_text_token(name) == candidate_norm:
                return name
        if candidate:
            return candidate

    return None


def _heuristic_plan(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    text = message or _extract_message(payload)

    normalized = _normalize_text_token(text)

    intent = "analyze"
    focus = "summary"

    if re.search(r"(homo|lumo|orbital|mo)|오비탈", normalized, re.IGNORECASE):
        intent = "orbital"
        focus = "orbital"
    elif re.search(r"(esp|electrostatic)|정전기|전위", normalized, re.IGNORECASE):
        intent = "esp"
        focus = "esp"
    elif re.search(r"(charge|charges|mulliken)|전하", normalized, re.IGNORECASE):
        intent = "charges"
        focus = "charges"
    elif re.search(r"(opt|optimize|optimization)|최적화", normalized, re.IGNORECASE):
        intent = "optimization"
        focus = "geometry"
    elif re.search(r"(geometry|bond|angle|dihedral)|구조|결합", normalized, re.IGNORECASE):
        intent = "geometry"
        focus = "geometry"
    elif re.search(r"(energy|single point|singlepoint)|에너지", normalized, re.IGNORECASE):
        intent = "single_point"
        focus = "summary"

    method = None
    basis = None
    charge = None
    multiplicity = None
    orbital = None
    esp_preset = None

    m_method = _METHOD_PAT.search(text)
    if m_method:
        method = m_method.group(1)

    m_basis = _BASIS_PAT.search(text)
    if m_basis:
        basis = m_basis.group(1)

    m_charge = _CHARGE_PAT.search(text)
    if m_charge:
        charge = _safe_int(m_charge.group(1))

    m_mult = _MULT_PAT.search(text)
    if m_mult:
        multiplicity = _safe_int(m_mult.group(1))

    m_orb = _ORBITAL_PAT.search(text)
    if m_orb:
        orbital = m_orb.group(1).upper().replace(" ", "")

    m_preset = _ESP_PRESET_PAT.search(text)
    if m_preset:
        esp_preset = _normalize_esp_preset(m_preset.group(1))

    structure_query = _fallback_extract_structure_query(text)

    job_type = _normalize_job_type(payload.get("job_type"), intent)

    return {
        "intent": intent,
        "confidence": 0.55,
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "structure_query": structure_query,
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
    }


@lru_cache(maxsize=1)
def get_qcviz_agent():
    if QCVizAgent is None:
        return None
    try:
        return QCVizAgent()
    except Exception as exc:  # pragma: no cover
        logger.warning("QCVizAgent initialization failed: %s", exc)
        return None


def _coerce_plan_to_dict(plan_obj: Any) -> Dict[str, Any]:
    if plan_obj is None:
        return {}
    if isinstance(plan_obj, Mapping):
        return dict(plan_obj)

    out: Dict[str, Any] = {}
    for key in (
        "intent",
        "confidence",
        "provider",
        "notes",
        "job_type",
        "structure_query",
        "method",
        "basis",
        "charge",
        "multiplicity",
        "orbital",
        "esp_preset",
        "advisor_focus_tab",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out


def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}

    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan_message") and callable(agent.plan_message):
                return _coerce_plan_to_dict(agent.plan_message(message, payload=payload))
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message, payload=payload))
        except TypeError:
            try:
                if hasattr(agent, "plan_message") and callable(agent.plan_message):
                    return _coerce_plan_to_dict(agent.plan_message(message))
                if hasattr(agent, "plan") and callable(agent.plan):
                    return _coerce_plan_to_dict(agent.plan(message))
            except Exception as exc:
                logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)
        except Exception as exc:
            logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)

    return _heuristic_plan(message, payload=payload)


def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})

    intent = _safe_str(plan.get("intent"))
    if not out.get("job_type"):
        out["job_type"] = _normalize_job_type(plan.get("job_type"), intent)

    for key in ("method", "basis", "orbital", "advisor_focus_tab"):
        if not out.get(key) and plan.get(key):
            out[key] = plan.get(key)

    for key in ("charge", "multiplicity"):
        if out.get(key) is None and plan.get(key) is not None:
            out[key] = plan.get(key)

    if not out.get("esp_preset") and plan.get("esp_preset"):
        out["esp_preset"] = _normalize_esp_preset(plan.get("esp_preset"))

    if not out.get("structure_query") and plan.get("structure_query"):
        out["structure_query"] = plan.get("structure_query")

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    if not out.get("structure_query") and not out.get("xyz") and not out.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message or _extract_message(out))
        if fallback:
            out["structure_query"] = fallback

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    return out


def _focus_tab_from_result(result: Mapping[str, Any]) -> str:
    for key in ("advisor_focus_tab", "focus_tab", "default_tab"):
        value = _safe_str(result.get(key))
        if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
            return value
    vis = result.get("visualization") or {}
    if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
        vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
    ):
        return "esp"
    if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"


def _normalize_result_contract(result: Any, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(payload or {})

    if isinstance(result, Mapping):
        out = dict(result)
    else:
        out = {"success": True, "result": _json_safe(result)}

    out.setdefault("success", True)
    out.setdefault("job_type", _normalize_job_type(payload.get("job_type"), payload.get("planner_intent")))
    out.setdefault("structure_query", payload.get("structure_query"))
    out.setdefault("structure_name", payload.get("structure_query") or payload.get("structure_name"))
    out.setdefault("method", payload.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"))
    out.setdefault("basis", payload.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"))
    out.setdefault("charge", _safe_int(payload.get("charge"), 0) or 0)
    out.setdefault("multiplicity", _safe_int(payload.get("multiplicity"), 1) or 1)

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    if out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(out.get("esp_preset") or payload.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_from_result(out))

    if out.get("xyz"):
        vis.setdefault("xyz", out.get("xyz"))
        vis.setdefault("molecule_xyz", out.get("xyz"))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    warnings = out.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [warnings]
    out["warnings"] = [_safe_str(x) for x in warnings if _safe_str(x)]

    if out.get("orbital_gap_hartree") is None and out.get("orbital_gap_ev") is not None:
        try:
            out["orbital_gap_hartree"] = float(out["orbital_gap_ev"]) / float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass
    if out.get("orbital_gap_ev") is None and out.get("orbital_gap_hartree") is not None:
        try:
            out["orbital_gap_ev"] = float(out["orbital_gap_hartree"]) * float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass

    out["advisor_focus_tab"] = _focus_tab_from_result(out)
    out["default_tab"] = out["advisor_focus_tab"]
    return _json_safe(out)


def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    data["job_type"] = _normalize_job_type(data.get("job_type"), data.get("planner_intent"))
    data["method"] = _safe_str(
        data.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
    )
    data["basis"] = _safe_str(
        data.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
    )
    data["charge"] = _safe_int(data.get("charge"), 0) or 0
    data["multiplicity"] = _safe_int(data.get("multiplicity"), 1) or 1

    if data.get("esp_preset"):
        data["esp_preset"] = _normalize_esp_preset(data.get("esp_preset"))

    if not data.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message)
        if xyz_block:
            data["xyz"] = xyz_block

    if not data.get("structure_query") and not data.get("xyz") and not data.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message)
        if fallback:
            data["structure_query"] = fallback

    if data["job_type"] not in {"resolve_structure"}:
        if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec")):
            raise HTTPException(
                status_code=400,
                detail="Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text.",
            )

    return data


def _build_kwargs_for_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    sig = inspect.signature(func)
    kwargs: Dict[str, Any] = {}

    candidate_map = {
        "structure_query": payload.get("structure_query") or payload.get("query"),
        "xyz": payload.get("xyz"),
        "atom_spec": payload.get("atom_spec"),
        "method": payload.get("method"),
        "basis": payload.get("basis"),
        "charge": payload.get("charge"),
        "multiplicity": payload.get("multiplicity"),
        "orbital": payload.get("orbital"),
        "esp_preset": payload.get("esp_preset"),
        "advisor_focus_tab": payload.get("advisor_focus_tab"),
        "user_message": _extract_message(payload),
        "message": _extract_message(payload),
        "progress_callback": progress_callback,
    }

    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

    for name, param in sig.parameters.items():
        if name in candidate_map and candidate_map[name] is not None:
            kwargs[name] = candidate_map[name]

    if accepts_var_kw:
        for key, value in payload.items():
            if key not in kwargs and value is not None:
                kwargs[key] = value
        if progress_callback is not None and "progress_callback" not in kwargs:
            kwargs["progress_callback"] = progress_callback

    return kwargs


def _invoke_callable_adaptive_sync(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Any:
    kwargs = _build_kwargs_for_callable(func, payload, progress_callback=progress_callback)
    return func(**kwargs)


def _run_direct_compute(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    prepared = _prepare_payload(payload)
    job_type = _normalize_job_type(prepared.get("job_type"), prepared.get("planner_intent"))
    runner_name = JOB_TYPE_TO_RUNNER.get(job_type)
    if not runner_name:
        raise HTTPException(status_code=400, detail=f"Unsupported job_type: {job_type}")

    runner = getattr(pyscf_runner, runner_name, None)
    if not callable(runner):
        raise RuntimeError(f"Runner not available: {runner_name}")

    result = _invoke_callable_adaptive_sync(runner, prepared, progress_callback=progress_callback)
    return _normalize_result_contract(result, prepared)


@dataclass
class JobRecord:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    step: str = "queued"
    message: str = "Queued"
    created_at: float = field(default_factory=_now_ts)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    updated_at: float = field(default_factory=_now_ts)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    future: Optional[Future] = None
    event_seq: int = 0


class InMemoryJobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", max_workers)

    def _prune(self) -> None:
        with self.lock:
            if len(self.jobs) <= MAX_JOBS:
                return
            ordered = sorted(self.jobs.values(), key=lambda x: x.created_at)
            removable = [j.job_id for j in ordered if j.status in TERMINAL_STATES]
            while len(self.jobs) > MAX_JOBS and removable:
                jid = removable.pop(0)
                self.jobs.pop(jid, None)

    def _append_event(self, job: JobRecord, event_type: str, message: str, data: Optional[Mapping[str, Any]] = None) -> None:
        job.event_seq += 1
        event = {
            "event_id": job.event_seq,
            "ts": _now_ts(),
            "type": _safe_str(event_type),
            "message": _safe_str(message),
            "data": _json_safe(dict(data or {})),
        }
        job.events.append(event)
        if len(job.events) > MAX_JOB_EVENTS:
            job.events = job.events[-MAX_JOB_EVENTS:]

    def _snapshot(
        self,
        job: JobRecord,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Dict[str, Any]:
        snap = {
            "job_id": job.job_id,
            "status": job.status,
            "progress": float(job.progress),
            "step": job.step,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "updated_at": job.updated_at,
        }
        if include_payload:
            snap["payload"] = _json_safe(job.payload)
        if include_result:
            snap["result"] = _json_safe(job.result)
            snap["error"] = _json_safe(job.error)
        if include_events:
            snap["events"] = _json_safe(job.events)
        return snap

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = dict(payload or {})
        job_id = uuid.uuid4().hex
        record = JobRecord(job_id=job_id, payload=prepared)

        with self.lock:
            self.jobs[job_id] = record
            self._append_event(record, "job_submitted", "Job submitted", {"job_type": prepared.get("job_type")})
            record.future = self.executor.submit(self._run_job, job_id)

        self._prune()
        return self._snapshot(record, include_payload=False, include_result=False, include_events=False)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = _now_ts()
            job.updated_at = job.started_at
            job.step = "starting"
            job.message = "Starting job"
            self._append_event(job, "job_started", "Job started")

        def progress_callback(*args: Any, **kwargs: Any) -> None:
            payload: Dict[str, Any] = {}
            if args and isinstance(args[0], Mapping):
                payload.update(dict(args[0]))
            else:
                if len(args) >= 1:
                    payload["progress"] = args[0]
                if len(args) >= 2:
                    payload["step"] = args[1]
                if len(args) >= 3:
                    payload["message"] = args[2]
            payload.update(kwargs)

            with self.lock:
                record = self.jobs[job_id]
                record.progress = max(0.0, min(1.0, float(_safe_float(payload.get("progress"), record.progress) or 0.0)))
                record.step = _safe_str(payload.get("step"), record.step or "running")
                record.message = _safe_str(payload.get("message"), record.message or record.step or "Running")
                record.updated_at = _now_ts()
                self._append_event(
                    record,
                    "job_progress",
                    record.message,
                    {
                        "progress": record.progress,
                        "step": record.step,
                    },
                )

        try:
            result = _run_direct_compute(job.payload, progress_callback=progress_callback)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "completed"
                job.progress = 1.0
                job.step = "done"
                job.message = "Completed"
                job.result = result
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_completed", "Job completed")
        except HTTPException as exc:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = _safe_str(exc.detail, "Request failed")
                job.error = {
                    "message": _safe_str(exc.detail, "Request failed"),
                    "status_code": exc.status_code,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)
        except Exception as exc:
            logger.exception("Direct compute failed for job %s", job_id)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = str(exc)
                job.error = {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)

    def get(
        self,
        job_id: str,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot(
                job,
                include_payload=include_payload,
                include_result=include_result,
                include_events=include_events,
            )

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [
                self._snapshot(
                    job,
                    include_payload=include_payload,
                    include_result=include_result,
                    include_events=include_events,
                )
                for job in jobs
            ]

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status not in TERMINAL_STATES:
                raise HTTPException(status_code=409, detail="Cannot delete a running job.")
            self.jobs.pop(job_id, None)
            return True

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = _now_ts() + timeout if timeout else None
        while True:
            snap = self.get(job_id, include_payload=False, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in TERMINAL_STATES:
                return snap
            if deadline is not None and _now_ts() >= deadline:
                return snap
            time.sleep(DEFAULT_POLL_SECONDS)


JOB_MANAGER = InMemoryJobManager(max_workers=MAX_WORKERS)


def get_job_manager() -> InMemoryJobManager:
    return JOB_MANAGER


@router.get("/health")
def compute_health() -> Dict[str, Any]:
    agent = get_qcviz_agent()
    provider = None
    if agent is not None:
        provider = getattr(agent, "provider", None) or getattr(agent, "resolved_provider", None)

    return {
        "ok": True,
        "route": "/compute",
        "planner_provider": provider or "heuristic",
        "job_count": len(JOB_MANAGER.list()),
        "max_workers": MAX_WORKERS,
        "timestamp": _now_ts(),
    }


@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    should_wait = bool(sync or wait or wait_for_result or body.get("sync") or body.get("wait") or body.get("wait_for_result"))

    snapshot = JOB_MANAGER.submit(body)

    if should_wait:
        terminal = JOB_MANAGER.wait(snapshot["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return terminal

    return snapshot


@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    return {
        "items": JOB_MANAGER.list(
            include_payload=include_payload,
            include_result=include_result,
            include_events=include_events,
        ),
        "count": len(JOB_MANAGER.list()),
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(
        job_id,
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
    )
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return snap


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_result=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "result": snap.get("result"),
        "error": snap.get("error"),
    }


@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_events=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "events": snap.get("events", []),
    }


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    ok = JOB_MANAGER.delete(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True, "job_id": job_id}


__all__ = [
    "router",
    "JOB_MANAGER",
    "get_job_manager",
    "_extract_message",
    "_extract_session_id",
    "_fallback_extract_structure_query",
    "_merge_plan_into_payload",
    "_normalize_result_contract",
    "_prepare_payload",
    "_public_plan_dict",
    "_safe_plan_message",
]
```

### `version02/src/qcviz_mcp/compute/pyscf_runner.py`
```python
from __future__ import annotations
import re
import os
import base64
import math
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
from pyscf import dft, gto, scf
from pyscf.tools import cubegen

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:  # pragma: no cover
    geometric_optimize = None

# ----------------------------------------------------------------------------
# CONSTANTS & METADATA
# ----------------------------------------------------------------------------

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
BOHR_TO_ANGSTROM = 0.529177210903
EV_TO_KCAL = 23.06054783061903

DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

DEFAULT_ESP_PRESET_ORDER = [
    "acs",
    "rsc",
    "nature",
    "spectral",
    "inferno",
    "viridis",
    "rwb",
    "bwr",
    "greyscale",
    "high_contrast",
]

ESP_PRESETS_DATA: Dict[str, Dict[str, Any]] = {
    "acs": {
        "id": "acs",
        "label": "ACS-style",
        "aliases": ["american chemical society", "acs-style", "science", "default"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Balanced red-white-blue diverging scheme for molecular ESP.",
    },
    "rsc": {
        "id": "rsc",
        "label": "RSC-style",
        "aliases": ["royal society of chemistry", "rsc-style"],
        "surface_scheme": "bwr",
        "default_range_au": 0.055,
        "description": "Soft blue-white-red variant commonly seen in chemistry figures.",
    },
    "nature": {
        "id": "nature",
        "label": "Nature-style",
        "aliases": ["nature-style"],
        "surface_scheme": "spectral",
        "default_range_au": 0.055,
        "description": "Publication-friendly high-separation spectral diverging scheme.",
    },
    "spectral": {
        "id": "spectral",
        "label": "Spectral",
        "aliases": ["rainbow", "diverging"],
        "surface_scheme": "spectral",
        "default_range_au": 0.060,
        "description": "High contrast diverging palette.",
    },
    "inferno": {
        "id": "inferno",
        "label": "Inferno",
        "aliases": [],
        "surface_scheme": "inferno",
        "default_range_au": 0.055,
        "description": "Perceptually uniform warm palette.",
    },
    "viridis": {
        "id": "viridis",
        "label": "Viridis",
        "aliases": [],
        "surface_scheme": "viridis",
        "default_range_au": 0.055,
        "description": "Perceptually uniform scientific palette.",
    },
    "rwb": {
        "id": "rwb",
        "label": "Red-White-Blue",
        "aliases": ["red-white-blue", "red white blue"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Classic negative/neutral/positive diverging palette.",
    },
    "bwr": {
        "id": "bwr",
        "label": "Blue-White-Red",
        "aliases": ["blue-white-red", "blue white red"],
        "surface_scheme": "bwr",
        "default_range_au": 0.060,
        "description": "Classic positive/neutral/negative diverging palette.",
    },
    "greyscale": {
        "id": "greyscale",
        "label": "Greyscale",
        "aliases": ["gray", "grey", "mono", "monochrome"],
        "surface_scheme": "greyscale",
        "default_range_au": 0.050,
        "description": "Monochrome publication palette.",
    },
    "high_contrast": {
        "id": "high_contrast",
        "label": "High Contrast",
        "aliases": ["high-contrast", "contrast"],
        "surface_scheme": "high_contrast",
        "default_range_au": 0.070,
        "description": "Strong contrast for presentations and screenshots.",
    },
}

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_ALIASES: Dict[str, str] = {
    "hf": "HF",
    "rhf": "HF",
    "uhf": "HF",
    "b3lyp": "B3LYP",
    "pbe": "PBE",
    "pbe0": "PBE0",
    "m062x": "M06-2X",
    "m06-2x": "M06-2X",
    "wb97xd": "wB97X-D",
    "ωb97x-d": "wB97X-D",
    "wb97x-d": "wB97X-D",
    "bp86": "BP86",
    "blyp": "BLYP",
}

_BASIS_ALIASES: Dict[str, str] = {
    "sto-3g": "STO-3G",
    "3-21g": "3-21G",
    "6-31g": "6-31G",
    "6-31g*": "6-31G*",
    "6-31g(d)": "6-31G*",
    "6-31g**": "6-31G**",
    "6-31g(d,p)": "6-31G**",
    "def2svp": "def2-SVP",
    "def2-svp": "def2-SVP",
    "def2tzvp": "def2-TZVP",
    "def2-tzvp": "def2-TZVP",
    "cc-pvdz": "cc-pVDZ",
    "cc-pvtz": "cc-pVTZ",
}

_COVALENT_RADII = {
    "H": 0.31,
    "B": 0.85,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
    "Si": 1.11,
}

BUILTIN_XYZ_LIBRARY = {
    "water": "3\n\nO 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469",
    "ammonia": "4\n\nN 0.000 0.000 0.112\nH 0.000 0.938 -0.262\nH 0.812 -0.469 -0.262\nH -0.812 -0.469 -0.262",
    "methane": "5\n\nC 0.000 0.000 0.000\nH 0.627 0.627 0.627\nH -0.627 -0.627 0.627\nH 0.627 -0.627 -0.627\nH -0.627 0.627 -0.627",
    "benzene": "12\n\nC 0.0000 1.3965 0.0000\nC 1.2094 0.6983 0.0000\nC 1.2094 -0.6983 0.0000\nC 0.0000 -1.3965 0.0000\nC -1.2094 -0.6983 0.0000\nC -1.2094 0.6983 0.0000\nH 0.0000 2.4842 0.0000\nH 2.1514 1.2421 0.0000\nH 2.1514 -1.2421 0.0000\nH 0.0000 -2.4842 0.0000\nH -2.1514 -1.2421 0.0000\nH -2.1514 1.2421 0.0000",
    "acetone": "10\n\nC 0.000 0.280 0.000\nO 0.000 1.488 0.000\nC 1.285 -0.551 0.000\nC -1.285 -0.551 0.000\nH 1.266 -1.203 -0.880\nH 1.266 -1.203 0.880\nH 2.155 0.106 0.000\nH -1.266 -1.203 -0.880\nH -1.266 -1.203 0.880\nH -2.155 0.106 0.000",
}

# ----------------------------------------------------------------------------
# CORE UTILS
# ----------------------------------------------------------------------------

def unique(arr):
    seen = set()
    out = []
    for x in arr:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _dedupe_strings(items: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items or []:
        text = _safe_str(item, "")
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out

def _normalize_name_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^0-9a-zA-Z가-힣+\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_method_name(method: Optional[str]) -> str:
    key = _normalize_name_token(method).replace(" ", "")
    return _METHOD_ALIASES.get(key, _safe_str(method, DEFAULT_METHOD) or DEFAULT_METHOD)

def _normalize_basis_name(basis: Optional[str]) -> str:
    key = _normalize_name_token(basis).replace(" ", "")
    return _BASIS_ALIASES.get(key, _safe_str(basis, DEFAULT_BASIS) or DEFAULT_BASIS)

def _normalize_esp_preset(preset: Optional[str]) -> str:
    raw = _normalize_name_token(preset)
    if not raw:
        return "acs"
    compact = raw.replace(" ", "_")
    if compact in ESP_PRESETS_DATA:
        return compact
    for key, meta in ESP_PRESETS_DATA.items():
        aliases = [_normalize_name_token(a).replace(" ", "_") for a in meta.get("aliases", [])]
        if compact == key or compact in aliases:
            return key
    if compact in {"default", "auto"}:
        return "acs"
    return "acs"

def _looks_like_xyz(text: Optional[str]) -> bool:
    if not text:
        return False
    s = str(text).strip()
    if "\n" in s:
        lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[2:]
        atom_pat = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
        atom_lines = [ln for ln in lines if atom_pat.match(ln.strip())]
        return len(atom_lines) >= 1
    return False

def _strip_xyz_header(xyz_text: str) -> str:
    lines = [ln.rstrip() for ln in (xyz_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) >= 3 and re.fullmatch(r"\d+", lines[0].strip()):
        lines = lines[2:]
    return "\n".join(lines).strip()

def _iter_structure_libraries() -> Iterable[Mapping[str, str]]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = globals().get(name)
        if isinstance(lib, Mapping) and id(lib) not in seen:
            seen.add(id(lib))
            yield lib

def _lookup_builtin_xyz(query: Optional[str]) -> Optional[Tuple[str, str]]:
    if not query:
        return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    
    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\\b{n}\\b", " ", qc, flags=re.I)
    qc = re.sub(r"\\s+", " ", qc).strip()
    
    candidates = unique([q0, qn, qc, qn.replace(" ", "_"), qn.replace(" ", ""), qc.replace(" ", "_"), qc.replace(" ", "")])
    
    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map = {}
        for key, value in lib.items():
            if not isinstance(value, str): continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
            
        for cand in candidates:
            if cand in normalized_map: return normalized_map[cand]
        
        for kn, pair in normalized_map.items():
            if len(kn) > 2 and (kn in qn or kn in qc):
                return pair
    return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    
    # Try direct mapping and common transforms
    candidates = [q0, qn, qn.replace(" ", "_"), qn.replace(" ", "")]
    
    # Try Korean aliases (substring match)
    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
            
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
    return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    candidates = [q0, qn, qn.replace(" ", "_"), qn.replace(" ", "")]
    if qn in _KO_STRUCTURE_ALIASES:
        alias = _KO_STRUCTURE_ALIASES[qn]
        candidates.extend([alias, alias.replace("_", " "), alias.replace("_", "")])
    if q0 in _KO_STRUCTURE_ALIASES:
        alias = _KO_STRUCTURE_ALIASES[q0]
        candidates.extend([alias, alias.replace("_", " "), alias.replace("_", "")])

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            normalized_map[_normalize_name_token(k)] = (k, value)
            normalized_map[_normalize_name_token(k).replace(" ", "_")] = (k, value)
            normalized_map[_normalize_name_token(k).replace(" ", "")] = (k, value)
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
    return None

def _resolve_structure_payload(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
) -> Tuple[str, str]:
    if atom_spec and _safe_str(atom_spec):
        return _safe_str(structure_query, "custom"), _safe_str(atom_spec).strip()

    if xyz and _safe_str(xyz):
        atom_text = _strip_xyz_header(_safe_str(xyz))
        if atom_text:
            return _safe_str(structure_query, "custom"), atom_text

    if structure_query and _looks_like_xyz(structure_query):
        atom_text = _strip_xyz_header(_safe_str(structure_query))
        if atom_text:
            return "custom", atom_text

    if structure_query:
        hit = _lookup_builtin_xyz(structure_query)
        if hit:
            label, xyz_text = hit
            atom_text = _strip_xyz_header(xyz_text)
            return label, atom_text

    raise ValueError("No structure could be resolved; provide query, XYZ, or atom-spec text.")

def _mol_to_xyz(mol: gto.Mole, comment: str = "") -> str:
    coords = mol.atom_coords(unit="Angstrom")
    lines = [str(mol.natm), comment or "QCViz-MCP"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        x, y, z = coords[i]
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    return "\n".join(lines)

def _build_mol(
    atom_text: str,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    unit: str = "Angstrom",
) -> gto.Mole:
    basis_name = _normalize_basis_name(basis or DEFAULT_BASIS)
    spin = max(int(multiplicity or 1) - 1, 0)
    return gto.M(
        atom=atom_text,
        basis=basis_name,
        charge=int(charge or 0),
        spin=spin,
        unit=unit,
        verbose=0,
    )

def _build_mean_field(mol: gto.Mole, method: Optional[str] = None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))
    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf

    xc_map = {
        "b3lyp": "b3lyp",
        "pbe": "pbe",
        "pbe0": "pbe0",
        "m06-2x": "m06-2x",
        "m062x": "m06-2x",
        "wb97x-d": "wb97x-d",
        "ωb97x-d": "wb97x-d",
        "wb97x-d": "wb97x-d",
        "bp86": "bp86",
        "blyp": "blyp",
    }
    xc = xc_map.get(key, "b3lyp")
    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass
    return method_name, mf

def _run_scf_with_fallback(mf, warnings: Optional[List[str]] = None):
    warnings = warnings if warnings is not None else []
    try:
        mf.conv_tol = min(getattr(mf, "conv_tol", 1e-9), 1e-9)
    except Exception:
        pass
    try:
        mf.max_cycle = max(int(getattr(mf, "max_cycle", 50)), 100)
    except Exception:
        pass

    energy = mf.kernel()
    if getattr(mf, "converged", False):
        return mf, energy

    warnings.append("Primary SCF did not converge; attempting Newton refinement.")
    try:
        mf = mf.newton()
        energy = mf.kernel()
    except Exception as exc:
        warnings.append(f"Newton refinement failed: {exc}")

    return mf, energy

def _file_to_b64(path: Union[str, Path, None]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")

def _parse_cube_values(path: Union[str, Path]) -> np.ndarray:
    p = Path(path)
    text = p.read_text(errors="ignore").splitlines()
    if len(text) < 7:
        return np.array([], dtype=float)

    try:
        natm = abs(int(text[2].split()[0]))
        data_start = 6 + natm
    except Exception:
        data_start = 6

    values: List[float] = []
    for line in text[data_start:]:
        for token in line.split():
            try:
                values.append(float(token))
            except Exception:
                continue
    return np.asarray(values, dtype=float)

def _nice_symmetric_limit(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.05
    if value < 0.02:
        step = 0.0025
    elif value < 0.05:
        step = 0.005
    elif value < 0.10:
        step = 0.010
    else:
        step = 0.020
    return float(math.ceil(value / step) * step)

def _compute_esp_auto_range(
    esp_values: np.ndarray,
    density_values: Optional[np.ndarray] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    arr = np.asarray(esp_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        default_au = ESP_PRESETS_DATA["acs"]["default_range_au"]
        return {
            "range_au": default_au,
            "range_kcal": default_au * HARTREE_TO_KCAL,
            "stats": {},
            "strategy": "default",
        }

    masked = arr
    if density_values is not None:
        dens = np.asarray(density_values, dtype=float).ravel()
        if dens.size == arr.size:
            dens = dens[np.isfinite(dens)]
            if dens.size == arr.size:
                low = density_iso * 0.35
                high = density_iso * 4.0
                mask = (density_values.ravel() >= low) & (density_values.ravel() <= high)
                mask = mask & np.isfinite(esp_values.ravel())
                if np.count_nonzero(mask) >= 128:
                    masked = np.asarray(esp_values, dtype=float).ravel()[mask]

    masked = masked[np.isfinite(masked)]
    if masked.size < 32:
        masked = arr

    abs_vals = np.abs(masked)
    p90 = float(np.percentile(abs_vals, 90))
    p95 = float(np.percentile(abs_vals, 95))
    p98 = float(np.percentile(abs_vals, 98))
    p995 = float(np.percentile(abs_vals, 99.5))
    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995
    robust = float(np.clip(robust, 0.02, 0.18))
    nice = _nice_symmetric_limit(robust)

    return {
        "range_au": nice,
        "range_kcal": nice * HARTREE_TO_KCAL,
        "stats": {
            "n": int(masked.size),
            "min_au": float(np.min(masked)),
            "max_au": float(np.max(masked)),
            "mean_au": float(np.mean(masked)),
            "std_au": float(np.std(masked)),
            "p90_abs_au": p90,
            "p95_abs_au": p95,
            "p98_abs_au": p98,
            "p995_abs_au": p995,
        },
        "strategy": "robust_surface_shell_percentile",
    }

def _compute_esp_auto_range_from_cube_files(
    esp_cube_path: Union[str, Path],
    density_cube_path: Optional[Union[str, Path]] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    try:
        esp_values = _parse_cube_values(esp_cube_path)
    except Exception:
        esp_values = np.array([], dtype=float)
    density_values = None
    if density_cube_path:
        try:
            density_values = _parse_cube_values(density_cube_path)
        except Exception:
            density_values = None
    return _compute_esp_auto_range(esp_values, density_values=density_values, density_iso=density_iso)

def _formula_from_symbols(symbols: Sequence[str]) -> str:
    counts = Counter(symbols)
    if not counts:
        return ""
    ordered: List[Tuple[str, int]] = []
    if "C" in counts:
        ordered.append(("C", counts.pop("C")))
    if "H" in counts:
        ordered.append(("H", counts.pop("H")))
    for key in sorted(counts):
        ordered.append((key, counts[key]))
    return "".join(f"{el}{n if n != 1 else ''}" for el, n in ordered)

def _guess_bonds(mol: gto.Mole) -> List[Dict[str, Any]]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds: List[Dict[str, Any]] = []
    for i in range(mol.natm):
        for j in range(i + 1, mol.natm):
            ri = _COVALENT_RADII.get(symbols[i], 0.77)
            rj = _COVALENT_RADII.get(symbols[j], 0.77)
            cutoff = 1.25 * (ri + rj)
            dist = float(np.linalg.norm(coords[i] - coords[j]))
            if 0.1 < dist <= cutoff:
                bonds.append(
                    {
                        "a": i,
                        "b": j,
                        "order": 1,
                        "length_angstrom": dist,
                    }
                )
    return bonds

def _normalize_partial_charges(mol: gto.Mole, charges: Optional[Sequence[float]]) -> List[Dict[str, Any]]:
    if charges is None:
        return []
    out: List[Dict[str, Any]] = []
    for i, q in enumerate(charges):
        out.append(
            {
                "atom_index": i,
                "symbol": mol.atom_symbol(i),
                "charge": float(q),
            }
        )
    return out

def _geometry_summary(mol: gto.Mole, bonds: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    centroid = coords.mean(axis=0) if len(coords) else np.zeros(3)
    bbox_min = coords.min(axis=0) if len(coords) else np.zeros(3)
    bbox_max = coords.max(axis=0) if len(coords) else np.zeros(3)
    dims = bbox_max - bbox_min
    bond_lengths = [float(b["length_angstrom"]) for b in (bonds or []) if "length_angstrom" in b]
    return {
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "centroid_angstrom": [float(x) for x in centroid],
        "bbox_min_angstrom": [float(x) for x in bbox_min],
        "bbox_max_angstrom": [float(x) for x in bbox_max],
        "bbox_size_angstrom": [float(x) for x in dims],
        "bond_count": int(len(bonds or [])),
        "bond_length_min_angstrom": float(min(bond_lengths)) if bond_lengths else None,
        "bond_length_max_angstrom": float(max(bond_lengths)) if bond_lengths else None,
        "bond_length_mean_angstrom": float(np.mean(bond_lengths)) if bond_lengths else None,
    }

def _extract_dipole(mf) -> Optional[Dict[str, Any]]:
    try:
        vec = np.asarray(mf.dip_moment(unit="Debye", verbose=0), dtype=float).ravel()
        if vec.size >= 3:
            return {
                "x": float(vec[0]),
                "y": float(vec[1]),
                "z": float(vec[2]),
                "magnitude": float(np.linalg.norm(vec[:3])),
                "unit": "Debye",
            }
    except Exception:
        return None
    return None

def _extract_mulliken_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
    dm = mf.make_rdm1()
    if isinstance(dm, tuple):
        dm = np.asarray(dm[0]) + np.asarray(dm[1])
    dm = np.asarray(dm)
    if dm.ndim == 3:
        dm = dm[0] + dm[1]
    try:
        _, chg = mf.mulliken_pop(mol=mol, dm=dm, verbose=0)
    except TypeError:
        _, chg = mf.mulliken_pop(mol, dm, verbose=0)
    except Exception:
        from pyscf.scf import hf as scf_hf
        s = mol.intor_symmetric("int1e_ovlp")
        _, chg = scf_hf.mulliken_pop(mol, dm, s=s, verbose=0)
    return _normalize_partial_charges(mol, chg)

def _restricted_or_unrestricted_arrays(mf):
    mo_energy = mf.mo_energy
    mo_occ = mf.mo_occ
    mo_coeff = mf.mo_coeff
    if isinstance(mo_energy, tuple):
        return list(mo_energy), list(mo_occ), list(mo_coeff), ["alpha", "beta"]
    if isinstance(mo_energy, list) and mo_energy and isinstance(mo_energy[0], np.ndarray):
        return list(mo_energy), list(mo_occ), list(mo_coeff), ["alpha", "beta"][: len(mo_energy)]
    return [np.asarray(mo_energy)], [np.asarray(mo_occ)], [np.asarray(mo_coeff)], ["restricted"]

def _build_orbital_items(mf, window: int = 4) -> List[Dict[str, Any]]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    items: List[Dict[str, Any]] = []
    for ch, (energies, occs, spin_label) in enumerate(zip(mo_energies, mo_occs, spin_labels)):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)
        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0:
            lo = 0
            hi = min(len(energies), 2 * window + 1)
        else:
            homo = int(occ_idx[-1])
            lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
            lo = max(0, homo - window)
            hi = min(len(energies), lumo + window + 1)
        for idx in range(lo, hi):
            occ = float(occs[idx])
            label = f"MO {idx + 1}"
            if occ_idx.size:
                homo = int(occ_idx[-1])
                lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
                if idx == homo:
                    label = "HOMO"
                elif idx < homo:
                    label = f"HOMO-{homo - idx}"
                elif idx == lumo:
                    label = "LUMO"
                elif idx > lumo:
                    label = f"LUMO+{idx - lumo}"
            items.append(
                {
                    "index": idx + 1,
                    "zero_based_index": idx,
                    "label": label,
                    "spin": spin_label,
                    "occupancy": occ,
                    "energy_hartree": float(energies[idx]),
                    "energy_ev": float(energies[idx] * HARTREE_TO_EV),
                }
            )
    items.sort(key=lambda x: (x.get("spin") != "restricted", x["zero_based_index"]))
    return items

def _resolve_orbital_selection(mf, orbital: Optional[Union[str, int]]) -> Dict[str, Any]:
    mo_energies, mo_occs, mo_coeffs, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel = 0
    spin_label = spin_labels[channel]
    energies = np.asarray(mo_energies[channel], dtype=float)
    occs = np.asarray(mo_occs[channel], dtype=float)

    occ_idx = np.where(occs > 1e-8)[0]
    vir_idx = np.where(occs <= 1e-8)[0]
    homo = int(occ_idx[-1]) if occ_idx.size else 0
    lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)

    raw = _safe_str(orbital, "HOMO").upper()
    if raw in {"", "AUTO"}:
        raw = "HOMO"

    idx = homo
    label = "HOMO"

    if isinstance(orbital, int):
        idx = max(0, min(int(orbital) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif re.fullmatch(r"\d+", raw):
        idx = max(0, min(int(raw) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif raw == "HOMO":
        idx = homo
        label = "HOMO"
    elif raw == "LUMO":
        idx = lumo
        label = "LUMO"
    else:
        m1 = re.fullmatch(r"HOMO\s*-\s*(\d+)", raw)
        m2 = re.fullmatch(r"LUMO\s*\+\s*(\d+)", raw)
        if m1:
            delta = int(m1.group(1))
            idx = max(0, homo - delta)
            label = f"HOMO-{delta}"
        elif m2:
            delta = int(m2.group(1))
            idx = min(len(energies) - 1, lumo + delta)
            label = f"LUMO+{delta}"

    return {
        "spin_channel": channel,
        "spin": spin_label,
        "index": idx + 1,
        "zero_based_index": idx,
        "label": label,
        "energy_hartree": float(energies[idx]),
        "energy_ev": float(energies[idx] * HARTREE_TO_EV),
        "occupancy": float(occs[idx]),
    }

def _extract_frontier_gap(mf) -> Dict[str, Any]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel_info: List[Dict[str, Any]] = []
    best_gap = None
    best_homo = None
    best_lumo = None

    for energies, occs, spin_label in zip(mo_energies, mo_occs, spin_labels):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)

        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0 or vir_idx.size == 0:
            continue

        homo_idx = int(occ_idx[-1])
        lumo_idx = int(vir_idx[0])
        gap_ha = float(energies[lumo_idx] - energies[homo_idx])

        info = {
            "spin": spin_label,
            "homo_index": homo_idx + 1,
            "lumo_index": lumo_idx + 1,
            "homo_energy_hartree": float(energies[homo_idx]),
            "lumo_energy_hartree": float(energies[lumo_idx]),
            "homo_energy_ev": float(energies[homo_idx] * HARTREE_TO_EV),
            "lumo_energy_ev": float(energies[lumo_idx] * HARTREE_TO_EV),
            "gap_hartree": gap_ha,
            "gap_ev": gap_ha * HARTREE_TO_EV,
        }
        channel_info.append(info)

        if best_gap is None or gap_ha < best_gap:
            best_gap = gap_ha
            best_homo = info
            best_lumo = info

    out: Dict[str, Any] = {
        "frontier_channels": channel_info,
        "orbital_gap_hartree": float(best_gap) if best_gap is not None else None,
        "orbital_gap_ev": float(best_gap * HARTREE_TO_EV) if best_gap is not None else None,
    }

    if best_homo:
        out["homo_energy_hartree"] = best_homo["homo_energy_hartree"]
        out["homo_energy_ev"] = best_homo["homo_energy_ev"]
        out["homo_index"] = best_homo["homo_index"]
    if best_lumo:
        out["lumo_energy_hartree"] = best_lumo["lumo_energy_hartree"]
        out["lumo_energy_ev"] = best_lumo["lumo_energy_ev"]
        out["lumo_index"] = best_lumo["lumo_index"]
    return out

def _extract_spin_info(mf) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        ss = mf.spin_square()
        if isinstance(ss, tuple) and len(ss) >= 2:
            info["spin_square"] = float(ss[0])
            info["spin_multiplicity_estimate"] = float(ss[1])
    except Exception:
        pass
    return info

def _coalesce_density_matrix(dm) -> np.ndarray:
    if isinstance(dm, tuple):
        return np.asarray(dm[0]) + np.asarray(dm[1])
    dm_arr = np.asarray(dm)
    if dm_arr.ndim == 3 and dm_arr.shape[0] == 2:
        return dm_arr[0] + dm_arr[1]
    return dm_arr

def _selected_orbital_vector(mf, selection: Mapping[str, Any]) -> np.ndarray:
    coeff = mf.mo_coeff
    ch = int(selection.get("spin_channel", 0) or 0)
    idx = int(selection.get("zero_based_index", 0) or 0)

    if isinstance(coeff, tuple):
        coeff_mat = np.asarray(coeff[ch])
    elif isinstance(coeff, list) and coeff and isinstance(coeff[0], np.ndarray):
        coeff_mat = np.asarray(coeff[ch])
    else:
        coeff_mat = np.asarray(coeff)

    return np.asarray(coeff_mat[:, idx], dtype=float)

def _emit_progress(
    progress_callback: Optional[Callable[..., Any]],
    progress: float,
    step: str,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    if not callable(progress_callback):
        return

    payload = {
        "progress": float(progress),
        "step": _safe_str(step, "working"),
        "message": _safe_str(message, message or step),
    }
    payload.update(extra)

    try:
        progress_callback(payload)
        return
    except TypeError:
        pass
    except Exception:
        return

    try:
        progress_callback(float(progress), _safe_str(step, "working"), payload["message"])
    except Exception:
        return

def _focus_tab_for_result(result: Mapping[str, Any]) -> str:
    forced = _safe_str(result.get("advisor_focus_tab") or result.get("focus_tab") or result.get("default_tab"))
    forced = forced.lower()
    if forced in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
        return forced

    vis = result.get("visualization") or {}
    if vis.get("esp_cube_b64") and vis.get("density_cube_b64"):
        return "esp"
    if vis.get("orbital_cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"

def _attach_visualization_payload(
    result: Dict[str, Any],
    xyz_text: str,
    orbital_cube_path: Optional[Union[str, Path]] = None,
    density_cube_path: Optional[Union[str, Path]] = None,
    esp_cube_path: Optional[Union[str, Path]] = None,
    orbital_meta: Optional[Mapping[str, Any]] = None,
    esp_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    vis = result.setdefault("visualization", {})
    vis["xyz"] = xyz_text
    vis["molecule_xyz"] = xyz_text
    result["xyz"] = result.get("xyz") or xyz_text

    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)

    if orbital_cube_path:
        orb_b64 = _file_to_b64(orbital_cube_path)
        if orb_b64:
            vis["orbital_cube_b64"] = orb_b64
            result["orbital_cube_b64"] = orb_b64
            orb_node = vis.setdefault("orbital", {})
            orb_node["cube_b64"] = orb_b64
            if orbital_meta:
                orb_node.update(dict(orbital_meta))
                if orbital_meta.get("label"):
                    defaults.setdefault("orbital_label", orbital_meta.get("label"))
                if orbital_meta.get("index") is not None:
                    defaults.setdefault("orbital_index", orbital_meta.get("index"))

    if density_cube_path:
        dens_b64 = _file_to_b64(density_cube_path)
        if dens_b64:
            vis["density_cube_b64"] = dens_b64
            result["density_cube_b64"] = dens_b64
            dens_node = vis.setdefault("density", {})
            dens_node["cube_b64"] = dens_b64

    if esp_cube_path:
        esp_b64 = _file_to_b64(esp_cube_path)
        if esp_b64:
            vis["esp_cube_b64"] = esp_b64
            result["esp_cube_b64"] = esp_b64
            esp_node = vis.setdefault("esp", {})
            esp_node["cube_b64"] = esp_b64

            if esp_meta:
                esp_node.update(dict(esp_meta))
                preset = _normalize_esp_preset(esp_meta.get("preset"))
                preset_meta = ESP_PRESETS_DATA.get(preset, ESP_PRESETS_DATA["acs"])
                esp_node["preset"] = preset
                esp_node["surface_scheme"] = preset_meta.get("surface_scheme", "rwb")

                defaults.setdefault("esp_preset", preset)
                defaults.setdefault("esp_scheme", preset_meta.get("surface_scheme", "rwb"))
                if esp_meta.get("range_au") is not None:
                    defaults["esp_range"] = float(esp_meta["range_au"])
                    defaults["esp_range_au"] = float(esp_meta["range_au"])
                if esp_meta.get("range_kcal") is not None:
                    defaults["esp_range_kcal"] = float(esp_meta["range_kcal"])
                if esp_meta.get("density_iso") is not None:
                    defaults["esp_density_iso"] = float(esp_meta["density_iso"])
                if esp_meta.get("opacity") is not None:
                    defaults["esp_opacity"] = float(esp_meta["opacity"])

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64")),
        "esp": bool(vis.get("esp_cube_b64") and vis.get("density_cube_b64")),
        "density": bool(vis.get("density_cube_b64")),
    }
    defaults.setdefault("focus_tab", _focus_tab_for_result(result))
    return result

def _finalize_result_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(result or {})
    out.setdefault("success", True)
    out.setdefault("warnings", [])
    out["warnings"] = _dedupe_strings(out.get("warnings", []))

    if not isinstance(out.get("events"), list):
        out["events"] = []

    out["method"] = _normalize_method_name(out.get("method") or DEFAULT_METHOD)
    out["basis"] = _normalize_basis_name(out.get("basis") or DEFAULT_BASIS)
    out["charge"] = int(_safe_int(out.get("charge"), 0) or 0)
    out["multiplicity"] = int(_safe_int(out.get("multiplicity"), 1) or 1)

    e_ha = _safe_float(out.get("total_energy_hartree"))
    if e_ha is not None:
        out["total_energy_hartree"] = e_ha
        out.setdefault("total_energy_ev", e_ha * HARTREE_TO_EV)
        out.setdefault("total_energy_kcal_mol", e_ha * HARTREE_TO_KCAL)

    gap_ha = _safe_float(out.get("orbital_gap_hartree"))
    gap_ev = _safe_float(out.get("orbital_gap_ev"))
    if gap_ha is None and gap_ev is not None:
        out["orbital_gap_hartree"] = gap_ev / HARTREE_TO_EV
    elif gap_ev is None and gap_ha is not None:
        out["orbital_gap_ev"] = gap_ha * HARTREE_TO_EV

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    elif out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(defaults.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_for_result(out))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis.setdefault("xyz", out.get("xyz"))
    vis.setdefault("molecule_xyz", out.get("xyz"))
    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    return out

def _make_base_result(
    *,
    job_type: str,
    structure_name: str,
    atom_text: str,
    mol: gto.Mole,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    advisor_focus_tab: Optional[str] = None,
) -> Dict[str, Any]:
    xyz_text = _mol_to_xyz(mol, comment=structure_name or "QCViz-MCP")
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds = _guess_bonds(mol)

    result: Dict[str, Any] = {
        "success": True,
        "job_type": _safe_str(job_type, "analyze"),
        "structure_name": _safe_str(structure_name, "custom"),
        "structure_query": _safe_str(structure_name, "custom"),
        "atom_spec": atom_text,
        "xyz": xyz_text,
        "method": _normalize_method_name(method or DEFAULT_METHOD),
        "basis": _normalize_basis_name(basis or DEFAULT_BASIS),
        "charge": int(charge or 0),
        "multiplicity": int(multiplicity or 1),
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "bonds": bonds,
        "geometry_summary": _geometry_summary(mol, bonds),
        "warnings": [],
        "events": [],
        "advisor_focus_tab": advisor_focus_tab,
        "visualization": {
            "xyz": xyz_text,
            "molecule_xyz": xyz_text,
            "defaults": {
                "style": "stick",
                "labels": False,
                "orbital_iso": 0.050,
                "orbital_opacity": 0.85,
                "esp_density_iso": 0.001,
                "esp_opacity": 0.90,
            },
        },
    }
    return _finalize_result_contract(result)

def _populate_scf_fields(
    result: Dict[str, Any],
    mol: gto.Mole,
    mf,
    *,
    include_charges: bool = True,
    include_orbitals: bool = True,
) -> Dict[str, Any]:
    result["scf_converged"] = bool(getattr(mf, "converged", False))
    result["total_energy_hartree"] = float(getattr(mf, "e_tot", np.nan))
    result["total_energy_ev"] = float(result["total_energy_hartree"] * HARTREE_TO_EV)
    result["total_energy_kcal_mol"] = float(result["total_energy_hartree"] * HARTREE_TO_KCAL)

    dip = _extract_dipole(mf)
    if dip:
        result["dipole_moment"] = dip

    result.update(_extract_frontier_gap(mf))
    result.update(_extract_spin_info(mf))

    if include_charges:
        try:
            charges = _extract_mulliken_charges(mol, mf)
            result["mulliken_charges"] = charges
            result["partial_charges"] = charges
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Charge analysis failed: {exc}")

    if include_orbitals:
        try:
            result["orbitals"] = _build_orbital_items(mf)
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Orbital analysis failed: {exc}")

    return result

def _prepare_structure_bundle(
    *,
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
) -> Tuple[str, str, gto.Mole]:
    structure_name, atom_text = _resolve_structure_payload(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
    )
    mol = _build_mol(
        atom_text=atom_text,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        unit="Angstrom",
    )
    return structure_name, atom_text, mol

# ----------------------------------------------------------------------------
# PUBLIC RUNNER FUNCTIONS
# ----------------------------------------------------------------------------

def run_resolve_structure(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )
    _emit_progress(progress_callback, 0.75, "geometry", "Preparing geometry payload")

    result = _make_base_result(
        job_type="resolve_structure",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    result["resolved_structure"] = {
        "name": structure_name,
        "xyz": result["xyz"],
        "atom_spec": atom_text,
    }

    _emit_progress(progress_callback, 1.0, "done", "Structure resolved")
    return _finalize_result_contract(result)

def run_geometry_analysis(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="geometry_analysis",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    result["atoms"] = [
        {
            "atom_index": i,
            "symbol": symbols[i],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "z": float(coords[i, 2]),
        }
        for i in range(mol.natm)
    ]

    _emit_progress(progress_callback, 1.0, "done", "Geometry analysis complete")
    return _finalize_result_contract(result)

def run_single_point(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="single_point",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])

    _emit_progress(progress_callback, 0.85, "analyze", "Collecting observables")
    _populate_scf_fields(result, mol, mf, include_charges=False, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Single-point calculation complete")
    return _finalize_result_contract(result)

def run_partial_charges(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="partial_charges",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "charges",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])

    _emit_progress(progress_callback, 0.80, "charges", "Computing Mulliken charges")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=False)

    _emit_progress(progress_callback, 1.0, "done", "Partial charge analysis complete")
    return _finalize_result_contract(result)

def run_orbital_preview(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="orbital_preview",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "orbital",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 0.70, "orbital_select", "Selecting orbital")
    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        with tempfile.TemporaryDirectory(prefix="qcviz_orb_") as tmpdir:
            cube_path = Path(tmpdir) / "orbital.cube"
            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60)

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=cube_path,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Orbital cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Orbital preview complete")
    return _finalize_result_contract(result)

def run_esp_map(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="esp_map",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "esp",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    try:
        _emit_progress(progress_callback, 0.70, "cube", "Generating density/ESP cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_esp_") as tmpdir:
            density_cube = Path(tmpdir) / "density.cube"
            esp_cube = Path(tmpdir) / "esp.cube"

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )

            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"ESP cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "ESP map complete")
    result["job_type"] = "esp_map"
    return _finalize_result_contract(result)

def run_geometry_optimization(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol0 = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol0,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    _emit_progress(progress_callback, 0.12, "build_scf", "Building optimization model")
    method_name, mf0 = _build_mean_field(mol0, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.22, "scf", "Running initial SCF")
    mf0, _ = _run_scf_with_fallback(mf0, result["warnings"])

    opt_mol = mol0
    optimization_performed = False

    if geometric_optimize is None:
        result.setdefault("warnings", []).append(
            "Geometry optimizer is unavailable; returning the input geometry."
        )
    else:
        try:
            _emit_progress(progress_callback, 0.45, "optimize", "Running geometry optimization")
            opt_mol = geometric_optimize(mf0)
            optimization_performed = True
        except Exception as exc:
            result.setdefault("warnings", []).append(
                f"Geometry optimization failed; returning the last available geometry: {exc}"
            )
            opt_mol = mol0

    _emit_progress(progress_callback, 0.78, "final_scf", "Running final SCF on optimized geometry")
    method_name, mf = _build_mean_field(opt_mol, method or DEFAULT_METHOD)
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])

    new_atom_text = _strip_xyz_header(_mol_to_xyz(opt_mol))
    final_result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=new_atom_text,
        mol=opt_mol,
        method=method_name,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    final_result["warnings"] = _dedupe_strings(result.get("warnings", []))
    final_result["optimization_performed"] = optimization_performed
    final_result["initial_xyz"] = result["xyz"]
    final_result["optimized_xyz"] = final_result["xyz"]

    _populate_scf_fields(final_result, opt_mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Geometry optimization complete")
    return _finalize_result_contract(final_result)

def run_analyze(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="analyze",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.12, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name

    _emit_progress(progress_callback, 0.30, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"])

    _emit_progress(progress_callback, 0.55, "analysis", "Collecting quantitative results")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        _emit_progress(progress_callback, 0.72, "cube", "Generating orbital/ESP visualization cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_all_") as tmpdir:
            tmpdir_p = Path(tmpdir)
            orbital_cube = tmpdir_p / "orbital.cube"
            density_cube = tmpdir_p / "density.cube"
            esp_cube = tmpdir_p / "esp.cube"

            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(orbital_cube), coeff_vec, nx=60, ny=60, nz=60)

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )
            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=orbital_cube,
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Visualization cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Full analysis complete")
    return _finalize_result_contract(result)

__all__ = [
    "HARTREE_TO_EV",
    "HARTREE_TO_KCAL",
    "BOHR_TO_ANGSTROM",
    "EV_TO_KCAL",
    "DEFAULT_METHOD",
    "DEFAULT_BASIS",
    "ESP_PRESETS_DATA",
    "run_resolve_structure",
    "run_geometry_analysis",
    "run_single_point",
    "run_partial_charges",
    "run_orbital_preview",
    "run_esp_map",
    "run_geometry_optimization",
    "run_analyze",
]

```

### `version02/src/qcviz_mcp/llm/agent.py`
```python
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "analyze",
                "single_point",
                "geometry_analysis",
                "partial_charges",
                "orbital_preview",
                "esp_map",
                "geometry_optimization",
                "resolve_structure",
            ],
        },
        "structure_query": {"type": "string"},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb",
                "bwr",
                "viridis",
                "inferno",
                "spectral",
                "nature",
                "acs",
                "rsc",
                "greyscale",
                "high_contrast",
                "grey",
                "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbitals", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["intent"],
    "additionalProperties": True,
}


INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbitals"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}


SYSTEM_PROMPT = """
You are QCViz Planner, a planning agent for a quantum chemistry web app.

Your job:
- Read the user's natural-language request.
- Infer the best computation intent.
- Extract structure_query, method, basis, charge, multiplicity, orbital, and esp_preset when explicit.
- Choose the best focus_tab for the frontend.
- Return ONLY arguments for the planning function / JSON object.

Intent rules:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

Extraction rules:
- structure_query should be the molecule/material/system name or pasted geometry string.
- focus_tab should be:
  - orbitals for orbital_preview
  - esp for esp_map
  - charges for partial_charges
  - geometry for geometry_analysis or geometry_optimization
  - summary otherwise
- confidence should be 0.0 to 1.0
- notes can explain ambiguous choices briefly.

If the structure is unclear, still return the best intent and leave structure_query empty.
""".strip()


@dataclass
class AgentPlan:
    intent: str = "analyze"
    structure_query: Optional[str] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    tool_name: str = "run_analyze"
    notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data


class QCVizAgent:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.0-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0}, provider="heuristic")

        chosen = self._choose_provider()
        if chosen == "openai":
            try:
                return self._plan_with_openai(text, context=context or {})
            except Exception:
                pass

        if chosen == "gemini":
            try:
                return self._plan_with_gemini(text, context=context or {})
            except Exception:
                pass

        if chosen == "auto":
            if self.openai_api_key:
                try:
                    return self._plan_with_openai(text, context=context or {})
                except Exception:
                    pass
            if self.gemini_api_key:
                try:
                    return self._plan_with_gemini(text, context=context or {})
                except Exception:
                    pass

        return self._heuristic_plan(text, context=context or {})

    def _choose_provider(self) -> str:
        if self.provider in {"openai", "gemini", "none"}:
            return self.provider
        return "auto"

    def _plan_with_openai(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        from openai import OpenAI

        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=self.openai_api_key)
        user_prompt = self._compose_user_prompt(message, context=context)

        resp = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "plan_quantum_request",
                        "description": "Plan a user request into a QCViz compute intent.",
                        "parameters": PLAN_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "plan_quantum_request"}},
        )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        data: Dict[str, Any]

        if tool_calls:
            args = tool_calls[0].function.arguments or "{}"
            data = json.loads(args)
        else:
            content = self._message_content_to_text(getattr(msg, "content", ""))
            data = self._extract_json_dict(content)

        return self._coerce_plan(data, provider="openai")

    def _plan_with_gemini(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        user_prompt = self._compose_user_prompt(message, context=context)

        # new google-genai
        try:
            from google import genai  # type: ignore

            if not self.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "user", "parts": [{"text": user_prompt}]},
                ],
                config={
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(resp, "text", None) or self._message_content_to_text(resp)
            data = self._extract_json_dict(text)
            return self._coerce_plan(data, provider="gemini")
        except ImportError:
            pass

        # older google-generativeai
        import google.generativeai as genai  # type: ignore

        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel(self.gemini_model)
        resp = model.generate_content(
            f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            generation_config={"response_mime_type": "application/json", "temperature": 0},
        )
        text = getattr(resp, "text", None) or self._message_content_to_text(resp)
        data = self._extract_json_dict(text)
        return self._coerce_plan(data, provider="gemini")

    def _compose_user_prompt(self, message: str, context: Dict[str, Any]) -> str:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return f"Context:\n{context_json}\n\nUser message:\n{message}"

    def _heuristic_plan(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        text = message.strip()
        lower = text.lower()

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = []

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy"]):
            intent = "single_point"
            confidence = 0.82

        structure_query = self._extract_structure_query(text)
        method = self._extract_method(text)
        basis = self._extract_basis(text)
        charge = self._extract_charge(text)
        multiplicity = self._extract_multiplicity(text)
        orbital = self._extract_orbital(text)
        esp_preset = self._extract_esp_preset(text)

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        data = {
            "intent": intent,
            "structure_query": structure_query,
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "orbital": orbital,
            "esp_preset": esp_preset,
            "confidence": confidence,
            "notes": notes,
        }
        return self._coerce_plan(data, provider="heuristic")

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structure_query = self._none_if_blank(data.get("structure_query"))
        method = self._none_if_blank(data.get("method"))
        basis = self._none_if_blank(data.get("basis"))
        orbital = self._none_if_blank(data.get("orbital"))
        esp_preset = self._normalize_preset(self._none_if_blank(data.get("esp_preset")))
        focus_tab = str(data.get("focus_tab") or defaults["focus_tab"]).strip()
        tool_name = str(data.get("tool_name") or defaults["tool_name"]).strip()

        charge = self._safe_int(data.get("charge"))
        multiplicity = self._safe_int(data.get("multiplicity"))
        confidence = self._safe_float(data.get("confidence"), 0.0)
        confidence = max(0.0, min(1.0, confidence))

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]

        return AgentPlan(
            intent=intent,
            structure_query=structure_query,
            method=method,
            basis=basis,
            charge=charge,
            multiplicity=multiplicity,
            orbital=orbital,
            esp_preset=esp_preset,
            focus_tab=focus_tab,
            confidence=confidence,
            tool_name=tool_name,
            notes=[str(x) for x in notes if str(x).strip()],
            provider=provider,
            raw=data,
        )

    def _extract_structure_query(self, text: str) -> Optional[str]:
        # pasted xyz block
        if len(re.findall(r"\n", text)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", text, re.M):
            return text.strip()

        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        if quoted:
            first = quoted[0][0] or quoted[0][1]
            if first.strip():
                return first.strip()

        patterns = [
            r"(?:for|of|about|analyze|compute|calculate|show|render|visualize|optimize)\s+([A-Za-z0-9_\-\+\(\), ]{2,80})",
            r"(?:molecule|system|structure)\s*:\s*([A-Za-z0-9_\-\+\(\), ]{2,80})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                candidate = m.group(1).strip(" .,:;")
                candidate = re.split(
                    r"\b(using|with|at|in|and show|and render|method|basis|charge|multiplicity|spin|preset)\b",
                    candidate,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip(" .,:;")
                if candidate and len(candidate) >= 2:
                    return candidate

        common = [
            "water",
            "methane",
            "ammonia",
            "benzene",
            "ethanol",
            "acetone",
            "formaldehyde",
            "carbon dioxide",
            "co2",
            "nh3",
            "h2o",
            "caffeine",
            "naphthalene",
            "pyridine",
            "phenol",
        ]
        lower = text.lower()
        for name in common:
            if name in lower:
                return name

        return None

    def _extract_method(self, text: str) -> Optional[str]:
        methods = [
            "HF",
            "B3LYP",
            "PBE",
            "PBE0",
            "M06-2X",
            "M062X",
            "wB97X-D",
            "WB97X-D",
            "CAM-B3LYP",
            "TPSSh",
            "BP86",
        ]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g",
            "3-21g",
            "6-31g",
            "6-31g*",
            "6-31g**",
            "6-311g",
            "6-311g*",
            "6-311g**",
            "def2-svp",
            "def2-tzvp",
            "cc-pvdz",
            "cc-pvtz",
            "aug-cc-pvdz",
        ]
        for basis in basis_list:
            if re.search(rf"\b{re.escape(basis)}\b", text, re.I):
                return basis
        return None

    def _extract_charge(self, text: str) -> Optional[int]:
        patterns = [
            r"\bcharge\s*[:=]?\s*([+-]?\d+)\b",
            r"\bq\s*=\s*([+-]?\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\banion\b", text, re.I):
            return -1
        if re.search(r"\bcation\b", text, re.I):
            return 1
        return None

    def _extract_multiplicity(self, text: str) -> Optional[int]:
        patterns = [
            r"\bmultiplicity\s*[:=]?\s*(\d+)\b",
            r"\bspin multiplicity\s*[:=]?\s*(\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\bsinglet\b", text, re.I):
            return 1
        if re.search(r"\bdoublet\b", text, re.I):
            return 2
        if re.search(r"\btriplet\b", text, re.I):
            return 3
        return None

    def _extract_orbital(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(HOMO(?:[+-]\d+)?)\b",
            r"\b(LUMO(?:[+-]\d+)?)\b",
            r"\b(MO\s*\d+)\b",
            r"\borbital\s+([A-Za-z0-9+\-]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip().upper().replace(" ", "")
        return None

    def _extract_esp_preset(self, text: str) -> Optional[str]:
        presets = [
            "rwb",
            "bwr",
            "viridis",
            "inferno",
            "spectral",
            "nature",
            "acs",
            "rsc",
            "greyscale",
            "grey",
            "high_contrast",
            "hicon",
        ]
        for preset in presets:
            if re.search(rf"\b{re.escape(preset)}\b", text, re.I):
                return self._normalize_preset(preset)
        return None

    def _normalize_preset(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        key = value.strip().lower()
        if key == "grey":
            return "greyscale"
        if key == "hicon":
            return "high_contrast"
        return key

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content or "")

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _safe_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _none_if_blank(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
```

