"""Tests for ion_pair resolver reuse."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qcviz_mcp.services.ion_pair_handler import resolve_ion_pair


@pytest.mark.asyncio
async def test_resolver_is_reused_when_provided():
    mock_resolver = MagicMock()
    mock_result = MagicMock()
    mock_result.sdf = "<fake SDF V2000>"
    mock_result.smiles = "CCO"
    mock_resolver.resolve = AsyncMock(return_value=mock_result)

    with patch("qcviz_mcp.services.ion_pair_handler.merge_sdfs", return_value="3\n\nH 0 0 0"):
        result = await resolve_ion_pair(
            structures=[
                {"name": "EMIM", "charge": 1},
                {"name": "TFSI", "charge": -1},
            ],
            molchat=MagicMock(),
            pubchem=MagicMock(),
            resolver=mock_resolver,
        )

    assert mock_resolver.resolve.call_count == 2
    assert result.total_charge == 0


@pytest.mark.asyncio
async def test_fallback_creates_new_resolver_when_none():
    mock_instance = MagicMock()
    mock_result = MagicMock()
    mock_result.sdf = "<fake SDF V2000>"
    mock_result.smiles = "O"
    mock_instance.resolve = AsyncMock(return_value=mock_result)

    with patch("qcviz_mcp.services.ion_pair_handler._new_resolver", return_value=mock_instance) as factory:
        with patch("qcviz_mcp.services.ion_pair_handler.merge_sdfs", return_value="3\n\nH 0 0 0"):
            await resolve_ion_pair(
                structures=[
                    {"name": "Li", "charge": 1},
                    {"name": "Cl", "charge": -1},
                ],
                molchat=MagicMock(),
                pubchem=MagicMock(),
            )

    factory.assert_called_once()
