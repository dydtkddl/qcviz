"""
API Routers – FastAPI route definitions for MolChat.

All routers share the ``/api/v1`` prefix and are registered
in ``main.py`` via ``include_routers(app)``.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.routers.chat import router as chat_router
from app.routers.feedback import router as feedback_router
from app.routers.health import router as health_router
from app.routers.molecules import router as molecules_router
from app.routers.sessions import router as sessions_router
from app.routers.websocket import router as ws_router

_API_PREFIX = "/api/v1"


def include_routers(app: FastAPI) -> None:
    """Register all routers on the FastAPI application."""
    app.include_router(health_router, prefix=_API_PREFIX, tags=["Health"])
    app.include_router(molecules_router, prefix=_API_PREFIX, tags=["Molecules"])
    app.include_router(chat_router, prefix=_API_PREFIX, tags=["Chat"])
    app.include_router(sessions_router, prefix=_API_PREFIX, tags=["Sessions"])
    app.include_router(feedback_router, prefix=_API_PREFIX, tags=["Feedback"])
    app.include_router(ws_router, prefix="", tags=["WebSocket"])


__all__ = ["include_routers"]