"""
Reproducibility Script Generator (F3).

Converts QCViz-MCP calculation metadata into standalone PySCF
scripts that reproduce the exact same results without requiring
the QCViz-MCP framework.

Version: 1.1.0
"""

import logging
from datetime import datetime

from qcviz_mcp.advisor.methods_drafter import CalculationRecord

__all__ = ["ReproducibilityScriptGenerator"]

logger = logging.getLogger(__name__)

_DISCLAIMER_COMMENT = (
    "# WARNING: This is a preliminary computational result generated\n"
    "# by QCViz-MCP. Results should be reviewed by a qualified\n"
    "# computational chemist before use in publications.\n"
)


def _strip_dispersion_from_functional(functional):
    """Remove dispersion correction suffixes from functional name.

    Args:
        functional (str): Functional name, possibly with D3/D4 suffix.

    Returns:
        str: Clean functional name suitable for PySCF xc parameter.
    """
    xc = str(functional or "").strip()
    for suffix in ("-D3(BJ)", "-D3BJ", "-D3(0)", "-D4", "-D3", "-NL"):
        xc = xc.replace(suffix, "")
    # Strip leading U/R for unrestricted/restricted KS labels
    if len(xc) > 1 and xc[0].upper() in {"U", "R"} and xc[1].isalpha():
        xc = xc[1:]
    return xc


