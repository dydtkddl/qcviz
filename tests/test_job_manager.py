from __future__ import annotations
import json
import threading
import time
import pytest
from fastapi import HTTPException
from qcviz_mcp.web.routes import compute as compute_route
pytestmark = [pytest.mark.contract]

def test_job_manager_success_records_progress_events(monkeypatch):
    def fake_run_direct_compute(payload, progress_callback=None):
        if progress_callback:
            progress_callback({"progress": 0.2, "step": "resolve", "message": "Resolving"})
            progress_callback({"progress": 0.8, "step": "compute", "message": "Computing"})
        return {"success": True, "job_type": "analyze", "structure_name": "water"}
    monkeypatch.setattr(compute_route, "_run_direct_compute", fake_run_direct_compute)
    
    manager = compute_route.InMemoryJobManager(max_workers=1)
    try:
        submitted = manager.submit({"message": "analyze water"})
        terminal = manager.wait(submitted["job_id"], timeout=2.0)
        assert terminal is not None
        assert terminal["status"] == "completed"
        assert terminal["result"]["success"] is True
        assert any(ev["type"] == "job_started" for ev in terminal["events"])
        assert any(ev["type"] == "job_progress" for ev in terminal["events"])
        assert any(ev["type"] == "job_completed" for ev in terminal["events"])
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)

def test_job_manager_failure_records_http_exception(monkeypatch):
    def fake_run_direct_compute(payload, progress_callback=None):
        raise HTTPException(status_code=400, detail="Structure not recognized.")
    monkeypatch.setattr(compute_route, "_run_direct_compute", fake_run_direct_compute)
    
    manager = compute_route.InMemoryJobManager(max_workers=1)
    try:
        submitted = manager.submit({"message": "HOMO 보여줘"})
        terminal = manager.wait(submitted["job_id"], timeout=2.0)
        assert terminal is not None
        assert terminal["status"] == "failed"
        assert terminal["error"]["status_code"] == 400
        assert "Structure not recognized" in terminal["error"]["message"]
        assert any(ev["type"] == "job_failed" for ev in terminal["events"])
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)

def test_job_manager_delete_completed_job(monkeypatch):
    def fake_run_direct_compute(payload, progress_callback=None):
        return {"success": True, "job_type": "single_point", "structure_name": "water"}
    monkeypatch.setattr(compute_route, "_run_direct_compute", fake_run_direct_compute)
    
    manager = compute_route.InMemoryJobManager(max_workers=1)
    try:
        submitted = manager.submit({"message": "energy of water"})
        terminal = manager.wait(submitted["job_id"], timeout=2.0)
        assert terminal["status"] == "completed"
        deleted = manager.delete(submitted["job_id"])
        assert deleted is True
        assert manager.get(submitted["job_id"]) is None
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)


def test_job_manager_queue_stats_reflect_waiting_jobs(monkeypatch):
    monkeypatch.setattr(compute_route.InMemoryJobManager, "_load_from_disk", lambda self: None)
    monkeypatch.setattr(compute_route.InMemoryJobManager, "_save_to_disk", lambda self: None)
    started = threading.Event()
    release = threading.Event()

    def fake_run_direct_compute(payload, progress_callback=None):
        started.set()
        release.wait(timeout=1.0)
        return {"success": True, "job_type": "single_point", "structure_name": payload.get("message", "water")}

    monkeypatch.setattr(compute_route, "_run_direct_compute", fake_run_direct_compute)

    manager = compute_route.InMemoryJobManager(max_workers=1)
    try:
        first = manager.submit({"message": "water first"})
        assert started.wait(timeout=0.5)

        second = manager.submit({"message": "water second"})
        third = manager.submit({"message": "water third"})

        second_snap = manager.get(second["job_id"])
        third_snap = manager.get(third["job_id"])
        assert second_snap is not None
        assert third_snap is not None
        assert second_snap["queue"]["running_count"] == 1
        assert second_snap["queue"]["queued_count"] >= 2
        assert second_snap["queue"]["queued_ahead"] == 0
        assert second_snap["queue"]["queue_position"] == 1
        assert third_snap["queue"]["queued_ahead"] >= 1
        assert third_snap["queue"]["queue_position"] >= 2

        release.set()
        assert manager.wait(first["job_id"], timeout=2.0)["status"] == "completed"
        assert manager.wait(second["job_id"], timeout=2.0)["status"] == "completed"
        assert manager.wait(third["job_id"], timeout=2.0)["status"] == "completed"
    finally:
        release.set()
        manager.executor.shutdown(wait=False, cancel_futures=True)


def test_job_manager_load_marks_stale_active_jobs_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(compute_route.InMemoryJobManager, "_save_to_disk", lambda self: None)
    manager = compute_route.InMemoryJobManager(max_workers=1)
    try:
        cache_file = tmp_path / "job_history.json"
        cache_file.write_text(
            json.dumps(
                {
                    "job-queued": {"job_id": "job-queued", "status": "queued", "payload": {"message": "queued job"}},
                    "job-running": {"job_id": "job-running", "status": "running", "payload": {"message": "running job"}},
                }
            ),
            encoding="utf-8",
        )
        manager.jobs.clear()
        manager.cache_dir = str(tmp_path)
        manager.cache_file = str(cache_file)
        manager._load_from_disk()

        queued = manager.get("job-queued", include_result=True)
        running = manager.get("job-running", include_result=True)
        assert queued is not None
        assert running is not None
        assert queued["status"] == "failed"
        assert running["status"] == "failed"
        assert queued["error"]["type"] == "stale_job_recovered"
        assert running["error"]["type"] == "stale_job_recovered"
        assert manager.queue_summary()["active_count"] == 0
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)
