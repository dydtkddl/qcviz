import logging
import time
import json
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger("qcviz_mcp")

@dataclass
class ToolInvocation:
    tool_name: str
    request_id: str
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    status: str = "running"
    parameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.monotonic() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def finish(self, status: str = "success", **extra_metrics):
        self.end_time = time.monotonic()
        self.status = status
        self.metrics.update(extra_metrics)

    def to_log_dict(self) -> dict:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d


class MetricsCollector:
    """In-process metrics aggregation. 
    Enterprise deployment would export to Prometheus/OTLP."""
    
    def __init__(self):
        self._invocations: list[ToolInvocation] = []
        self._counters: dict[str, int] = {}
    
    def record(self, invocation: ToolInvocation):
        self._invocations.append(invocation)
        self._counters[f"{invocation.tool_name}.{invocation.status}"] = (
            self._counters.get(f"{invocation.tool_name}.{invocation.status}", 0) + 1
        )
    
    def get_summary(self) -> dict:
        return {
            "total_invocations": len(self._invocations),
            "counters": dict(self._counters),
            "avg_duration_ms": {
                name: sum(
                    inv.duration_ms for inv in self._invocations 
                    if inv.tool_name == name
                ) / max(1, sum(1 for inv in self._invocations if inv.tool_name == name))
                for name in {inv.tool_name for inv in self._invocations}
            }
        }

# Singleton
metrics = MetricsCollector()


@contextmanager
def track_operation(tool_name: str, *, request_id: str | None = None, parameters: dict[str, Any] | None = None):
    """Context manager for lightweight route/service observability."""
    import uuid

    invocation = ToolInvocation(
        tool_name=tool_name,
        request_id=request_id or str(uuid.uuid4())[:8],
        parameters={k: _safe_repr(v) for k, v in (parameters or {}).items()},
    )
    try:
        yield invocation
    except Exception as exc:
        invocation.finish(status="error")
        invocation.error = f"{type(exc).__name__}: {exc}"
        metrics.record(invocation)
        raise
    else:
        invocation.finish(status="success")
        metrics.record(invocation)


def traced_tool(func):
    """Decorator for MCP tool functions with automatic tracing."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        import uuid
        invocation = ToolInvocation(
            tool_name=func.__name__,
            request_id=str(uuid.uuid4())[:8],
            parameters={k: _safe_repr(v) for k, v in kwargs.items()},
        )
        logger.info(
            "tool.start",
            extra={"invocation": invocation.to_log_dict()}
        )
        try:
            result = await func(*args, **kwargs)
            invocation.finish(
                status="success",
                result_size=len(str(result)) if result else 0,
            )
            logger.info(
                "tool.success",
                extra={"invocation": invocation.to_log_dict()}
            )
            metrics.record(invocation)
            return result
        except Exception as e:
            invocation.finish(status="error")
            invocation.error = f"{type(e).__name__}: {e}"
            logger.error(
                "tool.error",
                extra={"invocation": invocation.to_log_dict()},
                exc_info=True,
            )
            metrics.record(invocation)
            raise
    return wrapper


def _safe_repr(v: Any, max_len: int = 200) -> str:
    """Truncate large values for logging."""
    s = repr(v)
    return s[:max_len] + "..." if len(s) > max_len else s
