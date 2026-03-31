"""Gemini planner integration for natural language -> QCViz plan."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from qcviz_mcp.llm.normalizer import normalize_user_text
from qcviz_mcp.llm.schemas import PlanResponse

logger = logging.getLogger(__name__)


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "plan_quantum_request",
        "description": "Plan a user request into a structured QCViz compute or chat intent.",
        "parameters": PlanResponse.model_json_schema(),
    }
]


_SYSTEM_PROMPT = """You are QCViz Planner, an orchestration layer for a quantum chemistry web app.

Return exactly one JSON object that matches the schema.

Important rules:
- You are NOT the chemistry engine. Do not invent calculation results.
- Your job is intent parsing and slot extraction only.
- Use intent="chat" for educational questions or general explanation requests.
- For explicit computation requests, use one of:
  analyze, single_point, geometry_analysis, partial_charges, orbital_preview, esp_map, geometry_optimization, resolve_structure
- Prefer English structure_query names when possible.
- Preserve ion pairs in `structures` if the user clearly specifies multiple charged species.
- If a computation intent is clear but a required slot is missing, include it in `missing_slots` and set `needs_clarification=true`.
- Never fabricate a structure if the request is too vague.
- Reconstruct noisy molecule mentions before you commit to `structure_query`.
  Examples:
  - "베 ㄴ젠" -> "benzene"
  - "니트로 벤젠" -> "nitrobenzene"
  - "니트로 benzene" -> "nitrobenzene"
