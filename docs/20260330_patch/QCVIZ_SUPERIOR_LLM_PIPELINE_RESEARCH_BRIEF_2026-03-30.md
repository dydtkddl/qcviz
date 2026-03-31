# QCViz Superior LLM Research Brief

## Copy-Paste Prompt For a Stronger LLM

You are acting as a senior AI systems researcher and staff-level LLM architect.

Your job is to produce a **decision-quality, implementation-ready design review and benchmark study** for an existing production-oriented conversational quantum chemistry web platform named **QCViz**.

This is **not** a greenfield brainstorming task.
You must study the provided project context, reason about the actual architecture, and return a **concrete, enterprise-grade recommendation** for how to build and operate a **multi-stage LLM-first prompt pipeline with deterministic fallback**.

You must assume:

- the current codebase already exists
- the system is already partially working
- we do **not** want hand-wavy advice
- we do **not** want benchmark-case hardcoding
- we do **not** want compute safety delegated to the LLM
- we do **not** want “just use a bigger model” as the answer

Your job is to investigate the latest and strongest practical patterns from:

- commercial LLM production system design
- prompt-chain / orchestrator / agent pipeline practice
- structured-output and function-calling reliability guidance
- prompt-repair / retry / fallback design
- entity-grounding and clarification UX
- LangChain / LangGraph / LlamaIndex / OpenAI / Anthropic / Google / Microsoft / community best practice
- recent journal, preprint, engineering blog, official docs, and community gold-rule style discussions

You must return a **final recommendation**, not just options.

---

## 1. Project Context

QCViz is a **web-first conversational quantum chemistry platform** for experimental chemists.

The intended user experience is:

1. a user asks in natural language through the web UI
2. the system interprets the intent
3. the system grounds the molecular structure, partly via MolChat
4. the system selects an appropriate quantum chemistry action
5. the real calculation is executed using PySCF
6. the result is returned with browser-based visualization and conversational follow-up

The core product goal is:

**experimentalists should be able to access quantum chemistry in one browser workflow without installation, without deep computational chemistry expertise, and without manually stitching together structure lookup, input generation, execution, and visualization**

This project is **not** fundamentally an MCP-native project.
It is primarily a **web-first direct-orchestration product** with an optional MCP-compatible layer.

That positioning is already intentionally fixed.
Do not recommend redesigning the whole product around MCP.

---

## 2. Current Architecture

The current system has these major layers:

- `normalizer.py`
  - rule-based normalization
  - current routing heuristics
  - semantic descriptor detection
  - acronym handling
  - follow-up detection

- `agent.py`
  - current planning entrypoint
  - heuristic planner
  - optional OpenAI / Gemini planning paths

- `chat.py`
  - semantic chat handling
  - clarification UI construction
  - grounded direct answer vs clarification behavior

- `compute.py`
  - `_safe_plan_message()`
  - payload merging
  - execution preflight
  - deterministic guard before actual compute

- `pipeline.py`
  - newly introduced LLM-first coordinator skeleton
  - intended to become the main interpretation pipeline
  - designed to fall back deterministically to the current heuristic path

- MolChat
  - semantic grounding engine
  - interpret/resolve style structure grounding support

- PySCF
  - the real computation backend

The current design direction is:

- main path: **LLM-first**
- fallback path: **existing rule-based pipeline**
- execution safety: **deterministic guard**

---

## 3. Current Pipeline Direction

The currently intended multi-stage architecture is:

1. **Stage 1: Ingress Rewrite**
   - typo cleanup
   - spacing cleanup
   - noisy mixed-language cleanup
   - preserve scientific tokens

2. **Stage 2: Semantic Expansion**
   - produce short paraphrase candidates
   - help semantic grounding and explanation retrieval
   - must not invent action intent

3. **Stage 3: Action Planner**
   - classify into
     - `chat_only`
     - `grounding_required`
     - `compute_ready`
   - extract slots and produce a structured plan

4. **Stage 4: Grounding Decision**
   - combine planner result and MolChat grounding result
   - produce one final semantic outcome:
     - `grounded_direct_answer`
     - `single_candidate_confirm`
     - `grounding_clarification`
     - `custom_only_clarification`
     - `compute_ready`

5. **Execution Guard**
   - deterministic
   - no unresolved semantic query may reach compute
   - no explanation query may submit compute
   - no structure-unlocked compute submit

### Critical Policy

We want:

- **LLM-first UX**
- **deterministic fallback**
- **no wobbling**

That means:

- each stage should get at most one repair attempt after the main attempt
- if a stage still fails, the turn should drop to heuristic fallback
- once fallback is triggered, the turn should not bounce back into the LLM path
- once a lane family is chosen in a turn, it should not flip
  - `chat_only -> compute_ready` is forbidden
  - `grounding_required -> compute_ready before structure lock` is forbidden

---

## 4. What We Need From You

We want you to research and produce the **best possible enterprise-grade solution** for this exact situation.

You must answer these questions:

