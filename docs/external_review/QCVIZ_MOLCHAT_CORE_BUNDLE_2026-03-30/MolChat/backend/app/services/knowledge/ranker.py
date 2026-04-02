"""
ChunkRanker – re-rank retrieved knowledge chunks for relevance.

Ranking signals (combined via weighted sum):
  1. **Semantic similarity** – cosine between query and chunk embeddings (if available).
  2. **Keyword overlap** – Jaccard coefficient on normalized token sets.
  3. **Source authority** – static weight per source type.
  4. **Recency** – newer chunks get a slight boost.
  5. **Length penalty** – penalize very short or very long chunks.

This is a lightweight rule-based ranker. It can be replaced by a
cross-encoder model (e.g., ``ms-marco-MiniLM``) for higher accuracy.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from app.services.knowledge.embedder import TextEmbedder

logger = structlog.get_logger(__name__)

# Weight configuration
_W_SEMANTIC = 0.40
_W_KEYWORD = 0.25
_W_AUTHORITY = 0.15
_W_RECENCY = 0.10
_W_LENGTH = 0.10

# Source authority scores (0.0–1.0)
_SOURCE_AUTHORITY: dict[str, float] = {
    "safety": 1.0,       # Safety data is critical
    "property": 0.9,     # Well-established property data
    "ontology": 0.85,    # Chemical ontology (IUPAC, etc.)
    "pubchem": 0.8,      # PubChem curated data
    "textbook": 0.8,     # Textbook material
    "wiki": 0.6,         # Wikipedia (less authoritative)
    "community": 0.4,    # User-generated content
}

# Ideal chunk length range (characters)
_IDEAL_LENGTH_MIN = 100
_IDEAL_LENGTH_MAX = 1500


@dataclass
class ScoredChunk:
    """A knowledge chunk with its relevance score."""

    chunk_id: str
    content: str
    title: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    search_mode: str = ""

    # Detailed scores (for debugging / explainability)
    score_breakdown: dict[str, float] = field(default_factory=dict)


class ChunkRanker:
    """Re-rank retrieved chunks using multiple signals."""

    def __init__(self, embedder: TextEmbedder | None = None) -> None:
        self._embedder = embedder or TextEmbedder()

    async def rank(
        self,
        query: str,
        chunks: list[ScoredChunk],
        *,
        top_k: int = 5,
    ) -> list[ScoredChunk]:
        """Re-rank and return the top-K chunks.

        Each chunk's ``score`` is overwritten with the combined re-ranked score.
        """
        if not chunks:
            return []

        query_tokens = self._tokenize(query)
        query_embedding = await self._embedder.embed(query)

        for chunk in chunks:
            breakdown: dict[str, float] = {}

            # 1. Semantic similarity
            if query_embedding:
                chunk_embedding = await self._embedder.embed(chunk.content[:512])
                if chunk_embedding:
                    breakdown["semantic"] = self._cosine_similarity(
                        query_embedding, chunk_embedding
                    )
                else:
                    breakdown["semantic"] = 0.0
            else:
                breakdown["semantic"] = 0.0

            # 2. Keyword overlap (Jaccard)
            chunk_tokens = self._tokenize(chunk.content)
            breakdown["keyword"] = self._jaccard(query_tokens, chunk_tokens)

            # 3. Source authority
            breakdown["authority"] = _SOURCE_AUTHORITY.get(
                chunk.source.lower(), 0.5
            )

            # 4. Recency
            breakdown["recency"] = self._recency_score(chunk.metadata)

            # 5. Length penalty
            breakdown["length"] = self._length_score(len(chunk.content))

            # Combined weighted score
            combined = (
                breakdown["semantic"] * _W_SEMANTIC
                + breakdown["keyword"] * _W_KEYWORD
                + breakdown["authority"] * _W_AUTHORITY
                + breakdown["recency"] * _W_RECENCY
                + breakdown["length"] * _W_LENGTH
            )

            chunk.score = round(combined, 4)
            chunk.score_breakdown = breakdown

        # Sort descending by score
        ranked = sorted(chunks, key=lambda c: c.score, reverse=True)
        return ranked[:top_k]

    # ═══════════════════════════════════════════
    # Signal calculators
    # ═══════════════════════════════════════════

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    @staticmethod
    def _jaccard(tokens_a: set[str], tokens_b: set[str]) -> float:
        """Jaccard similarity between two token sets."""
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    @staticmethod
    def _recency_score(metadata: dict[str, Any]) -> float:
        """Score based on content age. Newer = higher.

        Returns 1.0 for content < 30 days old, decaying to 0.3 for > 2 years.
        """
        created_str = metadata.get("created_at") or metadata.get("indexed_at")
        if not created_str:
            return 0.5  # Unknown age → neutral

        try:
            if isinstance(created_str, datetime):
                created = created_str
            else:
                created = datetime.fromisoformat(str(created_str))

            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            days_old = (now - created).days

            if days_old <= 30:
                return 1.0
            elif days_old <= 365:
                return 0.8
            elif days_old <= 730:
                return 0.5
            else:
                return 0.3
        except (ValueError, TypeError):
            return 0.5

    @staticmethod
    def _length_score(char_count: int) -> float:
        """Penalize chunks that are too short or too long.

        Ideal range: 100–1500 characters → score 1.0.
        Below 50 or above 3000 → score 0.3.
        """
        if _IDEAL_LENGTH_MIN <= char_count <= _IDEAL_LENGTH_MAX:
            return 1.0
        elif char_count < 50:
            return 0.3
        elif char_count < _IDEAL_LENGTH_MIN:
            return 0.5 + 0.5 * (char_count / _IDEAL_LENGTH_MIN)
        elif char_count <= 3000:
            return 1.0 - 0.5 * (
                (char_count - _IDEAL_LENGTH_MAX)
                / (3000 - _IDEAL_LENGTH_MAX)
            )
        else:
            return 0.3

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Simple whitespace + punctuation tokenizer with lowercasing."""
        text = text.lower()
        tokens = re.findall(r"[a-z0-9\u3131-\u318e\uac00-\ud7a3]+", text)
        # Remove very short tokens
        return {t for t in tokens if len(t) >= 2}