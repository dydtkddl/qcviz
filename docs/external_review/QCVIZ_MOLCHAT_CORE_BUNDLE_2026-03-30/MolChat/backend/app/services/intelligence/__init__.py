"""
Intelligence Layer – LLM-powered conversational agent for molecular chemistry.

Architecture:
  ┌─────────────────────────────────────────────────────┐
  │                   MolChatAgent                       │
  │  (orchestrates conversation, tool calls, streaming)  │
  └──────┬──────────┬───────────────┬───────────────────┘
         │          │               │
   ┌─────▼────┐ ┌──▼────────┐ ┌───▼──────────────┐
   │ Fallback  │ │  Prompt   │ │  Hallucination   │
   │  Router   │ │  Builder  │ │     Guard        │
   └──┬───┬───┘ └───────────┘ └──────────────────┘
      │   │
 ┌────▼┐ ┌▼─────┐
 │Gemini│ │Ollama│
 │Client│ │Client│
 └─────┘ └──────┘

Tool bindings expose Molecule Engine capabilities as
structured function calls the LLM can invoke.
"""

from app.services.intelligence.agent import MolChatAgent
from app.services.intelligence.fallback_router import FallbackRouter
from app.services.intelligence.hallucination_guard import HallucinationGuard
from app.services.intelligence.prompt_builder import PromptBuilder

__all__ = [
    "MolChatAgent",
    "FallbackRouter",
    "HallucinationGuard",
    "PromptBuilder",
]