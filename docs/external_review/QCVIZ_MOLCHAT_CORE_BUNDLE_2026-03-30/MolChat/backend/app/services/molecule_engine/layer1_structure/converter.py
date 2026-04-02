"""
FormatConverter – convert molecular structures between formats.

Supported conversions:
  SMILES → SDF, MOL, XYZ, PDB
  SDF → SMILES, XYZ, PDB, MOL2
  XYZ → SDF (via RDKit)

Uses RDKit as primary engine with Open Babel (subprocess) as fallback
for formats RDKit cannot natively handle (e.g., MOL2, PDB).
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import (
    RDKitHandler,
    _check_rdkit,
)

logger = structlog.get_logger(__name__)

FormatType = Literal["smiles", "sdf", "mol", "xyz", "pdb", "mol2"]


class FormatConverter:
    """Convert molecular structures between chemical file formats."""

    def __init__(self, rdkit_handler: RDKitHandler | None = None) -> None:
        self._rdkit = rdkit_handler or RDKitHandler()

    async def convert(
        self,
        data: str,
        from_format: FormatType,
        to_format: FormatType,
    ) -> str | None:
        """Convert between any two supported formats.

        Returns the converted string or None on failure.
        """
        if from_format == to_format:
            return data

        log = logger.bind(from_fmt=from_format, to_fmt=to_format)
        log.debug("format_conversion_started")

        # Try RDKit-native conversion first
        result = await self._convert_rdkit(data, from_format, to_format)
        if result is not None:
            log.debug("format_conversion_rdkit_success")
            return result

        # Fallback to Open Babel subprocess
        result = await self._convert_openbabel(data, from_format, to_format)
        if result is not None:
            log.debug("format_conversion_openbabel_success")
            return result

        log.warning("format_conversion_failed")
        return None

    async def supported_conversions(self) -> list[dict[str, str]]:
        """List all supported from→to format pairs."""
        formats: list[FormatType] = ["smiles", "sdf", "mol", "xyz", "pdb", "mol2"]
        pairs = []
        for f in formats:
            for t in formats:
                if f != t:
                    pairs.append({"from": f, "to": t})
        return pairs

    # ═══════════════════════════════════════════
    # RDKit conversion
    # ═══════════════════════════════════════════

    async def _convert_rdkit(
        self, data: str, from_format: FormatType, to_format: FormatType
    ) -> str | None:
        """Attempt conversion using RDKit."""
        return await asyncio.to_thread(
            self._convert_rdkit_sync, data, from_format, to_format
        )

    @staticmethod
    def _convert_rdkit_sync(
        data: str, from_format: FormatType, to_format: FormatType
    ) -> str | None:
        if not _check_rdkit():
            return None

        from rdkit import Chem
        from rdkit.Chem import AllChem

        # Parse input
        mol = None
        if from_format == "smiles":
            mol = Chem.MolFromSmiles(data.strip())
        elif from_format in ("sdf", "mol"):
            mol = Chem.MolFromMolBlock(data)
        elif from_format == "xyz":
            mol = Chem.MolFromXYZBlock(data)
        elif from_format == "pdb":
            mol = Chem.MolFromPDBBlock(data)

        if mol is None:
            return None

        # Generate 3D if needed and not present
        if to_format in ("sdf", "mol", "xyz", "pdb"):
            if mol.GetNumConformers() == 0:
                mol = Chem.AddHs(mol)
                params = AllChem.ETKDGv3()
                params.randomSeed = 42
                result = AllChem.EmbedMolecule(mol, params)
                if result == -1:
                    return None
                AllChem.MMFFOptimizeMolecule(mol, maxIters=200)

        # Output
        if to_format == "smiles":
            return Chem.MolToSmiles(mol, canonical=True)
        elif to_format in ("sdf", "mol"):
            return Chem.MolToMolBlock(mol)
        elif to_format == "xyz":
            return Chem.MolToXYZBlock(mol)
        elif to_format == "pdb":
            return Chem.MolToPDBBlock(mol)

        return None

    # ═══════════════════════════════════════════
    # Open Babel fallback
    # ═══════════════════════════════════════════

    async def _convert_openbabel(
        self, data: str, from_format: FormatType, to_format: FormatType
    ) -> str | None:
        """Fallback conversion via Open Babel CLI (obabel)."""
        return await asyncio.to_thread(
            self._convert_openbabel_sync, data, from_format, to_format
        )

    @staticmethod
    def _convert_openbabel_sync(
        data: str, from_format: FormatType, to_format: FormatType
    ) -> str | None:
        # Map our format names to Open Babel format IDs
        ob_format_map: dict[str, str] = {
            "smiles": "smi",
            "sdf": "sdf",
            "mol": "mol",
            "xyz": "xyz",
            "pdb": "pdb",
            "mol2": "mol2",
        }

        in_fmt = ob_format_map.get(from_format)
        out_fmt = ob_format_map.get(to_format)

        if in_fmt is None or out_fmt is None:
            return None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=f".{in_fmt}", delete=False
            ) as f_in:
                f_in.write(data)
                f_in_path = f_in.name

            f_out_path = f_in_path.replace(f".{in_fmt}", f".{out_fmt}")

            result = subprocess.run(
                ["obabel", f_in_path, "-O", f_out_path, f"-i{in_fmt}", f"-o{out_fmt}", "--gen3d"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.debug(
                    "openbabel_error",
                    stderr=result.stderr[:500],
                )
                return None

            output_path = Path(f_out_path)
            if output_path.exists():
                content = output_path.read_text()
                output_path.unlink(missing_ok=True)
                Path(f_in_path).unlink(missing_ok=True)
                return content if content.strip() else None

            return None

        except FileNotFoundError:
            # obabel not installed
            return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None