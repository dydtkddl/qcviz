"""CORS middleware — always allow all origins for development."""
from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


def setup_cors(app: FastAPI) -> None:
    """Add permissive CORS for local development."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
