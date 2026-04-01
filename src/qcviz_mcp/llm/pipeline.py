from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from qcviz_mcp.llm.grounding_merge import (
    GroundingConfig,
    SEMANTIC_OUTCOME_CHAT_ONLY,
    SEMANTIC_OUTCOME_COMPUTE_READY,
    SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION,
    SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER,
    SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION,
    SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM,
    grounding_merge,
)
from qcviz_mcp.llm.lane_lock import LaneLock
from qcviz_mcp.llm.normalizer import analyze_follow_up_request, normalize_user_text
from qcviz_mcp.llm.schemas import (
    GroundingOutcome,
    IngressResult,
    IngressRewriteResult,
    PlanResult,
    PlanResponse,
)
from qcviz_mcp.llm.trace import PipelineTrace, emit_pipeline_trace

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_PROMPT_ASSET_DIR = Path(__file__).with_name("prompt_assets")
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_PRESERVE_TOKEN_RE = re.compile(
    r"\b(?:[A-Z]{2,6}(?:[+-])?|B3LYP|PBE0|M06-2X|M062X|WB97X-D|wB97X-D|HF|MP2|CCSD|"
    r"STO-?3G|3-21G|6-31G\*{0,2}|6-311G\*{0,2}|DEF2-?SVP|DEF2-?TZVP|CC-PV[DT]Z|AUG-CC-PV[DT]Z|"
    r"ACS|RSC|ESP|HOMO|LUMO)\b",
    re.IGNORECASE,
)


class PipelineStageError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_flag_any(names: List[str], default: bool) -> bool:
    for name in names:
        raw = os.getenv(name)
        if raw is not None:
            return _env_flag(name, default)
    return default


def _env_int_any(names: List[str], default: int) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is not None:
            try:
                return int(str(raw).strip())
            except Exception:
                return default
    return default


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_plan_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_public_dict") and callable(value.to_public_dict):
        try:
            public = value.to_public_dict()
            if isinstance(public, Mapping):
                return dict(public)
        except Exception:
            pass
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            dumped = value.model_dump(exclude_none=True)
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            dumped = value.to_dict()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass
    return {}


def _guess_language(text: str) -> str:
    raw = _coerce_text(text)
    if not raw:
        return "unknown"
    if re.search(r"[가-힣]", raw):
        return "ko"
    if re.search(r"[A-Za-z]", raw):
        return "en"
    return "unknown"


def _normalized_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9+\-]", "", _coerce_text(token)).lower()


def _collect_preserve_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for match in _PRESERVE_TOKEN_RE.finditer(_coerce_text(text)):
        token = _coerce_text(match.group(0))
        normalized = _normalized_token(token)
        if normalized and normalized not in seen:
            seen.add(normalized)
            tokens.append(token)
    return tokens


def _token_survives(text: str, token: str) -> bool:
    needle = _normalized_token(token)
    if not needle:
        return True
    haystack = _normalized_token(text)
    return needle in haystack


def build_grounding_outcome(
    plan: Optional[Mapping[str, Any]],
    candidates: List[Mapping[str, Any]],
    *,
    structure_locked: bool = False,
) -> GroundingOutcome:
    lane_lock = LaneLock()
    return grounding_merge(
        dict(plan or {}),
        candidates,
        lane_lock=lane_lock,
        structure_locked=structure_locked,
        config=GroundingConfig.from_env(),
    )


