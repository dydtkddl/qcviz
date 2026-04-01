# QCViz Current Issue Lookup Table

Date: `2026-03-31`  
Scope: `version03` live service, chat routing, structure resolution, compute lifecycle, viewer contract, session behavior  
Purpose: enumerate currently known or strongly suspected issues before broad 50-case expansion

## Reading Guide

- `Status`
  - `Confirmed`: observed in logs, live runs, or existing audit artifacts
  - `Likely`: strongly supported by code and symptoms but still needs a targeted repro
  - `Suspected`: architecture smell or partial symptom that should be verified
- `Priority`
  - `P0`: trust-breaking or user-truthfulness breaking
  - `P1`: major workflow breakage
  - `P2`: important but not immediately release-blocking
  - `P3`: debt, observability, or resilience issue

## Lookup Table

| ID | Status | Priority | Category | Symptom | Typical Trigger | Suspected Layer | Primary Files To Inspect | Detailed File / Code Points To Check | Notes |
|---|---|---|---|---|---|---|---|---|---|
| `ISSUE-01` | Confirmed | `P0` | Structure identity | TNT-like query can end up visualizing a structure that appears not to contain nitro groups | `TNT에 들어가는 주물질이 뭐지?` then choose `2,4,6-Trinitrotoluene` | structure identity / viewer binding | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/static/viewer.js`, `src/qcviz_mcp/web/static/results.js` | `structure_resolver.py`: `_build_query_plan()`, `resolve()`, `result.name` reassignment, `query_plan["display_query"]`; `compute.py`: final result payload normalization and structure metadata handoff; `results.js`: result-to-viewer hydration path; `viewer.js`: full model reset vs stale model reuse | Highest trust issue; selected structure and rendered structure may diverge |
| `ISSUE-02` | Confirmed | `P0` | Chat/result contamination | Casual input can appear to trigger an unrelated prior job completion message | `ㅎㅇㅎㅇ` right after a prior job finishes | frontend turn binding / WS result delivery | `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/compute/job_manager.py` | `chat.js`: `pendingTurnId`, `currentTurnId`, `activeJobIdForChat`, WS handlers for `assistant`, `job_submitted`, `result`, `error`; `compute.py`: terminal streaming/send order; `job_manager.py`: `_finalize_success()`, `_append_event()` | Likely previous job completion leaking into current turn, not true molecule parsing |
| `ISSUE-03` | Confirmed | `P1` | Planner overconfidence | Typo-like molecule text is classified as high-confidence `compute_ready` too early | `Methyl Ethyl aminje` | normalizer / planner fallback | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | `normalizer.py`: `normalize_user_text()`, `analyze_query_routing()`, `_extract_unknown_acronyms()`, `question_like`, `chat_only`, default confidence logic; `chat.py`: where normalized plan becomes immediate compute | `confidence=0.95` is too high for an obviously noisy string |
| `ISSUE-04` | Confirmed | `P1` | Typo rescue gap | Simple spelling or phonetic typo is not rescued into a likely chemical candidate | `Methyl Ethyl aminje` | resolver candidate generation | `src/qcviz_mcp/services/structure_resolver.py` | `structure_resolver.py`: `LOCAL_QUERY_AUTOCORRECTS`, `_build_query_plan()`, `candidate_queries`, `suggest_candidate_queries()`, `difflib` usage near candidate ranking, lack of broad typo generation | Current correction is mostly one-off aliases, not generic typo rescue |
| `ISSUE-05` | Confirmed | `P1` | Async lifecycle | PubChem fallback can fail with `Event loop is closed` | typo or fallback-heavy queries | HTTP client lifecycle | `src/qcviz_mcp/services/pubchem_client.py`, `src/qcviz_mcp/compute/job_manager.py` | `pubchem_client.py`: `_client`, `_get_client()`, `close()`, `name_to_cid()`, `name_to_sdf_3d()`; `job_manager.py`: `_run_job()` and `asyncio.run(result)` loop creation pattern | Likely `AsyncClient` reuse across different loops |
| `ISSUE-06` | Confirmed | `P1` | External fallback resilience | MolChat fallback can fail with `All connection attempts failed` and no graceful degradation path ranking | network hiccup or MolChat reachability issue | MolChat client / resolver retry policy | `src/qcviz_mcp/services/molchat_client.py`, `src/qcviz_mcp/services/structure_resolver.py` | `molchat_client.py`: `_build_client()`, `resolve()`, `search()`, `generate_3d_sdf()`; `structure_resolver.py`: `_try_molchat()`, `_try_molchat_with_search_fallback()`, transport failure handling vs no-hit handling | Need better degradation and clearer error classes |
| `ISSUE-07` | Confirmed | `P1` | Alias parity | MolChat standalone UI can autocorrect a query that QCViz compute path still fails to resolve | `Aminobutylic acid` | QCViz local resolver parity | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/services/molchat_client.py` | `structure_resolver.py`: local correction path, normalized vs display query, candidate ordering; `molchat_client.py`: whether integrated search fallback reaches the same correction quality as the standalone site | Shows product inconsistency between MolChat site and QCViz path |
| `ISSUE-08` | Likely | `P1` | Semantic intent | Descriptor-style questions may be pushed toward compute-adjacent flow too early instead of explanation-first | `TNT에 들어가는 주물질이 뭐지?` | routing policy | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | `normalizer.py`: `question_like`, `chat_only`, `semantic_grounding_needed`; `chat.py`: `_build_semantic_chat_response()`, `_build_semantic_unresolved_chat_response()`, `_prepare_or_clarify()` | Need a clean explanation-vs-compute boundary |
| `ISSUE-09` | Confirmed | `P1` | Clarification stability | User-selected clarification candidate can drift if later stages reinterpret free text rather than locked candidate metadata | semantic candidate submit flows | clarification payload binding | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` | `chat.py`: `_CLARIFICATION_SESSIONS`, `_session_put()`, `_session_get()`, `_session_pop()`, semantic clarification submit path; `chat.js`: `_renderClarifyForm()`, selected option submission payload | Previously observed with TNT-like candidate flows |
| `ISSUE-10` | Confirmed | `P1` | Session follow-up | Same-session pronoun follow-ups have historically broken or regressed | `그거 HOMO`, `ESP도`, `이번엔 LUMO` | conversation state / frontend session state | `src/qcviz_mcp/web/conversation_state.py`, `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` | `conversation_state.py`: `build_execution_state()`, `save_conversation_state_from_result()`; `chat.py`: semantic continuation writeback and reuse logic; `chat.js`: same-session submit path and turn reuse | Still a high-regression zone |
| `ISSUE-11` | Likely | `P1` | Parameter-only follow-up | Method/basis-only updates can lose structure context or get mistaken for new structure search | `basis만 더 키워`, `method를 PBE0로 바꿔` | follow-up routing | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | `normalizer.py`: `analyze_follow_up_request()`, basis/method regexes, `follow_up_mode = "modify_parameters"`; `chat.py`: how follow-up parameter hints merge into the prepared payload | Needs stronger regression protection |
| `ISSUE-12` | Likely | `P1` | Terminal result contract | Completed job and terminal result payload can still be misordered or partially inconsistent | any compute case under WS | compute route / frontend state machine | `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/static/results.js` | `compute.py`: `_normalize_result_contract()`, terminal streaming/send order, completed vs result emission; `chat.js`: `job_update`/`result` handling; `results.js`: assumptions about final payload completeness | Previously fixed once; still critical enough to keep on the list |
| `ISSUE-13` | Likely | `P1` | Viewer freshness | Viewer may reuse stale geometry/snapshot state if new result payload is incomplete or delayed | back-to-back different molecules | result hydration / viewer state | `src/qcviz_mcp/web/static/viewer.js`, `src/qcviz_mcp/web/static/results.js`, `src/qcviz_mcp/web/static/app.js` | `viewer.js`: full model reset path, cube reset path, geometry replacement; `results.js`: when active result is updated; `app.js`: `uiSnapshotsByJobId` restore semantics | Leading explanation for wrong-looking TNT rendering |
| `ISSUE-14` | Suspected | `P1` | Turn/job association | `pendingTurnId`, `currentTurnId`, and `activeJobIdForChat` may not be sufficient to isolate concurrent or late-arriving events | overlapping jobs or delayed completion | chat frontend state machine | `src/qcviz_mcp/web/static/chat.js` | Watch WS switch cases using fallback `msg.turn_id || currentTurnId || pendingTurnId`, plus `App.bindChatTurnToJob(...)` and per-job message storage assumptions | Important if multiple jobs interleave |
| `ISSUE-15` | Suspected | `P1` | Session reset UX | No explicit `New Session` affordance means user can get trapped in stale conversation/context baggage | long sessions, many follow-ups | frontend UX / session auth / state reset | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/session_auth.py` | `index.html`: session bootstrap and `setSessionAuth()`; `app.js`: `refreshHistoryForIdentityChange()`, `clearJobsState()`; `chat.js`: `resetChatMessagesToBase()`, `clearChatSurface()`; `session_auth.py`: new session issuance | Adding a button may reduce contamination symptoms |
| `ISSUE-16` | Suspected | `P2` | Session reset completeness | Even if session ID changes, not every cache/surface may reset together | future new-session feature | mixed frontend/backend session state | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/conversation_state.py` | `index.html`: `getSnapshotStorageKey()`, `getChatStorageKey()`, `clearChatMessages()`, `setSessionAuth()`; `app.js`: quota/queue/history reset; `chat.js`: pending cards and turn IDs; `conversation_state.py`: old state invalidation semantics | Must clear chat, snapshots, pending cards, continuation state together |
| `ISSUE-17` | Suspected | `P2` | Clarification session cache | `_CLARIFICATION_SESSIONS` is process-local and session keyed, which can leak or stale if not popped cleanly | repeated clarification within same session | in-memory clarification state | `src/qcviz_mcp/web/routes/chat.py` | `chat.py`: `_CLARIFICATION_SESSIONS`, `_session_put()`, `_session_get()`, `_session_pop()`, overwrite behavior on repeated clarification | Could interact with session reuse and same-tab long usage |
| `ISSUE-18` | Suspected | `P2` | Conversation-state persistence | Conversation state may persist only in manager-backed memory and not be fully invalidated on intentional session restart | session rollover or server restart | conversation state store | `src/qcviz_mcp/web/conversation_state.py`, `src/qcviz_mcp/web/session_auth.py` | `conversation_state.py`: `load/save/update_conversation_state()`; `session_auth.py`: session lifetime and issuance, but no explicit conversation purge hook | Relevant if introducing explicit new-session control |
| `ISSUE-19` | Confirmed | `P2` | Heuristic fallback dependence | When no LLM provider is available, the heuristic path dominates and can be overly rigid | `fallback_reason = no_llm_provider_available` | planner architecture | `src/qcviz_mcp/llm/pipeline.py`, `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/llm/providers.py` | `pipeline.py`: fallback stage decisions; `providers.py`: provider availability; `normalizer.py`: heuristic confidence and lane locking | Amplifies false confidence on noisy molecule-like strings |
| `ISSUE-20` | Likely | `P2` | Candidate generation quality | Generic fuzzy or edit-distance-based candidate recovery is weaker than needed for chemistry typos | misspelled amines, acids, abbreviations | resolver candidate generator | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/services/ko_aliases.py` | `structure_resolver.py`: `difflib.SequenceMatcher` use near ranking, no broad fuzzy generation; `ko_aliases.py`: deterministic alias map only | `difflib` is used more for ordering than true recovery |
| `ISSUE-21` | Suspected | `P2` | Name normalization policy | Different stages may prefer raw query, corrected query, or display query inconsistently | typo/autocorrect or semantic grounding flows | query plan normalization | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/chat.py` | `structure_resolver.py`: `raw_query`, `normalized_query`, `display_query`, `result.name`; `chat.py`: which field is echoed in messages, plans, and clarification cards | Risk: user sees one name, compute runs another, viewer labels a third |
| `ISSUE-22` | Suspected | `P2` | Cache-key semantics | Current cache/result keys may not be rich enough to detect semantically identical repeat requests for reuse | same molecule + same method/basis repeated later | cache/result architecture | `src/qcviz_mcp/compute/disk_cache.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/web/conversation_state.py` | `disk_cache.py`: cache key inputs and persistence shape; `job_manager.py`: result indexing and lookup capability; `conversation_state.py`: what prior structure/method metadata survives | Blocks a future retrieval-first pipeline |
| `ISSUE-23` | Suspected | `P2` | Prior result reuse missing | Repeating an already completed calculation likely recomputes instead of replaying a prior trustworthy result | repeated user asks same analysis again | retrieval / result persistence gap | `src/qcviz_mcp/compute/disk_cache.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/result_explainer.py` | Look for absence of canonical query-to-result lookup before submission, absence of viewer-ready replay path, and lack of “same request” detection at route layer | Strong candidate for a RAG-like result retrieval layer |
| `ISSUE-24` | Suspected | `P2` | Result persistence richness | Completed results may not store enough canonical metadata for safe future retrieval and comparison | future result reuse implementation | result schema | `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/web/conversation_state.py` | `compute.py`: final result schema; `job_manager.py`: `record.result`; `conversation_state.py`: persisted execution metadata; check for missing canonical structure key, normalized method/basis, artifact refs | Need canonical structure key, normalized method/basis, artifact references |
| `ISSUE-25` | Suspected | `P2` | Test blind spot | Tests may validate API shape and expected lane but still miss stale completion leakage and viewer-object mismatch | live browser timing and late WS events | test harness realism gap | `tests/test_chat_api.py`, `tests/test_chat_playwright.py`, `tests/test_chat_semantic_grounded_chat_playwright.py` | Look for assertions on lane only vs assertions on final rendered structure/result identity; check absence of prior-job-completes-during-new-turn tests | Green tests may still miss user-visible truth breaks |
| `ISSUE-26` | Suspected | `P2` | Live audit harness mismatch | Some failures or passes may depend on harness logic rather than product truth | Playwright sweep loops | audit harness | `output/playwright_live_restart_20260330/run_live_audit.py`, `output/playwright_live_restart_20260330_50/run_live_audit_50.py` | Inspect `wait_for_terminal_state()`, baseline terminal job filtering, event request logging, and any expectation hardcoding that can hide or invent failures | Important when using pass rate as ship signal |
| `ISSUE-27` | Suspected | `P3` | Observability gap | Logs do not always distinguish clearly between planner issue, resolver issue, transport issue, and viewer issue | complex failure cases | logging/trace design | `src/qcviz_mcp/llm/trace.py`, `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/compute.py` | `trace.py`: planner trace granularity; `structure_resolver.py`: transport vs no-hit logs; `compute.py`: result-stream logs and viewer payload logs | Makes root-cause analysis slower than necessary |
| `ISSUE-28` | Suspected | `P3` | Boot/runtime drift risk | Different startup scripts and root-path assumptions have historically drifted | `a.sh`, live restart, root path assumptions | boot path config | `a.sh`, `src/qcviz_mcp/web/app.py`, `src/qcviz_mcp/web/runtime_info.py` | Check boot command parity, `--app-dir src`, root-path assumptions, and health/runtime fingerprint reporting | Already improved, but still worth tracking |
| `ISSUE-29` | Suspected | `P3` | Local storage persistence coupling | UI snapshots and chat history persist by session key and can become confusing during partial identity changes | long browser sessions | browser persistence | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js` | `index.html`: storage keys, session-scoped save/load; `app.js`: snapshot/history refresh and identity-change behavior | Especially relevant if a manual new-session button is introduced |
| `ISSUE-30` | Suspected | `P3` | Scientific explanation safety | Explanation-like prompts can be partially coerced into compute-oriented pathways without enough user confirmation | concept questions with molecule-like words | routing / UX policy | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | `normalizer.py`: `chat_only` vs `compute_ready`; `chat.py`: semantic direct-answer path, unresolved semantic chat path, clarify-vs-compute decision | Not always a crash bug, but a user-truthfulness problem |

