"""tests/v3/integration/test_job_manager.py — JobManager 통합 테스트"""
import sys
import time
import pytest
from unittest.mock import MagicMock

# PySCF mock
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

from qcviz_mcp.web.routes.compute import InMemoryJobManager, TERMINAL_STATES


class TestJobManagerBasic:
    """JobManager 기본 동작"""

    def test_submit_returns_snapshot(self):
        """submit() → job_id 포함 snapshot."""
        mgr = InMemoryJobManager(max_workers=1)
        snap = mgr.submit({"message": "test", "xyz": "2\\nH2\\nH 0 0 0\\nH 0 0 0.74", "job_type": "analyze"})
        assert "job_id" in snap
        assert snap["status"] in ("queued", "running")

    def test_get_returns_none_for_unknown(self):
        """get(unknown_id) → None."""
        mgr = InMemoryJobManager(max_workers=1)
        assert mgr.get("nonexistent") is None

    def test_list_returns_list(self):
        """list() → 리스트 반환."""
        mgr = InMemoryJobManager(max_workers=1)
        items = mgr.list()
        assert isinstance(items, list)


class TestJobManagerOperations:
    """JobManager 상세 동작"""

    def test_submit_and_get(self):
        """submit → get → 결과 확인."""
        mgr = InMemoryJobManager(max_workers=1)
        snap = mgr.submit({"message": "test", "xyz": "2\\nH2\\nH 0 0 0\\nH 0 0 0.74"})
        job_id = snap["job_id"]
        result = mgr.get(job_id)
        assert result is not None
        assert result["job_id"] == job_id

    def test_submit_multiple(self):
        """여러 잡 submit → list에 전부 존재."""
        mgr = InMemoryJobManager(max_workers=2)
        ids = []
        for i in range(3):
            snap = mgr.submit({"message": f"test {i}", "xyz": "2\\nH2\\nH 0 0 0\\nH 0 0 0.74"})
            ids.append(snap["job_id"])
        time.sleep(0.5)  # let jobs start
        items = mgr.list()
        listed_ids = [j["job_id"] for j in items]
        for jid in ids:
            assert jid in listed_ids

    def test_snapshot_has_required_fields(self):
        """snapshot에 필수 필드 존재."""
        mgr = InMemoryJobManager(max_workers=1)
        snap = mgr.submit({"message": "test"})
        required = ["job_id", "status", "progress", "created_at"]
        for key in required:
            assert key in snap, f"Missing key: {key}"
