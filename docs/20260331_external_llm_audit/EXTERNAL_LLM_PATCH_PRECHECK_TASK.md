# QCViz Patch-Precheck Task for External LLM

Date: `2026-03-31`  
Project: `QCViz-MCP / version03`  
Task mode: `pre-patch diagnosis, root-cause analysis, remediation design`  

## Mission

You are not being asked to write code immediately.

You are being asked to act as an external senior reviewer who must:

1. inspect a specific cluster of live issues,
2. identify the real root causes,
3. distinguish UI symptoms from backend causes,
4. recommend the safest patch order,
5. define what must be validated before any production patch is accepted.

Do not start with refactoring ideas.
Do not start with generic code cleanup.
Start with fault isolation.

## Core Problem Cluster

We are seeing at least two live problem families.

### Problem A. Non-molecule casual input appears to trigger molecule-related behavior

Observed user symptom:

- User enters a casual greeting like `ㅎㅇㅎㅇ`
- The chat experience appears to show a molecule/job-related response such as:
  - `benzene의 오비탈 계산이 완료되었습니다...`

Important:

- This may or may not mean that `ㅎㅇㅎㅇ` itself was parsed as a molecule.
- It may instead mean that a previously running job completed and its terminal message was attached to the wrong UI turn.

Your job is to determine which is more likely from the code.

### Problem B. Simple typo rescue is too weak

Observed user input:

- `Methyl Ethyl aminje`

Observed behavior:

- planner marks it as high-confidence `compute_ready`
- `structure_query = "Methyl Ethyl aminje"`
- MolChat fails
- PubChem fails
- final result: structure not found

Observed logs indicate:

- `semantic_grounding_needed = false`
- `confidence = 0.95`
- `fallback_reason = no_llm_provider_available`
- MolChat failures:
  - `All connection attempts failed`
- PubChem failure:
  - `Event loop is closed`

This suggests the issue is not only typo rescue.
It may also include bad planner confidence and broken fallback client lifecycle.

## Key Questions You Must Answer

### Q1. Is the `ㅎㅇㅎㅇ` issue actually planner/routing failure, or is it turn-binding / stale completion leakage?

You must decide whether the likely root cause is:

- the normalizer incorrectly classifying `ㅎㅇㅎㅇ` as compute-ready,
- the backend attaching a previous job result to the wrong turn,
- the frontend rendering a late completion event into the current chat turn,
- or a combination of these.

### Q2. Why does `Methyl Ethyl aminje` go directly to `compute_ready` with `confidence=0.95`?

You must explain:

- what logic in the normalizer/planner causes this,
- why typo suspicion is not lowering confidence,
- whether this should instead become clarification-first or semantic-grounding-first.

### Q3. Why does typo rescue fail even though similar correction behavior exists elsewhere?

You must inspect:

- whether the resolver only supports hand-written local corrections,
- whether there is any generic fuzzy rescue mechanism,
- whether `difflib` is used only for sorting rather than actual candidate generation,
- whether local alias correction and external MolChat correction are inconsistent.

### Q4. Is the PubChem fallback broken because of async client lifecycle misuse?

You must check whether:

- `PubChemClient` reuses an `httpx.AsyncClient` across different event loops,
- while job execution uses `asyncio.run(...)`,
- causing `Event loop is closed`.

If yes, call this out as a real runtime bug, not just a typo-handling issue.

### Q5. What is the safest patch order?

We do not want simultaneous speculative edits.

You must propose a patch order that minimizes regression risk.

## Files to Inspect First

You must prioritize these files.

### Routing / normalization

- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/web/routes/chat.py`

### Structure resolution and fallback

- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`

### Compute lifecycle and result delivery

- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/compute/job_manager.py`

### Frontend turn/result rendering

- `src/qcviz_mcp/web/static/chat.js`
- `src/qcviz_mcp/web/static/results.js`
- `src/qcviz_mcp/web/static/viewer.js`

### Tests

- `tests/test_chat_api.py`
- `tests/test_structure_extraction.py`
- `tests/v3/unit/test_structure_resolver.py`
- `tests/test_chat_playwright.py`
- `tests/test_chat_semantic_grounded_chat_playwright.py`

## Strong Suspects to Evaluate

You must explicitly evaluate these hypotheses.

### Hypothesis 1. Casual text is not the real trigger

`ㅎㅇㅎㅇ` may not be parsed as a molecule at all.
Instead, a prior job's terminal completion may be leaking into the current chat moment.

Check:

- turn ID binding
- pending/current turn logic
- active job binding in frontend
- whether completed job messages are appended independently of the originating turn

### Hypothesis 2. The normalizer is overconfident on any plausible text-looking molecule phrase

`Methyl Ethyl aminje` may be treated as a plain molecule candidate because:

- it is not a question,
- not an acronym,
- not obviously garbage,
- and falls through to default `compute_ready`.

Check whether typo suspicion heuristics are missing or too weak.

### Hypothesis 3. Local typo correction exists only as one-off exceptions

There may be specific hardcoded corrections such as:

- `aminobutylic acid -> gamma-aminobutyric acid`

but no general typo rescue for:

- `aminje -> amine`
- close-name fuzzy candidate generation
- clarification-first on low-confidence molecule-like text

### Hypothesis 4. PubChem fallback is genuinely runtime-broken

If `PubChemClient` retains an `AsyncClient` and later gets reused inside a fresh `asyncio.run(...)` call, this can cause:

- `Event loop is closed`

If this is true, then some structure resolution failures are inflated by infrastructure bugs rather than chemistry resolution quality alone.

### Hypothesis 5. Existing tests may not catch this class of UI-result mismatch

Check whether the current tests mainly validate:

- API response shape,
- expected lane,
- happy-path resolution,

but do not fully validate:

- stale completion leakage into later turns,
- current-turn vs prior-turn assistant/result separation,
- typo rescue quality under fallback failure conditions.

## Required Output Format

Your answer must contain these sections in this exact order.

### 1. Executive Diagnosis

- one-paragraph summary of what is most likely happening
- top 3 root causes
- top 3 non-root-cause symptoms

### 2. Issue-by-Issue Findings

For each finding, include:

- `severity`: `P0`, `P1`, `P2`, or `P3`
- `confidence`: `high`, `medium`, or `low`
- affected files
- observed symptom
- likely root cause
- evidence from code
- why it matters

### 3. Problem A Analysis: `ㅎㅇㅎㅇ`

You must answer:

- Was `ㅎㅇㅎㅇ` likely parsed as compute?
- Or was an older result rendered into the wrong turn?
- Which specific code paths make that happen?
- What test should reproduce it deterministically?

### 4. Problem B Analysis: `Methyl Ethyl aminje`

You must answer:

- Why planner confidence is too high
- Why semantic grounding is skipped
- Why typo rescue does not activate
- Whether MolChat and PubChem failures are true molecule-resolution failures or partly infrastructure failures

### 5. Patch Order Recommendation

You must recommend an ordered fix list.

Expected style:

1. fix X first because it poisons diagnosis
2. fix Y second because it blocks reliable fallback
3. fix Z third because it improves user-facing rescue

### 6. Test Additions Required Before Patch Approval

List at least 12 tests to add.

Include tests for:

- casual greeting while previous job finishes
- typo molecule names
- partial typo correction
- fallback client lifecycle
- stale turn completion
- incorrect assistant/result message mixing
- same-session vs new-session behavior

### 7. Go / No-Go Criteria

Define what must be true before we allow the actual code patch to land.

## Constraints

- Do not propose speculative fixes without tying them to specific files and code paths.
- Do not assume the user symptom equals the real root cause.
- Distinguish clearly between:
  - planner bug
  - resolver bug
  - async client lifecycle bug
  - frontend rendering bug
  - stale job state bug
- If multiple issues interact, describe the dependency chain.

## Final Note

Your job is to help us avoid patching the wrong layer first.

We want the external review to tell us:

- what is actually broken,
- what only looks broken,
- what should be fixed first,
- and what tests prove the fix is real.