## Issue Families

These families are designed around “what can realistically be solved together in one patch package.”

### Family Lookup

| Family | Shared Fix Theme | Included Issues | Why They Belong Together | Main Files To Touch Together | Expected Win |
|---|---|---|---|---|---|
| `FAM-01` | Result truth / viewer truth / turn binding | `ISSUE-01`, `ISSUE-02`, `ISSUE-12`, `ISSUE-13`, `ISSUE-14` | All five are about the user seeing the wrong thing for the right job, the right thing in the wrong turn, or a stale structure/result being rendered | `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/static/results.js`, `src/qcviz_mcp/web/static/viewer.js`, `src/qcviz_mcp/compute/job_manager.py` | Restores trust in “what you selected is what you see” |
| `FAM-02` | Typo rescue / name normalization / candidate generation | `ISSUE-03`, `ISSUE-04`, `ISSUE-07`, `ISSUE-20`, `ISSUE-21` | These are all different faces of the same resolver weakness: noisy user text is over-trusted early and under-corrected later | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/services/ko_aliases.py`, `src/qcviz_mcp/web/routes/chat.py` | Better salvage of misspellings and fewer false-confidence compute launches |
| `FAM-03` | External lookup resilience / async lifecycle | `ISSUE-05`, `ISSUE-06`, `ISSUE-19`, `ISSUE-27`, `ISSUE-28` | PubChem loop issues, MolChat transport failures, heuristic fallback dominance, and weak logging all combine into hard-to-debug lookup failures | `src/qcviz_mcp/services/pubchem_client.py`, `src/qcviz_mcp/services/molchat_client.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/llm/pipeline.py`, `src/qcviz_mcp/llm/trace.py`, `a.sh` | Fewer resolver hard-fails and much clearer root-cause visibility |
| `FAM-04` | Semantic routing and explanation boundary | `ISSUE-08`, `ISSUE-11`, `ISSUE-30` | These all happen when the system confuses “tell me about it” with “run something on it,” or mistakes parameter-only edits for fresh structure requests | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | More truthful chat behavior and fewer accidental compute flows |
| `FAM-05` | Clarification lock / candidate stability | `ISSUE-09`, `ISSUE-17` | Both are about making sure a clarification choice stays bound to the same candidate and does not drift, leak, or get reinterpreted later | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` | Safer semantic clarification and fewer wrong-molecule submissions |
| `FAM-06` | Session continuity / new-session semantics | `ISSUE-10`, `ISSUE-15`, `ISSUE-16`, `ISSUE-18`, `ISSUE-29` | These issues all sit on the boundary between long-running context reuse and explicit reset. They should be solved as one session-state design pass | `src/qcviz_mcp/web/conversation_state.py`, `src/qcviz_mcp/web/session_auth.py`, `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js`, `src/qcviz_mcp/web/static/chat.js` | Cleaner follow-up behavior and a real escape hatch via `New Session` |
| `FAM-07` | Prior-result retrieval / no-recompute strategy | `ISSUE-22`, `ISSUE-23`, `ISSUE-24` | These are the foundation for a RAG-like “same request -> replay trusted result” layer and should be designed together, not piecemeal | `src/qcviz_mcp/compute/disk_cache.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/conversation_state.py`, `src/qcviz_mcp/web/result_explainer.py` | Enables result reuse instead of recompute for repeated requests |
| `FAM-08` | Test and audit realism | `ISSUE-25`, `ISSUE-26` | These do not directly break users, but they determine whether we can trust green results while the above families are being fixed | `tests/test_chat_api.py`, `tests/test_chat_playwright.py`, `tests/test_chat_semantic_grounded_chat_playwright.py`, `output/playwright_live_restart_20260330/run_live_audit.py`, `output/playwright_live_restart_20260330_50/run_live_audit_50.py` | Prevents false confidence and keeps fixes from regressing silently |

