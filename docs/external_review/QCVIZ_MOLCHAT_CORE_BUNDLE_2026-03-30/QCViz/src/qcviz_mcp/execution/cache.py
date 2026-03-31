"""Execution cache shim module."""

class _FallbackCache:
    def get(self, key):
        return None
    def set(self, key, value, ttl=None):
        pass
    def clear(self):
        pass
    def __call__(self, func):
        return func

cache = _FallbackCache()
