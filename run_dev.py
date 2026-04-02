"""Start QCViz server with PySCF mocked (for Windows testing)."""
import sys
from unittest.mock import MagicMock

# Mock PySCF modules
m = MagicMock()
m.__version__ = "2.4.0"
for sub in [
    "pyscf", "pyscf.gto", "pyscf.scf", "pyscf.dft",
    "pyscf.tools", "pyscf.tools.cubegen",
    "pyscf.geomopt", "pyscf.geomopt.geometric_solver",
    "pyscf.lib",
]:
    sys.modules[sub] = m

import uvicorn
from qcviz_mcp.web.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info", ws="none")
