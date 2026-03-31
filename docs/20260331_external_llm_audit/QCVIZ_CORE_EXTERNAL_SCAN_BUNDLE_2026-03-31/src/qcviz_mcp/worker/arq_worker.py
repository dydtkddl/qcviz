"""arq worker entrypoint for split web/compute deployments."""
from __future__ import annotations

import asyncio
import os
import socket
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException

from qcviz_mcp.web.redis_job_store import RedisJobStore
from qcviz_mcp.web.conversation_state import update_conversation_state_from_execution


class ExternalJobCancelled(RuntimeError):
    pass


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _worker_id() -> str:
    return _safe_str(os.getenv("QCVIZ_WORKER_ID"), f"{socket.gethostname()}:{os.getpid()}")


def _auto_retry_enabled() -> bool:
    return _safe_str(os.getenv("QCVIZ_AUTO_RETRY_ON_FAILURE", "1")).lower() not in {"0", "false", "no"}


def _build_store() -> RedisJobStore:
    import redis

    redis_url = _safe_str(os.getenv("QCVIZ_REDIS_URL"), "redis://127.0.0.1:6379/0")
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return RedisJobStore(
        client,
        max_events=int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200")),
        max_active_per_session=max(0, int(os.getenv("QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION", "2"))),
        max_active_per_user=max(0, int(os.getenv("QCVIZ_MAX_ACTIVE_JOBS_PER_USER", "3"))),
        max_workers=max(1, int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "1"))),
        poll_seconds=float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25")),
    )


def _update_worker_heartbeat(status: str, *, extra: Optional[Mapping[str, Any]] = None) -> None:
    try:
        store = _build_store()
        store.set_worker_heartbeat(_worker_id(), status=status, extra=extra)
    except Exception:
        pass


async def _busy_heartbeat_pulse(stop_event: "asyncio.Event", state: Dict[str, Any]) -> None:
    interval = max(5.0, float(os.getenv("QCVIZ_WORKER_HEARTBEAT_SECONDS", "10")))
    while not stop_event.is_set():
        _update_worker_heartbeat("busy", extra=dict(state))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def _idle_heartbeat_pulse(stop_event: "asyncio.Event", ctx: Dict[str, Any]) -> None:
    interval = max(5.0, float(os.getenv("QCVIZ_WORKER_HEARTBEAT_SECONDS", "10")))
    while not stop_event.is_set():
        if int(ctx.get("_qcviz_active_jobs") or 0) <= 0:
            _update_worker_heartbeat("idle")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def _progress_callback_factory(store: RedisJobStore, job_id: str, worker_state: Dict[str, Any]):
    def progress_callback(*args: Any, **kwargs: Any) -> None:
        if store.is_cancel_requested(job_id):
            raise ExternalJobCancelled("Cancellation acknowledged by external worker")

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
        progress = float(payload.get("progress") or 0.0)
        step = _safe_str(payload.get("step"), "running")
        message = _safe_str(payload.get("message"), step or "Running")
        extra = {k: v for k, v in payload.items() if k not in {"progress", "step", "message"}}
        extra["worker_id"] = _worker_id()
        store.update_progress(job_id, progress=progress, step=step, message=message, extra=extra)
        worker_state.update({"job_id": job_id, "step": step, "progress": progress, "worker_id": _worker_id()})
        _update_worker_heartbeat("busy", extra=dict(worker_state))

    return progress_callback


def _maybe_retry(job_id: str, payload: Mapping[str, Any], *, reason: str, actor: str = "worker") -> Optional[Dict[str, Any]]:
    if not _auto_retry_enabled():
        return None
    retry_count = max(0, int((payload or {}).get("retry_count") or 0))
    max_retries = max(0, int((payload or {}).get("max_retries") or os.getenv("QCVIZ_MAX_JOB_RETRIES", "1")))
    if retry_count >= max_retries:
        return None
    try:
        from qcviz_mcp.web.arq_backend import ArqJobManager

        manager = ArqJobManager(max_workers=max(1, int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "1"))))
        try:
            return manager.retry(job_id, reason=reason, actor=actor, force=False)
        finally:
            manager.shutdown()
    except Exception:
        return None


