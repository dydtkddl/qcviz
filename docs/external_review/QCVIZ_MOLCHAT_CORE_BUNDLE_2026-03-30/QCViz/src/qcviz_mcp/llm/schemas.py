from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


ConfidenceBand = Literal["low", "medium", "high"]
ClarificationFieldType = Literal["text", "textarea", "radio", "select", "multiselect", "number", "checkbox"]


def confidence_to_band(confidence: float) -> ConfidenceBand:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


class ClarificationOption(BaseModel):
    value: str
    label: str


class ClarificationField(BaseModel):
    id: str
    type: ClarificationFieldType
    label: str
    required: bool = False
    options: List[ClarificationOption] = Field(default_factory=list)
    default: Optional[Any] = None
    placeholder: Optional[str] = None
    help_text: Optional[str] = None
    validation: Dict[str, Any] = Field(default_factory=dict)


class ClarificationForm(BaseModel):
    mode: str = "clarification"
    title: str = "Need more information"
    message: str = ""
    fields: List[ClarificationField] = Field(default_factory=list)


class ResultExplanation(BaseModel):
    summary: str = ""
    key_findings: List[str] = Field(default_factory=list)
    interpretation: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class SlotMergeResult(BaseModel):
    session_id: Optional[str] = None
    prior_plan: Dict[str, Any] = Field(default_factory=dict)
    user_answers: Dict[str, Any] = Field(default_factory=dict)
    merged_plan: Dict[str, Any] = Field(default_factory=dict)
    still_missing_slots: List[str] = Field(default_factory=list)
    ready_to_execute: bool = False


class PlanResponse(BaseModel):
    normalized_text: str = ""
    intent: str = "analyze"
    job_type: str = "analyze"
    query_kind: Optional[str] = None
    semantic_grounding_needed: bool = False
    unknown_acronyms: List[str] = Field(default_factory=list)
    structure_query: Optional[str] = None
    structure_query_candidates: List[str] = Field(default_factory=list)
    formula_mentions: List[str] = Field(default_factory=list)
    alias_mentions: List[str] = Field(default_factory=list)
    canonical_candidates: List[str] = Field(default_factory=list)
    raw_input: Optional[str] = None
    mixed_input: bool = False
    mentioned_molecules: List[Dict[str, Any]] = Field(default_factory=list)
    target_scope: Optional[str] = None
    selection_mode: Optional[str] = None
    selection_hint: Optional[str] = None
    selected_molecules: List[str] = Field(default_factory=list)
    analysis_bundle: List[str] = Field(default_factory=list)
    batch_request: bool = False
    batch_size: int = 0
    composition_kind: Optional[str] = None
    charge_hint: Optional[int] = None
    structures: Optional[List[Dict[str, Any]]] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    confidence_band: Optional[ConfidenceBand] = None
    follow_up_mode: Optional[str] = None
    clarification_kind: Optional[str] = None
    missing_slots: List[str] = Field(default_factory=list)
    needs_clarification: bool = False
    provider: str = "heuristic"
    fallback_reason: Optional[str] = None
    reasoning_notes: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    chat_response: Optional[str] = None

    @field_validator("intent", "job_type", "focus_tab", "provider", mode="before")
    @classmethod
    def _normalize_text_field(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator(
        "structure_query",
        "method",
        "basis",
        "orbital",
        "esp_preset",
        "fallback_reason",
        "chat_response",
        "raw_input",
        "target_scope",
        "selection_mode",
        "selection_hint",
        "composition_kind",
        "follow_up_mode",
        "clarification_kind",
        "query_kind",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            fval = float(value)
        except Exception:
            fval = 0.0
        if fval < 0.0:
            return 0.0
        if fval > 1.0:
            return 1.0
        return fval

    @field_validator(
        "missing_slots",
        "reasoning_notes",
        "notes",
        "structure_query_candidates",
        "formula_mentions",
        "alias_mentions",
        "canonical_candidates",
        "selected_molecules",
        "analysis_bundle",
        "unknown_acronyms",
        mode="before",
    )
    @classmethod
    def _ensure_string_list(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @field_validator("mentioned_molecules", mode="before")
    @classmethod
    def _ensure_dict_list(cls, value: Any) -> List[Dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            out: List[Dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    out.append(dict(item))
            return out
        return []

    @model_validator(mode="after")
    def _derive_defaults(self) -> "PlanResponse":
        if not self.job_type:
            self.job_type = self.intent or "analyze"
        if not self.confidence_band:
            self.confidence_band = confidence_to_band(self.confidence)
        if self.missing_slots and not self.needs_clarification:
            self.needs_clarification = True
        if self.needs_clarification and not self.clarification_kind:
            self.clarification_kind = "clarification"
        if self.semantic_grounding_needed and not self.clarification_kind:
            self.clarification_kind = "semantic_grounding"
        if self.selected_molecules and not self.batch_size:
            self.batch_size = len(self.selected_molecules)
        elif self.mentioned_molecules and not self.batch_size:
            self.batch_size = len(self.mentioned_molecules)
        if self.batch_size > 1 and not self.batch_request:
            self.batch_request = True
        return self

    def to_public_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)