### Family-First Execution Order

1. `FAM-01`
   Why first: this is the highest user-trust break. Even perfect routing is not enough if the UI shows the wrong result or attaches it to the wrong turn.
2. `FAM-02`
   Why second: typo rescue and name normalization are the next biggest source of avoidable failure in real usage.
3. `FAM-03`
   Why third: once resolver quality is improved, transport and async lifecycle issues become the next hard blocker.
4. `FAM-05`
   Why fourth: clarification drift can silently undo resolver improvements, so it should be locked before adding more semantic sophistication.
5. `FAM-06`
   Why fifth: session continuity and explicit reset should be designed together, especially if a `New Session` button is added.
6. `FAM-04`
   Why sixth: explanation-vs-compute boundary can then be refined safely once session and clarification behavior are more deterministic.
7. `FAM-07`
   Why seventh: prior-result retrieval should come after identity, session, and result truth are stabilized.
8. `FAM-08`
   Why always-on: this family should be updated in parallel with every other family so the audit harness stays trustworthy.

### Family Notes

#### `FAM-01` Result Truth Family

- Best solved as one frontend/backend contract pass.
- If this family is fixed well, it should reduce confusion around TNT visualization mismatch, stale benzene completion leakage, and late WS completion contamination in one shot.

#### `FAM-02` Resolver Quality Family

