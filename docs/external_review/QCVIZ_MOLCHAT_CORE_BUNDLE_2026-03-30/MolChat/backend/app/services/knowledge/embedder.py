"""
TextEmbedder – generate dense vector embeddings for text chunks.

Strategy (ordered by preference):
  1. Local ONNX model (``all-MiniLM-L6-v2``, 384 dims) – fastest, no API cost.
  2. Ollama embeddings endpoint (``nomic-embed-text``) – moderate speed, local.
  3. Fallback: None (full-text search only).

The embedder is lazy-loaded on first use to avoid slowing app startup.
Embeddings are cached in Redis for 24 h to avoid recomputation.

Thread-safety: ONNX Runtime sessions are thread-safe for inference.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_EMBEDDING_DIM = 384
_CACHE_PREFIX = "molchat:emb:"
_CACHE_TTL = 86400  # 24 hours


class TextEmbedder:
    """Generate text embeddings with automatic backend selection."""

    def __init__(self) -> None:
        self._backend: str | None = None
        self._onnx_session: Any = None
        self._tokenizer: Any = None
        self._initialized = False

    @property
    def embedding_dim(self) -> int:
        return _EMBEDDING_DIM

    async def embed(self, text: str) -> list[float] | None:
        """Generate an embedding vector for the given text.

        Returns a list of floats (length = embedding_dim) or None if
        no backend is available.
        """
        if not text or not text.strip():
            return None

        # Check cache
        cached = await self._get_cached(text)
        if cached is not None:
            return cached

        # Initialize on first use
        if not self._initialized:
            await self._initialize()

        embedding: list[float] | None = None

        if self._backend == "onnx":
            embedding = await self._embed_onnx(text)
        elif self._backend == "ollama":
            embedding = await self._embed_ollama(text)

        # Cache result
        if embedding is not None:
            await self._set_cached(text, embedding)

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed multiple texts. Returns a list parallel to input."""
        results: list[list[float] | None] = []
        for txt in texts:
            vec = await self.embed(txt)
            results.append(vec)
        return results

    async def health_check(self) -> dict[str, Any]:
        """Return embedding backend status."""
        if not self._initialized:
            await self._initialize()
        return {
            "backend": self._backend or "none",
            "embedding_dim": _EMBEDDING_DIM,
            "available": self._backend is not None,
        }

    # ═══════════════════════════════════════════
    # Initialization
    # ═══════════════════════════════════════════

    async def _initialize(self) -> None:
        """Detect and initialize the best available embedding backend."""
        self._initialized = True

        # Try ONNX
        if await self._init_onnx():
            self._backend = "onnx"
            logger.info("embedder_initialized", backend="onnx")
            return

        # Try Ollama
        if await self._init_ollama():
            self._backend = "ollama"
            logger.info("embedder_initialized", backend="ollama")
            return

        self._backend = None
        logger.warning("embedder_no_backend_available")

    async def _init_onnx(self) -> bool:
        """Try to load the ONNX sentence-transformer model."""
        try:
            from tokenizers import Tokenizer

            model_path = "models/all-MiniLM-L6-v2"

            import onnxruntime as ort

            self._onnx_session = ort.InferenceSession(
                f"{model_path}/model.onnx",
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = Tokenizer.from_file(
                f"{model_path}/tokenizer.json"
            )
            return True

        except (ImportError, FileNotFoundError, Exception) as exc:
            logger.debug("onnx_embedder_unavailable", error=str(exc))
            return False

    async def _init_ollama(self) -> bool:
        """Check if Ollama has an embedding model available."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    embed_models = [
                        m for m in models
                        if "embed" in m.get("name", "").lower()
                        or "nomic" in m.get("name", "").lower()
                    ]
                    return len(embed_models) > 0
            return False
        except Exception:
            return False

    # ═══════════════════════════════════════════
    # ONNX backend
    # ═══════════════════════════════════════════

    async def _embed_onnx(self, text: str) -> list[float] | None:
        """Generate embedding using local ONNX model."""
        return await asyncio.to_thread(self._embed_onnx_sync, text)

    def _embed_onnx_sync(self, text: str) -> list[float] | None:
        """Synchronous ONNX inference."""
        try:
            import numpy as np

            # Tokenize
            encoded = self._tokenizer.encode(text)
            input_ids = encoded.ids[:512]  # Truncate to model max length
            attention_mask = encoded.attention_mask[:512]

            # Pad to length
            pad_length = 512 - len(input_ids)
            input_ids += [0] * pad_length
            attention_mask += [0] * pad_length

            # Run inference
            inputs = {
                "input_ids": np.array([input_ids], dtype=np.int64),
                "attention_mask": np.array([attention_mask], dtype=np.int64),
                "token_type_ids": np.zeros((1, 512), dtype=np.int64),
            }

            outputs = self._onnx_session.run(None, inputs)

            # Mean pooling over token embeddings
            token_embeddings = outputs[0]  # (1, seq_len, hidden_dim)
            mask = np.array([attention_mask], dtype=np.float32)
            mask = np.expand_dims(mask, axis=-1)

            sum_embeddings = np.sum(token_embeddings * mask, axis=1)
            sum_mask = np.sum(mask, axis=1)
            sum_mask = np.clip(sum_mask, a_min=1e-9, a_max=None)

            embedding = (sum_embeddings / sum_mask)[0]

            # L2 normalize
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding.tolist()

        except Exception as exc:
            logger.warning("onnx_embed_error", error=str(exc))
            return None

    # ═══════════════════════════════════════════
    # Ollama backend
    # ═══════════════════════════════════════════

    async def _embed_ollama(self, text: str) -> list[float] | None:
        """Generate embedding using Ollama embeddings API."""
        try:
            import httpx

            url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
            body = {
                "model": "nomic-embed-text",
                "prompt": text[:2048],  # Truncate
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embedding")

                if embedding and len(embedding) > 0:
                    return embedding

            return None

        except Exception as exc:
            logger.warning("ollama_embed_error", error=str(exc))
            return None

    # ═══════════════════════════════════════════
    # Cache
    # ═══════════════════════════════════════════

    @staticmethod
    def _cache_key(text: str) -> str:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"{_CACHE_PREFIX}{text_hash}"

    async def _get_cached(self, text: str) -> list[float] | None:
        """Look up a cached embedding."""
        try:
            from app.core.redis import get_redis_client
            import json as json_mod

            client = get_redis_client()
            raw = await client.get(self._cache_key(text))
            await client.aclose()

            if raw is None:
                return None
            return json_mod.loads(raw)

        except Exception:
            return None

    async def _set_cached(self, text: str, embedding: list[float]) -> None:
        """Cache an embedding."""
        try:
            from app.core.redis import get_redis_client
            import json as json_mod

            client = get_redis_client()
            await client.set(
                self._cache_key(text),
                json_mod.dumps(embedding),
                ex=_CACHE_TTL,
            )
            await client.aclose()

        except Exception:
            pass