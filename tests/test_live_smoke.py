from __future__ import annotations

import os

import pytest

from qcviz_mcp.services.gemini_agent import GeminiAgent
from qcviz_mcp.services.molchat_client import MolChatClient


def _live_enabled() -> bool:
    return os.getenv("RUN_LIVE_API_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.live
def test_live_gemini_planner_smoke() -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_API_TESTS=1 to enable live external API smoke tests.")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not configured.")

    agent = GeminiAgent()
    result = agent.parse_sync("water HOMO 보여줘")

    assert result is not None
    plan = result.to_plan_dict()
    assert plan["provider"] == "gemini"
    assert plan["job_type"] in {"orbital_preview", "analyze", "resolve_structure"}
    assert plan["confidence"] > 0


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_molchat_api_smoke() -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_API_TESTS=1 to enable live external API smoke tests.")

    client = MolChatClient()
    try:
        resolved = await client.resolve(["water"])
        assert resolved
        assert resolved[0]["cid"]

        card = await client.get_card("water")
        assert card is not None
        smiles = card.get("canonical_smiles") or card.get("smiles")
        assert smiles

        sdf = await client.generate_3d_sdf(smiles)
        assert sdf
        assert "V2000" in sdf or "V3000" in sdf
    finally:
        await client.close()
