from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from qcviz_mcp.llm.agent import QCVizAgent
from qcviz_mcp.llm.normalizer import extract_structure_candidate, normalize_user_text
from qcviz_mcp.services.structure_resolver import StructureResolver, StructureResult


@pytest.mark.contract
def test_normalize_user_text_handles_typo_and_spacing():
    normalized = normalize_user_text("무ㄹ오비탈 계산")
    assert normalized["normalized_text"]
    assert normalized["maybe_structure_hint"] == "water"
    assert normalized["maybe_task_hint"] == "orbital_preview"


@pytest.mark.contract
def test_extract_structure_candidate_handles_ion_pair_like_input():
    candidate = extract_structure_candidate("TFSI- EMIM +이온쌍에 대한 계산 ㄱㄱ")
    assert candidate == "TFSI- EMIM +"


@pytest.mark.contract
def test_normalize_user_text_prefers_anion_specific_tfsi_name():
    normalized = normalize_user_text("TFSI- 에너지 계산")
    assert "bis(trifluoromethanesulfonyl)azanide" in normalized["normalized_text"]
    assert "bis(trifluoromethanesulfonyl)azanide" in normalized["candidate_queries"]


@pytest.mark.contract
def test_qcviz_agent_heuristic_plan_populates_step1_fields():
    agent = QCVizAgent(provider="none")
    plan = agent.plan("무ㄹ오비탈 계산")
    assert plan.provider == "heuristic"
    assert plan.structure_query == "water"
    assert plan.job_type == "orbital_preview"
    assert plan.normalized_text
    assert "orbital" in plan.missing_slots
    assert plan.needs_clarification is True


@pytest.mark.asyncio
@pytest.mark.contract
async def test_structure_resolver_query_plan_retries_candidates():
    resolver = StructureResolver()
    mocked = StructureResult(
        xyz="25\nemim\nC 0 0 0",
        smiles="CC[n+]1ccn(C)c1",
        cid=123,
        name="1-ethyl-3-methylimidazolium",
        source="molchat",
    )
    with patch.object(resolver, "_try_molchat", new=AsyncMock(side_effect=[None, mocked])):
        with patch.object(resolver, "_try_pubchem", new=AsyncMock(return_value=None)):
            result = await resolver.resolve("emim+")
    assert result.source == "molchat"
    assert result.query_plan["raw_query"] == "emim+"
    assert "1-ethyl-3-methylimidazolium" in result.query_plan["candidate_queries"]


@pytest.mark.contract
def test_structure_resolver_query_plan_prefers_tfsi_anion():
    resolver = StructureResolver()
    query_plan = resolver._build_query_plan("TFSI-")
    assert query_plan["candidate_queries"][0] == "bis(trifluoromethanesulfonyl)azanide"
    assert query_plan["expected_charge"] == -1
