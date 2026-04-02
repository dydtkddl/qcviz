# QCViz-MCP v3 — MCP-Unified AI Agent Architecture Analysis

> **작업 지시 프롬프트 (Task Instruction Prompt)**
>
> 아래에 QCViz-MCP v3 프로젝트의 **핵심 소스 코드**가 포함되어 있습니다.
> 이 코드를 완전히 이해한 후, 아래 요청사항에 대해 **구체적이고 실행 가능한 분석**을 제공해주세요.

---

## 📋 프로젝트 개요

**QCViz-MCP**는 PySCF 기반 양자화학 계산을 웹 브라우저에서 수행하고 시각화하는 풀스택 애플리케이션입니다.

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla JS, 3Dmol.js, WebSocket |
| **Backend** | FastAPI, Uvicorn, WebSocket |
| **Computation** | PySCF (DFT/HF), NumPy, SciPy |
| **AI Planning** | Gemini API (google-genai) |
| **MCP Server** | FastMCP (`@mcp.tool()` decorator) |
| **Structure Resolution** | PubChem REST, MolChat API |

---

## 🔴 현재 아키텍처의 문제점: 이중 경로 (Dual Path)

```
경로 1 — MCP 클라이언트 (Claude Desktop, Gemini CLI):
  Client → MCP Protocol → @mcp.tool() (core.py) → PySCF

경로 2 — 웹 UI (브라우저):
  Browser → WebSocket → Gemini API (플래너만) → 하드코딩 직접호출 (compute.py) → PySCF
```

문제점:
1. MCP 도구(`core.py`)와 웹 직접호출(`compute.py`→`pyscf_runner.py`)이 같은 기능을 다르게 구현
2. Gemini는 JSON 플래너일 뿐 — 도구를 직접 호출하지 않음
3. PubChem 실패 시 자동 재시도 없음 — Gemini가 실패를 모름
4. "구조해석→SCF→시각화" 같은 multi-step 도구 체이닝 불가
5. intent→함수 하드코딩 매핑 — 새 도구 추가 시 양쪽 다 수정 필요

---

## 🟢 목표: MCP-Unified AI Agent Architecture

```
통합 후:
  모든 클라이언트 → Gemini Function Calling → MCP @mcp.tool() → PySCF

웹 UI 플로우:
  Browser → WebSocket(chat.py) → Gemini(function calling) → MCP tool in-process
      ↑                                    │
      └── 실시간 스트리밍 ◀── Gemini 결과 해석 + 추가 도구 호출 결정
```

핵심 변경:
1. Gemini에 MCP 도구 스키마를 function declaration으로 전달
2. tool_call 반환 → MCP 도구 in-process 실행 → 결과 Gemini에 반환
3. compute.py 직접호출 경로 제거, chat.py 단순화
4. agent.py: plan() → execute() (function calling loop)

---

## 📝 분석 요청사항

### 1. 아키텍처 분석
- 이중 경로 문제의 파일/함수 단위 식별
- MCP 도구 vs 웹 직접호출 기능 중복 목록
- 통합 시 제거 가능한 코드량, 살릴 유틸 함수 분류

### 2. 분자 구조 해석 개선
- PubChem/MolChat 실패 에러 전파 경로
- MCP 통합 시 Gemini 자동 재시도 시나리오
- `structure_resolver.py` vs `MoleculeResolver`(core.py) — 어떤 것을 유지?

### 3. 도구 체이닝 가능성
- multi-step 워크플로우 (resolve → SCF → orbital → ESP)
- Gemini function calling multi-turn에서 구현 방법
- Frontend 실시간 스트리밍 방법

### 4. 에러 핸들링 & 복원력
- 에러 핸들링 부실한 코드 위치
- Gemini 자율 복구 시나리오
- 타임아웃/메모리 초과 graceful degradation

### 5. 비용 & 레이턴시
- 도구 스키마 포함 토큰 비용 추정
- 캐싱 전략, 컨텍스트 윈도우 관리

### 6. 보안
- security.py 검증 유지 여부
- Gemini 임의 파라미터 추가 검증 필요성

### 7. Frontend 영향도
- chat.js 변경, progress 스트리밍 방법

### 8. 내가 놓치고 있는 관점
- 미처 생각하지 못한 이점, 새로운 가능성
- 업계 트렌드 관점, 잠재적 리스크
- 점진적 마이그레이션 전략

---

## 📦 기대 결과물

1. 현재 상태 진단서 — 이중 경로 코드 위치 + 영향
2. MCP 통합 설계 — 파일/함수 단위 변경 계획
3. 마이그레이션 로드맵 — Phase 1~3
4. 리스크 & 완화 전략
5. 숨겨진 기회 보고서

---

## 📂 핵심 소스 코드


---

## 📄 `pyproject.toml` (59 lines)

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "qcviz-mcp"
version = "0.2.0"
description = "Quantum Chemistry Visualization MCP server with FastAPI, PySCF, 3Dmol.js, WebSocket, and LLM planning"
readme = "README.md"
requires-python = ">=3.10"
authors = [
  { name = "QCViz Team" }
]
dependencies = [
  "fastapi>=0.110,<1.0",
  "uvicorn[standard]>=0.29,<1.0",
  "jinja2>=3.1,<4.0",
  "pydantic>=2.6,<3.0",
  "numpy>=1.26",
  "scipy>=1.11",
  "pyscf>=2.4,<3.0",
  "python-dotenv>=1.0,<2.0",
  "httpx>=0.27,<1.0",
  "orjson>=3.10,<4.0",
]

[project.optional-dependencies]
llm-openai = [
  "openai>=1.30,<2.0",
]
llm-gemini = [
  "google-genai>=0.7,<2.0",
]
dev = [
  "pytest>=8.0,<9.0",
  "pytest-asyncio>=0.23,<1.0",
  "pytest-cov>=5.0,<6.0",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "slow: PySCF 실제 계산 포함 (느림)",
    "integration: 통합 테스트",
    "e2e: End-to-End 테스트",
]
timeout = 60

[tool.coverage.run]
source = ["src/qcviz_mcp"]
branch = true
```

---

## 📄 `config.py` (105 lines)

```python
from dataclasses import dataclass, field
from pathlib import Path
import os

# Auto-load .env from project root (version03/.env)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"  # src/qcviz_mcp/config.py → version03/.env
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

@dataclass(frozen=True)
class ServerConfig:
    """서버 설정. 환경 변수 또는 기본값에서 로드. 불변."""
    
    # 서버
    host: str = "127.0.0.1"
    port: int = 8765
    transport: str = "sse"  # "sse" | "stdio"
    
    # 계산
    max_atoms: int = 50
    max_workers: int = 2
    computation_timeout_seconds: float = 300.0
    default_basis: str = "sto-3g"
    default_cube_resolution: int = 80
    
    # 캐시
    cache_max_size: int = 50
    cache_ttl_seconds: float = 3600.0
    
    # 보안
    rate_limit_capacity: int = 100
    rate_limit_refill_rate: float = 1.0
    allowed_output_root: Path = field(default_factory=lambda: Path.cwd() / "output")
    
    # 관측가능성
    log_level: str = "INFO"
    log_json: bool = False
    
    # 렌더러
    preferred_renderer: str = "auto"  # "auto" | "pyvista" | "playwright" | "py3dmol"
    
    # FIX(M1): Gemini API 설정
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout: float = 10.0
    gemini_temperature: float = 0.1
    
    # FIX(M1): MolChat API 설정
    molchat_base_url: str = "http://psid.aizen.co.kr/molchat"
    molchat_timeout: float = 15.0
    
    # FIX(M1): PubChem 폴백 설정
    pubchem_timeout: float = 10.0
    pubchem_fallback: bool = True
    
    # FIX(M1): 구조 캐시 설정
    scf_cache_max_size: int = 256
    
    # FIX(M1): 이온쌍 오프셋
    ion_offset_angstrom: float = 5.0
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        """환경 변수에서 설정 로드. QCVIZ_ 접두사 + 일부 키는 접두사 없이도 지원."""
        kwargs = {}
        
        # FIX(M1): 접두사 없는 환경변수도 지원하는 키 목록
        alt_env_keys = {
            "gemini_api_key": "GEMINI_API_KEY",
            "gemini_model": "GEMINI_MODEL",
            "gemini_timeout": "GEMINI_TIMEOUT",
            "gemini_temperature": "GEMINI_TEMPERATURE",
            "molchat_base_url": "MOLCHAT_BASE_URL",
            "molchat_timeout": "MOLCHAT_TIMEOUT",
            "pubchem_timeout": "PUBCHEM_TIMEOUT",
            "scf_cache_max_size": "SCF_CACHE_MAX_SIZE",
            "ion_offset_angstrom": "ION_OFFSET_ANGSTROM",
        }
        
        for f in cls.__dataclass_fields__:
            env_key = f"QCVIZ_{f.upper()}"
            env_val = os.environ.get(env_key)
            
            # FIX(M1): 접두사 없는 키도 폴백 확인
            if env_val is None and f in alt_env_keys:
                env_val = os.environ.get(alt_env_keys[f])
            
            if env_val is not None:
                field_type = cls.__dataclass_fields__[f].type
                if field_type in ("int", int):
                    kwargs[f] = int(env_val)
                elif field_type in ("float", float):
                    kwargs[f] = float(env_val)
                elif field_type in ("bool", bool):
                    kwargs[f] = env_val.lower() in ("true", "1", "yes")
                elif "Path" in str(field_type):
                    kwargs[f] = Path(env_val)
                else:
                    kwargs[f] = env_val
        return cls(**kwargs)

```

---

## 📄 `mcp_server.py` (25 lines)

```python
"""FastMCP 서버 엔트리포인트 (스텁).
Phase 2와 Phase 3 사이에서 유닛 테스트와 통합 테스트를 원활하게 진행하기 위해 뼈대만 작성합니다.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 초기화
mcp = FastMCP("QCViz-MCP")

# Tools 등록
import qcviz_mcp.tools.core  # noqa: F401
import qcviz_mcp.tools.advisor_tools  # noqa: F401  — v5.0 advisor

if __name__ == "__main__":
    logger.info("QCViz-MCP 서버 시작 중...")
    mcp.run()

```

---

## 📄 `tools/core.py` (502 lines)

```python
"""QCViz-MCP tool implementation v3.0.0 (Enterprise - Sync Compatible)."""

from __future__ import annotations

import json
import logging
import pathlib
import traceback
import os
import asyncio
import concurrent.futures
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np

from qcviz_mcp.backends.pyscf_backend import PySCFBackend, ESPResult, _cli
from qcviz_mcp.backends.viz_backend import (
    Py3DmolBackend,
    DashboardPayload,
    CubeNormalizer,
)

from qcviz_mcp.backends.registry import registry
from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.security import (
    validate_atom_spec_strict, validate_path, validate_basis,
    default_bucket, validate_atom_spec as _validate_atom_spec,
    validate_path as _validate_file_path, _PROJECT_ROOT
)
from qcviz_mcp.observability import traced_tool, metrics, ToolInvocation
try:
    from qcviz_mcp.execution.worker import _executor
except Exception:
    import atexit
    import os
    from concurrent.futures import ThreadPoolExecutor

    _executor = ThreadPoolExecutor(
        max_workers=max(4, min(32, (os.cpu_count() or 4) * 2)),
        thread_name_prefix="qcviz-core-fallback",
    )

    @atexit.register
    def _shutdown_core_executor():
        try:
            _executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
from qcviz_mcp.execution.cache import cache

logger = logging.getLogger(__name__)
HARTREE_TO_EV = 27.2114
OUTPUT_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
_pyscf = PySCFBackend()
_viz = Py3DmolBackend()

class _NumpyEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)

def _parse_atom_spec(atom_spec):
    lines = atom_spec.strip().splitlines()
    if len(lines) <= 2:
        return atom_spec
    if lines[0].strip().isdigit():
        return "\n".join(lines[2:])
    return atom_spec

def _extract_name(molecule_str, mol_obj):
    lines = molecule_str.strip().splitlines()
    if len(lines) > 1:
        name = lines[1].strip()
        if name and not name[0].isdigit() and len(name) < 100:
            return name.replace("\n", " ").replace("\r", " ")
    syms = [mol_obj.atom_symbol(i) for i in range(mol_obj.natm)]
    counts = Counter(syms)
    return "".join(
        "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
        for e in sorted(counts.keys())
    )

def _sanitize_display_name(name: Optional[str], fallback: str = "molecule") -> str:
    if not name:
        return fallback
    cleaned = str(name).strip().replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100] if cleaned else fallback

def _safe_filename(name: str, fallback: str = "molecule") -> str:
    cleaned = _sanitize_display_name(name, fallback=fallback)
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or fallback

class MoleculeResolver:
    """Resolve user query (XYZ / atom-spec / molecule name / SMILES) into XYZ text.

    Resolution order:
    1. If already XYZ text -> return as-is
    2. If already atom-spec text -> return as-is
    3. If looks like SMILES -> call Molchat directly
    4. Otherwise try PubChem name -> CanonicalSMILES -> Molchat
    """

    PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    MOLCHAT_BASE = "http://psid.aizen.co.kr/molchat/api/v1"
    DEFAULT_TIMEOUT = 30

    _ATOM_LINE_RE = re.compile(
        r"^\s*[A-Z][a-z]?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$"
    )
    _SMILES_LIKE_RE = re.compile(r"^[A-Za-z0-9@\+\-\[\]\(\)=#$\\/%.]+$")
    _SIMPLE_SMILES_TOKEN_RE = re.compile(
        r"^(?:Cl|Br|Si|Li|Na|Ca|Al|Mg|Zn|Fe|Cu|Mn|Hg|Ag|Pt|Au|Sn|Pb|Se|"
        r"[BCNOFPSIKH]|[bcnops])+$"
    )

    @classmethod
    def resolve(cls, query: str) -> str:
        if query is None:
            raise ValueError("입력 query가 비어 있습니다.")
        text = str(query).strip()
        if not text:
            raise ValueError("입력 query가 비어 있습니다.")

        if cls._is_xyz_text(text):
            return text

        if cls._is_atom_spec_text(text):
            return text

        if cls._looks_like_smiles(text):
            logger.info("MoleculeResolver: input recognized as SMILES-like string.")
            smiles = text
        else:
            logger.info("MoleculeResolver: resolving molecule name via PubChem: %s", text)
            smiles = cls._resolve_name_to_smiles(text)

        xyz = cls._generate_xyz_via_molchat(smiles)
        if not cls._is_xyz_text(xyz):
            raise ValueError("Molchat가 유효한 XYZ 구조를 반환하지 않았습니다.")
        return xyz

    @classmethod
    def _is_xyz_text(cls, text: str) -> bool:
        lines = [line.strip() for line in text.strip().splitlines()]
        if len(lines) < 3:
            return False
        if not lines[0].isdigit():
            return False

        atom_count = int(lines[0])
        if atom_count <= 0:
            return False

        # Some generators might omit the comment line or leave it empty
        # If line 1 is empty, it's just an empty comment
        atom_lines = lines[2:2 + atom_count]
        if len(atom_lines) < atom_count:
            # Maybe there was no comment line at all? Let's check if line 1 looks like an atom
            parts = lines[1].split()
            if len(parts) >= 4 and parts[0].isalpha():
                atom_lines = lines[1:1 + atom_count]
            else:
                return False

        if len(atom_lines) < atom_count:
            return False

        matched = 0
        for line in atom_lines:
            parts = line.split()
            if len(parts) < 4:
                return False
            try:
                float(parts[1])
                float(parts[2])
                float(parts[3])
            except Exception:
                return False
            matched += 1
        return matched == atom_count

    @classmethod
    def _is_atom_spec_text(cls, text: str) -> bool:
        lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return False
        if len(lines) == 1:
            return False
        return all(cls._ATOM_LINE_RE.match(line) for line in lines)

    @classmethod
    def _looks_like_smiles(cls, text: str) -> bool:
        if "\n" in text:
            return False

        s = text.strip()
        if not s or " " in s:
            return False

        if not cls._SMILES_LIKE_RE.match(s):
            return False

        # Strong SMILES markers
        if any(ch in s for ch in "[]=#()/\\@+$%"):
            return True
        if any(ch.isdigit() for ch in s):
            return True

        # Simple elemental-token-only linear smiles like CCO, CCN, O, N, ClCCl
        if cls._SIMPLE_SMILES_TOKEN_RE.fullmatch(s):
            return True

        return False

    @classmethod
    def _http_get_json(cls, url: str, timeout: int = None) -> Dict[str, Any]:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _http_post_json(
        cls,
        url: str,
        body: Dict[str, Any],
        timeout: int = None,
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _resolve_name_to_smiles(cls, name: str) -> str:
        import re
        clean_name = re.sub(r"(?i)\b(?:the|of|orbital|homo|lumo|mo|esp|map|charge|charges|mulliken|partial)\b", "", name).strip()
        quoted = urllib.parse.quote(clean_name, safe="")
        direct_url = (
            f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/property/CanonicalSMILES,IsomericSMILES/JSON"
        )

        try:
            data = cls._http_get_json(direct_url, timeout=20)
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                smiles = (p.get("CanonicalSMILES") or p.get("IsomericSMILES")
                          or p.get("SMILES") or p.get("ConnectivitySMILES"))
                if smiles:
                    return smiles
                # If PubChem returned properties but no SMILES, fall through to CID lookup
        except urllib.error.HTTPError as e:
            logger.warning("PubChem direct name->SMILES failed for %s: %s", name, e)
        except Exception as e:
            logger.warning("PubChem direct name->SMILES error for %s: %s", name, e)
        cid_url = f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/cids/JSON"
        try:
            data = cls._http_get_json(cid_url, timeout=20)
            cids = data.get("IdentifierList", {}).get("CID", [])
            if not cids:
                raise ValueError(f"PubChem에서 '{name}'에 대한 CID를 찾지 못했습니다.")
            cid = cids[0]
            prop_url = f"{cls.PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES/JSON"
            prop_data = cls._http_get_json(prop_url, timeout=20)
            props = prop_data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                return p.get("CanonicalSMILES") or p.get("IsomericSMILES") or p.get("SMILES") or p.get("ConnectivitySMILES")
        except Exception as e:
            raise ValueError(
                f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다: {e}"
            ) from e

        raise ValueError(f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다.")

    @classmethod
    def _generate_xyz_via_molchat(cls, smiles: str) -> str:
        url = f"{cls.MOLCHAT_BASE}/molecules/generate-3d"
        body = {
            "smiles": smiles,
            "format": "xyz",
            "optimize_xtb": True,
        }
        try:
            data = cls._http_post_json(url, body=body, timeout=60)
        except urllib.error.HTTPError as e:
            try:
                details = e.read().decode("utf-8", errors="replace")
            except Exception:
                details = str(e)
            raise ValueError(f"Molchat API 호출 실패: HTTP {e.code} - {details}") from e
        except Exception as e:
            raise ValueError(f"Molchat API 호출 실패: {e}") from e

        xyz = data.get("structure_data")
        if not xyz or not str(xyz).strip():
            raise ValueError("Molchat API 응답에 structure_data(XYZ)가 없습니다.")
        return str(xyz).strip()

    @classmethod
    def resolve_with_friendly_errors(cls, query: str) -> str:
        try:
            return cls.resolve(query)
        except Exception as e:
            raise ValueError(
                "분자 구조를 확보하지 못했습니다. "
                "XYZ 좌표를 직접 제공하거나, 인식 가능한 분자명/SMILES를 입력해 주세요. "
                f"원인: {e}"
            ) from e

def _resolve_query_input(query: str) -> Tuple[str, str, Optional[str]]:
    resolved_structure = MoleculeResolver.resolve_with_friendly_errors(query)
    validate_atom_spec_strict(resolved_structure)
    atom_data = _parse_atom_spec(resolved_structure)

    raw_query = str(query).strip() if query is not None else ""
    if MoleculeResolver._is_xyz_text(raw_query) or MoleculeResolver._is_atom_spec_text(raw_query):
        display_name_hint = None
    else:
        display_name_hint = _sanitize_display_name(raw_query)

    return resolved_structure, atom_data, display_name_hint

# --- Top-level implementation functions for Executor (Pickle-safe) ---

def _sync_compute_ibo_impl(
    atom_spec,
    basis,
    method,
    charge,
    spin,
    n_orbitals,
    include_esp,
    xyz_string_raw,
    display_name_hint=None,
):
    """
    Hybrid Orbital Rendering Architecture:
    - Occupied orbitals (idx <= HOMO): IBO coefficients for intuitive bond visualization
    - Virtual orbitals  (idx >  HOMO): Canonical MO coefficients from SCF result
    """
    scf_res, mol = _pyscf.compute_scf(atom_spec, basis, method, charge=charge, spin=spin)
    iao_res = _pyscf.compute_iao(scf_res, mol)
    ibo_res = _pyscf.compute_ibo(scf_res, iao_res, mol)

    # ── Determine orbital index boundaries ──
    mo_occ = scf_res.mo_occ
    n_ibo = ibo_res.n_ibo
    n_mo_total = scf_res.mo_coeff.shape[1]

    homo_idx = 0
    for i in range(len(mo_occ)):
        if mo_occ[i] > 0.5:
            homo_idx = i
    lumo_idx = homo_idx + 1

    selected = []

    if n_orbitals > 0:
        # Roughly half occupied / half virtual
        n_occ_to_show = max(1, n_orbitals // 2)
        n_vir_to_show = max(1, n_orbitals - n_occ_to_show)

        occ_start = max(0, homo_idx - n_occ_to_show + 1)
        occ_end = homo_idx + 1

        vir_start = lumo_idx
        vir_end = min(n_mo_total, lumo_idx + n_vir_to_show)

        occ_selected = [i for i in range(occ_start, occ_end) if scf_res.mo_energy[i] > -10.0]
        if not occ_selected and occ_end > 0:
            occ_selected = [homo_idx]

        vir_selected = list(range(vir_start, vir_end))
        selected = occ_selected + vir_selected

        if not selected:
            selected = list(range(max(0, n_ibo - n_orbitals), n_ibo))

    # ── Build XYZ data ──
    xyz_lines = [str(mol.natm), "QCViz Pro"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        c = mol.atom_coord(i) * 0.529177249  # Bohr to Angstrom
        xyz_lines.append("%s %.6f %.6f %.6f" % (sym, c[0], c[1], c[2]))
    xyz_data = "\n".join(xyz_lines)

    # ── Metadata ──
    if display_name_hint:
        clean_name = _sanitize_display_name(display_name_hint)
    else:
        clean_name = _extract_name(xyz_string_raw, mol)

    atom_symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    charges_dict = {
        "%s%d" % (atom_symbols[i], i + 1): float(iao_res.charges[i])
        for i in range(mol.natm)
    }

    payload = DashboardPayload(
        molecule_name=clean_name,
        xyz_data=xyz_data,
        atom_symbols=atom_symbols,
        basis=basis,
        method=method,
        energy_hartree=scf_res.energy_hartree,
        charges=charges_dict,
    )

    # ── Generate cube files with hybrid IBO/Canonical branching ──
    total_q = len(selected)
    for qi, i in enumerate(selected):
        if i == homo_idx:
            lbl = "HOMO"
        elif i == lumo_idx:
            lbl = "LUMO"
        elif i < homo_idx:
            lbl = "HOMO-%d" % (homo_idx - i)
        else:
            lbl = "LUMO+%d" % (i - lumo_idx)

        if i <= homo_idx:
            ibo_col_idx = i
            if ibo_col_idx < n_ibo:
                coeff_to_use = ibo_res.coefficients
                col_idx = ibo_col_idx
                lbl_suffix = "(IBO)"
            else:
                coeff_to_use = scf_res.mo_coeff
                col_idx = i
                lbl_suffix = "(Canonical)"
        else:
            coeff_to_use = scf_res.mo_coeff
            col_idx = i
            lbl_suffix = "(Canonical)"

        full_label = "%s %s" % (lbl, lbl_suffix)
        _cli.print_cube_progress(qi + 1, total_q, full_label)

        cube = _pyscf.generate_cube(
            mol, coeff_to_use, col_idx,
            grid_points=(60, 60, 60)
        )
        energy_eV = float(scf_res.mo_energy[i]) * HARTREE_TO_EV

        payload.orbitals.append(
            _viz.prepare_orbital_data(cube, i, full_label, energy=energy_eV)
        )

    # ── ESP calculation ──
    if include_esp:
        esp_res = _pyscf.compute_esp(
            atom_spec, basis, grid_size=60, charge=charge, spin=spin
        )
        payload.esp_data = _viz.prepare_esp_data(
            esp_res.density_cube, esp_res.potential_cube,
            esp_res.vmin, esp_res.vmax
        )

    # ── Render and save ──
    html = _viz.render_dashboard(payload)
    safe_name = _safe_filename(clean_name, fallback="molecule")
    html_path = OUTPUT_DIR / f"{safe_name}_dashboard.html"
    html_path.write_text(html, encoding="utf-8")

    n_occ_shown = len([i for i in selected if i <= homo_idx])
    n_vir_shown = len([i for i in selected if i > homo_idx])

# ... (truncated at 500 lines, 338 lines omitted) ...
```

---

## 📄 `tools/advisor_tools.py` (329 lines)

```python
"""QCViz-MCP v5.0 — Advisor Module MCP Tool Registration.

Registers 5 advisor tools that provide AI-driven chemistry research guidance:
  1. recommend_preset - DFT calculation settings recommendation
  2. draft_methods_section - Publication-ready methods text generation
  3. generate_script - Standalone PySCF script export
  4. validate_against_literature - NIST reference data validation
  5. score_confidence - Composite confidence scoring
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.advisor import (
    PresetRecommender,
    MethodsSectionDrafter,
    CalculationRecord,
    ReproducibilityScriptGenerator,
    LiteratureEnergyValidator,
    ValidationRequest,
    ConfidenceScorer,
)

