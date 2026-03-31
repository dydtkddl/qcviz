from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from qcviz_mcp import __version__ as PACKAGE_VERSION

_PROCESS_STARTED_AT = time.time()
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_TRACKED_RELATIVE_PATHS = [
    "llm/agent.py",
    "llm/normalizer.py",
    "services/molchat_client.py",
    "services/structure_resolver.py",
    "web/app.py",
    "web/routes/chat.py",
    "web/routes/compute.py",
]


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _collect_snapshot() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rel_path in _TRACKED_RELATIVE_PATHS:
        path = _PACKAGE_ROOT / rel_path
        if not path.exists():
            rows.append(
                {
                    "path": rel_path,
                    "exists": False,
                    "size": 0,
                    "mtime": None,
                    "mtime_iso": None,
                }
            )
            continue
        stat = path.stat()
        rows.append(
            {
                "path": rel_path,
                "exists": True,
                "size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
                "mtime_iso": _utc_iso(float(stat.st_mtime)),
            }
        )
    return rows


def _fingerprint(snapshot: List[Dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    for row in snapshot:
        digest.update(
            (
                f"{row.get('path')}|{row.get('exists')}|{row.get('size')}|"
                f"{row.get('mtime') or ''}"
            ).encode("utf-8", "ignore")
        )
    return digest.hexdigest()[:16]


_BOOT_SNAPSHOT = _collect_snapshot()
_BOOT_FINGERPRINT = _fingerprint(_BOOT_SNAPSHOT)


def runtime_debug_info() -> Dict[str, Any]:
    current_snapshot = _collect_snapshot()
    current_fingerprint = _fingerprint(current_snapshot)
    return {
        "package_version": PACKAGE_VERSION,
        "process_started_at": _PROCESS_STARTED_AT,
        "process_started_at_iso": _utc_iso(_PROCESS_STARTED_AT),
        "boot_fingerprint": _BOOT_FINGERPRINT,
        "current_disk_fingerprint": current_fingerprint,
        "boot_matches_current_disk": _BOOT_FINGERPRINT == current_fingerprint,
        "tracked_modules": current_snapshot,
    }


def runtime_fingerprint() -> str:
    return _BOOT_FINGERPRINT
