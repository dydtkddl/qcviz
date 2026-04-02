"""
KnowledgeIndexer – CRUD operations and index management for the
knowledge_chunks table.

Responsibilities:
  • Insert / update / delete knowledge chunks.
  • Build and refresh tsvector search indexes.
  • Trigger embedding generation for new/updated chunks.
  • Bulk import from structured sources (JSON, CSV, Markdown).
  • Statistics and health reporting.

Table schema (created via Alembic migration):
  knowledge_chunks (
      id            UUID PRIMARY KEY,
      title         VARCHAR(512),
      content       TEXT NOT NULL,
      source        VARCHAR(100) NOT NULL,    -- 'safety', 'property', 'ontology', 'wiki'
      category      VARCHAR(100),
      tags          JSONB DEFAULT '[]',
      metadata      JSONB DEFAULT '{}',
      embedding     VECTOR(384),              -- pgvector (optional)
      search_vector TSVECTOR,                 -- full-text index
      created_at    TIMESTAMPTZ DEFAULT now(),
      updated_at    TIMESTAMPTZ DEFAULT now()
  )
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.embedder import TextEmbedder

logger = structlog.get_logger(__name__)


class KnowledgeIndexer:
    """Manage the knowledge_chunks table and its indexes."""

    def __init__(
        self,
        db: AsyncSession,
        embedder: TextEmbedder | None = None,
    ) -> None:
        self._db = db
        self._embedder = embedder or TextEmbedder()

    # ═══════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════

    async def add_chunk(
        self,
        content: str,
        source: str,
        *,
        title: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        generate_embedding: bool = True,
    ) -> str:
        """Insert a single knowledge chunk. Returns the chunk UUID."""
        chunk_id = str(uuid.uuid4())

        # Generate embedding
        embedding_value: str | None = None
        if generate_embedding:
            vec = await self._embedder.embed(content)
            if vec is not None:
                embedding_value = "[" + ",".join(str(x) for x in vec) + "]"

        sql = text("""
            INSERT INTO knowledge_chunks
                (id, title, content, source, category, tags, metadata,
                 embedding, search_vector, created_at, updated_at)
            VALUES
                (:id, :title, :content, :source, :category,
                 :tags::jsonb, :metadata::jsonb,
                 :embedding::vector,
                 to_tsvector('english', coalesce(:title, '') || ' ' || :content),
                 now(), now())
        """)

        await self._db.execute(sql, {
            "id": chunk_id,
            "title": title,
            "content": content,
            "source": source,
            "category": category,
            "tags": json.dumps(tags or []),
            "metadata": json.dumps(metadata or {}),
            "embedding": embedding_value,
        })
        await self._db.flush()

        logger.info(
            "chunk_added",
            chunk_id=chunk_id,
            source=source,
            has_embedding=embedding_value is not None,
        )
        return chunk_id

    async def update_chunk(
        self,
        chunk_id: str,
        *,
        content: str | None = None,
        title: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        regenerate_embedding: bool = True,
    ) -> bool:
        """Update an existing chunk. Returns True if found and updated."""
        set_clauses: list[str] = ["updated_at = now()"]
        params: dict[str, Any] = {"chunk_id": chunk_id}

        if content is not None:
            set_clauses.append("content = :content")
            set_clauses.append(
                "search_vector = to_tsvector('english', "
                "coalesce(:title_for_vec, title, '') || ' ' || :content)"
            )
            params["content"] = content
            params["title_for_vec"] = title

            if regenerate_embedding:
                vec = await self._embedder.embed(content)
                if vec is not None:
                    embedding_str = "[" + ",".join(str(x) for x in vec) + "]"
                    set_clauses.append("embedding = :embedding::vector")
                    params["embedding"] = embedding_str

        if title is not None:
            set_clauses.append("title = :title")
            params["title"] = title

        if category is not None:
            set_clauses.append("category = :category")
            params["category"] = category

        if tags is not None:
            set_clauses.append("tags = :tags::jsonb")
            params["tags"] = json.dumps(tags)

        if metadata is not None:
            set_clauses.append("metadata = :metadata::jsonb")
            params["metadata"] = json.dumps(metadata)

        sql = text(f"""
            UPDATE knowledge_chunks
            SET {', '.join(set_clauses)}
            WHERE id = :chunk_id
        """)

        result = await self._db.execute(sql, params)
        await self._db.flush()
        updated = result.rowcount > 0

        if updated:
            logger.info("chunk_updated", chunk_id=chunk_id)
        return updated

    async def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a chunk by ID."""
        sql = text("DELETE FROM knowledge_chunks WHERE id = :chunk_id")
        result = await self._db.execute(sql, {"chunk_id": chunk_id})
        await self._db.flush()
        deleted = result.rowcount > 0

        if deleted:
            logger.info("chunk_deleted", chunk_id=chunk_id)
        return deleted

    async def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Retrieve a single chunk by ID."""
        sql = text("""
            SELECT id, title, content, source, category, tags, metadata,
                   created_at, updated_at
            FROM knowledge_chunks
            WHERE id = :chunk_id
        """)
        result = await self._db.execute(sql, {"chunk_id": chunk_id})
        row = result.fetchone()
        if row is None:
            return None

        return {
            "id": str(row.id),
            "title": row.title,
            "content": row.content,
            "source": row.source,
            "category": row.category,
            "tags": row.tags,
            "metadata": row.metadata,
            "created_at": str(row.created_at),
            "updated_at": str(row.updated_at),
        }

    # ═══════════════════════════════════════════
    # Bulk operations
    # ═══════════════════════════════════════════

    async def bulk_import(
        self,
        chunks: list[dict[str, Any]],
        *,
        batch_size: int = 50,
        generate_embeddings: bool = True,
    ) -> dict[str, int]:
        """Import multiple chunks efficiently.

        Each chunk dict should have: content, source, and optionally
        title, category, tags, metadata.
        """
        imported = 0
        skipped = 0
        errors = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            for chunk_data in batch:
                try:
                    content = chunk_data.get("content", "").strip()
                    if not content:
                        skipped += 1
                        continue

                    await self.add_chunk(
                        content=content,
                        source=chunk_data.get("source", "unknown"),
                        title=chunk_data.get("title"),
                        category=chunk_data.get("category"),
                        tags=chunk_data.get("tags"),
                        metadata=chunk_data.get("metadata"),
                        generate_embedding=generate_embeddings,
                    )
                    imported += 1

                except Exception as exc:
                    logger.warning(
                        "bulk_import_chunk_error",
                        error=str(exc),
                        title=chunk_data.get("title", "")[:50],
                    )
                    errors += 1

            # Commit per batch
            await self._db.commit()

        result = {"imported": imported, "skipped": skipped, "errors": errors}
        logger.info("bulk_import_completed", **result)
        return result

    async def delete_by_source(self, source: str) -> int:
        """Delete all chunks from a given source."""
        sql = text("DELETE FROM knowledge_chunks WHERE source = :source")
        result = await self._db.execute(sql, {"source": source})
        await self._db.flush()
        count = result.rowcount
        logger.info("chunks_deleted_by_source", source=source, count=count)
        return count

    # ═══════════════════════════════════════════
    # Index maintenance
    # ═══════════════════════════════════════════

    async def rebuild_search_vectors(self) -> int:
        """Recompute all tsvector search_vector columns."""
        sql = text("""
            UPDATE knowledge_chunks
            SET search_vector = to_tsvector(
                'english',
                coalesce(title, '') || ' ' || content
            ),
            updated_at = now()
        """)
        result = await self._db.execute(sql)
        await self._db.flush()
        count = result.rowcount
        logger.info("search_vectors_rebuilt", count=count)
        return count

    async def rebuild_embeddings(self, batch_size: int = 20) -> int:
        """Re-generate embeddings for all chunks missing them."""
        sql = text("""
            SELECT id, content, title
            FROM knowledge_chunks
            WHERE embedding IS NULL
            ORDER BY created_at
        """)
        result = await self._db.execute(sql)
        rows = result.fetchall()

        updated = 0
        for row in rows:
            try:
                text_to_embed = f"{row.title or ''} {row.content}"
                vec = await self._embedder.embed(text_to_embed)
                if vec is not None:
                    embedding_str = "[" + ",".join(str(x) for x in vec) + "]"
                    update_sql = text("""
                        UPDATE knowledge_chunks
                        SET embedding = :embedding::vector, updated_at = now()
                        WHERE id = :chunk_id
                    """)
                    await self._db.execute(update_sql, {
                        "embedding": embedding_str,
                        "chunk_id": str(row.id),
                    })
                    updated += 1

                    if updated % batch_size == 0:
                        await self._db.flush()

            except Exception as exc:
                logger.warning(
                    "embedding_rebuild_error",
                    chunk_id=str(row.id),
                    error=str(exc),
                )

        await self._db.flush()
        logger.info("embeddings_rebuilt", count=updated)
        return updated

    # ═══════════════════════════════════════════
    # Statistics
    # ═══════════════════════════════════════════

    async def stats(self) -> dict[str, Any]:
        """Return knowledge base statistics."""
        try:
            total_sql = text("SELECT COUNT(*) FROM knowledge_chunks")
            total = (await self._db.execute(total_sql)).scalar() or 0

            by_source_sql = text("""
                SELECT source, COUNT(*) as cnt
                FROM knowledge_chunks
                GROUP BY source
                ORDER BY cnt DESC
            """)
            by_source_result = await self._db.execute(by_source_sql)
            by_source = {
                row.source: row.cnt
                for row in by_source_result.fetchall()
            }

            embedded_sql = text(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"
            )
            embedded = (await self._db.execute(embedded_sql)).scalar() or 0

            return {
                "total_chunks": total,
                "by_source": by_source,
                "with_embeddings": embedded,
                "without_embeddings": total - embedded,
                "embedding_coverage": round(embedded / max(total, 1) * 100, 1),
            }

        except Exception as exc:
            logger.warning("knowledge_stats_error", error=str(exc))
            return {"error": str(exc)}