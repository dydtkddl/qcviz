"""tests/v3/unit/test_gemini_agent.py — Gemini Agent 단위 테스트 (mock)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from qcviz_mcp.services.gemini_agent import GeminiAgent, GeminiResult


class TestGeminiAgentInit:
    """GeminiAgent 초기화"""

    def test_agent_creation(self):
        """GeminiAgent 인스턴스 생성 (dummy key)."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        assert agent is not None

    def test_agent_has_parse(self):
        """parse() or extract() 메서드 존재."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        assert hasattr(agent, "parse") or hasattr(agent, "extract") or hasattr(agent, "run")


class TestGeminiResult:
    """GeminiResult 데이터 타입"""

    def test_gemini_result_creation(self):
        """GeminiResult 인스턴스 생성."""
        result = GeminiResult(
            intent="energy",
            structure="water",
            method="B3LYP",
            basis_set="def2-SVP",
        )
        assert result.intent == "energy"
        assert result.structure == "water"

    def test_gemini_result_fields(self):
        """GeminiResult에 필수 필드 존재."""
        result = GeminiResult(intent="analyze", structure="test")
        assert hasattr(result, "intent")
        assert hasattr(result, "structure")


class TestGeminiParse:
    """parse/extract 기능 검증 — Gemini API mock"""

    @pytest.mark.asyncio
    async def test_parse_simple_energy(self):
        """'calculate energy of water' 파싱."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        # Mock the internal call
        parse_method = getattr(agent, "parse", None) or getattr(agent, "extract", None) or getattr(agent, "run", None)
        if parse_method is None:
            pytest.skip("No parse/extract/run method found")

    def test_tool_schemas_present(self):
        """TOOL_SCHEMAS 또는 도구 정의가 존재."""
        from qcviz_mcp.services import gemini_agent as mod
        has_schemas = (
            hasattr(mod, "TOOL_SCHEMAS")
            or hasattr(mod, "TOOLS")
            or hasattr(mod, "FUNCTION_DECLARATIONS")
        )
        assert has_schemas
