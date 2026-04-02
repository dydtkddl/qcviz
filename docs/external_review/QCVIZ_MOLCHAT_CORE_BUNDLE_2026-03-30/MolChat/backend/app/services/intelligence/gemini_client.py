"""
GeminiClient – async wrapper for Google Gemini 2.5 Flash API.

Features:
  • Function/tool-calling support.
  • Streaming via async generators.
  • Automatic retry with exponential backoff (via tenacity).
  • Token counting and cost tracking.
  • Request timeout enforcement.

Cost tracking writes cumulative usage to Redis so the monthly
budget gate in ``FallbackRouter`` can trigger Ollama fallback
before overspending.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=10.0)

# Approximate pricing (per 1M tokens) – Gemini 2.5 Flash
_PRICE_INPUT_PER_M = 0.15
_PRICE_OUTPUT_PER_M = 0.60


class GeminiClient:
    """Async client for the Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._model = model or settings.GEMINI_MODEL
        self._max_tokens = settings.GEMINI_MAX_TOKENS
        self._temperature = settings.GEMINI_TEMPERATURE

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        """Check if the API key is configured."""
        return bool(self._api_key and self._api_key != "YOUR_GEMINI_API_KEY_HERE")

    # ═══════════════════════════════════════════
    # Generate (non-streaming)
    # ═══════════════════════════════════════════

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request and return structured result.

        Returns:
            {
                "content": str,
                "tool_calls": list[dict] | None,
                "token_count": int,
                "model": str,
                "finish_reason": str,
                "cost_usd": float,
            }
        """
        url = f"{_BASE_URL}/models/{self._model}:generateContent"
        params = {"key": self._api_key}

        body = self._build_request_body(
            messages, tools, temperature, max_tokens
        )

        t0 = time.perf_counter()

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, params=params, json=body)
            resp.raise_for_status()
            data = resp.json()

        elapsed = (time.perf_counter() - t0) * 1000
        result = self._parse_response(data)
        result["elapsed_ms"] = elapsed

        logger.info(
            "gemini_generate",
            model=self._model,
            tokens=result["token_count"],
            elapsed_ms=elapsed,
            has_tool_calls=bool(result.get("tool_calls")),
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
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens as an async generator."""
        url = f"{_BASE_URL}/models/{self._model}:streamGenerateContent"
        params = {"key": self._api_key, "alt": "sse"}

        body = self._build_request_body(
            messages, tools, temperature, max_tokens
        )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, params=params, json=body) as resp:
                resp.raise_for_status()

                buffer = ""
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        candidates = chunk.get("candidates", [])
                        if candidates:
                            parts = (
                                candidates[0]
                                .get("content", {})
                                .get("parts", [])
                            )
                            for part in parts:
                                text = part.get("text", "")
                                if text:
                                    yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    # ═══════════════════════════════════════════
    # Request/Response builders
    # ═══════════════════════════════════════════

    def _build_request_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Build the Gemini API request body."""
        # Convert our message format to Gemini format
        contents = []
        system_instruction = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
                continue

            gemini_role = "model" if role == "assistant" else "user"

            # Handle tool results
            if role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.get("name", "tool"),
                            "response": {
                                "content": content,
                            },
                        },
                    }],
                })
                continue

            parts = [{"text": content}]

            # Handle tool calls in assistant messages
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.get("name", ""),
                            "args": tc.get("arguments", {}),
                        },
                    })

            contents.append({"role": gemini_role, "parts": parts})

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature or self._temperature,
                "maxOutputTokens": max_tokens or self._max_tokens,
                "topP": 0.95,
                "topK": 40,
            },
        }

        if system_instruction:
            body["systemInstruction"] = system_instruction

        if tools:
            body["tools"] = [{"functionDeclarations": tools}]

        return body

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse the Gemini API response into a normalized dict."""
        result: dict[str, Any] = {
            "content": "",
            "tool_calls": None,
            "token_count": 0,
            "model": self._model,
            "finish_reason": "",
            "cost_usd": 0.0,
        }

        # Usage metadata
        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        result["token_count"] = input_tokens + output_tokens
        result["cost_usd"] = (
            (input_tokens / 1_000_000 * _PRICE_INPUT_PER_M)
            + (output_tokens / 1_000_000 * _PRICE_OUTPUT_PER_M)
        )

        # Candidates
        candidates = data.get("candidates", [])
        if not candidates:
            return result

        candidate = candidates[0]
        result["finish_reason"] = candidate.get("finishReason", "")

        parts = candidate.get("content", {}).get("parts", [])

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "name": fc.get("name", ""),
                    "arguments": fc.get("args", {}),
                })

        result["content"] = "".join(text_parts)
        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    # ═══════════════════════════════════════════
    # Cost tracking
    # ═══════════════════════════════════════════

    async def get_monthly_cost(self) -> float:
        """Read the cumulative monthly cost from Redis."""
        try:
            from app.core.redis import get_redis_client

            client = get_redis_client()
            raw = await client.get("molchat:gemini:monthly_cost")
            await client.aclose()
            return float(raw) if raw else 0.0
        except Exception:
            return 0.0

    async def record_cost(self, cost_usd: float) -> float:
        """Atomically increment the monthly cost counter. Returns new total."""
        try:
            from app.core.redis import get_redis_client

            client = get_redis_client()
            new_total = await client.incrbyfloat(
                "molchat:gemini:monthly_cost", cost_usd
            )
            # Set TTL to end of month (~30 days)
            await client.expire("molchat:gemini:monthly_cost", 2_592_000)
            await client.aclose()
            return float(new_total)
        except Exception:
            return 0.0

    async def health_check(self) -> dict[str, Any]:
        """Check Gemini API connectivity and return status."""
        if not self.is_available():
            return {"status": "unavailable", "reason": "api_key_not_configured"}

        try:
            url = f"{_BASE_URL}/models/{self._model}"
            params = {"key": self._api_key}
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return {"status": "healthy", "model": self._model}
                return {
                    "status": "degraded",
                    "http_status": resp.status_code,
                }
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}