"""
Redis async client with connection pool, cache helpers, and dependency.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

# ── Connection Pool ──
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """Lazily create a shared connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            str(settings.REDIS_URL),
            max_connections=50,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
    return _pool


def get_redis_client() -> Redis:
    """Return a Redis client bound to the shared pool."""
    return aioredis.Redis(connection_pool=_get_pool())


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency — yields a Redis client."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


# ═══════════════════════════════════════════════
# Cache Helpers
# ═══════════════════════════════════════════════


class CacheService:
    """Thin wrapper over Redis for JSON cache operations."""

    def __init__(self, client: Redis, default_ttl: int | None = None) -> None:
        self.client = client
        self.default_ttl = default_ttl or settings.REDIS_CACHE_TTL

    # ── Key helpers ──
    @staticmethod
    def _key(namespace: str, key: str) -> str:
        return f"molchat:{namespace}:{key}"

    # ── Get / Set ──
    async def get(self, namespace: str, key: str) -> Any | None:
        raw = await self.client.get(self._key(namespace, key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        ttl = ttl or self.default_ttl
        serialized = json.dumps(value, default=str)
        await self.client.set(self._key(namespace, key), serialized, ex=ttl)

    async def delete(self, namespace: str, key: str) -> None:
        await self.client.delete(self._key(namespace, key))

    async def exists(self, namespace: str, key: str) -> bool:
        return bool(await self.client.exists(self._key(namespace, key)))

    # ── Bulk ──
    async def clear_namespace(self, namespace: str) -> int:
        pattern = f"molchat:{namespace}:*"
        count = 0
        async for k in self.client.scan_iter(match=pattern, count=200):
            await self.client.delete(k)
            count += 1
        return count

    # ── Health ──
    async def ping(self) -> bool:
        try:
            return await self.client.ping()
        except Exception:
            return False


async def close_redis_pool() -> None:
    """Close the pool on application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None