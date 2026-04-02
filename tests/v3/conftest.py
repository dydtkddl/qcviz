"""tests/v3/conftest.py — v3 테스트 공용 fixture 모음"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from typing import Any, Dict

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 테스트용 환경변수 설정
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key-for-testing")
os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")
os.environ.setdefault("MOLCHAT_BASE_URL", "http://psid.aizen.co.kr/molchat")
os.environ.setdefault("QCVIZ_LOG_LEVEL", "WARNING")

# PySCF availability flag
try:
    import pyscf  # noqa: F401
    HAS_PYSCF = True
except ImportError:
    HAS_PYSCF = False

requires_pyscf = pytest.mark.skipif(not HAS_PYSCF, reason="PySCF not installed")

# ─── 샘플 데이터 ────────────────────────────────────

WATER_XYZ = """3
water
O   0.000000   0.000000   0.117300
H   0.000000   0.757200  -0.469200
H   0.000000  -0.757200  -0.469200"""

H2_XYZ = """2
hydrogen
H   0.000000   0.000000   0.000000
H   0.000000   0.000000   0.740000"""

WATER_SDF = """
     RDKit          3D

  3  2  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.1173 O   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000    0.7572   -0.4692 H   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000   -0.7572   -0.4692 H   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
  1  3  1  0
M  END
$$$$"""

ETHANOL_SDF = """
     RDKit          3D

  9  8  0  0  0  0  0  0  0  0999 V2000
   -0.0400   -0.0200    0.0300 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.4500    0.0100   -0.0200 C   0  0  0  0  0  0  0  0  0  0  0  0
    2.0200    1.2000    0.5800 O   0  0  0  0  0  0  0  0  0  0  0  0
   -0.4200    0.8600    0.5500 H   0  0  0  0  0  0  0  0  0  0  0  0
   -0.4300   -0.0500   -0.9900 H   0  0  0  0  0  0  0  0  0  0  0  0
   -0.3800   -0.9200    0.5400 H   0  0  0  0  0  0  0  0  0  0  0  0
    1.8300   -0.8800    0.4900 H   0  0  0  0  0  0  0  0  0  0  0  0
    1.8100   -0.0100   -1.0500 H   0  0  0  0  0  0  0  0  0  0  0  0
    2.9800    1.1900    0.5600 H   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
  2  3  1  0
  1  4  1  0
  1  5  1  0
  1  6  1  0
  2  7  1  0
  2  8  1  0
  3  9  1  0
M  END
$$$$"""

MOLCHAT_RESOLVE_WATER = {"resolved": [{"name": "water", "cid": 962}], "total": 1}
MOLCHAT_CARD_WATER = {
    "cid": 962, "name": "oxidane",
    "canonical_smiles": "O", "molecular_formula": "H2O", "molecular_weight": 18.015,
}
PUBCHEM_CID_WATER = {"IdentifierList": {"CID": [962]}}
PUBCHEM_SMILES_WATER = {"PropertyTable": {"Properties": [{"CID": 962, "CanonicalSMILES": "O"}]}}


# ─── Fixtures ────────────────────────────────────────

@pytest.fixture
def water_xyz():
    return WATER_XYZ

@pytest.fixture
def h2_xyz():
    return H2_XYZ

@pytest.fixture
def water_sdf():
    return WATER_SDF

@pytest.fixture
def ethanol_sdf():
    return ETHANOL_SDF

@pytest.fixture
def config():
    """테스트용 ServerConfig"""
    from qcviz_mcp.config import ServerConfig
    return ServerConfig.from_env()

@pytest.fixture
def mock_httpx_response():
    """Reusable httpx response mock factory"""
    def _make(status_code=200, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json = MagicMock(return_value=json_data or {})
        resp.text = text
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            import httpx
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=resp
            )
        return resp
    return _make