async def run_compute_job(ctx: Dict[str, Any], job_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    from qcviz_mcp.web.routes.compute import _run_direct_compute

    store = _build_store()
    worker_state: Dict[str, Any] = {"job_id": job_id, "worker_id": _worker_id(), "queue": _safe_str(os.getenv("QCVIZ_ARQ_QUEUE_NAME"), "qcviz-jobs")}
    ctx["_qcviz_active_jobs"] = int(ctx.get("_qcviz_active_jobs") or 0) + 1
    store.mark_running(job_id, worker_id=_worker_id())
    _update_worker_heartbeat("busy", extra=dict(worker_state))
    stop_event: asyncio.Event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_busy_heartbeat_pulse(stop_event, worker_state))
    progress_callback = _progress_callback_factory(store, job_id, worker_state)
    try:
        result = await asyncio.to_thread(
            _run_direct_compute,
            dict(payload or {}),
            progress_callback=progress_callback,
        )
        update_conversation_state_from_execution(
            payload,
            result,
            job_id=job_id,
            manager=SimpleNamespace(store=store),
        )
        store.mark_completed(job_id, result)
        store.clear_cancel(job_id)
        _update_worker_heartbeat("idle", extra={"job_id": job_id, "status": "completed"})
        return {"ok": True, "job_id": job_id}
    except ExternalJobCancelled as exc:
        store.mark_cancelled(job_id, detail=str(exc))
        store.clear_cancel(job_id)
        _update_worker_heartbeat("idle", extra={"job_id": job_id, "status": "cancelled"})
        return {"ok": False, "job_id": job_id, "cancelled": True}
    except HTTPException as exc:
        store.mark_failed(job_id, message=_safe_str(exc.detail, "Request failed"), error={"message": _safe_str(exc.detail), "status_code": exc.status_code})
        retry_job = None
        if int(exc.status_code) >= 500:
            retry_job = _maybe_retry(job_id, payload, reason=f"http_{int(exc.status_code)}", actor="worker-http")
            if retry_job is not None:
                store.append_event(job_id, "job_retry_scheduled", "Retry scheduled", {"retry_job_id": retry_job.get("job_id")})
        store.clear_cancel(job_id)
        _update_worker_heartbeat("idle", extra={"job_id": job_id, "status": "failed"})
        return {"ok": False, "job_id": job_id, "status_code": exc.status_code, "retry_job_id": (retry_job or {}).get("job_id")}
    except Exception as exc:
        store.mark_failed(job_id, message=str(exc), error={"message": str(exc), "type": exc.__class__.__name__})
        retry_job = _maybe_retry(job_id, payload, reason="worker_exception", actor="worker-exception")
        if retry_job is not None:
            store.append_event(job_id, "job_retry_scheduled", "Retry scheduled", {"retry_job_id": retry_job.get("job_id")})
        store.clear_cancel(job_id)
        _update_worker_heartbeat("idle", extra={"job_id": job_id, "status": "failed"})
        return {"ok": False, "job_id": job_id, "error": str(exc), "retry_job_id": (retry_job or {}).get("job_id")}
    finally:
        ctx["_qcviz_active_jobs"] = max(0, int(ctx.get("_qcviz_active_jobs") or 1) - 1)
        stop_event.set()
        try:
            await heartbeat_task
        except Exception:
            pass


async def startup(ctx: Dict[str, Any]) -> None:
    ctx["_qcviz_active_jobs"] = 0
    stop_event: asyncio.Event = asyncio.Event()
    ctx["_qcviz_idle_heartbeat_stop"] = stop_event
    ctx["_qcviz_idle_heartbeat_task"] = asyncio.create_task(_idle_heartbeat_pulse(stop_event, ctx))
    _update_worker_heartbeat("idle")


async def shutdown(ctx: Dict[str, Any]) -> None:
    stop_event = ctx.get("_qcviz_idle_heartbeat_stop")
    if isinstance(stop_event, asyncio.Event):
        stop_event.set()
    task = ctx.get("_qcviz_idle_heartbeat_task")
    if task is not None:
        try:
            await task
        except Exception:
            pass
    try:
        store = _build_store()
        store.clear_worker_heartbeat(_worker_id())
    except Exception:
        _update_worker_heartbeat("offline")


class WorkerSettings:
    functions = [run_compute_job]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = _safe_str(os.getenv("QCVIZ_ARQ_QUEUE_NAME"), "qcviz-jobs")
    max_jobs = max(1, int(os.getenv("QCVIZ_ARQ_MAX_JOBS", os.getenv("QCVIZ_JOB_MAX_WORKERS", "1"))))

    from arq.connections import RedisSettings  # type: ignore

    _redis_url = _safe_str(os.getenv("QCVIZ_REDIS_URL"), "redis://127.0.0.1:6379/0")
    redis_settings = RedisSettings.from_dsn(_redis_url)
