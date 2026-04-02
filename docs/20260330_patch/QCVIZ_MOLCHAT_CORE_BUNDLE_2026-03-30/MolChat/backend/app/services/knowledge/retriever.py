"""
KnowledgeRetriever – top-level facade for context retrieval.

Pipeline:
  1. Embed the query into a dense vector.
  2. Retrieve candidate chunks via hybrid search (vector + full-text).
  3. Re-rank candidates with the ChunkRanker.
  4. Return the top-K context chunks with metadata and scores.

Usage by the agent:
  retriever = KnowledgeRetriever(db, redis)
  context_chunks = await retriever.retrieve("What is the pKa of aspirin?", top_k=5)
  # → inject chunks into the LLM system prompt as grounding context.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.knowledge.embedder import TextEmbedder
from app.services.knowledge.ranker import ChunkRanker, ScoredChunk

logger = structlog.get_logger(__name__)

_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20
_VECTOR_WEIGHT = 0.6
_TEXT_WEIGHT = 0.4


@dataclass
class RetrievalResult:
    """Output of a knowledge retrieval query."""

    query: str
    chunks: list[ScoredChunk] = field(default_factory=list)
    total_candidates: int = 0
    elapsed_ms: float = 0.0
    search_modes_used: list[str] = field(default_factory=list)


class KnowledgeRetriever:
    """Hybrid (vector + full-text) knowledge retrieval with re-ranking."""

    def __init__(
        self,
        db: AsyncSession,
        embedder: TextEmbedder | None = None,
        ranker: ChunkRanker | None = None,
    ) -> None:
        self._db = db
        self._embedder = embedder or TextEmbedder()
        self._ranker = ranker or ChunkRanker()

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = _DEFAULT_TOP_K,
        source_filter: list[str] | None = None,
        min_score: float = 0.1,
    ) -> RetrievalResult:
        """Retrieve relevant knowledge chunks for a query.

        Args:
            query: Natural-language question or topic.
            top_k: Maximum number of chunks to return.
            source_filter: Restrict to specific sources (e.g., ["safety", "property"]).
            min_score: Minimum combined score threshold.
        """
        t0 = time.perf_counter()
        top_k = min(top_k, _MAX_TOP_K)
        log = logger.bind(query=query[:80], top_k=top_k)
        log.info("retrieval_started")

        result = RetrievalResult(query=query)

        # ── 1. Embed query ──
        query_embedding = await self._embedder.embed(query)
        has_vector = query_embedding is not None

        # ── 2. Hybrid search ──
        candidates: list[ScoredChunk] = []

        # 2a. Vector search
        if has_vector:
            vector_hits = await self._vector_search(
                query_embedding, top_k=top_k * 3, source_filter=source_filter
            )
            candidates.extend(vector_hits)
            result.search_modes_used.append("vector")

        # 2b. Full-text search (always)
        text_hits = await self._fulltext_search(
            query, top_k=top_k * 3, source_filter=source_filter
        )
        candidates.extend(text_hits)
        result.search_modes_used.append("fulltext")

        # ── 3. Deduplicate ──
        candidates = self._deduplicate(candidates)
        result.total_candidates = len(candidates)

        # ── 4. Re-rank ──
        ranked = await self._ranker.rank(
            query=query,
            chunks=candidates,
            top_k=top_k,
        )

        # ── 5. Filter by min_score ──
        result.chunks = [c for c in ranked if c.score >= min_score]

        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "retrieval_completed",
            candidates=result.total_candidates,
            returned=len(result.chunks),
            elapsed_ms=result.elapsed_ms,
        )

        return result

    async def retrieve_for_molecule(
        self,
        molecule_name: str,
        smiles: str | None = None,
        *,
        categories: list[str] | None = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        """Specialized retrieval for molecule-specific knowledge.

        Searches across safety data, property explanations, and
        chemical ontology for the given molecule.
        """
        # Build enhanced query
        query_parts = [molecule_name]
        if smiles:
            query_parts.append(f"SMILES: {smiles}")
        if categories:
            query_parts.append(f"categories: {', '.join(categories)}")

        enhanced_query = " ".join(query_parts)

        return await self.retrieve(
            enhanced_query,
            top_k=top_k,
            source_filter=categories,
        )

    # ═══════════════════════════════════════════
    # Vector search
    # ═══════════════════════════════════════════

    async def _vector_search(
        self,
        embedding: list[float],
        top_k: int,
        source_filter: list[str] | None,
    ) -> list[ScoredChunk]:
        """Approximate nearest-neighbor search using pgvector or fallback."""
        try:
            # Attempt pgvector cosine similarity
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            filter_clause = ""
            params: dict[str, Any] = {
                "embedding": embedding_str,
                "limit": top_k,
            }

            if source_filter:
                placeholders = ", ".join(f":src_{i}" for i in range(len(source_filter)))
                filter_clause = f"AND kc.source IN ({placeholders})"
                for i, src in enumerate(source_filter):
                    params[f"src_{i}"] = src

            query = text(f"""
                SELECT
                    kc.id,
                    kc.content,
                    kc.title,
                    kc.source,
                    kc.metadata,
                    1 - (kc.embedding <=> :embedding::vector) AS similarity
                FROM knowledge_chunks kc
                WHERE kc.embedding IS NOT NULL
                {filter_clause}
                ORDER BY kc.embedding <=> :embedding::vector
                LIMIT :limit
            """)

            result = await self._db.execute(query, params)
            rows = result.fetchall()

            chunks = []
            for row in rows:
                chunks.append(ScoredChunk(
                    chunk_id=str(row.id),
                    content=row.content,
                    title=row.title or "",
                    source=row.source or "",
                    metadata=row.metadata or {},
                    score=float(row.similarity) * _VECTOR_WEIGHT,
                    search_mode="vector",
                ))
            return chunks

        except Exception as exc:
            # pgvector not available or table doesn't exist yet
            logger.debug("vector_search_unavailable", error=str(exc))
            return []

    # ═══════════════════════════════════════════
    # Full-text search
    # ═══════════════════════════════════════════

    async def _fulltext_search(
        self,
        query: str,
        top_k: int,
        source_filter: list[str] | None,
    ) -> list[ScoredChunk]:
        """PostgreSQL full-text search with ts_rank."""
        try:
            filter_clause = ""
            params: dict[str, Any] = {
                "query": query,
                "limit": top_k,
            }

            if source_filter:
                placeholders = ", ".join(f":src_{i}" for i in range(len(source_filter)))
                filter_clause = f"AND kc.source IN ({placeholders})"
                for i, src in enumerate(source_filter):
                    params[f"src_{i}"] = src

            sql = text(f"""
                SELECT
                    kc.id,
                    kc.content,
                    kc.title,
                    kc.source,
                    kc.metadata,
                    ts_rank(kc.search_vector, plainto_tsquery('english', :query)) AS rank
                FROM knowledge_chunks kc
                WHERE kc.search_vector @@ plainto_tsquery('english', :query)
                {filter_clause}
                ORDER BY rank DESC
                LIMIT :limit
            """)

            result = await self._db.execute(sql, params)
            rows = result.fetchall()

            chunks = []
            for row in rows:
                chunks.append(ScoredChunk(
                    chunk_id=str(row.id),
                    content=row.content,
                    title=row.title or "",
                    source=row.source or "",
                    metadata=row.metadata or {},
                    score=float(row.rank) * _TEXT_WEIGHT,
                    search_mode="fulltext",
                ))
            return chunks

        except Exception as exc:
            logger.warning("fulltext_search_error", error=str(exc))
            return []

    # ═══════════════════════════════════════════
    # Deduplication
    # ═══════════════════════════════════════════

    @staticmethod
    def _deduplicate(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
        """Merge duplicate chunks, summing scores from different search modes."""
        seen: dict[str, ScoredChunk] = {}

        for chunk in chunks:
            key = chunk.chunk_id
            if key in seen:
                existing = seen[key]
                # Combine scores from different search modes
                existing.score = min(existing.score + chunk.score, 1.0)
                if chunk.search_mode not in existing.search_mode:
                    existing.search_mode += f"+{chunk.search_mode}"
            else:
                seen[key] = ScoredChunk(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    title=chunk.title,
                    source=chunk.source,
                    metadata=chunk.metadata,
                    score=chunk.score,
                    search_mode=chunk.search_mode,
                )

        return list(seen.values())
