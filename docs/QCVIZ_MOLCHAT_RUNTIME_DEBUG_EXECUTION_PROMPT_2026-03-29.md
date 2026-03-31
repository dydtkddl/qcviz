# QCViz + MolChat Runtime Consumption Debug Protocol

## Mission

You are not doing a broad code review. You are executing a targeted runtime-debug and root-cause patch mission.

The current observed symptom is:

- User enters: `TNT 에들어가는주물질`
- MolChat `/api/v1/molecules/interpret` now returns `200 OK`
- But QCViz still shows a dropdown such as:
  - `물 — 3 atoms / CID 962 (H2O)`
- QCViz logs show that **after** the successful `interpret` call, it still issues generic fallback searches such as:
  - `search?q=water`
  - `search?q=methane`
  - `search?q=ethanol`
  - `search?q=methanol`
  - `search?q=benzene`

Your job is to identify exactly **why the interpreted MolChat result is not becoming the final dropdown candidate list inside the running QCViz flow**, then implement the final patch and verify it end-to-end.

This is **not** a draft-design task.
This is **not** a theory-only analysis.
This is an execution task:

1. verify runtime state,
2. instrument precisely,
3. reproduce,
4. patch root cause,
5. verify with tests and live reproduction.

Do not stop at intermediate diagnosis.

---

## Repositories

Primary QCViz repo:

- `D:\20260305_양자화학시각화MCP서버구축\version03`

Related MolChat repo:

- `C:\Users\user\Desktop\molcaht\molchat\v3`

Reference runtime symptom:

- QCViz calls: `http://psid.aizen.co.kr/molchat/api/v1/molecules/interpret`
- MolChat now returns `200`
- But QCViz still falls through to generic suggestions

---

## Non-Negotiable Goal

After your patch, the following behavior must hold:

### Target behavior

Input:

- `TNT 에들어가는주물질`

Expected QCViz behavior:

- Clarification mode should remain semantic-grounding oriented
- Dropdown candidates should come from interpreted / grounded semantic candidates
- Generic fallback candidates such as `water`, `methane`, `ethanol`, `benzene` must **not** appear
- If interpreted candidates are empty, the UI may show only:
  - grounded alternatives
  - or `custom`
  - but never unrelated generic examples

### Forbidden behavior

- Successful MolChat `interpret` response followed by generic fallback candidate generation
- Reclassification of semantic descriptor input into normal discovery mode
- Silent swallowing of interpreted payload
- Raw phrase itself becoming dropdown candidate
- Any patch that hides the symptom without proving why the interpreted result was ignored

---

## Scope

You must investigate all three layers:

### A. Runtime state verification

You must determine whether the running QCViz process is actually using the latest source code.

Specifically verify:

- whether the running server has restarted after latest patches
- whether the code path being executed matches the current files on disk
- whether stale Python process / stale module import / multiple workers / duplicate server instances are involved

Do not guess.
Prove it with observable evidence.

### B. Runtime consumption bug trace

You must trace the exact path from:

1. raw user message
2. semantic descriptor classification
3. MolChat `interpret` response
4. QCViz candidate transformation
5. clarification field construction
6. final dropdown payload returned to UI

You must identify the exact branch where the interpreted payload is discarded, overwritten, bypassed, or treated as empty.

### C. Final patch

Once root cause is confirmed, implement the smallest correct patch that fixes the real issue.

You may add temporary diagnostic logging during investigation, but the final result must leave:

- useful durable logs if justified
- no noisy spam logging unless it is operationally valuable

---

## Required Investigation Order

Follow this sequence exactly.

### Phase 1. Confirm runtime freshness

Check whether QCViz runtime is using latest code.

Required actions:

1. Identify the running QCViz process model
   - single process / multiple workers / stale process possibility
2. Confirm that the deployed process has restarted after latest source edits
3. Add one short high-signal runtime log marker in the exact semantic-consumption path if needed
4. Reproduce the request and confirm the marker appears

You must not proceed assuming the process is fresh unless you have evidence.

### Phase 2. Add surgical instrumentation

Add temporary logs at these decision boundaries in QCViz:

