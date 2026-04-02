"""tests/v3/unit/test_sdf_converter.py — SDF→XYZ 변환 단위 테스트"""
import pytest
from qcviz_mcp.services.sdf_converter import sdf_to_xyz, sdf_to_atoms_list, merge_sdfs


class TestSdfToXyz:
    """sdf_to_xyz() 함수 검증"""

    def test_sdf_to_xyz_water(self, water_sdf):
        """물 SDF → 3원자 XYZ 문자열 변환."""
        xyz = sdf_to_xyz(water_sdf)
        assert isinstance(xyz, str)
        lines = [l for l in xyz.strip().splitlines() if l.strip()]
        # 첫 줄은 원자 수, 두 번째는 comment, 나머지는 원자
        assert int(lines[0].strip()) == 3

    def test_sdf_to_xyz_atom_count(self, water_sdf):
        """첫 줄이 원자 수(3)여야 한다."""
        xyz = sdf_to_xyz(water_sdf)
        first_line = xyz.strip().splitlines()[0].strip()
        assert first_line == "3"

    def test_sdf_to_xyz_coordinates_parseable(self, water_sdf):
        """좌표 값이 float으로 파싱 가능해야 한다."""
        xyz = sdf_to_xyz(water_sdf)
        lines = xyz.strip().splitlines()
        for line in lines[2:]:  # skip atom count and comment
            parts = line.strip().split()
            if len(parts) >= 4:
                float(parts[1])
                float(parts[2])
                float(parts[3])

    def test_sdf_to_xyz_symbols(self, water_sdf):
        """원소 기호가 O, H, H 순서여야 한다."""
        xyz = sdf_to_xyz(water_sdf)
        lines = xyz.strip().splitlines()
        symbols = [l.strip().split()[0] for l in lines[2:] if l.strip()]
        assert symbols == ["O", "H", "H"]

    def test_sdf_to_xyz_ethanol(self, ethanol_sdf):
        """에탄올 SDF → 9원자 XYZ."""
        xyz = sdf_to_xyz(ethanol_sdf)
        first_line = xyz.strip().splitlines()[0].strip()
        assert first_line == "9"

    def test_sdf_to_xyz_empty(self):
        """빈 문자열 → 예외 발생."""
        with pytest.raises((ValueError, Exception)):
            sdf_to_xyz("")

    def test_sdf_to_xyz_invalid(self):
        """잘못된 SDF → 예외 발생."""
        with pytest.raises((ValueError, Exception)):
            sdf_to_xyz("not a valid sdf at all")


class TestSdfToAtomsList:
    """sdf_to_atoms_list() 함수 검증"""

    def test_sdf_to_atoms_list_water(self, water_sdf):
        """물 → [(O, (x,y,z)), (H, ...), (H, ...)] 리스트."""
        atoms = sdf_to_atoms_list(water_sdf)
        assert isinstance(atoms, list)
        assert len(atoms) == 3

    def test_sdf_to_atoms_list_structure(self, water_sdf):
        """각 항목이 (symbol, (x, y, z)) 형태."""
        atoms = sdf_to_atoms_list(water_sdf)
        for symbol, coords in atoms:
            assert isinstance(symbol, str)
            assert len(coords) == 3
            for c in coords:
                assert isinstance(c, (int, float))


class TestMergeSdfs:
    """merge_sdfs() 함수 검증"""

    def test_merge_sdfs_two_molecules(self, water_sdf, ethanol_sdf):
        """물 + 에탄올 → 12원자 XYZ."""
        merged = merge_sdfs([water_sdf, ethanol_sdf])
        first_line = merged.strip().splitlines()[0].strip()
        assert int(first_line) == 12  # 3 + 9

    def test_merge_sdfs_single(self, water_sdf):
        """단일 SDF → 그대로 XYZ."""
        merged = merge_sdfs([water_sdf])
        first_line = merged.strip().splitlines()[0].strip()
        assert int(first_line) == 3

    def test_merge_sdfs_empty_list(self):
        """빈 리스트 → 예외 발생."""
        with pytest.raises((ValueError, Exception)):
            merge_sdfs([])