logger = logging.getLogger(__name__)

# Singleton instances — created once at import time
_recommender = PresetRecommender()
_drafter = MethodsSectionDrafter()
_script_gen = ReproducibilityScriptGenerator()
_validator = LiteratureEnergyValidator()
_scorer = ConfidenceScorer()

@mcp.tool()
def recommend_preset(
    atom_spec: str,
    purpose: str = "geometry_opt",
    charge: int = 0,
    spin: int = 0,
) -> str:
    """Analyze molecular structure and recommend optimal DFT calculation
    settings (functional, basis set, dispersion correction) with
    literature-backed justification.

    Args:
        atom_spec: Molecular structure in XYZ format.
        purpose: Calculation purpose (geometry_opt, single_point,
                 bonding_analysis, reaction_energy, spectroscopy,
                 esp_mapping).
        charge: Molecular charge.
        spin: Spin multiplicity (2S, e.g. 0=singlet, 1=doublet).

    Returns:
        JSON string with recommendation details.
    """
    try:
        rec = _recommender.recommend(
            atom_spec=atom_spec,
            purpose=purpose,
            charge=charge,
            spin=spin,
        )
        return json.dumps({
            "functional": rec.functional,
            "basis": rec.basis,
            "dispersion": rec.dispersion,
            "spin_treatment": rec.spin_treatment,
            "relativistic": rec.relativistic,
            "convergence": rec.convergence,
            "alternatives": [
                {"functional": a[0], "basis": a[1], "rationale": a[2]}
                for a in rec.alternatives
            ],
            "warnings": rec.warnings,
            "references": rec.references,
            "rationale": rec.rationale,
            "confidence": rec.confidence,
            "pyscf_settings": rec.pyscf_settings,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("recommend_preset error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def draft_methods_section(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    software_version: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    citation_style: str = "acs",
    energy_hartree: float = 0.0,
    converged: bool = True,
    n_cycles: int = 0,
) -> str:
    """Generate publication-ready Computational Methods text with BibTeX
    citations from calculation metadata.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional used (e.g. B3LYP-D3(BJ)).
        basis: Basis set used (e.g. def2-SVP).
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction (e.g. D3BJ).
        software_version: PySCF version string.
        optimizer: Geometry optimizer (e.g. geomeTRIC).
        analysis_type: Analysis performed (ibo, iao, esp).
        citation_style: Citation style (acs, rsc, nature).
        energy_hartree: Total energy in Hartree.
        converged: Whether SCF converged.
        n_cycles: Number of SCF cycles.

    Returns:
        JSON with methods_text, bibtex_entries, reviewer_notes, disclaimer.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            software="PySCF",
            software_version=software_version,
            optimizer=optimizer,
            analysis_type=analysis_type,
            energy_hartree=energy_hartree,
            converged=converged,
            n_cycles=n_cycles,
        )
        draft = _drafter.draft(
            [record],
            citation_style=citation_style,
            include_bibtex=True,
        )
        return json.dumps({
            "methods_text": draft.methods_text,
            "bibtex_entries": draft.bibtex_entries,
            "reviewer_notes": draft.reviewer_notes,
            "disclaimer": draft.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("draft_methods_section error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def generate_script(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    include_analysis: bool = True,
) -> str:
    """Generate standalone PySCF Python script that reproduces a
    calculation without QCViz-MCP.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional.
        basis: Basis set.
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction.
        optimizer: Geometry optimizer.
        analysis_type: Analysis type (ibo, esp, etc).
        include_analysis: Whether to include analysis code.

    Returns:
        Complete Python script as a string.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            optimizer=optimizer,
            analysis_type=analysis_type,
        )
        return _script_gen.generate(record, include_analysis=include_analysis)
    except Exception as e:
        logger.error("generate_script error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def validate_against_literature(
    system_formula: str,
    functional: str,
    basis: str,
    bond_lengths: Optional[dict] = None,
    bond_angles: Optional[dict] = None,
) -> str:
    """Compare computed molecular properties against NIST CCCBDB
    reference data and flag deviations.

    Args:
        system_formula: Hill-system molecular formula (e.g. H2O, CH4).
        functional: DFT functional used.
        basis: Basis set used.
        bond_lengths: Dict of bond_type to length in Angstrom.
        bond_angles: Dict of angle_type to angle in degrees.

    Returns:
        JSON with validation results, status, and recommendations.
    """
    try:
        req = ValidationRequest(
            system_formula=system_formula,
            functional=functional,
            basis=basis,
            bond_lengths=bond_lengths or {},
            bond_angles=bond_angles or {},
        )
        result = _validator.validate(req)
        return json.dumps({
            "overall_status": result.overall_status,
            "confidence": result.confidence,
            "method_assessment": result.method_assessment,
            "bond_validations": [
                {
                    "bond": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                    "comment": v.comment,
                }
                for v in result.bond_validations
            ],
            "angle_validations": [
                {
                    "angle": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                }
                for v in result.angle_validations
            ],
            "recommendations": result.recommendations,
            "disclaimer": result.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("validate_against_literature error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def score_confidence(
    functional: str,
    basis: str,
    converged: bool = True,
    n_scf_cycles: int = 0,
    max_cycles: int = 200,
    system_type: str = "organic_small",
    spin: int = 0,
    s2_expected: float = 0.0,
    s2_actual: float = 0.0,
    validation_status: str = None,
) -> str:
    """Compute composite confidence score (0-1) for a quantum chemistry
    calculation based on convergence, method quality, and reference
    agreement.

    Args:
        functional: DFT functional used.
        basis: Basis set used.
        converged: Whether SCF converged.
        n_scf_cycles: Number of SCF cycles taken.
        max_cycles: Maximum allowed SCF cycles.
        system_type: System classification (organic_small, organic_large,
                     3d_tm, heavy_tm, lanthanide, radical,
                     charged_organic, main_group_metal).
        spin: Spin multiplicity.
        s2_expected: Expected <S^2> value.
        s2_actual: Actual <S^2> value.
        validation_status: Literature validation status (PASS/WARN/FAIL).

    Returns:
        JSON with overall_score, sub-scores, breakdown, and recommendations.
    """
    try:
        report = _scorer.score(
            converged=converged,
            n_scf_cycles=n_scf_cycles,
            max_cycles=max_cycles,
            functional=functional,
            basis=basis,
            system_type=system_type,
            spin=spin,
            s2_expected=s2_expected,
            s2_actual=s2_actual,
            validation_status=validation_status,
        )
        return json.dumps({
            "overall_score": report.overall_score,
            "convergence_score": report.convergence_score,
            "basis_score": report.basis_score,
            "method_score": report.method_score,
            "spin_score": report.spin_score,
            "reference_score": report.reference_score,
            "breakdown": report.breakdown_text,
            "recommendations": report.recommendations,
            "disclaimer": report.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("score_confidence error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

```

---

## 📄 `llm/agent.py` (502 lines)

```python
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# FIX(M1): GeminiAgent import for function-calling integration
try:
    from qcviz_mcp.services.gemini_agent import GeminiAgent, GeminiResult
except ImportError:
    GeminiAgent = None  # type: ignore
    GeminiResult = None  # type: ignore

logger = logging.getLogger(__name__)

PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "chat",
                "analyze",
                "single_point",
                "geometry_analysis",
                "partial_charges",
                "orbital_preview",
                "esp_map",
                "geometry_optimization",
                "resolve_structure",
            ],
        },
        "chat_response": {"type": "string", "description": "Natural language response for chat intent"},
        "structure_query": {"type": "string"},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb",
                "bwr",
                "viridis",
                "inferno",
                "spectral",
                "nature",
                "acs",
                "rsc",
                "greyscale",
                "high_contrast",
                "grey",
                "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["intent"],
    "additionalProperties": True,
}

INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "chat": {"tool_name": "chat_response", "focus_tab": "summary"},
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}

SYSTEM_PROMPT = """
You are QCViz Assistant, a conversational AI for a quantum chemistry web app (PySCF-based).
You serve TWO roles:

## ROLE 1: Chatbot (intent="chat")
For questions, explanations, discussions, or anything NOT requesting a computation:
- Answer chemistry questions ("HOMO란 뭐야?", "DFT의 원리", "B3LYP vs HF 차이")
- Explain results and concepts
- Suggest what calculations to run
- General conversation and guidance
- Set intent="chat" and put your answer in chat_response.
- chat_response should be detailed, helpful, in the user's language (Korean/English).
- Use markdown formatting: **bold**, bullet points, etc.
- If the user asks a vague question that COULD be a computation but is unclear,
  respond conversationally and suggest a specific computation they could try.

## ROLE 2: Computation Planner (intent= any computation type)
For explicit computation requests:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

## How to decide:
- "HOMO가 뭐야?" → chat (educational question)
- "물 HOMO 보여줘" → orbital_preview (specific computation)
- "5개 원자 분자 대표적인거" → chat (suggest methane, then offer computation)
- "methane HOMO LUMO" → orbital_preview (clear computation request)
- "이온쌍이란?" → chat (explanation)
- "EMIM TFSI 에너지" → single_point (computation)

Extraction rules:
- structure_query should be the molecule name (English preferred: "water", "methane", "ethanol")
- focus_tab: orbital / esp / charges / geometry / summary
- confidence: 0.0 to 1.0

CRITICAL — Structure resolution (for computation intents only):
- If the user gives a vague description, suggest a specific molecule in chat_response
  and set intent="chat" so they can confirm.
- Examples: "5개 원자 분자" → chat intent, suggest CH4 in response
- NEVER leave structure_query empty for computation intents.
- For Korean names: TFSI- = bis(trifluoromethanesulfonyl)imide,
  EMIM+ = 1-ethyl-3-methylimidazolium, BF4- = tetrafluoroborate.

Always return the planning JSON. For chat intent, chat_response is required.
""".strip()

@dataclass
class AgentPlan:
    intent: str = "analyze"
    structure_query: Optional[str] = None
    structures: Optional[List[Dict[str, Any]]] = None  # FIX(M1): ion pair support
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    tool_name: str = "run_analyze"
    notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    chat_response: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data

class QCVizAgent:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        
        # FIX(M1): Initialize GeminiAgent for function-calling
        self._gemini_agent: Optional[Any] = None
        if GeminiAgent is not None and self.gemini_api_key:
            try:
                self._gemini_agent = GeminiAgent(
                    api_key=self.gemini_api_key,
                    model=self.gemini_model,
                )
                logger.info("GeminiAgent initialized for function calling")
            except Exception as e:
                logger.warning("GeminiAgent init failed: %s", e)

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0}, provider="heuristic")

        chosen = self._choose_provider()
        if chosen == "openai":
            try:
                return self._plan_with_openai(text, context=context or {})
            except Exception:
                pass

        if chosen == "gemini":
            try:
                return self._plan_with_gemini(text, context=context or {})
            except Exception:
                pass

        if chosen == "auto":
            if self.openai_api_key:
                try:
                    return self._plan_with_openai(text, context=context or {})
                except Exception:
                    pass
            if self.gemini_api_key:
                try:
                    return self._plan_with_gemini(text, context=context or {})
                except Exception:
                    pass

        return self._heuristic_plan(text, context=context or {})

    def _choose_provider(self) -> str:
        if self.provider in {"openai", "gemini", "none"}:
            return self.provider
        return "auto"

    def _plan_with_openai(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        from openai import OpenAI

        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=self.openai_api_key)
        user_prompt = self._compose_user_prompt(message, context=context)

        resp = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "plan_quantum_request",
                        "description": "Plan a user request into a QCViz compute intent.",
                        "parameters": PLAN_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "plan_quantum_request"}},
        )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        data: Dict[str, Any]

        if tool_calls:
            args = tool_calls[0].function.arguments or "{}"
            data = json.loads(args)
        else:
            content = self._message_content_to_text(getattr(msg, "content", ""))
            data = self._extract_json_dict(content)

        return self._coerce_plan(data, provider="openai")

    def _plan_with_gemini(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        user_prompt = self._compose_user_prompt(message, context=context)

        # new google-genai
        try:
            from google import genai  # type: ignore

            if not self.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "user", "parts": [{"text": user_prompt}]},
                ],
                config={
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(resp, "text", None) or self._message_content_to_text(resp)
            data = self._extract_json_dict(text)
            return self._coerce_plan(data, provider="gemini")
        except ImportError:
            pass

        # older google-generativeai
        import google.generativeai as genai  # type: ignore

        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel(self.gemini_model)
        resp = model.generate_content(
            f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            generation_config={"response_mime_type": "application/json", "temperature": 0},
        )
        text = getattr(resp, "text", None) or self._message_content_to_text(resp)
        data = self._extract_json_dict(text)
        return self._coerce_plan(data, provider="gemini")

    def _compose_user_prompt(self, message: str, context: Dict[str, Any]) -> str:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return f"Context:\n{context_json}\n\nUser message:\n{message}"

    def _heuristic_plan(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        text = message.strip()
        lower = text.lower()

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = []

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy"]):
            intent = "single_point"
            confidence = 0.82

        structure_query = self._extract_structure_query(text)
        method = self._extract_method(text)
        basis = self._extract_basis(text)
        charge = self._extract_charge(text)
        multiplicity = self._extract_multiplicity(text)
        orbital = self._extract_orbital(text)
        esp_preset = self._extract_esp_preset(text)

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        data = {
            "intent": intent,
            "structure_query": structure_query,
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "orbital": orbital,
            "esp_preset": esp_preset,
            "confidence": confidence,
            "notes": notes,
        }
        return self._coerce_plan(data, provider="heuristic")

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structure_query = self._none_if_blank(data.get("structure_query"))
        method = self._none_if_blank(data.get("method"))
        basis = self._none_if_blank(data.get("basis"))
        orbital = self._none_if_blank(data.get("orbital"))
        esp_preset = self._normalize_preset(self._none_if_blank(data.get("esp_preset")))
        focus_tab = str(data.get("focus_tab") or defaults["focus_tab"]).strip()
        tool_name = str(data.get("tool_name") or defaults["tool_name"]).strip()

        charge = self._safe_int(data.get("charge"))
        multiplicity = self._safe_int(data.get("multiplicity"))
        confidence = self._safe_float(data.get("confidence"), 0.0)
        confidence = max(0.0, min(1.0, confidence))

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]

        chat_response = self._none_if_blank(data.get("chat_response"))

        return AgentPlan(
            intent=intent,
            structure_query=structure_query,
            method=method,
            basis=basis,
            charge=charge,
            multiplicity=multiplicity,
            orbital=orbital,
            esp_preset=esp_preset,
            focus_tab=focus_tab,
            confidence=confidence,
            tool_name=tool_name,
            notes=[str(x) for x in notes if str(x).strip()],
            provider=provider,
            chat_response=chat_response,
            raw=data,
        )

    def _extract_structure_query(self, text: str) -> Optional[str]:
        # pasted xyz block
        if len(re.findall(r"\n", text)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", text, re.M):
            return text.strip()

        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        if quoted:
            first = quoted[0][0] or quoted[0][1]
            if first.strip():
                return first.strip()

        patterns = [
            r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})",
            r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})\s+(?:molecule|structure|system)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
            r"(?i)(?:analyze|compute|calculate|show|render|visualize|optimize)\s+(?:the\s+)?([A-Za-z0-9_\-\+\(\), ]{2,80})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                candidate = m.group(1).strip(" .,:;")
                candidate = re.split(
                    r"\b(using|with|at|in|and show|and render|method|basis|charge|multiplicity|spin|preset)\b",
                    candidate,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip(" .,:;")
                
                # Filter out korean noise words
                for noise in ["의", "에 대한", "에대한", "분자", "구조", "계산", "해줘", "보여줘"]:
                    if candidate.endswith(noise):
                        candidate = candidate[:-len(noise)].strip(" .,:;")
                        
                if candidate and len(candidate) >= 2:
                    return candidate

        common = [
            "water",
            "methane",
            "ammonia",
            "benzene",
            "ethanol",
            "acetone",
            "formaldehyde",
            "carbon dioxide",
            "co2",
            "nh3",
            "h2o",
            "caffeine",
            "naphthalene",
            "pyridine",
            "phenol",
        ]
        lower = text.lower()
        for name in common:
            if name in lower:
                return name

        return None

    def _extract_method(self, text: str) -> Optional[str]:
        methods = [
            "HF",
            "B3LYP",
            "PBE",
            "PBE0",
            "M06-2X",
            "M062X",
            "wB97X-D",
            "WB97X-D",
            "CAM-B3LYP",
            "TPSSh",
            "BP86",
        ]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g",
            "3-21g",

# ... (truncated at 500 lines, 246 lines omitted) ...
```

---

## 📄 `llm/bridge.py` (139 lines)

```python
"""LLM bridge for QCViz web UI."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

from qcviz_mcp.llm.rule_provider import plan_from_message

logger = logging.getLogger(__name__)

@dataclass
class Intent:
    """Normalized intent."""

    intent: str
    query: str
    metadata: Dict[str, Any]

class LLMBridge:
    """Tiered LLM bridge.

    Bootstrap implementation:
    - rule_based
    - auto -> rule_based
    - advisor direct-call helper
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode or "auto"

    def interpret_user_intent(self, message: str) -> Intent:
        """Interpret natural language into structured intent."""
        parsed = plan_from_message(message)
        return Intent(
            intent=parsed.intent,
            query=parsed.query,
            metadata=parsed.metadata,
        )

    def _load_advisor_module(self):
        """Load advisor tool module."""
        return importlib.import_module("qcviz_mcp.tools.advisor_tools")

    def call_advisor_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Call an advisor MCP tool directly as a Python function.

        Args:
            tool_name: Advisor tool name.
            params: Candidate kwargs.

        Returns:
            Tool output, parsed as JSON when possible.
        """
        module = self._load_advisor_module()

        if not hasattr(module, tool_name):
            raise AttributeError("advisor tool not found: %s" % tool_name)

        func = getattr(module, tool_name)
        sig = inspect.signature(func)
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )

        kwargs = {}
        for key, value in dict(params or {}).items():
            if accepts_kwargs or key in sig.parameters:
                kwargs[key] = value

        raw = func(**kwargs)

        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return raw

        return raw

    def generate_response(self, intent: Intent, results: Dict[str, Any]) -> str:
        """Generate a user-facing response."""
        if results.get("status") == "error":
            return "요청을 처리하지 못했습니다. %s" % results.get("error", "알 수 없는 오류")

        advisor = results.get("advisor") or {}
        confidence = advisor.get("confidence") or {}
        confidence_data = confidence.get("data") if isinstance(confidence, dict) else None

        literature = advisor.get("literature") or {}
        literature_data = literature.get("data") if isinstance(literature, dict) else None

        if intent.intent == "geometry_opt":
            base = "구조 최적화 계산이 완료되었습니다. 오른쪽 뷰어에서 최적화된 3D 구조를 확인하세요."
        elif intent.intent == "validate":
            base = "기하구조 분석이 완료되었습니다. 결합 길이와 각도 표를 확인하세요."
        elif intent.intent == "partial_charges":
            base = "부분 전하 계산이 완료되었습니다. Charges 탭에서 원자별 전하를 확인하세요."
        elif intent.intent == "orbital":
            base = "오비탈 프리뷰 계산이 완료되었습니다. Orbitals 탭에서 HOMO/LUMO 근처 궤도를 확인하세요."
        elif intent.intent == "single_point":
            base = "단일점 에너지 계산이 완료되었습니다."
        else:
            base = "요청한 구조 또는 계산 작업이 완료되었습니다."

        parts = [base]

        if results.get("method") and results.get("basis"):
            parts.append(
                "advisor 추천 또는 기본 설정으로 %s/%s 조건을 사용했습니다."
                % (results.get("method"), results.get("basis"))
            )

        if isinstance(confidence_data, dict):
            score = (
                confidence_data.get("score")
                or confidence_data.get("confidence")
                or confidence_data.get("final_score")
            )
            if score is not None:
                parts.append("신뢰도 점수는 %s 입니다." % score)

        if isinstance(literature_data, dict):
            status = (
                literature_data.get("status")
                or literature_data.get("summary")
                or literature_data.get("message")
            )
            if status:
                parts.append("문헌 검증 요약: %s" % status)

        return " ".join(parts)
```

---

## 📄 `services/gemini_agent.py` (315 lines)

```python
"""Gemini Function Calling agent for natural language → computation intent.

# FIX(N7): Gemini API function calling 스키마 3종 + 파싱 에이전트
Uses google-genai SDK with tool declarations for structured extraction.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Gemini Tool Schema ─────────────────────────────────────────

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "run_calculation",
        "description": (
            "양자화학 계산을 실행한다. 단일 분자 또는 이온쌍을 받아 PySCF로 계산한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "structure": {
                    "type": "string",
                    "description": "단일 분자명/화학식. 예: water, H2O, aspirin, benzene",
                },
                "structures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "이온/분자의 PubChem 검색 가능한 영문 화학명",
                            },
                            "charge": {
                                "type": "integer",
                                "description": "이온 전하. 예: +1, -1",
                            },
                        },
                        "required": ["name"],
                    },
                    "description": (
                        "이온쌍/다중 분자. 약어(TFSI, EMIM 등)가 아닌 풀네임으로 변환하여 반환할 것"
                    ),
                },
                "method": {
                    "type": "string",
                    "enum": ["hf", "b3lyp", "mp2", "pbe", "pbe0", "ccsd"],
                    "description": "계산 방법. 기본: hf",
                },
                "basis_set": {
                    "type": "string",
                    "description": "기저함수. 예: sto-3g, 6-31g*, cc-pvdz. 기본: sto-3g",
                },
                "job_type": {
                    "type": "string",
                    "enum": ["energy", "optimize", "frequency", "orbital", "esp"],
                    "description": "계산 종류. 기본: energy",
                },
                "charge": {
                    "type": "integer",
                    "description": "분자 전체 전하. 기본: 0",
                },
                "multiplicity": {
                    "type": "integer",
                    "description": "스핀 다중도. 기본: 1",
                },
            },
        },
    },
    {
        "name": "search_molecule",
        "description": "분자를 이름, 화학식, CAS 번호로 검색한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색어"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_molecule_info",
        "description": "특정 분자의 상세 정보(물성, 구조, 안전데이터)를 조회한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "분자명 (영문)"},
                "properties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "요청 속성. 예: molecular_weight, smiles, safety",
                },
            },
            "required": ["name"],
        },
    },
]

# ── System prompt ─────────────────────────────────────────────

_SYSTEM_PROMPT = """You are QCViz Planner, a quantum chemistry assistant.

Given the user's natural language request, call the most appropriate tool function.

Rules:
- Always call a function. Never respond with plain text.
- For ion pairs (e.g., "EMIM+ TFSI-", "NaCl"), use the `structures` array in run_calculation.
  Expand abbreviations: EMIM → 1-ethyl-3-methylimidazolium, TFSI → bis(trifluoromethylsulfonyl)imide.
- For Korean molecule names, translate them to English first.
- Default method is "hf", default basis_set is "sto-3g".
- Infer job_type from context: "에너지" → energy, "최적화" → optimize, "오비탈"/"HOMO"/"LUMO" → orbital, "ESP"/"전위" → esp.
- If the user just names a molecule without specifying a task, use job_type="energy".
""".strip()

@dataclass
class GeminiResult:
    """Parsed result from Gemini function calling."""
    function_name: str = ""
    intent: str = ""
    structure: Optional[str] = None
    structures: Optional[List[Dict[str, Any]]] = None
    method: str = "hf"
    basis_set: str = "sto-3g"
    job_type: str = "energy"
    charge: int = 0
    multiplicity: int = 1
    raw_response: str = ""
    model_used: str = ""
    # For search/info functions
    query: Optional[str] = None
    properties: Optional[List[str]] = None

class GeminiAgent:
    """Gemini function-calling agent for intent extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self.api_key: str = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model: str = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout: float = timeout or float(os.getenv("GEMINI_TIMEOUT", "10"))
        self.temperature: float = (
            temperature if temperature is not None
            else float(os.getenv("GEMINI_TEMPERATURE", "0.1"))
        )

    def is_available(self) -> bool:
        """Check if Gemini API key is configured."""
        return bool(self.api_key)

    async def parse(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        """Parse user message using Gemini function calling.

        Args:
            message: User's natural language input.
            history: Optional conversation history.

        Returns:
            GeminiResult if successful, None on failure.
        """
        if not self.is_available():
            logger.warning(
                "Gemini API 키 미설정, 폴백 사용 / "
                "Gemini API key not set, using fallback"
            )
            return None

        try:
            return await self._call_gemini(message, history)
        except Exception as e:
            logger.warning(
                "Gemini 호출 실패: %s — 폴백 사용 / "
                "Gemini call failed: %s — using fallback",
                e, e,
            )
            return None

    async def _call_gemini(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        """Internal: make Gemini API call with function declarations."""
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        client = genai.Client(api_key=self.api_key)

        # Build tool declarations
        tool_declarations = []
        for schema in TOOL_SCHEMAS:
            tool_declarations.append(
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema.get("description", ""),
                    parameters=schema.get("parameters"),
                )
            )

        tools = [types.Tool(function_declarations=tool_declarations)]

        # Build contents
        contents: List[types.Content] = []

        if history:
            for msg in history:
                role = msg.get("role", "user")
                text = msg.get("text", msg.get("content", ""))
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=text)],
                    )
                )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )
        )

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            tools=tools,
            temperature=self.temperature,
        )

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        return self._extract_result(response)

    def _extract_result(self, response: Any) -> Optional[GeminiResult]:
        """Extract function call result from Gemini response."""
        try:
            # Navigate response to find function call
            candidates = getattr(response, "candidates", [])
            if not candidates:
                logger.warning("Gemini 응답에 candidates 없음")
                return None

            content = candidates[0].content
            parts = content.parts if content else []

            for part in parts:
                fn_call = getattr(part, "function_call", None)
                if fn_call is None:
                    continue

                fn_name = fn_call.name
                args = dict(fn_call.args) if fn_call.args else {}

                logger.info(
                    "Gemini function call: %s(%s)",
                    fn_name,
                    json.dumps(args, ensure_ascii=False, default=str)[:200],
                )

                result = GeminiResult(
                    function_name=fn_name,
                    raw_response=str(response)[:500],
                    model_used=self.model,
                )

                if fn_name == "run_calculation":
                    result.intent = "calculate"
                    result.structure = args.get("structure")
                    result.structures = args.get("structures")
                    result.method = args.get("method", "hf")
                    result.basis_set = args.get("basis_set", "sto-3g")
                    result.job_type = args.get("job_type", "energy")
                    result.charge = int(args.get("charge", 0))
                    result.multiplicity = int(args.get("multiplicity", 1))

                elif fn_name == "search_molecule":
                    result.intent = "search"
                    result.query = args.get("query")

                elif fn_name == "get_molecule_info":
                    result.intent = "info"
                    result.structure = args.get("name")
                    result.properties = args.get("properties")

                return result

            # No function call found — try to extract text
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    logger.info("Gemini returned text instead of function call: %s", text[:200])

            return None

        except Exception as e:
            logger.warning("Gemini 응답 파싱 실패: %s", e)
            return None

```

---

## 📄 `services/structure_resolver.py` (281 lines)

```python
"""Unified structure resolution pipeline: name → SDF → XYZ.

