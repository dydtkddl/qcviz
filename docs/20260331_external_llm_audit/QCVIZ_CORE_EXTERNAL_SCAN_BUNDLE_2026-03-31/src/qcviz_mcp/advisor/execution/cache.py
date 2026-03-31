import hashlib
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

@dataclass
class CacheEntry:
    key: str
    result: Any
    created_at: float
    ttl_seconds: float = 3600.0  # 기본 1시간
    
    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class ComputationCache:
    """SCF/IBO 계산 결과의 in-memory LRU 캐시."""
    
    def __init__(self, max_size: int = 50, ttl_seconds: float = 3600.0):
        self._store: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
    
    @staticmethod
    def make_key(tool_name: str, **params) -> str:
        """결정론적 캐시 키 생성."""
        canonical = json.dumps(
            {"tool": tool_name, **params}, 
            sort_keys=True, 
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
    
    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._store[key]
            return None
        return entry.result
    
    def put(self, key: str, result: Any):
        if len(self._store) >= self._max_size:
            # LRU: 가장 오래된 것 제거
            oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
            del self._store[oldest_key]
        self._store[key] = CacheEntry(
            key=key, result=result, created_at=time.monotonic(), ttl_seconds=self._ttl
        )

cache = ComputationCache()
