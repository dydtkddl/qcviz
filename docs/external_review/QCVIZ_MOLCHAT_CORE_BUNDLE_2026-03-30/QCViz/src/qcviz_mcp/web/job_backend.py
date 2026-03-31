"""Job backend selection and runtime metadata for web/worker split migration."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class JobBackendRuntime:
    name: str
    mode: str
    external_queue: bool = False
    split_ready: bool = False
    worker_count: Optional[int] = None
    queue_driver: Optional[str] = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        return data


def configured_job_backend() -> str:
    return str(os.getenv("QCVIZ_JOB_BACKEND", "inmemory") or "inmemory").strip().lower()


def _inmemory_runtime(max_workers: int) -> JobBackendRuntime:
    return JobBackendRuntime(
        name="inmemory-threadpool",
        mode="single-process",
        external_queue=False,
        split_ready=False,
        worker_count=max(1, int(max_workers or 1)),
        queue_driver="threadpool",
        notes=(
            "Suitable for local and single-node deployments.",
            "Web and compute share the same process family.",
            "For multi-user production, migrate to Redis/arq worker topology.",
        ),
    )


def build_job_manager(
    *,
    max_workers: int,
    inmemory_factory: Callable[[int], Any],
) -> Any:
    backend = configured_job_backend()
    if backend in {"inmemory", "threadpool", "local"}:
        manager = inmemory_factory(max_workers)
        setattr(manager, "backend_runtime", _inmemory_runtime(max_workers))
        return manager

    if backend in {"arq", "redis", "external"}:
        try:
            from qcviz_mcp.web.arq_backend import ArqJobManager
            return ArqJobManager(max_workers=max_workers)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "QCVIZ_JOB_BACKEND is set to an external queue backend, but required packages are missing. "
                "Install worker extras (`pip install '.[worker]'`) and provide a running Redis server."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize Redis/arq job backend: {exc}"
            ) from exc

    raise RuntimeError(f"Unsupported QCVIZ_JOB_BACKEND: {backend}")


def get_job_backend_runtime(manager: Any, *, fallback_max_workers: int = 1) -> Dict[str, Any]:
    runtime = getattr(manager, "backend_runtime", None)
    if isinstance(runtime, JobBackendRuntime):
        return runtime.to_dict()
    return _inmemory_runtime(fallback_max_workers).to_dict()
