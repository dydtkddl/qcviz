"""PyVista 기반 네이티브 오비탈 렌더러. 브라우저 불필요."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import pyvista as pv

    _HAS_PYVISTA = True
except ImportError:
    _HAS_PYVISTA = False


def is_available() -> bool:
    return _HAS_PYVISTA


def cube_to_pyvista_grid(cube_data, origin, axes, npts):
    if not _HAS_PYVISTA:
        raise ImportError("PyVista not installed")
    spacing = tuple(
        float(np.linalg.norm(ax) / max(n - 1, 1)) for ax, n in zip(axes, npts)
    )
    grid = pv.ImageData(dimensions=npts, spacing=spacing, origin=origin)
    grid["orbital"] = cube_data.flatten(order="F")
    return grid


def render_orbital_png(
    cube_data,
    origin,
    axes,
    npts,
    output_path="orbital.png",
    isovalue=0.02,
    window_size=(1920, 1080),
    colors=("blue", "red"),
    background="white",
    show_atoms=None,
) -> str:
    if not _HAS_PYVISTA:
        raise ImportError("PyVista not installed")
    pv.OFF_SCREEN = True
    grid = cube_to_pyvista_grid(cube_data, origin, axes, npts)
    pl = pv.Plotter(off_screen=True, window_size=window_size)
    pl.background_color = background
    try:
        pos = grid.contour([isovalue], scalars="orbital")
        if pos.n_points > 0:
            pl.add_mesh(pos, color=colors[0], opacity=0.6, smooth_shading=True)
    except Exception:
        pass
    try:
        neg = grid.contour([-isovalue], scalars="orbital")
        if neg.n_points > 0:
            pl.add_mesh(neg, color=colors[1], opacity=0.6, smooth_shading=True)
    except Exception:
        pass
    if show_atoms:
        _C = {
            "H": "white",
            "C": "gray",
            "N": "blue",
            "O": "red",
            "F": "green",
            "Fe": "orange",
            "Ti": "silver",
            "Zr": "teal",
            "Mo": "purple",
        }
        for sym, coord in show_atoms:
            pl.add_mesh(
                pv.Sphere(radius=0.3, center=coord),
                color=_C.get(sym, "gray"),
                opacity=1.0,
            )
    pl.camera_position = "iso"
    pl.camera.zoom(1.3)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pl.screenshot(output_path)
    pl.close()
    logger.info(
        "PyVista PNG: %s (%d bytes)", output_path, Path(output_path).stat().st_size
    )
    return output_path


def render_from_cube_string(
    cube_text,
    output_path="orbital.png",
    isovalue=0.02,
    window_size=(1920, 1080),
    colors=("blue", "red"),
    background="white",
) -> str:
    from qcviz_mcp.backends.pyscf_backend import parse_cube_string

    parsed = parse_cube_string(cube_text)
    _Z = {
        1: "H",
        6: "C",
        7: "N",
        8: "O",
        9: "F",
        16: "S",
        22: "Ti",
        26: "Fe",
        40: "Zr",
        42: "Mo",
    }
    atoms = [(_Z.get(z, "X"), [x, y, zc]) for z, x, y, zc in parsed["atoms"]]
    return render_orbital_png(
        parsed["data"],
        parsed["origin"],
        parsed["axes"],
        parsed["npts"],
        output_path=output_path,
        isovalue=isovalue,
        window_size=window_size,
        colors=colors,
        background=background,
        show_atoms=atoms,
    )
