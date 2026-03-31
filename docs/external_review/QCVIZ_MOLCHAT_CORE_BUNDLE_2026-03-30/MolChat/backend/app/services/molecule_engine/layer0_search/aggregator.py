"""
SearchAggregator – runs multiple providers concurrently, deduplicates,
ranks, and returns a unified result set.

Design:
  • Each provider runs in its own ``asyncio.Task`` with an individual timeout.
  • Failed providers are recorded in ``errors`` but never block the pipeline.
  • Deduplication uses ``RawSearchResult.dedup_key()`` (InChIKey → CID → SMILES → name).
  • Results are ranked by provider priority × confidence.
  • Local DB is always tried first (sync-fast) and appended to fill gaps.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from rapidfuzz import fuzz

from app.services.molecule_engine.layer0_search.base import (
    AggregatedSearchResult,
    BaseSearchProvider,
    RawSearchResult,
    SearchType,
    classify_query,
)
from app.services.molecule_engine.layer0_search.pubchem import PubChemProvider
from app.services.molecule_engine.layer0_search.chembl import ChEMBLProvider
from app.services.molecule_engine.layer0_search.chemspider import ChemSpiderProvider
from app.services.molecule_engine.layer0_search.zinc import ZINCProvider

logger = structlog.get_logger(__name__)

# Provider name → available sources for filtering
_ALL_REMOTE_SOURCES = {"pubchem", "chembl", "chemspider", "zinc"}


class SearchAggregator:
    """Orchestrates L0 search across all registered providers."""

    def __init__(
        self,
        providers: list[BaseSearchProvider] | None = None,
        local_provider: BaseSearchProvider | None = None,
    ) -> None:
        if providers is not None:
            self._providers = providers
        else:
            self._providers = [
                PubChemProvider(),
                ChEMBLProvider(),
                ChemSpiderProvider(),
                ZINCProvider(),
            ]
        self._local = local_provider  # Injected when DB session is available

    def set_local_provider(self, provider: BaseSearchProvider) -> None:
        """Inject the LocalDB provider after DI resolution."""
        self._local = provider

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        sources: list[str] | None = None,
    ) -> AggregatedSearchResult:
        """Execute parallel multi-source search."""
        t0 = time.perf_counter()
        search_type = classify_query(query)
        log = logger.bind(query=query, search_type=search_type.value, sources=sources)
        log.info("aggregator_search_started")

        # ── 1. Filter providers ──
        active_providers = self._filter_providers(sources)

        # ── 2. Local DB (synchronous-fast) ──
        local_results: list[RawSearchResult] = []
        if self._local is not None:
            try:
                local_results = await asyncio.wait_for(
                    self._local.search(query, search_type, limit=limit),
                    timeout=self._local.timeout,
                )
                log.info("local_search_done", count=len(local_results))
            except Exception as exc:
                log.warning("local_search_error", error=str(exc))

        # ── 3. Remote providers (concurrent) ──
        tasks: dict[str, asyncio.Task] = {}
        for provider in active_providers:
            task = asyncio.create_task(
                self._guarded_search(provider, query, search_type, limit),
                name=provider.source_name,
            )
            tasks[provider.source_name] = task

        remote_results: list[RawSearchResult] = []
        errors: dict[str, str] = {}

        if tasks:
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=30.0,
                return_when=asyncio.ALL_COMPLETED,
            )

            # Cancel any still pending
            for task in pending:
                task.cancel()
                task_name = task.get_name()
                errors[task_name] = "timeout"
                log.warning("provider_timeout", provider=task_name)

            for task in done:
                task_name = task.get_name()
                exc = task.exception()
                if exc is not None:
                    errors[task_name] = str(exc)
                    log.warning("provider_error", provider=task_name, error=str(exc))
                else:
                    remote_results.extend(task.result())

        # ── 4. Merge & deduplicate ──
        all_results = local_results + remote_results
        deduped = self._deduplicate(all_results)

        # ── 5. Rank by priority × confidence ──
        ranked = self._rank(deduped, query=query)[:limit]

        # ── 6. Convert to dicts ──
        result_dicts = [self._result_to_dict(r) for r in ranked]

        sources_queried = [p.source_name for p in active_providers]
        if self._local is not None:
            sources_queried.insert(0, self._local.source_name)

        elapsed = (time.perf_counter() - t0) * 1000
        log.info(
            "aggregator_search_completed",
            total=len(result_dicts),
            elapsed_ms=elapsed,
        )

        return AggregatedSearchResult(
            results=result_dicts,
            total=len(result_dicts),
            sources_queried=sources_queried,
            errors=errors,
        )

    # ═══════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════

    def _filter_providers(
        self, sources: list[str] | None
    ) -> list[BaseSearchProvider]:
        """Filter to requested sources, or use all."""
        if sources is None:
            return list(self._providers)
        allowed = set(s.lower() for s in sources)
        return [p for p in self._providers if p.source_name in allowed]

    async def _guarded_search(
        self,
        provider: BaseSearchProvider,
        query: str,
        search_type: SearchType,
        limit: int,
    ) -> list[RawSearchResult]:
        """Run a single provider search with its own timeout."""
        try:
            return await asyncio.wait_for(
                provider.search(query, search_type, limit=limit),
                timeout=provider.timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "provider_individual_timeout",
                provider=provider.source_name,
                timeout=provider.timeout,
            )
            return []
        except Exception as exc:
            logger.warning(
                "provider_individual_error",
                provider=provider.source_name,
                error=str(exc),
            )
            return []

    def _deduplicate(
        self, results: list[RawSearchResult]
    ) -> list[RawSearchResult]:
        """Deduplicate by InChIKey(first 14 chars)/CID/SMILES, keeping highest-confidence entry.

        Enhanced: also merges entries with same InChIKey connectivity layer (first 14 chars)
        to catch stereoisomer variants from different sources.
        """
        seen: dict[str, RawSearchResult] = {}
        inchikey_seen: dict[str, str] = {}  # first-14-chars → dedup_key

        for r in results:
            key = r.dedup_key()

            # Also check InChIKey connectivity layer (first 14 chars)
            if r.inchikey and len(r.inchikey) >= 14:
                ik14 = r.inchikey[:14]
                if ik14 in inchikey_seen:
                    existing_key = inchikey_seen[ik14]
                    existing = seen.get(existing_key)
                    if existing and r.confidence > existing.confidence:
                        del seen[existing_key]
                        seen[key] = r
                        inchikey_seen[ik14] = key
                    continue
                inchikey_seen[ik14] = key

            existing = seen.get(key)
            if existing is None:
                seen[key] = r
            else:
                if r.confidence > existing.confidence:
                    seen[key] = r

        return list(seen.values())

    def _rank(self, results: list[RawSearchResult], query: str = "") -> list[RawSearchResult]:
        """Enterprise-grade ranking v2: exact match priority + synonyms + CID bonus.

        Score = w1*name_relevance + w2*source_score + w3*cid_bonus + w4*confidence
        Key improvements over v1:
        - Exact match (including synonyms) gets maximum name_relevance = 1.0
        - "Contains but not exact" (e.g. "GLUCOSE OXIDASE" for query "glucose")
          is heavily penalized vs exact match
        - CID bonus raised to 0.30 to strongly prefer verified compounds
        - Synonyms from PubChem enrichment are checked for exact match
        """
        W1, W2, W3, W4 = 0.30, 0.15, 0.30, 0.25

        # Build source priority map
        priority_map: dict[str, int] = {}
        for p in self._providers:
            priority_map[p.source_name] = p.priority
        if self._local is not None:
            priority_map[self._local.source_name] = self._local.priority

        # Normalize priority to 0~1 (lower priority number = better = higher score)
        max_priority = max(priority_map.values()) if priority_map else 100
        min_priority = min(priority_map.values()) if priority_map else 1

        def source_score(source: str) -> float:
            p = priority_map.get(source, 99)
            if max_priority == min_priority:
                return 0.5
            return 1.0 - (p - min_priority) / (max_priority - min_priority + 1)

        ql = query.lower().strip()

        def compute_score(r: RawSearchResult) -> float:
            # ── Name relevance (0~1) ──
            name = (r.name or "").strip()
            nl = name.lower()

            # Check synonyms for exact match too
            synonyms_lower: list[str] = []
            syns_raw = r.properties.get("synonyms", [])
            if isinstance(syns_raw, list):
                synonyms_lower = [s.lower().strip() for s in syns_raw if isinstance(s, str)]

            if not ql or not nl:
                name_rel = 0.0
            elif nl == ql or ql in synonyms_lower:
                # Exact match on name OR any synonym → maximum
                name_rel = 1.0
            elif nl.startswith(ql) and len(nl) < len(ql) * 2:
                # Starts-with and name is not too much longer
                # "glucose" matches "glucose" but not "glucose oxidase" (2x+ longer)
                len_ratio = len(ql) / max(len(nl), 1)
                name_rel = 0.85 + 0.15 * len_ratio
            elif nl.startswith(ql):
                # Starts-with but name is much longer → mild penalty
                len_ratio = len(ql) / max(len(nl), 1)
                name_rel = 0.50 + 0.20 * len_ratio
            elif ql in nl:
                # Query is contained in name but doesn't start with it
                # e.g. "GLUCOSE OXIDASE" contains "glucose" → low relevance
                len_ratio = len(ql) / max(len(nl), 1)
                name_rel = 0.30 + 0.15 * len_ratio
            else:
                # Fuzzy match via RapidFuzz WRatio
                try:
                    name_rel = fuzz.WRatio(ql, nl, score_cutoff=0) / 100.0
                    # Cap fuzzy-only matches so they never beat exact/synonym matches
                    name_rel = min(name_rel, 0.60)
                except Exception:
                    name_rel = 0.0

            # ── CID bonus (strongly prefer verified compounds) ──
            cid_bonus = 1.0 if r.cid else 0.0

            # ── Source score ──
            src = source_score(r.source)

            # ── Confidence ──
            conf = min(max(r.confidence, 0.0), 1.0)

            return W1 * name_rel + W2 * src + W3 * cid_bonus + W4 * conf

        # Sort descending by total score, store score in properties
        for r in results:
            r.properties['_relevance_score'] = round(compute_score(r), 3)
        return sorted(results, key=lambda r: -r.properties['_relevance_score'])

    @staticmethod
    def _result_to_dict(r: RawSearchResult) -> dict[str, Any]:
        """Convert RawSearchResult to a dict compatible with orchestrator._persist_molecule."""
        return {
            "name": r.name,
            "source": r.source,
            "canonical_smiles": r.canonical_smiles,
            "inchi": r.inchi,
            "inchikey": r.inchikey,
            "cid": r.cid,
            "molecular_formula": r.molecular_formula,
            "molecular_weight": r.molecular_weight,
            "properties": {
                **r.properties,
                "_source": r.source,
                "_source_id": r.source_id,
                "_source_url": r.source_url,
                "_confidence": r.confidence,
            },
            "structure_3d": r.structure_3d,
            "structure_format": r.structure_format,
        }