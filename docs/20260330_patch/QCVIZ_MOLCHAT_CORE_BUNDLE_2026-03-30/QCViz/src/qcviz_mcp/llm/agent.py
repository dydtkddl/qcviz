from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from qcviz_mcp.llm.normalizer import (
    analyze_query_routing,
    analyze_follow_up_request,
    analyze_structure_input,
    build_structure_hypotheses,
    detect_task_hint,
    extract_structure_candidate,
    normalize_user_text,
)
from qcviz_mcp.llm.schemas import PlanResponse, confidence_to_band

# FIX(M1): GeminiAgent import for function-calling integration
try:
    from qcviz_mcp.services.gemini_agent import GeminiAgent, GeminiResult
except ImportError:
    GeminiAgent = None  # type: ignore
    GeminiResult = None  # type: ignore

logger = logging.getLogger(__name__)


PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "chat",
                "analyze",
                "single_point",
                "geometry_analysis",
                "partial_charges",
                "orbital_preview",
                "esp_map",
                "geometry_optimization",
                "resolve_structure",
            ],
        },
        "chat_response": {"type": "string", "description": "Natural language response for chat intent"},
        "structure_query": {"type": "string"},
        "structure_query_candidates": {"type": "array", "items": {"type": "string"}},
        "query_kind": {"type": "string"},
        "semantic_grounding_needed": {"type": "boolean"},
        "unknown_acronyms": {"type": "array", "items": {"type": "string"}},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb",
                "bwr",
                "viridis",
                "inferno",
                "spectral",
                "nature",
                "acs",
                "rsc",
                "greyscale",
                "high_contrast",
                "grey",
                "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "clarification_kind": {"type": "string"},
        "missing_slots": {
            "type": "array",
            "items": {"type": "string"},
        },
        "needs_clarification": {"type": "boolean"},
        "mentioned_molecules": {
            "type": "array",
            "items": {"type": "object"},
        },
        "target_scope": {
            "type": "string",
            "enum": ["single", "all_mentioned", "subset", "custom"],
        },
        "selection_mode": {
            "type": "string",
            "enum": ["implicit_all", "explicit_all", "subset_picker", "custom"],
        },
        "selection_hint": {"type": "string"},
        "selected_molecules": {
            "type": "array",
            "items": {"type": "string"},
        },
        "analysis_bundle": {
            "type": "array",
            "items": {"type": "string"},
        },
        "batch_request": {"type": "boolean"},
        "batch_size": {"type": "integer"},
    },
    "required": ["intent"],
    "additionalProperties": True,
}


INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "chat": {"tool_name": "chat_response", "focus_tab": "summary"},
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}


SYSTEM_PROMPT = """
You are QCViz Assistant, a conversational AI for a quantum chemistry web app (PySCF-based).
You serve TWO roles:

## ROLE 1: Chatbot (intent="chat")
For questions, explanations, discussions, or anything NOT requesting a computation:
- Answer chemistry questions ("HOMO란 뭐야?", "DFT의 원리", "B3LYP vs HF 차이")
- Explain results and concepts
- Suggest what calculations to run
- General conversation and guidance
- Set intent="chat" and put your answer in chat_response.
- chat_response should be detailed, helpful, in the user's language (Korean/English).
- Use markdown formatting: **bold**, bullet points, etc.
- If the user asks a vague question that COULD be a computation but is unclear,
  respond conversationally and suggest a specific computation they could try.

## ROLE 2: Computation Planner (intent= any computation type)
For explicit computation requests:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

## How to decide:
- "HOMO가 뭐야?" → chat (educational question)
- "물 HOMO 보여줘" → orbital_preview (specific computation)
- "5개 원자 분자 대표적인거" → chat (suggest methane, then offer computation)
- "methane HOMO LUMO" → orbital_preview (clear computation request)
- "이온쌍이란?" → chat (explanation)
- "EMIM TFSI 에너지" → single_point (computation)

Extraction rules:
- structure_query should be the molecule name (English preferred: "water", "methane", "ethanol")
- focus_tab: orbital / esp / charges / geometry / summary
- confidence: 0.0 to 1.0

CRITICAL — Structure resolution (for computation intents only):
- If the user gives a vague description, suggest a specific molecule in chat_response
  and set intent="chat" so they can confirm.
- Examples: "5개 원자 분자" → chat intent, suggest CH4 in response
- NEVER leave structure_query empty for computation intents.
- Reconstruct noisy molecule mentions before you commit to structure_query.
  Examples:
  - "베 ㄴ젠" -> "benzene"
  - "니트로 벤젠" -> "nitrobenzene"
  - "니트로 benzene" -> "nitrobenzene"
- Do NOT return half-normalized names such as "니트로 benzene".
- If the structure is still ambiguous after reconstruction, set needs_clarification=true.
- For Korean names: TFSI- = bis(trifluoromethanesulfonyl)imide,
  EMIM+ = 1-ethyl-3-methylimidazolium, BF4- = tetrafluoroborate.

Always return the planning JSON. For chat intent, chat_response is required.
""".strip()


