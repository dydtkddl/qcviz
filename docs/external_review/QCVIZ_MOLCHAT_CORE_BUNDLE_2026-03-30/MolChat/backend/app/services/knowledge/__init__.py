"""
Knowledge Engine – Retrieval-Augmented Generation (RAG) for molecular chemistry.

Architecture:
  ┌──────────────────────────────────────────────────────┐
  │                  KnowledgeRetriever                   │
  │  (top-level facade: query → ranked context chunks)    │
  └────┬─────────────┬──────────────┬───────────────────┘
       │             │              │
  ┌────▼───┐   ┌────▼────┐   ┌────▼────┐
  │Embedder│   │ Indexer  │   │ Ranker  │
  │(vector)│   │(CRUD+idx)│   │(re-rank)│
  └────────┘   └─────────┘   └─────────┘
       │             │
  ┌────▼─────────────▼───┐
  │    KnowledgeSources   │
  │ (chem ontology, wiki, │
  │  safety DB, property)  │
  └───────────────────────┘

Storage: PostgreSQL (JSONB + tsvector) with optional pgvector extension.
All methods are async. Vector embeddings use a lightweight local model
(e.g., sentence-transformers via ONNX) to avoid external API costs.
"""

from app.services.knowledge.retriever import KnowledgeRetriever
from app.services.knowledge.indexer import KnowledgeIndexer
from app.services.knowledge.embedder import TextEmbedder
from app.services.knowledge.ranker import ChunkRanker
from app.services.knowledge.sources import KnowledgeSources

__all__ = [
    "KnowledgeRetriever",
    "KnowledgeIndexer",
    "TextEmbedder",
    "ChunkRanker",
    "KnowledgeSources",
]