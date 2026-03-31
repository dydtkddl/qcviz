"""QCViz-MCP 보안 유틸리티 모듈."""

import os
import re
import time
from pathlib import Path
from dataclasses import dataclass

# 프로젝트 루트 설정
_PROJECT_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

def validate_path(path: str, mode: str = "r") -> Path:
    """경로 탐색 공격 방지를 위한 경로 검증."""
    if ":" in path:
        raise ValueError(f"보안: 잘못된 경로 형식입니다: {path}")
    real_path = os.path.realpath(path)
    if not real_path.startswith(_PROJECT_ROOT):
        # 만약 output 폴더면 허용
        if "output" in real_path:
            return Path(real_path)
        raise ValueError(f"보안: 허용되지 않은 경로입니다: {path}")
    return Path(real_path)

def validate_atom_spec(atom_spec: str, max_atoms: int = 200) -> str:
    """원자 지정 문자열 검증."""
    # 간단한 원자 수 체크
    lines = atom_spec.strip().splitlines()
    if not lines:
        return atom_spec
        
    # XYZ 포맷 체크
    try:
        n = int(lines[0].strip())
        is_xyz = True
    except (ValueError, IndexError):
        is_xyz = False
        
    if is_xyz:
        if n > max_atoms:
            raise ValueError(f"원자 수 초과 (최대 {max_atoms})")
    else:
        # PySCF 포맷 체크 (세미콜론 구분)
        n = len([l for l in atom_spec.split(";") if l.strip()])
        if n > max_atoms:
            raise ValueError(f"원자 수 초과 (최대 {max_atoms})")
    return atom_spec

# 기존 검증에 추가
FORBIDDEN_BASIS_PATTERNS = re.compile(r"[;&|`$(){}]")  # shell injection 차단

def validate_basis(basis: str) -> str:
    """기저 함수 이름 검증. Shell injection 등 방지."""
    if len(basis) > 50:
        raise ValueError(f"Basis name too long: {len(basis)} chars (max 50)")
    if FORBIDDEN_BASIS_PATTERNS.search(basis):
        raise ValueError(f"Invalid characters in basis name: {basis!r}")
    return basis

def validate_atom_spec_strict(atom_spec: str, max_atoms: int = 50, 
                                max_length: int = 10_000) -> str:
    """원자 지정 문자열 엄격 검증."""
    if len(atom_spec) > max_length:
        raise ValueError(f"atom_spec too long: {len(atom_spec)} chars (max {max_length})")
    # 줄 수 = 원자 수 근사
    lines = [l.strip() for l in atom_spec.strip().splitlines() if l.strip()]
    if len(lines) > max_atoms:
        raise ValueError(f"원자 수 초과: {len(lines)} (max {max_atoms})")
    return atom_spec

def validate_output_dir(path: Path, allowed_root: Path) -> Path:
    """출력 디렉토리가 허용 범위 내인지 확인. Symlink 해소 후 검증."""
    resolved = path.resolve()
    allowed = allowed_root.resolve()
    if not str(resolved).startswith(str(allowed)):
        raise ValueError(f"Path traversal detected: {path} resolves to {resolved}")
    return resolved


@dataclass
class TokenBucket:
    capacity: int          # 최대 토큰 수
    refill_rate: float     # 초당 토큰 리필 속도
    tokens: float = 0.0
    last_refill: float = 0.0
    
    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()
    
    def consume(self, n: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

# 도구별 비용 가중치 (SCF 계산은 비쌈)
TOOL_COSTS = {
    "compute_ibo": 10,        # 무거운 계산
    "analyze_bonding": 8,
    "compute_partial_charges": 5,
    "visualize_orbital": 2,   # 렌더링만
    "parse_output": 1,        # 파일 읽기만
    "convert_format": 1,
}

# 기본 버킷: 분당 60 토큰, 최대 100 토큰
default_bucket = TokenBucket(capacity=100, refill_rate=1.0)
