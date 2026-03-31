"""Redis-backed job record store shared by web and external workers."""
from __future__ import annotations

import json
import os
import math
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional


TERMINAL_STATES = {"completed", "failed", "error", "cancelled"}
ACTIVE_STATES = {"queued", "running"}
STATUS_BUCKETS = {"queued", "running", "completed", "failed", "error", "cancelled"}


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except Exception:
            pass
    return str(value)


def _now_ts() -> float:
    return time.time()


def _job_session_id(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str((payload or {}).get("session_id"))


def _job_owner_username(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str((payload or {}).get("owner_username"))


def _job_type(payload: Optional[Mapping[str, Any]]) -> str:
    return _safe_str((payload or {}).get("job_type"))


def _job_retry_count(payload: Optional[Mapping[str, Any]]) -> int:
    return max(0, _safe_int((payload or {}).get("retry_count"), 0))


def _job_max_retries(payload: Optional[Mapping[str, Any]]) -> int:
    return max(0, _safe_int((payload or {}).get("max_retries"), 0))


class RedisJobStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        prefix: Optional[str] = None,
        max_events: Optional[int] = None,
        max_active_per_session: int = 2,
        max_active_per_user: int = 3,
        max_workers: int = 1,
        poll_seconds: float = 0.25,
    ) -> None:
        self.redis = redis_client
        self.prefix = _safe_str(prefix) or _safe_str(os.getenv("QCVIZ_REDIS_PREFIX"), "qcviz")
        self.max_events = max(50, int(max_events or os.getenv("QCVIZ_MAX_JOB_EVENTS", "200")))
        self.max_active_per_session = max(0, int(max_active_per_session or 0))
        self.max_active_per_user = max(0, int(max_active_per_user or 0))
        self.max_workers = max(1, int(max_workers or 1))
        self.poll_seconds = max(0.05, float(poll_seconds or 0.25))
        self.worker_heartbeat_ttl_seconds = max(15, _safe_int(os.getenv("QCVIZ_WORKER_HEARTBEAT_TTL_SECONDS"), 90))
        self.stale_running_after_seconds = max(
            self.worker_heartbeat_ttl_seconds,
            _safe_int(os.getenv("QCVIZ_STALE_RUNNING_AFTER_SECONDS"), 180),
        )
        self.default_eta_seconds = max(5.0, _safe_float(os.getenv("QCVIZ_QUEUE_ETA_DEFAULT_SECONDS"), 75.0))

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}:{suffix}"

    def job_key(self, job_id: str) -> str:
        return self._key(f"job:{job_id}")

    def jobs_index_key(self) -> str:
        return self._key("jobs:all")

    def session_index_key(self, session_id: str) -> str:
        return self._key(f"jobs:session:{session_id}")

    def owner_index_key(self, owner_username: str) -> str:
        return self._key(f"jobs:owner:{owner_username}")

    def status_index_key(self, status: str) -> str:
        return self._key(f"jobs:status:{status}")

    def active_index_key(self) -> str:
        return self._key("jobs:status:active")

    def session_state_key(self, session_id: str) -> str:
        return self._key(f"session:{_safe_str(session_id)}:state")

    def cancel_key(self, job_id: str) -> str:
        return self._key(f"job:{job_id}:cancel")

    def worker_heartbeat_key(self, worker_id: str) -> str:
        return self._key(f"worker:{worker_id}:heartbeat")

    def clear_worker_heartbeat(self, worker_id: str) -> None:
        if not _safe_str(worker_id):
            return
        self.redis.delete(self.worker_heartbeat_key(worker_id))

    def load_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        wanted = _safe_str(session_id)
        if not wanted:
            return None
        raw = self.redis.get(self.session_state_key(wanted))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def save_session_state(self, session_id: str, state: Mapping[str, Any]) -> Dict[str, Any]:
        wanted = _safe_str(session_id)
        if not wanted:
            return {}
        payload = dict(_json_safe(dict(state or {})))
        payload["session_id"] = wanted
        payload["updated_at"] = _safe_float(payload.get("updated_at"), _now_ts())
        self.redis.set(self.session_state_key(wanted), json.dumps(payload, ensure_ascii=False))
        return payload

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        raw = self.redis.get(self.job_key(job_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def save(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        data = dict(record or {})
        job_id = _safe_str(data.get("job_id"))
        if not job_id:
            raise ValueError("job_id is required")
        payload = dict(data.get("payload") or {})
        score = _safe_float(data.get("created_at"), _now_ts())
        session_id = _job_session_id(payload)
        owner_username = _job_owner_username(payload)
        status = _safe_str(data.get("status"), "queued") or "queued"
        data["payload"] = _json_safe(payload)
        data["updated_at"] = _safe_float(data.get("updated_at"), _now_ts())
        data["events"] = list(data.get("events") or [])
        pipe = self.redis.pipeline()
        pipe.set(self.job_key(job_id), json.dumps(_json_safe(data), ensure_ascii=False))
        pipe.zadd(self.jobs_index_key(), {job_id: score})
        if session_id:
            pipe.zadd(self.session_index_key(session_id), {job_id: score})
        if owner_username:
            pipe.zadd(self.owner_index_key(owner_username), {job_id: score})
        for bucket in STATUS_BUCKETS:
            pipe.zrem(self.status_index_key(bucket), job_id)
        pipe.zrem(self.active_index_key(), job_id)
        if status in STATUS_BUCKETS:
            pipe.zadd(self.status_index_key(status), {job_id: score})
        if status in ACTIVE_STATES:
            pipe.zadd(self.active_index_key(), {job_id: score})
        pipe.execute()
        return data

    def create(self, job_id: str, payload: Mapping[str, Any], *, user_query: str = "") -> Dict[str, Any]:
        now = _now_ts()
        record = {
            "job_id": job_id,
            "payload": dict(payload or {}),
            "status": "queued",
            "progress": 0.0,
            "step": "queued",
            "message": "Queued",
            "user_query": _safe_str(user_query),
            "created_at": now,
            "started_at": None,
            "ended_at": None,
            "updated_at": now,
            "result": None,
            "error": None,
            "events": [],
            "event_seq": 0,
        }
        return self.save(record)

    def append_event(self, job_id: str, event_type: str, message: str, data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        event_seq = int(record.get("event_seq") or 0) + 1
        record["event_seq"] = event_seq
        events = list(record.get("events") or [])
        events.append(
            {
                "event_id": event_seq,
                "ts": _now_ts(),
                "type": _safe_str(event_type),
                "message": _safe_str(message),
                "data": _json_safe(dict(data or {})),
            }
        )
        if len(events) > self.max_events:
            events = events[-self.max_events :]
        record["events"] = events
        record["updated_at"] = _now_ts()
        return self.save(record)

    def update_progress(self, job_id: str, *, progress: float, step: str, message: str, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        record["progress"] = max(0.0, min(1.0, float(progress)))
        record["step"] = _safe_str(step, record.get("step") or "running")
        record["message"] = _safe_str(message, record.get("message") or "Running")
        record["updated_at"] = _now_ts()
        extra_data = dict(extra or {})
        worker_id = _safe_str(extra_data.get("worker_id"))
        if worker_id:
            record["worker_id"] = worker_id
        record = self.save(record)
        return self.append_event(
            job_id,
            "job_progress",
            record["message"],
            {"progress": record["progress"], "step": record["step"], **extra_data},
        )

    def mark_running(self, job_id: str, *, worker_id: str = "") -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        now = _now_ts()
        record["status"] = "running"
        record["step"] = "starting"
        record["message"] = "Starting job"
        record["started_at"] = now
        record["updated_at"] = now
        if _safe_str(worker_id):
            record["worker_id"] = _safe_str(worker_id)
        self.save(record)
        return self.append_event(job_id, "job_started", "Job started", {"worker_id": _safe_str(worker_id)})

    def mark_completed(self, job_id: str, result: Mapping[str, Any]) -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        now = _now_ts()
        record["status"] = "completed"
        record["progress"] = 1.0
        record["step"] = "done"
        record["message"] = "Completed"
        record["result"] = _json_safe(result)
        record["updated_at"] = now
        record["ended_at"] = now
        self.save(record)
        return self.append_event(job_id, "job_completed", "Job completed")

    def mark_failed(self, job_id: str, *, message: str, error: Mapping[str, Any]) -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        now = _now_ts()
        record["status"] = "failed"
        record["step"] = "error"
        record["message"] = _safe_str(message, "Job failed")
        record["error"] = _json_safe(dict(error or {}))
        record["updated_at"] = now
        record["ended_at"] = now
        self.save(record)
        return self.append_event(job_id, "job_failed", record["message"], record["error"])

    def mark_cancelled(self, job_id: str, *, detail: str = "Cancelled") -> Dict[str, Any]:
        record = self.load(job_id)
        if record is None:
            raise KeyError(job_id)
        now = _now_ts()
        record["status"] = "cancelled"
        record["step"] = "cancelled"
        record["message"] = _safe_str(detail, "Cancelled")
        record["updated_at"] = now
        record["ended_at"] = now
        self.save(record)
        return self.append_event(job_id, "job_cancelled", record["message"], {"detail": record["message"]})

    def request_cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        record = self.load(job_id)
        if record is None:
            return None
        self.redis.set(self.cancel_key(job_id), "1")
        record["cancel_requested"] = True
        self.save(record)
        self.append_event(job_id, "job_cancel_requested", "Cancellation requested")
        return record

    def is_cancel_requested(self, job_id: str) -> bool:
        return bool(self.redis.exists(self.cancel_key(job_id)))

    def clear_cancel(self, job_id: str) -> None:
        self.redis.delete(self.cancel_key(job_id))

    def delete(self, job_id: str) -> bool:
        record = self.load(job_id)
        if record is None:
            return False
        status = _safe_str(record.get("status"))
        if status not in TERMINAL_STATES:
            raise RuntimeError("Cannot delete a running job.")
        payload = dict(record.get("payload") or {})
        session_id = _job_session_id(payload)
        owner_username = _job_owner_username(payload)
        pipe = self.redis.pipeline()
        pipe.delete(self.job_key(job_id))
        pipe.zrem(self.jobs_index_key(), job_id)
        if session_id:
            pipe.zrem(self.session_index_key(session_id), job_id)
        if owner_username:
            pipe.zrem(self.owner_index_key(owner_username), job_id)
        for bucket in STATUS_BUCKETS:
            pipe.zrem(self.status_index_key(bucket), job_id)
        pipe.zrem(self.active_index_key(), job_id)
        pipe.delete(self.cancel_key(job_id))
        pipe.execute()
        return True

    def _recent_completed_durations(self, limit: int = 25, *, job_type: Optional[str] = None) -> List[float]:
        durations: List[float] = []
        ids = self.redis.zrevrange(self.status_index_key("completed"), 0, max(0, int(limit) - 1))
        wanted_type = _safe_str(job_type)
        for job_id in ids:
            record = self.load(job_id)
            if not record:
                continue
            if wanted_type and _job_type(record.get("payload")) != wanted_type:
                continue
            started_at = _safe_float(record.get("started_at"), 0.0)
            ended_at = _safe_float(record.get("ended_at"), 0.0)
            duration = ended_at - started_at
            if started_at > 0 and ended_at > 0 and duration > 0:
                durations.append(duration)
        return durations

    def average_runtime_seconds(self, limit: int = 25, *, job_type: Optional[str] = None) -> float:
        samples = sorted(self._recent_completed_durations(limit=limit, job_type=job_type))
        if not samples and _safe_str(job_type):
            samples = sorted(self._recent_completed_durations(limit=limit, job_type=None))
        if not samples:
            return float(self.default_eta_seconds)
        mid = len(samples) // 2
        if len(samples) % 2 == 1:
            return float(samples[mid])
        return float((samples[mid - 1] + samples[mid]) / 2.0)

    def queue_summary(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        total_count = int(self.redis.zcard(self.jobs_index_key()) or 0)
        running_count = int(self.redis.zcard(self.status_index_key("running")) or 0)
        queued_count = int(self.redis.zcard(self.status_index_key("queued")) or 0)
        active_count = int(self.redis.zcard(self.active_index_key()) or 0)
        target_record = self.load(job_id) if job_id else None
        target_job_type = _job_type((target_record or {}).get("payload"))
        avg_runtime_seconds = float(self.average_runtime_seconds(job_type=target_job_type or None))
        estimated_queue_drain_seconds = (
            int(math.ceil(float(queued_count) / float(max(1, self.max_workers))) * avg_runtime_seconds)
            if queued_count > 0
            else 0
        )
        queue: Dict[str, Any] = {
            "max_workers": self.max_workers,
            "total_count": total_count,
            "active_count": active_count,
            "running_count": running_count,
            "queued_count": queued_count,
            "available_workers": max(0, self.max_workers - running_count),
            "is_saturated": running_count >= self.max_workers,
            "avg_runtime_seconds": avg_runtime_seconds,
            "estimated_queue_drain_seconds": estimated_queue_drain_seconds,
        }
        if not job_id:
            return queue
        record = target_record or self.load(job_id)
        if record is None:
            queue.update(
                {
                    "job_id": job_id,
                    "job_status": None,
                    "queued_ahead": None,
                    "queue_position": None,
                    "active_ahead": None,
                    "active_position": None,
                    "will_wait": None,
                }
            )
            return queue
        status = _safe_str(record.get("status"))
        queue["job_id"] = job_id
        queue["job_status"] = status
        active_rank = self.redis.zrank(self.active_index_key(), job_id)
        queued_rank = self.redis.zrank(self.status_index_key("queued"), job_id)
        queue["active_ahead"] = int(active_rank) if active_rank is not None else None
        queue["active_position"] = int(active_rank) + 1 if active_rank is not None else None
        queue["queued_ahead"] = int(queued_rank) if queued_rank is not None else (0 if status == "running" else None)
        queue["queue_position"] = int(queued_rank) + 1 if queued_rank is not None else (0 if status == "running" else None)
        queue["will_wait"] = bool(status == "queued" and running_count >= self.max_workers)
        if status == "queued":
            available_now = max(0, self.max_workers - running_count)
            queued_ahead = max(0, int(queue["queued_ahead"] or 0))
            if queued_ahead < available_now:
                estimated_start_in_seconds = 0
            else:
                remaining_ahead = max(0, queued_ahead - available_now + 1)
                batches = int(math.ceil(float(remaining_ahead) / float(max(1, self.max_workers))))
                estimated_start_in_seconds = int(batches * avg_runtime_seconds)
            queue["estimated_start_in_seconds"] = estimated_start_in_seconds
            queue["estimated_finish_in_seconds"] = int(estimated_start_in_seconds + avg_runtime_seconds)
            queue["estimated_remaining_seconds"] = None
        elif status == "running":
            progress = max(0.0, min(1.0, _safe_float(record.get("progress"), 0.0)))
            queue["estimated_start_in_seconds"] = 0
            queue["estimated_remaining_seconds"] = int(max(0.0, avg_runtime_seconds * (1.0 - progress)))
            queue["estimated_finish_in_seconds"] = int(queue["estimated_remaining_seconds"])
        else:
            queue["estimated_start_in_seconds"] = None
            queue["estimated_remaining_seconds"] = None
            queue["estimated_finish_in_seconds"] = None
        return queue

    def _active_records_for_ids(self, ids: Iterable[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for job_id in ids:
            record = self.load(job_id)
            if record and _safe_str(record.get("status")) in ACTIVE_STATES:
                out.append(record)
        return out

    def quota_summary(self, *, session_id: Optional[str] = None, owner_username: Optional[str] = None) -> Dict[str, Any]:
        session = _safe_str(session_id)
        owner = _safe_str(owner_username)
        session_ids = self.redis.zrange(self.session_index_key(session), 0, -1) if session else []
        owner_ids = self.redis.zrange(self.owner_index_key(owner), 0, -1) if owner else []
        active_for_session = len(self._active_records_for_ids(session_ids))
        active_for_owner = len(self._active_records_for_ids(owner_ids))
        return {
            "session_id": session,
            "owner_username": owner,
            "active_for_session": active_for_session,
            "active_for_owner": active_for_owner,
            "max_active_per_session": self.max_active_per_session,
            "max_active_per_user": self.max_active_per_user,
            "session_limited": bool(session and self.max_active_per_session > 0),
            "user_limited": bool(owner and self.max_active_per_user > 0),
            "session_remaining": None if not session or self.max_active_per_session <= 0 else max(0, self.max_active_per_session - active_for_session),
            "user_remaining": None if not owner or self.max_active_per_user <= 0 else max(0, self.max_active_per_user - active_for_owner),
        }

    def enforce_quota(self, payload: Mapping[str, Any]) -> None:
        session = _job_session_id(payload)
        owner = _job_owner_username(payload)
        quota = self.quota_summary(session_id=session, owner_username=owner)
        if quota["user_limited"] and quota["active_for_owner"] >= quota["max_active_per_user"]:
            raise RuntimeError(
                f"Active job quota exceeded for user '{owner}' "
                f"({quota['active_for_owner']}/{quota['max_active_per_user']})."
            )
        if quota["session_limited"] and quota["active_for_session"] >= quota["max_active_per_session"]:
            raise RuntimeError(
                f"Active job quota exceeded for this session "
                f"({quota['active_for_session']}/{quota['max_active_per_session']})."
            )

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if session_id:
            ids = self.redis.zrevrange(self.session_index_key(_safe_str(session_id)), 0, -1)
        elif owner_username:
            ids = self.redis.zrevrange(self.owner_index_key(_safe_str(owner_username)), 0, -1)
        else:
            ids = self.redis.zrevrange(self.jobs_index_key(), 0, -1)
        out: List[Dict[str, Any]] = []
        for job_id in ids:
            record = self.load(job_id)
            if not record:
                continue
            if owner_username and _job_owner_username(record.get("payload")) != _safe_str(owner_username):
                continue
            if session_id and _job_session_id(record.get("payload")) != _safe_str(session_id):
                continue
            out.append(self.snapshot(record, include_payload=include_payload, include_result=include_result, include_events=include_events))
        return out

    def snapshot(
        self,
        record: Mapping[str, Any],
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Dict[str, Any]:
        payload = dict(record.get("payload") or {})
        snap = {
            "job_id": _safe_str(record.get("job_id")),
            "session_id": _job_session_id(payload),
            "owner_username": _job_owner_username(payload),
            "owner_display_name": _safe_str(payload.get("owner_display_name")),
            "worker_id": _safe_str(record.get("worker_id")),
            "status": _safe_str(record.get("status")),
            "user_query": _safe_str(record.get("user_query")),
            "job_type": payload.get("job_type", ""),
            "retry_count": _job_retry_count(payload),
            "max_retries": _job_max_retries(payload),
            "retry_origin_job_id": _safe_str(payload.get("retry_origin_job_id")),
            "retry_parent_job_id": _safe_str(payload.get("retry_parent_job_id")),
            "molecule_name": payload.get("structure_query", ""),
            "method": payload.get("method", ""),
            "basis_set": payload.get("basis", ""),
            "progress": float(record.get("progress") or 0.0),
            "step": _safe_str(record.get("step")),
            "message": _safe_str(record.get("message")),
            "created_at": _safe_float(record.get("created_at"), 0.0),
            "started_at": record.get("started_at"),
            "ended_at": record.get("ended_at"),
            "updated_at": _safe_float(record.get("updated_at"), 0.0),
            "queue": self.queue_summary(_safe_str(record.get("job_id"))),
            "quota": self.quota_summary(
                session_id=_job_session_id(payload),
                owner_username=_job_owner_username(payload),
            ),
        }
        started_at = _safe_float(record.get("started_at"), 0.0)
        ended_at = _safe_float(record.get("ended_at"), 0.0)
        if started_at > 0:
            snap["runtime_seconds"] = max(0.0, (ended_at or _now_ts()) - started_at)
        if include_payload:
            snap["payload"] = _json_safe(payload)
        if include_result:
            snap["result"] = _json_safe(record.get("result"))
            snap["error"] = _json_safe(record.get("error"))
        if include_events:
            snap["events"] = _json_safe(list(record.get("events") or []))
        return snap

    def get(
        self,
        job_id: str,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        record = self.load(job_id)
        if record is None:
            return None
        return self.snapshot(record, include_payload=include_payload, include_result=include_result, include_events=include_events)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = _now_ts() + timeout if timeout else None
        while True:
            snap = self.get(job_id, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in TERMINAL_STATES:
                return snap
            if deadline is not None and _now_ts() >= deadline:
                return snap
            time.sleep(self.poll_seconds)

    def set_worker_heartbeat(self, worker_id: str, *, status: str, extra: Optional[Mapping[str, Any]] = None, ttl_seconds: int = 120) -> None:
        payload = {"worker_id": worker_id, "status": status, "timestamp": _now_ts(), **dict(extra or {})}
        self.redis.set(self.worker_heartbeat_key(worker_id), json.dumps(_json_safe(payload), ensure_ascii=False), ex=max(30, int(ttl_seconds)))

    def list_worker_heartbeats(self, *, max_age_seconds: Optional[float] = None) -> List[Dict[str, Any]]:
        pattern = self._key("worker:*:heartbeat")
        scan_iter = getattr(self.redis, "scan_iter", None)
        if not callable(scan_iter):
            return []
        now = _now_ts()
        max_age = _safe_float(max_age_seconds, 0.0) if max_age_seconds is not None else float(self.worker_heartbeat_ttl_seconds)
        out: List[Dict[str, Any]] = []
        for key in scan_iter(match=pattern):
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if isinstance(item, dict):
                item = dict(item)
                timestamp = _safe_float(item.get("timestamp"), 0.0)
                age_seconds = max(0.0, now - timestamp) if timestamp > 0 else None
                item["age_seconds"] = age_seconds
                item["is_stale"] = bool(age_seconds is not None and max_age > 0 and age_seconds > max_age)
                out.append(item)
        out.sort(key=lambda item: float(item.get("timestamp") or 0.0), reverse=True)
        return out

    def recover_stale_running_jobs(
        self,
        *,
        heartbeat_ttl_seconds: Optional[float] = None,
        stale_after_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        heartbeat_ttl = max(15.0, _safe_float(heartbeat_ttl_seconds, float(self.worker_heartbeat_ttl_seconds)))
        stale_after = max(heartbeat_ttl, _safe_float(stale_after_seconds, float(self.stale_running_after_seconds)))
        workers = self.list_worker_heartbeats(max_age_seconds=heartbeat_ttl)
        live_workers = {
            _safe_str(item.get("worker_id")): item
            for item in workers
            if not bool(item.get("is_stale")) and _safe_str(item.get("status")).lower() != "offline"
        }
        recovered: List[Dict[str, Any]] = []
        now = _now_ts()
        for job_id in self.redis.zrange(self.active_index_key(), 0, -1):
            record = self.load(job_id)
            if not record:
                continue
            if _safe_str(record.get("status")) != "running":
                continue
            worker_id = _safe_str(record.get("worker_id"))
            updated_at = _safe_float(record.get("updated_at") or record.get("started_at") or record.get("created_at"), 0.0)
            stale_for = max(0.0, now - updated_at) if updated_at > 0 else float("inf")
            if stale_for < stale_after:
                continue
            live_worker = live_workers.get(worker_id) if worker_id else None
            worker_job_id = _safe_str((live_worker or {}).get("job_id"))
            worker_status = _safe_str((live_worker or {}).get("status")).lower()
            if live_worker and worker_job_id == _safe_str(job_id) and worker_status == "busy":
                continue
            error = {
                "message": "Recovered stale running job after worker heartbeat loss.",
                "type": "stale_job_recovered",
                "worker_id": worker_id or None,
                "stale_for_seconds": round(stale_for, 2),
                "recovered_at": now,
            }
            message = "Recovered stale running job after worker heartbeat loss."
            self.mark_failed(job_id, message=message, error=error)
            recovered.append(
                {
                    "job_id": _safe_str(job_id),
                    "worker_id": worker_id or None,
                    "stale_for_seconds": round(stale_for, 2),
                    "reason": "worker heartbeat missing or no longer assigned",
                }
            )
        return {
            "checked_workers": len(workers),
            "live_workers": len(live_workers),
            "recovered_count": len(recovered),
            "recovered_jobs": recovered,
            "heartbeat_ttl_seconds": heartbeat_ttl,
            "stale_after_seconds": stale_after,
            "checked_at": now,
        }