- semantic descriptor classification result
- `_molchat_interpret_candidates(...)` raw returned payload
- whether that payload is considered usable or empty
- whether fallback branch is entered
- which fallback branch is chosen
- final `structure_choice` options sent in clarification response

Each log line must include:

- query text
- mode
- candidate count
- chosen branch

Do not add vague logs like “here” or “got result”.
Every log must help answer a concrete branch question.

### Phase 3. Reproduce end-to-end

Reproduce with the real problematic input:

- `TNT 에들어가는주물질`

You must capture:

- MolChat raw interpret payload
- QCViz internal transformed candidate list
- final clarification payload sent to frontend

You must explicitly answer:

- Did QCViz receive the correct interpreted candidate?
- If yes, where exactly was it lost?
- If no, was the runtime path stale or was the transformation broken earlier?

### Phase 4. Patch root cause

Patch only after the exact discard point is proven.

Possible root-cause categories include:

- stale QCViz runtime process
- old code path still running
- semantic suggestions considered invalid because of transformation bug
- interpreted candidate name normalization causing candidates to be dropped
- merge logic preferring generic fallback over semantic suggestions
- clarification mode branch incorrectly re-entering discovery fallback
- UI field-building logic replacing semantic candidates with generic options

Do not commit to any one of these without proof.

### Phase 5. Verify with tests and live reproduction

You must verify using both:

1. automated tests
2. live runtime reproduction

At minimum:

- update/add regression tests for the exact failure mode
- rerun relevant QCViz tests
- perform a live request or equivalent direct route invocation
- confirm that `water` no longer appears for this TNT semantic query

---

## Files You Must Inspect

In QCViz, inspect at minimum:

- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/ko_aliases.py`
- `src/qcviz_mcp/llm/normalizer.py`
- relevant tests under:
  - `tests/test_chat_api.py`
  - `tests/test_structure_extraction.py`
  - `tests/v3/unit/test_molchat_client.py`
  - `tests/v3/unit/test_structure_resolver.py`

In MolChat, inspect only as needed for confirmation:

- `backend/app/routers/molecules.py`
- `backend/app/services/molecule_engine/orchestrator.py`
- `backend/app/services/molecule_engine/query_resolver.py`

Do not drift into unrelated refactors.

---

## Explicit Deliverables

Your final output must contain all of the following.

### 1. Root cause statement

One concise paragraph:

- what exact condition caused QCViz to ignore or override MolChat interpreted candidates
- whether runtime staleness contributed
- which function/branch was the decisive failure point

### 2. Patched files list

For every changed file:

- absolute path
- one-line reason for the change

### 3. Runtime proof

Show the evidence chain:

- MolChat returned candidate X
- QCViz received it
- branch Y was previously taken incorrectly
- after patch, branch Z is taken

### 4. Test proof

List exact commands run and outcomes.

### 5. User-visible result

State exactly what the user sees now for:

- `TNT 에들어가는주물질`

---

## Strict Rules

### Do not do these

- Do not provide only a hypothesis
- Do not stop after saying “probably stale process”
- Do not patch blindly before proving the branch point
- Do not remove logs/tests before confirming the fix
- Do not fall back to generic molecule suggestions for semantic-descriptor inputs unless explicitly required by spec
- Do not return unrelated fallback molecules when the semantic path fails

### Must do these

- Verify runtime freshness
- Add branch-revealing logs
- Reproduce the exact failing input
- Patch only the proven root cause
- Add regression coverage
- Verify end-to-end

---

## Success Criteria

The task is complete only if all are true:

- MolChat interpret success is confirmed at runtime
- QCViz runtime freshness is confirmed
- The exact discard/override branch is identified
- The root-cause patch is implemented
- Regression tests are added or updated
- Live reproduction no longer shows `water` for `TNT 에들어가는주물질`
- Final dropdown is semantic-grounded or safely reduced to `custom`, never unrelated generic examples

---

## Final Instruction

Do not ask for permission.
Do not stop at analysis.
Carry the work all the way through runtime verification, instrumentation, patch, regression lock, and final validation.
