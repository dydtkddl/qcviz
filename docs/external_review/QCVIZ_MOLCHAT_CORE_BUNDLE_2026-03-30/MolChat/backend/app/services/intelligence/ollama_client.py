"""
OllamaClient – async wrapper for the Ollama REST API (local LLM).

Serves as the fallback when Gemini is unavailable or over budget.
Supports tool/function calling (Ollama ≥ 0.4 with compatible models),
streaming, and model management.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=10.0)


class OllamaClient:
    """Async client for the Ollama local LLM server."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self._base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or settings.OLLAMA_MODEL_PRIMARY
        self._fallback_model = fallback_model or settings.OLLAMA_MODEL_FALLBACK
        self._num_ctx = settings.OLLAMA_NUM_CTX

    @property
    def model_name(self) -> str:
        return self._model

    # ═══════════════════════════════════════════
    # Generate (non-streaming)
    # ═══════════════════════════════════════════

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to Ollama.

        Returns the same normalized dict structure as GeminiClient.
        """
        model = model_override or self._model
        url = f"{self._base_url}/api/chat"

        body = self._build_request_body(
            messages, model, tools, temperature, max_tokens
        )

        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()

        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            # Try fallback model
            if model != self._fallback_model:
                logger.warning(
                    "ollama_primary_failed_trying_fallback",
                    primary=model,
                    fallback=self._fallback_model,
                    error=str(exc),
                )
                return await self.generate(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model_override=self._fallback_model,
                )
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        result = self._parse_response(data, model)
        result["elapsed_ms"] = elapsed

        logger.info(
            "ollama_generate",
            model=model,
            tokens=result["token_count"],
            elapsed_ms=elapsed,
        )

        return result

    # ═══════════════════════════════════════════
    # Streaming
    # ═══════════════════════════════════════════

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response tokens as an async generator."""
        url = f"{self._base_url}/api/chat"

        body = self._build_request_body(
            messages, self._model, tools, temperature, max_tokens
        )
        body["stream"] = True

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        content = msg.get("content", "")
                        if content:
                            yield content
                        if chunk.get("done", False):
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue

    # ═══════════════════════════════════════════
    # Request / Response
    # ═══════════════════════════════════════════

    def _build_request_body(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build the Ollama chat API request body."""
        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "tool":
                # Ollama tool response format
                ollama_messages.append({
                    "role": "tool",
                    "content": content,
                })
                continue

            ollama_msg: dict[str, Any] = {
                "role": role,
                "content": content,
            }

            # Tool calls
            tool_calls = msg.get("tool_calls")
            if tool_calls and role == "assistant":
                ollama_msg["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", {}),
                        }
                    }
                    for tc in tool_calls
                ]

            ollama_messages.append(ollama_msg)

        body: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self._num_ctx,
                "top_p": 0.95,
                "repeat_penalty": 1.1,
            },
        }

        if tools:
            # Convert tool definitions to Ollama format
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]

        return body

    def _parse_response(
        self, data: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Parse Ollama response into normalized dict."""
        message = data.get("message", {})
        content = message.get("content", "")

        # Token counts
        prompt_eval = data.get("prompt_eval_count", 0)
        eval_count = data.get("eval_count", 0)

        # Tool calls
        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                fn = tc.get("function", {})
                tool_calls.append({
                    "id": f"call_{i}",
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", {}),
                })

        return {
            "content": content,
            "tool_calls": tool_calls,
            "token_count": prompt_eval + eval_count,
            "model": model,
            "finish_reason": "stop" if data.get("done") else "length",
            "cost_usd": 0.0,  # Local model = free
        }

    # ═══════════════════════════════════════════
    # Model management
    # ═══════════════════════════════════════════

    async def list_models(self) -> list[dict[str, Any]]:
        """List all locally available models."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return data.get("models", [])
        except Exception as exc:
            logger.warning("ollama_list_models_error", error=str(exc))
            return []

    async def is_model_available(self, model: str | None = None) -> bool:
        """Check if a specific model is downloaded."""
        model = model or self._model
        models = await self.list_models()
        return any(m.get("name", "").startswith(model) for m in models)

    async def health_check(self) -> dict[str, Any]:
        """Check Ollama server connectivity."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    primary_ready = any(
                        n.startswith(self._model) for n in model_names
                    )
                    return {
                        "status": "healthy" if primary_ready else "degraded",
                        "models_available": model_names,
                        "primary_model": self._model,
                        "primary_ready": primary_ready,
                    }
                return {"status": "degraded", "http_status": resp.status_code}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}