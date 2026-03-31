import pytest
from qcviz_mcp.compute import pyscf_runner

@pytest.mark.parametrize("method", ["RHF"])
def test_run_geometry_optimization_methane(method):
    # Use a small basis to keep it fast
    # structure_query="methane" should be resolvable
    try:
        result = pyscf_runner.run_geometry_optimization(
            structure_query="methane",
            method=method,
            basis="sto-3g",
        )
        assert result["success"] is True
        assert "xyz" in result
        assert "optimized_xyz" in result
        assert "trajectory" in result
        assert result["job_type"] == "geometry_optimization"
    except Exception as e:
        pytest.fail(f"run_geometry_optimization failed with {type(e).__name__}: {e}")

if __name__ == "__main__":
    test_run_geometry_optimization_methane("RHF")
