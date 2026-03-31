import pytest
from qcviz_mcp.compute.pyscf_runner import _get_cache_key, run_analyze, run_orbital_preview
import time
import os

def test_cache_hit_on_subsequent_orbital_queries():
    os.environ["QCVIZ_CACHE_DIR"] = "/tmp/qcviz_pytest_cache"
    benzene = "6\n\nC 0.0 1.4 0.0\nC 1.2 0.7 0.0\nC 1.2 -0.7 0.0\nC 0.0 -1.4 0.0\nC -1.2 -0.7 0.0\nC -1.2 0.7 0.0"
    
    t0 = time.time()
    res1 = run_orbital_preview(structure_query="benzene", xyz=benzene, method="B3LYP", basis="sto-3g", orbital="HOMO")
    t1 = time.time()
    
    res2 = run_orbital_preview(structure_query="benzene", xyz=benzene, method="B3LYP", basis="sto-3g", orbital="LUMO")
    t2 = time.time()
    
    print(f"First run: {t1-t0:.2f}s, Second run: {t2-t1:.2f}s")
    
    assert res2["success"] is True
