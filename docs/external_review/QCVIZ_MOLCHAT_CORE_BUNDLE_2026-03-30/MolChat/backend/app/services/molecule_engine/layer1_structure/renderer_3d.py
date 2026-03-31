"""
Renderer3D – generate 3Dmol.js-compatible JSON payloads for the frontend viewer.

This module does NOT perform 3D rendering itself; it prepares structured
data (SDF/XYZ + style config) that the frontend ``Viewer3D`` React
component feeds into the 3Dmol.js library.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import RDKitHandler

logger = structlog.get_logger(__name__)

ViewStyle = Literal["stick", "ball_and_stick", "sphere", "cartoon", "surface"]


# Preset style configs for 3Dmol.js
_STYLE_MAP: dict[ViewStyle, dict[str, Any]] = {
    "stick": {"stick": {"radius": 0.15, "colorscheme": "Jmol"}},
    "ball_and_stick": {
        "stick": {"radius": 0.1, "colorscheme": "Jmol"},
        "sphere": {"radius": 0.3, "colorscheme": "Jmol"},
    },
    "sphere": {"sphere": {"colorscheme": "Jmol"}},
    "cartoon": {"cartoon": {"color": "spectrum"}},
    "surface": {
        "stick": {"colorscheme": "Jmol"},
        "surface": {"opacity": 0.7, "color": "white"},
    },
}


class Renderer3D:
    """Prepare 3D viewer payloads for the frontend."""

    def __init__(self, rdkit_handler: RDKitHandler | None = None) -> None:
        self._rdkit = rdkit_handler or RDKitHandler()

    async def prepare_viewer_data(
        self,
        smiles: str | None = None,
        sdf_data: str | None = None,
        xyz_data: str | None = None,
        *,
        style: ViewStyle = "ball_and_stick",
        background_color: str = "#1a1a2e",
        show_labels: bool = False,
        animate: bool = False,
    ) -> dict[str, Any] | None:
        """Generate a JSON payload for the frontend 3Dmol.js viewer.

        Priority: sdf_data > xyz_data > smiles (generate SDF on-the-fly).
        """
        # Resolve structure data
        structure: str | None = None
        fmt: str = "sdf"

        if sdf_data:
            structure = sdf_data
            fmt = "sdf"
        elif xyz_data:
            structure = xyz_data
            fmt = "xyz"
        elif smiles:
            structure = await self._rdkit.smiles_to_sdf(smiles)
            fmt = "sdf"

        if structure is None:
            logger.warning("renderer_3d_no_structure", smiles=smiles)
            return None

        style_config = _STYLE_MAP.get(style, _STYLE_MAP["ball_and_stick"])

        return {
            "structure": structure,
            "format": fmt,
            "style": style_config,
            "config": {
                "backgroundColor": background_color,
                "antialias": True,
                "cartoonQuality": 10,
            },
            "labels": show_labels,
            "animate": animate,
            "available_styles": list(_STYLE_MAP.keys()),
        }

    async def prepare_comparison(
        self,
        molecules: list[dict[str, str]],
        *,
        style: ViewStyle = "stick",
    ) -> list[dict[str, Any]]:
        """Prepare viewer data for side-by-side comparison.

        Each dict in ``molecules`` must have at least 'smiles' or 'sdf_data'.
        """
        results = []
        for mol_data in molecules:
            viewer = await self.prepare_viewer_data(
                smiles=mol_data.get("smiles"),
                sdf_data=mol_data.get("sdf_data"),
                style=style,
            )
            if viewer:
                viewer["label"] = mol_data.get("name", "Unknown")
                results.append(viewer)
        return results