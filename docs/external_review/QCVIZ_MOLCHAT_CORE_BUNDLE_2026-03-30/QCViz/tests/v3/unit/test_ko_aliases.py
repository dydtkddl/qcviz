"""tests/v3/unit/test_ko_aliases.py — 한국어 별칭 모듈 단위 테스트"""
import pytest
from qcviz_mcp.services.ko_aliases import KO_TO_EN, translate, find_molecule_name


class TestKOToEN:
    """KO_TO_EN 딕셔너리 검증"""

    def test_ko_to_en_has_30_entries(self):
        """KO_TO_EN 딕셔너리에 30개 이상의 항목이 있어야 한다."""
        assert len(KO_TO_EN) >= 30

    def test_ko_to_en_contains_water(self):
        """'물' 키가 존재해야 한다."""
        assert "물" in KO_TO_EN

    def test_ko_to_en_contains_benzene(self):
        """'벤젠' 키가 존재해야 한다."""
        assert "벤젠" in KO_TO_EN

    def test_ko_to_en_contains_aspirin(self):
        """'아스피린' 키가 존재해야 한다."""
        assert "아스피린" in KO_TO_EN


class TestTranslate:
    """translate() 함수 검증"""

    def test_translate_simple_korean(self):
        """'물' → 'water' 기본 번역."""
        result = translate("물")
        assert "water" in result.lower()

    def test_translate_korean_with_josa_ui(self):
        """'물의' → 'water' (조사 '의' 제거)."""
        result = translate("물의")
        assert "water" in result.lower()

    def test_translate_korean_with_josa_eul(self):
        """'벤젠을' → 'benzene' (조사 '을' 제거)."""
        result = translate("벤젠을")
        assert "benzene" in result.lower()

    def test_translate_korean_with_josa_euro(self):
        """'아세톤으로' → 'acetone' (조사 '으로' 제거)."""
        result = translate("아세톤으로")
        assert "acetone" in result.lower()

    def test_translate_korean_with_josa_eseo(self):
        """'에탄올에서' → 'ethanol' (조사 '에서' 제거)."""
        result = translate("에탄올에서")
        assert "ethanol" in result.lower()

    def test_translate_no_match(self):
        """영어 텍스트는 변경되지 않아야 한다."""
        assert translate("hello world") == "hello world"

    def test_translate_empty_string(self):
        """빈 문자열은 빈 문자열을 반환."""
        assert translate("") == ""

    def test_translate_aspirin(self):
        """'아스피린' → 'aspirin'."""
        result = translate("아스피린")
        assert "aspirin" in result.lower()

    def test_translate_serotonin(self):
        """'세로토닌' → 'serotonin'."""
        result = translate("세로토닌")
        assert "serotonin" in result.lower()

    def test_translate_caffeine(self):
        """'카페인' → 'caffeine'."""
        result = translate("카페인")
        assert "caffeine" in result.lower()

    def test_all_entries_translate(self):
        """KO_TO_EN의 모든 키에 대해 translate가 영어명을 반환."""
        for ko, en in KO_TO_EN.items():
            result = translate(ko)
            assert en.lower() in result.lower(), f"{ko} → {result}, expected {en}"


class TestFindMoleculeName:
    """find_molecule_name() 함수 검증"""

    def test_find_molecule_name_found(self):
        """'물의 에너지'에서 분자명 '물' 감지."""
        result = find_molecule_name("물의 에너지를 계산해줘")
        assert result is not None

    def test_find_molecule_name_not_found(self):
        """분자명이 없는 텍스트 → None."""
        result = find_molecule_name("hello world")
        assert result is None

    def test_find_molecule_name_empty(self):
        """빈 문자열 → None."""
        result = find_molecule_name("")
        assert result is None

    def test_find_molecule_name_benzene(self):
        """'벤젠의 HOMO'에서 벤젠 감지."""
        result = find_molecule_name("벤젠의 HOMO를 보여줘")
        assert result is not None
