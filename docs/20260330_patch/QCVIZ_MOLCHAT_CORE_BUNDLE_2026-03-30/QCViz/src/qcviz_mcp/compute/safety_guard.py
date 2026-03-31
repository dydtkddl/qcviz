"""Safety guard for local quantum chemistry jobs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


MAX_ATOMS_DEFAULT = 200
TIMEOUT_MINUTES_DEFAULT = 30
MEMORY_FRACTION_LIMIT_DEFAULT = 0.80


@dataclass
class SafetyDecision:
    """Safety evaluation result."""

    allowed: bool
    atom_count: Optional[int]
    estimated_memory_mb: Optional[float]
    total_memory_mb: Optional[float]
    max_workers: int
    warnings: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert decision to dict."""
        return {
            "allowed": self.allowed,
            "atom_count": self.atom_count,
            "estimated_memory_mb": self.estimated_memory_mb,
            "total_memory_mb": self.total_memory_mb,
            "max_workers": self.max_workers,
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
        }


def _is_xyz_text(text: str) -> bool:
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    if not lines[0].isdigit():
        return False
    atom_count = int(lines[0])
    return len(lines) >= atom_count + 2


def _is_atom_spec_line(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*[A-Z][a-z]?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$",
            line or "",
        )
    )


def estimate_atom_count(query: str) -> Optional[int]:
    """Estimate atom count from XYZ or atom-spec text.

    Args:
        query: User input.

    Returns:
        Atom count if determinable, else None.
    """
    text = (query or "").strip()
    if not text:
        return None

    if _is_xyz_text(text):
        first = text.splitlines()[0].strip()
        return int(first)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and all(_is_atom_spec_line(line) for line in lines):
        return len(lines)

    return None


def _basis_factor(basis: str) -> float:
    """Very rough memory multiplier by basis family."""
    name = (basis or "").lower()

    if "sto-3g" in name:
        return 1.0
    if "3-21g" in name:
        return 1.4
    if "6-31g" in name:
        return 1.8
    if "svp" in name:
        return 2.4
    if "tzvp" in name:
        return 4.0
    if "qzvp" in name:
        return 7.0
    if "cc-pvdz" in name:
        return 2.8
    if "cc-pvtz" in name:
        return 5.0
    if "def2-svp" in name:
        return 2.5
    if "def2-tzvp" in name:
        return 4.2
    if "def2-qzvp" in name:
        return 7.2

    return 3.0


def estimate_memory_mb(atom_count: Optional[int], basis: str) -> Optional[float]:
    """Estimate memory usage in MB.

    This is intentionally conservative and heuristic.

    Args:
        atom_count: Number of atoms if known.
        basis: Basis set name.

    Returns:
        Estimated memory in MB, or None.
    """
    if atom_count is None:
        return None

    factor = _basis_factor(basis)
    estimate = 256.0 + (float(atom_count) ** 2) * factor * 0.35
    return round(estimate, 1)


def get_total_memory_mb() -> Optional[float]:
    """Get total physical memory in MB if detectable."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        total = float(page_size) * float(phys_pages) / (1024.0 * 1024.0)
        return round(total, 1)
    except Exception:
        return None


def recommended_max_workers(cpu_fraction: float = 0.5) -> int:
    """Recommend max worker count for local machine."""
    cpu_count = os.cpu_count() or 1
    workers = int(max(1, round(float(cpu_count) * float(cpu_fraction))))
    return max(1, workers)


def evaluate_request(
    query: str,
    basis: str = "def2-SVP",
    requested_timeout_minutes: int = TIMEOUT_MINUTES_DEFAULT,
    max_atoms: int = MAX_ATOMS_DEFAULT,
    memory_fraction_limit: float = MEMORY_FRACTION_LIMIT_DEFAULT,
) -> SafetyDecision:
    """Evaluate whether a local job should be allowed.

    Args:
        query: User molecular input.
        basis: Basis set name.
        requested_timeout_minutes: Requested timeout.
        max_atoms: Hard atom-count limit.
        memory_fraction_limit: Fraction of RAM allowed for estimated job size.

    Returns:
        SafetyDecision object.
    """
    warnings = []
    reasons = []

    atom_count = estimate_atom_count(query)
    estimated_mb = estimate_memory_mb(atom_count, basis)
    total_mb = get_total_memory_mb()
    max_workers = recommended_max_workers()

    allowed = True

    if atom_count is not None and atom_count > max_atoms:
        allowed = False
        reasons.append(
            "원자 수 %d개가 허용 한도 %d개를 초과합니다." % (atom_count, max_atoms)
        )

    if (
        estimated_mb is not None
        and total_mb is not None
        and estimated_mb > total_mb * float(memory_fraction_limit)
    ):
        allowed = False
        reasons.append(
            "예상 메모리 사용량 %.1f MB가 총 메모리 %.1f MB의 %.0f%%를 초과합니다."
            % (estimated_mb, total_mb, float(memory_fraction_limit) * 100.0)
        )

    if atom_count is None:
        warnings.append("입력만으로 원자 수를 추정하지 못했습니다. 계산 전 추가 검증이 필요합니다.")

    if requested_timeout_minutes > TIMEOUT_MINUTES_DEFAULT:
        warnings.append(
            "요청된 타임아웃 %d분은 기본 권장값 %d분보다 큽니다."
            % (requested_timeout_minutes, TIMEOUT_MINUTES_DEFAULT)
        )

    return SafetyDecision(
        allowed=allowed,
        atom_count=atom_count,
        estimated_memory_mb=estimated_mb,
        total_memory_mb=total_mb,
        max_workers=max_workers,
        warnings=warnings,
        reasons=reasons,
    )


def raise_if_unsafe(decision: SafetyDecision) -> None:
    """Raise ValueError if a request is unsafe."""
    if not decision.allowed:
        raise ValueError("; ".join(decision.reasons))