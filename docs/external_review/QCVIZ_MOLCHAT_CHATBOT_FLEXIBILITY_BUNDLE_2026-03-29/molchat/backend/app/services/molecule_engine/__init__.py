"""
Molecule Engine – three-layer architecture for molecular data acquisition,
structure processing, and quantum-chemical computation.

Architecture:
  ┌──────────────────────────────────────────────┐
  │            MoleculeOrchestrator               │
  │  (facade: routes all requests through layers) │
  └──────┬──────────┬──────────────┬─────────────┘
         │          │              │
    ┌────▼───┐ ┌────▼─────┐ ┌─────▼──────┐
    │Layer 0 │ │ Layer 1  │ │  Layer 2   │
    │Search  │ │Structure │ │Calculation │
    └────────┘ └──────────┘ └────────────┘

Cache Manager sits beside the orchestrator and transparently
handles Redis read-through / write-through caching.
"""

from app.services.molecule_engine.orchestrator import MoleculeOrchestrator
from app.services.molecule_engine.cache_manager import MoleculeCacheManager

__all__ = [
    "MoleculeOrchestrator",
    "MoleculeCacheManager",
]