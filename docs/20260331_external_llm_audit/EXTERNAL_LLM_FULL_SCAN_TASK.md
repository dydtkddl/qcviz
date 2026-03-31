# QCViz External LLM Full-Scan Task

Date: `2026-03-31`  
Project: `QCViz-MCP / version03`  
Audit mode: `scan-first, score-first, fix-plan-first`  

## Bundle

- Zip bundle: `D:\20260305_양자화학시각화MCP서버구축\version03\docs\20260331_external_llm_audit\QCVIZ_CORE_EXTERNAL_SCAN_BUNDLE_2026-03-31.zip`
- Extracted bundle: `D:\20260305_양자화학시각화MCP서버구축\version03\docs\20260331_external_llm_audit\QCVIZ_CORE_EXTERNAL_SCAN_BUNDLE_2026-03-31`
- Manifest: `D:\20260305_양자화학시각화MCP서버구축\version03\docs\20260331_external_llm_audit\bundle_manifest.txt`

## Your Role

You are acting as an external principal engineer and scientific QA reviewer for a quantum chemistry chat-and-compute service.

Your job is not to praise the codebase. Your job is to find what is still wrong, what is fragile, what is misleading, what is scientifically risky, what is operationally unsafe, and what is likely to break in live usage even if current tests pass.

Assume there are still unidentified issues.

Do not assume a green test suite means the product is correct.

## Primary Goal

Perform a full static audit of the provided core bundle and produce:

1. a weighted scorecard,
2. a prioritized issue inventory,
3. root-cause hypotheses,
4. specific gap analysis for unresolved live anomalies,
5. a remediation plan that should happen before the 50-case live scenario campaign is trusted.

This is an audit-first task.  
Do not start by proposing cosmetic refactors.  
Start by finding correctness, routing, identity, cache, visualization, and scientific integrity failures.

## Important Context

This project is a chat-driven quantum chemistry application that:

- interprets user text,
- decides whether the turn is `chat`, `clarification`, or `compute`,
- resolves molecule names through local aliases, MolChat, and PubChem,
- launches PySCF-based jobs,
- stores job/results state,
- streams updates to a web UI,
- renders orbitals / ESP / density / geometry outputs,
- supports same-session follow-up requests like:
  - `그거 HOMO 보여줘`
  - `ESP도`
  - `method를 PBE0로 바꿔`

The current bundle includes:

- runtime source code,
- tests,
- prior audit outputs,
- Playwright live audit harnesses,
- live audit result JSONs.

## What To Score

Score the system from the following perspectives.  
Use a 0-10 score for each category, then compute the weighted total out of 100.

| Category | Weight | What to inspect |
|---|---:|---|
| Routing and planner fidelity | 15 | Whether user intent becomes the correct lane: `chat`, `clarify`, `compute`, follow-up, parameter-only update |
| Semantic grounding and alias resolution | 15 | Acronym disambiguation, typo correction, alias preference, descriptor grounding, candidate stability |
| Structure identity integrity | 15 | Whether the same molecule identity survives end-to-end across name, CID, SMILES, SDF, geometry, viewer payload, cache, and follow-up |
| Visualization correctness | 15 | Whether rendered structure/orbital/ESP truly corresponds to the requested molecule and latest result |
| Continuation and session memory | 10 | Same-session pronoun follow-up, short follow-up, parameter-only follow-up, state persistence, session resets |
| Result contract and job lifecycle | 10 | Whether completed jobs produce correct terminal results, whether UI and backend agree on completion and payload |
| Result caching and reuse architecture | 10 | Whether repeated or near-identical requests should reuse previous results instead of recomputing, and whether the project is ready for a RAG-like result retrieval layer |
| Test realism and harness validity | 5 | Whether tests are checking the right thing, whether harness logic can mask bugs or produce false confidence |
| Production robustness and observability | 5 | Health checks, boot drift, cache drift, logging, traceability, failure visibility |
| Scientific safety and trustworthiness | 10 | Whether compute defaults, structure resolution, and user-facing explanations can mislead users scientifically |

