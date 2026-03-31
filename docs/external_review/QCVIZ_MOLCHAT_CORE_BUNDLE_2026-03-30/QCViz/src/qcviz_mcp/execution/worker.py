"""Compatibility worker module.

Some older parts of QCViz import:
    from qcviz_mcp.execution.worker import _executor

This shim provides an in-process ThreadPoolExecutor so legacy imports
keep working even if the old execution package is absent.
"""

from __future__ import annotations

import atexit
import os
from concurrent.futures import ThreadPoolExecutor

_MAX_WORKERS = max(4, min(32, (os.cpu_count() or 4) * 2))

_executor = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="qcviz-exec",
)


@atexit.register
def _shutdown_executor() -> None:
    try:
        _executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
