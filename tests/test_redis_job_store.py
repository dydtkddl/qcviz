from __future__ import annotations

import fnmatch
from typing import Any, Dict, List

from qcviz_mcp.web import redis_job_store as store_mod
from qcviz_mcp.web.redis_job_store import RedisJobStore


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops: List[tuple[str, tuple[Any, ...], Dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def _call(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return _call

    def execute(self):
        out = []
        for name, args, kwargs in self.ops:
            out.append(getattr(self.redis, name)(*args, **kwargs))
        self.ops.clear()
        return out


class FakeRedis:
    def __init__(self):
        self.kv: Dict[str, Any] = {}
        self.zsets: Dict[str, Dict[str, float]] = {}

    def pipeline(self):
        return FakePipeline(self)

    def get(self, key: str):
        return self.kv.get(key)

    def set(self, key: str, value: Any, ex: int | None = None):
        self.kv[key] = value
        return True

    def delete(self, key: str):
        self.kv.pop(key, None)
        self.zsets.pop(key, None)
        return True

    def exists(self, key: str):
        return 1 if key in self.kv else 0

    def zadd(self, key: str, mapping: Dict[str, float]):
        bucket = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            bucket[str(member)] = float(score)
        return True

    def zrem(self, key: str, member: str):
        bucket = self.zsets.setdefault(key, {})
        bucket.pop(str(member), None)
        return True

    def zcard(self, key: str):
        return len(self.zsets.get(key, {}))

    def zrank(self, key: str, member: str):
        bucket = self.zsets.get(key, {})
        ordered = sorted(bucket.items(), key=lambda item: (item[1], item[0]))
        for idx, (name, _) in enumerate(ordered):
            if name == str(member):
                return idx
        return None

    def zrange(self, key: str, start: int, end: int):
        bucket = self.zsets.get(key, {})
        ordered = [name for name, _ in sorted(bucket.items(), key=lambda item: (item[1], item[0]))]
        if end == -1:
            return ordered[start:]
        return ordered[start : end + 1]

    def zrevrange(self, key: str, start: int, end: int):
        bucket = self.zsets.get(key, {})
        ordered = [name for name, _ in sorted(bucket.items(), key=lambda item: (item[1], item[0]), reverse=True)]
        if end == -1:
            return ordered[start:]
        return ordered[start : end + 1]

    def scan_iter(self, match: str | None = None):
        if not match:
            for key in self.kv:
                yield key
            return
        for key in self.kv:
            if fnmatch.fnmatch(str(key), match):
                yield key


def test_redis_job_store_create_progress_complete_and_queue_summary():
    redis = FakeRedis()
    store = RedisJobStore(redis, max_workers=1, max_active_per_session=2, max_active_per_user=3, poll_seconds=0.01)
    payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "benzene", "job_type": "orbital_preview"}
    store.create("job-1", payload, user_query="benzene HOMO")
    store.append_event("job-1", "job_submitted", "Job submitted")
    snap = store.get("job-1", include_payload=True, include_events=True)
    assert snap is not None
    assert snap["status"] == "queued"
    assert snap["queue"]["queued_count"] == 1
    store.mark_running("job-1")
    store.update_progress("job-1", progress=0.5, step="scf", message="Running SCF", extra={"scf_cycle": 3})
    running = store.get("job-1", include_events=True)
    assert running["status"] == "running"
    assert running["queue"]["running_count"] == 1
    assert any(event["type"] == "job_progress" for event in running["events"])
    store.mark_completed("job-1", {"success": True, "structure_query": "benzene"})
    done = store.get("job-1", include_result=True, include_events=True)
    assert done["status"] == "completed"
    assert done["result"]["structure_query"] == "benzene"


def test_redis_job_store_quota_and_cancel_flow():
    redis = FakeRedis()
    store = RedisJobStore(redis, max_workers=1, max_active_per_session=1, max_active_per_user=1, poll_seconds=0.01)
    payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "water", "job_type": "single_point"}
    store.create("job-1", payload, user_query="water")
    quota = store.quota_summary(session_id="sess-a", owner_username="alice")
    assert quota["active_for_session"] == 1
    assert quota["active_for_owner"] == 1
    try:
        store.enforce_quota(payload)
    except RuntimeError as exc:
        assert "quota exceeded" in str(exc)
    else:
        raise AssertionError("quota enforcement should fail")
    cancel = store.request_cancel("job-1")
    assert cancel is not None
    assert store.is_cancel_requested("job-1") is True
    store.mark_cancelled("job-1", detail="Cancelled externally")
    cancelled = store.get("job-1", include_events=True)
    assert cancelled["status"] == "cancelled"
    assert store.delete("job-1") is True
    assert store.get("job-1") is None


def test_redis_job_store_lists_worker_heartbeats():
    redis = FakeRedis()
    store = RedisJobStore(redis, max_workers=1)
    store.set_worker_heartbeat("worker-a", status="idle", extra={"queue": "qcviz-jobs"})
    store.set_worker_heartbeat("worker-b", status="busy", extra={"job_id": "job-2"})
    workers = store.list_worker_heartbeats()
    assert len(workers) == 2
    assert {item["worker_id"] for item in workers} == {"worker-a", "worker-b"}
    assert all("age_seconds" in item for item in workers)
    store.clear_worker_heartbeat("worker-a")
    workers = store.list_worker_heartbeats()
    assert {item["worker_id"] for item in workers} == {"worker-b"}


def test_redis_job_store_queue_summary_includes_eta(monkeypatch):
    redis = FakeRedis()
    now = {"value": 1000.0}
    monkeypatch.setattr(store_mod, "_now_ts", lambda: now["value"])
    store = RedisJobStore(redis, max_workers=1, poll_seconds=0.01)

    payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "benzene", "job_type": "single_point"}
    store.create("job-1", payload, user_query="benzene")
    store.mark_running("job-1", worker_id="worker-a")
    now["value"] = 1060.0
    store.mark_completed("job-1", {"ok": True})

    now["value"] = 1065.0
    store.create("job-2", payload, user_query="benzene gap")
    queue = store.queue_summary("job-2")
    assert queue["queued_count"] == 1
    assert queue["avg_runtime_seconds"] >= 60
    assert queue["estimated_finish_in_seconds"] >= queue["avg_runtime_seconds"]


