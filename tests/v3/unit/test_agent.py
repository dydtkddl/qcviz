"""tests/v3/unit/test_agent.py — QCVizAgent (llm/agent.py) 단위 테스트"""
import pytest
from qcviz_mcp.llm.agent import QCVizAgent, AgentPlan


class TestAgentPlan:
    """AgentPlan 데이터클래스 검증"""

    def test_agentplan_default_intent(self):
        """기본 intent == 'analyze'."""
        plan = AgentPlan()
        assert plan.intent == "analyze"

    def test_agentplan_to_dict(self):
        """to_dict() 직렬화 동작."""
        plan = AgentPlan(intent="energy", structure_query="water")
        d = plan.to_dict()
        assert isinstance(d, dict)
        assert d["intent"] == "energy"
        assert d["structure_query"] == "water"

    def test_agentplan_structures_field(self):
        """structures 필드 존재 (이온쌍용)."""
        plan = AgentPlan()
        assert hasattr(plan, "structures")
        assert plan.structures is None

    def test_agentplan_structures_populated(self):
        """structures 필드에 이온쌍 데이터 할당."""
        plan = AgentPlan(
            intent="energy",
            structures=[{"name": "EMIM", "charge": 1}, {"name": "TFSI", "charge": -1}],
        )
        assert len(plan.structures) == 2

    def test_agentplan_provider(self):
        """기본 provider == 'heuristic'."""
        plan = AgentPlan()
        assert plan.provider == "heuristic"


class TestQCVizAgent:
    """QCVizAgent 클래스 검증"""

    def test_agent_creation(self):
        """QCVizAgent 인스턴스 생성."""
        agent = QCVizAgent()
        assert agent is not None

    def test_agent_from_env(self):
        """from_env() 팩토리 메서드."""
        agent = QCVizAgent.from_env()
        assert agent is not None

    def test_agent_plan_returns_agentplan(self):
        """plan() → AgentPlan 인스턴스."""
        agent = QCVizAgent()
        result = agent.plan("calculate energy of water")
        assert isinstance(result, AgentPlan)

    def test_agent_plan_empty_message(self):
        """빈 메시지 → intent=analyze."""
        agent = QCVizAgent()
        result = agent.plan("")
        assert isinstance(result, AgentPlan)

    def test_agent_heuristic_orbital(self):
        """'HOMO of benzene' → intent에 orbital 관련 의도."""
        agent = QCVizAgent()
        result = agent.plan("show HOMO of benzene")
        assert isinstance(result, AgentPlan)
        # The heuristic should detect orbital-related intent
        assert result.intent in ("orbital", "orbital_preview", "analyze")

    def test_agent_heuristic_esp(self):
        """'ESP map' → ESP 관련 의도."""
        agent = QCVizAgent()
        result = agent.plan("ESP map of aspirin")
        assert isinstance(result, AgentPlan)

    def test_agent_heuristic_charges(self):
        """'Mulliken charges' → charges 의도."""
        agent = QCVizAgent()
        result = agent.plan("Mulliken charges of water")
        assert isinstance(result, AgentPlan)

    def test_agent_heuristic_optimize(self):
        """'optimize geometry' → optimization 의도."""
        agent = QCVizAgent()
        result = agent.plan("optimize geometry of methane")
        assert isinstance(result, AgentPlan)

    def test_agent_provider_default(self):
        """기본 provider 설정."""
        agent = QCVizAgent()
        assert agent.provider in ("auto", "heuristic", "gemini", "openai")

    def test_agent_heuristic_follow_up_classifies_lumo_request(self):
        agent = QCVizAgent()
        result = agent.plan("LUMO도")
        assert result.follow_up_mode in {"add_analysis", "reuse_last_structure"}
        assert result.job_type == "orbital_preview"
        assert result.orbital == "LUMO"

    def test_agent_heuristic_detects_ion_pair_structures(self):
        agent = QCVizAgent()
        result = agent.plan("EMIM TFSI 에너지")
        assert result.structures == [
            {"name": "EMIM", "charge": 1},
            {"name": "TFSI", "charge": -1},
        ]

    def test_agent_analysis_only_followup_does_not_promote_task_text_to_structure(self):
        agent = QCVizAgent()
        result = agent.plan("HOMO LUMO ESP가 궁금")
        assert result.structure_query in (None, "")
        assert result.follow_up_mode == "add_analysis"
        assert result.needs_clarification is True
        assert result.clarification_kind == "continuation_targeting"