@dataclass
class AgentPlan:
    intent: str = "analyze"
    normalized_text: str = ""
    job_type: str = "analyze"
    query_kind: Optional[str] = None
    semantic_grounding_needed: bool = False
    unknown_acronyms: List[str] = field(default_factory=list)
    structure_query: Optional[str] = None
    structure_query_candidates: List[str] = field(default_factory=list)
    formula_mentions: List[str] = field(default_factory=list)
    alias_mentions: List[str] = field(default_factory=list)
    canonical_candidates: List[str] = field(default_factory=list)
    raw_input: Optional[str] = None
    mixed_input: bool = False
    composition_kind: Optional[str] = None
    charge_hint: Optional[int] = None
    structures: Optional[List[Dict[str, Any]]] = None  # FIX(M1): ion pair support
    mentioned_molecules: List[Dict[str, Any]] = field(default_factory=list)
    target_scope: Optional[str] = None
    selection_mode: Optional[str] = None
    selection_hint: Optional[str] = None
    selected_molecules: List[str] = field(default_factory=list)
    analysis_bundle: List[str] = field(default_factory=list)
    batch_request: bool = False
    batch_size: int = 0
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    confidence_band: str = "low"
    tool_name: str = "run_analyze"
    follow_up_mode: Optional[str] = None
    clarification_kind: Optional[str] = None
    missing_slots: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    notes: List[str] = field(default_factory=list)
    reasoning_notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    fallback_reason: Optional[str] = None
    chat_response: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data

    @property
    def advisor_focus_tab(self) -> str:
        return self.focus_tab


