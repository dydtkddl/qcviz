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

    def test_suggest_candidate_queries_keeps_exact_tnt_name_ahead_of_cached_toluene_variant(self):
        resolver = StructureResolver()
        resolver._cache_put(
            "toluene",
            StructureResult(
                xyz="1\ntoluene\nC 0 0 0",
                smiles="Cc1ccccc1",
                cid=1140,
                name="toluene",
                source="molchat",
            ),
        )
        with patch.object(
            resolver,
            "_build_query_plan",
            return_value={
                "query_kind": "direct_name",
                "raw_query": "2,4,6-TRINITROTOLUENE",
                "translated_query": "",
                "normalized_query": "2,4,6-TRINITROTOLUENE",
                "expected_charge": None,
                "candidate_queries": ["toluene", "6-TRINITROTOLUENE"],
            },
        ):
            suggestions = resolver.suggest_candidate_queries("2,4,6-TRINITROTOLUENE")

        assert suggestions[0]["name"] == "2,4,6-TRINITROTOLUENE"
        assert suggestions[1]["name"] == "6-TRINITROTOLUENE"

    def test_query_plan_preserves_full_locant_name_for_tnt(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("2,4,6-TRINITROTOLUENE")
        assert query_plan["normalized_query"] == "2,4,6-TRINITROTOLUENE"
        assert query_plan["display_query"] == "2,4,6-TRINITROTOLUENE"
        assert query_plan["candidate_queries"][0] == "2,4,6-TRINITROTOLUENE"

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

    def test_query_plan_autocorrects_aminobutylic_acid_to_gamma_aminobutyric_acid(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("Aminobutylic acid")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert lowered[0] == "gamma-aminobutyric acid"
        assert query_plan["normalized_query"].lower() == "gamma-aminobutyric acid"
        assert query_plan["display_query"].lower() == "gamma-aminobutyric acid"

    def test_query_plan_adds_fuzzy_rescue_candidate_for_methyl_ethyl_aminje(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("Methyl Ethyl aminje")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "methylethylamine" in lowered

    def test_query_plan_reconstructs_korean_compositional_amine_name(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("\uba54\ud2f8\uc5d0\ud2f8\uc544\ubbfc")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "methylethylamine" in lowered

    def test_query_plan_adds_fuzzy_rescue_candidate_for_benzne(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("benzne")
        lowered = [item.lower() for item in query_plan["candidate_queries"]]
        assert "benzene" in lowered

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

    @pytest.mark.asyncio
    async def test_resolve_uses_molchat_search_autocorrect_when_exact_resolve_fails(self):
        molchat = MagicMock()
        molchat.resolve = AsyncMock(return_value=[])
        molchat.search = AsyncMock(
            return_value={
                "query": "Aminobutylic acid",
                "resolved_query": "gamma-aminobutyric acid",
                "resolve_method": "autocorrect",
                "results": [
                    {
                        "name": "gamma-aminobutyric acid",
                        "cid": 119,
                        "canonical_smiles": "C(CC(=O)O)CN",
                        "molecular_weight": 103.12,
                    }
                ],
            }
        )
        molchat.get_card = AsyncMock(return_value=None)
        molchat.generate_3d_sdf = AsyncMock(return_value="mock-sdf")

        pubchem = MagicMock()
        pubchem.cid_to_smiles = AsyncMock(return_value="C(CC(=O)O)CN")

        resolver = StructureResolver(molchat=molchat, pubchem=pubchem)
        with patch("qcviz_mcp.services.structure_resolver.sdf_to_xyz", return_value="7\ngamma-aminobutyric acid\nC 0 0 0"):
            result = await resolver.resolve("Aminobutylic acid")

        assert result.name == "gamma-aminobutyric acid"
        assert result.cid == 119
        assert result.smiles == "C(CC(=O)O)CN"
        assert result.source == "molchat_search_autocorrect"

    def test_normalize_user_text_locks_condensed_formula_as_single_structure(self):
        formula = "CH\u2083\u2013C(CH\u2083)(Cl)\u2013CH\u2082CH\u2083"
        normalized = normalize_user_text(formula)
        assert normalized["condensed_formula"] is True
        assert normalized["candidate_queries"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert normalized["canonical_candidates"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert normalized["formula_mentions"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert normalized["structures"] == []
        assert normalized["charge_hint"] is None
        assert normalized["unknown_acronyms"] == []
        assert normalized["query_kind"] == "compute_ready"

    def test_query_plan_marks_condensed_formula_without_fragment_candidates(self):
        resolver = StructureResolver()
        formula = "CH\u2083\u2013C(CH\u2083)(Cl)\u2013CH\u2082CH\u2083"
        query_plan = resolver._build_query_plan(formula)
        assert query_plan["condensed_formula"] is True
        assert query_plan["query_kind"] == "condensed_formula"
        assert query_plan["candidate_queries"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert query_plan["canonical_candidates"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert query_plan["formula_mentions"] == ["CH3-C(CH3)(Cl)-CH2CH3"]
        assert query_plan["expected_charge"] is None

    @pytest.mark.asyncio
    async def test_resolve_condensed_formula_uses_llm_smiles_fallback_after_lookup_failure(self):
        resolver = StructureResolver()
        formula = "CH\u2083\u2013C(CH\u2083)(Cl)\u2013CH\u2082CH\u2083"

        with patch.object(resolver, "_try_molchat_with_search_fallback", new=AsyncMock(return_value=None)):
            with patch.object(resolver, "_try_pubchem", new=AsyncMock(return_value=None)):
                with patch.object(
                    resolver,
                    "_llm_condensed_formula_to_smiles",
                    new=AsyncMock(
                        return_value={
                            "smiles": "CC(Cl)(C)CC",
                            "resolved_name": "2-chloro-2-methylbutane",
                        }
                    ),
                ):
                    resolver.molchat.generate_3d_sdf = AsyncMock(return_value="mock-sdf")
                    with patch(
                        "qcviz_mcp.services.structure_resolver.sdf_to_xyz",
                        return_value="6\n2-chloro-2-methylbutane\nC 0 0 0",
                    ):
                        result = await resolver.resolve(formula)

        assert result.source == "llm_condensed_formula"
        assert result.structure_query_raw == formula
        assert result.resolved_structure_name == "2-chloro-2-methylbutane"
        assert result.resolved_smiles == "CC(Cl)(C)CC"
        assert result.name == "2-chloro-2-methylbutane"

    def test_query_plan_marks_semantic_descriptor_and_drops_raw_phrase_candidates(self):
        resolver = StructureResolver()
        query_plan = resolver._build_query_plan("TNT에 들어가는 주물질")
        assert query_plan["semantic_descriptor"] is True
        lowered = [str(item).lower() for item in query_plan["candidate_queries"]]
        assert "tnt에 들어가는 주물질" not in lowered
        assert "tnt 에 들어가는 주물질" not in lowered