class QCVizPromptPipeline:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        enabled: Optional[bool] = None,
        force_heuristic: Optional[bool] = None,
        stage1_enabled: Optional[bool] = None,
        stage2_enabled: Optional[bool] = None,
        stage3_enabled: Optional[bool] = None,
        stage4_enabled: Optional[bool] = None,
        shadow_mode: Optional[bool] = None,
        serve_llm: Optional[bool] = None,
        canary_percent: Optional[int] = None,
        repair_max: Optional[int] = None,
    ) -> None:
        self.provider = _coerce_text(provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).lower() or "auto"
        self.openai_api_key = _coerce_text(openai_api_key or os.getenv("OPENAI_API_KEY"))
        self.openai_model = _coerce_text(openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")) or "gpt-4.1-mini"
        self.gemini_api_key = _coerce_text(gemini_api_key or os.getenv("GEMINI_API_KEY"))
        self.gemini_model = _coerce_text(gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.5-flash")) or "gemini-2.5-flash"
        self.enabled = enabled if enabled is not None else _env_flag_any(
            ["QCVIZ_PIPELINE_ENABLED", "QCVIZ_ENABLE_LLM_PIPELINE"],
            True,
        )
        self.force_heuristic = (
            force_heuristic
            if force_heuristic is not None
            else _env_flag_any(
                ["QCVIZ_PIPELINE_FORCE_HEURISTIC", "QCVIZ_LLM_PIPELINE_FORCE_HEURISTIC"],
                False,
            )
        )
        self.stage1_enabled = (
            stage1_enabled
            if stage1_enabled is not None
            else _env_flag_any(
                ["QCVIZ_PIPELINE_STAGE1_LLM", "QCVIZ_LLM_PIPELINE_STAGE1"],
                False,
            )
        )
        effective_stage2 = stage2_enabled
        if effective_stage2 is None and stage3_enabled is not None:
            effective_stage2 = stage3_enabled
        self.stage2_enabled = (
            effective_stage2
            if effective_stage2 is not None
            else _env_flag_any(
                ["QCVIZ_PIPELINE_STAGE2_LLM", "QCVIZ_LLM_PIPELINE_STAGE3", "QCVIZ_LLM_PIPELINE_STAGE2"],
                True,
            )
        )
        self.shadow_mode = (
            shadow_mode
            if shadow_mode is not None
            else _env_flag_any(["QCVIZ_PIPELINE_SHADOW_MODE"], False)
        )
        self.serve_llm = (
            serve_llm
            if serve_llm is not None
            else _env_flag_any(["QCVIZ_PIPELINE_SERVE_LLM"], True)
        )
        self.canary_percent = max(
            0,
            min(
                100,
                canary_percent
                if canary_percent is not None
                else _env_int_any(["QCVIZ_PIPELINE_CANARY_PERCENT"], 100),
            ),
        )
        self.stage3_enabled = self.stage2_enabled
        self.stage4_enabled = stage4_enabled if stage4_enabled is not None else False
        self.repair_max = max(
            0,
            repair_max
            if repair_max is not None
            else _env_int_any(["QCVIZ_PIPELINE_REPAIR_MAX", "QCVIZ_LLM_PIPELINE_REPAIR_MAX"], 1),
        )
        self._stage_attempts: Dict[str, int] = {}

    def is_enabled(self) -> bool:
        return bool(self.enabled and not self.force_heuristic)

    def execute(
        self,
        message: str,
        context: Optional[Mapping[str, Any]],
        *,
        heuristic_planner: Callable[[str, Mapping[str, Any], Dict[str, Any]], Any],
        llm_planner: Optional[Callable[[str, Dict[str, Any], Mapping[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        raw_text = _coerce_text(message)
        context = dict(context or {})
        normalized_hint = normalize_user_text(raw_text)
        self._stage_attempts = {}
        trace = PipelineTrace(
            trace_id=str(uuid.uuid4()),
            session_id=_coerce_text(context.get("session_id")) or None,
            raw_input=raw_text,
        )
        started = time.perf_counter()

        if not raw_text:
            result = self._fallback(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                stage="stage0",
                reason="empty_message",
                repair_count=0,
            )
            trace.stage_outputs["fallback"] = result
            trace.fallback_stage = "stage0"
            trace.fallback_reason = "empty_message"
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return result

        if not self.enabled:
            result = self._fallback(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                stage="disabled",
                reason="pipeline_disabled",
                repair_count=0,
            )
            trace.stage_outputs["fallback"] = result
            trace.fallback_stage = "disabled"
            trace.fallback_reason = "pipeline_disabled"
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return result

        if self.force_heuristic:
            result = self._fallback(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                stage="forced",
                reason="pipeline_force_heuristic",
                repair_count=0,
            )
            trace.stage_outputs["fallback"] = result
            trace.fallback_stage = "forced"
            trace.fallback_reason = "pipeline_force_heuristic"
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return result

        if not self._has_llm_provider():
            reason = self._detailed_no_provider_reason()
            result = self._fallback(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                stage="provider",
                reason=reason,
                repair_count=0,
            )
            trace.stage_outputs["fallback"] = result
            trace.fallback_stage = "provider"
            trace.fallback_reason = reason
            trace.failure_class = "planner_error"
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return result

        repair_count = 0
        try:
            stage_started = time.perf_counter()
            rewrite = self._run_ingress_rewrite(raw_text, normalized_hint, context)
            trace.stage_latencies_ms["stage1_ingress"] = round((time.perf_counter() - stage_started) * 1000.0, 3)
            trace.stage_outputs["stage1_ingress"] = rewrite.model_dump(exclude_none=True)
            if self.stage1_enabled and rewrite.rewrite_confidence < 0.5:
                raise PipelineStageError("stage1", "rewrite_confidence_below_threshold")

            stage_started = time.perf_counter()
            plan_dict = self._run_action_planner(
                raw_text,
                rewrite,
                normalized_hint,
                context,
                llm_planner,
            )
            trace.stage_latencies_ms["stage2_router"] = round((time.perf_counter() - stage_started) * 1000.0, 3)
            plan_dict = self._validate_planner_lane(plan_dict, normalized_hint)
            lane_lock = LaneLock()
            lane_lock.set(_coerce_text(plan_dict.get("lane") or plan_dict.get("query_kind")))
            repair_count = sum(max(0, count - 1) for count in self._stage_attempts.values())
            plan_dict = self._validate_and_enrich_plan(
                plan_dict,
                raw_text,
                normalized_hint,
                repair_count=repair_count,
                lane_lock=lane_lock,
            )
            trace.stage_outputs["stage2_router"] = {
                "planner_lane": plan_dict.get("planner_lane"),
                "provider": plan_dict.get("provider"),
                "query_kind": plan_dict.get("query_kind"),
            }
            trace.provider = _coerce_text(plan_dict.get("provider")) or None
            trace.locked_lane = lane_lock.lane
            trace.repair_count = max(0, int(plan_dict.get("pipeline_repair_count") or repair_count))
            plan_dict = self._maybe_apply_shadow_mode(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                llm_result=plan_dict,
                trace=trace,
            )
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return plan_dict
        except PipelineStageError as exc:
            logger.info("LLM pipeline fallback triggered at %s: %s", exc.stage, exc.reason)
            repair_count = max(repair_count, self.repair_max)
            result = self._fallback(
                raw_text,
                context,
                normalized_hint,
                heuristic_planner,
                stage=exc.stage,
                reason=exc.reason,
                repair_count=repair_count,
            )
            trace.stage_outputs["fallback"] = result
            trace.fallback_stage = exc.stage
            trace.fallback_reason = exc.reason
            trace.failure_class = "planner_error"
            trace.locked_lane = _coerce_text(result.get("locked_lane") or result.get("planner_lane")) or None
            trace.repair_count = max(0, int(result.get("pipeline_repair_count") or repair_count))
            trace.total_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            emit_pipeline_trace(trace)
            return result

    def _has_llm_provider(self) -> bool:
        if self.provider == "none":
            return False
        return bool(self.gemini_api_key or self.openai_api_key)

    def _detailed_no_provider_reason(self) -> str:
        if self.provider == "none":
            return "provider_set_to_none"
        if self.provider == "gemini" and not self.gemini_api_key:
            return "no_gemini_key"
        if self.provider == "openai" and not self.openai_api_key:
            return "no_openai_key"
        if not self.gemini_api_key and not self.openai_api_key:
            return "no_gemini_key_and_no_openai_key"
        return "no_llm_provider_available"

    def _load_prompt_asset(self, name: str) -> str:
        asset_path = _PROMPT_ASSET_DIR / name
        if not asset_path.exists():
            raise PipelineStageError("prompt_assets", f"missing prompt asset: {name}")
        return asset_path.read_text(encoding="utf-8")

    def _invoke_structured_stage(
        self,
        *,
        stage_name: str,
        asset_name: str,
        repair_asset_name: str,
        response_model: Type[T],
        payload: Dict[str, Any],
    ) -> T:
        last_error = "unknown_error"
        for attempt in range(self.repair_max + 1):
            repair_feedback = last_error if attempt else None
            try:
                provider = self._choose_stage_provider()
                if provider == "gemini":
                    result = self._invoke_gemini_stage(
                        stage_name=stage_name,
                        asset_name=repair_asset_name if repair_feedback else asset_name,
                        response_model=response_model,
                        payload=payload,
                        repair_feedback=repair_feedback,
                    )
                    self._stage_attempts[stage_name] = attempt + 1
                    return result
                if provider == "openai":
                    result = self._invoke_openai_stage(
                        stage_name=stage_name,
                        asset_name=repair_asset_name if repair_feedback else asset_name,
                        response_model=response_model,
                        payload=payload,
                        repair_feedback=repair_feedback,
                    )
                    self._stage_attempts[stage_name] = attempt + 1
                    return result
                raise PipelineStageError(stage_name, "no_stage_provider")
            except Exception as exc:
                last_error = str(exc)
                logger.info("%s attempt %s failed: %s", stage_name, attempt + 1, exc)
                self._stage_attempts[stage_name] = attempt + 1
        raise PipelineStageError(stage_name, last_error)

    def _choose_stage_provider(self) -> Optional[str]:
        if self.provider == "openai":
            return "openai" if self.openai_api_key else None
        if self.provider == "gemini":
            return "gemini" if self.gemini_api_key else None
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return None

    def _compose_stage_prompt(
        self,
        *,
        asset_name: str,
        payload: Dict[str, Any],
        response_model: Type[BaseModel],
        repair_feedback: Optional[str] = None,
    ) -> str:
        instructions = self._load_prompt_asset(asset_name)
        schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        repair_section = f"\nRepair feedback:\n{repair_feedback}\n" if repair_feedback else ""
        return (
            f"{instructions}\n\n"
            f"Output JSON schema:\n{schema_json}\n\n"
            f"Input payload:\n{payload_json}\n"
            f"{repair_section}"
        )

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        raw = _coerce_text(text)
        if not raw:
            raise ValueError("empty_response")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, Mapping):
                return dict(parsed)
        except Exception:
            pass
        match = _JSON_BLOCK_RE.search(raw)
        if not match:
            raise ValueError("no_json_object_found")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, Mapping):
            raise ValueError("response_is_not_json_object")
        return dict(parsed)

    def _invoke_openai_stage(
        self,
        *,
        stage_name: str,
        asset_name: str,
        response_model: Type[T],
        payload: Dict[str, Any],
        repair_feedback: Optional[str] = None,
    ) -> T:
        from openai import OpenAI

        if not self.openai_api_key:
            raise PipelineStageError(stage_name, "openai_api_key_missing")

        prompt = self._compose_stage_prompt(
            asset_name=asset_name,
            payload=payload,
            response_model=response_model,
            repair_feedback=repair_feedback,
        )
        client = OpenAI(api_key=self.openai_api_key)
        response = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return exactly one JSON object that matches the schema."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        data = self._extract_json_dict(content)
        return response_model.model_validate(data)

    def _invoke_gemini_stage(
        self,
        *,
        stage_name: str,
        asset_name: str,
        response_model: Type[T],
        payload: Dict[str, Any],
        repair_feedback: Optional[str] = None,
    ) -> T:
        from google import genai  # type: ignore

        if not self.gemini_api_key:
            raise PipelineStageError(stage_name, "gemini_api_key_missing")

        prompt = self._compose_stage_prompt(
            asset_name=asset_name,
            payload=payload,
            response_model=response_model,
            repair_feedback=repair_feedback,
        )
        client = genai.Client(api_key=self.gemini_api_key)
        response = client.models.generate_content(
            model=self.gemini_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config={"response_mime_type": "application/json", "temperature": 0},
        )
        content = _coerce_text(getattr(response, "text", None))
        if not content:
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                maybe_content = getattr(candidate, "content", None)
                parts = getattr(maybe_content, "parts", None) or []
                fragments = [str(getattr(part, "text", "")).strip() for part in parts if _coerce_text(getattr(part, "text", ""))]
                if fragments:
                    content = "\n".join(fragments)
                    break
        data = self._extract_json_dict(content)
        return response_model.model_validate(data)

    def _run_ingress_rewrite(
        self,
        raw_text: str,
        normalized_hint: Dict[str, Any],
        context: Mapping[str, Any],
    ) -> IngressRewriteResult:
        follow_up = analyze_follow_up_request(raw_text)
        fallback = IngressRewriteResult(
            original_text=raw_text,
            cleaned_text=_coerce_text(normalized_hint.get("normalized_text")) or raw_text,
            language_hint=_guess_language(raw_text),
            noise_flags=[],
            suspected_typos=[],
            preserved_tokens=_collect_preserve_tokens(raw_text),
            rewrite_confidence=0.55,
            is_follow_up=bool(follow_up.get("requires_context") or follow_up.get("follow_up_mode")),
            follow_up_type=_coerce_text(follow_up.get("follow_up_mode")) or None,
            llm_rewrite_used=False,
            unknown_tokens=list(normalized_hint.get("unknown_acronyms") or []),
        )
        if not self.stage1_enabled or not self._should_use_stage1_rewrite(raw_text, normalized_hint):
            return fallback

        result = self._invoke_structured_stage(
            stage_name="stage1",
            asset_name="ingress_rewrite.md",
            repair_asset_name="ingress_rewrite_repair.md",
            response_model=IngressRewriteResult,
            payload={
                "raw_text": raw_text,
                "context": dict(context or {}),
                "preserve_tokens": fallback.preserve_tokens,
                "follow_up_hint": fallback.follow_up_type,
            },
        )
        if not _coerce_text(result.cleaned_text):
            raise PipelineStageError("stage1", "clean_text_empty")
        result.original_text = raw_text
        result.llm_rewrite_used = True
        result.is_follow_up = fallback.is_follow_up if not result.is_follow_up else result.is_follow_up
        result.follow_up_type = result.follow_up_type or fallback.follow_up_type
        if not result.preserved_tokens:
            result.preserved_tokens = list(fallback.preserved_tokens)
        if not result.unknown_tokens:
            result.unknown_tokens = list(fallback.unknown_tokens)
        for token in fallback.preserve_tokens:
            if not _token_survives(result.cleaned_text, token):
                raise PipelineStageError("stage1", f"preserve_token_lost:{token}")
        if len(result.cleaned_text) < max(4, len(raw_text) // 4):
            raise PipelineStageError("stage1", "rewrite_drift_too_aggressive")
        return result

    def _run_action_planner(
        self,
        raw_text: str,
        rewrite: IngressRewriteResult,
        normalized_hint: Dict[str, Any],
        context: Mapping[str, Any],
        llm_planner: Optional[Callable[[str, Dict[str, Any], Mapping[str, Any]], Any]],
    ) -> Dict[str, Any]:
        if not self.stage2_enabled:
            raise PipelineStageError("stage2", "router_planner_disabled")

        if llm_planner is not None and getattr(self, "_legacy_planner_passthrough", False):
            plan_obj = llm_planner(
                rewrite.cleaned_text or raw_text,
                {
                    "rewrite": rewrite.model_dump(),
                    "normalized_hint": normalized_hint,
                },
                context,
            )
            plan_dict = _coerce_plan_dict(plan_obj)
            if not plan_dict:
                raise PipelineStageError("stage2", "legacy_llm_planner_returned_empty_plan")
            return plan_dict

        result = self._invoke_structured_stage(
            stage_name="stage2",
            asset_name="action_planner.md",
            repair_asset_name="action_planner_repair.md",
            response_model=PlanResult,
            payload={
                "original_text": raw_text,
                "cleaned_text": rewrite.cleaned_text or raw_text,
                "ingress": rewrite.model_dump(exclude_none=True),
                "annotations": {
                    "question_like": bool(normalized_hint.get("question_like")),
                    "explicit_compute_action": bool(normalized_hint.get("explicit_compute_action")),
                    "semantic_descriptor": bool(normalized_hint.get("semantic_descriptor")),
                    "unknown_acronyms": list(normalized_hint.get("unknown_acronyms") or []),
                    "follow_up_mode": normalized_hint.get("follow_up_mode"),
                    "follow_up_requires_context": bool(normalized_hint.get("follow_up_requires_context")),
                    "analysis_bundle": list(normalized_hint.get("analysis_bundle") or []),
                },
                "context": dict(context or {}),
                "available_actions": [
                    "chat_only",
                    "grounding_required",
                    "compute_ready",
                    "homo",
                    "lumo",
                    "esp",
                    "optimization",
                    "energy",
                    "frequency",
                    "custom",
                ],
            },
        )
        return result.model_dump(exclude_none=True)

    def _should_use_stage1_rewrite(self, raw_text: str, normalized_hint: Mapping[str, Any]) -> bool:
        text = _coerce_text(raw_text)
        if not text:
            return False
        if len(text) > 220:
            return True
        normalized_text = _coerce_text(normalized_hint.get("normalized_text"))
        preserve_tokens = _collect_preserve_tokens(text)
        has_mixed_language = bool(re.search(r"[A-Za-z]", text) and re.search(r"[가-힣]", text))
        noisy_spacing = bool(normalized_text and normalized_text != text and len(text.split()) <= 2)
        preserve_risk = bool(preserve_tokens and normalized_text and any(not _token_survives(normalized_text, token) for token in preserve_tokens))
        typo_density = text.count("?") >= 2 or bool(re.search(r"[^\w\s\-\+\(\)=/#,.;:]{3,}", text))
        return bool(has_mixed_language or noisy_spacing or preserve_risk or typo_density)

    def _validate_planner_lane(self, plan_dict: Dict[str, Any], normalized_hint: Dict[str, Any]) -> Dict[str, Any]:
        legacy_payload = {
            "lane": _coerce_text(plan_dict.get("lane") or plan_dict.get("planner_lane") or plan_dict.get("query_kind")),
            "confidence": plan_dict.get("confidence", 0.0),
            "reasoning": plan_dict.get("reasoning") or "router-planner output",
            "molecule_name": _coerce_text(
                plan_dict.get("molecule_name")
                or plan_dict.get("structure_query")
                or plan_dict.get("raw_input")
                if (_coerce_text(plan_dict.get("lane") or plan_dict.get("planner_lane") or plan_dict.get("query_kind")) == "compute_ready")
                else plan_dict.get("molecule_name") or plan_dict.get("structure_query")
            ) or None,
            "computation_type": plan_dict.get("computation_type") or self._legacy_computation_type(plan_dict),
            "basis_set": plan_dict.get("basis_set") or plan_dict.get("basis"),
            "method": plan_dict.get("method"),
            "preset": plan_dict.get("preset") or self._legacy_preset(plan_dict),
            "is_follow_up": plan_dict.get("is_follow_up") or bool(normalized_hint.get("follow_up_mode")),
            "unknown_acronyms": plan_dict.get("unknown_acronyms") or normalized_hint.get("unknown_acronyms") or [],
            "molecule_from_context": plan_dict.get("molecule_from_context") or normalized_hint.get("maybe_structure_hint"),
        }
        try:
            parsed = PlanResult.model_validate(legacy_payload)
        except ValidationError as exc:
            raise PipelineStageError("stage2", f"planner_schema_validation_failed:{exc}") from exc

        question_like = bool(normalized_hint.get("question_like"))
        explicit_compute_action = bool(normalized_hint.get("explicit_compute_action"))
        if parsed.lane == "compute_ready" and question_like and not explicit_compute_action and not parsed.is_follow_up:
            raise PipelineStageError("stage2", "question_like_input_promoted_to_compute_ready")
        if parsed.lane == "chat_only" and parsed.computation_type is not None:
            raise PipelineStageError("stage2", "chat_only_with_computation_type")

        merged = dict(plan_dict)
        merged["lane"] = parsed.lane
        merged["query_kind"] = parsed.lane
        merged["planner_lane"] = parsed.lane
        merged["confidence"] = parsed.confidence
        merged["reasoning"] = parsed.reasoning
        merged["molecule_name"] = parsed.molecule_name
        merged["computation_type"] = parsed.computation_type
        merged["basis_set"] = parsed.basis_set
        merged["preset"] = parsed.preset
        merged["molecule_from_context"] = parsed.molecule_from_context
        merged["is_follow_up"] = parsed.is_follow_up
        merged["unknown_acronyms"] = list(parsed.unknown_acronyms)
        return merged

    def _validate_and_enrich_plan(
        self,
        plan_dict: Dict[str, Any],
        raw_text: str,
        normalized_hint: Dict[str, Any],
        *,
        repair_count: int,
        lane_lock: Optional[LaneLock] = None,
    ) -> Dict[str, Any]:
        enriched = dict(plan_dict)
        for key in (
            "question_like",
            "explicit_compute_action",
            "unknown_acronyms",
            "structure_query_candidates",
            "formula_mentions",
            "alias_mentions",
            "canonical_candidates",
            "raw_input",
            "mixed_input",
            "structures",
            "composition_kind",
            "charge_hint",
            "follow_up_mode",
            "mentioned_molecules",
            "target_scope",
            "selection_mode",
            "selection_hint",
            "selected_molecules",
            "analysis_bundle",
            "batch_request",
            "batch_size",
        ):
            if key not in enriched and normalized_hint.get(key) not in (None, [], ""):
                enriched[key] = normalized_hint.get(key)

        query_kind = _coerce_text(enriched.get("planner_lane") or enriched.get("query_kind")) or "compute_ready"
        question_like = bool(enriched.get("question_like") or normalized_hint.get("question_like"))
        explicit_compute_action = bool(
            enriched.get("explicit_compute_action") or normalized_hint.get("explicit_compute_action")
        )
        semantic_grounding_needed = bool(
            enriched.get("semantic_grounding_needed")
            or query_kind == "grounding_required"
        )
        molecule_name = _coerce_text(enriched.get("molecule_name")) or _coerce_text(enriched.get("structure_query"))
        computation_type = _coerce_text(enriched.get("computation_type")) or self._legacy_computation_type(enriched) or ""
        job_type = self._job_type_from_computation_type(computation_type)
        enriched["query_kind"] = query_kind
        enriched["planner_lane"] = query_kind
        enriched["chat_only"] = bool(query_kind == "chat_only")
        enriched["semantic_grounding_needed"] = semantic_grounding_needed
        enriched["lane_locked"] = bool(lane_lock.locked) if lane_lock is not None else False
        enriched["locked_lane"] = lane_lock.lane if lane_lock is not None else None
        enriched["question_like"] = question_like
        enriched["explicit_compute_action"] = explicit_compute_action
        enriched["explanation_intent"] = bool(query_kind == "chat_only" or (question_like and not explicit_compute_action))
        enriched["grounding_intent"] = bool(query_kind == "grounding_required")
        enriched["compute_intent"] = bool(query_kind == "compute_ready" and enriched.get("intent") != "chat")
        enriched["pipeline_enabled"] = True
        enriched["pipeline_repair_count"] = max(0, int(repair_count))
        enriched["pipeline_fallback_stage"] = None
        enriched["provider"] = _coerce_text(enriched.get("provider")) or self._choose_stage_provider() or "heuristic"
        enriched["confidence_band"] = PlanResponse.model_validate({"confidence": enriched.get("confidence", 0.0)}).confidence_band
        enriched["reasoning"] = _coerce_text(enriched.get("reasoning")) or "router-planner output"

        if query_kind == "chat_only":
            enriched["intent"] = "chat"
            enriched["job_type"] = "chat"
            enriched["structure_query"] = None
            enriched["missing_slots"] = []
            enriched["needs_clarification"] = False
            enriched["clarification_kind"] = None
        else:
            enriched["intent"] = _coerce_text(enriched.get("intent")) or job_type
            enriched["job_type"] = _coerce_text(enriched.get("job_type")) or job_type
            if molecule_name and not _coerce_text(enriched.get("structure_query")):
                enriched["structure_query"] = molecule_name
            if computation_type in {"homo", "lumo"} and not _coerce_text(enriched.get("orbital")):
                enriched["orbital"] = computation_type.upper()
            if computation_type == "esp" and not _coerce_text(enriched.get("esp_preset")):
                enriched["esp_preset"] = _coerce_text(enriched.get("preset")) or None
            if _coerce_text(enriched.get("basis_set")) and not _coerce_text(enriched.get("basis")):
                enriched["basis"] = _coerce_text(enriched.get("basis_set"))

        reasoning_notes = [str(item).strip() for item in list(enriched.get("reasoning_notes") or []) if str(item).strip()]
        if "llm-first pipeline accepted plan" not in reasoning_notes:
            reasoning_notes.append("llm-first pipeline accepted plan")
        enriched["reasoning_notes"] = reasoning_notes

        if not _coerce_text(enriched.get("normalized_text")):
            enriched["normalized_text"] = _coerce_text(normalized_hint.get("normalized_text")) or raw_text
        if not _coerce_text(enriched.get("raw_input")):
            enriched["raw_input"] = raw_text
        if query_kind == "grounding_required" and not _coerce_text(enriched.get("structure_query")):
            missing_slots = [str(item).strip() for item in list(enriched.get("missing_slots") or []) if str(item).strip()]
            if "structure_query" not in missing_slots:
                missing_slots.append("structure_query")
            enriched["missing_slots"] = missing_slots
            enriched["needs_clarification"] = True
            enriched["clarification_kind"] = _coerce_text(enriched.get("clarification_kind")) or "semantic_grounding"
        return enriched

    def _maybe_apply_shadow_mode(
        self,
        raw_text: str,
        context: Mapping[str, Any],
        normalized_hint: Dict[str, Any],
        heuristic_planner: Callable[[str, Mapping[str, Any], Dict[str, Any]], Any],
        *,
        llm_result: Dict[str, Any],
        trace: PipelineTrace,
    ) -> Dict[str, Any]:
        serve_llm = self._can_serve_llm(raw_text, context)
        trace.serve_mode = "llm" if serve_llm else "heuristic"
        if not self.shadow_mode and serve_llm:
            return llm_result

        heuristic_result = self._normalize_shadow_heuristic_result(
            raw_text,
            context,
            normalized_hint,
            heuristic_planner,
        )
        trace.stage_outputs["heuristic_shadow"] = {
            "planner_lane": heuristic_result.get("planner_lane"),
            "provider": heuristic_result.get("provider"),
            "query_kind": heuristic_result.get("query_kind"),
        }
        trace.llm_vs_heuristic_agreement = self._llm_vs_heuristic_agree(llm_result, heuristic_result)
        if serve_llm:
            return llm_result
        heuristic_result["shadow_primary"] = True
        heuristic_result["shadow_llm_lane"] = llm_result.get("planner_lane")
        heuristic_result["shadow_llm_provider"] = llm_result.get("provider")
        heuristic_result["shadow_llm_agreement"] = trace.llm_vs_heuristic_agreement
        return heuristic_result

    def _normalize_shadow_heuristic_result(
        self,
        raw_text: str,
        context: Mapping[str, Any],
        normalized_hint: Dict[str, Any],
        heuristic_planner: Callable[[str, Mapping[str, Any], Dict[str, Any]], Any],
    ) -> Dict[str, Any]:
        result = _coerce_plan_dict(heuristic_planner(raw_text, context, normalized_hint))
        query_kind = _coerce_text(result.get("planner_lane") or result.get("query_kind")) or "compute_ready"
        result["query_kind"] = query_kind
        result["planner_lane"] = query_kind
        result["lane_locked"] = bool(result.get("lane_locked") or bool(query_kind))
        result["locked_lane"] = _coerce_text(result.get("locked_lane")) or query_kind
        result["provider"] = _coerce_text(result.get("provider")) or "heuristic"
        return result

    def _llm_vs_heuristic_agree(self, llm_result: Mapping[str, Any], heuristic_result: Mapping[str, Any]) -> bool:
        llm_lane = _coerce_text(llm_result.get("planner_lane") or llm_result.get("query_kind"))
        heuristic_lane = _coerce_text(heuristic_result.get("planner_lane") or heuristic_result.get("query_kind"))
        llm_job = _coerce_text(llm_result.get("job_type"))
        heuristic_job = _coerce_text(heuristic_result.get("job_type"))
        llm_structure = _coerce_text(llm_result.get("structure_query") or llm_result.get("molecule_name"))
        heuristic_structure = _coerce_text(heuristic_result.get("structure_query") or heuristic_result.get("molecule_name"))
        return (
            llm_lane == heuristic_lane
            and llm_job == heuristic_job
            and llm_structure.lower() == heuristic_structure.lower()
        )

    def _can_serve_llm(self, raw_text: str, context: Mapping[str, Any]) -> bool:
        if not self.serve_llm:
            return False
        if self.canary_percent >= 100:
            return True
        if self.canary_percent <= 0:
            return False
        sample_key = _coerce_text(context.get("session_id")) or raw_text
        if not sample_key:
            return False
        digest = hashlib.md5(sample_key.encode("utf-8", errors="ignore")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        return bucket < self.canary_percent

    def _fallback(
        self,
        raw_text: str,
        context: Mapping[str, Any],
        normalized_hint: Dict[str, Any],
        heuristic_planner: Callable[[str, Mapping[str, Any], Dict[str, Any]], Any],
        *,
        stage: str,
        reason: str,
        repair_count: int,
    ) -> Dict[str, Any]:
        fallback_obj = heuristic_planner(raw_text, context, normalized_hint)
        fallback = _coerce_plan_dict(fallback_obj)
        query_kind = _coerce_text(fallback.get("query_kind")) or _coerce_text(normalized_hint.get("query_kind")) or "compute_ready"
        question_like = bool(fallback.get("question_like") or normalized_hint.get("question_like"))
        explicit_compute_action = bool(
            fallback.get("explicit_compute_action") or normalized_hint.get("explicit_compute_action")
        )

        fallback["query_kind"] = query_kind
        fallback["planner_lane"] = query_kind
        fallback["lane_locked"] = True
        fallback["locked_lane"] = query_kind
        fallback["question_like"] = question_like
        fallback["explicit_compute_action"] = explicit_compute_action
        fallback["explanation_intent"] = bool(query_kind == "chat_only" or (question_like and not explicit_compute_action))
        fallback["grounding_intent"] = bool(query_kind == "grounding_required")
        fallback["compute_intent"] = bool(query_kind == "compute_ready" and fallback.get("intent") != "chat")
        fallback["pipeline_enabled"] = bool(self.enabled)
        fallback["pipeline_fallback_stage"] = stage
        fallback["pipeline_repair_count"] = max(0, int(repair_count))
        fallback["fallback_reason"] = _coerce_text(fallback.get("fallback_reason")) or reason
        fallback["provider"] = _coerce_text(fallback.get("provider")) or "heuristic"

        notes = [str(item).strip() for item in list(fallback.get("notes") or []) if str(item).strip()]
        note = f"LLM pipeline fallback at {stage}: {reason}"
        if note not in notes:
            notes.append(note)
        fallback["notes"] = notes

        reasoning_notes = [str(item).strip() for item in list(fallback.get("reasoning_notes") or []) if str(item).strip()]
        trace = f"pipeline fallback reason={reason}"
        if trace not in reasoning_notes:
            reasoning_notes.append(trace)
        fallback["reasoning_notes"] = reasoning_notes

        if not _coerce_text(fallback.get("normalized_text")):
            fallback["normalized_text"] = _coerce_text(normalized_hint.get("normalized_text")) or raw_text
        if not _coerce_text(fallback.get("raw_input")):
            fallback["raw_input"] = raw_text
        return fallback

    def _legacy_computation_type(self, plan_dict: Mapping[str, Any]) -> Optional[str]:
        job_type = _coerce_text(plan_dict.get("job_type") or plan_dict.get("intent"))
        orbital = _coerce_text(plan_dict.get("orbital")).upper()
        if orbital == "HOMO":
            return "homo"
        if orbital == "LUMO":
            return "lumo"
        mapping = {
            "orbital_preview": "custom",
            "esp_map": "esp",
            "geometry_optimization": "optimization",
            "single_point": "energy",
            "analyze": "custom",
            "geometry_analysis": "custom",
            "partial_charges": "custom",
            "chat": None,
        }
        return mapping.get(job_type) if job_type in mapping else None

    def _legacy_preset(self, plan_dict: Mapping[str, Any]) -> Optional[str]:
        preset = _coerce_text(plan_dict.get("esp_preset") or plan_dict.get("preset")).lower()
        if preset in {"acs", "rsc", "custom"}:
            return preset
        return None

    def _job_type_from_computation_type(self, computation_type: str) -> str:
        mapping = {
            "homo": "orbital_preview",
            "lumo": "orbital_preview",
            "esp": "esp_map",
            "optimization": "geometry_optimization",
            "energy": "single_point",
            "frequency": "analyze",
            "custom": "analyze",
        }
        return mapping.get((computation_type or "").lower(), "analyze")
