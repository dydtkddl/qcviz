from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from qcviz_mcp.observability import metrics


class LaneLockViolation(RuntimeError):
    pass


@dataclass
class LaneLock:
    _lane: Optional[str] = None
    _locked: bool = False

    def set(self, lane: Optional[str]) -> None:
        normalized = str(lane or "").strip()
        if not normalized:
            metrics.increment("pipeline.lane_lock_violation_rate")
            raise LaneLockViolation("cannot lock empty lane")
        if self._locked and self._lane != normalized:
            metrics.increment("pipeline.lane_lock_violation_rate")
            raise LaneLockViolation(f"attempted to change lane from {self._lane} to {normalized}")
        self._lane = normalized
        self._locked = True

    @property
    def lane(self) -> Optional[str]:
        return self._lane

    @property
    def locked(self) -> bool:
        return self._locked

    def allows_compute(self) -> bool:
        return self._lane == "compute_ready"

    def allows_grounding(self) -> bool:
        return self._lane in {"grounding_required", "compute_ready"}

    def snapshot(self) -> dict:
        return {
            "lane": self._lane,
            "locked": self._locked,
        }

    @classmethod
    def from_lane(cls, lane: Optional[str]) -> "LaneLock":
        lock = cls()
        if lane:
            lock.set(lane)
        return lock
