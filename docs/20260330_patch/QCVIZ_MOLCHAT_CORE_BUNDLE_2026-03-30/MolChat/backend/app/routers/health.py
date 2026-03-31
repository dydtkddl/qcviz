"""
Health check & readiness endpoints.

Endpoints:
  GET /api/v1/health      – full health status (DB, Redis, LLM, Cache)
  GET /api/v1/health/live  – lightweight liveness probe (K8s)
  GET /api/v1/health/ready – readiness probe (all dependencies)
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.schemas.common import HealthResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/health")


@router.get(
    "",
    response_model=HealthResponse,
    summary="Full health check",
    description="Returns status of all dependencies: database, cache, LLM providers.",
)
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> HealthResponse:
    t0 = time.perf_counter()
    checks: dict[str, Any] = {}

    # ── PostgreSQL ──
    try:
        result = await db.execute(text("SELECT 1"))
        val = result.scalar()
        checks["database"] = {
            "status": "healthy" if val == 1 else "degraded",
            "type": "postgresql",
        }
    except Exception as exc:
        checks["database"] = {"status": "unhealthy", "error": str(exc)}

    # ── Redis ──
    try:
        pong = await redis.ping()
        info = await redis.info(section="memory")
        checks["cache"] = {
            "status": "healthy" if pong else "degraded",
            "type": "redis",
            "used_memory": info.get("used_memory_human", "unknown"),
        }
    except Exception as exc:
        checks["cache"] = {"status": "unhealthy", "error": str(exc)}

    # ── Ollama ──
    try:
        from app.services.intelligence.ollama_client import OllamaClient

        ollama = OllamaClient()
        ollama_health = await ollama.health_check()
        checks["ollama"] = ollama_health
    except Exception as exc:
        checks["ollama"] = {"status": "unhealthy", "error": str(exc)}

    # ── Gemini (connectivity only) ──
    try:
        from app.services.intelligence.gemini_client import GeminiClient

        gemini = GeminiClient()
        checks["gemini"] = await gemini.health_check()
    except Exception as exc:
        checks["gemini"] = {"status": "unhealthy", "error": str(exc)}

    # ── Calculation queue ──
    try:
        from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue

        queue = CalculationQueue(redis)
        queue_stats = await queue.stats()
        checks["calculation_queue"] = {
            "status": "healthy",
            **queue_stats,
        }
    except Exception as exc:
        checks["calculation_queue"] = {"status": "unhealthy", "error": str(exc)}

    # ── Overall status ──
    critical_healthy = all(
        checks.get(k, {}).get("status") in ("healthy", "degraded")
        for k in ("database", "cache")
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return HealthResponse(
        status="healthy" if critical_healthy else "unhealthy",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        checks=checks,
        elapsed_ms=round(elapsed_ms, 2),
    )


@router.get(
    "/live",
    summary="Liveness probe",
    description="Lightweight check — returns 200 if the process is alive.",
)
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Returns 200 only when DB and Redis are reachable.",
)
async def readiness(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        await redis.ping()
        return {"status": "ready"}
    except Exception as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=f"Not ready: {exc}")