# FIX(N6): MolChat 1순위, PubChem 폴백, 한국어 별칭, LRU 캐시
Pipeline:
  1. ko_aliases.translate() — 한국어→영어
  2. MolChat resolve → card → SMILES → generate-3d → SDF
  3. Fallback: PubChem name→SDF or name→CID→SDF
  4. SDF → XYZ (sdf_converter)
"""
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from . import ko_aliases
from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import sdf_to_xyz

logger = logging.getLogger(__name__)

_CACHE_MAX_SIZE = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))

# Chemistry abbreviation → PubChem-searchable name
CHEM_ABBREVIATIONS: Dict[str, str] = {
    # Battery electrolyte anions
    "tfsi": "bis(trifluoromethanesulfonyl)imide",
    "tfsi-": "bis(trifluoromethanesulfonyl)imide",
    "fsi": "bis(fluorosulfonyl)imide",
    "fsi-": "bis(fluorosulfonyl)imide",
    "pf6": "hexafluorophosphate",
    "pf6-": "hexafluorophosphate",
    "bf4": "tetrafluoroborate",
    "bf4-": "tetrafluoroborate",
    # Battery electrolyte solvents
    "ec": "ethylene carbonate",
    "pc": "propylene carbonate",
    "dmc": "dimethyl carbonate",
    "emc": "ethyl methyl carbonate",
    "dec": "diethyl carbonate",
    "dme": "1,2-dimethoxyethane",
    "fec": "fluoroethylene carbonate",
    "vc": "vinylene carbonate",
    # Battery cations
    "emim": "1-ethyl-3-methylimidazolium",
    "emim+": "1-ethyl-3-methylimidazolium",
    "bmim": "1-butyl-3-methylimidazolium",
    "bmim+": "1-butyl-3-methylimidazolium",
    # Common molecules
    "thf": "tetrahydrofuran",
    "dmf": "dimethylformamide",
    "dmso": "dimethyl sulfoxide",
    "nmp": "n-methyl-2-pyrrolidone",
    "acn": "acetonitrile",
    "meoh": "methanol",
    "etoh": "ethanol",
    "toluene": "toluene",
    "dcm": "dichloromethane",
}

@dataclass
class StructureResult:
    """Resolved structure data."""
    xyz: str = ""
    sdf: Optional[str] = None
    smiles: Optional[str] = None
    cid: Optional[int] = None
    name: str = ""
    source: str = ""  # "molchat", "pubchem", "builtin", etc.
    molecular_weight: Optional[float] = None

class StructureResolver:
    """Stateful resolver with LRU cache."""

    def __init__(
        self,
        molchat: Optional[MolChatClient] = None,
        pubchem: Optional[PubChemClient] = None,
        cache_max_size: int = _CACHE_MAX_SIZE,
    ) -> None:
        self.molchat = molchat or MolChatClient()
        self.pubchem = pubchem or PubChemClient()
        self._cache: OrderedDict[str, StructureResult] = OrderedDict()
        self._cache_max = cache_max_size
        self._cache_lock = Lock()

    # ── cache helpers ─────────────────────────────────────────

    def _cache_get(self, key: str) -> Optional[StructureResult]:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: str, value: StructureResult) -> None:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                self._cache[key] = value
                while len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)

    # ── main resolve ──────────────────────────────────────────

    async def resolve(self, query: str) -> StructureResult:
        """Resolve a molecule query to XYZ coordinates.

        Args:
            query: Molecule name (Korean or English), SMILES, or chemical formula.

        Returns:
            StructureResult with xyz, sdf, smiles, etc.

        Raises:
            ValueError: If structure cannot be resolved from any source.
        """
        if not query or not query.strip():
            raise ValueError(
                "구조 쿼리가 비어있습니다 / Structure query is empty"
            )

        original_query = query.strip()

        # Step 1: Korean → English translation
        translated = ko_aliases.translate(original_query)
        # If translation changed the text, use translated version
        search_name = translated if translated != original_query else original_query

        # Step 1.5: Chemistry abbreviation → full name
        abbrev_key = search_name.lower().strip()
        if abbrev_key in CHEM_ABBREVIATIONS:
            logger.info("Abbreviation '%s' → '%s'", search_name, CHEM_ABBREVIATIONS[abbrev_key])
            search_name = CHEM_ABBREVIATIONS[abbrev_key]

        # Check cache
        cache_key = search_name.lower().strip()
        cached = self._cache_get(cache_key)
        if cached:
            logger.debug("Cache hit: %s", cache_key)
            return cached

        # Step 2: Try MolChat pipeline
        result = await self._try_molchat(search_name)
        if result:
            result.name = original_query
            self._cache_put(cache_key, result)
            return result

        # Step 3: Try PubChem fallback
        pubchem_enabled = os.getenv("PUBCHEM_FALLBACK", "true").lower() in ("true", "1", "yes")
        if pubchem_enabled:
            result = await self._try_pubchem(search_name)
            if result:
                result.name = original_query
                self._cache_put(cache_key, result)
                return result

        raise ValueError(
            f"'{original_query}' 구조를 찾을 수 없습니다. "
            f"MolChat 및 PubChem에서 모두 실패했습니다. / "
            f"Cannot resolve structure for '{original_query}'. "
            f"Both MolChat and PubChem failed."
        )

    # ── MolChat pipeline ─────────────────────────────────────

    async def _try_molchat(self, name: str) -> Optional[StructureResult]:
        """MolChat: resolve → card → SMILES → generate-3d → SDF → XYZ."""
        try:
            # resolve name → CID
            resolved = await self.molchat.resolve([name])
            if not resolved:
                logger.info("MolChat resolve 실패: %s", name)
                return None

            cid = resolved[0].get("cid")

            # get card → SMILES
            card = await self.molchat.get_card(name)
            smiles: Optional[str] = None
            molecular_weight: Optional[float] = None

            if card:
                smiles = card.get("canonical_smiles") or card.get("smiles")
                molecular_weight = card.get("molecular_weight")

            if not smiles and cid:
                # Fallback: get SMILES from PubChem using CID
                smiles = await self.pubchem.cid_to_smiles(cid)

            if not smiles:
                logger.info("MolChat에서 SMILES를 얻지 못함: %s", name)
                return None

            # generate 3D SDF
            sdf = await self.molchat.generate_3d_sdf(smiles)
            if not sdf:
                logger.info("MolChat generate-3d 실패: %s (SMILES: %s)", name, smiles)
                return None

            # SDF → XYZ
            xyz = sdf_to_xyz(sdf, comment=name)

            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="molchat",
                molecular_weight=molecular_weight,
            )

        except Exception as e:
            logger.warning(
                "MolChat 파이프라인 실패: %s → %s / "
                "MolChat pipeline failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── PubChem pipeline ──────────────────────────────────────

    async def _try_pubchem(self, name: str) -> Optional[StructureResult]:
        """PubChem fallback: name → SDF (direct or via CID)."""
        try:
            # Try direct name → SDF
            sdf = await self.pubchem.name_to_sdf_3d(name)

            cid: Optional[int] = None
            smiles: Optional[str] = None

            if not sdf:
                # Try name → CID → SDF
                cid = await self.pubchem.name_to_cid(name)
                if cid:
                    sdf = await self.pubchem.cid_to_sdf_3d(cid)

            if not sdf:
                return None

            # Get SMILES for metadata
            if cid:
                smiles = await self.pubchem.cid_to_smiles(cid)
            else:
                cid = await self.pubchem.name_to_cid(name)
                if cid:
                    smiles = await self.pubchem.cid_to_smiles(cid)

            xyz = sdf_to_xyz(sdf, comment=name)

            return StructureResult(
                xyz=xyz,
                sdf=sdf,
                smiles=smiles,
                cid=cid,
                name=name,
                source="pubchem",
                molecular_weight=None,
            )

        except Exception as e:
            logger.warning(
                "PubChem 파이프라인 실패: %s → %s / "
                "PubChem pipeline failed: %s → %s",
                name, e, name, e,
            )
            return None

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        await self.molchat.close()
        await self.pubchem.close()

```

---

## 📄 `services/pubchem_client.py` (194 lines)

```python
"""PubChem PUG-REST async client (fallback for MolChat).

# FIX(N4): PubChem REST 클라이언트 — name→CID, CID→SMILES, CID→3D SDF
Rate limit: 4 req/s (sleep 0.25s between calls).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_DEFAULT_TIMEOUT = 10
_RATE_LIMIT_DELAY = 0.25  # 4 req/s

