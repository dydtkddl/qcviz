"""
FallbackRouter – intelligent LLM routing with automatic failover.

Routing logic:
  1. If Gemini API key configured AND monthly cost < budget → Gemini.
  2. If Gemini fails (timeout, 5xx, quota) → Ollama primary.
  3. If Ollama primary fails → Ollama fallback model.
  4. If all fail → raise LLMError.

Also handles:
  • Cost tracking (increments Redis counter after each Gemini call).
  • Circuit breaker pattern (disable Gemini for N seconds after M failures).
  • Unified message format conversion.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import structlog

from app.core.config import settings
from app.middleware.error_handler import LLMError
from app.services.intelligence.gemini_client import GeminiClient
from app.services.intelligence.ollama_client import OllamaClient

logger = structlog.get_logger(__name__)

# Circuit breaker settings
_CB_FAILURE_THRESHOLD = 3        # failures before opening circuit
_CB_RECOVERY_TIMEOUT = 120.0     # seconds before retrying Gemini


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""

    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    token_count: int = 0
    model: str = ""
    finish_reason: str = ""
    cost_usd: float = 0.0
    fallback_used: bool = False
    elapsed_ms: float = 0.0


@dataclass
class _CircuitState:
    """Per-provider circuit breaker state."""

    failure_count: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= _CB_FAILURE_THRESHOLD:
            self.is_open = True
            logger.warning(
                "circuit_breaker_opened",
                failures=self.failure_count,
            )

    def record_success(self) -> None:
        self.failure_count = 0
        self.is_open = False

    def should_allow(self) -> bool:
        if not self.is_open:
            return True
        elapsed = time.time() - self.last_failure_time
        if elapsed >= _CB_RECOVERY_TIMEOUT:
            logger.info("circuit_breaker_half_open")
            return True  # Half-open: allow one attempt
        return False


class FallbackRouter:
    """Route LLM requests with automatic failover and cost control."""

    def __init__(
        self,
        gemini: GeminiClient | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self._gemini = gemini or GeminiClient()
        self._ollama = ollama or OllamaClient()
        self._gemini_circuit = _CircuitState()

    # ═══════════════════════════════════════════
    # Generate (non-streaming)
    # ═══════════════════════════════════════════

    async def generate(
        self,
        messages: list[Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Route to the best available LLM and return a normalized response."""
        msg_dicts = self._normalize_messages(messages)

        # ── Try Gemini ──
        if await self._should_use_gemini():
            try:
                result = await self._gemini.generate(
                    msg_dicts,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Record cost
                if result.get("cost_usd", 0) > 0:
                    await self._gemini.record_cost(result["cost_usd"])

                self._gemini_circuit.record_success()

                return LLMResponse(
                    content=result.get("content", ""),
                    tool_calls=result.get("tool_calls"),
                    token_count=result.get("token_count", 0),
                    model=result.get("model", ""),
                    finish_reason=result.get("finish_reason", ""),
                    cost_usd=result.get("cost_usd", 0.0),
                    fallback_used=False,
                    elapsed_ms=result.get("elapsed_ms", 0.0),
                )

            except Exception as exc:
                logger.warning(
                    "gemini_failed_falling_back",
                    error=str(exc),
                )
                self._gemini_circuit.record_failure()

        # ── Fallback to Ollama ──
        try:
            result = await self._ollama.generate(
                msg_dicts,
                tools=tools,
                temperature=temperature or 0.3,
                max_tokens=max_tokens or 4096,
            )

            return LLMResponse(
                content=result.get("content", ""),
                tool_calls=result.get("tool_calls"),
                token_count=result.get("token_count", 0),
                model=result.get("model", ""),
                finish_reason=result.get("finish_reason", ""),
                cost_usd=0.0,
                fallback_used=True,
                elapsed_ms=result.get("elapsed_ms", 0.0),
            )

        except Exception as exc:
            logger.error("all_llm_providers_failed", error=str(exc))
            raise LLMError(
                model="all",
                reason=f"All LLM providers failed: {exc}",
            )

    # ═══════════════════════════════════════════
    # Streaming
    # ═══════════════════════════════════════════

    async def stream(
        self,
        messages: list[Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the best available LLM."""
        msg_dicts = self._normalize_messages(messages)

        # ── Try Gemini streaming ──
        if await self._should_use_gemini():
            try:
                async for token in self._gemini.stream(
                    msg_dicts,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield token
                self._gemini_circuit.record_success()
                return
            except Exception as exc:
                logger.warning("gemini_stream_failed", error=str(exc))
                self._gemini_circuit.record_failure()

        # ── Ollama streaming fallback ──
        try:
            async for token in self._ollama.stream(
                msg_dicts,
                tools=tools,
                temperature=temperature or 0.3,
                max_tokens=max_tokens or 4096,
            ):
                yield token
        except Exception as exc:
            logger.error("all_stream_providers_failed", error=str(exc))
            yield "[오류: LLM 서비스를 사용할 수 없습니다.]"

    # ═══════════════════════════════════════════
    # Routing logic
    # ═══════════════════════════════════════════

    async def _should_use_gemini(self) -> bool:
        """Determine whether to route to Gemini."""
        # API key check
        if not self._gemini.is_available():
            return False

        # Circuit breaker
        if not self._gemini_circuit.should_allow():
            logger.debug("gemini_circuit_open_skipping")
            return False

        # Cost budget
        try:
            monthly_cost = await self._gemini.get_monthly_cost()
            if monthly_cost >= settings.GEMINI_MONTHLY_COST_LIMIT:
                logger.info(
                    "gemini_budget_exceeded",
                    cost=monthly_cost,
                    limit=settings.GEMINI_MONTHLY_COST_LIMIT,
                )
                return False
        except Exception:
            pass  # Fail-open: allow Gemini if Redis is down

        return True

    # ═══════════════════════════════════════════
    # Message normalization
    # ═══════════════════════════════════════════

    @staticmethod
    def _normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
        """Convert ConversationMessage objects or dicts to plain dicts."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, dict):
                result.append(msg)
            else:
                d: dict[str, Any] = {
                    "role": getattr(msg, "role", "user"),
                    "content": getattr(msg, "content", ""),
                }
                if getattr(msg, "tool_call_id", None):
                    d["tool_call_id"] = msg.tool_call_id
                if getattr(msg, "tool_calls", None):
                    d["tool_calls"] = msg.tool_calls
                if getattr(msg, "name", None):
                    d["name"] = msg.name
                result.append(d)
        return result

    # ═══════════════════════════════════════════
    # Health
    # ═══════════════════════════════════════════

    async def health_check(self) -> dict[str, Any]:
        """Return combined health status for all LLM providers."""
        gemini_health, ollama_health = await asyncio.gather(
            self._gemini.health_check(),
            self._ollama.health_check(),
            return_exceptions=True,
        )

        if isinstance(gemini_health, Exception):
            gemini_health = {"status": "error", "error": str(gemini_health)}
        if isinstance(ollama_health, Exception):
            ollama_health = {"status": "error", "error": str(ollama_health)}

        any_healthy = (
            gemini_health.get("status") == "healthy"
            or ollama_health.get("status") == "healthy"
        )

        return {
            "status": "healthy" if any_healthy else "degraded",
            "gemini": gemini_health,
            "ollama": ollama_health,
            "circuit_breaker": {
                "gemini_open": self._gemini_circuit.is_open,
                "failure_count": self._gemini_circuit.failure_count,
            },
        }