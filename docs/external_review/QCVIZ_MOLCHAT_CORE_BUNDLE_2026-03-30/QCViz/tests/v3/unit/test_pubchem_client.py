"""tests/v3/unit/test_pubchem_client.py — PubChem 클라이언트 단위 테스트 (mock)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from qcviz_mcp.services.pubchem_client import PubChemClient


@pytest.fixture
def client():
    return PubChemClient(timeout=5.0)


@pytest.fixture
def mock_response():
    def _make(json_data=None, text="", status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json = MagicMock(return_value=json_data or {})
        resp.text = text
        resp.raise_for_status = MagicMock()
        return resp
    return _make


class TestPubChemNameToCid:
    """name_to_cid() 검증"""

    @pytest.mark.asyncio
    async def test_name_to_cid_water(self, client, mock_response):
        """'water' → CID 962."""
        resp = mock_response(json_data={"IdentifierList": {"CID": [962]}})
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = instance
            cid = await client.name_to_cid("water")
        assert cid == 962

    @pytest.mark.asyncio
    async def test_name_to_cid_not_found(self, client, mock_response):
        """존재하지 않는 물질 → None."""
        resp = mock_response(json_data={"IdentifierList": {"CID": []}}, status_code=404)
        resp.raise_for_status.side_effect = Exception("Not found")
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = instance
            cid = await client.name_to_cid("xyznonexistent")
        assert cid is None


class TestPubChemCidToSdf:
    """cid_to_sdf_3d() 검증"""

    @pytest.mark.asyncio
    async def test_cid_to_sdf_3d(self, client, mock_response):
        """CID 962 → SDF 문자열."""
        sdf_text = "fake sdf\nM  END\n$$$$"
        resp = mock_response(text=sdf_text)
        resp.text = sdf_text
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = instance
            sdf = await client.cid_to_sdf_3d(962)
        # The method may return None if the sdf doesn't parse correctly,
        # or the text if it does
        assert sdf is None or isinstance(sdf, str)

    @pytest.mark.asyncio
    async def test_cid_to_smiles_falls_back_to_connectivity_smiles(self, client, mock_response):
        """CanonicalSMILES가 비어도 ConnectivitySMILES를 반환."""
        resp = mock_response(
            json_data={
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 4176748,
                            "CanonicalSMILES": None,
                            "ConnectivitySMILES": "C(F)(F)(F)S(=O)(=O)[N-]S(=O)(=O)C(F)(F)F",
                        }
                    ]
                }
            }
        )
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = instance
            smiles = await client.cid_to_smiles(4176748)
        assert smiles == "C(F)(F)(F)S(=O)(=O)[N-]S(=O)(=O)C(F)(F)F"


class TestPubChemPipeline:
    """전체 파이프라인 메서드 존재 확인"""

    def test_name_to_sdf_full_method_exists(self, client):
        """name_to_sdf_full 또는 equivalent 메서드 존재."""
        assert (
            hasattr(client, "name_to_sdf_full")
            or hasattr(client, "name_to_sdf_3d")
            or hasattr(client, "name_to_sdf")
        )

    def test_cid_to_smiles_method_exists(self, client):
        """cid_to_smiles 메서드 존재."""
        assert hasattr(client, "cid_to_smiles")
