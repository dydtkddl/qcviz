"""Boundary-safe Korean molecule alias translation helpers."""

from __future__ import annotations

import re
from typing import Optional

from qcviz_mcp.llm.normalizer import KO_TO_EN

_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")
_UNICODE_DASH_RE = re.compile(r"[‐‑‒–—−]")


def _normalize_formula_text(text: str) -> str:
    result = str(text or "").translate(_SUBSCRIPT_MAP)
    result = _UNICODE_DASH_RE.sub("-", result)
    result = re.sub(r"\s*/+\s*$", "", result).strip()
    return result


def _alias_pattern(ko_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![가-힣A-Za-z0-9])({re.escape(ko_name)})"
        r"(?:은|는|이|가|을|를|의|에|에서|로|으로|부터|에\s*대해|에\s*대한|도|만|까지)?"
        r"(?![가-힣A-Za-z0-9])"
    )


def translate(text: str) -> str:
    """Translate Korean molecule aliases only when they appear as standalone names."""
    if not text or not text.strip():
        return text

    result = _normalize_formula_text(text.strip())
    for ko_name, en_name in sorted(KO_TO_EN.items(), key=lambda item: len(item[0]), reverse=True):
        result = _alias_pattern(ko_name).sub(en_name, result)
    return result.strip()


def find_molecule_name(text: str) -> Optional[str]:
    """Return the English alias for a standalone Korean molecule mention."""
    if not text or not text.strip():
        return None

    cleaned = _normalize_formula_text(text.strip())
    for ko_name, en_name in sorted(KO_TO_EN.items(), key=lambda item: len(item[0]), reverse=True):
        if _alias_pattern(ko_name).search(cleaned):
            return en_name
    return None