class QCVizAgent:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        
        # FIX(M1): Initialize GeminiAgent for function-calling
        self._gemini_agent: Optional[Any] = None
        if GeminiAgent is not None and self.gemini_api_key:
            try:
                self._gemini_agent = GeminiAgent(
                    api_key=self.gemini_api_key,
                    model=self.gemini_model,
                )
                logger.info("GeminiAgent initialized for function calling")
            except Exception as e:
                logger.warning("GeminiAgent init failed: %s", e)

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0, "normalized_text": ""}, provider="heuristic")

        normalized = normalize_user_text(text)
        normalized_text = normalized.get("normalized_text") or text

        chosen = self._choose_provider()
        if chosen == "openai":
            try:
                return self._plan_with_openai(normalized_text, context=context or {})
            except Exception:
                pass

        if chosen == "gemini":
            try:
                return self._plan_with_gemini_structured(text, normalized, context=context or {})
            except Exception:
                try:
                    return self._plan_with_gemini(normalized_text, context=context or {})
                except Exception:
                    pass

        if chosen == "auto":
            if self.gemini_api_key:
                try:
                    return self._plan_with_gemini_structured(text, normalized, context=context or {})
                except Exception:
                    pass
            if self.openai_api_key:
                try:
                    return self._plan_with_openai(normalized_text, context=context or {})
                except Exception:
                    pass

        return self._heuristic_plan(text, context=context or {}, normalized=normalized)

    def _choose_provider(self) -> str:
        if self.provider in {"openai", "gemini", "none"}:
            return self.provider
        return "auto"

    def _plan_with_openai(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        from openai import OpenAI

        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=self.openai_api_key)
        user_prompt = self._compose_user_prompt(message, context=context)

        resp = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "plan_quantum_request",
                        "description": "Plan a user request into a QCViz compute intent.",
                        "parameters": PLAN_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "plan_quantum_request"}},
        )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        data: Dict[str, Any]

        if tool_calls:
            args = tool_calls[0].function.arguments or "{}"
            data = json.loads(args)
        else:
            content = self._message_content_to_text(getattr(msg, "content", ""))
            data = self._extract_json_dict(content)

        return self._coerce_plan(data, provider="openai")

    def _plan_with_gemini_structured(
        self,
        message: str,
        normalized: Dict[str, Any],
        context: Dict[str, Any],
    ) -> AgentPlan:
        if self._gemini_agent is None:
            raise RuntimeError("GeminiAgent is not initialized")

        result = self._gemini_agent.parse_sync(message, history=context.get("history"))
        if result is None:
            raise RuntimeError("Gemini structured planner returned no result")
        data = result.to_plan_dict() if hasattr(result, "to_plan_dict") else dict(result)
        data.setdefault("normalized_text", normalized.get("normalized_text"))
        return self._coerce_plan(data, provider="gemini")

    def _plan_with_gemini(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        user_prompt = self._compose_user_prompt(message, context=context)

        # new google-genai
        try:
            from google import genai  # type: ignore

            if not self.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "user", "parts": [{"text": user_prompt}]},
                ],
                config={
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(resp, "text", None) or self._message_content_to_text(resp)
            data = self._extract_json_dict(text)
            return self._coerce_plan(data, provider="gemini")
        except ImportError:
            pass

        # older google-generativeai
        import google.generativeai as genai  # type: ignore

        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel(self.gemini_model)
        resp = model.generate_content(
            f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            generation_config={"response_mime_type": "application/json", "temperature": 0},
        )
        text = getattr(resp, "text", None) or self._message_content_to_text(resp)
        data = self._extract_json_dict(text)
        return self._coerce_plan(data, provider="gemini")

    def _compose_user_prompt(self, message: str, context: Dict[str, Any]) -> str:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return f"Context:\n{context_json}\n\nUser message:\n{message}"

    def _heuristic_plan(
        self,
        message: str,
        context: Dict[str, Any],
        normalized: Optional[Dict[str, Any]] = None,
    ) -> AgentPlan:
        text = message.strip()
        normalized = normalized or normalize_user_text(text)
        normalized_text = normalized.get("normalized_text") or text
        lower = normalized_text.lower()
        query_kind = str(normalized.get("query_kind") or "compute_ready").strip() or "compute_ready"
        semantic_grounding_needed = bool(normalized.get("semantic_grounding_needed"))
        unknown_acronyms = list(normalized.get("unknown_acronyms") or [])

        if bool(normalized.get("chat_only")):
            return self._coerce_plan(
                {
                    "normalized_text": normalized_text,
                    "intent": "chat",
                    "job_type": "chat",
                    "query_kind": query_kind,
                    "semantic_grounding_needed": semantic_grounding_needed,
                    "unknown_acronyms": unknown_acronyms,
                    "confidence": 0.82,
                    "chat_response": self._heuristic_chat_response(text, normalized),
                    "notes": ["Heuristic chat-only routing."],
                    "reasoning_notes": list(normalized.get("routing_reasoning_notes") or []),
                    "needs_clarification": False,
                    "missing_slots": [],
                    "structure_query": None,
                    "structure_query_candidates": [],
                    "canonical_candidates": [],
                },
                provider="heuristic",
            )

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = []

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map", "전위", "정전기"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface", "오비탈"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution", "전하"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize", "최적화"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle", "구조", "결합"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy", "에너지"]):
            intent = "single_point"
            confidence = 0.82

        structure_query = (
            normalized.get("maybe_structure_hint")
            or self._extract_structure_query(normalized_text)
            or extract_structure_candidate(text)
        )
        if structure_query and self._is_task_like_structure_query(str(structure_query)):
            structure_query = None
        if query_kind == "grounding_required" and unknown_acronyms:
            structure_query = None
        mentioned_molecules = list(normalized.get("mentioned_molecules") or [])
        target_scope = normalized.get("target_scope")
        selection_mode = normalized.get("selection_mode")
        selection_hint = normalized.get("selection_hint")
        selected_molecules = list(normalized.get("selected_molecules") or [])
        analysis_bundle = list(normalized.get("analysis_bundle") or [])
        batch_request = bool(normalized.get("batch_request"))
        batch_size = int(normalized.get("batch_size") or len(selected_molecules) or len(mentioned_molecules) or 0)
        method = self._extract_method(text)
        basis = self._extract_basis(text)
        charge = self._extract_charge(text)
        multiplicity = self._extract_multiplicity(text)
        orbital = self._extract_orbital(text)
        esp_preset = self._extract_esp_preset(text)
        follow_up = analyze_follow_up_request(text)
        missing_slots: List[str] = []
        needs_clarification = False
        clarification_kind: Optional[str] = None
        structures = list(normalized.get("structures") or []) or None

        analysis_signal_bundle = {str(item).upper() for item in analysis_bundle if str(item).strip()}
        analysis_only_follow_up = bool(
            not structure_query
            and not structures
            and not batch_request
            and analysis_signal_bundle.intersection({"HOMO", "LUMO", "ESP"})
            and (
                len(analysis_signal_bundle.intersection({"HOMO", "LUMO", "ESP"})) >= 2
                or bool(re.search(r"궁금|알려줘|뭐야|추가|다시|also|too|again|more|도\b|ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자", text, re.IGNORECASE))
            )
        )
        if analysis_only_follow_up and not follow_up.get("follow_up_mode"):
            follow_up = dict(follow_up)
            follow_up["follow_up_mode"] = "add_analysis"
            follow_up["requires_context"] = True

        composition_kind = normalized.get("composition_kind")
        charge_hint = normalized.get("charge_hint")
        if charge is None and charge_hint is not None:
            charge = charge_hint

        if not orbital and follow_up.get("orbital"):
            orbital = str(follow_up.get("orbital"))
        if follow_up.get("job_type"):
            intent = str(follow_up.get("job_type"))

        if analysis_bundle and intent not in {"chat", "orbital_preview", "esp_map"}:
            if set(analysis_bundle) == {"structure"}:
                intent = "resolve_structure"
            else:
                intent = "analyze"

        if batch_request:
            structure_query = None

        if intent != "chat" and not structure_query and not structures and not batch_request:
            missing_slots.append("structure_query")
            needs_clarification = True
            if query_kind == "grounding_required":
                clarification_kind = "semantic_grounding"
            else:
                clarification_kind = "continuation_targeting" if follow_up.get("requires_context") else "discovery"
        if intent == "orbital_preview" and not orbital:
            missing_slots.append("orbital")
            needs_clarification = True
            clarification_kind = clarification_kind or "parameter_completion"

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        data = {
            "normalized_text": normalized_text,
            "intent": intent,
            "job_type": intent,
            "query_kind": query_kind,
            "semantic_grounding_needed": semantic_grounding_needed,
            "unknown_acronyms": unknown_acronyms,
            "structure_query": structure_query,
            "structure_query_candidates": list(normalized.get("canonical_candidates") or normalized.get("candidate_queries") or []),
            "formula_mentions": list(normalized.get("formula_mentions") or []),
            "alias_mentions": list(normalized.get("alias_mentions") or []),
            "canonical_candidates": list(normalized.get("canonical_candidates") or []),
            "raw_input": normalized.get("raw_input"),
            "mixed_input": bool(normalized.get("mixed_input")),
            "composition_kind": composition_kind,
            "charge_hint": charge_hint,
            "structures": structures,
            "mentioned_molecules": mentioned_molecules,
            "target_scope": target_scope,
            "selection_mode": selection_mode,
            "selection_hint": selection_hint,
            "selected_molecules": selected_molecules,
            "analysis_bundle": analysis_bundle,
            "batch_request": batch_request,
            "batch_size": batch_size,
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "orbital": orbital,
            "esp_preset": esp_preset,
            "follow_up_mode": follow_up.get("follow_up_mode"),
            "clarification_kind": clarification_kind,
            "confidence": confidence,
            "missing_slots": missing_slots,
            "needs_clarification": needs_clarification,
            "notes": notes,
        }
        data = self._apply_structure_hypotheses(data, source_text=text, normalized=normalized)
        return self._coerce_plan(data, provider="heuristic")

    def _apply_structure_hypotheses(
        self,
        data: Dict[str, Any],
        *,
        source_text: str,
        normalized: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        out = dict(data or {})
        normalized = normalized or normalize_user_text(source_text or "")
        base_text = (
            source_text
            or str(out.get("raw_input") or "")
            or str(out.get("structure_query") or "")
            or str(out.get("normalized_text") or "")
        )
        hypotheses = build_structure_hypotheses(
            base_text,
            translated_text=normalized.get("translated_text"),
            expanded_text=normalized.get("normalized_text"),
        )
        primary_candidate = self._none_if_blank(hypotheses.get("primary_candidate"))
        current_structure = self._none_if_blank(out.get("structure_query"))
        raw_input = self._none_if_blank(out.get("raw_input") or normalized.get("raw_input"))
        intent = str(out.get("intent") or out.get("job_type") or "analyze").strip()
        is_computation_intent = intent not in {"chat"}

        if primary_candidate and (
            is_computation_intent
            and (
            not current_structure
            or current_structure == raw_input
            or self._looks_like_half_normalized_structure(current_structure)
            )
        ):
            out["structure_query"] = primary_candidate

        merged_candidates: List[str] = []
        for key in ("structure_query_candidates", "canonical_candidates"):
            for item in list(out.get(key) or []):
                token = self._none_if_blank(item)
                if token and token.lower() not in {entry.lower() for entry in merged_candidates}:
                    merged_candidates.append(token)
        for item in list(hypotheses.get("candidate_queries") or []) + list(normalized.get("candidate_queries") or []):
            token = self._none_if_blank(item)
            if token and token.lower() not in {entry.lower() for entry in merged_candidates}:
                merged_candidates.append(token)
        if merged_candidates:
            out["structure_query_candidates"] = merged_candidates
            if not out.get("canonical_candidates"):
                out["canonical_candidates"] = list(merged_candidates)

        if str(out.get("query_kind") or "").strip() == "grounding_required":
            raw_variants = {
                str(item).strip().lower()
                for item in (
                    source_text,
                    out.get("raw_input"),
                    out.get("normalized_text"),
                )
                if str(item or "").strip()
            }
            structure_query = self._none_if_blank(out.get("structure_query"))
            if structure_query and structure_query.lower() in raw_variants:
                out["structure_query"] = None

        reasoning_notes = [str(item).strip() for item in list(out.get("reasoning_notes") or []) if str(item).strip()]
        for item in list(hypotheses.get("reasoning_notes") or []) + list(normalized.get("structure_reasoning_notes") or []):
            token = str(item).strip()
            if token and token not in reasoning_notes:
                reasoning_notes.append(token)
        if reasoning_notes:
            out["reasoning_notes"] = reasoning_notes

        if is_computation_intent and hypotheses.get("needs_clarification"):
            out["needs_clarification"] = True
            out["clarification_kind"] = out.get("clarification_kind") or "disambiguation"
            missing_slots = [str(item).strip() for item in list(out.get("missing_slots") or []) if str(item).strip()]
            if not out.get("structure_query") and "structure_query" not in missing_slots:
                missing_slots.append("structure_query")
            out["missing_slots"] = missing_slots
            out["confidence"] = min(float(out.get("confidence") or 0.0), float(hypotheses.get("confidence") or 0.6))
        elif is_computation_intent and primary_candidate:
            out["confidence"] = max(float(out.get("confidence") or 0.0), float(hypotheses.get("confidence") or 0.0))

        return out

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        source_text = str(data.get("raw_input") or data.get("normalized_text") or data.get("structure_query") or "")
        data = self._apply_structure_hypotheses(data, source_text=source_text)
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structure_input = data.get("raw_input") or data.get("structure_query")
        structure_analysis = analyze_structure_input(str(structure_input or ""))
        if structure_analysis.get("canonical_candidates"):
            data.setdefault("structure_query_candidates", list(structure_analysis.get("canonical_candidates") or []))
            data.setdefault("formula_mentions", list(structure_analysis.get("formula_mentions") or []))
            data.setdefault("alias_mentions", list(structure_analysis.get("alias_mentions") or []))
            data.setdefault("canonical_candidates", list(structure_analysis.get("canonical_candidates") or []))
            data.setdefault("raw_input", structure_analysis.get("raw_input"))
            data.setdefault("mixed_input", bool(structure_analysis.get("mixed_input")))
            if structure_analysis.get("multi_molecule"):
                data.setdefault("mentioned_molecules", list(structure_analysis.get("mentioned_molecules") or []))
                data.setdefault("target_scope", "all_mentioned")
                data.setdefault("selection_mode", "implicit_all")
                selected = list(data.get("selected_molecules") or []) or list(structure_analysis.get("canonical_candidates") or [])
                data.setdefault("selected_molecules", selected)
                data.setdefault("batch_request", len(selected) > 1)
                data.setdefault("batch_size", len(selected))
                data["structure_query"] = None
            elif structure_analysis.get("mixed_input") and structure_analysis.get("primary_candidate"):
                data["structure_query"] = structure_analysis["primary_candidate"]
        routing = analyze_query_routing(
            str(data.get("normalized_text") or data.get("raw_input") or data.get("structure_query") or ""),
            structure_analysis=structure_analysis,
        )
        data.setdefault("query_kind", routing.get("query_kind"))
        data.setdefault("semantic_grounding_needed", routing.get("semantic_grounding_needed"))
        data.setdefault("unknown_acronyms", list(routing.get("unknown_acronyms") or []))
        data.setdefault("mentioned_molecules", [])
        data.setdefault("selected_molecules", [])
        data.setdefault("analysis_bundle", [])
        follow_up = analyze_follow_up_request(str(data.get("normalized_text") or data.get("raw_input") or data.get("structure_query") or ""))
        if follow_up.get("follow_up_mode") and not data.get("follow_up_mode"):
            data["follow_up_mode"] = follow_up.get("follow_up_mode")
        if follow_up.get("job_type") and not data.get("job_type") and not data.get("intent"):
            data["job_type"] = follow_up.get("job_type")

        if not data.get("job_type"):
            data["job_type"] = intent or "analyze"
        if not data.get("normalized_text") and data.get("structure_query"):
            data["normalized_text"] = str(data.get("structure_query"))
        data["provider"] = provider

        parsed = PlanResponse.model_validate(data)

        return AgentPlan(
            intent=parsed.intent or intent,
            normalized_text=parsed.normalized_text,
            job_type=parsed.job_type or intent,
            query_kind=parsed.query_kind,
            semantic_grounding_needed=bool(parsed.semantic_grounding_needed),
            unknown_acronyms=list(parsed.unknown_acronyms),
            structure_query=parsed.structure_query,
            structure_query_candidates=list(parsed.structure_query_candidates),
            formula_mentions=list(parsed.formula_mentions),
            alias_mentions=list(parsed.alias_mentions),
            canonical_candidates=list(parsed.canonical_candidates),
            raw_input=parsed.raw_input,
            mixed_input=bool(parsed.mixed_input),
            composition_kind=parsed.composition_kind,
            charge_hint=parsed.charge_hint,
            structures=parsed.structures,
            mentioned_molecules=list(parsed.mentioned_molecules),
            target_scope=parsed.target_scope,
            selection_mode=parsed.selection_mode,
            selection_hint=parsed.selection_hint,
            selected_molecules=list(parsed.selected_molecules),
            analysis_bundle=list(parsed.analysis_bundle),
            batch_request=bool(parsed.batch_request),
            batch_size=parsed.batch_size,
            method=parsed.method,
            basis=parsed.basis,
            charge=parsed.charge,
            multiplicity=parsed.multiplicity,
            orbital=parsed.orbital,
            esp_preset=self._normalize_preset(parsed.esp_preset),
            focus_tab=parsed.focus_tab or defaults["focus_tab"],
            confidence=parsed.confidence,
            confidence_band=parsed.confidence_band or confidence_to_band(parsed.confidence),
            tool_name=str(data.get("tool_name") or defaults["tool_name"]).strip(),
            follow_up_mode=parsed.follow_up_mode,
            clarification_kind=parsed.clarification_kind,
            missing_slots=list(parsed.missing_slots),
            needs_clarification=bool(parsed.needs_clarification),
            notes=list(parsed.notes),
            reasoning_notes=list(parsed.reasoning_notes),
            provider=provider,
            fallback_reason=parsed.fallback_reason,
            chat_response=parsed.chat_response,
            raw=parsed.to_public_dict(),
        )

    def _heuristic_chat_response(self, text: str, normalized: Dict[str, Any]) -> str:
        acronyms = [str(item).strip() for item in list(normalized.get("unknown_acronyms") or []) if str(item).strip()]
        if acronyms:
            token = acronyms[0]
            return (
                f"`{token}` looks like an abbreviation, and chemistry abbreviations can be ambiguous.\n\n"
                f"- If you want a calculation, tell me the full compound name or a SMILES string.\n"
                f"- If you want an explanation, tell me which compound you mean and what you want to know.\n\n"
                f"For example: `full name + HOMO`, `full name + ESP`, or `SMILES + optimize`."
            )
        return (
            "This looks more like a chemistry question than an explicit calculation request.\n\n"
            "- If you want an explanation, ask the concept directly.\n"
            "- If you want a calculation, tell me the molecule and the task together.\n\n"
            "Examples: `benzene HOMO 보여줘`, `water ESP map`, `acetone optimize`."
        )

    def _looks_like_half_normalized_structure(self, query: Optional[str]) -> bool:
        token = str(query or "").strip()
        if not token:
            return False
        return bool(re.search(r"(?=.*[A-Za-z])(?=.*[가-힣ㄱ-ㅎㅏ-ㅣ])", token))

    def _extract_structure_query(self, text: str) -> Optional[str]:
        return extract_structure_candidate(text)

    def _is_task_like_structure_query(self, query: str) -> bool:
        token = str(query or "").strip()
        if not token:
            return False
        if detect_task_hint(token):
            return True
        return bool(
            re.search(
                r"\b(homo|lumo|esp|orbital|charge|charges|basis|optimize|optimization|analysis)\b|"
                r"궁금|알려줘|뭐야|보여줘|해줘|그려줘|ㄱㄱ|(?:\bgo(?:\s+go)?\b)|가자",
                token,
                re.IGNORECASE,
            )
        )

    def _extract_method(self, text: str) -> Optional[str]:
        methods = [
            "HF",
            "B3LYP",
            "PBE",
            "PBE0",
            "M06-2X",
            "M062X",
            "wB97X-D",
            "WB97X-D",
            "CAM-B3LYP",
            "TPSSh",
            "BP86",
        ]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g",
            "3-21g",
            "6-31g",
            "6-31g*",
            "6-31g**",
            "6-311g",
            "6-311g*",
            "6-311g**",
            "def2-svp",
            "def2-tzvp",
            "cc-pvdz",
            "cc-pvtz",
            "aug-cc-pvdz",
        ]
        for basis in basis_list:
            if re.search(rf"\b{re.escape(basis)}\b", text, re.I):
                return basis
        return None

    def _extract_charge(self, text: str) -> Optional[int]:
        patterns = [
            r"\bcharge\s*[:=]?\s*([+-]?\d+)\b",
            r"\bq\s*=\s*([+-]?\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\banion\b", text, re.I):
            return -1
        if re.search(r"\bcation\b", text, re.I):
            return 1
        return None

    def _extract_multiplicity(self, text: str) -> Optional[int]:
        patterns = [
            r"\bmultiplicity\s*[:=]?\s*(\d+)\b",
            r"\bspin multiplicity\s*[:=]?\s*(\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\bsinglet\b", text, re.I):
            return 1
        if re.search(r"\bdoublet\b", text, re.I):
            return 2
        if re.search(r"\btriplet\b", text, re.I):
            return 3
        return None

    def _extract_orbital(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(HOMO(?:[+-]\d+)?)\b",
            r"\b(LUMO(?:[+-]\d+)?)\b",
            r"\b(MO\s*\d+)\b",
            r"\borbital\s+([A-Za-z0-9+\-]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip().upper().replace(" ", "")
        return None

    def _extract_esp_preset(self, text: str) -> Optional[str]:
        presets = [
            "rwb",
            "bwr",
            "viridis",
            "inferno",
            "spectral",
            "nature",
            "acs",
            "rsc",
            "greyscale",
            "grey",
            "high_contrast",
            "hicon",
        ]
        for preset in presets:
            if re.search(rf"\b{re.escape(preset)}\b", text, re.I):
                return self._normalize_preset(preset)
        return None

    def _normalize_preset(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        key = value.strip().lower()
        if key == "grey":
            return "greyscale"
        if key == "hicon":
            return "high_contrast"
        return key

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content or "")

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
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _safe_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _none_if_blank(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    # ── Gemini direct chat & molecule suggestion ──────────────

    def _gemini_generate(self, prompt: str, json_mode: bool = False) -> str:
        """Low-level Gemini call. Returns raw text response."""
        config = {}
        if json_mode:
            config["response_mime_type"] = "application/json"

        try:
            from google import genai  # type: ignore
            if not self.gemini_api_key:
                return ""
            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=config if config else None,
            )
            return getattr(resp, "text", "") or ""
        except Exception:
            pass

        try:
            import google.generativeai as genai  # type: ignore
            if not self.gemini_api_key:
                return ""
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel(self.gemini_model)
            resp = model.generate_content(prompt)
            return getattr(resp, "text", "") or ""
        except Exception:
            return ""

    def chat_direct(self, message: str, context: Optional[List[Dict[str, str]]] = None) -> str:
        """Direct conversational Gemini call. Returns natural language response."""
        history_str = ""
        if context:
            for msg in context[-10:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_str += f"\n{role}: {content}"

        prompt = f"""You are QCViz Assistant, a friendly and knowledgeable quantum chemistry AI chatbot.
You are part of a web app that runs PySCF quantum chemistry calculations.

Respond naturally in the user's language (Korean/English). Be helpful, detailed, and suggest
specific molecules or calculations when appropriate.

If the user asks about molecules vaguely (e.g., "5원자 분자", "representative molecule"),
suggest specific molecules with their formulas and atom counts, and offer to run calculations.

Use markdown formatting for readability.
{f"Conversation history:{history_str}" if history_str else ""}

User: {message}

Respond:"""
        return self._gemini_generate(prompt)

    def suggest_molecules(
        self,
        description: str,
        *,
        allow_generic_fallback: bool = True,
    ) -> List[Dict[str, str]]:
        """Ask Gemini to suggest molecules matching a description. Returns structured list."""
        prompt = f"""You are a chemistry expert. The user described a molecule they want:
"{description}"

Suggest exactly 5 specific molecules that match this description.
Return a JSON array where each element has:
- "name": English molecule name (e.g., "methane")
- "formula": Chemical formula (e.g., "CH4")  
- "atoms": Number of atoms as integer
- "description": Brief Korean+English description (e.g., "메탄 — simplest alkane, 5 atoms")

Pick molecules that are commonly computed and well-supported by PySCF.
Prioritize molecules that match the atom count or description.
Return ONLY the JSON array, nothing else."""
        try:
            text = self._gemini_generate(prompt, json_mode=True)
            data = json.loads(text)
            if isinstance(data, list):
                return data[:5]
        except Exception:
            pass
        if not allow_generic_fallback:
            return []
        # Fallback
        return [
            {"name": "water", "formula": "H2O", "atoms": 3, "description": "물 — 3 atoms"},
            {"name": "methane", "formula": "CH4", "atoms": 5, "description": "메탄 — 5 atoms"},
            {"name": "ethanol", "formula": "C2H5OH", "atoms": 9, "description": "에탄올 — 9 atoms"},
            {"name": "methanol", "formula": "CH3OH", "atoms": 6, "description": "메탄올 — 6 atoms"},
            {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "벤젠 — 12 atoms"},
        ]
