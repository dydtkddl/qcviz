# QCViz Patch Execution Status

Date: 2026-03-30

## Current State

`version03` is now in a 4-stage intermediate-to-mature state:

1. `Ingress Normalize + Annotate`
2. `Router-Planner`
3. `Grounding Merge`
4. `Execution Guard`

The main remaining work is no longer core architecture invention. It is completion work:

- removing remaining second-brain behavior
- operationalizing rollout and shadow mode
- hardening benchmark gates
- keeping docs and runbooks synchronized

## Completed in This Round

### 1. Pipeline runtime aligned to 4-stage structure

- separate semantic expansion is no longer executed as a network stage
- router-planner is the only primary LLM interpretation step
- stage1 rewrite is now gated to noisy input patterns
- shadow/canary serve logic hooks were added to the pipeline coordinator

Files:

- `src/qcviz_mcp/llm/pipeline.py`

### 2. Decision authority moved further away from the normalizer

- `_safe_plan_message()` now treats planner lane as authoritative when present
- route enrichment no longer lets `normalize_user_text()` silently overwrite a planner lane
- explicit structure extraction now uses annotation-style signals instead of raw `query_kind` branching

Files:

- `src/qcviz_mcp/web/routes/compute.py`

### 3. Observability was extended from logging to metric-shaped signals

- pipeline traces now emit:
  - repair count
  - serve mode
  - llm-vs-heuristic agreement
  - stage latencies
- in-process metrics now support:
  - counter increments
  - histogram-style observations
- guard actions and lane-lock violations are counted explicitly

Files:

- `src/qcviz_mcp/observability.py`
- `src/qcviz_mcp/llm/trace.py`
- `src/qcviz_mcp/llm/lane_lock.py`
- `src/qcviz_mcp/llm/execution_guard.py`

### 4. Benchmark scaffolding was expanded

Added benchmark assets for:

- direct molecule compute
- follow-up parameter-only
- red-team / adversarial inputs

The aggregate asset suite is now intended to exceed 100 benchmark variants when combined with the existing semantic explanation and semantic compute sets.

Files:

- `tests/assets/direct_molecule_compute_benchmark.json`
- `tests/assets/follow_up_parameter_only_benchmark.json`
- `tests/assets/red_team_benchmark.json`
- `tests/test_pipeline_benchmark_assets.py`

### 5. Docs were synchronized to the 4-stage target

- 5-stage language was removed from the core pipeline plan
- rollout flags and benchmark gate expectations were updated

Files:

- `docs/20260330_patch/QCVIZ_ENTERPRISE_LLM_PIPELINE_PLAN_2026-03-30.md`

### 6. Follow-up reuse and batch multi-molecule regressions were closed

- parameter-only follow-up requests now reuse the locked session structure before any semantic-grounding early return can short-circuit the flow
- multi-molecule paragraph requests no longer get reinterpreted as continuation-style semantic grounding just because they contain analysis terms like `HOMO`, `LUMO`, or `ESP`
- chat-side missing-slot detection now treats `selected_molecules + batch_request` as structure-ready, preventing false `no_structure` clarification loops
- heuristic batch planning now suppresses accidental `follow_up_mode=add_analysis` on fresh multi-molecule paragraphs

Files:

- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/agent.py`

### 7. Targeted regression suite is green again

Validated shards:

- `tests/test_compute_api.py` → `19 passed`
- `tests/test_chat_api.py -k "semantic_descriptor or unknown_acronym or concept_question or analysis_only_followup or batch_multi_molecule or follow_up_reuses_same_session_structure or explicit_molecule_overrides_previous_session_structure"` → `13 passed`
- `tests/v3/unit/test_pipeline.py`
- `tests/test_pipeline_benchmark_assets.py`
- `tests/test_semantic_grounding_policy.py`
- `tests/test_chat_semantic_grounded_chat.py` → combined `44 passed`
- `tests/test_chat_playwright.py`
- `tests/test_runtime_health.py`
- `tests/v3/unit/test_molchat_client.py`
- `tests/v3/unit/test_structure_resolver.py` → combined `29 passed`

Current targeted validation total: `105 passed`

## Still Open

### 1. Full normalizer authority removal

`normalizer.py` still computes `query_kind`, `chat_only`, and `semantic_grounding_needed`.
That is acceptable as fallback support, but it should continue to shrink toward annotation-only semantics.

### 2. Production rollout execution

The code now supports shadow/canary semantics, but real deployment rollout still requires:

- environment flag configuration
- disagreement logging review
- provider-level monitoring in staging/production

### 3. Benchmark scoring

The asset suite exists, but an offline scorecard with:

- lane accuracy
- grounding outcome accuracy
- fallback rate
- perturbation stability

still needs to be formalized as a report step.

### 4. Remaining authority cleanup

The main architectural risk is now narrower:

- `normalizer.py` still emits decision-like fields that are useful for fallback and shadow comparison, but should keep shrinking toward annotation-only semantics
- some route-level compatibility code still carries transitional planner/normalizer merge behavior for backwards compatibility

## Recommended Next Sequence

1. Run targeted regression plus the new benchmark asset checks
2. Audit remaining `normalize_user_text()` decision-like consumers
3. Turn on shadow mode in staging
4. Review disagreement traces
5. Promote to canary

## Product Direction Guardrail

This patch line continues to assume:

- web-first direct orchestration
- LLM-first interpretation
- deterministic submit guard
- heuristic fallback as a permanent safety net

It does **not** change the broader architecture decision:
QCViz remains a web-first computational chemistry platform with optional MCP compatibility, not an MCP-native runtime product.
