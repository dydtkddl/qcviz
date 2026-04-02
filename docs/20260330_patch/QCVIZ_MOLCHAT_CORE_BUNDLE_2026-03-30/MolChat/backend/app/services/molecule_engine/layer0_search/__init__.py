
## 39 `backend/app/services/molecule_engine/layer0_search/__init__.py`

"""
Layer 0 – Multi-source molecular search.

Adapters:
  • PubChem     (primary, free, REST)
  • ChEMBL      (secondary, free, REST)
  • ChemSpider  (tertiary, API-key required)
  • ZINC-22     (quaternary, free, REST)
  • LocalDB     (PostgreSQL full-text fallback)

All adapters implement ``BaseSearchProvider`` and are orchestrated by
``SearchAggregator`` which runs them concurrently with per-provider
timeouts, deduplication, and priority-based ranking.
"""

from app.services.molecule_engine.layer0_search.aggregator import SearchAggregator
from app.services.molecule_engine.layer0_search.base import (
    BaseSearchProvider,
    RawSearchResult,
    AggregatedSearchResult,
)

__all__ = [
    "SearchAggregator",
    "BaseSearchProvider",
    "RawSearchResult",
    "AggregatedSearchResult",
]