def test_redis_job_store_queue_summary_prefers_same_job_type_history(monkeypatch):
    redis = FakeRedis()
    now = {"value": 500.0}
    monkeypatch.setattr(store_mod, "_now_ts", lambda: now["value"])
    store = RedisJobStore(redis, max_workers=1, poll_seconds=0.01)

    sp_payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "water", "job_type": "single_point"}
    esp_payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "acetone", "job_type": "esp_map"}

    store.create("job-sp", sp_payload, user_query="water")
    store.mark_running("job-sp", worker_id="worker-a")
    now["value"] = 520.0
    store.mark_completed("job-sp", {"ok": True})

    now["value"] = 530.0
    store.create("job-esp-old", esp_payload, user_query="acetone ESP")
    store.mark_running("job-esp-old", worker_id="worker-a")
    now["value"] = 650.0
    store.mark_completed("job-esp-old", {"ok": True})

    now["value"] = 655.0
    store.create("job-esp-new", esp_payload, user_query="acetone ESP again")
    queue = store.queue_summary("job-esp-new")
    assert queue["avg_runtime_seconds"] >= 120
    assert queue["estimated_finish_in_seconds"] >= 120


def test_redis_job_store_recovers_stale_running_job(monkeypatch):
    redis = FakeRedis()
    now = {"value": 2000.0}
    monkeypatch.setattr(store_mod, "_now_ts", lambda: now["value"])
    store = RedisJobStore(redis, max_workers=1, poll_seconds=0.01)
    payload = {"session_id": "sess-a", "owner_username": "alice", "structure_query": "water", "job_type": "single_point"}
    store.create("job-stale", payload, user_query="water")
    store.mark_running("job-stale", worker_id="worker-z")
    record = store.load("job-stale")
    assert record is not None
    record["updated_at"] = 1700.0
    store.save(record)

    now["value"] = 2000.0
    recovery = store.recover_stale_running_jobs(heartbeat_ttl_seconds=30, stale_after_seconds=120)
    recovered = store.get("job-stale", include_result=True)
    assert recovery["recovered_count"] == 1
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error"]["type"] == "stale_job_recovered"


def test_redis_job_store_snapshot_exposes_retry_metadata():
    redis = FakeRedis()
    store = RedisJobStore(redis, max_workers=1, poll_seconds=0.01)
    payload = {
        "session_id": "sess-a",
        "owner_username": "alice",
        "structure_query": "water",
        "job_type": "single_point",
        "retry_count": 1,
        "max_retries": 3,
        "retry_origin_job_id": "job-root",
        "retry_parent_job_id": "job-parent",
    }
    store.create("job-retry", payload, user_query="water")
    snap = store.get("job-retry", include_payload=True)
    assert snap is not None
    assert snap["retry_count"] == 1
    assert snap["max_retries"] == 3
    assert snap["retry_origin_job_id"] == "job-root"
    assert snap["retry_parent_job_id"] == "job-parent"
