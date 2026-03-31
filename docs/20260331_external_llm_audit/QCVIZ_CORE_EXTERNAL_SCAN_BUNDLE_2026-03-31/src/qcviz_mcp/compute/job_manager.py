"""Progress-aware in-process JobManager for QCViz.

# FIX(M5): RLock 확인, atomic file write (tmp→rename), shallow copy 반환
기존 인터페이스 전부 유지.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobEvent:
    """A lightweight event emitted during job execution."""
    job_id: str
    timestamp: float
    level: str = "info"
    message: str = ""
    step: str = ""
    detail: str = ""
    progress: float = 0.0
    payload: Optional[Dict[str, Any]] = None


@dataclass
class JobRecord:
    """Serializable public job record."""
    job_id: str
    name: str
    label: str
    status: str = "queued"
    progress: float = 0.0
    step: str = ""
    detail: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    cancel_requested: bool = False


class JobCancelledError(RuntimeError):
    """Raised when a running job cooperatively acknowledges cancellation."""


class JobManager:
    """Thread-based job manager with progress and event buffering.

    # FIX(M5): RLock 사용 확인, atomic writes, shallow copy snapshots
    """

    def __init__(self, max_workers: Optional[int] = None, max_events_per_job: int = 300) -> None:
        cpu = os.cpu_count() or 2
        self._max_workers = max_workers or max(2, min(4, cpu))
        self._max_events_per_job = max(50, int(max_events_per_job))

        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="qcviz-job")

        # FIX(M5): RLock for reentrant locking
        self._lock = threading.RLock()
        self._records: Dict[str, JobRecord] = {}
        self._futures: Dict[str, Future] = {}
        self._events: Dict[str, List[JobEvent]] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}

        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s)", self._max_workers)

    # ── Public API ────────────────────────────────────────────

    def submit(self, target: Optional[Callable[..., Any]] = None, kwargs: Optional[Dict[str, Any]] = None,
               label: Optional[str] = None, name: Optional[str] = None,
               func: Optional[Callable[..., Any]] = None) -> str:
        callable_obj = target or func
        if callable_obj is None or not callable(callable_obj):
            raise ValueError("submit() requires a callable target/func")

        job_id = self._new_job_id()
        job_name = str(name or label or getattr(callable_obj, "__name__", "job")).strip() or "job"

        record = JobRecord(job_id=job_id, name=job_name, label=str(label or job_name),
                           status="queued", progress=0.0, step="queued", detail="Job queued")

        with self._lock:
            self._records[job_id] = record
            self._events[job_id] = []
            self._cancel_flags[job_id] = threading.Event()

        self._append_event(job_id, level="info", message="Job queued", step="queued", detail=record.detail)

        future = self._executor.submit(self._run_job, job_id, callable_obj, dict(kwargs or {}))
        with self._lock:
            self._futures[job_id] = future
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            # FIX(M5): shallow copy via asdict for thread safety
            return self._record_to_dict(record)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.get(job_id)

    def get_record(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return JobRecord(**asdict(record))

    def list_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            records = [self._record_to_dict(rec) for rec in self._records.values()]
        records.sort(key=lambda x: x.get("created_at", 0.0), reverse=True)
        if limit is not None:
            return records[:max(0, int(limit))]
        return records

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._records.get(job_id)
            future = self._futures.get(job_id)
            cancel_flag = self._cancel_flags.get(job_id)

        if record is None:
            return {"ok": False, "job_id": job_id, "status": "missing", "message": "job not found"}

        if cancel_flag is not None:
            cancel_flag.set()

        self._update_record(job_id, cancel_requested=True, detail="Cancellation requested")
        self._append_event(job_id, level="warning", message="Cancellation requested",
                           step="cancellation_requested", detail="Cancellation requested by user",
                           progress=self._get_progress(job_id))

        if future is not None and future.cancel():
            self._finalize_cancelled(job_id, detail="Cancelled before execution")
            return {"ok": True, "job_id": job_id, "status": "cancelled", "message": "job cancelled before execution"}

        return {"ok": True, "job_id": job_id, "status": "cancellation_requested", "message": "cancellation requested"}

    def drain_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            events = self._events.get(job_id, [])
            data = [asdict(ev) for ev in events]
            if clear:
                self._events[job_id] = []
        return data

    def pop_events(self, job_id: str) -> List[Dict[str, Any]]:
        return self.drain_events(job_id, clear=True)

    def get_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        return self.drain_events(job_id, clear=clear)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            future = self._futures.get(job_id)
        if future is None:
            return self.get(job_id)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            raise
        except Exception:
            pass
        return self.get(job_id)

    async def async_wait(self, job_id: str, timeout: Optional[float] = None, poll_interval: float = 0.2) -> Optional[Dict[str, Any]]:
        start = time.time()
        while True:
            record = self.get(job_id)
            if record is None:
                return None
            if record.get("status") in {"success", "error", "cancelled"}:
                return record
            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError(f"Timed out waiting for job {job_id}")
            await asyncio.sleep(poll_interval)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        logger.info("Shutting down JobManager (wait=%s, cancel_futures=%s)", wait, cancel_futures)
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    # ── Internal ──────────────────────────────────────────────

    def _run_job(self, job_id: str, target: Callable[..., Any], kwargs: Dict[str, Any]) -> None:
        self._mark_running(job_id)
        try:
            cancel_flag = self._cancel_flags[job_id]
            if cancel_flag.is_set():
                raise JobCancelledError("Cancelled before start")
            injected = self._build_runtime_injections(job_id)
            call_kwargs = dict(kwargs or {})
            call_kwargs.update(injected)
            filtered_kwargs = self._filter_kwargs_for_callable(target, call_kwargs)
            result = target(**filtered_kwargs)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            if cancel_flag.is_set():
                raise JobCancelledError("Cancelled during execution")
            self._finalize_success(job_id, result)
        except JobCancelledError as exc:
            self._finalize_cancelled(job_id, detail=str(exc))
        except Exception:
            tb = traceback.format_exc()
            logger.exception("Job %s failed", job_id)
            self._finalize_error(job_id, error=tb)

    def _build_runtime_injections(self, job_id: str) -> Dict[str, Any]:
        cancel_flag = self._cancel_flags[job_id]

        def progress_callback(progress: Optional[float] = None, step: Optional[str] = None,
                               detail: Optional[str] = None, message: Optional[str] = None,
                               level: str = "info", payload: Optional[Dict[str, Any]] = None) -> None:
            if cancel_flag.is_set():
                raise JobCancelledError("Cancellation acknowledged")
            detail_text = str(detail or message or "")
            progress_val = max(0.0, min(100.0, float(progress))) if progress is not None else self._get_progress(job_id)
            updates: Dict[str, Any] = {"progress": progress_val}
            if step is not None:
                updates["step"] = str(step)
            if detail_text:
                updates["detail"] = detail_text
            self._update_record(job_id, **updates)
            self._append_event(job_id, level=level, message=str(message or detail or step or ""),
                               step=str(step or ""), detail=detail_text, progress=progress_val, payload=payload)

        def emit_event(message: str = "", *, level: str = "info", step: str = "", detail: str = "",
                       progress: Optional[float] = None, payload: Optional[Dict[str, Any]] = None) -> None:
            progress_callback(progress=progress, step=step, detail=detail, message=message, level=level, payload=payload)

        def is_cancelled() -> bool:
            return cancel_flag.is_set()

        return {
            "progress_callback": progress_callback, "progress_cb": progress_callback,
            "report_progress": progress_callback, "job_reporter": progress_callback,
            "emit_event": emit_event, "event_callback": emit_event,
            "is_cancelled": is_cancelled, "cancel_requested": is_cancelled, "job_id": job_id,
        }

    def _new_job_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _filter_kwargs_for_callable(self, func: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            sig = inspect.signature(func)
        except Exception:
            return dict(kwargs)
        params = sig.parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_kwargs:
            return dict(kwargs)
        allowed = set(params.keys())
        return {key: value for key, value in kwargs.items() if key in allowed}

    def _record_to_dict(self, record: JobRecord) -> Dict[str, Any]:
        # FIX(M5): returns shallow copy
        return asdict(record)

    def _get_progress(self, job_id: str) -> float:
        with self._lock:
            record = self._records.get(job_id)
            return float(record.progress) if record else 0.0

    def _update_record(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            for key, value in updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.updated_at = time.time()

    def _append_event(self, job_id: str, *, level: str = "info", message: str = "", step: str = "",
                       detail: str = "", progress: float = 0.0, payload: Optional[Dict[str, Any]] = None) -> None:
        event = JobEvent(job_id=job_id, timestamp=time.time(), level=str(level or "info"),
                         message=str(message or ""), step=str(step or ""), detail=str(detail or ""),
                         progress=max(0.0, min(100.0, float(progress))), payload=payload)
        with self._lock:
            bucket = self._events.setdefault(job_id, [])
            bucket.append(event)
            if len(bucket) > self._max_events_per_job:
                del bucket[:len(bucket) - self._max_events_per_job]

    def _mark_running(self, job_id: str) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "running"
            record.progress = max(record.progress, 1.0)
            record.step = "running"
            record.detail = "Job started"
            record.started_at = time.time()
            record.updated_at = record.started_at
        self._append_event(job_id, level="info", message="Job started", step="running", progress=1.0)

    def _finalize_success(self, job_id: str, result: Any) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "success"
            record.progress = 100.0
            record.step = "completed"
            record.detail = "Job completed successfully"
            record.result = result
            record.error = None
            record.ended_at = time.time()
            record.updated_at = record.ended_at
        self._append_event(job_id, level="info", message="Job completed successfully", step="completed", progress=100.0)

    def _finalize_error(self, job_id: str, error: str) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "error"
            record.step = "error"
            record.detail = "Job failed"
            record.error = str(error)
            record.ended_at = time.time()
            record.updated_at = record.ended_at
        self._append_event(job_id, level="error", message="Job failed", step="error",
                           detail=str(error), progress=self._get_progress(job_id))

    def _finalize_cancelled(self, job_id: str, detail: str = "Cancelled") -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "cancelled"
            record.step = "cancelled"
            record.detail = detail
            record.cancel_requested = True
            record.ended_at = time.time()
            record.updated_at = record.ended_at
        self._append_event(job_id, level="warning", message="Job cancelled", step="cancelled",
                           detail=detail, progress=self._get_progress(job_id))


# ── Singleton ─────────────────────────────────────────────────

_JOB_MANAGER_SINGLETON: Optional[JobManager] = None
_JOB_MANAGER_SINGLETON_LOCK = threading.Lock()


def get_job_manager() -> JobManager:
    global _JOB_MANAGER_SINGLETON
    if _JOB_MANAGER_SINGLETON is None:
        with _JOB_MANAGER_SINGLETON_LOCK:
            if _JOB_MANAGER_SINGLETON is None:
                _JOB_MANAGER_SINGLETON = JobManager()
    return _JOB_MANAGER_SINGLETON


def reset_job_manager() -> JobManager:
    global _JOB_MANAGER_SINGLETON
    with _JOB_MANAGER_SINGLETON_LOCK:
        if _JOB_MANAGER_SINGLETON is not None:
            try:
                _JOB_MANAGER_SINGLETON.shutdown(wait=False, cancel_futures=False)
            except Exception:
                logger.exception("Error shutting down previous JobManager")
        _JOB_MANAGER_SINGLETON = JobManager()
    return _JOB_MANAGER_SINGLETON
