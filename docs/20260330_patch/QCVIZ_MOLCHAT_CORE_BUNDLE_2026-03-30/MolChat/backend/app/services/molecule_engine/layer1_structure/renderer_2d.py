"""
Renderer2D – generate 2D depiction images (SVG / PNG) from molecular data.

Uses RDKit's ``MolDraw2DSVG`` / ``MolDraw2DCairo`` to produce
publication-quality 2D structure diagrams.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Literal

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import _check_rdkit

logger = structlog.get_logger(__name__)

ImageFormat = Literal["svg", "png"]


class Renderer2D:
    """Generate 2D molecular depictions."""

    async def render(
        self,
        smiles: str,
        *,
        fmt: ImageFormat = "svg",
        width: int = 400,
        height: int = 300,
        highlight_atoms: list[int] | None = None,
        highlight_bonds: list[int] | None = None,
        kekulize: bool = True,
    ) -> str | None:
        """Render a 2D depiction of the molecule.

        Returns:
          - SVG string (if fmt='svg')
          - Base64-encoded PNG string (if fmt='png')
          - None on failure
        """
        return await asyncio.to_thread(
            self._render_sync,
            smiles, fmt, width, height,
            highlight_atoms, highlight_bonds, kekulize,
        )

    @staticmethod
    def _render_sync(
        smiles: str,
        fmt: ImageFormat,
        width: int,
        height: int,
        highlight_atoms: list[int] | None,
        highlight_bonds: list[int] | None,
        kekulize: bool,
    ) -> str | None:
        if not _check_rdkit():
            return None

        from rdkit import Chem
        from rdkit.Chem import Draw, rdCoordGen
        from rdkit.Chem.Draw import rdMolDraw2D

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        # Generate 2D coordinates
        rdCoordGen.AddCoords(mol)

        if fmt == "svg":
            drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        else:
            drawer = rdMolDraw2D.MolDraw2DCairo(width, height)

        # Drawing options
        opts = drawer.drawOptions()
        opts.addStereoAnnotation = True
        opts.addAtomIndices = False
        opts.bondLineWidth = 2.0
        opts.padding = 0.1

        if kekulize:
            try:
                Chem.Kekulize(mol)
            except Exception:
                pass

        drawer.DrawMolecule(
            mol,
            highlightAtoms=highlight_atoms or [],
            highlightBonds=highlight_bonds or [],
        )
        drawer.FinishDrawing()

        if fmt == "svg":
            return drawer.GetDrawingText()
        else:
            png_bytes = drawer.GetDrawingText()
            return base64.b64encode(png_bytes).decode("utf-8")

    async def render_grid(
        self,
        smiles_list: list[str],
        *,
        mols_per_row: int = 4,
        sub_img_size: tuple[int, int] = (300, 250),
        fmt: ImageFormat = "svg",
    ) -> str | None:
        """Render a grid of 2D depictions."""
        return await asyncio.to_thread(
            self._render_grid_sync,
            smiles_list, mols_per_row, sub_img_size, fmt,
        )

    @staticmethod
    def _render_grid_sync(
        smiles_list: list[str],
        mols_per_row: int,
        sub_img_size: tuple[int, int],
        fmt: ImageFormat,
    ) -> str | None:
        if not _check_rdkit():
            return None

        from rdkit import Chem
        from rdkit.Chem import Draw

        mols = []
        for s in smiles_list:
            mol = Chem.MolFromSmiles(s)
            if mol is not None:
                mols.append(mol)

        if not mols:
            return None

        if fmt == "svg":
            return Draw.MolsToGridImage(
                mols,
                molsPerRow=mols_per_row,
                subImgSize=sub_img_size,
                useSVG=True,
            )
        else:
            img = Draw.MolsToGridImage(
                mols,
                molsPerRow=mols_per_row,
                subImgSize=sub_img_size,
            )
            import io

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")