"""tests/v3/unit/test_structure_resolver.py — StructureResolver 단위 테스트 (mock)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from qcviz_mcp.llm.normalizer import normalize_user_text
from qcviz_mcp.services.structure_resolver import StructureResolver, StructureResult


class TestStructureResolverInit:
    """StructureResolver 초기화 검증"""

    def test_resolver_creation(self):
        """StructureResolver 인스턴스 생성."""
        resolver = StructureResolver()
        assert resolver is not None

    def test_resolver_has_resolve(self):
        """resolve() 메서드 존재."""
        resolver = StructureResolver()
        assert hasattr(resolver, "resolve")


class TestStructureResult:
    """StructureResult 데이터 타입 검증"""

    def test_structure_result_creation(self):
        """StructureResult 인스턴스 생성."""
        result = StructureResult(
            xyz="3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0",
            smiles="O",
            cid=962,
            name="water",
            source="test",
        )
        assert result.xyz is not None
        assert result.smiles == "O"
        assert result.name == "water"

    def test_structure_result_fields(self):
        """StructureResult에 필수 필드 존재."""
        result = StructureResult(
            xyz="test", smiles="O", cid=962, name="water", source="test",
        )
        assert hasattr(result, "xyz")
        assert hasattr(result, "smiles")
        assert hasattr(result, "cid")
        assert hasattr(result, "name")
        assert hasattr(result, "source")


class TestResolve:
    """resolve() 메서드 검증 — MolChat/PubChem mock"""

    @pytest.mark.asyncio
    async def test_resolve_returns_result(self):
        """resolve('water') → StructureResult 타입 반환."""
        resolver = StructureResolver()
        # Mock the internal clients
        mock_result = StructureResult(
            xyz="3\nwater\nO 0 0 0.11\nH 0 0.76 -0.47\nH 0 -0.76 -0.47",
            smiles="O", cid=962, name="water", source="molchat",
        )
        with patch.object(resolver, "resolve", new=AsyncMock(return_value=mock_result)):
            result = await resolver.resolve("water")
        assert isinstance(result, StructureResult)
        assert result.name == "water"

    @pytest.mark.asyncio
    async def test_resolve_korean_name(self):
        """resolve('물') → ko_aliases 경유 해석."""
        resolver = StructureResolver()
        mock_result = StructureResult(
            xyz="3\nwater\nO 0 0 0\nH 0 1 0\nH 1 0 0",
            smiles="O", cid=962, name="water", source="molchat",
        )
        with patch.object(resolver, "resolve", new=AsyncMock(return_value=mock_result)):
            result = await resolver.resolve("물")
        assert result.smiles == "O"

    @pytest.mark.asyncio
    async def test_resolve_both_fail(self):
        """MolChat + PubChem 둘 다 실패 → ValueError."""
        resolver = StructureResolver()
        with patch.object(resolver, "resolve", new=AsyncMock(side_effect=ValueError("not found"))):
            with pytest.raises(ValueError):
                await resolver.resolve("xyznonexistent")

    def test_query_plan_prefers_charge_aware_tfsi_alias(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("TFSI-")
        assert query_plan["candidate_queries"][0] == "bis(trifluoromethanesulfonyl)azanide"
        assert query_plan["expected_charge"] == -1

    def test_query_plan_decomposes_formula_alias_mixed_input(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("CH3COOH (acetic acid)")
        assert query_plan["candidate_queries"][0] != "CH3COOH (acetic acid)"
        assert "acetic acid" in query_plan["candidate_queries"]
        assert "CH3COOH" in query_plan["candidate_queries"]
        assert query_plan["mixed_input"] is True
        assert query_plan["display_query"] == "acetic acid"

    def test_query_plan_collapses_spaced_korean_fragments_into_benzene(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("베 ㄴ젠")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "benzene" in lowered
        assert query_plan["normalized_query"].lower() == "benzene"

    def test_query_plan_reconstructs_nitrobenzene_from_mixed_korean_phrase(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("니트로 벤젠")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "nitrobenzene" in lowered
        assert query_plan["normalized_query"].lower() == "nitrobenzene"

    def test_query_plan_reconstructs_compact_nitrobenzene_korean_phrase(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("니트로벤젠")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "nitrobenzene" in lowered
        assert query_plan["normalized_query"].lower() == "nitrobenzene"

    def test_query_plan_collapses_compact_hangul_fragment_benzene(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("베ㄴ젠")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "benzene" in lowered
        assert query_plan["normalized_query"].lower() == "benzene"

    def test_charge_inference_distinguishes_tfsi_anion_and_acid(self):
        anion = "C(F)(F)(F)S(=O)(=O)[N-]S(=O)(=O)C(F)(F)F"
        acid = "C(F)(F)(F)S(=O)(=O)NS(=O)(=O)C(F)(F)F"
        assert StructureResolver._infer_smiles_formal_charge(anion) == -1
        assert StructureResolver._infer_smiles_formal_charge(acid) == 0

    def test_suggest_candidate_queries_preserves_raw_and_alias_variants(self):
        resolver = StructureResolver()
        suggestions = resolver.suggest_candidate_queries("TFSI-")
        names = [item["name"] for item in suggestions]
        assert "TFSI-" in names
        assert "bis(trifluoromethanesulfonyl)azanide" in names
        assert suggestions[0]["name"] == "TFSI-"

    def test_query_plan_detects_emim_tfsi_ion_pair_without_single_structure_fallback(self):
        resolver = StructureResolver()
        analysis = normalize_user_text("EMIM+ TFSI-")
        assert analysis["composition_kind"] == "ion_pair"
        assert analysis["structures"] == [
            {"name": "EMIM", "charge": 1},
            {"name": "TFSI", "charge": -1},
        ]

    @pytest.mark.asyncio
    async def test_resolve_rejects_neutral_result_for_explicit_anion_query(self):
        resolver = StructureResolver()
        neutral = StructureResult(
            xyz="1\nneutral\nN 0 0 0",
            smiles="C(F)(F)(F)S(=O)(=O)NS(=O)(=O)C(F)(F)F",
            cid=157857,
            name="bis(trifluoromethanesulfonyl)imide",
            source="molchat",
        )
        anion = StructureResult(
            xyz="1\nanion\nN 0 0 0",
            smiles="C(F)(F)(F)S(=O)(=O)[N-]S(=O)(=O)C(F)(F)F",
            cid=4176748,
            name="bis(trifluoromethanesulfonyl)azanide",
            source="molchat",
        )
        with patch.object(resolver, "_try_molchat", new=AsyncMock(side_effect=[neutral, anion])):
            with patch.object(resolver, "_try_pubchem", new=AsyncMock(return_value=None)):
                result = await resolver.resolve("TFSI-")
        assert result.cid == 4176748
        assert result.smiles and "[N-]" in result.smiles

    @pytest.mark.asyncio
    async def test_resolve_mixed_input_does_not_call_external_services_with_raw_literal_query(self):
        resolver = StructureResolver()
        seen_candidates = []
        mock_result = StructureResult(
            xyz="8\nacetic acid\nC 0 0 0",
            smiles="CC(=O)O",
            cid=176,
            name="acetic acid",
            source="molchat",
        )

        async def _fake_try_molchat(candidate: str):
            seen_candidates.append(candidate)
            if candidate == "acetic acid":
                return mock_result
            return None

        with patch.object(resolver, "_try_molchat", new=_fake_try_molchat):
            with patch.object(resolver, "_try_pubchem", new=AsyncMock(return_value=None)):
                result = await resolver.resolve("CH3COOH (acetic acid)")

        assert result.name == "acetic acid"
        assert "CH3COOH (acetic acid)" not in seen_candidates
        assert seen_candidates[0] == "acetic acid"

    def test_query_plan_marks_semantic_descriptor_and_drops_raw_phrase_candidates(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("TNT에 들어가는 주물질")
        assert query_plan["semantic_descriptor"] is True
        lowered = [str(item).lower() for item in query_plan["candidate_queries"]]
        assert "tnt에 들어가는 주물질" not in lowered
        assert "tnt 에 들어가는 주물질" not in lowered
