from qcviz_mcp.compute.pyscf_runner import _lookup_builtin_xyz

def test_korean_noise_stripping():
    # Test cases that previously failed
    cases = [
        ("물분자 분석해줘", "water"),
        ("벤젠의 HOMO", "benzene"),
        ("아세톤 ESP 맵", "acetone"),
        ("HOMO of benzene", "benzene"),
        ("water orbital", "water"),
    ]
    
    for query, expected_key in cases:
        res = _lookup_builtin_xyz(query)
        assert res is not None, f"Failed to resolve: {query}"
        assert res[0] == expected_key, f"Expected {expected_key} for '{query}', got {res[0]}"

def test_korean_alias_direct():
    assert _lookup_builtin_xyz("물")[0] == "water"
    assert _lookup_builtin_xyz("벤젠")[0] == "benzene"
