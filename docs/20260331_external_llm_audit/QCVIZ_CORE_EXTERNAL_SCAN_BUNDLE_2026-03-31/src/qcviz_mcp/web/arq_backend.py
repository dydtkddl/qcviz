"""Optional Redis/arq-backed job manager for split web/worker deployments."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import os
import time
import uuid
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException

from qcviz_mcp.web.job_backend import JobBackendRuntime
from qcviz_mcp.web.redis_job_store import RedisJobStore


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "query", "prompt", "text"):
        value = _safe_str((payload or {}).get(key))
        if value:
            return value
    return ""


def _quota_limit(name: str, default: int) -> int:
    raw = _safe_str(os.getenv(name, str(default)))
    try:
        value = int(raw)
    except Exception:
        return default
    return max(0, value)


def _retry_limit(name: str, default: int) -> int:
    raw = _safe_str(os.getenv(name, str(default)))
    try:
        value = int(raw)
    except Exception:
        return default
    return max(0, value)


class ArqJobManager:
    def __init__(self, *, max_workers: int = 1) -> None:
        redis_mod = importlib.import_module("redis")
        self._arq_mod = importlib.import_module("arq")
        self._arq_conn_mod = importlib.import_module("arq.connections")
        redis_url = _safe_str(os.getenv("QCVIZ_REDIS_URL"), "redis://127.0.0.1:6379/0")
        self.redis_url = redis_url
        self.queue_name = _safe_str(os.getenv("QCVIZ_ARQ_QUEUE_NAME"), "qcviz-jobs")
        self.max_workers = max(1, int(max_workers or 1))
        self.max_events = max(50, int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200")))
        self.poll_seconds = max(0.05, float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25")))
        self.recovery_interval_seconds = max(2.0, float(os.getenv("QCVIZ_STALE_RECOVERY_INTERVAL_SECONDS", "5")))
        self.default_max_retries = _retry_limit("QCVIZ_MAX_JOB_RETRIES", 1)
        self.auto_retry_enabled = _safe_str(os.getenv("QCVIZ_AUTO_RETRY_ENABLED", "1")).lower() not in {"0", "false", "no"}
        self._enqueue_bridge = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qcviz-arq-enqueue")
        self.redis = redis_mod.Redis.from_url(redis_url, decode_responses=True)
        self.redis.ping()
        self.store = RedisJobStore(
            self.redis,
            max_events=self.max_events,
            max_active_per_session=_quota_limit("QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION", 2),
            max_active_per_user=_quota_limit("QCVIZ_MAX_ACTIVE_JOBS_PER_USER", 3),
            max_workers=self.max_workers,
            poll_seconds=self.poll_seconds,
        )
        self.backend_runtime = JobBackendRuntime(
            name="redis-arq",
            mode="split-web-worker",
            external_queue=True,
            split_ready=True,
            worker_count=self.max_workers,
            queue_driver="arq",
            notes=(
                "Web/API process stores job records in Redis.",
                "Compute execution is dispatched to external arq workers.",
                "Requires Redis server and worker process startup.",
            ),
        )
        self._last_recovery: Dict[str, Any] = {
            "checked_at": 0.0,
            "recovered_count": 0,
            "recovered_jobs": [],
        }

    def _build_redis_settings(self) -> Any:
        redis_settings_cls = getattr(self._arq_conn_mod, "RedisSettings")
        from_dsn = getattr(redis_settings_cls, "from_dsn", None)
        if callable(from_dsn):
            return from_dsn(self.redis_url)
        return redis_settings_cls()

    async def _enqueue_async(self, job_id: str, payload: Mapping[str, Any]) -> None:
        create_pool = getattr(self._arq_mod, "create_pool")
        pool = await create_pool(self._build_redis_settings())
        try:
            await pool.enqueue_job(
                "run_compute_job",
                job_id,
                dict(payload or {}),
                _queue_name=self.queue_name,
                _job_id=f"{job_id}:dispatch",
            )
        finally:
            aclose = getattr(pool, "aclose", None)
            if callable(aclose):
                result = aclose()
                if asyncio.iscoroutine(result):
                    await result
                return
            close = getattr(pool, "close", None)
            if callable(close):
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    def _enqueue_blocking(self, job_id: str, payload: Mapping[str, Any]) -> None:
        asyncio.run(self._enqueue_async(job_id, payload))

    def _prepare_payload(self, payload: Mapping[str, Any], *, job_id: Optional[str] = None) -> Dict[str, Any]:
        prepared = dict(payload or {})
        prepared["retry_count"] = max(0, int(prepared.get("retry_count") or 0))
        prepared["max_retries"] = max(0, int(prepared.get("max_retries") or self.default_max_retries))
        if job_id and not _safe_str(prepared.get("retry_origin_job_id")):
            prepared["retry_origin_job_id"] = job_id
        return prepared

    def _submit_prepared(self, payload: Mapping[str, Any], *, enforce_quota: bool = True) -> Dict[str, Any]:
        prepared = dict(payload or {})
        if enforce_quota:
            try:
                self.store.enforce_quota(prepared)
            except RuntimeError as exc:
                raise HTTPException(status_code=429, detail=str(exc))
        job_id = uuid.uuid4().hex
        prepared = self._prepare_payload(prepared, job_id=job_id)
        record = self.store.create(job_id, prepared, user_query=_extract_message(prepared))
        self.store.append_event(
            job_id,
            "job_submitted",
            "Job submitted",
            {
                "job_type": prepared.get("job_type"),
                "retry_count": prepared.get("retry_count"),
                "max_retries": prepared.get("max_retries"),
            },
        )
        future = self._enqueue_bridge.submit(self._enqueue_blocking, job_id, prepared)
        try:
            future.result(timeout=10.0)
        except Exception as exc:
            self.store.mark_failed(
                job_id,
                message="Failed to enqueue job to external worker queue",
                error={"message": str(exc), "type": exc.__class__.__name__},
            )
            raise HTTPException(status_code=503, detail=f"Failed to enqueue external job: {exc}")
        return self.store.snapshot(record, include_payload=False, include_result=False, include_events=False)

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        self.recover_stale_jobs()
        return self._submit_prepared(payload, enforce_quota=True)

    def _build_retry_payload(
        self,
        payload: Mapping[str, Any],
        *,
        parent_job_id: str,
        reason: str,
        actor: str,
    ) -> Dict[str, Any]:
        base = dict(payload or {})
        origin_job_id = _safe_str(base.get("retry_origin_job_id") or parent_job_id)
        retry_count = max(0, int(base.get("retry_count") or 0)) + 1
        max_retries = max(0, int(base.get("max_retries") or self.default_max_retries))
        base["retry_count"] = retry_count
        base["max_retries"] = max_retries
        base["retry_origin_job_id"] = origin_job_id
        base["retry_parent_job_id"] = parent_job_id
        base["retry_reason"] = _safe_str(reason, "retry")
        base["retry_actor"] = _safe_str(actor, "system")
        return base

    def retry(
        self,
        job_id: str,
        *,
        reason: str = "manual_retry",
        actor: str = "system",
        force: bool = False,
    ) -> Dict[str, Any]:
        self.recover_stale_jobs(force=True)
        snap = self.store.get(job_id, include_payload=True, include_result=True, include_events=False)
        if snap is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        status = _safe_str(snap.get("status")).lower()
        if status in {"queued", "running"} and not force:
            raise HTTPException(status_code=409, detail="Cannot requeue an active job without force.")
        payload = dict(snap.get("payload") or {})
        prepared = self._build_retry_payload(payload, parent_job_id=job_id, reason=reason, actor=actor)
        return self._submit_prepared(prepared, enforce_quota=not force)

    def get(self, job_id: str, *, include_payload: bool = False, include_result: bool = False, include_events: bool = False) -> Optional[Dict[str, Any]]:
        self.recover_stale_jobs()
        return self.store.get(job_id, include_payload=include_payload, include_result=include_result, include_events=include_events)

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        self.recover_stale_jobs()
        return self.store.list(
            include_payload=include_payload,
            include_result=include_result,
            include_events=include_events,
            session_id=session_id,
            owner_username=owner_username,
        )

    def delete(self, job_id: str) -> bool:
        try:
            return self.store.delete(job_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = time.time() + float(timeout) if timeout else None
        while True:
            self.recover_stale_jobs(force=True)
            snap = self.store.get(job_id, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in {"completed", "failed", "error", "cancelled"}:
                return snap
            if deadline is not None and time.time() >= deadline:
                return snap
            time.sleep(self.poll_seconds)

    def queue_summary(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        self.recover_stale_jobs()
        queue = self.store.queue_summary(job_id)
        queue["recovery"] = dict(self._last_recovery)
        return queue

    def quota_summary(self, *, session_id: Optional[str] = None, owner_username: Optional[str] = None) -> Dict[str, Any]:
        return self.store.quota_summary(session_id=session_id, owner_username=owner_username)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        record = self.store.request_cancel(job_id)
        if record is None:
            return {"ok": False, "job_id": job_id, "status": "missing", "message": "job not found"}
        return {"ok": True, "job_id": job_id, "status": "cancellation_requested", "message": "cancellation requested"}

    def recover_stale_jobs(self, *, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        checked_at = float(self._last_recovery.get("checked_at") or 0.0)
        if not force and (now - checked_at) < self.recovery_interval_seconds:
            return dict(self._last_recovery)
        recovery = self.store.recover_stale_running_jobs()
        requeued_jobs = []
        if self.auto_retry_enabled:
            for item in list(recovery.get("recovered_jobs") or []):
                job_id = _safe_str(item.get("job_id"))
                snap = self.store.get(job_id, include_payload=True, include_result=True, include_events=False)
                if snap is None:
                    continue
                retry_count = int((snap.get("retry_count") or 0))
                max_retries = int((snap.get("max_retries") or self.default_max_retries))
                if retry_count >= max_retries:
                    continue
                try:
                    retried = self.retry(job_id, reason="stale_recovery", actor="system-recovery", force=False)
                    requeued_jobs.append({"source_job_id": job_id, "retry_job_id": retried.get("job_id")})
                except Exception as exc:
                    requeued_jobs.append({"source_job_id": job_id, "error": str(exc)})
        recovery["requeued_jobs"] = requeued_jobs
        recovery["requeued_count"] = len([item for item in requeued_jobs if item.get("retry_job_id")])
        self._last_recovery = recovery
        return dict(self._last_recovery)

    def operational_summary(self) -> Dict[str, Any]:
        recovery = self.recover_stale_jobs()
        queue = self.store.queue_summary()
        workers = self.store.list_worker_heartbeats()
        return {
            "queue": queue,
            "recovery": recovery,
            "workers": workers,
        }

    def shutdown(self) -> None:
        try:
            self._enqueue_bridge.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