## How You Must Judge

- Be conservative.
- Prefer evidence from code paths and test paths over optimistic interpretation.
- If something looks correct in tests but suspicious in runtime architecture, call that out.
- If a behavior appears nondeterministic, say so explicitly.
- If you are inferring rather than directly observing, label it as `Inference`.
- If you think a bug is likely hidden behind caching or stale viewer state, say that directly.
- Do not fabricate live behavior that is not supported by the bundle.

## High-Priority Audit Themes

Pay special attention to these themes.

### 1. Structure identity drift

Audit whether the selected molecule can silently change or degrade across:

- clarification selection,
- MolChat/PubChem resolution,
- canonical naming,
- CID/SMILES/SDF conversion,
- geometry generation,
- job submission,
- result persistence,
- viewer payload,
- follow-up reuse.

The system must not accept one molecule and visualize another.

### 2. Visualization-object mismatch

Check whether the displayed molecular structure can differ from:

- the selected candidate,
- the actual compute input,
- the finalized result record,
- the job metadata,
- the cube/geometry artifact used by the viewer.

This is critical because a user-reported anomaly suggests that a TNT-related flow can end up visualizing a toluene-like structure without nitro groups even after a `2,4,6-Trinitrotoluene` selection.

### 3. Semantic explanation vs compute lane confusion

Check whether question-like prompts are being forced into compute paths when they should remain explanatory.

Example class:

- `TNT에 들어가는 주물질이 뭐지?`

This type of prompt may need:

- explanation-first behavior,
- semantic candidate clarification,
- no automatic compute until the intent is clear.

### 4. Alias correction parity failure

Investigate whether local resolver behavior is weaker than the standalone MolChat UI.

Known example class:

- `Aminobutylic acid`

Standalone MolChat appears able to autocorrect this toward `gamma-aminobutyric acid`, while the QCViz compute path may still fail or behave inconsistently.

You must check:

- where local autocorrect exists,
- whether it is applied in every route,
- whether compute-ready, clarification, and suggestion paths all see the same corrected query,
- whether the correction survives through final structure selection.

### 5. Same-request result reuse

Evaluate whether the system should detect that a new request is materially the same as an already completed calculation and return the prior result immediately instead of running a new calculation.

This is intentionally important.

You must assess:

- whether current result persistence is rich enough for retrieval,
- whether disk cache / job cache / conversation state could support retrieval,
- what metadata is missing,
- what a minimal RAG-like retrieval layer for prior calculations would require,
- what risks exist if retrieval is added incorrectly.

At the end of your report, include a dedicated section titled:

`Prior Result Reuse / Retrieval Layer Feasibility`

and discuss whether the project should store completed calculations in a form suitable for direct retrieval and re-display.

## Seed Anomalies You Must Investigate

Treat these as unresolved unless the bundle proves otherwise.

1. `TNT에 들어가는 주물질이 뭐지?`
   - may be routed as compute or compute-adjacent too early,
   - may ground to `2,4,6-Trinitrotoluene`,
   - may later visualize a structure that appears to be missing nitro groups.

2. `Aminobutylic acid`
   - may fail in the QCViz compute path,
   - while standalone MolChat UI appears to autocorrect to `gamma-aminobutyric acid`.

3. repeated requests that are effectively identical
   - may trigger full recomputation instead of returning prior artifacts,
   - may indicate missing retrieval/indexing logic.

4. follow-up requests that depend on session memory
   - must be checked for hidden drift between textual state and actual resolved structure state.

## Files That Matter Most

Prioritize these files first.

### Boot and runtime entry

- `a.sh`
- `src/qcviz_mcp/web/app.py`
- `src/qcviz_mcp/web/runtime_info.py`

### Chat and routing

- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/llm/pipeline.py`
- `src/qcviz_mcp/llm/grounding_merge.py`
- `src/qcviz_mcp/llm/execution_guard.py`
- `src/qcviz_mcp/llm/lane_lock.py`
- `src/qcviz_mcp/web/conversation_state.py`

### Structure resolution

- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`
- `src/qcviz_mcp/services/ko_aliases.py`
- `src/qcviz_mcp/services/sdf_converter.py`
- `src/qcviz_mcp/services/ion_pair_handler.py`

### Compute and results

- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `src/qcviz_mcp/compute/job_manager.py`
- `src/qcviz_mcp/compute/disk_cache.py`
- `src/qcviz_mcp/web/job_backend.py`
- `src/qcviz_mcp/web/redis_job_store.py`
- `src/qcviz_mcp/web/result_explainer.py`

### Frontend contract

- `src/qcviz_mcp/web/static/chat.js`
- `src/qcviz_mcp/web/static/results.js`
- `src/qcviz_mcp/web/static/viewer.js`
- `src/qcviz_mcp/web/static/app.js`
- `src/qcviz_mcp/web/templates/index.html`

### Audit harness and tests

- `tests/test_chat_api.py`
- `tests/test_structure_extraction.py`
- `tests/test_chat_playwright.py`
- `tests/test_chat_semantic_grounded_chat_playwright.py`
- `tests/v3/unit/test_structure_resolver.py`
- `output/playwright_live_restart_20260330/run_live_audit.py`
- `output/playwright_live_restart_20260330_50/run_live_audit_50.py`
- `output/playwright_live_restart_20260330/live_case_results.json`
- `output/playwright_live_restart_20260330_50/live_case_results_50.json`

## Required Output Format

Your answer must contain the following sections in this exact order.

### 1. Executive Summary

- top 5 findings,
- total weighted score,
- overall release confidence.

### 2. Weighted Scorecard

Provide the full score table with:

- category,
- raw score 0-10,
- weight,
- weighted score,
- short reason.

### 3. Prioritized Issue Inventory

List each issue with:

- `severity`: `P0`, `P1`, `P2`, or `P3`
- `confidence`: `high`, `medium`, or `low`
- affected files
- symptom
- likely root cause
- why it matters to users
- whether it can invalidate test confidence

### 4. Deep Dives

Provide separate subsections for:

- `TNT structure / visualization mismatch`
- `Aminobutylic acid correction gap`
- `Session follow-up / pronoun memory drift`
- `Terminal result vs viewer contract consistency`

### 5. Prior Result Reuse / Retrieval Layer Feasibility

You must discuss:

- whether repeated calculations should be reused,
- what entity key should identify a prior calculation,
- what metadata should be persisted,
- whether current disk/job/session cache is sufficient,
- what a safe phased design would look like,
- what failure modes would appear if naive retrieval is added.

### 6. Test Gap Analysis

Explain:

- which classes of bugs are already covered,
- which classes are under-tested,
- which currently passing tests may still miss real failures,
- what 15 additional scenario ideas should be added before trusting the 50-case live campaign.

### 7. Remediation Order

Produce a step-by-step order of fixes:

- quick wins,
- structural fixes,
- contract hardening,
- result retrieval groundwork,
- final live validation order.

## Constraints

- Do not say “looks good overall” unless your score and issue inventory truly justify it.
- Do not hide uncertainty.
- Do not treat test green as equivalent to product correct.
- Do not suggest broad rewrites unless a targeted repair is impossible.
- Use file paths exactly as they appear in the bundle.
- If you think a bug is likely caused by stale cache, stale state, or viewer reuse, name that explicitly.

## Final Instruction

Your mission is to help us find the still-unidentified problems before we trust the larger 50-scenario live campaign.

Audit aggressively.
Score conservatively.
Prioritize user-truthfulness, structure identity integrity, and result correctness over convenience.
