from __future__ import annotations

import pytest

from qcviz_mcp.web import job_backend


def test_build_job_manager_attaches_runtime_metadata():
    class DummyManager:
        def __init__(self, max_workers: int):
            self.max_workers = max_workers

    manager = job_backend.build_job_manager(
        max_workers=2,
        inmemory_factory=lambda max_workers: DummyManager(max_workers),
    )
    runtime = job_backend.get_job_backend_runtime(manager, fallback_max_workers=2)
    assert runtime["name"] == "inmemory-threadpool"
    assert runtime["worker_count"] == 2
    assert runtime["external_queue"] is False


def test_external_backend_requires_real_implementation(monkeypatch):
    monkeypatch.setenv("QCVIZ_JOB_BACKEND", "arq")
    with pytest.raises(RuntimeError):
        job_backend.build_job_manager(max_workers=1, inmemory_factory=lambda max_workers: object())
