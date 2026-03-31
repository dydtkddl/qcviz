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

| ID | Status | Priority | Category | Symptom | Typical Trigger | Suspected Layer | Primary Files To Inspect | Notes |
|---|---|---|---|---|---|---|---|---|
| `ISSUE-01` | Confirmed | `P0` | Structure identity | Selected TNT-like query can end up visualizing a structure that appears not to contain nitro groups | `TNT에 들어가는 주물질이 뭐지?` then choose `2,4,6-Trinitrotoluene` | structure identity / viewer binding | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/static/viewer.js`, `src/qcviz_mcp/web/static/results.js` | Highest trust issue; selected structure and rendered structure may diverge |
| `ISSUE-02` | Confirmed | `P0` | Chat/result contamination | Casual input can appear to trigger an unrelated prior job completion message | `ㅎㅇㅎㅇ` right after a prior job finishes | frontend turn binding / WS result delivery | `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/compute/job_manager.py` | Likely previous job completion leaking into current turn, not true molecule parsing |
| `ISSUE-03` | Confirmed | `P1` | Planner overconfidence | Typo-like molecule text is classified as high-confidence `compute_ready` too early | `Methyl Ethyl aminje` | normalizer / planner fallback | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | `confidence=0.95` is too high for an obviously noisy string |
| `ISSUE-04` | Confirmed | `P1` | Typo rescue gap | Simple spelling or phonetic typo is not rescued into a likely chemical candidate | `Methyl Ethyl aminje` | resolver candidate generation | `src/qcviz_mcp/services/structure_resolver.py` | Current correction is mostly one-off aliases, not generic typo rescue |
| `ISSUE-05` | Confirmed | `P1` | Async lifecycle | PubChem fallback can fail with `Event loop is closed` | typo or fallback-heavy queries | HTTP client lifecycle | `src/qcviz_mcp/services/pubchem_client.py`, `src/qcviz_mcp/compute/job_manager.py` | Likely AsyncClient reuse across different loops under `asyncio.run(...)` |
| `ISSUE-06` | Confirmed | `P1` | External fallback resilience | MolChat fallback can fail with `All connection attempts failed` and no graceful degradation path ranking | network hiccup or MolChat reachability issue | MolChat client / resolver retry policy | `src/qcviz_mcp/services/molchat_client.py`, `src/qcviz_mcp/services/structure_resolver.py` | Need better degradation and better differentiation between transport failure and no-hit |
| `ISSUE-07` | Confirmed | `P1` | Alias parity | MolChat standalone UI can autocorrect a query that QCViz compute path still fails to resolve | `Aminobutylic acid` | QCViz local resolver parity | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/services/molchat_client.py` | Shows product inconsistency between MolChat site and integrated QCViz path |
| `ISSUE-08` | Likely | `P1` | Semantic intent | Descriptor-style questions may be pushed toward compute-adjacent flow too early instead of explanation-first | `TNT에 들어가는 주물질이 뭐지?` | routing policy | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | Need a clean explanation-vs-compute boundary for chemistry description queries |
| `ISSUE-09` | Confirmed | `P1` | Clarification stability | User-selected clarification candidate can drift if later stages reinterpret free text rather than locked candidate metadata | semantic candidate submit flows | clarification payload binding | `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` | Previously observed with TNT-like candidate flows |
| `ISSUE-10` | Confirmed | `P1` | Session follow-up | Same-session pronoun follow-ups have historically broken or regressed | `그거 HOMO`, `ESP도`, `이번엔 LUMO` | conversation state / frontend session state | `src/qcviz_mcp/web/conversation_state.py`, `src/qcviz_mcp/web/routes/chat.py`, `src/qcviz_mcp/web/static/chat.js` | Currently improved, but still a high-regression zone |
| `ISSUE-11` | Likely | `P1` | Parameter-only follow-up | Method/basis-only updates can lose structure context or get mistaken for new structure search | `basis만 더 키워`, `method를 PBE0로 바꿔` | follow-up routing | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | Needs stronger regression protection |
| `ISSUE-12` | Likely | `P1` | Terminal result contract | Completed job and terminal result payload can still be misordered or partially inconsistent | any compute case under WS | compute route / frontend state machine | `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/static/results.js` | Previously fixed once; still critical enough to keep on the list |
| `ISSUE-13` | Likely | `P1` | Viewer freshness | Viewer may reuse stale geometry/snapshot state if new result payload is incomplete or delayed | back-to-back different molecules | result hydration / viewer state | `src/qcviz_mcp/web/static/viewer.js`, `src/qcviz_mcp/web/static/results.js`, `src/qcviz_mcp/web/static/app.js` | This is one of the leading explanations for wrong-looking TNT rendering |
| `ISSUE-14` | Suspected | `P1` | Turn/job association | `pendingTurnId`, `currentTurnId`, and `activeJobIdForChat` may not be sufficient to isolate concurrent or late-arriving events | overlapping jobs or delayed completion | chat frontend state machine | `src/qcviz_mcp/web/static/chat.js` | Important if multiple fast/slow jobs interleave |
| `ISSUE-15` | Suspected | `P1` | Session reset UX | No explicit “new session” affordance means user can get trapped in stale conversation/context baggage | long sessions, many follow-ups | frontend UX / session auth / state reset | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/session_auth.py` | Adding a new-session button may reduce contamination symptoms |
| `ISSUE-16` | Suspected | `P2` | Session reset completeness | Even if session ID changes, not every cache/surface may reset together | future new-session feature | mixed frontend/backend session state | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js`, `src/qcviz_mcp/web/static/chat.js`, `src/qcviz_mcp/web/conversation_state.py` | Must clear chat, UI snapshots, pending cards, and in-memory continuation state together |
| `ISSUE-17` | Suspected | `P2` | Clarification session cache | `_CLARIFICATION_SESSIONS` is process-local and session keyed, which can leak or stale if not popped cleanly | repeated clarification within same session | in-memory clarification state | `src/qcviz_mcp/web/routes/chat.py` | Could interact with session reuse and same-tab long usage |
| `ISSUE-18` | Suspected | `P2` | Conversation-state persistence | Conversation state may persist only in manager-backed memory and not be fully invalidated on intentional session restart | session rollover or server restart | conversation state store | `src/qcviz_mcp/web/conversation_state.py` | Relevant if introducing explicit “new session” control |
| `ISSUE-19` | Confirmed | `P2` | Heuristic fallback dependence | When no LLM provider is available, the heuristic path dominates and can be overly rigid | `fallback_reason = no_llm_provider_available` | planner architecture | `src/qcviz_mcp/llm/pipeline.py`, `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/llm/providers.py` | This amplifies false confidence on noisy molecule-like strings |
| `ISSUE-20` | Likely | `P2` | Candidate generation quality | Generic fuzzy or edit-distance-based candidate recovery is weaker than needed for chemistry typos | misspelled amines, acids, abbreviations | resolver candidate generator | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/services/ko_aliases.py` | `difflib` appears to be used more for ordering than true recovery |
| `ISSUE-21` | Suspected | `P2` | Name normalization policy | Different stages may prefer raw query, corrected query, or display query inconsistently | typo/autocorrect or semantic grounding flows | query plan normalization | `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/chat.py` | Risk: user sees one name, compute runs another, viewer labels a third |
| `ISSUE-22` | Suspected | `P2` | Cache-key semantics | Current cache/result keys may not be rich enough to detect semantically identical repeat requests for reuse | same molecule + same method/basis repeated later | cache/result architecture | `src/qcviz_mcp/compute/disk_cache.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/web/conversation_state.py` | This blocks a future retrieval-first pipeline |
| `ISSUE-23` | Suspected | `P2` | Prior result reuse missing | Repeating an already completed calculation likely recomputes instead of replaying a prior trustworthy result | repeated user asks same analysis again | retrieval / result persistence gap | `src/qcviz_mcp/compute/disk_cache.py`, `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/web/result_explainer.py` | Strong candidate for a RAG-like result retrieval layer |
| `ISSUE-24` | Suspected | `P2` | Result persistence richness | Completed results may not store enough canonical metadata for safe future retrieval and comparison | future result reuse implementation | result schema | `src/qcviz_mcp/web/routes/compute.py`, `src/qcviz_mcp/compute/job_manager.py`, `src/qcviz_mcp/web/conversation_state.py` | Need canonical structure key, normalized method/basis, artifact references |
| `ISSUE-25` | Suspected | `P2` | Test blind spot | Tests may validate API shape and expected lane but still miss stale completion leakage and viewer-object mismatch | live browser timing and late WS events | test harness realism gap | `tests/test_chat_api.py`, `tests/test_chat_playwright.py`, `tests/test_chat_semantic_grounded_chat_playwright.py` | Green tests may still miss user-visible truth breaks |
| `ISSUE-26` | Suspected | `P2` | Live audit harness mismatch | Some failures or passes may depend on harness logic rather than product truth | Playwright sweep loops | audit harness | `output/playwright_live_restart_20260330/run_live_audit.py`, `output/playwright_live_restart_20260330_50/run_live_audit_50.py` | Important when using pass rate as ship signal |
| `ISSUE-27` | Suspected | `P3` | Observability gap | Logs do not always distinguish clearly between planner issue, resolver issue, transport issue, and viewer issue | complex failure cases | logging/trace design | `src/qcviz_mcp/llm/trace.py`, `src/qcviz_mcp/services/structure_resolver.py`, `src/qcviz_mcp/web/routes/compute.py` | Makes root-cause analysis slower than necessary |
| `ISSUE-28` | Suspected | `P3` | Boot/runtime drift risk | Different startup scripts and root-path assumptions have historically drifted | `a.sh`, live restart, root path assumptions | boot path config | `a.sh`, `src/qcviz_mcp/web/app.py`, `src/qcviz_mcp/web/runtime_info.py` | Already improved, but still worth tracking |
| `ISSUE-29` | Suspected | `P3` | Local storage persistence coupling | UI snapshots and chat history persist by session key and can become confusing during partial identity changes | long browser sessions | browser persistence | `src/qcviz_mcp/web/templates/index.html`, `src/qcviz_mcp/web/static/app.js` | Especially relevant if a manual new-session button is introduced |
| `ISSUE-30` | Suspected | `P3` | Scientific explanation safety | Explanation-like prompts can be partially coerced into compute-oriented pathways without enough user confirmation | concept questions with molecule-like words | routing / UX policy | `src/qcviz_mcp/llm/normalizer.py`, `src/qcviz_mcp/web/routes/chat.py` | Not always a crash bug, but a user-truthfulness problem |

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

A future “same request -> return prior trusted result” layer is strongly recommended.

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
