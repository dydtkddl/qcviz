"""
FastAPI application entry point.

Configures:
  • Application metadata (title, version, docs)
  • Middleware stack
  • Route registration
  • Startup / shutdown lifecycle hooks
  • Prometheus metrics (optional)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.database import dispose_engine, engine
from app.core.logging import setup_logging
from app.core.redis import close_redis_pool
from app.middleware import register_middleware
from app.middleware.error_handler import ErrorHandlerMiddleware, MolChatError
from app.routers import include_routers

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    # ── Startup ──
    setup_logging()
    logger.info(
        "app_starting",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
    )

    # Verify database connectivity
    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected")
    except Exception as exc:
        logger.error("database_connection_failed", error=str(exc))

    # Verify Redis connectivity
    try:
        from app.core.redis import get_redis_client

        client = get_redis_client()
        await client.ping()
        await client.aclose()
        logger.info("redis_connected")
    except Exception as exc:
        logger.warning("redis_connection_failed", error=str(exc))

    # Prometheus metrics
    if settings.PROMETHEUS_ENABLED:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator

            Instrumentator(
                should_group_status_codes=True,
                should_ignore_untemplated=True,
                should_respect_env_var=False,
                excluded_handlers=["/health/live", "/metrics"],
                env_var_name="ENABLE_METRICS",
            )  # .instrument(app).expose(app, endpoint="/metrics")  # moved outside lifespan
            logger.info("prometheus_metrics_enabled")
        except ImportError:
            logger.debug("prometheus_instrumentator_not_installed")

    logger.info("app_started")
    yield

    # ── Shutdown ──
    logger.info("app_shutting_down")
    await close_redis_pool()
    await dispose_engine()
    logger.info("app_stopped")


# ═══════════════════════════════════════════════
# Application factory
# ═══════════════════════════════════════════════


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "MolChat – AI-Powered Molecular Intelligence Chatbot API. "
            "Search molecules, visualize structures, compute properties, "
            "and chat with an AI chemistry assistant."
        ),
        docs_url="/docs" if settings.APP_DEBUG or settings.is_development else None,
        redoc_url="/redoc" if settings.APP_DEBUG or settings.is_development else None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Middleware
    register_middleware(app)

    # Routes
    include_routers(app)

    # Root redirect
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


# ── Singleton for uvicorn ──
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower(),
        workers=1,
    )