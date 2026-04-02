"""
XTBRunner – async subprocess wrapper for the xTB program (GFN2-xTB).

xTB is executed in an isolated temporary directory with strict
resource limits (timeout, max atoms). Results are parsed from
xTB's JSON/stdout output.

Security:
  • Input is written to a temp file (no shell injection).
  • Subprocess runs with a hard timeout.
  • Temp directory is cleaned up even on failure.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

XTBTask = Literal["energy", "optimize", "frequencies", "orbitals"]


@dataclass
class XTBResult:
    """Parsed output from an xTB calculation."""

    success: bool = False
    method: str = "gfn2"
    tasks_completed: list[str] = field(default_factory=list)

    # Energetics (Hartree)
    total_energy: float | None = None
    homo_energy: float | None = None
    lumo_energy: float | None = None
    homo_lumo_gap: float | None = None

    # Thermodynamics (if frequencies requested)
    zpve: float | None = None            # Zero-point vibrational energy
    enthalpy: float | None = None
    entropy: float | None = None          # T*S
    gibbs_free_energy: float | None = None

    # Geometry
    optimized_xyz: str | None = None
    dipole_moment: float | None = None    # Debye

    # Frequencies (cm⁻¹)
    frequencies: list[float] = field(default_factory=list)
    imaginary_frequencies: int = 0

    # Raw output for debugging
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float = 0.0
    error_message: str = ""


class XTBRunner:
    """Execute xTB calculations as async subprocesses."""

    def __init__(
        self,
        xtb_path: str = "xtb",
        method: str | None = None,
        timeout: int | None = None,
        max_atoms: int | None = None,
    ) -> None:
        self._xtb_path = xtb_path
        self._method = method or settings.XTB_METHOD
        self._timeout = timeout or settings.XTB_TIMEOUT
        self._max_atoms = max_atoms or settings.XTB_MAX_ATOMS

    async def run(
        self,
        xyz_data: str,
        *,
        tasks: list[XTBTask] | None = None,
        charge: int = 0,
        multiplicity: int = 1,
        solvent: str | None = None,
    ) -> XTBResult:
        """Run an xTB calculation on the given XYZ structure.

        Args:
            xyz_data: Molecular geometry in XYZ format.
            tasks: List of tasks (energy, optimize, frequencies, orbitals).
            charge: Net molecular charge.
            multiplicity: Spin multiplicity.
            solvent: ALPB solvent model name (e.g., 'water', 'methanol').
        """
        tasks = tasks or ["energy"]
        result = XTBResult(method=self._method)

        # ── Validate input ──
        atom_count = self._count_atoms_xyz(xyz_data)
        if atom_count == 0:
            result.error_message = "Invalid XYZ data: no atoms found"
            return result

        if atom_count > self._max_atoms:
            result.error_message = (
                f"Too many atoms ({atom_count} > {self._max_atoms})"
            )
            return result

        # ── Prepare temp directory ──
        tmpdir = Path(tempfile.mkdtemp(prefix="molchat_xtb_"))

        try:
            input_file = tmpdir / "molecule.xyz"
            input_file.write_text(xyz_data)

            # ── Build command ──
            cmd = self._build_command(
                input_file, tasks, charge, multiplicity, solvent
            )

            log = logger.bind(
                tasks=tasks, atoms=atom_count, method=self._method
            )
            log.info("xtb_calculation_started")

            # ── Execute ──
            import time

            t0 = time.perf_counter()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(tmpdir),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                result.error_message = f"xTB timed out after {self._timeout}s"
                log.warning("xtb_timeout", timeout=self._timeout)
                return result

            elapsed = time.perf_counter() - t0
            result.stdout = stdout_bytes.decode("utf-8", errors="replace")
            result.stderr = stderr_bytes.decode("utf-8", errors="replace")
            result.elapsed_seconds = elapsed

            if proc.returncode != 0:
                result.error_message = (
                    f"xTB exited with code {proc.returncode}"
                )
                log.warning(
                    "xtb_failed",
                    return_code=proc.returncode,
                    stderr=result.stderr[:500],
                )
                return result

            # ── Parse results ──
            result = self._parse_output(result, tmpdir, tasks)
            result.success = True

            log.info(
                "xtb_calculation_completed",
                elapsed=f"{elapsed:.1f}s",
                energy=result.total_energy,
            )

        except Exception as exc:
            result.error_message = f"Unexpected error: {exc}"
            logger.error("xtb_unexpected_error", error=str(exc))

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return result

    # ═══════════════════════════════════════════
    # Command builder
    # ═══════════════════════════════════════════

    def _build_command(
        self,
        input_file: Path,
        tasks: list[XTBTask],
        charge: int,
        multiplicity: int,
        solvent: str | None,
    ) -> list[str]:
        cmd = [
            self._xtb_path,
            str(input_file),
            f"--{self._method}",
            "--chrg", str(charge),
            "--uhf", str(multiplicity - 1),
        ]

        if "optimize" in tasks:
            cmd.append("--opt")
        if "frequencies" in tasks:
            cmd.append("--hess")

        if solvent:
            cmd.extend(["--alpb", solvent])

        cmd.append("--json")  # Request JSON output
        cmd.append("--verbose")

        return cmd

    # ═══════════════════════════════════════════
    # Output parser
    # ═══════════════════════════════════════════

    def _parse_output(
        self, result: XTBResult, tmpdir: Path, tasks: list[XTBTask]
    ) -> XTBResult:
        """Parse xTB output files and stdout."""

        # ── JSON output (xtbout.json) ──
        json_file = tmpdir / "xtbout.json"
        if json_file.exists():
            try:
                data = json.loads(json_file.read_text())
                result.total_energy = data.get("total energy")
                result.homo_lumo_gap = data.get("HOMO-LUMO gap/eV")

                orbitals = data.get("orbital energies", {})
                if "HOMO" in orbitals:
                    result.homo_energy = orbitals["HOMO"]
                if "LUMO" in orbitals:
                    result.lumo_energy = orbitals["LUMO"]
            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug("xtb_json_parse_error", error=str(exc))

        # ── Stdout parsing (fallback) ──
        self._parse_stdout(result)

        # ── Optimized geometry ──
        if "optimize" in tasks:
            opt_file = tmpdir / "xtbopt.xyz"
            if opt_file.exists():
                result.optimized_xyz = opt_file.read_text()
                result.tasks_completed.append("optimize")

        # ── Frequencies ──
        if "frequencies" in tasks:
            self._parse_frequencies(result, tmpdir)
            result.tasks_completed.append("frequencies")

        if result.total_energy is not None:
            result.tasks_completed.append("energy")

        return result

    def _parse_stdout(self, result: XTBResult) -> None:
        """Extract values from xTB stdout text."""
        stdout = result.stdout

        # Total energy
        if result.total_energy is None:
            match = re.search(r"TOTAL ENERGY\s+([-\d.]+)\s+Eh", stdout)
            if match:
                result.total_energy = float(match.group(1))

        # HOMO-LUMO gap
        if result.homo_lumo_gap is None:
            match = re.search(r"HOMO-LUMO GAP\s+([-\d.]+)\s+eV", stdout)
            if match:
                result.homo_lumo_gap = float(match.group(1))

        # Dipole moment
        match = re.search(r"molecular dipole:.*?full.*?([\d.]+)\s+Debye", stdout, re.DOTALL)
        if match:
            result.dipole_moment = float(match.group(1))

        # Thermodynamics
        match = re.search(r"TOTAL FREE ENERGY\s+([-\d.]+)\s+Eh", stdout)
        if match:
            result.gibbs_free_energy = float(match.group(1))

        match = re.search(r"TOTAL ENTHALPY\s+([-\d.]+)\s+Eh", stdout)
        if match:
            result.enthalpy = float(match.group(1))

        match = re.search(r"zero point energy\s+([-\d.]+)\s+Eh", stdout)
        if match:
            result.zpve = float(match.group(1))

    def _parse_frequencies(self, result: XTBResult, tmpdir: Path) -> None:
        """Parse vibrational frequencies from g98.out or stdout."""
        g98_file = tmpdir / "g98.out"
        if g98_file.exists():
            text = g98_file.read_text()
            freq_matches = re.findall(r"Frequencies\s+--\s+([\d.\s-]+)", text)
            freqs: list[float] = []
            for match in freq_matches:
                for val in match.split():
                    try:
                        freqs.append(float(val))
                    except ValueError:
                        continue
            result.frequencies = sorted(freqs)
            result.imaginary_frequencies = sum(1 for f in freqs if f < 0)
            return

        # Fallback: parse from stdout
        freq_matches = re.findall(
            r"(\d+)\s+([-\d.]+)\s+\d+\.\d+\s+\d+\.\d+", result.stdout
        )
        for _, freq_str in freq_matches:
            try:
                result.frequencies.append(float(freq_str))
            except ValueError:
                continue
        result.imaginary_frequencies = sum(1 for f in result.frequencies if f < 0)

    # ═══════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════

    @staticmethod
    def _count_atoms_xyz(xyz_data: str) -> int:
        """Count atoms from XYZ-format data."""
        lines = xyz_data.strip().splitlines()
        if not lines:
            return 0
        try:
            return int(lines[0].strip())
        except ValueError:
            # Count non-empty lines after the first two (header lines)
            return sum(
                1 for line in lines[2:]
                if line.strip() and len(line.split()) >= 4
            )