- This is the right family to include:
  - typo correction
  - alias expansion
  - corrected-query vs display-query consistency
  - planner confidence downshift for noisy strings
- `Aminobutylic acid` and `Methyl Ethyl aminje` belong here, not in separate isolated patches.

#### `FAM-03` External Resilience Family

- If PubChem loop handling and MolChat transport handling are patched separately, debugging gets messy.
- It is better to fix:
  - async client lifecycle
  - retry/degradation policy
  - fallback stage labeling
  - resolver error-class logging
  together.

#### `FAM-06` Session/New-Session Family

- This is the family where the `New Session` button belongs.
- A frontend-only button is not enough; it must reset:
  - session identity
  - chat message storage
  - UI snapshot storage
  - pending clarification cards
  - current WS identity
  - backend continuation state

#### `FAM-07` Prior-Result Retrieval Family

- This is the right place to add the “same request -> reuse existing result” idea.
- It should not be treated as a quick cache toggle.
- It needs canonical structure identity, normalized method/basis, and viewer-ready artifact references first.

## Highest-Value Immediate Buckets

### Bucket A. User-truth / trust-breaking

- `ISSUE-01`
- `ISSUE-02`
- `ISSUE-12`
- `ISSUE-13`

### Bucket B. Molecule interpretation quality