1. Is the current 5-stage design fundamentally correct?
2. What should be changed to make it actually production-mature?
3. Which stages should truly be LLM-driven, and which should remain deterministic?
4. What are the strongest modern benchmark patterns for:
   - query rewrite
   - semantic routing
   - action planning
   - repair prompts
   - fallback design
   - explanation-vs-action separation
   - acronym disambiguation
   - entity grounding
5. What are the strongest “gold rules” from recent industry/community practice?
6. What are the recommended latency and retry budgets?
7. What observability should exist before we turn this on broadly?
8. What benchmark suite should we use to prove this pipeline is mature?
9. What are the biggest design mistakes or blind spots in the current direction?

---

## 5. Investigation Scope

You must explicitly investigate and synthesize patterns from:

- OpenAI official docs and engineering guidance
- Anthropic official docs and tool-use / MCP / agent patterns
- Google Gemini official docs on structured outputs and function calling
- Microsoft / Azure / Foundry / Copilot-style agent orchestration guidance
- LangChain / LangGraph production pipeline patterns
- LlamaIndex or equivalent retrieval-orchestration design
- community best-practice posts from high-signal engineering sources
- recent journal or preprint style work where relevant
- prompt-repair / schema-validation / structured retry literature

You must distinguish:

- official guidance
- production engineering convention
- community heuristic
- speculative recommendation

If a recommendation is speculative, label it as speculative.

---

## 6. Hard Constraints

You must respect all of these:

- do not recommend benchmark-specific hardcoding
- do not recommend molecule-specific whitelist logic
- do not recommend compute submission before structure lock
- do not recommend turning every route decision into unconstrained free-form LLM output
- do not recommend dropping the deterministic execution guard
- do not recommend a full platform rewrite before incremental rollout
- do not assume MCP-first architecture
- do not answer at a vague strategy level only

---

## 7. Required Deliverables

Your final answer must contain all of the following:

### A. Executive Judgment
- Is the current direction correct or not?
- What is your final recommendation?

### B. Production Architecture
- final stage architecture
- stage responsibilities
- stage inputs and outputs
- what stays deterministic
- what is LLM-driven

### C. Prompt Design
- prompt draft for each stage
- repair prompt for each stage
- explicit forbidden behaviors for each stage

### D. Schema Design
- JSON schema or typed contract for each stage
- fields that are mandatory vs optional
- cross-stage invariants

### E. Retry / Repair / Fallback Matrix
- main attempt
- repair attempt
- escalation condition
- fallback condition
- turn-level lane lock behavior

### F. Observability
- metrics
- logs
- trace fields
- shadow-mode rollout design
- offline vs online evaluation plan

### G. Benchmark Plan
- benchmark datasets
- perturbation tests
- anti-hardcode tests
- acceptance criteria
- red-team cases

### H. Code Patch Design
- exact modules to change
- change order
- safest migration sequence
- feature-flag strategy

### I. Risk Review
- what can still fail
- what user experience issues are most likely
- where the current design is still weak

---

## 8. Required Output Style

Return the answer as a structured engineering report with these sections:

1. Executive Summary
2. Evaluation of Current Direction
3. Recommended Final Architecture
4. Stage-by-Stage Prompt Design
5. Stage Schemas
6. Retry / Repair / Fallback Matrix
7. Observability and Rollout
8. Benchmark and Red-Team Plan
9. Code Patch Design
10. Risks and Tradeoffs
11. Final Recommendation

Use tables where useful.
Be concrete.
Do not give a shallow product-manager answer.

---

## 9. Current Product Issues To Keep In Mind

The current system has struggled with cases like:

- explanation-style semantic questions being accidentally treated like compute requests
- unknown acronym compute requests trying to resolve too early
- semantic descriptor queries surfacing generic fallback options
- raw descriptive phrases reviving as fake structure options
- single high-confidence grounding results still going through awkward confirmation UX
- follow-up parameter changes being misrouted into semantic grounding
- direct molecule requests being over-blocked by conservative routing

Representative examples:

- `MEA라는 물질이 뭐야?`
- `MEA HOMO 보여줘`
- `TNT에 들어가는 주물질이 뭐지?`
- `main component of TNT`
- `Tell me about MEA`
- `Render ESP map for acetone using ACS preset`
- `basis만 더 키워봐`
- `benzene HOMO 보여줘`

These are **benchmark cases**, not hardcoding targets.
Your solution must generalize beyond them.

---

## 10. Raw Code Attachments

Below are relevant raw code excerpts. Use them as concrete implementation context.

### Attachment A: `src/qcviz_mcp/llm/pipeline.py`

```python
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Type, TypeVar

from pydantic import BaseModel

from qcviz_mcp.llm.normalizer import normalize_user_text
from qcviz_mcp.llm.schemas import (
    GroundingOutcome,
    IngressRewriteResult,
    PlanResponse,
    SemanticExpansionResult,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER = "grounded_direct_answer"
SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM = "single_candidate_confirm"
SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION = "grounding_clarification"
SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION = "custom_only_clarification"
SEMANTIC_OUTCOME_COMPUTE_READY = "compute_ready"

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
        repair_max: Optional[int] = None,
    ) -> None:
        ...

    def execute(
        self,
        message: str,
        context: Optional[Mapping[str, Any]],
        *,
        heuristic_planner: Callable[[str, Mapping[str, Any], Dict[str, Any]], Any],
        llm_planner: Callable[[str, Dict[str, Any], Mapping[str, Any]], Any],
    ) -> Dict[str, Any]:
        ...
```

