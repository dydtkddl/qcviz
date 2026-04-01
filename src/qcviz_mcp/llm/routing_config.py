from __future__ import annotations

import os
from typing import Iterable


def _env_float_any(
    names: Iterable[str],
    default: float,
    *,
    min_value: float = 0.0,
    max_value: float = 1.0,
) -> float:
    value = default
    for name in names:
        raw = os.getenv(name)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
            break
        except Exception:
            continue
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


PLAN_CONFIDENCE_THRESHOLD = _env_float_any(["QCVIZ_CONFIDENCE_THRESHOLD"], 0.75)
GROUNDING_AUTO_ACCEPT_THRESHOLD = _env_float_any(["QCVIZ_GROUNDING_AUTO_ACCEPT_THRESHOLD"], 0.85)
TYPO_AUTO_PROMOTE_THRESHOLD = _env_float_any(["QCVIZ_TYPO_AUTO_PROMOTE_THRESHOLD"], 0.85)
