from __future__ import annotations

import pytest

from app.services.molecule_engine.orchestrator import MoleculeOrchestrator
from app.services.molecule_engine.pug_rest_resolver import PugRestResult
from app.services.molecule_engine.query_resolver import InterpretedCandidate, QueryResolver


class _FakeGeminiClient:
    async def generate(self, messages, temperature=0.0, max_tokens=500):
        return {
            "content": """
            {
              "candidates": [
                {"name": "nitrobenzene", "confidence": 0.82, "rationale": "common nitration-related aromatic precursor"},
                {"name": "toluene", "confidence": 0.55, "rationale": "common TNT synthesis precursor family"}
              ]
            }
            """
        }


@pytest.mark.asyncio
async def test_query_resolver_interpret_candidates_uses_semantic_mode():
    resolver = QueryResolver(gemini_client=_FakeGeminiClient())
    mode, normalized_query, resolution_method, notes, candidates = await resolver.interpret_candidates(
        "TNT에 들어가는 주물질",
        limit=5,
    )
    assert mode == "semantic_descriptor"
    assert normalized_query is None
    assert resolution_method is None
    assert candidates
    assert candidates[0].name == "nitrobenzene"
    assert "semantic candidates" in " ".join(notes)


@pytest.mark.asyncio
async def test_orchestrator_interpret_candidates_filters_to_grounded_results(monkeypatch):
    orchestrator = object.__new__(MoleculeOrchestrator)
    class _FakeResolver:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return (
                "semantic_descriptor",
                None,
                None,
                ["semantic candidates proposed by Gemini and require PubChem grounding"],
                [
                    InterpretedCandidate(
                        name="nitrobenzene",
                        source="semantic_llm",
                        confidence=0.82,
                        rationale="common nitration-related aromatic precursor",
                    ),
                    InterpretedCandidate(
                        name="unknown semantic thing",
                        source="semantic_llm",
                        confidence=0.40,
                        rationale="should be dropped after grounding",
                    ),
                ],
            )

    orchestrator._resolver = _FakeResolver()

    async def _fake_resolve_name_to_cid(name: str, timeout: float = 8.0):
        if name == "nitrobenzene":
            return PugRestResult(
                found=True,
                cid=7416,
                name="nitrobenzene",
                molecular_formula="C6H5NO2",
                molecular_weight=123.11,
                canonical_smiles="O=[N+]([O-])c1ccccc1",
            )
        return PugRestResult(found=False, error="not found")

    monkeypatch.setattr(
        "app.services.molecule_engine.orchestrator.resolve_name_to_cid",
        _fake_resolve_name_to_cid,
    )

    response = await orchestrator.interpret_candidates("TNT에 들어가는 주물질", limit=5)
    assert response.query_mode == "semantic_descriptor"
    assert len(response.candidates) == 1
    assert response.candidates[0].name == "nitrobenzene"
