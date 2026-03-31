from __future__ import annotations

import asyncio
import time

import pytest

from qcviz_mcp.web.routes import compute as compute_route
from qcviz_mcp.worker import arq_worker


class _FakeStore:
    def __init__(self) -> None:
        self.running_job_id = None
        self.completed = None
        self.cancelled = None
        self.failed = None
        self.progress_updates = []

    def mark_running(self, job_id: str, *, worker_id: str = ""):
        self.running_job_id = job_id
        return {"job_id": job_id, "worker_id": worker_id}

    def mark_completed(self, job_id: str, result):
        self.completed = {"job_id": job_id, "result": dict(result or {})}
        return self.completed

    def mark_cancelled(self, job_id: str, detail: str = ""):
        self.cancelled = {"job_id": job_id, "detail": detail}
        return self.cancelled

    def mark_failed(self, job_id: str, message: str = "", error=None):
        self.failed = {"job_id": job_id, "message": message, "error": error or {}}
        return self.failed

    def clear_cancel(self, job_id: str):
        return None

    def is_cancel_requested(self, job_id: str) -> bool:
        return False

    def update_progress(self, job_id: str, *, progress: float, step: str, message: str, extra=None):
        self.progress_updates.append(
            {
                "job_id": job_id,
                "progress": progress,
                "step": step,
                "message": message,
                "extra": dict(extra or {}),
            }
        )
        return self.progress_updates[-1]

    def append_event(self, job_id: str, event_type: str, message: str, data=None):
        return {"job_id": job_id, "event_type": event_type, "message": message, "data": dict(data or {})}


@pytest.mark.asyncio
async def test_run_compute_job_keeps_busy_heartbeat_while_compute_runs(monkeypatch):
    store = _FakeStore()
    pulses = []
    heartbeats = []

    async def fake_busy_pulse(stop_event: asyncio.Event, state):
        while not stop_event.is_set():
            pulses.append(dict(state))
            await asyncio.sleep(0.01)

    def fake_update_heartbeat(status: str, *, extra=None):
        heartbeats.append({"status": status, **dict(extra or {})})

    def slow_run(payload, progress_callback=None):
        time.sleep(0.06)
        return {
            "success": True,
            "job_type": payload.get("job_type", "single_point"),
            "structure_query": payload.get("structure_query", "water"),
            "visualization": {},
        }

    monkeypatch.setattr(arq_worker, "_build_store", lambda: store)
    monkeypatch.setattr(arq_worker, "_busy_heartbeat_pulse", fake_busy_pulse)
    monkeypatch.setattr(arq_worker, "_update_worker_heartbeat", fake_update_heartbeat)
    monkeypatch.setattr(compute_route, "_run_direct_compute", slow_run)

    result = await arq_worker.run_compute_job({}, "job-1", {"job_type": "single_point", "structure_query": "water"})

    assert result["ok"] is True
    assert store.running_job_id == "job-1"
    assert store.completed is not None
    assert store.completed["result"]["structure_query"] == "water"
    assert len(pulses) >= 2
    assert any(item.get("status") == "busy" and item.get("job_id") == "job-1" for item in heartbeats)
    assert any(item.get("status") == "completed" and item.get("job_id") == "job-1" for item in heartbeats)


@pytest.mark.asyncio
async def test_worker_startup_and_shutdown_manage_idle_heartbeat_task(monkeypatch):
    events = []
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def fake_idle_pulse(stop_event: asyncio.Event, ctx):
        started.set()
        await stop_event.wait()
        stopped.set()

    def fake_update_heartbeat(status: str, *, extra=None):
        events.append({"status": status, **dict(extra or {})})

    monkeypatch.setattr(arq_worker, "_idle_heartbeat_pulse", fake_idle_pulse)
    monkeypatch.setattr(arq_worker, "_update_worker_heartbeat", fake_update_heartbeat)

    ctx = {}
    await arq_worker.startup(ctx)
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert ctx["_qcviz_active_jobs"] == 0
    assert any(item.get("status") == "idle" for item in events)

    await arq_worker.shutdown(ctx)
    await asyncio.wait_for(stopped.wait(), timeout=1.0)
