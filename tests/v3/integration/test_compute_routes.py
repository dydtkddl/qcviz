"""tests/v3/integration/test_compute_routes.py — 계산 라우트 통합 테스트

PySCF가 없는 환경에서도 라우트 등록 및 기본 API 동작을 테스트합니다.
실제 PySCF 계산은 requires_pyscf 마커로 보호합니다.
"""
import sys
import pytest
from unittest.mock import MagicMock

# PySCF mock — Windows에서 pyscf 없이 compute route import 가능하도록
if "pyscf" not in sys.modules:
    pyscf_mock = MagicMock()
    pyscf_mock.__version__ = "2.4.0"
    pyscf_mock.gto = MagicMock()
    pyscf_mock.scf = MagicMock()
    pyscf_mock.dft = MagicMock()
    pyscf_mock.tools = MagicMock()
    pyscf_mock.tools.cubegen = MagicMock()
    sys.modules["pyscf"] = pyscf_mock
    sys.modules["pyscf.gto"] = pyscf_mock.gto
    sys.modules["pyscf.scf"] = pyscf_mock.scf
    sys.modules["pyscf.dft"] = pyscf_mock.dft
    sys.modules["pyscf.tools"] = pyscf_mock.tools
    sys.modules["pyscf.tools.cubegen"] = pyscf_mock.tools.cubegen
    sys.modules["pyscf.geomopt"] = MagicMock()
    sys.modules["pyscf.geomopt.geometric_solver"] = MagicMock()
    sys.modules["pyscf.lib"] = MagicMock()

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.fixture
def app(isolated_job_manager, patch_fake_runners):
    """FastAPI 앱 조립"""
    from qcviz_mcp.web.routes.compute import router as compute_router
    _app = FastAPI()
    _app.include_router(compute_router)
    return _app


@pytest.fixture
async def client(app):
    """httpx AsyncClient"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestComputeHealth:
    """GET /compute/health"""

    @pytest.mark.asyncio
    async def test_compute_health_ok(self, client):
        """헬스체크 → 200, ok=true."""
        resp = await client.get("/compute/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "route" in data
        assert "queue" in data
        assert data["queue"]["max_workers"] >= 1


class TestListJobs:
    """GET /compute/jobs"""

    @pytest.mark.asyncio
    async def test_list_jobs(self, client):
        """잡 목록 → 200, items 배열."""
        resp = await client.get("/compute/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert "queue" in data


class TestSubmitJob:
    """POST /compute/jobs"""

    @pytest.mark.asyncio
    async def test_submit_job_returns_job_id(self, client):
        """잡 제출 → job_id 반환."""
        resp = await client.post(
            "/compute/jobs",
            json={"message": "test water energy", "xyz": "3\\nwater\\nO 0 0 0.11\\nH 0 0.76 -0.47\\nH 0 -0.76 -0.47"},
        )
        # Must return 200 with job_id
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client):
        """존재하지 않는 job → 404."""
        resp = await client.get("/compute/jobs/nonexistent-id-12345")
        assert resp.status_code == 404
