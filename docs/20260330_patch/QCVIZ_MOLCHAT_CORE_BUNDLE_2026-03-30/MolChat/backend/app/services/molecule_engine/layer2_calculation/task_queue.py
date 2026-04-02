"""
CalculationQueue – async task queue for long-running L2 calculations.

Uses Redis as the broker and result backend. Tasks are submitted as
lightweight descriptors and picked up by the ``xtb-worker`` process.

Architecture:
  • Producer (API process) → Redis LIST ``molchat:calc:queue``
  • Consumer (worker process) → BRPOP loop
  • Status stored in Redis HASH ``molchat:calc:status:<task_id>``
  • Results stored in Redis HASH ``molchat:calc:result:<task_id>``
  • TTL on status/result keys: 24 hours

This avoids a hard Celery dependency while preserving the same
semantics. Can be swapped for Celery with minimal changes.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis

from app.core.config import settings
from app.core.redis import get_redis_client

logger = structlog.get_logger(__name__)

_QUEUE_KEY = "molchat:calc:queue"
_STATUS_PREFIX = "molchat:calc:status:"
_RESULT_PREFIX = "molchat:calc:result:"
_TTL = 86400  # 24 hours


class CalculationQueue:
    """Submit, poll, and manage L2 calculation tasks."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    def _get_redis(self) -> Redis:
        return self._redis or get_redis_client()

    # ═══════════════════════════════════════════
    # Producer API
    # ═══════════════════════════════════════════

    async def submit(
        self,
        molecule_id: uuid.UUID,
        smiles: str,
        method: str = "gfn2",
        tasks: list[str] | None = None,
        charge: int = 0,
        multiplicity: int = 1,
        solvent: str | None = None,
        priority: int = 5,
    ) -> str:
        """Submit a calculation task and return a unique task_id."""
        task_id = f"calc-{uuid.uuid4().hex[:12]}"
        redis = self._get_redis()

        payload = {
            "task_id": task_id,
            "molecule_id": str(molecule_id),
            "smiles": smiles,
            "method": method,
            "tasks": tasks or ["energy"],
            "charge": charge,
            "multiplicity": multiplicity,
            "solvent": solvent,
            "priority": priority,
            "submitted_at": time.time(),
        }

        # Set initial status
        await redis.set(
            f"{_STATUS_PREFIX}{task_id}",
            json.dumps({
                "task_id": task_id,
                "status": "pending",
                "submitted_at": payload["submitted_at"],
                "progress": 0,
            }),
            ex=_TTL,
        )

        # Push to queue (LPUSH for FIFO with BRPOP consumer)
        await redis.lpush(_QUEUE_KEY, json.dumps(payload))

        logger.info(
            "calc_task_submitted",
            task_id=task_id,
            molecule_id=str(molecule_id),
            tasks=tasks,
        )

        return task_id

    async def get_status(self, task_id: str) -> dict[str, Any]:
        """Poll the current status of a task."""
        redis = self._get_redis()
        raw = await redis.get(f"{_STATUS_PREFIX}{task_id}")
        if raw is None:
            return {"task_id": task_id, "status": "not_found"}

        data = json.loads(raw)

        # If completed, attach results
        if data.get("status") == "completed":
            result_raw = await redis.get(f"{_RESULT_PREFIX}{task_id}")
            if result_raw:
                data["result"] = json.loads(result_raw)

        return data

    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve the full calculation result (None if not yet complete)."""
        redis = self._get_redis()
        raw = await redis.get(f"{_RESULT_PREFIX}{task_id}")
        if raw is None:
            return None
        return json.loads(raw)

    # ═══════════════════════════════════════════
    # Consumer API (used by xtb-worker)
    # ═══════════════════════════════════════════

    async def dequeue(self, timeout: int = 30) -> dict[str, Any] | None:
        """Block-pop the next task from the queue.

        Returns the task payload dict or None on timeout.
        Called by the worker loop.
        """
        redis = self._get_redis()
        result = await redis.brpop(_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None

        _, raw = result
        payload = json.loads(raw)

        # Update status to running
        await self.update_status(
            payload["task_id"],
            status="running",
            progress=0,
            started_at=time.time(),
        )

        logger.info(
            "calc_task_dequeued",
            task_id=payload["task_id"],
            molecule_id=payload.get("molecule_id"),
        )

        return payload

    async def update_status(
        self,
        task_id: str,
        *,
        status: str,
        progress: int = 0,
        message: str = "",
        **extra: Any,
    ) -> None:
        """Update the status of a running task."""
        redis = self._get_redis()
        existing_raw = await redis.get(f"{_STATUS_PREFIX}{task_id}")

        if existing_raw:
            existing = json.loads(existing_raw)
        else:
            existing = {"task_id": task_id}

        existing.update({
            "status": status,
            "progress": progress,
            "message": message,
            "updated_at": time.time(),
            **extra,
        })

        await redis.set(
            f"{_STATUS_PREFIX}{task_id}",
            json.dumps(existing, default=str),
            ex=_TTL,
        )

    async def store_result(
        self,
        task_id: str,
        result: dict[str, Any],
    ) -> None:
        """Store the final calculation result and mark status as completed."""
        redis = self._get_redis()

        # Store result
        await redis.set(
            f"{_RESULT_PREFIX}{task_id}",
            json.dumps(result, default=str),
            ex=_TTL,
        )

        # Update status
        await self.update_status(
            task_id,
            status="completed",
            progress=100,
            completed_at=time.time(),
        )

        logger.info("calc_task_completed", task_id=task_id)

    async def mark_failed(
        self,
        task_id: str,
        error: str,
    ) -> None:
        """Mark a task as failed with an error message."""
        await self.update_status(
            task_id,
            status="failed",
            progress=0,
            error=error,
            failed_at=time.time(),
        )
        logger.warning("calc_task_failed", task_id=task_id, error=error)

    # ═══════════════════════════════════════════
    # Queue Management
    # ═══════════════════════════════════════════

    async def queue_length(self) -> int:
        """Return the number of pending tasks in the queue."""
        redis = self._get_redis()
        return await redis.llen(_QUEUE_KEY)

    async def cancel(self, task_id: str) -> bool:
        """Attempt to cancel a pending task.

        Only works if the task hasn't been dequeued yet.
        Returns True if the task was found and removed.
        """
        redis = self._get_redis()

        # Scan the queue for the task_id
        queue_items = await redis.lrange(_QUEUE_KEY, 0, -1)
        for item in queue_items:
            payload = json.loads(item)
            if payload.get("task_id") == task_id:
                removed = await redis.lrem(_QUEUE_KEY, 1, item)
                if removed > 0:
                    await self.update_status(
                        task_id,
                        status="cancelled",
                        progress=0,
                        cancelled_at=time.time(),
                    )
                    logger.info("calc_task_cancelled", task_id=task_id)
                    return True

        # If already running, we can't cancel from here
        status = await self.get_status(task_id)
        if status.get("status") == "running":
            logger.warning(
                "calc_task_cancel_running",
                task_id=task_id,
                message="Cannot cancel a running task",
            )
        return False

    async def cleanup_stale(self, max_age_seconds: int = 7200) -> int:
        """Clean up tasks stuck in 'running' state beyond max_age.

        Returns number of tasks marked as failed.
        """
        redis = self._get_redis()
        now = time.time()
        cleaned = 0

        # Scan all status keys
        async for key in redis.scan_iter(match=f"{_STATUS_PREFIX}*", count=200):
            raw = await redis.get(key)
            if raw is None:
                continue

            data = json.loads(raw)
            if data.get("status") != "running":
                continue

            started_at = data.get("started_at", 0)
            if now - started_at > max_age_seconds:
                task_id = data.get("task_id", key.replace(_STATUS_PREFIX, ""))
                await self.mark_failed(
                    task_id,
                    error=f"Task stale: running for > {max_age_seconds}s",
                )
                cleaned += 1

        if cleaned > 0:
            logger.warning("calc_stale_tasks_cleaned", count=cleaned)

        return cleaned

    async def stats(self) -> dict[str, Any]:
        """Return queue statistics for monitoring."""
        redis = self._get_redis()

        pending = await self.queue_length()

        running = 0
        completed = 0
        failed = 0

        async for key in redis.scan_iter(match=f"{_STATUS_PREFIX}*", count=500):
            raw = await redis.get(key)
            if raw is None:
                continue
            data = json.loads(raw)
            st = data.get("status")
            if st == "running":
                running += 1
            elif st == "completed":
                completed += 1
            elif st == "failed":
                failed += 1

        return {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "total_tracked": pending + running + completed + failed,
        }