### Attachment B: `src/qcviz_mcp/llm/agent.py`

```python
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
        self._prompt_pipeline = QCVizPromptPipeline(
            provider=self.provider,
            openai_api_key=self.openai_api_key,
            openai_model=self.openai_model,
            gemini_api_key=self.gemini_api_key,
            gemini_model=self.gemini_model,
        )

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0, "normalized_text": ""}, provider="heuristic")

        if self._prompt_pipeline.is_enabled():
            try:
                pipeline_result = self._prompt_pipeline.execute(
                    text,
                    context or {},
                    heuristic_planner=lambda msg, ctx, normalized_hint: self._heuristic_plan(
                        msg,
                        context=dict(ctx or {}),
                        normalized=normalized_hint,
                    ),
                    llm_planner=lambda msg, stage_payload, ctx: self._plan_with_llm_preference(
                        msg,
                        normalized=dict(stage_payload.get("normalized_hint") or normalize_user_text(msg)),
                        context=dict(ctx or {}),
                    ),
                )
                provider = str(pipeline_result.get("provider") or "heuristic").strip() or "heuristic"
                return self._coerce_plan(pipeline_result, provider=provider)
            except Exception as exc:
                logger.warning("LLM-first pipeline failed; using legacy planner: %s", exc)

        normalized = normalize_user_text(text)
        ...
```

### Attachment C: `src/qcviz_mcp/llm/normalizer.py`

```python
def analyze_query_routing(
    text: str,
    *,
    structure_analysis: Optional[Dict[str, Any]] = None,
    semantic_info: Optional[Dict[str, Any]] = None,
    follow_up_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    ...
    question_like = bool(has_terminal_question_mark or has_explanation_phrase)
    explicit_compute_action = bool(_EXPLICIT_COMPUTE_ACTION_RE.search(normalized_text))
    unknown_acronyms = _extract_unknown_acronyms(normalized_text)
    ...
    chat_only = bool(
        question_like
        and not explicit_compute_action
        and not analysis_bundle
        and (
            has_explanation_phrase
            or has_terminal_question_mark
            or bool(unknown_acronyms and not direct_molecule_like)
        )
    )

    semantic_grounding_needed = bool(semantic_info.get("semantic_descriptor"))
    if follow_up_analysis.get("follow_up_mode"):
        semantic_grounding_needed = False
    if chat_only and unknown_acronyms and question_like:
        semantic_grounding_needed = True
    if unknown_acronyms and explicit_compute_action:
        semantic_grounding_needed = True

    query_kind = "compute_ready"
    if chat_only:
        query_kind = "chat_only"
    elif semantic_grounding_needed:
        query_kind = "grounding_required"
    ...
```

### Attachment D: `src/qcviz_mcp/web/routes/chat.py`

```python
SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER = "grounded_direct_answer"
SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM = "single_candidate_confirm"
SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION = "grounding_clarification"
SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION = "custom_only_clarification"


def _determine_semantic_chat_outcome(
    plan: Optional[Mapping[str, Any]],
    candidates: List[Mapping[str, Any]],
) -> str:
    del plan
    if len(candidates) == 1:
        candidate = candidates[0]
        confidence = float(candidate.get("confidence") or 0.0)
        if confidence >= 0.85:
            return SEMANTIC_OUTCOME_GROUNDED_DIRECT_ANSWER
        return SEMANTIC_OUTCOME_SINGLE_CANDIDATE_CONFIRM
    if candidates:
        return SEMANTIC_OUTCOME_GROUNDING_CLARIFICATION
    return SEMANTIC_OUTCOME_CUSTOM_ONLY_CLARIFICATION
```

### Attachment E: `src/qcviz_mcp/web/routes/compute.py`

```python
def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    message_normalization = normalize_user_text(message or "")
    ...
    agent = get_qcviz_agent()
    with track_operation("web.plan_message", parameters={"message": message[:120] if message else ""}) as obs:
        if agent is not None:
            try:
                if hasattr(agent, "plan") and callable(agent.plan):
                    planned = _enrich_plan(_coerce_plan_to_dict(agent.plan(message)))
                    ...
                    return planned
            except Exception as exc:
                ...
        planned = _enrich_plan(_heuristic_plan(message, payload=payload))
        ...
        return planned


def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    ...

    if data["job_type"] not in {"resolve_structure"}:
        if not has_batch and not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec") or data.get("structures")):
            raise HTTPException(
                status_code=400,
                detail="Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text.",
            )
```

---

## 11. Final Instruction

Do not give me a vague overview.
I want a **serious, concrete, benchmark-aware architecture review** that I can use to guide the next implementation phase of this exact codebase.

If you think the current direction is wrong, say so directly and explain why.
If you think it is broadly right but immature, say exactly what is missing.
If you recommend a final design, make it operationally credible.

Your answer should be good enough that an engineering team could execute Phase 2 to Phase 4 from it.