- Do not return half-normalized names such as "니트로 benzene".
- `confidence` must be between 0 and 1.
""".strip()


_INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "chat": "analyze",
    "analyze": "analyze",
    "single_point": "single_point",
    "geometry_analysis": "geometry_analysis",
    "partial_charges": "partial_charges",
    "orbital_preview": "orbital_preview",
    "esp_map": "esp_map",
    "geometry_optimization": "geometry_optimization",
    "resolve_structure": "resolve_structure",
}


@dataclass
class GeminiResult:
    """Parsed result from Gemini planning."""

    intent: str = "analyze"
    structure: Optional[str] = None
    structures: Optional[List[Dict[str, Any]]] = None
    method: Optional[str] = None
    basis_set: Optional[str] = None
    job_type: str = "analyze"
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    missing_slots: Optional[List[str]] = None
    needs_clarification: bool = False
    notes: Optional[List[str]] = None
    normalized_text: str = ""
    provider: str = "gemini"
    raw_response: str = ""
    model_used: str = ""
    fallback_reason: Optional[str] = None
    query: Optional[str] = None
    properties: Optional[List[str]] = None

    def to_plan_dict(self) -> Dict[str, Any]:
        return {
            "normalized_text": self.normalized_text,
            "intent": self.intent,
            "job_type": self.job_type,
            "structure_query": self.structure,
            "structures": self.structures,
            "method": self.method,
            "basis": self.basis_set,
            "charge": self.charge,
            "multiplicity": self.multiplicity,
            "orbital": self.orbital,
            "esp_preset": self.esp_preset,
            "focus_tab": self.focus_tab,
            "confidence": self.confidence,
            "missing_slots": list(self.missing_slots or []),
            "needs_clarification": bool(self.needs_clarification),
            "provider": self.provider,
            "fallback_reason": self.fallback_reason,
            "notes": list(self.notes or []),
        }


class GeminiAgent:
    """Gemini-backed structured planner."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self.api_key: str = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model: str = model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout: float = timeout or float(os.getenv("GEMINI_TIMEOUT", "10"))
        self.temperature: float = (
            temperature if temperature is not None
            else float(os.getenv("GEMINI_TEMPERATURE", "0.0"))
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def parse(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        return await asyncio.to_thread(self.parse_sync, message, history)

    def parse_sync(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        if not self.is_available():
            logger.warning("Gemini API key not set; planner will fall back")
            return None

        normalized = normalize_user_text(message)
        try:
            return self._call_gemini_sync(message, normalized, history)
        except Exception as exc:
            logger.warning("Gemini planner failed: %s", exc)
            return None

    def _call_gemini_sync(
        self,
        message: str,
        normalized: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[GeminiResult]:
        from google import genai  # type: ignore

        client = genai.Client(api_key=self.api_key)
        prompt = self._compose_prompt(message, normalized, history)
        response = client.models.generate_content(
            model=self.model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config={
                "response_mime_type": "application/json",
                "temperature": self.temperature,
            },
        )
        raw_text = self._response_to_text(response)
        return self._extract_result(raw_text, normalized)

    def _compose_prompt(
        self,
        message: str,
        normalized: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        history_json = json.dumps(history or [], ensure_ascii=False)
        normalized_json = json.dumps(normalized, ensure_ascii=False)
        schema_json = json.dumps(PlanResponse.model_json_schema(), ensure_ascii=False)
        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Schema:\n{schema_json}\n\n"
            f"Normalization hints:\n{normalized_json}\n\n"
            f"Conversation history:\n{history_json}\n\n"
            f"User message:\n{message}\n"
        )

    def _response_to_text(self, response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            fragments: List[str] = []
            for part in parts:
                maybe_text = getattr(part, "text", None)
                if maybe_text:
                    fragments.append(str(maybe_text))
            if fragments:
                return "\n".join(fragments).strip()
        return str(response or "")

    def _extract_result(self, raw_text: str, normalized: Dict[str, Any]) -> Optional[GeminiResult]:
        data = self._extract_json_dict(raw_text)
        if not data:
            return None
        plan = self._postprocess_plan_dict(data, normalized)
        parsed = PlanResponse.model_validate(plan)
        return GeminiResult(
            intent=parsed.intent,
            structure=parsed.structure_query,
            structures=parsed.structures,
            method=parsed.method,
            basis_set=parsed.basis,
            job_type=parsed.job_type,
            charge=parsed.charge,
            multiplicity=parsed.multiplicity,
            orbital=parsed.orbital,
            esp_preset=parsed.esp_preset,
            focus_tab=parsed.focus_tab,
            confidence=parsed.confidence,
            missing_slots=parsed.missing_slots,
            needs_clarification=parsed.needs_clarification,
            notes=list(parsed.notes or parsed.reasoning_notes),
            normalized_text=parsed.normalized_text,
            provider=parsed.provider,
            raw_response=raw_text[:1000],
            model_used=self.model,
            fallback_reason=parsed.fallback_reason,
        )

    def _postprocess_plan_dict(self, data: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data or {})
        if not out.get("normalized_text"):
            out["normalized_text"] = normalized.get("normalized_text", "")

        intent = str(out.get("intent") or "analyze").strip() or "analyze"
        out["intent"] = intent
        out["job_type"] = str(out.get("job_type") or _INTENT_TO_JOB_TYPE.get(intent, "analyze")).strip()
        out["provider"] = "gemini"

        structure_query = out.get("structure_query") or out.get("structure")
        if structure_query is None:
            structure_query = normalized.get("maybe_structure_hint")
        out["structure_query"] = structure_query

        if out.get("basis_set") and not out.get("basis"):
            out["basis"] = out.get("basis_set")

        if intent != "chat" and not out.get("structures") and not out.get("structure_query"):
            missing_slots = list(out.get("missing_slots") or [])
            if "structure_query" not in missing_slots:
                missing_slots.append("structure_query")
            out["missing_slots"] = missing_slots
            out["needs_clarification"] = True

        if intent == "orbital_preview" and not out.get("orbital"):
            missing_slots = list(out.get("missing_slots") or [])
            if "orbital" not in missing_slots:
                missing_slots.append("orbital")
            out["missing_slots"] = missing_slots
            out["needs_clarification"] = True

        if not out.get("focus_tab"):
            if intent == "orbital_preview":
                out["focus_tab"] = "orbital"
            elif intent == "esp_map":
                out["focus_tab"] = "esp"
            elif intent == "partial_charges":
                out["focus_tab"] = "charges"
            elif intent in {"geometry_analysis", "geometry_optimization"}:
                out["focus_tab"] = "geometry"
            else:
                out["focus_tab"] = "summary"

        return out

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
