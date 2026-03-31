"""
MoleculeCacheManager – transparent Redis caching layer for the Molecule Engine.

Strategy:
  • Read-through: check cache before upstream.
  • Write-through: populate cache after upstream.
  • Namespace isolation: ``mol:search:<hash>``, ``mol:detail:<uuid>``, ``mol:struct:<uuid>:<fmt>``.
  • TTL hierarchy: search results 15 min, detail 1 h, structures 24 h.
  • Graceful degradation: all methods return ``None`` on Redis failure.

Serialization uses ``orjson`` for speed (~6× faster than stdlib json).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import orjson
import structlog
from redis.asyncio import Redis

from app.core.config import settings

logger = structlog.get_logger(__name__)

# TTLs (seconds)
_TTL_SEARCH = 900       # 15 minutes
_TTL_DETAIL = 3600      # 1 hour
_TTL_STRUCTURE = 86400  # 24 hours
_TTL_CALC = 600         # 10 minutes (in-progress status)


def _hash_key(*parts: str) -> str:
    """Produce a deterministic short hash from variable-length key parts."""
    raw = ":".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _serialize(obj: Any) -> bytes:
    """Serialize to JSON bytes via orjson."""
    return orjson.dumps(obj, default=str)


def _deserialize(raw: bytes | str | None) -> Any | None:
    """Deserialize JSON bytes, returning None on failure."""
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return orjson.loads(raw)
    except (orjson.JSONDecodeError, TypeError, ValueError):
        return None


class MoleculeCacheManager:
    """Redis-backed caching for the Molecule Engine.

    Every public method is safe to call even when Redis is down –
    failures are logged and ``None`` / silent-fail is returned.
    """

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ═══════════════════════════════════════════
    # Search cache
    # ═══════════════════════════════════════════

    def _search_key(self, query: str, limit: int, offset: int) -> str:
        h = _hash_key(query.lower().strip(), str(limit), str(offset))
        return f"mol:search:{h}"

    async def get_search(
        self, query: str, limit: int, offset: int
    ) -> Any | None:
        """Return cached MoleculeSearchResponse dict or None."""
        try:
            key = self._search_key(query, limit, offset)
            raw = await self._r.get(key)
            if raw is None:
                return None
            data = _deserialize(raw)
            if data is None:
                return None

            # Re-hydrate into schema
            from app.schemas.molecule import MoleculeSearchResponse

            return MoleculeSearchResponse(**data)
        except Exception as exc:
            logger.warning("cache_get_search_error", error=str(exc))
            return None

    async def set_search(
        self, query: str, limit: int, offset: int, response: Any
    ) -> None:
        """Cache a search response."""
        try:
            key = self._search_key(query, limit, offset)
            data = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
            await self._r.set(key, _serialize(data), ex=_TTL_SEARCH)
            logger.debug("cache_set_search", key=key)
        except Exception as exc:
            logger.warning("cache_set_search_error", error=str(exc))

    # ═══════════════════════════════════════════
    # Detail cache
    # ═══════════════════════════════════════════

    def _detail_key(self, molecule_id: uuid.UUID) -> str:
        return f"mol:detail:{molecule_id}"

    async def get_detail(self, molecule_id: uuid.UUID) -> Any | None:
        """Return cached MoleculeDetailResponse dict or None."""
        try:
            raw = await self._r.get(self._detail_key(molecule_id))
            if raw is None:
                return None
            data = _deserialize(raw)
            if data is None:
                return None

            from app.schemas.molecule import MoleculeDetailResponse

            return MoleculeDetailResponse(**data)
        except Exception as exc:
            logger.warning("cache_get_detail_error", error=str(exc))
            return None

    async def set_detail(
        self, molecule_id: uuid.UUID, response: Any
    ) -> None:
        """Cache a molecule detail response."""
        try:
            key = self._detail_key(molecule_id)
            data = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
            await self._r.set(key, _serialize(data), ex=_TTL_DETAIL)
            logger.debug("cache_set_detail", key=key)
        except Exception as exc:
            logger.warning("cache_set_detail_error", error=str(exc))

    # ═══════════════════════════════════════════
    # Structure cache (large blobs – longer TTL)
    # ═══════════════════════════════════════════

    def _structure_key(self, molecule_id: uuid.UUID, fmt: str) -> str:
        return f"mol:struct:{molecule_id}:{fmt}"

    async def get_structure(
        self, molecule_id: uuid.UUID, fmt: str
    ) -> str | None:
        """Return cached raw structure string (SDF, XYZ, etc.) or None."""
        try:
            raw = await self._r.get(self._structure_key(molecule_id, fmt))
            if raw is None:
                return None
            return raw if isinstance(raw, str) else raw.decode("utf-8")
        except Exception as exc:
            logger.warning("cache_get_structure_error", error=str(exc))
            return None

    async def set_structure(
        self, molecule_id: uuid.UUID, fmt: str, data: str
    ) -> None:
        """Cache a raw structure string."""
        try:
            key = self._structure_key(molecule_id, fmt)
            await self._r.set(key, data.encode("utf-8"), ex=_TTL_STRUCTURE)
            logger.debug("cache_set_structure", key=key, fmt=fmt)
        except Exception as exc:
            logger.warning("cache_set_structure_error", error=str(exc))


    # ═══════════════════════════════════════════
    # Calculation status cache (short TTL)
    # ═══════════════════════════════════════════

    def _calc_key(self, task_id: str) -> str:
        return f"mol:calc:{task_id}"

    async def get_calc_status(self, task_id: str) -> dict | None:
        """Return cached calculation status or None."""
        try:
            raw = await self._r.get(self._calc_key(task_id))
            return _deserialize(raw)
        except Exception as exc:
            logger.warning("cache_get_calc_error", error=str(exc))
            return None

    async def set_calc_status(
        self, task_id: str, status: dict, ttl: int | None = None
    ) -> None:
        """Cache a calculation status dict."""
        try:
            key = self._calc_key(task_id)
            await self._r.set(key, _serialize(status), ex=ttl or _TTL_CALC)
        except Exception as exc:
            logger.warning("cache_set_calc_error", error=str(exc))

    # ═══════════════════════════════════════════
    # Invalidation
    # ═══════════════════════════════════════════

    async def invalidate_molecule(self, molecule_id: uuid.UUID) -> int:
        """Purge all cached data for a specific molecule.

        Returns the number of keys deleted.
        """
        deleted = 0
        try:
            # Detail
            deleted += await self._r.delete(self._detail_key(molecule_id))

            # Structures (scan pattern)
            pattern = f"mol:struct:{molecule_id}:*"
            async for key in self._r.scan_iter(match=pattern, count=100):
                deleted += await self._r.delete(key)

            logger.info(
                "cache_invalidated_molecule",
                molecule_id=str(molecule_id),
                keys_deleted=deleted,
            )
        except Exception as exc:
            logger.warning("cache_invalidate_error", error=str(exc))
        return deleted

    async def invalidate_search(self, query: str | None = None) -> int:
        """Purge search caches. If query is None, purge ALL search caches."""
        deleted = 0
        try:
            if query:
                # Only invalidate caches matching this query (any limit/offset)
                h = _hash_key(query.lower().strip())
                # hash_key only uses first part so we can't reverse; purge by prefix
                pattern = f"mol:search:*"
            else:
                pattern = "mol:search:*"

            async for key in self._r.scan_iter(match=pattern, count=200):
                deleted += await self._r.delete(key)

            logger.info("cache_invalidated_search", keys_deleted=deleted)
        except Exception as exc:
            logger.warning("cache_invalidate_search_error", error=str(exc))
        return deleted

    async def flush_all(self) -> None:
        """Purge the entire mol: namespace. Use with caution."""
        try:
            count = 0
            async for key in self._r.scan_iter(match="mol:*", count=500):
                await self._r.delete(key)
                count += 1
            logger.warning("cache_flushed_all", keys_deleted=count)
        except Exception as exc:
            logger.warning("cache_flush_error", error=str(exc))

    # ═══════════════════════════════════════════
    # Health / Stats
    # ═══════════════════════════════════════════

    async def health(self) -> dict[str, Any]:
        """Return cache health info for the /health endpoint."""
        try:
            pong = await self._r.ping()
            info = await self._r.info(section="memory")
            key_count = 0
            async for _ in self._r.scan_iter(match="mol:*", count=500):
                key_count += 1

            return {
                "status": "healthy" if pong else "degraded",
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "used_memory_peak_human": info.get("used_memory_peak_human", "unknown"),
                "mol_key_count": key_count,
            }
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}



    # ═══════════════════════════════════════════
    # Generic raw cache (for molecule card etc.)
    # ═══════════════════════════════════════════

    async def get_raw(self, key: str) -> dict | None:
        """Get a raw JSON dict from Redis."""
        try:
            import orjson
            data = await self._r.get(key)
            if data is not None:
                return orjson.loads(data)
        except Exception as e:
            pass
        return None

    async def set_raw(self, key: str, value: dict, ttl: int = 86400) -> None:
        """Store a raw JSON dict in Redis with TTL."""
        try:
            import orjson
            await self._r.set(key, orjson.dumps(value), ex=ttl)
        except Exception as e:
            import traceback; print(f'SET_RAW ERROR: {e} {traceback.format_exc()}')
