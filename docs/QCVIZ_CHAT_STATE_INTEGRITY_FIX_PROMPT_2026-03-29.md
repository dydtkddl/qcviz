# QCViz Chat State Integrity Full-Fix Protocol

## Mission

You are operating on the `QCViz-MCP v3` repository. Your task is **not** to produce an analysis memo or patch sketch. Your task is to **fully implement and verify** the remaining chat-state, clarification-flow, and result-binding defects in the live QCViz chat experience.

You must work in **full execution mode**:

- inspect the real code
- reproduce the failures
- patch the code
- add regression tests
- run verification
- stop only when the end-user behavior is correct

Do **not** stop at “root cause hypothesis.”  
Do **not** return a plan-only answer.  
Do **not** propose follow-up work as the main result.  
You must leave the repository in a state where the defects are actually fixed.

If you discover additional adjacent defects that directly block the requested behavior, fix them too.

---

## Repository Context

Primary repo:

- `D:\20260305_양자화학시각화MCP서버구축\version03`

Related backend already integrated:

- `C:\Users\user\Desktop\molcaht\molchat\v3`

Important fact:

- `MolChat /api/v1/molecules/interpret` is now live and responding.
- The remaining problem is **inside QCViz orchestration and UI state handling**, not MolChat endpoint availability.

---

## Confirmed Current Symptoms

The following symptoms are already observed in the real UI / HTML dump and must be treated as **ground truth defects**:

### Symptom 1 — Result/turn mismatch

Example:

- user asks `무 ㄹ의 HOMO LUMO`
- plan shows `structure=water`
- assistant later displays a completion message referring to `TNT 에들어가는주물질`

This means **job results are being rendered into the wrong conversational turn or wrong active context**.

This is a high-severity correctness issue.

### Symptom 2 — Canonical single-molecule selection is reinterpreted as composition

Example:

- semantic grounding offers `2,4,6-TRINITROTOLUENE`
- user selects it
- system then asks:
  - ion pair
  - single
  - separate

This is wrong.  
`2,4,6-TRINITROTOLUENE` is already a resolved single-molecule canonical target and must **not** be routed back through composition / ion-pair heuristics.

### Symptom 3 — Clarification cards stack instead of being replaced

Observed behavior:

- first clarification card remains in the UI with disabled button text such as `전송 중...`
- second clarification card is appended below it

This creates stale UI state and confuses the user about which prompt is active.

### Symptom 4 — Chat history duplication / restore pollution

Observed behavior:

- repeated identical user messages appear multiple times
- `── 이전 대화 ──` markers are interleaved with current live interaction
- previous restored messages and fresh websocket messages appear to be merged without proper deduplication

This means current-session rendering and restored-history rendering are not cleanly separated.

### Symptom 5 — Candidate dropdown labels are too verbose and expose reasoning text

Observed behavior:

- dropdown labels contain long English rationale text such as:
  - `The query asks for the main component of TNT, which is Trinitrotoluene...`

This is not an acceptable user-facing selection label.

The user should see concise, chemically meaningful labels such as:

- `2,4,6-Trinitrotoluene (TNT) — CID 8376`
- optional compact formula metadata

not model-style explanatory prose.

---

## Problem Definition

This is **not** primarily a molecule-resolution problem anymore.

The current defect cluster is:

1. **chat turn ↔ backend job ↔ rendered result** mapping integrity
2. **clarification lifecycle management** integrity
3. **history restoration vs live append** integrity
4. **selected canonical structure protection** against reclassification
5. **candidate presentation quality** in the clarification UI

Your job is to fix the system at those layers.

---

## Primary Files to Inspect

You must read these files completely before changing behavior:

Backend / orchestration:

- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\routes\chat.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\routes\compute.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\conversation_state.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\llm\normalizer.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\structure_resolver.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\molchat_client.py`

Frontend / UI state:

- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\static\chat.js`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\static\app.js`
- `D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\templates\index.html`

Tests:

- `D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_chat_api.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_chat_playwright.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_runtime_health.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_web_server_smoke.py`
- `D:\20260305_양자화학시각화MCP서버구축\version03\tests\conftest.py`

If other files are imported into these flows, follow them.

---

## Mandatory Execution Order

You must proceed in this exact order.

### Phase 1 — Reproduce and instrument

Before changing behavior:

1. Reproduce the TNT semantic-grounding flow.
2. Reproduce the “water HOMO/LUMO then TNT message contamination” symptom.
3. Insert temporary or durable logging where necessary to identify:
   - which websocket event binds to which job id
   - which UI message block owns which active job
   - when clarification cards are created, updated, disabled, or superseded
   - when restored chat history is rehydrated
   - when canonical resolved structure names are passed back into composition heuristics

You must identify the exact transition points, not just the broad subsystem.

### Phase 2 — Fix backend state integrity

You must ensure:

1. A job completion event can only render into the correct active chat turn / correct job association.
2. Canonical molecule selections from semantic grounding are treated as **final single-structure selections** unless the payload explicitly still indicates unresolved composition.
3. Once the user has selected a grounded molecule candidate, composition/ion-pair heuristics do not re-trigger on the canonical resolved label.
4. Clarification session state is advanced cleanly and old clarification state is invalidated when superseded.

### Phase 3 — Fix frontend clarification lifecycle

You must ensure:

1. Only one active clarification card exists for the current unresolved interaction.
2. A submitted clarification card is either:
   - replaced by the next clarification card, or
   - marked completed and not left as an active duplicate
3. Disabled stale cards do not remain as if they still require user attention.
4. UI state for clarification must be derived from stable identifiers, not just DOM append order.

### Phase 4 — Fix chat history hydration / dedupe

You must ensure:

1. restored history is not re-appended as new live messages
2. duplicate user messages are not rendered multiple times unless they were actually sent multiple times
3. “previous conversation” separators are not inserted into the middle of an active current turn flow
4. websocket replay / local storage hydration / global app state merge do not double-count the same messages

### Phase 5 — Fix candidate label quality

You must ensure:

1. dropdown labels are concise and user-facing
2. rationale text is not directly exposed as verbose prose
3. labels prefer:
   - canonical molecule name
   - optional alias / common name
   - CID
   - formula
4. semantic grounding labels remain readable in Korean/English mixed UI

Example good label:

- `2,4,6-Trinitrotoluene (TNT) — CID 8376, C7H5N3O6`

Example bad label:

- `The query asks for the main component of TNT, which is Trinitrotoluene. / CID 8376 / confidence 1.00`

### Phase 6 — Add regression tests

You must add or strengthen tests for:

1. semantic grounding candidate selection for TNT-style descriptor queries
2. no generic fallback leakage (`water`, `methane`, `ethanol`, `methanol`, `benzene`) when semantic grounding should own the flow
3. canonical single-molecule selection does not re-trigger composition clarification
4. clarification card replacement / dedupe
5. result message belongs to the correct job / correct turn
6. restored history does not duplicate current live messages
7. browser-level clarification dropdown content using Playwright

### Phase 7 — Verify end-to-end

You must run:

1. `pytest -q`
2. targeted Playwright / browser verification
3. if needed, a local live server smoke roundtrip

If a test fails, fix the code and rerun.  
Do not report success until the suite is green.

---

## Constraints

### Do not do these

- do not replace the whole chat UI with a new framework
- do not remove semantic grounding
- do not disable MolChat integration to hide the bug
- do not paper over the issue by suppressing messages in the DOM only
- do not ship only more logging without fixing the flow
- do not hand-wave around “probably stale runtime” without adding a concrete runtime check

### You may do these

- add stable identifiers for clarification cards or live chat turns
- add state fields to websocket payloads if needed
- enrich health endpoints with runtime fingerprinting
- normalize candidate label formatting in the backend before sending to the UI
- change frontend rendering logic to update existing cards instead of blindly appending

---

## Concrete Acceptance Criteria

The task is only complete if all of the following are true.

### A. TNT semantic flow

For input:

- `TNT 에들어가는주물질`

Expected:

- user gets a clarification dropdown
- first grounded candidate is something equivalent to `2,4,6-Trinitrotoluene`
- `water` does **not** appear
- generic fallback examples do **not** appear
- selecting the grounded TNT candidate does **not** trigger ion-pair/composition clarification

### B. Water/TNT cross-turn contamination

For a sequence like:

1. `무 ㄹ의 HOMO LUMO`
2. `TNT 에들어가는주물질`

Expected:

- the water request produces only water-related progress/result text
- the TNT request produces only TNT-related clarification/result text
- no result summary for one query appears under the other query’s turn

### C. Clarification lifecycle

Expected:

- old clarification card does not remain as an active stale card after submission
- only one current actionable clarification card is visible for the active unresolved turn

### D. History integrity

Expected:

- reloaded/restored messages do not duplicate live messages
- “previous conversation” separators do not pollute the active flow

### E. Runtime freshness observability

Expected:

- `/api/health`
- `/api/chat/health`
- `/api/compute/health`

all expose enough runtime fingerprint info to determine whether the running process reflects current disk code.

---

## Required Deliverables

You must produce all of the following:

1. Actual code changes in the repository
2. Updated / added tests
3. A short execution report that contains:
   - exact root causes fixed
   - files changed
   - tests run
   - final pass/fail counts
   - any residual risk that is real and still remaining

The report must be brief and factual.  
The main deliverable is the working code, not the prose.

---

## Suggested Investigation Questions

Use these to guide your debugging, but do not stop at answering them.

1. Where is `activeJobIdForChat` assigned, updated, and cleared?
2. Are websocket `job_update`, `result`, `clarify`, and restored-history events sharing a single append path without proper turn ownership?
3. Does clarification submission append a new card without retiring the old one?
4. Is a selected canonical molecule value being fed back into `_looks_like_composite_query` or `composition_mode` logic?
5. Are restored `chatMessages` from storage merged back into DOM on reconnect in a way that duplicates live appends?
6. Are backend result summaries using stale conversation state instead of the current job payload?
7. Is the frontend using “latest active result” globally when it should be using “result for this turn / this job”?

---

## Implementation Standard

This is a user-facing correctness fix.  
Treat it as a reliability issue, not a cosmetic tweak.

Your patch should be:

- explicit
- traceable
- test-backed
- resistant to regression

If you must choose, prefer correctness and state integrity over cleverness.

---

## Final Instruction

Do the work end-to-end.

Do not return:

- a diagnosis only
- a patch idea only
- a TODO list
- a request for manual follow-up

Return only after the repository is actually fixed and verified.