class ReproducibilityScriptGenerator:
    """Generates standalone PySCF scripts for reproducibility.

    Converts calculation metadata into self-contained Python scripts
    that can be run independently of QCViz-MCP to reproduce results.
    """

    def __init__(self):
        """Initialize the script generator."""
        pass

    def generate(self, record, include_analysis=True):
        """Generate a reproducibility script from a calculation record.

        Args:
            record (CalculationRecord): Calculation metadata.
            include_analysis (bool): Whether to include analysis code
                (IBO, charges, etc.).

        Returns:
            str: Complete Python script as a string.
        """
        sections = []

        # Header
        sections.append(self._header(record))

        # Imports
        sections.append(self._imports(record))

        # Molecule definition
        sections.append(self._molecule_def(record))

        # SCF calculation
        sections.append(self._scf_block(record))

        # Geometry optimization (if applicable)
        if record.optimizer:
            sections.append(self._geomopt_block(record))

        # Analysis (if applicable)
        if include_analysis and record.analysis_type:
            sections.append(self._analysis_block(record))

        # Results summary
        sections.append(self._results_block(record))

        return "\n".join(sections)

    def _header(self, record):
        """Generate script header with metadata.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Header string.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = '"""\n'
        header += "Reproducibility script for QCViz-MCP calculation.\n"
        header += "System: %s\n" % record.system_name
        header += "Method: %s/%s" % (record.functional, record.basis)
        if record.dispersion:
            header += " + %s" % record.dispersion.upper()
        header += "\n"
        header += "Generated: %s\n" % now
        header += "\n"
        header += (
            "This script reproduces the calculation using only PySCF.\n"
            "No QCViz-MCP installation is required.\n"
        )
        header += '"""\n'
        header += _DISCLAIMER_COMMENT
        return header

    def _imports(self, record):
        """Generate import statements.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Import block string.
        """
        imports = ["from pyscf import gto, scf, dft"]

        if record.analysis_type in ("ibo", "iao"):
            imports.append("from pyscf import lo")

        if record.analysis_type == "esp":
            imports.append("from pyscf.tools import cubegen")
            imports.append("import numpy as np")

        if record.analysis_type == "charges":
            imports.append("from pyscf import lo")

        if record.optimizer:
            imports.append(
                "from pyscf.geomopt.geometric_solver import optimize"
            )

        return "\n".join(imports) + "\n"

    def _molecule_def(self, record):
        """Generate molecule definition block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Molecule definition code string.
        """
        lines = []
        lines.append("# --- Molecule Definition ---")
        lines.append("mol = gto.M(")
        lines.append("    atom='''")

        # Format atom spec with proper indentation
        for line in record.atom_spec.strip().split("\n"):
            line = line.strip()
            if line and not line.isdigit():
                parts = line.split()
                if len(parts) >= 4:
                    lines.append("    %s" % line)

        lines.append("    ''',")
        lines.append("    basis='%s'," % record.basis.lower())
        lines.append("    charge=%d," % record.charge)
        lines.append("    spin=%d," % record.spin)
        lines.append(")")
        lines.append("")
        return "\n".join(lines)

    def _scf_block(self, record):
        """Generate SCF calculation block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: SCF code string.
        """
        lines = []
        lines.append("# --- SCF Calculation ---")

        # Determine RKS vs UKS
        if record.spin > 0:
            lines.append("mf = dft.UKS(mol)")
        else:
            lines.append("mf = dft.RKS(mol)")

        # Set functional (strip dispersion suffixes)
        xc = _strip_dispersion_from_functional(record.functional)
        lines.append("mf.xc = '%s'" % xc.lower())

        # Convergence
        lines.append("mf.conv_tol = 1e-9")
        lines.append("mf.max_cycle = 200")
        lines.append("")
        lines.append("# Run SCF")
        lines.append("mf.kernel()")
        lines.append("")
        lines.append("if not mf.converged:")
        lines.append("    print('WARNING: SCF did not converge!')")
        lines.append("")
        return "\n".join(lines)

    def _geomopt_block(self, record):
        """Generate geometry optimization block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Geometry optimization code string.
        """
        # FIXED #2: Strip D3 suffix from functional in geomopt block
        xc = _strip_dispersion_from_functional(record.functional)

        lines = []
        lines.append("# --- Geometry Optimization ---")
        lines.append("# Note: optimize() returns a Mole object (PySCF >= 2.1)")
        lines.append(
            "mol_opt = optimize(mf, maxsteps=100)"
        )
        lines.append("")
        lines.append("# Update mol with optimized geometry")
        lines.append("mol = mol_opt")
        lines.append("")
        lines.append("# Re-run SCF at optimized geometry")
        if record.spin > 0:
            lines.append("mf = dft.UKS(mol)")
        else:
            lines.append("mf = dft.RKS(mol)")
        lines.append("mf.xc = '%s'" % xc.lower())
        lines.append("mf.conv_tol = 1e-9")
        lines.append("mf.kernel()")
        lines.append("")
        return "\n".join(lines)

    def _analysis_block(self, record):
        """Generate analysis code block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Analysis code string.
        """
        lines = []
        analysis = record.analysis_type

        if analysis in ("ibo", "iao"):
            lines.append("# --- IBO Analysis ---")
            lines.append(
                "orbocc = mf.mo_coeff[:, mf.mo_occ > 0]"
            )
            lines.append(
                "iao_coeff = lo.iao.iao(mol, orbocc)"
            )
            lines.append(
                "ibo_coeff = lo.ibo.ibo(mol, orbocc, iaos=iao_coeff)"
            )
            lines.append("")
            lines.append(
                "print('Number of IBOs: %%d' %% ibo_coeff.shape[1])"
            )
            lines.append("")

        elif analysis == "charges":
            lines.append("# --- Charge Analysis (IAO) ---")
            lines.append(
                "orbocc = mf.mo_coeff[:, mf.mo_occ > 0]"
            )
            lines.append(
                "iao_coeff = lo.iao.iao(mol, orbocc)"
            )
            lines.append("# IAO partial charges via Mulliken on IAO basis")
            lines.append("import numpy as np")
            lines.append("S = mol.intor('int1e_ovlp')")
            lines.append(
                "dm = mf.make_rdm1()"
            )
            lines.append(
                "# Project density onto IAO basis"
            )
            lines.append(
                "iao_inv = np.linalg.pinv(iao_coeff)"
            )
            lines.append(
                "dm_iao = iao_inv @ dm @ iao_inv.T"
            )
            lines.append("")

        elif analysis == "esp":
            lines.append("# --- ESP Cube File Generation ---")
            lines.append("import numpy as np")
            lines.append(
                "cubegen.density(mol, 'density.cube', mf.make_rdm1())"
            )
            lines.append(
                "cubegen.mep(mol, 'esp.cube', mf.make_rdm1())"
            )
            lines.append("print('Generated: density.cube, esp.cube')")
            lines.append("")

        return "\n".join(lines)

    def _results_block(self, record):
        """Generate results summary block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Results summary code string.
        """
        lines = []
        lines.append("# --- Results Summary ---")
        lines.append("print('=' * 60)")
        lines.append(
            "print('System: %s')" % record.system_name
        )
        lines.append(
            "print('Method: %s/%s')"
            % (record.functional, record.basis)
        )
        lines.append(
            "print('SCF Energy: %%.10f Hartree' %% mf.e_tot)"
        )
        lines.append(
            "print('SCF Energy: %%.6f eV' %% (mf.e_tot * 27.2114))"
        )
        lines.append(
            "print('Converged: %%s' %% mf.converged)"
        )
        lines.append("print('=' * 60)")
        lines.append("")
        return "\n".join(lines)
