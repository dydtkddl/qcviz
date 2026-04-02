"""
Tool bindings – expose Molecule Engine capabilities as structured
function calls that the LLM can invoke.

Architecture:
  • ``ToolRegistry`` holds all available tools.
  • Each tool is an async callable with typed parameters.
  • Tool definitions follow the OpenAI/Gemini function-calling schema.
  • The ``MolChatAgent`` queries the registry for definitions and dispatches calls.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger(__name__)


# Type alias for an async tool function
ToolFunction = Callable[..., Awaitable[dict[str, Any] | str]]


class ToolRegistry:
    """Registry of callable tools for the LLM agent."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}
        self._definitions: list[dict[str, Any]] = []

    def register(
        self,
        name: str,
        fn: ToolFunction,
        definition: dict[str, Any],
    ) -> None:
        """Register a tool with its function and schema definition."""
        self._tools[name] = fn
        self._definitions.append(definition)
        logger.debug("tool_registered", name=name)

    def get_tool(self, name: str) -> ToolFunction | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return all tool definitions for the LLM."""
        return list(self._definitions)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())


# ── Singleton registry ──
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry.

    Lazily imports and registers all tools on first access.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_all_tools(_registry)
    return _registry


def _register_all_tools(registry: ToolRegistry) -> None:
    """Import and register all tool modules."""
    from app.services.intelligence.tools.molecule_tools import register_molecule_tools
    from app.services.intelligence.tools.calculation_tools import register_calculation_tools

    register_molecule_tools(registry)
    register_calculation_tools(registry)

    logger.info(
        "tools_registered",
        count=len(registry.list_tools()),
        tools=registry.list_tools(),
    )


__all__ = [
    "ToolRegistry",
    "ToolFunction",
    "get_tool_registry",
]