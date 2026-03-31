from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from qcviz_mcp.services.molchat_client import MolChatClient


@pytest.fixture
def client():
    return MolChatClient(base_url="http://mock-molchat:8000", timeout=5.0)


@pytest.fixture
def mock_response_ok():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_resolve_returns_cid_entries_only(client, mock_response_ok):
    mock_response_ok.json = MagicMock(
        return_value={"resolved": [{"name": "water", "cid": 962}, {"name": "bad", "cid": None}], "total": 2}
    )
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response_ok)
        mock_client_cls.return_value = instance
        result = await client.resolve(["water", "bad"])
    assert result == [{"name": "water", "cid": 962}]


@pytest.mark.asyncio
async def test_resolve_empty_returns_empty_list(client):
    assert await client.resolve([]) == []


@pytest.mark.asyncio
async def test_interpret_candidates_returns_structured_payload(client, mock_response_ok):
    mock_response_ok.json = MagicMock(
        return_value={
            "query": "TNT에 들어가는 주물질",
            "query_mode": "semantic_descriptor",
            "candidates": [
                {"name": "nitrobenzene", "cid": 7416, "confidence": 0.82, "source": "semantic_llm"},
                {"name": "toluene", "cid": 1140, "confidence": 0.55, "source": "semantic_llm"},
            ],
            "notes": ["semantic candidates proposed by Gemini and require PubChem grounding"],
        }
    )
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response_ok)
        mock_client_cls.return_value = instance
        result = await client.interpret_candidates("TNT에 들어가는 주물질")
    assert result["query_mode"] == "semantic_descriptor"
    assert result["candidates"][0]["name"] == "nitrobenzene"


@pytest.mark.asyncio
async def test_interpret_candidates_falls_back_to_search_when_endpoint_unavailable(client):
    post_resp = MagicMock()
    post_resp.status_code = 405
    post_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Method Not Allowed",
        request=httpx.Request("POST", "http://mock-molchat:8000/api/v1/molecules/interpret"),
        response=httpx.Response(405),
    )

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.raise_for_status = MagicMock()
    search_resp.json = MagicMock(
        return_value={
            "query": "TNT에 들어가는 주물질",
            "resolved_query": "TNT",
            "resolve_method": "autocomplete",
            "results": [
                {
                    "name": "2,4,6-TRINITROTOLUENE",
                    "cid": 8376,
                    "canonical_smiles": "CC1=C(C=C(C=C1[N+](=O)[O-])[N+](=O)[O-])[N+](=O)[O-]",
                    "molecular_formula": "C7H5N3O6",
                    "molecular_weight": 227.13,
                }
            ],
        }
    )
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=post_resp)
        instance.get = AsyncMock(return_value=search_resp)
        mock_client_cls.return_value = instance
        result = await client.interpret_candidates("TNT에 들어가는 주물질")
    assert result["candidates"][0]["name"] == "2,4,6-TRINITROTOLUENE"
    assert result["candidates"][0]["source"] == "molchat_search_fallback"


@pytest.mark.asyncio
async def test_generate_3d_sdf_requires_v2000_block(client, mock_response_ok):
    mock_response_ok.text = "fake sdf content\nM  END\n$$$$"
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response_ok)
        mock_client_cls.return_value = instance
        assert await client.generate_3d_sdf("O") is None


def test_name_to_sdf_exists(client):
    assert hasattr(client, "name_to_sdf")
