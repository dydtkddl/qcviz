"""Rendering utilities — Phase η: 자동 선택 로직."""


def get_best_renderer() -> str:
    try:
        import pyvista  # noqa: F401

        return "pyvista"
    except ImportError:
        pass
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return "playwright"
    except ImportError:
        pass
    return "html_only"


try:
    from qcviz_mcp.renderers.pyvista_renderer import (  # noqa: F401
        is_available as pyvista_available,
    )
    from qcviz_mcp.renderers.pyvista_renderer import (
        render_from_cube_string,
        render_orbital_png,
    )

    HAS_PYVISTA = pyvista_available()
except ImportError:
    HAS_PYVISTA = False
