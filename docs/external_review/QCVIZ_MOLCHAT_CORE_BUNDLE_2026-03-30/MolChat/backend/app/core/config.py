"""
Application settings loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the MolChat backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──
    APP_NAME: str = "MolChat"
    APP_ENV: Literal["development", "staging", "production", "test"] = "production"
    APP_DEBUG: bool = False
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"  # noqa: S104
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ── PostgreSQL ──
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "molchat"
    POSTGRES_USER: str = "molchat"
    POSTGRES_PASSWORD: str = ""
    DATABASE_URL: PostgresDsn | str = ""
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: str, info: object) -> str:
        if v:
            return v
        data = info.data if hasattr(info, "data") else {}
        user = data.get("POSTGRES_USER", "molchat")
        password = data.get("POSTGRES_PASSWORD", "")
        host = data.get("POSTGRES_HOST", "postgres")
        port = data.get("POSTGRES_PORT", 5432)
        db = data.get("POSTGRES_DB", "molchat")
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

    # ── Redis ──
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_URL: RedisDsn | str = ""
    REDIS_CACHE_TTL: int = 3600
    REDIS_MAX_MEMORY: str = "512mb"

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_url(cls, v: str, info: object) -> str:
        if v:
            return v
        data = info.data if hasattr(info, "data") else {}
        password = data.get("REDIS_PASSWORD", "")
        host = data.get("REDIS_HOST", "redis")
        port = data.get("REDIS_PORT", 6379)
        return f"redis://:{password}@{host}:{port}/0"

    # ── Gemini (Primary LLM) ──
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_MAX_TOKENS: int = 8192
    GEMINI_TEMPERATURE: float = 0.3
    GEMINI_TIMEOUT: int = 30
    GEMINI_MONTHLY_COST_LIMIT: float = 50.0

    # ── Ollama (Fallback LLM) ──
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL_PRIMARY: str = "qwen3:32b"
    OLLAMA_MODEL_FALLBACK: str = "qwen3:8b"
    OLLAMA_TIMEOUT: int = 120
    OLLAMA_NUM_CTX: int = 8192

    # ── ChemSpider (Optional) ──
    CHEMSPIDER_API_KEY: str = ""

    # ── JWT / Auth ──
    JWT_SECRET_KEY: str = "CHANGE_ME_JWT_SECRET_AT_LEAST_32_CHARS"  # noqa: S105
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    API_KEY_HASH_ALGORITHM: str = "sha256"

    # ── xTB Worker ──
    XTB_WORKER_CONCURRENCY: int = 2
    XTB_MAX_ATOMS: int = 200
    XTB_TIMEOUT: int = 20
    XTB_METHOD: str = "gfn2"

    # ── Rate Limiting ──
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW: int = 60

    # ── Monitoring ──
    PROMETHEUS_ENABLED: bool = True

    # ── Computed helpers ──
    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def database_url_sync(self) -> str:
        """Synchronous DB URL for Alembic offline mode."""
        return str(self.DATABASE_URL).replace(
            "postgresql+asyncpg://", "postgresql://"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()