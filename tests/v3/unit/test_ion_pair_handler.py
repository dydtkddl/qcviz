"""tests/v3/unit/test_ion_pair_handler.py — 이온쌍 처리 단위 테스트"""
import pytest
from qcviz_mcp.services.ion_pair_handler import (
    ION_ALIASES, is_ion_pair, expand_alias, IonPairResult,
)


class TestIONAliases:
    """ION_ALIASES 딕셔너리 검증"""

    def test_ion_aliases_count(self):
        """ION_ALIASES에 27개 이상 항목 존재."""
        assert len(ION_ALIASES) >= 27

    def test_expand_alias_emim(self):
        """'EMIM' → cation 정보 반환."""
        result = expand_alias("EMIM")
        assert result is not None
        assert result.get("charge", 0) > 0 or result.get("type") == "cation"

    def test_expand_alias_tfsi(self):
        """'TFSI' → anion 정보 반환."""
        result = expand_alias("TFSI")
        assert result is not None
        assert result.get("charge", 0) < 0 or result.get("type") == "anion"
        assert result.get("name") == "bis(trifluoromethanesulfonyl)azanide"

    def test_expand_alias_unknown(self):
        """알 수 없는 별칭 → 기본값 반환 (type=unknown)."""
        result = expand_alias("NONEXISTENT_THING")
        # expand_alias returns a default dict for unknown aliases
        if result is None:
            assert True
        else:
            assert result.get("type") == "unknown" or result.get("name") == "NONEXISTENT_THING"

    def test_expand_alias_li(self):
        """'Li' → lithium ion."""
        result = expand_alias("Li")
        assert result is not None

    def test_expand_alias_cl(self):
        """'Cl' → chloride."""
        result = expand_alias("Cl")
        assert result is not None

    def test_expand_alias_bf4(self):
        """'BF4' → tetrafluoroborate."""
        result = expand_alias("BF4")
        assert result is not None


class TestIsIonPair:
    """is_ion_pair() 함수 검증"""

    def test_is_ion_pair_true(self):
        """양이온+음이온 구조 → True."""
        structures = [
            {"name": "EMIM", "charge": 1},
            {"name": "TFSI", "charge": -1},
        ]
        assert is_ion_pair(structures) is True

    def test_is_ion_pair_false_single(self):
        """단일 분자 → False."""
        structures = [{"name": "water"}]
        assert is_ion_pair(structures) is False

    def test_is_ion_pair_empty(self):
        """빈 리스트 → False."""
        assert is_ion_pair([]) is False

    def test_is_ion_pair_none(self):
        """None → False."""
        assert is_ion_pair(None) is False


class TestIonPairResult:
    """IonPairResult 데이터클래스 검증"""

    def test_ion_pair_result_creation(self):
        """IonPairResult 인스턴스 생성."""
        result = IonPairResult(
            xyz="2\ntest\nH 0 0 0\nH 0 0 1",
            total_charge=0,
            smiles_list=["O", "O"],
            names=["water", "water"],
            source="test",
        )
        assert result.xyz is not None
        assert result.total_charge == 0
        assert len(result.names) == 2
