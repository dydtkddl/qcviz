"""QCViz-MCP v3 services package.

# FIX(N0): 신규 services 패키지 초기화
Provides molecule resolution, API clients, and Gemini agent integration.
"""
from __future__ import annotations

from .ko_aliases import KO_TO_EN, translate  # noqa: F401
from .sdf_converter import sdf_to_xyz, merge_sdfs, sdf_to_atoms_list  # noqa: F401
from .molchat_client import MolChatClient  # noqa: F401
from .pubchem_client import PubChemClient  # noqa: F401
from .ion_pair_handler import IonPairResult, ION_ALIASES, is_ion_pair, resolve_ion_pair  # noqa: F401
from .structure_resolver import StructureResolver, StructureResult  # noqa: F401
from .gemini_agent import GeminiAgent, GeminiResult  # noqa: F401

__all__ = [
    "KO_TO_EN",
    "translate",
    "sdf_to_xyz",
    "merge_sdfs",
    "sdf_to_atoms_list",
    "MolChatClient",
    "PubChemClient",
    "IonPairResult",
    "ION_ALIASES",
    "is_ion_pair",
    "resolve_ion_pair",
    "StructureResolver",
    "StructureResult",
    "GeminiAgent",
    "GeminiResult",
]
