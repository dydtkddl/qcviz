"""tests/v3/integration/test_chat_routes.py — 채팅 라우트 통합 테스트"""
import sys
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

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.fixture
def app(isolated_job_manager, patch_fake_runners):
    """FastAPI 앱 조립 (chat + compute routes)"""
    from qcviz_mcp.web.routes.compute import router as compute_router
    from qcviz_mcp.web.routes.chat import router as chat_router
    _app = FastAPI()
    _app.include_router(compute_router)
    _app.include_router(chat_router)
    return _app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestChatHealth:
    """GET /chat/health"""

    @pytest.mark.asyncio
    async def test_chat_health_ok(self, client):
        """헬스체크 → 200, ok=true."""
        resp = await client.get("/chat/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True


class TestPostChat:
    """POST /chat"""

    @pytest.mark.asyncio
    async def test_post_chat_returns_plan(self, client):
        """채팅 메시지 → plan/job 반환."""
        resp = await client.post(
            "/chat",
            json={"message": "calculate water energy", "xyz": "3\\nwater\\nO 0 0 0.11\\nH 0 0.76 -0.47\\nH 0 -0.76 -0.47"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data or "job" in data


try:
    from httpx_ws import aconnect_ws
    from httpx_ws.transport import ASGIWebSocketTransport
    HAS_HTTPX_WS = True
except ImportError:
    HAS_HTTPX_WS = False


@pytest.mark.skipif(not HAS_HTTPX_WS, reason="httpx-ws not installed")
class TestWebSocketChat:
    """WebSocket /ws/chat"""

    @pytest.mark.asyncio
    async def test_websocket_connect(self, app):
        """WebSocket 연결 → ready 메시지."""
        transport = ASGIWebSocketTransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with aconnect_ws("/ws/chat", client) as ws:
                msg = await ws.receive_json()
                assert msg.get("type") == "ready"

    @pytest.mark.asyncio
    async def test_websocket_ping(self, app):
        """WebSocket ping → ack 응답."""
        transport = ASGIWebSocketTransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with aconnect_ws("/ws/chat", client) as ws:
                msg = await ws.receive_json()  # ready
                await ws.send_json({"type": "ping"})
                ack = await ws.receive_json()
                assert ack.get("type") == "ack"

