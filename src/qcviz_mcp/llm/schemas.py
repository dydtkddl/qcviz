from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


ConfidenceBand = Literal["low", "medium", "high"]
ClarificationFieldType = Literal["text", "textarea", "radio", "select", "multiselect", "number", "checkbox"]
PlannerLane = Literal["chat_only", "grounding_required", "compute_ready"]
ComputationType = Literal["homo", "lumo", "esp", "optimization", "energy", "frequency", "custom"]
PresetType = Literal["acs", "rsc", "custom"]
GroundingSemanticOutcome = Literal[
    "grounded_direct_answer",
    "single_candidate_confirm",
    "grounding_clarification",
    "custom_only_clarification",
    "compute_ready",
    "chat_only",
]
ExecutionAction = Literal["compute", "chat_response", "chat_with_structure", "clarification"]


def confidence_to_band(confidence: float) -> ConfidenceBand:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _as_clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_optional_text(value: Any) -> Optional[str]:
    text = _as_clean_text(value)
    return text or None


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _as_clean_text(value)
    return [text] if text else []


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        out: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
        return out
    return []


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _clamp_confidence(value: Any) -> float:
    try:
        fval = float(value)
    except Exception:
        fval = 0.0
    if fval < 0.0:
        return 0.0
    if fval > 1.0:
        return 1.0
    return fval


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


class IngressResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    original_text: str = Field(default="", validation_alias=AliasChoices("original_text", "raw_text"))
    cleaned_text: str = Field(default="", validation_alias=AliasChoices("cleaned_text", "clean_text"))
    preserved_tokens: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("preserved_tokens", "preserve_tokens"),
    )
    is_follow_up: bool = False
    follow_up_type: Optional[str] = None
    language_hint: Optional[str] = Field(default=None, validation_alias=AliasChoices("language_hint", "language"))
    llm_rewrite_used: bool = False
    unknown_tokens: List[str] = Field(default_factory=list)
    noise_flags: List[str] = Field(default_factory=list)
    suspected_typos: List[str] = Field(default_factory=list)
    rewrite_confidence: float = 0.0

    @field_validator("original_text", "cleaned_text", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _as_clean_text(value)

    @field_validator(
        "preserved_tokens",
        "unknown_tokens",
        "noise_flags",
        "suspected_typos",
        mode="before",
    )
    @classmethod
    def _normalize_list_fields(cls, value: Any) -> List[str]:
        return _as_string_list(value)

    @field_validator("is_follow_up", "llm_rewrite_used", mode="before")
    @classmethod
    def _normalize_bool_fields(cls, value: Any) -> bool:
        return _as_bool(value)

    @field_validator("follow_up_type", "language_hint", mode="before")
    @classmethod
    def _normalize_optional_text_fields(cls, value: Any) -> Optional[str]:
        return _as_optional_text(value)

    @field_validator("rewrite_confidence", mode="before")
    @classmethod
    def _normalize_rewrite_confidence(cls, value: Any) -> float:
        return _clamp_confidence(value)

    @model_validator(mode="after")
    def _derive_ingress_defaults(self) -> "IngressResult":
        if not self.cleaned_text:
            self.cleaned_text = self.original_text
        if self.language_hint is None:
            self.language_hint = "unknown"
        return self

    @property
    def raw_text(self) -> str:
        return self.original_text

    @property
    def clean_text(self) -> str:
        return self.cleaned_text

    @property
    def preserve_tokens(self) -> List[str]:
        return list(self.preserved_tokens)

    @property
    def language(self) -> str:
        return self.language_hint or "unknown"


class IngressRewriteResult(IngressResult):
    pass


class SemanticExpansionResult(BaseModel):
    canonical_user_question: str = ""
    grounding_queries: List[str] = Field(default_factory=list)
    explanation_queries: List[str] = Field(default_factory=list)
    compute_queries: List[str] = Field(default_factory=list)
    expansion_notes: List[str] = Field(default_factory=list)

    @field_validator("canonical_user_question", mode="before")
    @classmethod
    def _normalize_expansion_text_field(cls, value: Any) -> str:
        return _as_clean_text(value)

    @field_validator(
        "grounding_queries",
        "explanation_queries",
        "compute_queries",
        "expansion_notes",
        mode="before",
    )
    @classmethod
    def _ensure_expansion_string_list(cls, value: Any) -> List[str]:
        return _as_string_list(value)


class PlanResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lane: PlannerLane
    confidence: float = 0.0
    reasoning: str = ""
    molecule_name: Optional[str] = None
    computation_type: Optional[ComputationType] = None
    basis_set: Optional[str] = None
    method: Optional[str] = None
    preset: Optional[PresetType] = None
    is_follow_up: bool = False
    unknown_acronyms: List[str] = Field(default_factory=list)
    molecule_from_context: Optional[str] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_plan_confidence(cls, value: Any) -> float:
        return _clamp_confidence(value)

    @field_validator("reasoning", mode="before")
    @classmethod
    def _normalize_reasoning(cls, value: Any) -> str:
        return _as_clean_text(value)

    @field_validator(
        "molecule_name",
        "basis_set",
        "method",
        "preset",
        "molecule_from_context",
        mode="before",
    )
    @classmethod
    def _normalize_plan_optional_text_fields(cls, value: Any) -> Optional[str]:
        return _as_optional_text(value)

    @field_validator("is_follow_up", mode="before")
    @classmethod
    def _normalize_plan_bool_fields(cls, value: Any) -> bool:
        return _as_bool(value)

    @field_validator("unknown_acronyms", mode="before")
    @classmethod
    def _normalize_unknown_acronyms(cls, value: Any) -> List[str]:
        return _as_string_list(value)

    @model_validator(mode="after")
    def _check_plan_invariants(self) -> "PlanResult":
        if self.lane == "chat_only" and self.computation_type is not None:
            raise ValueError("chat_only lane cannot include computation_type")
        if self.lane == "compute_ready" and not (self.molecule_name or self.molecule_from_context):
            raise ValueError("compute_ready lane requires molecule_name or molecule_from_context")
        return self


class GroundingCandidate(BaseModel):
    name: str = ""
    formula: Optional[str] = None
    smiles: Optional[str] = None
    confidence: float = 0.0
    source: str = "unknown"
    query_mode: Optional[str] = None
    resolution_method: Optional[str] = None
    rationale: Optional[str] = None
    cid: Optional[int] = None

    @field_validator("name", "source", mode="before")
    @classmethod
    def _normalize_candidate_required_text_fields(cls, value: Any) -> str:
        return _as_clean_text(value)

    @field_validator("formula", "smiles", "query_mode", "resolution_method", "rationale", mode="before")
    @classmethod
    def _normalize_candidate_optional_text_fields(cls, value: Any) -> Optional[str]:
        return _as_optional_text(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_candidate_confidence(cls, value: Any) -> float:
        return _clamp_confidence(value)

    @field_validator("cid", mode="before")
    @classmethod
    def _normalize_candidate_cid(cls, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None


class GroundingOutcome(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    semantic_outcome: GroundingSemanticOutcome = Field(
        default="grounding_clarification",
        validation_alias=AliasChoices("semantic_outcome", "outcome"),
    )
    resolved_structure: Optional[GroundingCandidate] = None
    candidates: List[GroundingCandidate] = Field(default_factory=list)
    clarification_message: Optional[str] = None
    supports_direct_answer: Optional[bool] = None
    requires_confirmation: Optional[bool] = None
    allow_compute_submit: Optional[bool] = None

    @field_validator("clarification_message", mode="before")
    @classmethod
    def _normalize_clarification_message(cls, value: Any) -> Optional[str]:
        return _as_optional_text(value)

    @field_validator("supports_direct_answer", "requires_confirmation", "allow_compute_submit", mode="before")
    @classmethod
    def _normalize_outcome_bool_fields(cls, value: Any) -> Optional[bool]:
        if value is None:
            return None
        return _as_bool(value)

    @field_validator("candidates", mode="before")
    @classmethod
    def _normalize_candidates(cls, value: Any) -> List[GroundingCandidate]:
        if value is None:
            return []
        if isinstance(value, list):
            return [GroundingCandidate.model_validate(item) for item in value]
        return []

    @field_validator("resolved_structure", mode="before")
    @classmethod
    def _normalize_resolved_structure(cls, value: Any) -> Optional[GroundingCandidate]:
        if value is None or value == "":
            return None
        if isinstance(value, GroundingCandidate):
            return value
        if isinstance(value, dict):
            return GroundingCandidate.model_validate(value)
        if isinstance(value, str):
            text = _as_clean_text(value)
            if not text:
                return None
            return GroundingCandidate(name=text, source="plan")
        return None

    @model_validator(mode="after")
    def _derive_outcome_defaults(self) -> "GroundingOutcome":
        if self.resolved_structure is not None:
            if not self.candidates:
                self.candidates = [self.resolved_structure]
            elif not any(candidate.name == self.resolved_structure.name for candidate in self.candidates):
                self.candidates = [self.resolved_structure, *self.candidates]
        if self.supports_direct_answer is None:
            self.supports_direct_answer = self.semantic_outcome == "grounded_direct_answer"
        if self.requires_confirmation is None:
            self.requires_confirmation = self.semantic_outcome in {
                "single_candidate_confirm",
                "grounding_clarification",
                "custom_only_clarification",
            }
        if self.allow_compute_submit is None:
            self.allow_compute_submit = self.semantic_outcome == "compute_ready"
        return self

    @property
    def outcome(self) -> str:
        return self.semantic_outcome

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def selected_candidate(self) -> Optional[str]:
        if self.resolved_structure is not None and self.resolved_structure.name:
            return self.resolved_structure.name
        if len(self.candidates) == 1:
            return self.candidates[0].name or None
        return None


class ExecutionDecision(BaseModel):
    action: ExecutionAction
    payload: Optional[Dict[str, Any]] = None
    candidates: List[GroundingCandidate] = Field(default_factory=list)

    @field_validator("payload", mode="before")
    @classmethod
    def _normalize_payload(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        return None

    @field_validator("candidates", mode="before")
    @classmethod
    def _normalize_decision_candidates(cls, value: Any) -> List[GroundingCandidate]:
        if value is None:
            return []
        if isinstance(value, list):
            return [GroundingCandidate.model_validate(item) for item in value]
        return []


class PlanResponse(BaseModel):
    normalized_text: str = ""
    intent: str = "analyze"
    job_type: str = "analyze"
    query_kind: Optional[str] = None
    planner_lane: Optional[str] = None
    lane_locked: bool = False
    locked_lane: Optional[str] = None
    semantic_grounding_needed: bool = False
    question_like: bool = False
    explicit_compute_action: bool = False
    explanation_intent: bool = False
    grounding_intent: bool = False
    compute_intent: bool = False
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
    reasoning: str = ""
    follow_up_mode: Optional[str] = None
    clarification_kind: Optional[str] = None
    missing_slots: List[str] = Field(default_factory=list)
    needs_clarification: bool = False
    provider: str = "heuristic"
    pipeline_enabled: bool = False
    pipeline_fallback_stage: Optional[str] = None
    pipeline_repair_count: int = 0
    fallback_reason: Optional[str] = None
    reasoning_notes: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    chat_response: Optional[str] = None

    @field_validator("intent", "job_type", "focus_tab", "provider", "reasoning", mode="before")
    @classmethod
    def _normalize_text_field(cls, value: Any) -> str:
        return _as_clean_text(value)

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
        "planner_lane",
        "locked_lane",
        "pipeline_fallback_stage",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Optional[str]:
        return _as_optional_text(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence_field(cls, value: Any) -> float:
        return _clamp_confidence(value)

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
        return _as_string_list(value)

    @field_validator("mentioned_molecules", mode="before")
    @classmethod
    def _ensure_dict_list(cls, value: Any) -> List[Dict[str, Any]]:
        return _as_dict_list(value)

    @field_validator(
        "semantic_grounding_needed",
        "question_like",
        "explicit_compute_action",
        "explanation_intent",
        "grounding_intent",
        "compute_intent",
        "needs_clarification",
        "batch_request",
        "mixed_input",
        "pipeline_enabled",
        "lane_locked",
        mode="before",
    )
    @classmethod
    def _normalize_bool_fields(cls, value: Any) -> bool:
        return _as_bool(value)

    @field_validator("pipeline_repair_count", mode="before")
    @classmethod
    def _normalize_pipeline_repair_count(cls, value: Any) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return 0

    @model_validator(mode="after")
    def _derive_defaults(self) -> "PlanResponse":
        if not self.job_type:
            self.job_type = self.intent or "analyze"
        if not self.planner_lane:
            self.planner_lane = self.query_kind
        if self.lane_locked and not self.locked_lane:
            self.locked_lane = self.planner_lane
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
