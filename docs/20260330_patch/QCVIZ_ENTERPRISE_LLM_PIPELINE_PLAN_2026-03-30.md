# QCViz Enterprise LLM Pipeline Plan

Date: 2026-03-30

## Final Target

QCViz adopts a 4-stage `LLM-first + deterministic guard` architecture.

1. `Ingress Normalize + Annotate`
2. `Router-Planner`
3. `Grounding Merge`
4. `Execution Guard`

This is the production target for the web-first runtime. MCP remains out of scope for this pipeline plan.

## Source of Truth

- `Router-Planner` or heuristic fallback owns the final lane.
- `normalizer.py` remains an annotation module and fallback helper.
- `Grounding Merge` is the only semantic outcome merge point.
- `Execution Guard` is the last authority before compute submission.
- `LaneLock` prevents per-turn lane flips.

## Runtime Contract

### Stage 1: Ingress Normalize + Annotate

- Default path: deterministic normalization and annotation
- Optional thin rewrite: noisy mixed-language or high-corruption input only
- Output: `IngressResult`

### Stage 2: Router-Planner

- Single structured-output LLM call
- Responsibilities:
  - lane classification
  - slot extraction
  - follow-up interpretation
  - confidence and reasoning
- Repair: 1 retry maximum
- Failure path: heuristic fallback
- Output: `PlanResult`

### Stage 3: Grounding Merge

- Pure deterministic merge of:
  - planner lane
  - MolChat candidates
  - lock state
  - confidence threshold policy
- Output:
  - `grounded_direct_answer`
  - `single_candidate_confirm`
  - `grounding_clarification`
  - `custom_only_clarification`
  - `compute_ready`
  - `chat_only`

### Stage 4: Execution Guard

- Pure deterministic guard
- Rejects compute when:
  - structure is unresolved
  - clarification is still required
  - payload is incomplete
- Output: `ExecutionDecision`

## Rollout Flags

- `QCVIZ_PIPELINE_ENABLED`
- `QCVIZ_PIPELINE_STAGE1_LLM`
- `QCVIZ_PIPELINE_STAGE2_LLM`
- `QCVIZ_PIPELINE_SHADOW_MODE`
- `QCVIZ_PIPELINE_SERVE_LLM`
- `QCVIZ_PIPELINE_CANARY_PERCENT`
- `QCVIZ_PIPELINE_FORCE_HEURISTIC`
- `QCVIZ_PIPELINE_REPAIR_MAX`

Legacy `QCVIZ_LLM_PIPELINE_*` flags are still accepted for compatibility during migration.

## Deterministic Guarantees

- explanation-style semantic requests never auto-submit compute
- unresolved acronym compute requests never bypass grounding
- follow-up parameter-only requests reuse locked structure when context exists
- lane flips raise `LaneLockViolation`
- fallback never bounces back into the LLM path within the same turn

## Observability

Pipeline traces emit:

- ingress output
- router result
- shadow heuristic result when enabled
- locked lane
- fallback stage and reason
- repair count
- total latency

Tracked counters/histograms include:

- `pipeline.stage1.rewrite_rate`
- `pipeline.stage2.main_success_rate`
- `pipeline.stage2.repair_success_rate`
- `pipeline.stage2.fallback_rate`
- `pipeline.lane_distribution.*`
- `pipeline.guard_rejection_rate`
- `pipeline.lane_lock_violation_rate`
- `pipeline.e2e_latency_ms`
- `pipeline.llm_vs_heuristic_agreement.*`

## Benchmark Gate

The release gate now expects benchmark assets across:

- semantic explanation
- semantic compute
- direct molecule compute
- follow-up parameter-only
- red-team / adversarial inputs

Current asset scaffolding lives under `tests/assets/` and the aggregate variant count is designed to exceed 100.

## Migration Status

### Implemented

- typed contracts for ingress / planner / grounding / execution
- `LaneLock`
- `grounding_merge.py`
- `execution_guard.py`
- pipeline trace emission
- shadow-mode comparison hook
- route-level consumption of deterministic grounding and guard results

### Still to Mature

- remove remaining decision-like reliance on `normalizer` fields from more legacy call sites
- complete rollout automation for shadow and canary in deployed environments
- turn benchmark assets into a full scored offline report
- finalize operator runbooks and release discipline

## Non-Goals

- no MCP-native runtime rewrite
- no multi-agent orchestration
- no extra semantic-expansion network round trip
- no LLM-controlled compute submission