class PubChemClient:
    """Async HTTP client for PubChem PUG-REST API."""

    def __init__(
        self,
        timeout: Optional[float] = None,
    ) -> None:
        self.timeout: float = timeout or float(
            os.getenv("PUBCHEM_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "QCViz-MCP/3.0 PubChemFallback",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        await asyncio.sleep(_RATE_LIMIT_DELAY)

    # ── name → CID ─────────────────────────────────────────────

    async def name_to_cid(self, name: str) -> Optional[int]:
        """Resolve molecule name to PubChem CID.

        GET /compound/name/{name}/cids/JSON
        """
        if not name or not name.strip():
            return None

        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/name/{httpx.URL(name.strip())}/cids/JSON"
        # Use manual URL to avoid double encoding
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            cids = data.get("IdentifierList", {}).get("CID", [])
            return int(cids[0]) if cids else None
        except Exception as e:
            logger.warning(
                "PubChem name_to_cid 실패: %s → %s / "
                "PubChem name_to_cid failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── CID → SMILES ──────────────────────────────────────────

    async def cid_to_smiles(self, cid: int) -> Optional[str]:
        """Get canonical SMILES from CID.

        GET /compound/cid/{cid}/property/CanonicalSMILES/JSON
        """
        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES/JSON"
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                return props[0].get("CanonicalSMILES")
            return None
        except Exception as e:
            logger.warning(
                "PubChem cid_to_smiles 실패: CID %d → %s / "
                "PubChem cid_to_smiles failed: CID %d → %s",
                cid, e, cid, e,
            )
            return None

    # ── CID → 3D SDF ─────────────────────────────────────────

    async def cid_to_sdf_3d(self, cid: int) -> Optional[str]:
        """Download 3D SDF from PubChem.

        GET /compound/cid/{cid}/SDF?record_type=3d
        """
        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/SDF"
        try:
            resp = await client.get(url, params={"record_type": "3d"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text.strip()
            if "V2000" in text:
                return text
            logger.warning(
                "PubChem SDF 응답에 V2000 블록 없음 (CID %d) / "
                "No V2000 in PubChem SDF response (CID %d)",
                cid, cid,
            )
            return None
        except Exception as e:
            logger.warning(
                "PubChem cid_to_sdf_3d 실패: CID %d → %s / "
                "PubChem cid_to_sdf_3d failed: CID %d → %s",
                cid, e, cid, e,
            )
            return None

    # ── name → 3D SDF (direct) ────────────────────────────────

    async def name_to_sdf_3d(self, name: str) -> Optional[str]:
        """Download 3D SDF directly by name (convenience shortcut).

        GET /compound/name/{name}/SDF?record_type=3d
        """
        if not name or not name.strip():
            return None

        await self._rate_limit()
        client = await self._get_client()
        url = f"{_PUBCHEM_BASE}/compound/name/{httpx.URL(name.strip())}/SDF"
        try:
            resp = await client.get(url, params={"record_type": "3d"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text.strip()
            if "V2000" in text:
                return text
            return None
        except Exception as e:
            logger.warning(
                "PubChem name_to_sdf_3d 실패: %s → %s / "
                "PubChem name_to_sdf_3d failed: %s → %s",
                name, e, name, e,
            )
            return None

    # ── high-level: name → XYZ pipeline ──────────────────────

    async def name_to_sdf_full(self, name: str) -> Optional[str]:
        """Try direct name→SDF, then name→CID→SDF fallback.

        Returns:
            SDF text or None.
        """
        # Try direct
        sdf = await self.name_to_sdf_3d(name)
        if sdf:
            return sdf

        # Fallback: name → CID → SDF
        cid = await self.name_to_cid(name)
        if cid:
            sdf = await self.cid_to_sdf_3d(cid)
            if sdf:
                return sdf

        return None

```

---

## 📄 `services/molchat_client.py` (152 lines)

```python
"""MolChat API async client.

# FIX(N3): MolChat REST 클라이언트 — resolve, card, generate-3d/sdf
Base URL: http://psid.aizen.co.kr/molchat
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://psid.aizen.co.kr/molchat"
_DEFAULT_TIMEOUT = 15

class MolChatClient:
    """Async HTTP client for the MolChat molecule service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url: str = (
            base_url
            or os.getenv("MOLCHAT_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout: float = timeout or float(
            os.getenv("MOLCHAT_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self.api_key: Optional[str] = api_key or os.getenv("MOLCHAT_API_KEY")
        self._client: Optional[httpx.AsyncClient] = None

    # ── lifecycle ──────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── health ─────────────────────────────────────────────────

    async def health_live(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/health/live")
            return resp.status_code == 200
        except Exception:
            return False

    async def health_ready(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/health/ready")
            return resp.status_code == 200
        except Exception:
            return False

    # ── resolve ────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def resolve(self, names: List[str]) -> List[Dict[str, Any]]:
        """Resolve molecule names to CIDs.

        GET /api/v1/molecules/resolve?names=water,ethanol

        Returns:
            List of {name, cid} dicts. Items without CID are omitted.
        """
        if not names:
            return []

        client = await self._get_client()
        names_param = ",".join(n.strip() for n in names if n.strip())
        resp = await client.get(
            "/api/v1/molecules/resolve",
            params={"names": names_param},
        )
        resp.raise_for_status()
        data = resp.json()
        resolved = data.get("resolved", [])
        return [r for r in resolved if r.get("cid")]

    # ── card ───────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def get_card(self, query: str) -> Optional[Dict[str, Any]]:
        """Get molecule card (SMILES, weight, etc.).

        GET /api/v1/molecules/card?q=aspirin

        Returns:
            Card dict or None if not found.
        """
        if not query or not query.strip():
            return None

        client = await self._get_client()
        resp = await client.get(
            "/api/v1/molecules/card",
            params={"q": query.strip()},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data if data.get("cid") else None

    # ── generate-3d SDF ───────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),

# ... (truncated at 150 lines, 74 lines omitted) ...
```

---

## 📄 `services/ion_pair_handler.py` (176 lines)

```python
"""Ion pair abbreviation dictionary and multi-ion resolve logic.

# FIX(N5): 이온쌍 별칭 27개 + 이온쌍 감지 + 개별 resolve + SDF merge
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .molchat_client import MolChatClient
from .pubchem_client import PubChemClient
from .sdf_converter import merge_sdfs, sdf_to_xyz

logger = logging.getLogger(__name__)

# ── 이온쌍 약어 사전 (27개) ────────────────────────────────────
# format: abbreviation → {"name": full PubChem-searchable name, "type": "cation"|"anion", "default_charge": int}
ION_ALIASES: Dict[str, Dict[str, Any]] = {
    # Cations
    "EMIM":  {"name": "1-ethyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BMIM":  {"name": "1-butyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "HMIM":  {"name": "1-hexyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "OMIM":  {"name": "1-octyl-3-methylimidazolium", "type": "cation", "default_charge": 1},
    "BPy":   {"name": "1-butylpyridinium", "type": "cation", "default_charge": 1},
    "DEME":  {"name": "N,N-diethyl-N-methyl-N-(2-methoxyethyl)ammonium", "type": "cation", "default_charge": 1},
    "P14":   {"name": "N-butyl-N-methylpyrrolidinium", "type": "cation", "default_charge": 1},
    "TEA":   {"name": "tetraethylammonium", "type": "cation", "default_charge": 1},
    "TBA":   {"name": "tetrabutylammonium", "type": "cation", "default_charge": 1},
    "Li":    {"name": "lithium ion", "type": "cation", "default_charge": 1},
    "Na":    {"name": "sodium ion", "type": "cation", "default_charge": 1},
    "K":     {"name": "potassium ion", "type": "cation", "default_charge": 1},
    # Anions
    "TFSI":  {"name": "bis(trifluoromethylsulfonyl)imide", "type": "anion", "default_charge": -1},
    "BF4":   {"name": "tetrafluoroborate", "type": "anion", "default_charge": -1},
    "PF6":   {"name": "hexafluorophosphate", "type": "anion", "default_charge": -1},
    "OTf":   {"name": "trifluoromethanesulfonate", "type": "anion", "default_charge": -1},
    "DCA":   {"name": "dicyanamide", "type": "anion", "default_charge": -1},
    "SCN":   {"name": "thiocyanate", "type": "anion", "default_charge": -1},
    "OAc":   {"name": "acetate", "type": "anion", "default_charge": -1},
    "Cl":    {"name": "chloride", "type": "anion", "default_charge": -1},
    "Br":    {"name": "bromide", "type": "anion", "default_charge": -1},
    "I":     {"name": "iodide", "type": "anion", "default_charge": -1},
    "NO3":   {"name": "nitrate", "type": "anion", "default_charge": -1},
    "HSO4":  {"name": "hydrogen sulfate", "type": "anion", "default_charge": -1},
    "FSI":   {"name": "bis(fluorosulfonyl)imide", "type": "anion", "default_charge": -1},
    "BOB":   {"name": "bis(oxalato)borate", "type": "anion", "default_charge": -1},
    "FAP":   {"name": "tris(pentafluoroethyl)trifluorophosphate", "type": "anion", "default_charge": -1},
}

@dataclass
class IonPairResult:
    """Result of ion-pair resolution."""
    xyz: str = ""
    total_charge: int = 0
    smiles_list: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    source: str = "ion_pair_handler"
    individual_sdfs: List[str] = field(default_factory=list)

def expand_alias(name: str) -> Dict[str, Any]:
    """Expand an ion abbreviation to its full searchable name.

    Returns:
        Dict with 'name', 'type', 'default_charge' or the original name
        with charge 0 if not an alias.
    """
    clean = name.strip().rstrip("+-")
    if clean in ION_ALIASES:
        return dict(ION_ALIASES[clean])

    # Case-insensitive lookup
    upper = clean.upper()
    for key, val in ION_ALIASES.items():
        if key.upper() == upper:
            return dict(val)

    # Not a known alias — return as-is with neutral charge
    return {"name": name.strip(), "type": "unknown", "default_charge": 0}

def is_ion_pair(structures: List[Dict[str, Any]]) -> bool:
    """Check if the structures list represents an ion pair.

    An ion pair requires at least 2 structures, and at least one must
    have a non-zero charge or be a known ion alias.
    """
    if not structures or len(structures) < 2:
        return False

    has_charged = False
    for s in structures:
        name = s.get("name", "")
        charge = s.get("charge", 0)
        clean = name.strip().rstrip("+-")

        if charge and charge != 0:
            has_charged = True
        elif clean in ION_ALIASES or clean.upper() in {k.upper() for k in ION_ALIASES}:
            has_charged = True

    return has_charged

async def resolve_ion_pair(
    structures: List[Dict[str, Any]],
    molchat: MolChatClient,
    pubchem: PubChemClient,
    offset: float = 5.0,
) -> IonPairResult:
    """Resolve an ion pair by resolving each ion individually then merging.

    Args:
        structures: List of dicts with 'name' and optional 'charge'.
        molchat: MolChat API client.
        pubchem: PubChem API client (fallback).
        offset: X-axis offset between fragments (Å).

    Returns:
        IonPairResult with merged XYZ and total charge.

    Raises:
        ValueError: If resolution fails for any ion.
    """
    # Avoid circular import
    from .structure_resolver import StructureResolver

    resolver = StructureResolver(molchat=molchat, pubchem=pubchem)

    result = IonPairResult()
    sdfs: List[str] = []

    for ion_spec in structures:
        raw_name = ion_spec.get("name", "").strip()
        explicit_charge = ion_spec.get("charge")

        # Expand alias
        info = expand_alias(raw_name)
        search_name = info["name"]
        ion_charge = explicit_charge if explicit_charge is not None else info["default_charge"]

        logger.info(
            "이온 resolve 중: %s → %s (charge=%d) / "
            "Resolving ion: %s → %s (charge=%d)",
            raw_name, search_name, ion_charge,
            raw_name, search_name, ion_charge,
        )

        # Resolve to SDF via structure_resolver's internal pipeline
        resolved = await resolver.resolve(search_name)

        if not resolved or not resolved.sdf:
            raise ValueError(
                f"이온 '{raw_name}' ({search_name}) 구조 해석 실패 / "
                f"Failed to resolve ion '{raw_name}' ({search_name})"
            )

        sdfs.append(resolved.sdf)
        result.total_charge += ion_charge
        result.names.append(search_name)
        if resolved.smiles:
            result.smiles_list.append(resolved.smiles)

    # Merge SDFs into single XYZ
    comment = f"Ion pair: {' + '.join(result.names)}"
    result.xyz = merge_sdfs(sdfs, offset=offset, comment=comment)
    result.individual_sdfs = sdfs
    result.source = "ion_pair_handler"

    logger.info(
        "이온쌍 해석 완료: %s (total_charge=%d) / "
        "Ion pair resolved: %s (total_charge=%d)",
        result.names, result.total_charge,
        result.names, result.total_charge,
    )

    return result

```

---

## 📄 `services/ko_aliases.py` (82 lines)

```python
"""Korean → English molecule name alias dictionary and translator.

# FIX(N1): 한국어 분자명 30개 매핑 + 조사 제거 + 번역 함수
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# ── 한국어→영어 분자명 매핑 (30개) ──────────────────────────────
KO_TO_EN: Dict[str, str] = {
    "물": "water",
    "에탄올": "ethanol",
    "메탄올": "methanol",
    "메탄": "methane",
    "에탄": "ethane",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "아세톤": "acetone",
    "암모니아": "ammonia",
    "이산화탄소": "carbon dioxide",
    "일산화탄소": "carbon monoxide",
    "포름알데히드": "formaldehyde",
    "아세트산": "acetic acid",
    "글리신": "glycine",
    "요소": "urea",
    "피리딘": "pyridine",
    "페놀": "phenol",
    "아스피린": "aspirin",
    "카페인": "caffeine",
    "포도당": "glucose",
    "과산화수소": "hydrogen peroxide",
    "황산": "sulfuric acid",
    "염산": "hydrochloric acid",
    "수산화나트륨": "sodium hydroxide",
    "아세틸렌": "acetylene",
    "프로판": "propane",
    "부탄": "butane",
    "나프탈렌": "naphthalene",
    "글루탐산": "glutamic acid",
    "세로토닌": "serotonin",
}

# ── 한국어 조사 패턴 (제거 대상) ──────────────────────────────
_JOSA_PATTERN = re.compile(
    r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지|처럼|같은|하고|이랑|랑|과|와)\s*$"
)

_JOSA_INLINE_PATTERN = re.compile(
    r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지|처럼|같은|하고|이랑|랑|과|와)(?=\s)"
)

def _strip_josa(text: str) -> str:
    """Remove trailing Korean postpositions (조사)."""
    result = text.strip()
    for _ in range(3):  # iterative strip in case of stacking
        prev = result
        result = _JOSA_PATTERN.sub("", result).strip()
        if result == prev:
            break
    return result

def translate(text: str) -> str:
    """Translate Korean molecule names to English in the input text.

    - Longest-match-first replacement to avoid partial matches.
    - Strips common Korean postpositions before and after replacement.

    Args:
        text: User input that may contain Korean molecule names.

    Returns:
        Text with Korean molecule names replaced by English equivalents.
    """
    if not text or not text.strip():
        return text

    result = text.strip()

    # Sort by length descending for longest-match-first

# ... (truncated at 80 lines, 37 lines omitted) ...
```

---

## 📄 `compute/pyscf_runner.py` (602 lines)

```python
"""PySCF computation runner — single-point, geometry, orbital, ESP, optimization.

# FIX(M4): XYZ 문자열 직접 입력 강화, atoms list [(sym,(x,y,z))] 지원,
#          +/- regex 안전화, re.error 방지, progress callback 유지
기존 인터페이스 전부 유지 (run_analyze, run_single_point 등).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import math
import re
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

import numpy as np
from pyscf import dft, gto, scf
from pyscf.tools import cubegen

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:
    geometric_optimize = None

# ── CONSTANTS ────────────────────────────────────────────────

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
BOHR_TO_ANGSTROM = 0.529177210903
EV_TO_KCAL = 23.06054783061903

DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

DEFAULT_ESP_PRESET_ORDER = [
    "acs", "rsc", "nature", "spectral", "inferno",
    "viridis", "rwb", "bwr", "greyscale", "high_contrast",
]

ESP_PRESETS_DATA: Dict[str, Dict[str, Any]] = {
    "acs": {"id": "acs", "label": "ACS-style", "aliases": ["american chemical society", "acs-style", "science", "default"], "surface_scheme": "rwb", "default_range_au": 0.060, "description": "Balanced red-white-blue diverging scheme."},
    "rsc": {"id": "rsc", "label": "RSC-style", "aliases": ["royal society of chemistry", "rsc-style"], "surface_scheme": "bwr", "default_range_au": 0.055, "description": "Soft blue-white-red variant."},
    "nature": {"id": "nature", "label": "Nature-style", "aliases": ["nature-style"], "surface_scheme": "spectral", "default_range_au": 0.055, "description": "Publication-friendly spectral scheme."},
    "spectral": {"id": "spectral", "label": "Spectral", "aliases": ["rainbow", "diverging"], "surface_scheme": "spectral", "default_range_au": 0.060, "description": "High contrast diverging palette."},
    "inferno": {"id": "inferno", "label": "Inferno", "aliases": [], "surface_scheme": "inferno", "default_range_au": 0.055, "description": "Perceptually uniform warm palette."},
    "viridis": {"id": "viridis", "label": "Viridis", "aliases": [], "surface_scheme": "viridis", "default_range_au": 0.055, "description": "Perceptually uniform scientific palette."},
    "rwb": {"id": "rwb", "label": "Red-White-Blue", "aliases": ["red-white-blue", "red white blue"], "surface_scheme": "rwb", "default_range_au": 0.060, "description": "Classic diverging palette."},
    "bwr": {"id": "bwr", "label": "Blue-White-Red", "aliases": ["blue-white-red", "blue white red"], "surface_scheme": "bwr", "default_range_au": 0.060, "description": "Classic positive/neutral/negative."},
    "greyscale": {"id": "greyscale", "label": "Greyscale", "aliases": ["gray", "grey", "mono", "monochrome"], "surface_scheme": "greyscale", "default_range_au": 0.050, "description": "Monochrome publication palette."},
    "high_contrast": {"id": "high_contrast", "label": "High Contrast", "aliases": ["high-contrast", "contrast"], "surface_scheme": "high_contrast", "default_range_au": 0.070, "description": "Strong contrast for presentations."},
}

# FIX(M4): Korean aliases moved to services/ko_aliases.py but kept here for backward compat
_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water", "워터": "water", "암모니아": "ammonia", "메탄": "methane",
    "에탄": "ethane", "에틸렌": "ethylene", "아세틸렌": "acetylene", "벤젠": "benzene",
    "톨루엔": "toluene", "페놀": "phenol", "아닐린": "aniline", "피리딘": "pyridine",
    "아세톤": "acetone", "메탄올": "methanol", "에탄올": "ethanol",
    "포름알데히드": "formaldehyde", "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid", "아세트산": "acetic_acid", "요소": "urea",
    "우레아": "urea", "이산화탄소": "carbon_dioxide", "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen", "산소": "oxygen", "수소": "hydrogen", "불소": "fluorine", "네온": "neon",
}

_METHOD_ALIASES: Dict[str, str] = {
    "hf": "HF", "rhf": "HF", "uhf": "HF", "b3lyp": "B3LYP",
    "pbe": "PBE", "pbe0": "PBE0", "m062x": "M06-2X", "m06-2x": "M06-2X",
    "wb97xd": "wB97X-D", "ωb97x-d": "wB97X-D", "wb97x-d": "wB97X-D",
    "bp86": "BP86", "blyp": "BLYP", "mp2": "MP2", "ccsd": "CCSD",
}

_BASIS_ALIASES: Dict[str, str] = {
    "sto-3g": "STO-3G", "3-21g": "3-21G", "6-31g": "6-31G",
    "6-31g*": "6-31G*", "6-31g(d)": "6-31G*", "6-31g**": "6-31G**",
    "6-31g(d,p)": "6-31G**", "def2svp": "def2-SVP", "def2-svp": "def2-SVP",
    "def2tzvp": "def2-TZVP", "def2-tzvp": "def2-TZVP",
    "cc-pvdz": "cc-pVDZ", "cc-pvtz": "cc-pVTZ",
    "aug-cc-pvdz": "aug-cc-pVDZ", "aug-cc-pvtz": "aug-cc-pVTZ",
}

_COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.85, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38,
    "I": 1.39, "Xe": 1.40, "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
}

BUILTIN_XYZ_LIBRARY = {
    "water": "3\n\nO 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469",
    "ammonia": "4\n\nN 0.000 0.000 0.112\nH 0.000 0.938 -0.262\nH 0.812 -0.469 -0.262\nH -0.812 -0.469 -0.262",
    "methane": "5\n\nC 0.000 0.000 0.000\nH 0.627 0.627 0.627\nH -0.627 -0.627 0.627\nH 0.627 -0.627 -0.627\nH -0.627 0.627 -0.627",
    "benzene": "12\n\nC 0.0000 1.3965 0.0000\nC 1.2094 0.6983 0.0000\nC 1.2094 -0.6983 0.0000\nC 0.0000 -1.3965 0.0000\nC -1.2094 -0.6983 0.0000\nC -1.2094 0.6983 0.0000\nH 0.0000 2.4842 0.0000\nH 2.1514 1.2421 0.0000\nH 2.1514 -1.2421 0.0000\nH 0.0000 -2.4842 0.0000\nH -2.1514 -1.2421 0.0000\nH -2.1514 1.2421 0.0000",
    "acetone": "10\n\nC 0.000 0.280 0.000\nO 0.000 1.488 0.000\nC 1.285 -0.551 0.000\nC -1.285 -0.551 0.000\nH 1.266 -1.203 -0.880\nH 1.266 -1.203 0.880\nH 2.155 0.106 0.000\nH -1.266 -1.203 -0.880\nH -1.266 -1.203 0.880\nH -2.155 0.106 0.000",
}

# ── CORE UTILS ───────────────────────────────────────────────

def unique(arr: list) -> list:
    seen: set = set()
    out = []
    for x in arr:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _dedupe_strings(items: Iterable[Any]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for item in items or []:
        text = _safe_str(item, "")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out

def _normalize_name_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    # FIX(M4): safe regex — escape + and - inside character class properly
    s = re.sub(r"[^0-9a-zA-Z가-힣\+\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_method_name(method: Optional[str]) -> str:
    key = _normalize_name_token(method).replace(" ", "")
    return _METHOD_ALIASES.get(key, _safe_str(method, DEFAULT_METHOD) or DEFAULT_METHOD)

def _normalize_basis_name(basis: Optional[str]) -> str:
    key = _normalize_name_token(basis).replace(" ", "")
    return _BASIS_ALIASES.get(key, _safe_str(basis, DEFAULT_BASIS) or DEFAULT_BASIS)

def _normalize_esp_preset(preset: Optional[str]) -> str:
    raw = _normalize_name_token(preset)
    if not raw:
        return "acs"
    compact = raw.replace(" ", "_")
    if compact in ESP_PRESETS_DATA:
        return compact
    for key, meta in ESP_PRESETS_DATA.items():
        aliases = [_normalize_name_token(a).replace(" ", "_") for a in meta.get("aliases", [])]
        if compact == key or compact in aliases:
            return key
    if compact in {"default", "auto"}:
        return "acs"
    return "acs"

def _looks_like_xyz(text: Optional[str]) -> bool:
    if not text:
        return False
    s = str(text).strip()
    if "\n" in s:
        lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[2:]
        # FIX(M4): safe atom pattern — no unescaped +/- issues
        atom_pat = re.compile(r"^[A-Za-z]{1,3}\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?$")
        atom_lines = [ln for ln in lines if atom_pat.match(ln.strip())]
        return len(atom_lines) >= 1
    return False

def _strip_xyz_header(xyz_text: str) -> str:
    lines = (xyz_text or "").splitlines()
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            start_idx = i
            break
    else:
        return ""
    first_line = lines[start_idx].strip()
    if re.fullmatch(r"\d+", first_line):
        start_idx += 2
    atom_lines = [ln.strip() for ln in lines[start_idx:] if ln.strip()]
    return "\n".join(atom_lines)

# FIX(M4): atoms list [(sym, (x,y,z))] → atom_spec string
def _atoms_list_to_spec(atoms_list: List[Tuple[str, Tuple[float, float, float]]]) -> str:
    """Convert [(symbol, (x, y, z)), ...] to PySCF atom-spec string."""
    lines = []
    for sym, (x, y, z) in atoms_list:
        lines.append(f"{sym} {x:.8f} {y:.8f} {z:.8f}")
    return "\n".join(lines)

def _iter_structure_libraries() -> Iterable[Mapping[str, str]]:
    candidate_names = ["BUILTIN_XYZ_LIBRARY", "XYZ_LIBRARY", "XYZ_LIBRARY_DATA", "STRUCTURE_LIBRARY", "MOLECULE_LIBRARY"]
    seen: set = set()
    for name in candidate_names:
        lib = globals().get(name)
        if isinstance(lib, Mapping) and id(lib) not in seen:
            seen.add(id(lib))
            yield lib

def _lookup_builtin_xyz(query: Optional[str]) -> Optional[Tuple[str, str]]:
    if not query:
        return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)

    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges",
             "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\b{re.escape(n)}\b", " ", qc, flags=re.I)
    qc = re.sub(r"\s+", " ", qc).strip()

    candidates = unique([q0, qn, qc, qn.replace(" ", "_"), qn.replace(" ", ""),
                         qc.replace(" ", "_"), qc.replace(" ", "")])

    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
        for kn_key, pair in normalized_map.items():
            if len(kn_key) > 2 and (kn_key in qn or kn_key in qc):
                return pair
    return None

def _resolve_structure_payload(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    # FIX(M4): atoms_list support
    atoms_list: Optional[List[Tuple[str, Tuple[float, float, float]]]] = None,
) -> Tuple[str, str]:
    """Resolve structure input to (name, atom_text).

    # FIX(M4): Now accepts atoms_list [(sym,(x,y,z))] in addition to xyz/atom_spec.
    """
    # FIX(M4): atoms_list takes priority
    if atoms_list:
        atom_text = _atoms_list_to_spec(atoms_list)
        return _safe_str(structure_query, "custom"), atom_text

    if atom_spec and _safe_str(atom_spec):
        return _safe_str(structure_query, "custom"), _safe_str(atom_spec).strip()

    if xyz and _safe_str(xyz):
        atom_text = _strip_xyz_header(_safe_str(xyz))
        if atom_text:
            return _safe_str(structure_query, "custom"), atom_text

    if structure_query and _looks_like_xyz(structure_query):
        atom_text = _strip_xyz_header(_safe_str(structure_query))
        if atom_text:
            return "custom", atom_text

    if structure_query:
        hit = _lookup_builtin_xyz(structure_query)
        if hit:
            label, xyz_text = hit
            atom_text = _strip_xyz_header(xyz_text)
            return label, atom_text

        # Apply chemistry abbreviation lookup before resolver
        _resolve_query = structure_query
        try:
            from qcviz_mcp.services.structure_resolver import CHEM_ABBREVIATIONS
            abbrev_key = _resolve_query.lower().strip()
            if abbrev_key in CHEM_ABBREVIATIONS:
                _resolve_query = CHEM_ABBREVIATIONS[abbrev_key]
                logger.info("Abbreviation '%s' → '%s'", structure_query, _resolve_query)
        except ImportError:
            pass

        # FIX(M4): Try MoleculeResolver if available (backward compat with tools/core.py)
        resolve_error = None
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(_resolve_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except ImportError:
            pass
        except Exception as e:
            resolve_error = e

        if resolve_error:
            raise ValueError(
                f"'{structure_query}' 구조를 해석할 수 없습니다: {resolve_error} / "
                f"Could not resolve structure '{structure_query}': {resolve_error}"
            ) from resolve_error

    raise ValueError(
        "구조를 확인할 수 없습니다. 쿼리, XYZ, 또는 atom-spec을 제공하세요. / "
        "No structure could be resolved; provide query, XYZ, or atom-spec text."
    )

def _mol_to_xyz(mol: gto.Mole, comment: str = "") -> str:
    coords = mol.atom_coords(unit="Angstrom")
    lines = [str(mol.natm), comment or "QCViz-MCP"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        x, y, z = coords[i]
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    return "\n".join(lines)

def _build_mol(
    atom_text: str,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    unit: str = "Angstrom",
) -> gto.Mole:
    basis_name = _normalize_basis_name(basis or DEFAULT_BASIS)
    spin = max(int(multiplicity or 1) - 1, 0)
    return gto.M(
        atom=atom_text,
        basis=basis_name,
        charge=int(charge or 0),
        spin=spin,
        unit=unit,
        verbose=0,
    )

def _build_mean_field(mol: gto.Mole, method: Optional[str] = None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))
    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf
    xc_map = {
        "b3lyp": "b3lyp", "pbe": "pbe", "pbe0": "pbe0", "m06-2x": "m06-2x",
        "m062x": "m06-2x", "wb97x-d": "wb97x-d", "bp86": "bp86", "blyp": "blyp",
    }
    xc = xc_map.get(key)
    if xc is None:
        xc = key
        logger.warning("Method '%s' not predefined; using '%s' directly.", method_name, key)
    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass
    return method_name, mf

# ── SCF Cache ────────────────────────────────────────────────

try:
    from qcviz_mcp.compute.disk_cache import save_to_disk, load_from_disk
except ImportError:
    def save_to_disk(*a: Any, **kw: Any) -> None: pass  # type: ignore
    def load_from_disk(*a: Any, **kw: Any) -> Tuple[None, None]: return None, None  # type: ignore

_SCF_CACHE: Dict[str, Any] = {}
_SCF_CACHE_LOCK = threading.Lock()
_CANCEL_FLAGS: Dict[str, bool] = {}  # job cancellation flags

def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode("utf-8")).hexdigest()

def _run_scf_with_fallback(mf: Any, warnings: Optional[List[str]] = None, cache_key: Optional[str] = None, progress_callback: Optional[Callable] = None) -> Tuple[Any, float]:
    warnings = warnings if warnings is not None else []
    current_mol = getattr(mf, "mol", None)

    if cache_key:
        with _SCF_CACHE_LOCK:
            if cache_key in _SCF_CACHE:
                cached_mf, cached_energy = _SCF_CACHE[cache_key]
                if current_mol is not None:
                    cached_mf.mol = current_mol
                if progress_callback:
                    _emit_progress(progress_callback, 0.5, "scf", "Cache hit: SCF skipped (0.0s)")
                return cached_mf, cached_energy
        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            if current_mol is not None:
                disk_mf.mol = current_mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Disk cache hit (0.0s)")
            return disk_mf, disk_energy

    try:
        mf.conv_tol = min(getattr(mf, "conv_tol", 1e-9), 1e-9)
    except Exception:
        pass
    try:
        mf.max_cycle = max(int(getattr(mf, "max_cycle", 50)), 100)
    except Exception:
        pass

    cycle_count = [0]
    prev_energy = [None]
    scf_history = []  # list of {cycle, energy, dE}

    def _scf_callback(env: Dict[str, Any]) -> None:
        try:
            cycle_count[0] += 1
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0)

            # Compute dE (energy change from previous cycle)
            dE = None
            if prev_energy[0] is not None:
                dE = e - prev_energy[0]
            prev_energy[0] = e

            # Build history entry
            entry = {"cycle": c, "energy": round(e, 10)}
            if dE is not None:
                entry["dE"] = round(dE, 12)
            scf_history.append(entry)

            # Check cancel flag
            if cache_key and cache_key in _CANCEL_FLAGS:
                del _CANCEL_FLAGS[cache_key]
                raise KeyboardInterrupt("Job cancelled by user")

            if progress_callback:
                pct = min(0.60, 0.35 + (c / 100.0) * 0.25)
                dE_str = f" dE={dE:+.2e}" if dE is not None else ""
                msg = f"SCF iteration {c}/{max_c} (E={e:.6f} Ha{dE_str})"
                _emit_progress(progress_callback, pct, "scf", msg,
                               scf_cycle=c, scf_energy=e, scf_dE=dE,
                               scf_max_cycle=max_c if isinstance(max_c, int) else 100,
                               scf_history=scf_history[-20:])  # last 20 for chart
        except KeyboardInterrupt:
            raise
        except Exception:
            pass

    try:
        mf.callback = _scf_callback
    except Exception:
        pass

    t0 = time.time()
    energy = mf.kernel()
    t1 = time.time()
    elapsed = t1 - t0
    cycles = cycle_count[0]

    if getattr(mf, "converged", False):
        if progress_callback:
            _emit_progress(progress_callback, 0.60, "scf", f"SCF converged in {cycles} cycles ({elapsed:.1f}s)")
        if cache_key:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
        return mf, energy

    warnings.append(f"Primary SCF did not converge after {cycles} cycles; attempting Newton refinement.")
    if progress_callback:
        _emit_progress(progress_callback, 0.60, "scf", "Primary SCF failed; starting Newton refinement")

    try:
        mf = mf.newton()
        energy = mf.kernel()
        t2 = time.time()
        if progress_callback:
            _emit_progress(progress_callback, 0.65, "scf", f"Newton refinement finished ({t2 - t1:.1f}s)")
        if cache_key and getattr(mf, "converged", False):
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
    except Exception as exc:
        warnings.append(f"Newton refinement failed: {exc}")

    return mf, energy

# ── File / cube helpers ──────────────────────────────────────

def _file_to_b64(path: Union[str, Path, None]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")

def _parse_cube_values(path: Union[str, Path]) -> np.ndarray:
    p = Path(path)
    text = p.read_text(errors="ignore").splitlines()
    if len(text) < 7:
        return np.array([], dtype=float)
    try:
        natm = abs(int(text[2].split()[0]))
        data_start = 6 + natm
    except Exception:
        data_start = 6
    values: List[float] = []
    for line in text[data_start:]:
        for token in line.split():
            try:
                values.append(float(token))
            except Exception:
                continue
    return np.asarray(values, dtype=float)

def _nice_symmetric_limit(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.05
    if value < 0.02:
        step = 0.0025
    elif value < 0.05:
        step = 0.005
    elif value < 0.10:
        step = 0.010
    else:
        step = 0.020
    return float(math.ceil(value / step) * step)

def _compute_esp_auto_range(
    esp_values: np.ndarray,
    density_values: Optional[np.ndarray] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    arr = np.asarray(esp_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        default_au = ESP_PRESETS_DATA["acs"]["default_range_au"]
        return {"range_au": default_au, "range_kcal": default_au * HARTREE_TO_KCAL, "stats": {}, "strategy": "default"}

    masked = arr
    if density_values is not None:
        dens_raw = np.asarray(density_values, dtype=float).ravel()
        esp_raw = np.asarray(esp_values, dtype=float).ravel()
        if dens_raw.size == esp_raw.size:
            finite_mask = np.isfinite(dens_raw) & np.isfinite(esp_raw)
            if np.count_nonzero(finite_mask) >= 128:
                low = density_iso * 0.35
                high = density_iso * 4.0
                shell_mask = finite_mask & (dens_raw >= low) & (dens_raw <= high)
                if np.count_nonzero(shell_mask) >= 128:
                    masked = esp_raw[shell_mask]

    masked = masked[np.isfinite(masked)] if not np.all(np.isfinite(masked)) else masked
    if masked.size < 32:
        masked = arr

    abs_vals = np.abs(masked)
    p90 = float(np.percentile(abs_vals, 90))
    p95 = float(np.percentile(abs_vals, 95))
    p98 = float(np.percentile(abs_vals, 98))
    p995 = float(np.percentile(abs_vals, 99.5))
    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995
    dynamic_upper = max(0.18, min(float(p995) * 1.2, 0.50))
    robust = float(np.clip(robust, 0.02, dynamic_upper))

# ... (truncated at 600 lines, 984 lines omitted) ...
```

---

## 📄 `compute/job_manager.py` (202 lines)

```python
"""Progress-aware in-process JobManager for QCViz.

# FIX(M5): RLock 확인, atomic file write (tmp→rename), shallow copy 반환
기존 인터페이스 전부 유지.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class JobEvent:
    """A lightweight event emitted during job execution."""
    job_id: str
    timestamp: float
    level: str = "info"
    message: str = ""
    step: str = ""
    detail: str = ""
    progress: float = 0.0
    payload: Optional[Dict[str, Any]] = None

@dataclass
class JobRecord:
    """Serializable public job record."""
    job_id: str
    name: str
    label: str
    status: str = "queued"
    progress: float = 0.0
    step: str = ""
    detail: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    cancel_requested: bool = False

class JobCancelledError(RuntimeError):
    """Raised when a running job cooperatively acknowledges cancellation."""

class JobManager:
    """Thread-based job manager with progress and event buffering.

    # FIX(M5): RLock 사용 확인, atomic writes, shallow copy snapshots
    """

    def __init__(self, max_workers: Optional[int] = None, max_events_per_job: int = 300) -> None:
        cpu = os.cpu_count() or 2
        self._max_workers = max_workers or max(2, min(4, cpu))
        self._max_events_per_job = max(50, int(max_events_per_job))

        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="qcviz-job")

        # FIX(M5): RLock for reentrant locking
        self._lock = threading.RLock()
        self._records: Dict[str, JobRecord] = {}
        self._futures: Dict[str, Future] = {}
        self._events: Dict[str, List[JobEvent]] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}

        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s)", self._max_workers)

    # ── Public API ────────────────────────────────────────────

    def submit(self, target: Optional[Callable[..., Any]] = None, kwargs: Optional[Dict[str, Any]] = None,
               label: Optional[str] = None, name: Optional[str] = None,
               func: Optional[Callable[..., Any]] = None) -> str:
        callable_obj = target or func
        if callable_obj is None or not callable(callable_obj):
            raise ValueError("submit() requires a callable target/func")

        job_id = self._new_job_id()
        job_name = str(name or label or getattr(callable_obj, "__name__", "job")).strip() or "job"

        record = JobRecord(job_id=job_id, name=job_name, label=str(label or job_name),
                           status="queued", progress=0.0, step="queued", detail="Job queued")

        with self._lock:
            self._records[job_id] = record
            self._events[job_id] = []
            self._cancel_flags[job_id] = threading.Event()

        self._append_event(job_id, level="info", message="Job queued", step="queued", detail=record.detail)

        future = self._executor.submit(self._run_job, job_id, callable_obj, dict(kwargs or {}))
        with self._lock:
            self._futures[job_id] = future
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            # FIX(M5): shallow copy via asdict for thread safety
            return self._record_to_dict(record)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.get(job_id)

    def get_record(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return JobRecord(**asdict(record))

    def list_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            records = [self._record_to_dict(rec) for rec in self._records.values()]
        records.sort(key=lambda x: x.get("created_at", 0.0), reverse=True)
        if limit is not None:
            return records[:max(0, int(limit))]
        return records

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._records.get(job_id)
            future = self._futures.get(job_id)
            cancel_flag = self._cancel_flags.get(job_id)

        if record is None:
            return {"ok": False, "job_id": job_id, "status": "missing", "message": "job not found"}

        if cancel_flag is not None:
            cancel_flag.set()

        self._update_record(job_id, cancel_requested=True, detail="Cancellation requested")
        self._append_event(job_id, level="warning", message="Cancellation requested",
                           step="cancellation_requested", detail="Cancellation requested by user",
                           progress=self._get_progress(job_id))

        if future is not None and future.cancel():
            self._finalize_cancelled(job_id, detail="Cancelled before execution")
            return {"ok": True, "job_id": job_id, "status": "cancelled", "message": "job cancelled before execution"}

        return {"ok": True, "job_id": job_id, "status": "cancellation_requested", "message": "cancellation requested"}

    def drain_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            events = self._events.get(job_id, [])
            data = [asdict(ev) for ev in events]
            if clear:
                self._events[job_id] = []
        return data

    def pop_events(self, job_id: str) -> List[Dict[str, Any]]:
        return self.drain_events(job_id, clear=True)

    def get_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        return self.drain_events(job_id, clear=clear)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            future = self._futures.get(job_id)
        if future is None:
            return self.get(job_id)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            raise
        except Exception:
            pass
        return self.get(job_id)

    async def async_wait(self, job_id: str, timeout: Optional[float] = None, poll_interval: float = 0.2) -> Optional[Dict[str, Any]]:
        start = time.time()
        while True:
            record = self.get(job_id)
            if record is None:
                return None
            if record.get("status") in {"success", "error", "cancelled"}:
                return record
            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError(f"Timed out waiting for job {job_id}")
            await asyncio.sleep(poll_interval)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        logger.info("Shutting down JobManager (wait=%s, cancel_futures=%s)", wait, cancel_futures)
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    # ── Internal ──────────────────────────────────────────────

    def _run_job(self, job_id: str, target: Callable[..., Any], kwargs: Dict[str, Any]) -> None:
        self._mark_running(job_id)

# ... (truncated at 200 lines, 186 lines omitted) ...
```

---

## 📄 `web/routes/chat.py` (502 lines)

```python
"""Chat routes — HTTP POST + WebSocket with Gemini agent integration.

# FIX(M3): Gemini agent 연동, keepalive (25s ping, 60s timeout), cleanup
"""
from __future__ import annotations

import asyncio
import json
import re
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect

from qcviz_mcp.web.routes.compute import (
    TERMINAL_FAILURE,
    TERMINAL_STATES,
    _extract_message,
    _extract_session_id,
    _merge_plan_into_payload,
    _prepare_payload,
    _public_plan_dict,
    _safe_plan_message,
    get_job_manager,
)

# FIX(M3): ko_aliases for follow-up structure detection
try:
    from qcviz_mcp.services.ko_aliases import translate as ko_translate, find_molecule_name
except ImportError:
    def ko_translate(t: str) -> str: return t  # type: ignore
    def find_molecule_name(t: str) -> Optional[str]: return None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter()

WS_POLL_SECONDS = float(os.getenv("QCVIZ_WS_POLL_SECONDS", "0.25"))
# FIX(M3): keepalive settings
WS_PING_INTERVAL = float(os.getenv("QCVIZ_WS_PING_INTERVAL", "25"))
WS_TIMEOUT = float(os.getenv("QCVIZ_WS_TIMEOUT", "60"))

def _now_ts() -> float:
    return time.time()

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)

def _parse_client_message(text: str) -> Dict[str, Any]:
    raw = _safe_str(text)
    if not raw:
        return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"message": raw}

def _plan_status_message(plan: Optional[Mapping[str, Any]], payload: Optional[Mapping[str, Any]] = None) -> str:
    plan = dict(plan or {})
    payload = dict(payload or {})
    job_type = _safe_str(payload.get("job_type") or plan.get("job_type") or "analyze")
    structure = _safe_str(payload.get("structure_query") or plan.get("structure_query"))
    method = _safe_str(payload.get("method") or plan.get("method"))
    basis = _safe_str(payload.get("basis") or plan.get("basis"))
    orbital = _safe_str(payload.get("orbital") or plan.get("orbital"))
    esp_preset = _safe_str(payload.get("esp_preset") or plan.get("esp_preset"))
    confidence = plan.get("confidence")
    provider = plan.get("provider", "")

    parts = [f"Plan: {job_type}"]
    if structure:
        parts.append(f"structure={structure}")
    if method:
        parts.append(f"method={method}")
    if basis:
        parts.append(f"basis={basis}")
    if orbital and job_type in {"orbital_preview", "analyze"}:
        parts.append(f"orbital={orbital}")
    if esp_preset and job_type in {"esp_map", "analyze"}:
        parts.append(f"esp_preset={esp_preset}")
    if confidence is not None:
        try:
            parts.append(f"confidence={float(confidence):.2f}")
        except Exception:
            parts.append(f"confidence={confidence}")
    if provider:
        parts.append(f"via={provider}")
    return " | ".join(parts)

def _result_summary(result: Optional[Mapping[str, Any]]) -> str:
    if not result:
        return "Job completed."
    structure = _safe_str(result.get("structure_name") or result.get("structure_query") or "molecule")
    job_type = _safe_str(result.get("job_type") or "calculation")
    energy = result.get("total_energy_hartree")
    gap = result.get("orbital_gap_ev")
    parts = [f"{job_type} completed for {structure}"]
    if energy is not None:
        try:
            parts.append(f"E={float(energy):.8f} Ha")
        except Exception:
            pass
    if gap is not None:
        try:
            parts.append(f"gap={float(gap):.3f} eV")
        except Exception:
            pass
    return " | ".join(parts)

# FIX(M3): Detect follow-up molecule queries
def _detect_follow_up_molecule(message: str) -> Optional[str]:
    """Check if message references a molecule from Korean aliases or common names."""
    if not message:
        return None
    # Try Korean alias lookup
    mol = find_molecule_name(message)
    if mol:
        return mol
    # Check for common English molecule names
    common = [
        "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
        "formaldehyde", "caffeine", "aspirin", "glucose", "urea",
    ]
    lower = message.lower()
    for name in common:
        if name in lower:
            return name
    return None

# ─── Clarification Flow helpers ────────────────────────
CONFIDENCE_THRESHOLD = 0.75

def _detect_ambiguity(plan: Dict[str, Any], prepared: Dict[str, Any], raw_message: str) -> List[str]:
    """Return list of ambiguity reasons, or empty if plan is clear."""
    reasons = []
    confidence = float(plan.get("confidence", 0.0))
    query = prepared.get("structure_query", "") or ""
    msg_lower = (raw_message or "").lower()

    # Low confidence
    if confidence < CONFIDENCE_THRESHOLD:
        reasons.append("low_confidence")

    # Multiple molecule names (space-separated tokens with uppercase)
    tokens = [t for t in query.split() if len(t) > 1]
    if len(tokens) >= 2 and not any(c in query for c in "+-"):
        reasons.append("multiple_molecules")

    # Ion indicators without explicit charge
    if re.search(r'[A-Za-z]\+|[A-Za-z]-', query):
        if prepared.get("charge") is None:
            reasons.append("ion_charge_unclear")

    # No structure detected or structure_query is not a valid molecule name
    if not query and not prepared.get("xyz") and not prepared.get("atom_spec"):
        reasons.append("no_structure")
    elif query and not _looks_like_molecule(query):
        reasons.append("no_structure")

    return reasons

def _looks_like_molecule(query: str) -> bool:
    """Check if the query looks like a valid molecule name (vs Korean task text)."""
    if not query:
        return False
    # Contains significant Korean text → probably not a molecule name
    korean_chars = sum(1 for c in query if '\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163')
    if korean_chars > len(query) * 0.3:
        return False
    # Known molecule patterns: single English word, formula, SMILES
    if re.match(r'^[A-Za-z][A-Za-z0-9()\[\]\-+.,\s#=\\/]*$', query.strip()):
        return True
    # Contains chemical formula patterns (e.g., C2H5OH, CH4)
    if re.match(r'^[A-Z][a-z]?\d*', query.strip()):
        return True
    return False

def _build_clarification_fields(reasons: List[str], plan: Dict[str, Any],
                                prepared: Dict[str, Any], raw_message: str) -> List[Dict[str, Any]]:
    """Build form fields for user clarification."""
    fields = []
    query = prepared.get("structure_query", "") or raw_message or ""

    if "multiple_molecules" in reasons:
        fields.append({
            "id": "ion_pair",
            "type": "radio",
            "label": f"'{query}'은(는) 이온쌍인가요? / Is this an ion pair?",
            "options": [
                {"value": "ion_pair", "label": "이온쌍 (Ion pair, e.g. EMIM+ TFSI-)"},
                {"value": "neutral", "label": "중성 분자 (Neutral molecule)"},
                {"value": "separate", "label": "각각 따로 계산 (Compute separately)"},
            ],
            "default": "ion_pair",
        })

    if "ion_charge_unclear" in reasons or "multiple_molecules" in reasons:
        fields.append({
            "id": "charge",
            "type": "number",
            "label": "전체 전하 / Total charge",
            "default": 0,
        })
        fields.append({
            "id": "multiplicity",
            "type": "number",
            "label": "스핀 다중도 / Spin multiplicity",
            "default": 1,
        })

    if "no_structure" in reasons:
        # Use Gemini to suggest molecules matching the user's description
        from qcviz_mcp.web.routes.compute import get_qcviz_agent
        agent = get_qcviz_agent()
        suggestions = []
        if agent and hasattr(agent, 'suggest_molecules'):
            try:
                suggestions = agent.suggest_molecules(raw_message)
            except Exception:
                pass

        options = []
        default_val = None
        for s in suggestions:
            name = s.get("name", "")
            desc = s.get("description", name)
            formula = s.get("formula", "")
            label = f"{desc} ({formula})" if formula else desc
            options.append({"value": name, "label": label})
            if default_val is None:
                default_val = name

        if not options:
            # Fallback hardcoded options
            options = [
                {"value": "methane", "label": "메탄 (CH4, 5 atoms)"},
                {"value": "water", "label": "물 (H2O, 3 atoms)"},
                {"value": "ethanol", "label": "에탄올 (C2H5OH, 9 atoms)"},
            ]
            default_val = "methane"

        options.append({"value": "custom", "label": "직접 입력 (Custom)"})

        fields.insert(0, {
            "id": "structure",
            "type": "radio",
            "label": "Gemini 추천 분자 / Suggested molecules:",
            "options": options,
            "default": default_val,
        })
        fields.insert(1, {
            "id": "structure_custom",
            "type": "text",
            "label": "직접 입력 (Custom molecule name or SMILES)",
            "placeholder": "예: acetone, C3H6O, CC(=O)C",
        })

    # Always offer method/basis selection
    fields.append({
        "id": "method",
        "type": "select",
        "label": "계산 방법 / Method",
        "options": [
            {"value": "B3LYP", "label": "B3LYP (추천)"},
            {"value": "HF", "label": "HF (빠름)"},
            {"value": "PBE", "label": "PBE"},
            {"value": "M06-2X", "label": "M06-2X"},
        ],
        "default": prepared.get("method", "B3LYP"),
    })
    fields.append({
        "id": "basis",
        "type": "select",
        "label": "기저함수 / Basis set",
        "options": [
            {"value": "def2-SVP", "label": "def2-SVP (추천)"},
            {"value": "STO-3G", "label": "STO-3G (빠름)"},
            {"value": "6-31G*", "label": "6-31G*"},
            {"value": "cc-pVDZ", "label": "cc-pVDZ"},
            {"value": "def2-TZVP", "label": "def2-TZVP (정밀)"},
        ],
        "default": prepared.get("basis", "def2-SVP"),
    })
    fields.append({
        "id": "job_type",
        "type": "select",
        "label": "계산 유형 / Calculation type",
        "options": [
            {"value": "single_point", "label": "에너지 계산 (Single point)"},
            {"value": "geometry_optimization", "label": "구조 최적화 (Optimization)"},
            {"value": "orbital_preview", "label": "오비탈 시각화 (Orbital)"},
            {"value": "esp_map", "label": "정전기 전위 (ESP map)"},
        ],
        "default": prepared.get("job_type", "single_point"),
    })

    return fields

def _summarize_plan_for_confirm(prepared: Dict[str, Any]) -> str:
    """Human-readable summary of computation plan."""
    parts = []
    q = prepared.get("structure_query") or prepared.get("structure_name") or "unknown"
    jt = prepared.get("job_type", "single_point")
    m = prepared.get("method", "B3LYP")
    b = prepared.get("basis", "def2-SVP")
    ch = prepared.get("charge", 0)
    mult = prepared.get("multiplicity", 1)

    jt_labels = {
        "single_point": "에너지 계산",
        "geometry_optimization": "구조 최적화",
        "orbital_preview": "오비탈 시각화",
        "esp_map": "ESP 맵",
        "partial_charges": "부분 전하",
    }
    jt_label = jt_labels.get(jt, jt)

    parts.append(f"🧪 **{q}**")
    parts.append(f"📐 {jt_label} | {m}/{b}")
    parts.append(f"⚡ charge={ch}, multiplicity={mult}")
    return "\n".join(parts)

async def _ws_send(websocket: WebSocket, event_type: str, **payload: Any) -> None:
    body = {"type": event_type, **_json_safe(payload)}
    await websocket.send_json(body)

async def _ws_send_error(
    websocket: WebSocket, *,
    message: str, detail: Optional[Any] = None,
    status_code: int = 400, session_id: Optional[str] = None,
) -> None:
    error_obj = {
        "message": _safe_str(message, "Request failed"),
        "detail": _json_safe(detail),
        "status_code": status_code,
        "timestamp": _now_ts(),
    }
    await _ws_send(websocket, "error", session_id=session_id, error=error_obj)

async def _stream_backend_job_until_terminal(
    websocket: WebSocket, *, job_id: str, session_id: str,
) -> None:
    manager = get_job_manager()
    seen_event_ids: set = set()
    last_state = None

    while True:
        snap = manager.get(job_id, include_result=False, include_events=True)
        if snap is None:
            await _ws_send_error(websocket, message="Job not found while streaming.", status_code=404, session_id=session_id)
            return

        state_key = (snap.get("status"), snap.get("progress"), snap.get("step"), snap.get("message"))
        if state_key != last_state:
            await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                           status=snap.get("status"), progress=snap.get("progress"),
                           step=snap.get("step"), message=snap.get("message"), job=snap)
            last_state = state_key

        for event in snap.get("events", []) or []:
            event_id = event.get("event_id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            event_type = event.get("type", "")

            if event_type == "job_progress":
                data = event.get("data") or {}
                # Include SCF convergence data if present
                scf_kwargs = {}
                for k in ("scf_history", "scf_dE", "scf_cycle", "scf_energy", "scf_max_cycle"):
                    if k in data:
                        scf_kwargs[k] = data[k]
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running", progress=data.get("progress", 0.0),
                               step=data.get("step", ""), message=event.get("message", ""),
                               **scf_kwargs)
                continue
            if event_type in ("job_started", "job_completed"):
                await _ws_send(websocket, "job_update", session_id=session_id, job_id=job_id,
                               status="running" if event_type == "job_started" else "completed",
                               step=event_type, message=event.get("message", ""))
                continue
            await _ws_send(websocket, "job_event", session_id=session_id, job_id=job_id, event=event)

        if snap.get("status") in TERMINAL_STATES:
            terminal = manager.get(job_id, include_result=True, include_events=True)
            if terminal is None:
                await _ws_send_error(websocket, message="Job disappeared.", status_code=404, session_id=session_id)
                return
            if terminal.get("status") in TERMINAL_FAILURE:
                await _ws_send_error(
                    websocket,
                    message=((terminal.get("error") or {}).get("message") or terminal.get("message") or "Job failed."),
                    detail=terminal.get("error"),
                    status_code=int(((terminal.get("error") or {}).get("status_code")) or 500),
                    session_id=session_id,
                )
                return
            result = terminal.get("result") or {}
            await _ws_send(websocket, "result", session_id=session_id, job=terminal,
                           result=result, summary=_result_summary(result))
            return

        await asyncio.sleep(WS_POLL_SECONDS)

@router.get("/chat/health")
def chat_health() -> Dict[str, Any]:
    manager = get_job_manager()
    return {"ok": True, "route": "/chat", "ws_route": "/ws/chat",
            "job_backend": manager.__class__.__name__, "timestamp": _now_ts()}

@router.post("/chat")
def post_chat(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    raw_message = _extract_message(body)

    plan = _safe_plan_message(raw_message, body) if raw_message else {}
    merged = _merge_plan_into_payload(body, plan, raw_message=raw_message)
    prepared = _prepare_payload(merged)
    plan_message = _plan_status_message(plan, prepared)

    manager = get_job_manager()
    submitted = manager.submit(prepared)

    should_wait = bool(wait or wait_for_result or body.get("wait") or body.get("wait_for_result") or body.get("sync"))
    if should_wait:
        terminal = manager.wait(submitted["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        ok = terminal.get("status") not in TERMINAL_FAILURE
        return {
            "ok": ok, "message": plan_message, "plan": _public_plan_dict(plan),
            "job": terminal, "result": terminal.get("result"), "error": terminal.get("error"),
            "summary": _result_summary(terminal.get("result") or {}),
        }

    return {"ok": True, "message": plan_message, "plan": _public_plan_dict(plan), "job": submitted}

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    default_session_id = f"ws-{int(_now_ts() * 1000)}"
    session_state: Dict[str, Any] = {"last_molecule": None}

    await _ws_send(websocket, "ready", session_id=default_session_id,
                   message="QCViz chat websocket connected.", timestamp=_now_ts())

    # FIX(M3): keepalive ping task
    async def _keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(WS_PING_INTERVAL)
                try:
                    await websocket.send_json({"type": "ping", "ts": _now_ts()})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_keepalive())

    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # FIX(M3): send ping on timeout, don't disconnect
                try:
                    await websocket.send_json({"type": "ping", "ts": _now_ts()})
                except Exception:
                    break
                continue


# ... (truncated at 500 lines, 265 lines omitted) ...
```

---

## 📄 `web/routes/compute.py` (702 lines)

```python
"""Compute routes — job submission, status, results.

# FIX(M2): 가짜 resolver 삭제, structure_resolver.resolve() 교체,
#          이온쌍 감지 → ion_pair_handler 위임, LRU 캐시, 이중 언어 에러
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner

# FIX(M2): 새 서비스 모듈 import
try:
    from qcviz_mcp.services.structure_resolver import StructureResolver, StructureResult
    from qcviz_mcp.services.ion_pair_handler import is_ion_pair, resolve_ion_pair, IonPairResult, expand_alias
    from qcviz_mcp.services.molchat_client import MolChatClient
    from qcviz_mcp.services.pubchem_client import PubChemClient
    from qcviz_mcp.services.ko_aliases import translate as ko_translate
except ImportError as _imp_err:
    logging.getLogger(__name__).warning("services import failed: %s", _imp_err)
    StructureResolver = None  # type: ignore
    StructureResult = None  # type: ignore

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:
    QCVizAgent = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])

# ── Intent / job type mappings ────────────────────────────────

INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "analyze": "analyze",
    "full_analysis": "analyze",
    "single_point": "single_point",
    "energy": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "optimize": "geometry_optimization",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_ALIASES: Dict[str, str] = {
    "analyze": "analyze", "analysis": "analyze", "full_analysis": "analyze",
    "singlepoint": "single_point", "single_point": "single_point", "sp": "single_point",
    "geometry": "geometry_analysis", "geometry_analysis": "geometry_analysis", "geom": "geometry_analysis",
    "charge": "partial_charges", "charges": "partial_charges", "partial_charges": "partial_charges",
    "mulliken": "partial_charges",
    "orbital": "orbital_preview", "orbital_preview": "orbital_preview", "mo": "orbital_preview",
    "esp": "esp_map", "esp_map": "esp_map", "electrostatic_potential": "esp_map",
    "opt": "geometry_optimization", "optimize": "geometry_optimization",
    "optimization": "geometry_optimization", "geometry_optimization": "geometry_optimization",
    "resolve": "resolve_structure", "resolve_structure": "resolve_structure", "structure": "resolve_structure",
}

JOB_TYPE_TO_RUNNER: Dict[str, str] = {
    "analyze": "run_analyze",
    "single_point": "run_single_point",
    "geometry_analysis": "run_geometry_analysis",
    "partial_charges": "run_partial_charges",
    "orbital_preview": "run_orbital_preview",
    "esp_map": "run_esp_map",
    "geometry_optimization": "run_geometry_optimization",
    "resolve_structure": "run_resolve_structure",
}

TERMINAL_SUCCESS = {"completed"}
TERMINAL_FAILURE = {"failed", "error"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE

DEFAULT_POLL_SECONDS = float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25"))
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "4"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

# FIX(M2): LRU structure resolution cache
_STRUCTURE_CACHE: OrderedDict[str, Any] = OrderedDict()
_STRUCTURE_CACHE_LOCK = threading.Lock()
_STRUCTURE_CACHE_MAX = int(os.getenv("SCF_CACHE_MAX_SIZE", "256"))

# FIX(M2): Singleton resolver instances
_resolver_instance: Optional[Any] = None
_resolver_lock = threading.Lock()

def _get_resolver() -> Any:
    """Get or create singleton StructureResolver."""
    global _resolver_instance
    if _resolver_instance is not None:
        return _resolver_instance
    with _resolver_lock:
        if _resolver_instance is None and StructureResolver is not None:
            _resolver_instance = StructureResolver()
    return _resolver_instance

def _structure_cache_get(key: str) -> Optional[Any]:
    with _STRUCTURE_CACHE_LOCK:
        if key in _STRUCTURE_CACHE:
            _STRUCTURE_CACHE.move_to_end(key)
            return _STRUCTURE_CACHE[key]
    return None

def _structure_cache_put(key: str, value: Any) -> None:
    with _STRUCTURE_CACHE_LOCK:
        if key in _STRUCTURE_CACHE:
            _STRUCTURE_CACHE.move_to_end(key)
        _STRUCTURE_CACHE[key] = value
        while len(_STRUCTURE_CACHE) > _STRUCTURE_CACHE_MAX:
            _STRUCTURE_CACHE.popitem(last=False)

# ── Regex patterns for heuristic extraction ───────────────────

_METHOD_PAT = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|bp86|blyp|mp2|ccsd)\b",
    re.IGNORECASE,
)
_BASIS_PAT = re.compile(
    r"\b(sto-?3g|3-21g|6-31g\*{0,2}|6-31g\(d(?:,p)?\)|6-311g\*{0,2}|def2-?svp|def2-?tzvp|cc-pv[dt]z|aug-cc-pv[dt]z)\b",
    re.IGNORECASE,
)
_CHARGE_PAT = re.compile(r"(?:charge|전하)\s*[:=]?\s*([+-]?\d+)", re.IGNORECASE)
_MULT_PAT = re.compile(r"(?:multiplicity|spin multiplicity|다중도)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_ORBITAL_PAT = re.compile(
    r"\b(homo(?:\s*-\s*\d+)?|lumo(?:\s*\+\s*\d+)?|mo\s*\d+)\b",
    re.IGNORECASE,
)
_ESP_PRESET_PAT = re.compile(
    r"\b(acs|rsc|nature|spectral|inferno|viridis|rwb|bwr|greyscale|grayscale|high[_ -]?contrast)\b",
    re.IGNORECASE,
)

# ── Utility functions ────────────────────────────────────────

def _now_ts() -> float:
    return time.time()

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default

def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    try:
        import numpy as np
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            return None if not math.isfinite(v) else v
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, np.ndarray):
            return _json_safe(value.tolist())
    except ImportError:
        pass
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)

def _public_plan_dict(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    return {
        "intent": out.get("intent"),
        "confidence": out.get("confidence"),
        "provider": out.get("provider"),
        "notes": out.get("notes"),
        "job_type": out.get("job_type"),
        "structure_query": out.get("structure_query"),
        "structures": out.get("structures"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
    }

def _normalize_text_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s가-힣+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "user_message", "text", "prompt", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _extract_session_id(payload: Mapping[str, Any]) -> str:
    for key in ("session_id", "conversation_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _normalize_job_type(job_type: Optional[str], intent: Optional[str] = None) -> str:
    jt = _normalize_text_token(job_type).replace(" ", "_")
    if jt in JOB_TYPE_ALIASES:
        return JOB_TYPE_ALIASES[jt]
    intent_key = _normalize_text_token(intent).replace(" ", "_")
    if intent_key in INTENT_TO_JOB_TYPE:
        return INTENT_TO_JOB_TYPE[intent_key]
    return "analyze"

def _normalize_esp_preset(preset: Optional[str]) -> str:
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    if token == "grayscale":
        token = "greyscale"
    if token == "high-contrast":
        token = "high_contrast"
    if token in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}):
        return token
    for key, meta in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}).items():
        aliases = [_normalize_text_token(x).replace(" ", "_") for x in meta.get("aliases", [])]
        if token == key or token in aliases:
            return key
    return "acs"

def _extract_xyz_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    raw = str(text).strip()
    fence = re.search(r"```(?:xyz)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fence:
        block = fence.group(1).strip()
        if block:
            return block
    if "\n" not in raw:
        return None
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    atom_line = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
    if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 3:
        candidate = "\n".join(lines)
        body = lines[2:]
        if body and all(atom_line.match(x.strip()) for x in body):
            return candidate
    atom_lines = [ln for ln in lines if atom_line.match(ln.strip())]
    if len(atom_lines) >= 1 and len(atom_lines) == len(lines):
        return "\n".join(lines)
    return None

# FIX(M2): async structure resolution via new resolver
async def _resolve_structure_async(query: str) -> Dict[str, Any]:
    """Resolve structure query using the new StructureResolver pipeline.

    Returns dict with keys: xyz, smiles, cid, name, source, sdf, molecular_weight.
    """
    cache_key = query.strip().lower()
    cached = _structure_cache_get(cache_key)
    if cached:
        return cached

    resolver = _get_resolver()
    if resolver is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "구조 해석 서비스를 초기화할 수 없습니다 / "
                "Structure resolver service unavailable"
            ),
        )

    try:
        result = await resolver.resolve(query)
        out = {
            "xyz": result.xyz,
            "smiles": result.smiles,
            "cid": result.cid,
            "name": result.name or query,
            "source": result.source,
            "sdf": result.sdf,
            "molecular_weight": result.molecular_weight,
        }
        _structure_cache_put(cache_key, out)
        return out
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Structure resolution failed for: %s", query)
        raise HTTPException(
            status_code=502,
            detail=(
                f"구조 해석 중 오류 발생: {e} / "
                f"Error during structure resolution: {e}"
            ),
        )

# FIX(M2): async ion pair resolution
async def _resolve_ion_pair_async(structures: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve ion pair via ion_pair_handler."""
    resolver = _get_resolver()
    if resolver is None:
        raise HTTPException(status_code=500, detail="Structure resolver unavailable")

    try:
        ion_result = await resolve_ion_pair(
            structures=structures,
            molchat=resolver.molchat,
            pubchem=resolver.pubchem,
            offset=float(os.getenv("ION_OFFSET_ANGSTROM", "5.0")),
        )
        return {
            "xyz": ion_result.xyz,
            "total_charge": ion_result.total_charge,
            "smiles_list": ion_result.smiles_list,
            "names": ion_result.names,
            "source": ion_result.source,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Ion pair resolution failed")
        raise HTTPException(
            status_code=502,
            detail=f"이온쌍 해석 실패: {e} / Ion pair resolution failed: {e}",
        )

def _heuristic_plan(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Heuristic fallback planner (no LLM)."""
    payload = payload or {}
    text = message or _extract_message(payload)
    normalized = _normalize_text_token(text)

    intent = "analyze"
    focus = "summary"

    if re.search(r"\b(homo|lumo|orbital|mo)\b|오비탈", normalized, re.IGNORECASE):
        intent = "orbital"
        focus = "orbital"
    elif re.search(r"\b(esp|electrostatic)\b|정전기|전위", normalized, re.IGNORECASE):
        intent = "esp"
        focus = "esp"
    elif re.search(r"\b(charge|charges|mulliken)\b|전하", normalized, re.IGNORECASE):
        intent = "charges"
        focus = "charges"
    elif re.search(r"\b(opt|optimize|optimization)\b|최적화", normalized, re.IGNORECASE):
        intent = "optimization"
        focus = "geometry"
    elif re.search(r"\b(geometry|bond|angle|dihedral)\b|구조|결합", normalized, re.IGNORECASE):
        intent = "geometry"
        focus = "geometry"
    elif re.search(r"\b(energy|single point|singlepoint)\b|에너지", normalized, re.IGNORECASE):
        intent = "single_point"
        focus = "summary"

    method = None
    basis = None
    charge = None
    multiplicity = None
    orbital = None
    esp_preset = None

    m_method = _METHOD_PAT.search(text)
    if m_method:
        method = m_method.group(1)
    m_basis = _BASIS_PAT.search(text)
    if m_basis:
        basis = m_basis.group(1)
    m_charge = _CHARGE_PAT.search(text)
    if m_charge:
        charge = _safe_int(m_charge.group(1))
    m_mult = _MULT_PAT.search(text)
    if m_mult:
        multiplicity = _safe_int(m_mult.group(1))
    m_orb = _ORBITAL_PAT.search(text)
    if m_orb:
        orbital = m_orb.group(1).upper().replace(" ", "")
    m_preset = _ESP_PRESET_PAT.search(text)
    if m_preset:
        esp_preset = _normalize_esp_preset(m_preset.group(1))

    job_type = _normalize_job_type(payload.get("job_type"), intent)

    return {
        "intent": intent,
        "confidence": 0.55,
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "structure_query": None,  # FIX(M2): resolver handles extraction
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
    }

@lru_cache(maxsize=1)
def get_qcviz_agent():
    if QCVizAgent is None:
        return None
    try:
        return QCVizAgent()
    except Exception as exc:
        logger.warning("QCVizAgent initialization failed: %s", exc)
        return None

def _coerce_plan_to_dict(plan_obj: Any) -> Dict[str, Any]:
    if plan_obj is None:
        return {}
    if isinstance(plan_obj, Mapping):
        return dict(plan_obj)
    out: Dict[str, Any] = {}
    for key in (
        "intent", "confidence", "provider", "notes", "job_type",
        "structure_query", "structures", "method", "basis", "charge",
        "multiplicity", "orbital", "esp_preset", "advisor_focus_tab",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out

def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message))
        except Exception as exc:
            logger.warning("Planner invocation failed; heuristic fallback: %s", exc)
    return _heuristic_plan(message, payload=payload)

def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})

    intent = _safe_str(plan.get("intent"))
    if not out.get("job_type"):
        out["job_type"] = _normalize_job_type(plan.get("job_type"), intent)

    for key in ("method", "basis", "orbital", "advisor_focus_tab"):
        if not out.get(key) and plan.get(key):
            out[key] = plan.get(key)

    for key in ("charge", "multiplicity"):
        if out.get(key) is None and plan.get(key) is not None:
            out[key] = plan.get(key)

    if not out.get("esp_preset") and plan.get("esp_preset"):
        out["esp_preset"] = _normalize_esp_preset(plan.get("esp_preset"))

    # FIX(M2): structure_query and structures from plan
    if not out.get("structure_query") and plan.get("structure_query"):
        out["structure_query"] = plan.get("structure_query")
    if not out.get("structures") and plan.get("structures"):
        out["structures"] = plan.get("structures")

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    # FIX(M2): If still no structure, use raw message as query (resolver will handle it)
    if not out.get("structure_query") and not out.get("xyz") and not out.get("atom_spec") and not out.get("structures"):
        raw = raw_message or _extract_message(out)
        if raw and len(raw.strip()) >= 2:
            out["structure_query"] = raw.strip()

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    return out

def _focus_tab_from_result(result: Mapping[str, Any]) -> str:
    for key in ("advisor_focus_tab", "focus_tab", "default_tab"):
        value = _safe_str(result.get(key))
        if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
            return value
    vis = result.get("visualization") or {}
    if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
        vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
    ):
        return "esp"
    if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"

def _normalize_result_contract(result: Any, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    if isinstance(result, Mapping):
        out = dict(result)
    else:
        out = {"success": True, "result": _json_safe(result)}

    out.setdefault("success", True)
    out.setdefault("job_type", _normalize_job_type(payload.get("job_type"), payload.get("planner_intent")))
    out.setdefault("structure_query", payload.get("structure_query"))
    out.setdefault("structure_name", payload.get("structure_query") or payload.get("structure_name"))
    out.setdefault("method", payload.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"))
    out.setdefault("basis", payload.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"))
    out.setdefault("charge", _safe_int(payload.get("charge"), 0) or 0)
    out.setdefault("multiplicity", _safe_int(payload.get("multiplicity"), 1) or 1)

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    if out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(out.get("esp_preset") or payload.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_from_result(out))

    if out.get("xyz"):
        vis.setdefault("xyz", out.get("xyz"))
        vis.setdefault("molecule_xyz", out.get("xyz"))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    warnings = out.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [warnings]
    out["warnings"] = [_safe_str(x) for x in warnings if _safe_str(x)]

    H2EV = getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
    if out.get("orbital_gap_hartree") is None and out.get("orbital_gap_ev") is not None:
        try:
            out["orbital_gap_hartree"] = float(out["orbital_gap_ev"]) / H2EV
        except Exception:
            pass
    if out.get("orbital_gap_ev") is None and out.get("orbital_gap_hartree") is not None:
        try:
            out["orbital_gap_ev"] = float(out["orbital_gap_hartree"]) * H2EV
        except Exception:
            pass

    out["advisor_focus_tab"] = _focus_tab_from_result(out)
    out["default_tab"] = out["advisor_focus_tab"]
    return _json_safe(out)

# FIX(M2): _prepare_payload now uses structure_resolver
def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    data["job_type"] = _normalize_job_type(data.get("job_type"), data.get("planner_intent"))
    data["method"] = _safe_str(
        data.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
    )
    data["basis"] = _safe_str(
        data.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
    )
    data["charge"] = _safe_int(data.get("charge"), 0) or 0
    data["multiplicity"] = _safe_int(data.get("multiplicity"), 1) or 1

    if data.get("esp_preset"):
        data["esp_preset"] = _normalize_esp_preset(data.get("esp_preset"))

    if not data.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message)
        if xyz_block:
            data["xyz"] = xyz_block

    # FIX(M2): No more inline structure extraction — resolver will handle it
    if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
        if raw_message and len(raw_message.strip()) >= 2:
            data["structure_query"] = raw_message.strip()

    if data["job_type"] not in {"resolve_structure"}:
        if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
            raise HTTPException(
                status_code=400,
                detail=(
                    "구조를 인식할 수 없습니다. 분자 이름, XYZ 좌표 또는 atom-spec을 제공해 주세요. / "
                    "Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text."
                ),
            )

    return data

def _build_kwargs_for_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    sig = inspect.signature(func)
    kwargs: Dict[str, Any] = {}
    candidate_map = {
        "structure_query": payload.get("structure_query") or payload.get("query"),
        "xyz": payload.get("xyz"),
        "atom_spec": payload.get("atom_spec"),
        "method": payload.get("method"),
        "basis": payload.get("basis"),
        "charge": payload.get("charge"),
        "multiplicity": payload.get("multiplicity"),
        "orbital": payload.get("orbital"),
        "esp_preset": payload.get("esp_preset"),
        "advisor_focus_tab": payload.get("advisor_focus_tab"),

# ... (truncated at 700 lines, 556 lines omitted) ...
```

---

## 📄 `backends/pyscf_backend.py` (302 lines)

```python
"""PySCF 기반 IAO/IBO 및 엔터프라이즈 기능(Rich CLI, Shell-Sampling) 백엔드 v3.0.1."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from collections import Counter

import numpy as np

try:
    import pyscf
    from pyscf import gto, lo, scf, lib
    from pyscf.tools import cubegen
    _HAS_PYSCF = True
except ImportError:
    _HAS_PYSCF = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn,
    )
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

from qcviz_mcp.backends.base import IAOResult, IBOResult, OrbitalBackend, SCFResult
from qcviz_mcp.backends.registry import registry
from qcviz_mcp.analysis.sanitize import sanitize_xyz as _sanitize_xyz, extract_atom_list, atoms_to_xyz_string

logger = logging.getLogger(__name__)

_SUPPORTED_METHODS = frozenset({"HF", "RHF", "UHF", "RKS", "UKS", "B3LYP", "PBE0"})
_HEAVY_TM_Z = set(range(39, 49)) | set(range(72, 81))  # 4d(Y-Cd) + 5d(Hf-Hg)

# ================================================================
# §0  Errors & Strategies (Restored for tests)
# ================================================================

class ConvergenceError(RuntimeError):
    """적응적 SCF 수렴 전략이 모두 실패했을 때 발생."""
    pass

class ConvergenceStrategy:
    """적응적 SCF 수렴 에스컬레이션 엔진 (5단계)."""
    LEVELS = (
        {"name": "diis_default", "max_cycle": 100, "level_shift": 0.0, "soscf": False, "damp": 0.0},
        {"name": "diis_levelshift", "max_cycle": 200, "level_shift": 0.5, "soscf": False, "damp": 0.0},
        {"name": "diis_damp", "max_cycle": 200, "level_shift": 0.3, "soscf": False, "damp": 0.5},
        {"name": "soscf", "max_cycle": 200, "level_shift": 0.0, "soscf": True, "damp": 0.0},
        {"name": "soscf_shift", "max_cycle": 300, "level_shift": 0.5, "soscf": True, "damp": 0.0},
    )

    @staticmethod
    def apply(mf, level_idx: int = 0):
        if level_idx < 0 or level_idx >= len(ConvergenceStrategy.LEVELS):
            raise ValueError(f"Invalid strategy level: {level_idx}")
        cfg = ConvergenceStrategy.LEVELS[level_idx]
        mf.max_cycle = cfg["max_cycle"]
        mf.level_shift = cfg["level_shift"]
        mf.damp = cfg["damp"]
        if cfg["soscf"]:
            mf = mf.newton()
        return mf

    @staticmethod
    def level_name(level_idx: int) -> str:
        return ConvergenceStrategy.LEVELS[level_idx]["name"]

def _has_heavy_tm(mol) -> bool:
    if not _HAS_PYSCF: return False
    for ia in range(mol.natm):
        if int(mol.atom_charge(ia)) in _HEAVY_TM_Z: return True
    return False

def parse_cube_string(cube_text: str) -> dict:
    lines = cube_text.strip().splitlines()
    parts = lines[2].split()
    natm = abs(int(parts[0]))
    origin = (float(parts[1]), float(parts[2]), float(parts[3]))
    axes = []; npts_list = []
    for i in range(3):
        p = lines[3 + i].split()
        n = int(p[0]); npts_list.append(n)
        vec = np.array([float(p[1]), float(p[2]), float(p[3])]) * n
        axes.append(vec)
    npts = tuple(npts_list); atoms = []
    for i in range(natm):
        p = lines[6 + i].split()
        atoms.append((int(float(p[0])), float(p[2]), float(p[3]), float(p[4])))
    data_start = 6 + natm
    values = []
    for line in lines[data_start:]: values.extend(float(v) for v in line.split())
    data = np.array(values).reshape(npts)
    return {"data": data, "origin": origin, "axes": axes, "npts": npts, "atoms": atoms}

def _parse_atom_spec(atom_spec: str) -> str:
    lines = atom_spec.strip().splitlines()
    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        return atom_spec
    atom_lines: list[str] = []
    for line in lines[2 : 2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            atom_lines.append(f"{parts[0]}  {parts[1]}  {parts[2]}  {parts[3]}")
    return "; ".join(atom_lines)

def _safe_parse_atom_spec(atom_spec: str) -> str:
    """sanitize_xyz를 시도하고, 실패 시 기존 _parse_atom_spec으로 폴백."""
    try:
        return _sanitize_xyz(atom_spec)
    except (ValueError, Exception):
        return _parse_atom_spec(atom_spec)

# ================================================================
# §1  Rich CLI Reporter
# ================================================================
class _CLIReporter:
    def __init__(self):
        self.console = Console(stderr=True) if _HAS_RICH else None

    def print_calc_summary(self, method, basis, charge, spin, natoms, formula):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]QCViz Setup[/bold cyan]", header_style="bold white on dark_blue", border_style="blue")
            t.add_column("Parameter", style="bold"); t.add_column("Value", style="green")
            t.add_row("Method", method); t.add_row("Basis", basis); t.add_row("Charge", str(charge))
            t.add_row("Spin", str(spin)); t.add_row("Atoms", str(natoms)); t.add_row("Formula", formula)
            self.console.print(t)

    def run_scf_with_progress(self, mf, method, basis):
        if not self.console or not _HAS_RICH:
            mf.run(); return mf
        cd = {"n": 0, "last_e": None, "max": getattr(mf, "max_cycle", 50)}
        prog = Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), BarColumn(bar_width=30, complete_style="green"),
                        TextColumn("[cyan]{task.fields[energy]}"), TextColumn("[yellow]{task.fields[delta]}"), TimeElapsedColumn(), console=self.console)
        tid = [None]
        def cb(envs):
            cd["n"] += 1; e = envs.get("e_tot"); d_str = ""
            if e is not None:
                if cd["last_e"] is not None: d_str = "dE=%.2e" % (e - cd["last_e"])
                cd["last_e"] = e
            e_str = "E=%.8f" % e if e is not None else "E=..."
            if tid[0] is not None: prog.update(tid[0], completed=min(cd["n"]/cd["max"]*100, 100), energy=e_str, delta=d_str, description="SCF Cycle %d" % cd["n"])
        mf.callback = cb
        with prog:
            tid[0] = prog.add_task("SCF ...", total=100, energy="E=...", delta="")
            mf.run()
        if mf.converged: self.console.print(Panel(Text("CONVERGED  E = %.10f Ha" % mf.e_tot, style="bold green"), title="SCF Result", border_style="green"))
        return mf

    def print_esp_summary(self, vmin_raw, vmax_raw, vmin_sym, vmax_sym, p_lo, p_hi):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]ESP Analysis[/bold cyan]", border_style="cyan")
            t.add_column("Metric"); t.add_column("Value", style="green")
            t.add_row("Raw Min/Max", "%.6f / %.6f" % (vmin_raw, vmax_raw))
            t.add_row("P5/P95", "%.6f / %.6f" % (p_lo, p_hi))
            t.add_row("Final Range", "[bold]%.6f .. %.6f[/bold]" % (vmin_sym, vmax_sym))
            self.console.print(t)

    def print_cube_progress(self, current, total, label):
        if self.console and _HAS_RICH: self.console.print("  [dim]Cube[/dim] [bold]%d[/bold]/%d  %s" % (current, total, label))

_cli = _CLIReporter()

@dataclass
class ESPResult:
    density_cube: str; potential_cube: str; vmin: float; vmax: float; vmin_raw: float; vmax_raw: float
    atom_symbols: list; energy_hartree: float; basis: str; grid_size: int = 60; margin: float = 10.0

# ================================================================
# §2  PySCF Backend
# ================================================================

class PySCFBackend(OrbitalBackend):
    @classmethod
    def name(cls): return "pyscf"
    @classmethod
    def is_available(cls): return _HAS_PYSCF

    def compute_scf(self, atom_spec, basis="cc-pvdz", method="RHF", charge=0, spin=0):
        if not _HAS_PYSCF: raise ImportError("PySCF가 설치되지 않았습니다.")
        method_upper = method.upper()
        if method_upper not in _SUPPORTED_METHODS: raise ValueError(f"지원하지 않는 메서드 유형: {method}")
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, verbose=0)
        
        is_dft = any(xc in method_upper for xc in ("B3LYP", "PBE", "WB97", "M06", "RKS", "UKS", "TPSS"))
        if is_dft:
            mf = scf.UKS(mol) if (spin > 0 or method_upper == "UKS") else scf.RKS(mol)
            if method_upper not in ("RKS", "UKS"): mf.xc = method
        else:
            mf = scf.UHF(mol) if (spin > 0 or method_upper == "UHF") else scf.RHF(mol)
        
        syms = [mol.atom_symbol(i) for i in range(mol.natm)]; counts = Counter(syms)
        formula = "".join("%s%s" % (e, str(counts[e]) if counts[e] > 1 else "") for e in sorted(counts.keys()))
        _cli.print_calc_summary(method, basis, charge, spin, mol.natm, formula)
        mf = _cli.run_scf_with_progress(mf, method, basis)
        
        if not mf.converged: mf, mol = self.compute_scf_adaptive(mol, spin=spin)
        return (SCFResult(True, float(mf.e_tot), mf.mo_coeff, mf.mo_occ, mf.mo_energy, basis, method), mol)

    def compute_esp(self, atom_spec, basis="cc-pvdz", grid_size=60, method="rhf", charge=0, spin=0):
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, unit="Angstrom", verbose=0)
        mol.build(); mf = scf.RKS(mol) if spin == 0 else scf.UKS(mol); mf.run(); dm = mf.make_rdm1()
        d_p = p_p = None
        try:
            with tempfile.NamedTemporaryFile(suffix="_den.cube", delete=False) as f1: d_p = f1.name
            with tempfile.NamedTemporaryFile(suffix="_pot.cube", delete=False) as f2: p_p = f2.name
            cubegen.density(mol, d_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            cubegen.mep(mol, p_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            with open(d_p) as f: d_c = f.read()
            with open(p_p) as f: p_c = f.read()
        finally:
            for p in (d_p, p_p):
                if p and os.path.exists(p): os.unlink(p)
        vr, vxr, p_lo, p_hi = self._extract_surface_potential_range(d_c, p_c)
        abs_max = max(abs(p_lo), abs(p_hi))
        if abs_max < 1e-5: abs_max = 0.05
        _cli.print_esp_summary(vr, vxr, -abs_max, abs_max, p_lo, p_hi)
        return ESPResult(d_c, p_c, -abs_max, abs_max, vr, vxr, [mol.atom_symbol(i) for i in range(mol.natm)], float(mf.e_tot), basis, grid_size, 10.0)

    def _extract_surface_potential_range(self, den_cube, pot_cube, isoval=0.002):
        def get_data(cube):
            ls = cube.splitlines()
            if len(ls) < 7: return np.array([])
            toks2 = ls[2].split(); na = abs(int(toks2[0])); ds = 6 + na + (1 if int(toks2[0]) < 0 else 0)
            raw = " ".join(ls[ds:]).replace("D", "E").replace("d", "e")
            return np.fromstring(raw, sep=" ")
        darr = get_data(den_cube); parr = get_data(pot_cube)
        if len(darr) == 0 or len(darr) != len(parr): return -0.1, 0.1, -0.1, 0.1
        mask = (darr >= isoval * 0.8) & (darr <= isoval * 1.2)
        if not np.any(mask): mask = darr >= isoval
        surf_p = parr[mask]
        surf_p = surf_p[np.isfinite(surf_p)]
        if len(surf_p) == 0: return -0.1, 0.1, -0.1, 0.1
        p_lo = float(np.percentile(surf_p, 5))
        p_hi = float(np.percentile(surf_p, 95))
        return float(np.min(surf_p)), float(np.max(surf_p)), p_lo, p_hi

    def generate_cube(self, mol, coeffs, orbital_index, grid_points=(60,60,60)):
        with tempfile.NamedTemporaryFile(suffix=".cube", delete=False) as tmp: t_p = tmp.name
        try:
            cubegen.orbital(mol, t_p, coeffs[:, orbital_index], nx=grid_points[0], ny=grid_points[1], nz=grid_points[2], margin=10.0)
            with open(t_p) as f: return f.read()
        finally:
            if os.path.exists(t_p): os.remove(t_p)

    def compute_iao(self, scf_res, mol, minao="minao"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        iao_coeff = lo.iao.iao(mol, orbocc, minao=minao)
        charges = self._compute_iao_charges(mol, scf_res, iao_coeff)
        return IAOResult(coefficients=iao_coeff, charges=charges)

    def _iao_population_custom(self, mol, dm, iao_coeff):
        ovlp = mol.intor_symmetric("int1e_ovlp")
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        p_matrix = (iao_coeff @ np.linalg.inv(s_iao) @ iao_coeff.T @ ovlp @ dm @ ovlp)
        a_pop = [np.trace(p_matrix[b0:b1, b0:b1]) for b0, b1 in [mol.aoslice_by_atom()[i][2:] for i in range(mol.natm)]]
        return np.array(a_pop)

    def _compute_iao_charges(self, mol: Any, scf_result: SCFResult, iao_coeff: np.ndarray) -> np.ndarray:
        ovlp = mol.intor_symmetric("int1e_ovlp")
        orbocc = scf_result.mo_coeff[:, scf_result.mo_occ > 0]
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        eigvals, eigvecs = np.linalg.eigh(s_iao)
        s_iao_inv_half = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
        iao_orth = iao_coeff @ s_iao_inv_half
        proj = iao_orth.T @ ovlp @ orbocc
        dm_iao = (1.0 if mol.spin > 0 else 2.0) * proj @ proj.T
        
        from pyscf.lo.iao import reference_mol
        effective_minao, _ = self._resolve_minao(mol, "minao")
        pmol = reference_mol(mol, minao=effective_minao)
        ref_labels = pmol.ao_labels(fmt=False)
        n_iao = iao_orth.shape[1]
        charges = np.zeros(mol.natm)
        for j in range(n_iao):
            atom_idx = ref_labels[j][0]
            charges[atom_idx] += dm_iao[j, j]
        for i in range(mol.natm):
            charges[i] = mol.atom_charge(i) - charges[i]
        return charges

    def compute_ibo(self, scf_res, iao_res, mol, localization_method: str = "IBO"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        if localization_method.upper() == "BOYS":
            loc_obj = lo.Boys(mol, orbocc)

# ... (truncated at 300 lines, 218 lines omitted) ...
```

---

## 📄 `backends/viz_backend.py` (202 lines)

```python
"""시각화 백엔드 — Enterprise v3.5 UI/UX Restoration & Upgrade.

v3.5 패치 내역:
1. [RESTORE] v2.3.0의 모든 UI 요소 100% 복구 + v4 기능 통합.
2. [UPGRADE] Enterprise-grade sidebar layout, floating toolbar.
3. [ADD] Isovalue/Opacity sliders, Representation toggle, Labels,
   Charges overlay, Screenshot, Keyboard shortcuts.
4. [STYLE] Clean commercial SaaS aesthetic — white background,
   refined typography, subtle shadows.
5. [FIX] Flexbox scroll (min-height:0), Orbital clipping (zoom & slab), 
   White background, Resize handling.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qcviz_mcp.backends.base import VisualizationBackend
from qcviz_mcp.backends.registry import registry

logger = logging.getLogger("qcviz_mcp.viz_backend")

_ESP_PRESET_ORDER = (
    "rwb",
    "viridis",
    "inferno",
    "spectral",
    "nature",
    "acs",
    "rsc",
    "matdark",
    "grey",
    "hicon",
)

def _json_for_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

def _build_esp_select_options(presets: dict) -> str:
    seen = set()
    items = []

    for key in _ESP_PRESET_ORDER:
        if key in presets:
            items.append((key, presets[key]))
            seen.add(key)

    for key, value in presets.items():
        if key not in seen:
            items.append((key, value))

    lines = []
    for key, spec in items:
        label = html.escape(str(spec.get("name") or key))
        value = html.escape(str(key))
        selected = ' selected' if key == "rwb" else ""
        lines.append(f'<option value="{value}"{selected}>{label}</option>')

    return "\n".join(lines)

ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}

ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}

def build_web_visualization_payload(payload: DashboardPayload) -> dict:
    orbitals = []
    selected_key = None

    for i, orb in enumerate(payload.orbitals or []):
        key = f"orb:{orb.index}"
        item = {
            "key": key,

# ... (truncated at 200 lines, 2144 lines omitted) ...
```

---

## 📄 `security.py` (113 lines)

```python
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

```

---

## 📄 `web/templates/index.html` (352 lines)

```html
<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <script>window.__ROOT_PATH = "{{ root_path }}";</script>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1, viewport-fit=cover"
    />
    <title>QCViz-MCP v3</title>
    <meta
      name="description"
      content="Quantum chemistry visualization with PySCF, 3Dmol.js, Gemini AI, MolChat integration, and WebSocket orchestration."
    />
    <!-- FIX(M11): ARIA landmark: lang attribute set -->
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="{{ root_path }}/static/style.css" />

    <script>
      /* FIX(M11): QCVizApp global store — inline bootstrap */
      (function (g) {
        "use strict";
        if (g.QCVizApp && g.QCVizApp.__v3) return;

        var STORAGE_KEY = "QCVIZ_V3_UI_SNAPSHOTS";
        var listeners = new Map();

        function safeStr(v, fb) {
          return v == null ? fb || "" : String(v).trim();
        }
        function clone(v) {
          try {
            return JSON.parse(JSON.stringify(v));
          } catch (_) {
            return v;
          }
        }
        function deepMerge(base, patch) {
          var lhs = base && typeof base === "object" ? clone(base) : {};
          var rhs = patch && typeof patch === "object" ? patch : {};
          Object.keys(rhs).forEach(function (k) {
            var lv = lhs[k],
              rv = rhs[k];
            if (
              lv &&
              rv &&
              typeof lv === "object" &&
              typeof rv === "object" &&
              !Array.isArray(lv) &&
              !Array.isArray(rv)
            ) {
              lhs[k] = deepMerge(lv, rv);
            } else {
              lhs[k] = clone(rv);
            }
          });
          return lhs;
        }

        function makeSessionId() {
          var ts = Date.now().toString(36);
          var r = Math.random().toString(36).substring(2, 8);
          return "qcviz-" + ts + "-" + r;
        }

        var apiPrefix = g.QCVIZ_API_PREFIX || "";

        var store = {
          version: "v3",
          jobsById: {},
          jobOrder: [],
          resultsByJobId: {},
          activeJobId: null,
          activeResult: null,
          status: {
            text: "Ready",
            kind: "idle",
            source: "app",
            at: Date.now(),
          },
          uiSnapshotsByJobId: {},
          chatMessages: [],
          chatMessagesByJobId: {},
          theme: "dark",
          lastUserInput: "",
          sessionId: makeSessionId(),
        };

        var CHAT_STORAGE_KEY = "QCVIZ_CHAT";
        var MAX_CHAT_MESSAGES = 200;
        var chatSaveTimer = null;

        function emit(ev, detail) {
          (listeners.get(ev) || []).slice().forEach(function (fn) {
            try {
              fn(detail);
            } catch (_) {}
          });
        }
        function on(ev, fn) {
          if (!listeners.has(ev)) listeners.set(ev, []);
          listeners.get(ev).push(fn);
          return function () {
            var arr = listeners.get(ev) || [];
            var idx = arr.indexOf(fn);
            if (idx >= 0) arr.splice(idx, 1);
          };
        }

        function persistSnapshots() {
          try {
            localStorage.setItem(
              STORAGE_KEY,
              JSON.stringify(store.uiSnapshotsByJobId),
            );
          } catch (_) {}
        }
        function loadSnapshots() {
          try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (raw) store.uiSnapshotsByJobId = JSON.parse(raw);
          } catch (_) {}
        }
        loadSnapshots();

        function persistChatMessages() {
          try {
            var msgs = store.chatMessages.slice(-MAX_CHAT_MESSAGES);
            var data = { global: msgs, byJob: store.chatMessagesByJobId };
            localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(data));
          } catch (_) {}
        }
        function throttledSaveChatMessages() {
          if (chatSaveTimer) return;
          chatSaveTimer = setTimeout(function () {
            chatSaveTimer = null;
            persistChatMessages();
          }, 1000);
        }
        function loadChatMessages() {
          try {
            var raw = localStorage.getItem(CHAT_STORAGE_KEY);
            if (raw) {
              var parsed = JSON.parse(raw);
              store.chatMessages = parsed.global || parsed || [];
              store.chatMessagesByJobId = parsed.byJob || {};
            }
          } catch (_) {
            store.chatMessages = [];
            store.chatMessagesByJobId = {};
          }
        }
        loadChatMessages();

        var prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
        function applyTheme(theme) {
          store.theme = theme;
          document.documentElement.setAttribute("data-theme", theme);
          emit("theme:changed", { theme: theme });
        }
        var savedTheme = localStorage.getItem("QCVIZ_THEME");
        if (savedTheme) applyTheme(savedTheme);
        else applyTheme(prefersDark.matches ? "dark" : "light");
        prefersDark.addEventListener("change", function (e) {
          if (!localStorage.getItem("QCVIZ_THEME"))
            applyTheme(e.matches ? "dark" : "light");
        });

        g.QCVizApp = {
          __v3: true,
          store: store,
          on: on,
          emit: emit,
          clone: clone,
          deepMerge: deepMerge,
          apiPrefix: apiPrefix,

          setTheme: function (theme) {
            localStorage.setItem("QCVIZ_THEME", theme);
            applyTheme(theme);
          },

          setStatus: function (text, kind, source) {
            store.status = {
              text: text,
              kind: kind || "idle",
              source: source || "app",
              at: Date.now(),
            };
            emit("status:changed", clone(store.status));
          },

          upsertJob: function (job) {
            if (!job || typeof job !== "object") return null;
            var jobId = safeStr(job.job_id);
            if (!jobId) return null;
            var prev = store.jobsById[jobId] || {};
            var next = deepMerge(prev, job);
            store.jobsById[jobId] = next;
            if (next.result) store.resultsByJobId[jobId] = clone(next.result);
            store.jobOrder = Object.values(store.jobsById)
              .sort(function (a, b) {
                return (
                  Number(b.created_at || b.updated_at || 0) -
                  Number(a.created_at || a.updated_at || 0)
                );
              })
              .map(function (j) {
                return j.job_id;
              });
            emit("jobs:changed", {
              job: clone(next),
              jobs: store.jobOrder.map(function (id) {
                return clone(store.jobsById[id]);
              }),
            });
            return clone(next);
          },

          setActiveJob: function (jobId) {
            store.activeJobId = jobId;
            var result = store.resultsByJobId[jobId] || null;
            store.activeResult = result ? clone(result) : null;
            emit("activejob:changed", {
              jobId: jobId,
              result: store.activeResult,
            });
            if (result)
              emit("result:changed", {
                jobId: jobId,
                result: clone(result),
                source: "history",
              });
          },

          setActiveResult: function (res, opts) {
            opts = opts || {};
            var jobId = safeStr(opts.jobId || store.activeJobId);
            store.activeResult = res;
            if (jobId) {
              store.activeJobId = jobId;
              store.resultsByJobId[jobId] = clone(res);
            }
            emit("result:changed", {
              jobId: jobId,
              result: clone(res),
              source: opts.source || "app",
            });
          },

          saveUISnapshot: function (jobId, snapshot) {
            if (!jobId) return;
            store.uiSnapshotsByJobId[jobId] = clone(snapshot);
            persistSnapshots();
          },

          getUISnapshot: function (jobId) {
            return store.uiSnapshotsByJobId[jobId]
              ? clone(store.uiSnapshotsByJobId[jobId])
              : null;
          },

          addChatMessage: function (msg) {
            store.chatMessages.push(msg);
            // Also store per-job if jobId is set
            if (msg.jobId) {
              if (!store.chatMessagesByJobId[msg.jobId]) {
                store.chatMessagesByJobId[msg.jobId] = [];
              }
              store.chatMessagesByJobId[msg.jobId].push(msg);
            }
            // Trim to max
            if (store.chatMessages.length > MAX_CHAT_MESSAGES) {
              store.chatMessages = store.chatMessages.slice(-MAX_CHAT_MESSAGES);
            }
            throttledSaveChatMessages();
            emit("chat:message", clone(msg));
          },

          getChatMessages: function () {
            return clone(store.chatMessages);
          },

          getChatMessagesForJob: function (jobId) {
            if (!jobId || !store.chatMessagesByJobId[jobId]) return [];
            return clone(store.chatMessagesByJobId[jobId]);
          },

          clearChatMessages: function () {
            store.chatMessages = [];
            store.chatMessagesByJobId = {};
            try { localStorage.removeItem(CHAT_STORAGE_KEY); } catch (_) {}
          },
        };
      })(window);
    </script>
  </head>

  <body>
    <!-- FIX(M11): skip-to-content link -->
    <a href="#chatInput" class="skip-link">Skip to chat input</a>

    <!-- Loading overlay -->
    <div id="appLoader" class="app-loader" role="status" aria-label="Loading">
      <div class="loader-content">
        <div class="loader-spinner"></div>
        <p class="loader-text">Initializing QCViz-MCP v3...</p>
        <p class="loader-sub">Loading 3D visualization engine</p>
      </div>
    </div>
    <script>
      window.addEventListener("load", function () {
        setTimeout(function () {
          var loader = document.getElementById("appLoader");
          if (loader) {
            loader.classList.add("fade-out");
            setTimeout(function () {
              if (loader.parentNode) loader.parentNode.removeChild(loader);
            }, 600);
          }
        }, 1500);
      });
    </script>

    <div class="app-shell" id="appShell">
      <!-- Top Bar -->
      <header class="topbar" id="topbar" role="banner">
        <div class="topbar__left">
          <div class="topbar__logo" aria-label="QCViz Logo">
            <svg
              width="28"
              height="28"
              viewBox="0 0 28 28"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <rect width="28" height="28" rx="8" fill="url(#logoGrad)" />
              <path
                d="M8 14a6 6 0 1 1 12 0 6 6 0 0 1-12 0Zm6-3.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"
                fill="white"
                fill-opacity="0.95"
              />
              <path
                d="M17.5 17.5L21 21"
                stroke="white"

# ... (truncated at 350 lines, 637 lines omitted) ...
```

---

## 📄 `web/static/chat.js` (502 lines)

```javascript
/**
 * QCViz-MCP v3 — Chat Module
 * FIX(M7): 재귀 방지(depth guard), 상태 머신, 지수 백오프 재접속,
 *          XSS 방지(textContent), aria-live, client ping 20s
 */
(function (g) {
  "use strict";
  console.log("[chat.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[chat.js] ✖ QCVizApp not found — aborting chat module");
    return;
  }
  console.log("[chat.js] ✔ QCVizApp found");

  // ─── 상수 ───────────────────────────────────────────
  var MAX_RECONNECT = 10;
  var RECONNECT_BASE_MS = 1000;
  var RECONNECT_MAX_MS = 30000;
  var PING_INTERVAL_MS = 20000;
  var MAX_DEPTH = 3;

  // ─── 상태 머신 ──────────────────────────────────────
  var STATE_IDLE = "idle";
  var STATE_SENDING = "sending";
  var STATE_AWAITING = "awaiting_ack";

  var chatState = STATE_IDLE;
  var ws = null;
  var reconnectCount = 0;
  var reconnectTimer = null;
  var pingTimer = null;
  var depth = 0;
  var activeJobIdForChat = null;  // Track current job for per-job chat storage

  // ─── DOM refs ───────────────────────────────────────
  var chatMessages = document.getElementById("chatMessages");
  var chatInput = document.getElementById("chatInput");
  var chatSend = document.getElementById("chatSend");
  var chatForm = document.getElementById("chatForm");
  var chatScroll = document.getElementById("chatScroll");
  var wsStatusDot = null;
  var wsStatusLabel = null;

  console.log("[chat.js] DOM refs:", {
    chatMessages: !!chatMessages, chatInput: !!chatInput,
    chatSend: !!chatSend, chatForm: !!chatForm, chatScroll: !!chatScroll,
  });

  function initWsStatus() {
    var wsStatus = document.getElementById("wsStatus");
    if (wsStatus) {
      wsStatusDot = wsStatus.querySelector(".ws-status__dot");
      wsStatusLabel = wsStatus.querySelector(".ws-status__label");
    }
    console.log("[chat.js] initWsStatus — dot:", !!wsStatusDot, "label:", !!wsStatusLabel);
  }

  // ─── 유틸 ───────────────────────────────────────────

  function escapeText(str) {
    if (str == null) return "";
    return String(str);
  }

  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function setWsConnected(connected) {
    console.log("[chat.js] setWsConnected:", connected);
    if (wsStatusDot)
      wsStatusDot.setAttribute("data-connected", String(!!connected));
    if (wsStatusLabel)
      wsStatusLabel.textContent = connected ? "Connected" : "Disconnected";
  }

  function scrollToBottom() {
    if (chatScroll) {
      requestAnimationFrame(function () {
        chatScroll.scrollTop = chatScroll.scrollHeight;
      });
    }
  }

  function ensureAriaLive() {
    if (!chatMessages) return;
    if (!chatMessages.getAttribute("aria-live")) {
      chatMessages.setAttribute("aria-live", "polite");
      chatMessages.setAttribute("aria-relevant", "additions");
    }
  }

  // ─── 메시지 렌더링 ─────────────────────────────

  function _renderMarkdown(text) {
    // Escape HTML first for XSS safety
    var html = escapeText(text);

    // Code blocks (```...```)
    html = html.replace(/```([\s\S]*?)```/g, function (_, code) {
      return '<pre class="chat-code"><code>' + code.trim() + '</code></pre>';
    });

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');

    // Headers
    html = html.replace(/^### (.+)$/gm, '<strong class="chat-h3">$1</strong>');
    html = html.replace(/^## (.+)$/gm, '<strong class="chat-h2">$1</strong>');
    html = html.replace(/^# (.+)$/gm, '<strong class="chat-h1">$1</strong>');

    // Bold + italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(?<![*])\*([^*]+?)\*(?![*])/g, '<em>$1</em>');

    // Bullet lists (lines starting with - or * )
    html = html.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li class="chat-li">$1</li>');
    html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, function (m) {
      return '<ul class="chat-ul">' + m + '</ul>';
    });

    // Numbered lists (lines starting with 1. 2. etc.)
    html = html.replace(/^\s*(\d+)\.\s+(.+)$/gm, '<li class="chat-li" value="$1">$2</li>');
    html = html.replace(/(<li class="chat-li" value="\d+">.*<\/li>\n?)+/g, function (m) {
      return '<ol class="chat-ol">' + m + '</ol>';
    });

    // Line breaks (preserve double newlines as paragraphs)
    html = html.replace(/\n\n/g, '</p><p class="chat-p">');
    html = html.replace(/\n/g, '<br>');

    return '<p class="chat-p">' + html + '</p>';
  }

  function appendMessage(role, text, extra) {
    console.log("[chat.js] appendMessage — role:", role, "text length:", (text||"").length,
      "extra:", extra ? Object.keys(extra).join(",") : "none");
    if (!chatMessages) return;
    extra = extra || {};

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--" + safeStr(role, "system");

    var avatar = document.createElement("div");
    avatar.className =
      "chat-msg__avatar chat-msg__avatar--" + safeStr(role, "system");
    if (role === "user") {
      avatar.textContent = "U";
    } else if (role === "assistant" || role === "system") {
      avatar.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
    } else {
      avatar.textContent = role.charAt(0).toUpperCase();
    }

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var p = document.createElement("div");
    p.className = "chat-msg__text";
    if (role === "assistant" || role === "system") {
      p.innerHTML = _renderMarkdown(text);
    } else {
      p.textContent = escapeText(text);
    }

    body.appendChild(p);

    if (extra.plan) {
      console.log("[chat.js] appendMessage — attaching plan JSON");
      var planEl = document.createElement("pre");
      planEl.className = "chat-msg__plan";
      planEl.textContent = JSON.stringify(extra.plan, null, 2);
      body.appendChild(planEl);
    }

    wrapper.appendChild(avatar);
    wrapper.appendChild(body);
    chatMessages.appendChild(wrapper);

    App.addChatMessage({
      role: role, text: text, jobId: activeJobIdForChat || null,
      timestamp: Date.now(), extra: extra,
    });

    scrollToBottom();
  }

  function appendProgress(jobId, progress, step, message, extra) {
    var pct = Math.round(Math.min(100, Math.max(0, (progress || 0) * 100)));
    console.log("[chat.js] appendProgress — jobId:", jobId, "pct:", pct, "step:", step, "msg:", message);

    var existing = chatMessages
      ? chatMessages.querySelector('[data-progress-job="' + jobId + '"]')
      : null;

    if (existing) {
      var bar = existing.querySelector(".progress-bar__fill");
      var lbl = existing.querySelector(".progress-bar__label");
      if (bar) bar.style.width = pct + "%";
      if (lbl)
        lbl.textContent =
          safeStr(message, step || "Working...") + " (" + pct + "%)";

      // Update SCF convergence chart if available
      if (extra && extra.scf_history && extra.scf_history.length > 1) {
        _renderScfChart(existing, extra.scf_history);
      }
      return;
    }

    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--progress";
    wrapper.setAttribute("data-progress-job", jobId);

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var container = document.createElement("div");
    container.className = "progress-bar";

    var fill = document.createElement("div");
    fill.className = "progress-bar__fill";
    fill.style.width = pct + "%";

    var label = document.createElement("div");
    label.className = "progress-bar__label";
    label.textContent =
      safeStr(message, step || "Working...") + " (" + pct + "%)";

    container.appendChild(fill);
    body.appendChild(label);
    body.appendChild(container);

    // Add cancel button
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "scf-cancel-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.title = "Cancel this computation";
    cancelBtn.onclick = function () {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelling...";
      fetch(window.__ROOT_PATH + "/compute/jobs/" + jobId + "/cancel", { method: "POST" })
        .then(function () { cancelBtn.textContent = "Cancelled"; })
        .catch(function () { cancelBtn.textContent = "Cancel"; cancelBtn.disabled = false; });
    };
    body.appendChild(cancelBtn);

    // Add SCF chart area
    var chartArea = document.createElement("div");
    chartArea.className = "scf-chart-area";
    chartArea.style.display = "none";
    var canvas = document.createElement("canvas");
    canvas.className = "scf-chart-canvas";
    canvas.width = 280;
    canvas.height = 80;
    chartArea.appendChild(canvas);
    body.appendChild(chartArea);

    wrapper.appendChild(body);

    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  // Mini convergence chart: log|dE| vs cycle
  function _renderScfChart(container, history) {
    var chartArea = container.querySelector(".scf-chart-area");
    var canvas = container.querySelector(".scf-chart-canvas");
    if (!chartArea || !canvas) return;
    chartArea.style.display = "block";

    var ctx = canvas.getContext("2d");
    var W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Filter entries with dE
    var pts = [];
    for (var i = 0; i < history.length; i++) {
      if (history[i].dE != null && history[i].dE !== 0) {
        pts.push({ c: history[i].cycle, v: Math.log10(Math.abs(history[i].dE)) });
      }
    }
    if (pts.length < 2) return;

    var minV = pts[0].v, maxV = pts[0].v;
    for (var j = 0; j < pts.length; j++) {
      if (pts[j].v < minV) minV = pts[j].v;
      if (pts[j].v > maxV) maxV = pts[j].v;
    }
    var rangeV = maxV - minV || 1;

    // Background
    ctx.fillStyle = "rgba(0,0,0,0.03)";
    ctx.fillRect(0, 0, W, H);

    // Convergence threshold line (1e-9)
    var threshY = H - (((-9) - minV) / rangeV) * (H - 10) - 5;
    if (threshY > 5 && threshY < H - 5) {
      ctx.strokeStyle = "rgba(239,68,68,0.4)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, threshY);
      ctx.lineTo(W, threshY);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Plot line
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var k = 0; k < pts.length; k++) {
      var x = (k / (pts.length - 1)) * (W - 10) + 5;
      var y = H - ((pts[k].v - minV) / rangeV) * (H - 10) - 5;
      if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Labels
    ctx.fillStyle = "#666";
    ctx.font = "9px monospace";
    ctx.fillText("log|dE|", 2, 10);
    ctx.fillText(maxV.toFixed(1), W - 30, 10);
    ctx.fillText(minV.toFixed(1), W - 30, H - 2);
    ctx.fillText("cycle " + pts[pts.length - 1].c, W - 55, H - 2);
  }

  // ─── Clarification Form ──────────────────────────────
  function _renderClarifyForm(message, fields, sessionId) {
    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--clarify";

    var body = document.createElement("div");
    body.className = "chat-msg__body clarify-form";

    var title = document.createElement("p");
    title.className = "clarify-form__title";
    title.textContent = message || "Please clarify:";
    body.appendChild(title);

    var form = document.createElement("div");
    form.className = "clarify-form__fields";

    fields.forEach(function (f) {
      var group = document.createElement("div");
      group.className = "clarify-field";

      var lbl = document.createElement("label");
      lbl.className = "clarify-field__label";
      lbl.textContent = f.label;
      group.appendChild(lbl);

      if (f.type === "radio" && f.options) {
        f.options.forEach(function (opt) {
          var radioWrap = document.createElement("label");
          radioWrap.className = "clarify-radio";
          var radio = document.createElement("input");
          radio.type = "radio";
          radio.name = "clarify_" + f.id;
          radio.value = opt.value;
          if (opt.value === f.default) radio.checked = true;
          radioWrap.appendChild(radio);
          radioWrap.appendChild(document.createTextNode(" " + opt.label));
          group.appendChild(radioWrap);
        });
      } else if (f.type === "select" && f.options) {
        var sel = document.createElement("select");
        sel.className = "clarify-select";
        sel.setAttribute("data-field-id", f.id);
        f.options.forEach(function (opt) {
          var option = document.createElement("option");
          option.value = opt.value;
          option.textContent = opt.label;
          if (opt.value === f.default) option.selected = true;
          sel.appendChild(option);
        });
        group.appendChild(sel);
      } else if (f.type === "number") {
        var numInput = document.createElement("input");
        numInput.type = "number";
        numInput.className = "clarify-input";
        numInput.setAttribute("data-field-id", f.id);
        numInput.value = f.default != null ? f.default : 0;
        group.appendChild(numInput);
      } else {
        var txtInput = document.createElement("input");
        txtInput.type = "text";
        txtInput.className = "clarify-input";
        txtInput.setAttribute("data-field-id", f.id);
        txtInput.placeholder = f.placeholder || "";
        if (f.default) txtInput.value = f.default;
        group.appendChild(txtInput);
      }
      form.appendChild(group);
    });

    body.appendChild(form);

    var btnRow = document.createElement("div");
    btnRow.className = "clarify-form__actions";
    var submitBtn = document.createElement("button");
    submitBtn.className = "clarify-btn clarify-btn--primary";
    submitBtn.textContent = "확인 / Submit";
    submitBtn.onclick = function () {
      var answers = {};
      fields.forEach(function (f) {
        if (f.type === "radio") {
          var checked = form.querySelector('input[name="clarify_' + f.id + '"]:checked');
          answers[f.id] = checked ? checked.value : f.default;
        } else {
          var el = form.querySelector('[data-field-id="' + f.id + '"]');
          answers[f.id] = el ? el.value : f.default;
        }
      });
      submitBtn.disabled = true;
      submitBtn.textContent = "전송 중...";
      wsSend({ type: "clarify_response", answers: answers });
    };
    btnRow.appendChild(submitBtn);
    body.appendChild(btnRow);
    wrapper.appendChild(body);

    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  function _renderConfirmCard(message, pendingPlan, sessionId) {
    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--confirm";

    var body = document.createElement("div");
    body.className = "chat-msg__body confirm-card";

    var msgEl = document.createElement("div");
    msgEl.className = "confirm-card__message";
    msgEl.innerHTML = (message || "").replace(/\n/g, "<br>").replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    body.appendChild(msgEl);

    var btnRow = document.createElement("div");
    btnRow.className = "confirm-card__actions";

    var computeBtn = document.createElement("button");
    computeBtn.className = "clarify-btn clarify-btn--primary";
    computeBtn.textContent = "🚀 계산하기 / Compute";
    computeBtn.onclick = function () {
      computeBtn.disabled = true;
      computeBtn.textContent = "제출 중...";
      wsSend({ type: "confirm" });
    };

    var editBtn = document.createElement("button");
    editBtn.className = "clarify-btn clarify-btn--secondary";
    editBtn.textContent = "✏️ 수정하기 / Edit";
    editBtn.onclick = function () {
      // Re-trigger clarification
      wsSend({ type: "clarify_response", answers: {} });
    };

    btnRow.appendChild(computeBtn);
    btnRow.appendChild(editBtn);
    body.appendChild(btnRow);
    wrapper.appendChild(body);

    if (chatMessages) chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  // ─── WebSocket ──────────────────────────────────────

  function getWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + (window.__ROOT_PATH || "") + "/ws/chat";
    return url;
  }

  function connect() {
    console.log("[chat.js] connect() — ws state:",
      ws ? ["CONNECTING","OPEN","CLOSING","CLOSED"][ws.readyState] : "null",
      "reconnectCount:", reconnectCount);

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      console.log("[chat.js] connect — already connected/connecting, skipping");
      return;
    }

    var url = getWsUrl();
    console.log("[chat.js] connect — opening WebSocket:", url);

    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.error("[chat.js] ✖ WebSocket creation failed:", e);
      scheduleReconnect();
      return;
    }

# ... (truncated at 500 lines, 457 lines omitted) ...
```

---

## 📄 `web/static/app.js` (202 lines)

```javascript
/**
 * QCViz-MCP v3 — App Shell Controller
 * FIX(M10): newest-first history, rAF batch rendering,
 *           localStorage 2s throttle, 키보드 접근성, 이벤트 루프 방지
 */
(function (g) {
  "use strict";
  console.log("[app.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[app.js] ✖ QCVizApp not found — aborting app module");
    return;
  }
  console.log("[app.js] ✔ QCVizApp found, theme:", App.store.theme);

  // ─── 상수 ──────────────────────────────────────────
  var LS_THROTTLE_MS = 2000;

  // ─── DOM refs ──────────────────────────────────────
  var globalStatus = document.getElementById("globalStatus");
  var statusDot = globalStatus ? globalStatus.querySelector(".status-indicator__dot") : null;
  var statusText = globalStatus ? globalStatus.querySelector(".status-indicator__text") : null;
  var historyList = document.getElementById("historyList");
  var historyEmpty = document.getElementById("historyEmpty");
  var historySearch = document.getElementById("historySearch");
  var btnRefreshHistory = document.getElementById("btnRefreshHistory");
  var btnThemeToggle = document.getElementById("btnThemeToggle");
  var btnKeyboardShortcuts = document.getElementById("btnKeyboardShortcuts");
  var modalShortcuts = document.getElementById("modalShortcuts");
  var appLoader = document.getElementById("appLoader");

  console.log("[app.js] DOM refs:", {
    globalStatus: !!globalStatus, historyList: !!historyList,
    historySearch: !!historySearch, btnRefreshHistory: !!btnRefreshHistory,
    btnThemeToggle: !!btnThemeToggle, modalShortcuts: !!modalShortcuts,
    appLoader: !!appLoader,
  });

  // ─── 상태 ──────────────────────────────────────────
  var dirtyHistory = false;
  var rafPending = false;
  var lastLsSave = 0;
  var lsTimer = null;
  var eventLoopGuard = false;

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) { return v == null ? fb || "" : String(v).trim(); }

  function formatTime(ts) {
    if (!ts) return "—";
    try { var d = new Date(ts * 1000); return d.toLocaleTimeString(); }
    catch (_) { return "—"; }
  }

  function show(el) { if (el) el.removeAttribute("hidden"); }
  function hide(el) { if (el) el.setAttribute("hidden", ""); }

  // ─── 상태 표시 ────────────────────────────────────

  function updateStatus(detail) {
    if (!detail) return;
    console.log("[app.js] updateStatus — kind:", detail.kind, "text:", detail.text);
    if (statusDot) statusDot.setAttribute("data-kind", safeStr(detail.kind, "idle"));
    if (statusText) statusText.textContent = safeStr(detail.text, "Ready");
  }

  // ─── 히스토리 렌더링 ──────────────────────────────

  function renderHistory(filter) {
    if (!historyList) return;

    var jobs = App.store.jobOrder
      .map(function (id) { return App.store.jobsById[id]; })
      .filter(function (j) { return !!j; });

    jobs.sort(function (a, b) { return (b.created_at || 0) - (a.created_at || 0); });

    if (filter) {
      var lf = filter.toLowerCase();
      jobs = jobs.filter(function (j) {
        var name = safeStr(j.molecule_name || j.user_query || "").toLowerCase();
        var jtype = safeStr(j.job_type || "").toLowerCase();
        var status = safeStr(j.status || "").toLowerCase();
        return name.indexOf(lf) >= 0 || jtype.indexOf(lf) >= 0 || status.indexOf(lf) >= 0;
      });
    }

    console.log("[app.js] renderHistory — total jobs:", jobs.length, "filter:", filter || "(none)");

    if (jobs.length === 0) {
      historyList.innerHTML = "";
      show(historyEmpty);
      return;
    }

    hide(historyEmpty);
    var fragment = document.createDocumentFragment();

    jobs.forEach(function (job) {
      var card = document.createElement("div");
      card.className = "history-card";
      card.setAttribute("data-job-id", safeStr(job.job_id));
      card.setAttribute("data-job-type", safeStr(job.job_type || ""));
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-label",
        safeStr(job.molecule_name || job.user_query || job.job_type || "Job"));

      var statusClass = "history-card__status--" + safeStr(job.status, "queued");

      card.innerHTML =
        '<div class="history-card__header">' +
        '<span class="history-card__name">' +
        escapeHtmlSafe(safeStr(job.molecule_name || job.user_query || "Unnamed")) +
        "</span>" +
        '<span class="history-card__status ' + statusClass + '">' +
        safeStr(job.status, "queued") + "</span></div>" +
        '<div class="history-card__meta">' +
        "<span>" + escapeHtmlSafe(safeStr(job.job_type || "")) + "</span>" +
        '<span class="history-card__method">' + escapeHtmlSafe(safeStr(job.method || "")) + "</span>" +
        '<span class="history-card__basis">' + escapeHtmlSafe(safeStr(job.basis_set || job.basis || "")) + "</span>" +
        "<span>" + formatTime(job.created_at) + "</span></div>";

      card.addEventListener("click", function () {
        console.log("[app.js] 🎛 History card clicked — jobId:", job.job_id);
        handleHistoryClick(safeStr(job.job_id));
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleHistoryClick(safeStr(job.job_id));
        }
      });

      fragment.appendChild(card);
    });

    historyList.innerHTML = "";
    historyList.appendChild(fragment);
  }

  function escapeHtmlSafe(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function handleHistoryClick(jobId) {
    if (!jobId) return;
    console.log("[app.js] handleHistoryClick — jobId:", jobId);
    App.setActiveJob(jobId);
  }

  function scheduleHistoryRender() {
    dirtyHistory = true;
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () {
      rafPending = false;
      if (dirtyHistory) {
        dirtyHistory = false;
        var filter = historySearch ? historySearch.value.trim() : "";
        renderHistory(filter);
      }
    });
  }

  // ─── localStorage 쓰로틀 ──────────────────────────

  function throttledSaveSnapshots() {
    var now = Date.now();
    if (now - lastLsSave < LS_THROTTLE_MS) {
      if (!lsTimer) {
        lsTimer = setTimeout(function () {
          lsTimer = null;
          throttledSaveSnapshots();
        }, LS_THROTTLE_MS);
      }
      return;
    }
    lastLsSave = now;
    try {
      localStorage.setItem("QCVIZ_ENTERPRISE_V5_UI_SNAPSHOTS", JSON.stringify(App.store.uiSnapshotsByJobId));
      console.log("[app.js] throttledSaveSnapshots — saved to localStorage");
    } catch (_) {}
  }

  // ─── 테마 토글 ────────────────────────────────────

  function toggleTheme() {
    var next = App.store.theme === "dark" ? "light" : "dark";
    console.log("[app.js] 🎛 toggleTheme:", App.store.theme, "→", next);
    App.setTheme(next);
  }

  // ─── 모달 ──────────────────────────────────────────

  function openModal(modal) {
    console.log("[app.js] openModal");

# ... (truncated at 200 lines, 139 lines omitted) ...
```

---

## 📄 `web/static/viewer.js` (302 lines)

```javascript
/**
 * QCViz-MCP v3 — 3D Molecular Viewer
 * FIX(M8): CDN 3개 순차 재시도, 100ms 디바운스, viewerReady 큐잉,
 *          xyz/molecule_xyz→xyz_block 키 매핑
 */
(function (g) {
  "use strict";
  console.log("[viewer.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[viewer.js] ✖ QCVizApp not found — aborting viewer module");
    return;
  }
  console.log("[viewer.js] ✔ QCVizApp found, __v3:", App.__v3);

  // ─── 상수 ──────────────────────────────────────────
  var CDN_URLS = [
    "https://3Dmol.org/build/3Dmol-min.js",
    "https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js",
    "https://unpkg.com/3dmol@2.4.2/build/3Dmol-min.js",
  ];

  var DEBOUNCE_MS = 100;
  var viewerReady = false;
  var viewer = null;
  var pendingUpdate = null;
  var debounceTimer = null;
  var currentResult = null;
  var currentMode = "orbital";

  // ─── DOM refs ──────────────────────────────────────
  var viewer3d = document.getElementById("viewer3d");
  var viewerEmpty = document.getElementById("viewerEmpty");
  var viewerControls = document.getElementById("viewerControls");
  var viewerLegend = document.getElementById("viewerLegend");
  var vizModeToggle = document.getElementById("vizModeToggle");
  var btnViewerReset = document.getElementById("btnViewerReset");
  var btnViewerScreenshot = document.getElementById("btnViewerScreenshot");
  var btnViewerFullscreen = document.getElementById("btnViewerFullscreen");
  var btnModeOrbital = document.getElementById("btnModeOrbital");
  var btnModeESP = document.getElementById("btnModeESP");
  var segStyle = document.getElementById("segStyle");
  var sliderIsovalue = document.getElementById("sliderIsovalue");
  var lblIsovalue = document.getElementById("lblIsovalue");
  var sliderEspDensIso = document.getElementById("sliderEspDensIso");
  var lblEspDensIso = document.getElementById("lblEspDensIso");
  var sliderOpacity = document.getElementById("sliderOpacity");
  var lblOpacity = document.getElementById("lblOpacity");
  var btnToggleLabels = document.getElementById("btnToggleLabels");
  var grpOrbital = document.getElementById("grpOrbital");
  var grpESP = document.getElementById("grpESP");
  var grpOpacity = document.getElementById("grpOpacity");
  var selectColorScheme = document.getElementById("selectColorScheme");
  var grpColorScheme = document.getElementById("grpColorScheme");
  var selectOrbital = document.getElementById("selectOrbital");
  var grpOrbitalSelect = document.getElementById("grpOrbitalSelect");

  // Trajectory controls DOM refs
  var grpTrajectory = document.getElementById("grpTrajectory");
  var btnTrajPlay = document.getElementById("btnTrajPlay");
  var sliderTrajFrame = document.getElementById("sliderTrajFrame");
  var lblTrajFrame = document.getElementById("lblTrajFrame");
  var lblTrajEnergy = document.getElementById("lblTrajEnergy");

  // Trajectory state
  var trajFrames = [];  // array of { step, energy_hartree, grad_norm, xyz }
  var trajPlaying = false;
  var trajInterval = null;

  // Color scheme mapping: name → { pos, neg } for orbital, gradient+invert for ESP
  // 3Dmol supports gradients: "rwb", "roygb", "sinebow"
  var COLOR_SCHEMES = {
    classic: { pos: "blue",    neg: "red",     gradient: "rwb",     invert: false },
    jmol:    { pos: "#3050F8", neg: "#FF8000", gradient: "roygb",   invert: false },  // deep blue / orange
    rwb:     { pos: "#0000CC", neg: "#CC0000", gradient: "rwb",     invert: false },  // darker blue / darker red
    bwr:     { pos: "#CC0000", neg: "#0000CC", gradient: "rwb",     invert: true  },  // swapped: red=pos, blue=neg
    spectral:{ pos: "#2B83BA", neg: "#D7191C", gradient: "sinebow", invert: false },  // teal / crimson
    viridis: { pos: "#21918C", neg: "#FDE725", gradient: "roygb",   invert: true  },  // teal / yellow
    inferno: { pos: "#BB3754", neg: "#FCFFA4", gradient: "sinebow", invert: true  },  // magenta / light yellow
  };

  function getColorScheme() {
    var val = selectColorScheme ? selectColorScheme.value : "classic";
    return COLOR_SCHEMES[val] || COLOR_SCHEMES.classic;
  }

  console.log("[viewer.js] DOM refs:", {
    viewer3d: !!viewer3d, viewerEmpty: !!viewerEmpty,
    viewerControls: !!viewerControls, vizModeToggle: !!vizModeToggle,
    segStyle: !!segStyle, sliderIsovalue: !!sliderIsovalue,
    sliderEspDensIso: !!sliderEspDensIso, sliderOpacity: !!sliderOpacity,
    btnModeOrbital: !!btnModeOrbital, btnModeESP: !!btnModeESP,
    selectColorScheme: !!selectColorScheme, selectOrbital: !!selectOrbital,
  });

  // ─── 유틸 ──────────────────────────────────────────

  function safeStr(v, fb) {
    return v == null ? fb || "" : String(v).trim();
  }

  function show(el) {
    if (el) el.removeAttribute("hidden");
  }
  function hide(el) {
    if (el) el.setAttribute("hidden", "");
  }

  // ─── Style helpers ─────────────────────────────────
  function getActiveStyle() {
    if (segStyle) {
      var activeBtn = segStyle.querySelector(".segmented__btn--active");
      if (activeBtn) return activeBtn.getAttribute("data-value") || "stick";
    }
    return "stick";
  }

  function applyStyle(style) {
    if (!viewer) return;
    var styleMap = {
      stick:     { stick: { radius: 0.15 }, sphere: { scale: 0.25 } },
      ball_stick:{ stick: { radius: 0.12 }, sphere: { scale: 0.3 } },
      sphere:    { sphere: { scale: 0.6 } },
      line:      { line: { linewidth: 2 } },
    };
    viewer.setStyle({}, styleMap[style] || styleMap.stick);
  }

  // ─── 3Dmol 로딩 ───────────────────────────────────

  function load3Dmol(urls, idx) {
    idx = idx || 0;
    console.log("[viewer.js] load3Dmol — trying CDN", idx, "of", urls.length, ":", urls[idx]);
    if (idx >= urls.length) {
      console.error("[viewer.js] ✖ All CDN URLs failed, cannot load 3Dmol.js");
      if (viewerEmpty) {
        viewerEmpty.querySelector(".viewer-empty__text").textContent =
          "Failed to load 3D viewer library. / 3D 뷰어 라이브러리 로드 실패.";
      }
      show(viewerEmpty);
      return;
    }
    var script = document.createElement("script");
    script.src = urls[idx];
    script.onload = function () {
      console.log("[viewer.js] ✔ 3Dmol loaded from CDN", idx, ":", urls[idx]);
      initViewer();
    };
    script.onerror = function () {
      console.warn("[viewer.js] ✖ CDN", idx, "failed:", urls[idx], "— trying next");
      load3Dmol(urls, idx + 1);
    };
    document.head.appendChild(script);
  }

  function initViewer() {
    console.log("[viewer.js] initViewer — $3Dmol:", !!g.$3Dmol, "viewer3d:", !!viewer3d);
    if (!g.$3Dmol || !viewer3d) {
      console.error("[viewer.js] ✖ $3Dmol not available or viewer3d element missing");
      return;
    }

    viewer = g.$3Dmol.createViewer(viewer3d, {
      backgroundColor: "white",
      antialias: true,
    });
    viewerReady = true;
    console.log("[viewer.js] ✔ Viewer created, viewerReady=true");

    if (pendingUpdate) {
      console.log("[viewer.js] Processing queued pendingUpdate");
      var res = pendingUpdate;
      pendingUpdate = null;
      updateViewer(res);
    }
  }

  // ─── XYZ 키 매핑 ──────────────────────────────────

  function extractXyz(result) {
    if (!result) {
      console.log("[viewer.js] extractXyz — result is null/undefined");
      return null;
    }
    var viz = result.visualization || {};
    var xyz =
      viz.xyz_block || viz.xyz || viz.molecule_xyz ||
      result.xyz_block || result.xyz || result.molecule_xyz || null;

    console.log("[viewer.js] extractXyz — keys checked:", {
      "viz.xyz_block": !!viz.xyz_block, "viz.xyz": !!viz.xyz,
      "viz.molecule_xyz": !!viz.molecule_xyz,
      "result.xyz_block": !!result.xyz_block, "result.xyz": !!result.xyz,
      "result.molecule_xyz": !!result.molecule_xyz,
      found: !!xyz, length: xyz ? xyz.length : 0,
    });

    if (!xyz && typeof result === "string") {
      if (result.indexOf("\n") > -1) {
        console.log("[viewer.js] extractXyz — result IS a raw XYZ string, length:", result.length);
        return result;
      }
    }
    return xyz;
  }

  // ─── 뷰어 업데이트 ────────────────────────────────

  function updateViewer(result) {
    console.log("[viewer.js] updateViewer called, viewerReady:", viewerReady, "result:", !!result);
    if (!result) return;

    if (!viewerReady) {
      console.log("[viewer.js] updateViewer — viewer not ready, queuing update");
      pendingUpdate = result;
      return;
    }

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      console.log("[viewer.js] updateViewer — debounce fired, calling _doUpdate");
      _doUpdate(result);
    }, DEBOUNCE_MS);
  }

  function _doUpdate(result) {
    console.log("[viewer.js] ─── _doUpdate START ───");
    currentResult = result;
    var xyz = extractXyz(result);

    if (!xyz) {
      console.warn("[viewer.js] _doUpdate — NO xyz found, showing empty placeholder");
      show(viewerEmpty);
      hide(viewerControls);
      return;
    }

    console.log("[viewer.js] _doUpdate — xyz length:", xyz.length, "first 80 chars:", xyz.substring(0, 80));
    hide(viewerEmpty);
    show(viewerControls);

    console.log("[viewer.js] _doUpdate — viewer.clear()");
    viewer.clear();

    console.log("[viewer.js] _doUpdate — viewer.addModel(xyz, 'xyz', {keepH:true})");
    viewer.addModel(xyz, "xyz", { keepH: true });

    var style = getActiveStyle();
    console.log("[viewer.js] _doUpdate — applyStyle:", style);
    applyStyle(style);
    viewer.render();

    var showLabels =
      btnToggleLabels && btnToggleLabels.getAttribute("data-active") === "true";
    console.log("[viewer.js] _doUpdate — labels:", showLabels);
    if (showLabels) {
      viewer.addPropertyLabels("atom", {}, {
        font: "Arial", fontSize: 11, showBackground: true,
        backgroundColor: 0x222222, backgroundOpacity: 0.6,
      });
    }

    var viz = result.visualization || {};
    var available = viz.available || {};
    console.log("[viewer.js] _doUpdate — available surfaces:", JSON.stringify(available));
    console.log("[viewer.js] _doUpdate — viz keys:", Object.keys(viz).join(", "));
    console.log("[viewer.js] _doUpdate — currentMode:", currentMode);

    if (available.orbital || available.esp) {
      show(vizModeToggle);
    } else {
      hide(vizModeToggle);
    }

    if (available.orbital && grpOrbital) show(grpOrbital);
    else hide(grpOrbital);
    if (available.esp && grpESP) show(grpESP);
    else hide(grpESP);
    if ((available.orbital || available.esp) && grpOpacity) show(grpOpacity);
    else hide(grpOpacity);

    console.log("[viewer.js] _doUpdate — calling addSurface");
    addSurface(result);

    // Populate orbital select dropdown
    _populateOrbitalDropdown(result);

    console.log("[viewer.js] _doUpdate — final zoomTo + render");
    viewer.zoomTo();
    viewer.render();

    // Setup trajectory controls if geo_opt result
    setupTrajectory(result);

    var jobId = safeStr(result.job_id || (viz).job_id);
    if (jobId) {
      var snap = {
        style: style,
        isovalue: sliderIsovalue ? parseFloat(sliderIsovalue.value) : 0.03,

# ... (truncated at 300 lines, 561 lines omitted) ...
```

---

## 📄 `web/static/results.js` (202 lines)

```javascript
/**
 * QCViz-MCP v3 — Results Panel
 * FIX(M9): created_at 안정 정렬, MAX_RETAINED=100 eviction,
 *          clampIndex, 키 매핑, 메모리 누수 방지
 */
(function (g) {
  "use strict";
  console.log("[results.js] ▶ Module loading...");

  var App = g.QCVizApp;
  if (!App) {
    console.error("[results.js] ✖ QCVizApp not found — aborting results module");
    return;
  }
  console.log("[results.js] ✔ QCVizApp found");

  // ─── 상수 ──────────────────────────────────────────
  var MAX_RETAINED_RESULTS = 100;
  var TAB_KEYS = ["summary", "geometry", "orbital", "esp", "charges", "json"];

  // ─── DOM refs ──────────────────────────────────────
  var resultsTabs = document.getElementById("resultsTabs");
  var resultsContent = document.getElementById("resultsContent");
  var resultsEmpty = document.getElementById("resultsEmpty");

  console.log("[results.js] DOM refs:", {
    resultsTabs: !!resultsTabs, resultsContent: !!resultsContent, resultsEmpty: !!resultsEmpty,
  });

  // ─── 상태 ──────────────────────────────────────────
  var activeTab = "summary";
  var resultHistory = [];

  // ─── 유틸 ──────────────────────────────────────────
  function safeStr(v, fb) { return v == null ? fb || "" : String(v).trim(); }
  function safeNum(v, fb) { var n = parseFloat(v); return isFinite(n) ? n : fb || 0; }
  function show(el) { if (el) el.removeAttribute("hidden"); }
  function hide(el) { if (el) el.setAttribute("hidden", ""); }
  function escapeHtml(str) { var div = document.createElement("div"); div.textContent = str; return div.innerHTML; }

  function mapResultKeys(r) {
    if (!r) return r;
    if (r.total_energy_hartree != null && r.energy_hartree == null) r.energy_hartree = r.total_energy_hartree;
    if (r.total_energy_ev != null && r.energy_ev == null) r.energy_ev = r.total_energy_ev;
    var viz = r.visualization || {};
    if (!viz.xyz_block) viz.xyz_block = viz.xyz || viz.molecule_xyz || r.xyz || null;
    r.visualization = viz;
    console.log("[results.js] mapResultKeys — energy_ha:", r.energy_hartree,
      "viz_xyz:", !!viz.xyz_block, "viz.available:", JSON.stringify(viz.available || {}));
    return r;
  }

  // ─── 탭 렌더링 ────────────────────────────────────

  function renderTabs(result) {
    if (!resultsTabs) return;
    console.log("[results.js] renderTabs — activeTab:", activeTab);
    resultsTabs.innerHTML = "";

    var viz = result && result.visualization ? result.visualization : {};
    var available = viz.available || {};

    TAB_KEYS.forEach(function (key) {
      var btn = document.createElement("button");
      btn.className = "results-tab" + (key === activeTab ? " results-tab--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", key === activeTab ? "true" : "false");
      btn.setAttribute("data-tab", key);
      btn.textContent = key.charAt(0).toUpperCase() + key.slice(1);

      if (key === "orbital" && !available.orbital) {
        btn.disabled = true; btn.classList.add("results-tab--disabled");
      }
      if (key === "esp" && !available.esp) {
        btn.disabled = true; btn.classList.add("results-tab--disabled");
      }

      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        console.log("[results.js] 🎛 Tab clicked:", key);
        activeTab = key;
        renderTabs(result);
        renderContent(result);
      });

      resultsTabs.appendChild(btn);
    });
  }

  function renderContent(result) {
    if (!resultsContent) return;
    console.log("[results.js] renderContent — tab:", activeTab, "has result:", !!result);

    if (!result) {
      show(resultsEmpty);
      resultsContent.querySelectorAll(".results-pane").forEach(function (el) { el.remove(); });
      return;
    }

    hide(resultsEmpty);
    result = mapResultKeys(result);

    resultsContent.querySelectorAll(".results-pane").forEach(function (el) { el.remove(); });

    var pane = document.createElement("div");
    pane.className = "results-pane";

    switch (activeTab) {
      case "summary": pane.innerHTML = renderSummary(result); break;
      case "geometry": pane.innerHTML = renderGeometry(result); break;
      case "orbital": pane.innerHTML = renderOrbital(result); break;
      case "esp": pane.innerHTML = renderEsp(result); break;
      case "charges": pane.innerHTML = renderCharges(result); break;
      case "json": pane.innerHTML = renderJson(result); break;
      default: pane.innerHTML = "<p>Unknown tab</p>";
    }

    resultsContent.appendChild(pane);

    // Bind orbital table row clicks → dispatch orbital-selected event
    pane.querySelectorAll("tr[data-orbital-label]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        var label = this.getAttribute("data-orbital-label");
        console.log("[results.js] orbital row clicked:", label);
        document.dispatchEvent(new CustomEvent("orbital-selected", { detail: { label: label } }));
        // Highlight selected row
        pane.querySelectorAll("tr[data-orbital-label]").forEach(function (r) {
          r.classList.remove("result-table__highlight");
        });
        this.classList.add("result-table__highlight");
      });
    });

    console.log("[results.js] renderContent — done for tab:", activeTab);
  }

  // ─── 개별 탭 HTML 생성 ─────────────────────────────

  function renderSummary(r) {
    console.log("[results.js] renderSummary — structure:", r.structure_name || r.structure_query,
      "job_type:", r.job_type, "method:", r.method, "basis:", r.basis);
    var parts = [];
    parts.push('<div class="result-section">');
    parts.push('<h3 class="result-section__title">Summary</h3>');
    parts.push('<table class="result-table">');

    var rows = [
      ["Structure", escapeHtml(safeStr(r.structure_name || r.structure_query, "—"))],
      ["Job Type", escapeHtml(safeStr(r.job_type, "—"))],
      ["Method", escapeHtml(safeStr(r.method, "—"))],
      ["Basis", escapeHtml(safeStr(r.basis, "—"))],
      ["Charge", safeStr(r.charge, "0")],
      ["Multiplicity", safeStr(r.multiplicity, "1")],
      ["# Atoms", safeStr(r.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(r.formula, "—"))],
    ];

    if (r.total_energy_hartree != null) rows.push(["Energy (Ha)", safeNum(r.total_energy_hartree).toFixed(8)]);
    if (r.total_energy_ev != null) rows.push(["Energy (eV)", safeNum(r.total_energy_ev).toFixed(4)]);
    if (r.orbital_gap_ev != null) rows.push(["HOMO-LUMO Gap (eV)", safeNum(r.orbital_gap_ev).toFixed(4)]);
    if (r.scf_converged != null) rows.push(["SCF Converged", r.scf_converged ? "Yes" : "No"]);
    if (r.dipole_moment) rows.push(["Dipole (Debye)", safeNum(r.dipole_moment.magnitude).toFixed(4)]);

    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td>");
      parts.push('<td class="result-table__val">' + row[1] + "</td></tr>");
    });
    parts.push("</table></div>");

    var warnings = r.warnings || [];
    if (warnings.length > 0) {
      console.log("[results.js] renderSummary — warnings:", warnings.length);
      parts.push('<div class="result-section result-section--warnings">');
      parts.push("<h4>Warnings</h4><ul>");
      warnings.forEach(function (w) { parts.push("<li>" + escapeHtml(w) + "</li>"); });
      parts.push("</ul></div>");
    }
    return parts.join("");
  }

  function renderGeometry(r) {
    console.log("[results.js] renderGeometry — atoms:", (r.atoms||[]).length, "bonds:", (r.bonds||[]).length);
    var geo = r.geometry_summary || {};
    var parts = [];
    parts.push('<div class="result-section"><h3 class="result-section__title">Geometry</h3>');
    parts.push('<table class="result-table">');
    var rows = [
      ["# Atoms", safeStr(geo.n_atoms, "—")],
      ["Formula", escapeHtml(safeStr(geo.formula || r.formula, "—"))],
      ["# Bonds", safeStr(geo.bond_count, "—")],
    ];
    if (geo.bond_length_min_angstrom != null) rows.push(["Min Bond (Å)", safeNum(geo.bond_length_min_angstrom).toFixed(4)]);
    if (geo.bond_length_max_angstrom != null) rows.push(["Max Bond (Å)", safeNum(geo.bond_length_max_angstrom).toFixed(4)]);
    if (geo.bond_length_mean_angstrom != null) rows.push(["Mean Bond (Å)", safeNum(geo.bond_length_mean_angstrom).toFixed(4)]);
    rows.forEach(function (row) {
      parts.push('<tr><td class="result-table__key">' + row[0] + "</td><td class=\"result-table__val\">" + row[1] + "</td></tr>");
    });
    parts.push("</table>");
    var atoms = r.atoms || [];
    if (atoms.length > 0 && atoms.length <= 100) {

# ... (truncated at 200 lines, 199 lines omitted) ...
```
