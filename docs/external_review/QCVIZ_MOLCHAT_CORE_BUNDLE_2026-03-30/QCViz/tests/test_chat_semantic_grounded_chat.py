from __future__ import annotations

from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route


def test_chat_rest_semantic_question_returns_grounded_chat_response_without_clarification(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "llm",
                "candidates": [
                    {
                        "name": "Ethanolamine",
                        "cid": 7003,
                        "molecular_formula": "C2H7NO",
                        "confidence": 0.93,
                        "source": "llm",
                        "rationale": "MEA is commonly used as an abbreviation for monoethanolamine / ethanolamine.",
                    }
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)

    resp = client.post("/api/chat", json={"message": "MEA라는 물질이 뭐야?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert data["job"] is None
    assert data["plan"]["intent"] == "chat"
    assert data["plan"]["query_kind"] == "chat_only"
    assert data["plan"]["semantic_grounding_needed"] is True
    assert "Ethanolamine" in data["message"]
    assert "HOMO/LUMO" in data["message"]
    assert "requires_clarification" not in data


def test_chat_rest_semantic_question_with_single_grounded_candidate_does_not_open_picker(
    client, patch_fake_runners, monkeypatch
):
    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            return {
                "query": query,
                "query_mode": "semantic_descriptor",
                "resolution_method": "llm",
                "candidates": [
                    {
                        "name": "2,4,6-TRINITROTOLUENE",
                        "cid": 8376,
                        "molecular_formula": "C7H5N3O6",
                        "confidence": 0.99,
                        "source": "llm",
                        "rationale": "The main component of TNT is trinitrotoluene.",
                    }
                ],
                "notes": [],
            }

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)

    resp = client.post("/api/chat", json={"message": "TNT에 들어가는 주물질이 뭐지?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["chat_only"] is True
    assert data["job"] is None
    assert data["plan"]["intent"] == "chat"
    assert data["plan"]["query_kind"] == "chat_only"
    assert "2,4,6-TRINITROTOLUENE" in data["message"]
    assert "requires_clarification" not in data