- `ISSUE-03`
- `ISSUE-04`
- `ISSUE-07`
- `ISSUE-08`
- `ISSUE-20`
- `ISSUE-21`

### Bucket C. Runtime infrastructure bugs

- `ISSUE-05`
- `ISSUE-06`
- `ISSUE-14`
- `ISSUE-17`
- `ISSUE-18`

### Bucket D. Future-proofing for result retrieval

- `ISSUE-22`
- `ISSUE-23`
- `ISSUE-24`
- `ISSUE-29`

## Suggested Next Sort Order

1. Fix or conclusively isolate `ISSUE-02`, `ISSUE-12`, `ISSUE-13`
2. Fix `ISSUE-05` and improve `ISSUE-06`
3. Rework planner confidence and typo rescue for `ISSUE-03`, `ISSUE-04`, `ISSUE-20`
4. Re-check TNT identity integrity for `ISSUE-01` and `ISSUE-21`
5. Design explicit new-session semantics for `ISSUE-15`, `ISSUE-16`, `ISSUE-18`, `ISSUE-29`
6. Prepare result retrieval groundwork for `ISSUE-22`, `ISSUE-23`, `ISSUE-24`

## New Session Button Angle

Adding a `New Session` button is a valid mitigation direction, but it is not a substitute for fixing root causes.

It is most likely helpful for:

- reducing stale follow-up contamination,
- giving users a clean escape hatch after long ambiguous conversations,
- separating old chat history and UI snapshots from fresh work,
- making turn/result contamination easier to reason about.

It will not by itself fix:

- wrong structure resolution,
- typo rescue weakness,
- PubChem async lifecycle failure,
- viewer/object mismatch,
- stale terminal event routing bugs.

If this button is introduced later, it should be designed to reset:

- frontend `sessionId` and `sessionToken`
- `chatMessages`
- `chatMessagesByJobId`
- UI snapshots
- pending clarification/confirm cards
- chat WS connection identity
- backend conversation state for the new session key

## Result Reuse Angle

A future `same request -> return prior trusted result` layer is strongly recommended.

This would help when:

- the user repeats the same molecule + same job type + same method/basis,
- or asks a nearly identical follow-up that should reuse artifacts instead of recomputing.

Before that can be safely added, the system should reliably persist and index:

- canonical structure identity
- resolved name
- CID/SMILES if available
- normalized method/basis/charge/multiplicity
- job type
- artifact paths or cache keys
- viewer-ready payload references
- provenance timestamp and source

Without that, naive reuse could return the wrong molecule or wrong artifact.
