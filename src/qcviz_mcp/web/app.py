from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from qcviz_mcp.web.routes.chat import router as chat_router
from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes.compute import router as compute_router
from qcviz_mcp.web.routes import compute as compute_route
from qcviz_mcp.web.auth_store import (
    auth_health,
    get_auth_user,
    init_auth_db,
    list_users,
    login_user,
    register_user,
    require_admin_user,
    revoke_auth_token,
)
from qcviz_mcp.web.session_auth import (
    bootstrap_or_validate_session,
    invalidate_session,
    session_auth_health,
)
from qcviz_mcp.web.conversation_state import clear_conversation_state
from qcviz_mcp.web.runtime_info import runtime_debug_info

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
            "session_bootstrap": "/session/bootstrap",
            "session_clear_state": "/session/clear_state",
            "auth_register": "/auth/register",
            "auth_login": "/auth/login",
            "auth_me": "/auth/me",
            "auth_logout": "/auth/logout",
            "admin_overview": "/admin/overview",
            "admin_job_cancel": "/admin/jobs/{job_id}/cancel",
            "admin_job_requeue": "/admin/jobs/{job_id}/requeue",
            "chat_health": "/chat/health",
            "compute_health": "/compute/health",
            "chat_rest": "/chat",
            "compute_jobs": "/compute/jobs",
        },
        "api_alias": {
            "health": "/api/health",
            "session_bootstrap": "/api/session/bootstrap",
            "session_clear_state": "/api/session/clear_state",
            "auth_register": "/api/auth/register",
            "auth_login": "/api/auth/login",
            "auth_me": "/api/auth/me",
            "auth_logout": "/api/auth/logout",
            "admin_overview": "/api/admin/overview",
            "admin_job_cancel": "/api/admin/jobs/{job_id}/cancel",
            "admin_job_requeue": "/api/admin/jobs/{job_id}/requeue",
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


def _build_admin_overview() -> Dict[str, Any]:
    manager = compute_route.get_job_manager()
    operational = {}
    if hasattr(manager, "operational_summary"):
        try:
            operational = manager.operational_summary()
        except Exception:
            operational = {}
    jobs = manager.list(include_payload=False, include_result=False, include_events=False)
    queue = dict((operational or {}).get("queue") or manager.queue_summary())
    recovery = dict((operational or {}).get("recovery") or {})
    workers = list((operational or {}).get("workers") or [])
    if not workers:
        store = getattr(manager, "store", None)
        if store is not None and hasattr(store, "list_worker_heartbeats"):
            try:
                workers = store.list_worker_heartbeats()
            except Exception:
                workers = []
    auth_users = list_users(limit=500)

    status_counts: Dict[str, int] = defaultdict(int)
    user_stats: Dict[str, Dict[str, Any]] = {}
    session_stats: Dict[str, Dict[str, Any]] = {}

    for user in auth_users:
        username = str(user["username"])
        user_stats[username] = {
            "username": username,
            "display_name": user.get("display_name") or username,
            "role": user.get("role", "user"),
            "active_tokens": int(user.get("active_tokens") or 0),
            "disabled": bool(user.get("disabled")),
            "created_at": user.get("created_at"),
            "total_jobs": 0,
            "active_jobs": 0,
            "queued_jobs": 0,
            "running_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0,
        }

    active_jobs: List[Dict[str, Any]] = []
    for job in jobs:
        status = str(job.get("status") or "unknown")
        status_counts[status] += 1
        owner = str(job.get("owner_username") or "")
        session_id = str(job.get("session_id") or "")
        if owner:
            bucket = user_stats.setdefault(
                owner,
                {
                    "username": owner,
                    "display_name": job.get("owner_display_name") or owner,
                    "role": "user",
                    "active_tokens": 0,
                    "disabled": False,
                    "created_at": None,
                    "total_jobs": 0,
                    "active_jobs": 0,
                    "queued_jobs": 0,
                    "running_jobs": 0,
                    "completed_jobs": 0,
                    "failed_jobs": 0,
                },
            )
            bucket["display_name"] = bucket.get("display_name") or job.get("owner_display_name") or owner
            bucket["total_jobs"] += 1
            if status in {"queued", "running"}:
                bucket["active_jobs"] += 1
            if status == "queued":
                bucket["queued_jobs"] += 1
            elif status == "running":
                bucket["running_jobs"] += 1
            elif status == "completed":
                bucket["completed_jobs"] += 1
            elif status == "failed":
                bucket["failed_jobs"] += 1

        if session_id:
            session_bucket = session_stats.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "owner_username": owner,
                    "owner_display_name": job.get("owner_display_name") or owner,
                    "total_jobs": 0,
                    "active_jobs": 0,
                    "queued_jobs": 0,
                    "running_jobs": 0,
                    "last_job_at": 0,
                },
            )
            session_bucket["total_jobs"] += 1
            if status in {"queued", "running"}:
                session_bucket["active_jobs"] += 1
            if status == "queued":
                session_bucket["queued_jobs"] += 1
            elif status == "running":
                session_bucket["running_jobs"] += 1
            session_bucket["last_job_at"] = max(
                float(session_bucket.get("last_job_at") or 0),
                float(job.get("updated_at") or job.get("created_at") or 0),
            )

        if status in {"queued", "running"}:
            active_jobs.append(job)

    active_jobs.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    recent_jobs = jobs[:25]
    workers_ranked = sorted(
        workers,
        key=lambda item: (
            1 if str(item.get("status") or "").lower() == "busy" else 0,
            0 if bool(item.get("is_stale")) else 1,
            float(item.get("timestamp") or 0.0),
        ),
        reverse=True,
    )
    users_ranked = sorted(
        user_stats.values(),
        key=lambda item: (
            int(item.get("active_jobs") or 0),
            int(item.get("total_jobs") or 0),
            float(item.get("created_at") or 0),
        ),
        reverse=True,
    )
    sessions_ranked = sorted(
        session_stats.values(),
        key=lambda item: (
            int(item.get("active_jobs") or 0),
            float(item.get("last_job_at") or 0),
        ),
        reverse=True,
    )

    return {
        "generated_at": _now_ts(),
        "job_backend": compute_route.get_job_backend_runtime(manager, fallback_max_workers=manager.max_workers),
        "quota_config": {
            "max_active_per_session": compute_route._max_active_jobs_per_session(),
            "max_active_per_user": compute_route._max_active_jobs_per_user(),
        },
        "queue": queue,
        "recovery": recovery,
        "counts": {
            "total_jobs": len(jobs),
            "active_jobs": len(active_jobs),
            "registered_users": len(auth_users),
            "sessions_seen": len(session_stats),
            "workers_seen": len(workers),
            "stale_workers": len([item for item in workers if bool(item.get("is_stale"))]),
            "recovered_jobs": int(recovery.get("recovered_count") or 0),
            "status": dict(status_counts),
        },
        "workers": workers_ranked[:50],
        "users": users_ranked,
        "sessions": sessions_ranked[:50],
        "active_jobs": active_jobs[:50],
        "recent_jobs": recent_jobs,
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
    init_auth_db()

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
            return templates.TemplateResponse("index.html", {"request": request, "root_path": request.scope.get("root_path", "")})
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
            "session_auth": session_auth_health(),
            "auth": auth_health(),
            "runtime": runtime_debug_info(),
            "routes": _route_table(),
        }

    @app.post("/session/bootstrap")
    @app.post("/api/session/bootstrap", include_in_schema=False)
    async def session_bootstrap(payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        body = dict(payload or {})
        session_meta = bootstrap_or_validate_session(
            body.get("session_id"),
            body.get("session_token"),
            allow_new=True,
        )
        return {
            "ok": True,
            **session_meta,
            "routes": {
                "chat_ws": "/ws/chat",
                "chat_rest": "/chat",
                "compute_jobs": "/compute/jobs",
            },
        }

    @app.post("/session/clear_state")
    @app.post("/api/session/clear_state", include_in_schema=False)
    async def session_clear_state(payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        body = dict(payload or {})
        previous_session_id = str(body.get("previous_session_id") or body.get("session_id") or "").strip()
        previous_session_token = str(body.get("previous_session_token") or body.get("session_token") or "").strip()
        cleared_auth = invalidate_session(previous_session_id, previous_session_token or None)
        clear_conversation_state(previous_session_id, manager=compute_route.get_job_manager())
        try:
            chat_route._session_pop(previous_session_id)
        except Exception:
            pass
        return {
            "ok": True,
            "cleared_session": previous_session_id,
            "cleared_auth": cleared_auth,
        }

    @app.post("/auth/register")
    @app.post("/api/auth/register", include_in_schema=False)
    async def auth_register(payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        body = dict(payload or {})
        user = register_user(
            body.get("username"),
            body.get("password"),
            display_name=body.get("display_name"),
        )
        login = login_user(body.get("username"), body.get("password"))
        return {"ok": True, "user": user, "auth_token": login["auth_token"], "expires_at": login["expires_at"]}

    @app.post("/auth/login")
    @app.post("/api/auth/login", include_in_schema=False)
    async def auth_login(payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        body = dict(payload or {})
        login = login_user(body.get("username"), body.get("password"))
        return {"ok": True, **login}

    @app.get("/auth/me")
    @app.get("/api/auth/me", include_in_schema=False)
    async def auth_me(request: Request) -> Dict[str, Any]:
        auth_token = request.headers.get("X-QCViz-Auth-Token", "")
        user = get_auth_user(auth_token)
        return {"ok": user is not None, "authenticated": user is not None, "user": user}

    @app.get("/admin/overview")
    @app.get("/api/admin/overview", include_in_schema=False)
    async def admin_overview(request: Request) -> Dict[str, Any]:
        auth_token = request.headers.get("X-QCViz-Auth-Token", "")
        admin_user = require_admin_user(auth_token)
        return {
            "ok": True,
            "admin_user": admin_user,
            "overview": _build_admin_overview(),
        }

    @app.post("/admin/jobs/{job_id}/cancel")
    @app.post("/api/admin/jobs/{job_id}/cancel", include_in_schema=False)
    async def admin_cancel_job(job_id: str, request: Request) -> Dict[str, Any]:
        auth_token = request.headers.get("X-QCViz-Auth-Token", "")
        admin_user = require_admin_user(auth_token)
        manager = compute_route.get_job_manager()
        cancel_method = getattr(manager, "cancel", None)
        if not callable(cancel_method):
            return JSONResponse(status_code=501, content={"ok": False, "detail": "Job backend does not support admin cancellation."})
        response = cancel_method(job_id)
        out = dict(response or {})
        out["ok"] = bool(out.get("ok", True))
        out["admin_user"] = admin_user["username"]
        out["job_id"] = job_id
        return out

    @app.post("/admin/jobs/{job_id}/requeue")
    @app.post("/api/admin/jobs/{job_id}/requeue", include_in_schema=False)
    async def admin_requeue_job(job_id: str, request: Request, payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        auth_token = request.headers.get("X-QCViz-Auth-Token", "")
        admin_user = require_admin_user(auth_token)
        body = dict(payload or {})
        manager = compute_route.get_job_manager()
        requeue_method = getattr(manager, "requeue", None)
        if not callable(requeue_method):
            return JSONResponse(status_code=501, content={"ok": False, "detail": "Job backend does not support admin requeue."})
        retry = requeue_method(
            job_id,
            reason=str(body.get("reason") or "admin_requeue"),
            actor=str(admin_user.get("username") or "admin"),
            force=bool(body.get("force", True)),
        )
        return {
            "ok": True,
            "admin_user": admin_user["username"],
            "source_job_id": job_id,
            "job": retry,
        }

    @app.post("/auth/logout")
    @app.post("/api/auth/logout", include_in_schema=False)
    async def auth_logout(request: Request, payload: Dict[str, Any] | None = Body(default=None)) -> Dict[str, Any]:
        body = dict(payload or {})
        auth_token = request.headers.get("X-QCViz-Auth-Token") or body.get("auth_token")
        revoke_auth_token(auth_token)
        return {"ok": True}

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
