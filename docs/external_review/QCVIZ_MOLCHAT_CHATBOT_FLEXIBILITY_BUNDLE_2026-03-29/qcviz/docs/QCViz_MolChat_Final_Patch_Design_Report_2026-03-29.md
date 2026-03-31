# QCViz + MolChat Final Patch Design Report

## A. Executive Diagnosis

- The actual failure boundary is **not** the final structure resolver call. The break happens earlier, when QCViz converts descriptive user text into a fake “structure-like” candidate and then feeds that candidate into clarification and resolution paths.
- In QCViz, `extract_structure_candidate()` and `build_structure_hypotheses()` are still permissive enough that a descriptive phrase can survive as a candidate string. That candidate then enters `StructureResolver._build_query_plan()` and later `suggest_candidate_queries()`, which currently promotes the raw input at the top of the ranked list.
- The most dangerous specific step is in `qcviz-version03/src/qcviz_mcp/services/structure_resolver.py`: `suggest_candidate_queries()` always inserts the raw query first as `raw_exact` with score `120`. That is correct for true molecule names, but wrong for semantic-descriptor queries.
- QCViz clarification UX compounds the problem. In `qcviz-version03/src/qcviz_mcp/web/routes/chat.py`, the discovery/disambiguation dropdown is built from resolver-backed suggestions, local catalog suggestions, and finally a hardcoded generic fallback list. That is how bad options like the raw phrase itself, or unrelated defaults such as `benzene` / `acetone` / `ethanol`, can appear.
- MolChat’s current **chat** API is not a trustworthy dropdown-candidate source. Its `ChatResponse` is optimized for conversational output, not candidate clarification. `molecules_referenced` is opportunistically derived from tool outputs or regex extraction from the final answer text, so it lacks the contract stability required for QCViz clarification.
- MolChat’s current **molecule search** path is much closer to what QCViz needs: it has structured search results, query resolution metadata, and actual retrievable records. However, it still does not solve descriptive semantics by itself, because `QueryResolver` only returns one resolved query plus string suggestions, and its LLM tier is still “single best English chemical name” rather than “grounded candidate list with ranking and provenance.”
- Current QCViz strengths are real and should be preserved as-is: Hangul spacing/jamo recovery (`베 ㄴ젠`, `베ㄴ젠`), Korean alias canonicalization (`니트로 벤젠`, `니트로벤젠`), follow-up reuse (`ESP도 그려줘`), continuation targeting when no prior structure exists, and ion-pair handling (`EMIM+ TFSI-`).
- Final recommendation: **Hybrid design recommended**. QCViz should keep its current fast-path normalization for direct molecule-like input, but add a new MolChat-backed **semantic candidate interpretation endpoint** for descriptive queries. QCViz should not consume MolChat `/chat` output directly for dropdown generation.

## B. Code-Path Failure Map

### 1. QCViz normalizer path

#### Entry path
- `qcviz-version03/src/qcviz_mcp/llm/normalizer.py`
  - `extract_structure_candidate()`
  - `analyze_structure_input()`
  - `build_structure_hypotheses()`
  - `normalize_user_text()`

#### Current broken behavior
1. `extract_structure_candidate(text)` tries regex extraction over broad sentence patterns such as:
   - `([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)`
   - `([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)`
   These are useful for direct phrases, but they are too permissive for semantic-descriptor phrases.
2. `build_structure_hypotheses()` then mixes:
   - `analysis.canonical_candidates`
   - `analysis.primary_candidate`
   - `extract_structure_candidate(raw)`
   - normalized/transliterated/expanded seeds
   into one `candidate_queries` list.
3. If the descriptive phrase survives `_clean_structure_candidate()` and `_is_plausible_structure_candidate()`, it becomes the `primary_candidate` or at least stays in the candidate list.
4. `normalize_user_text()` later exposes these candidates through:
   - `candidate_queries`
   - `canonical_candidates`
   - `maybe_structure_hint`
   - `structure_needs_clarification`

#### Exact boundary where descriptive text becomes fake molecule candidate
The first dangerous conversion happens inside:
- `qcviz-version03/src/qcviz_mcp/llm/normalizer.py::extract_structure_candidate()`
- then is formalized in:
- `qcviz-version03/src/qcviz_mcp/llm/normalizer.py::build_structure_hypotheses()`

That is the earliest file-level boundary where descriptive text can be reclassified as a structure candidate.

---

### 2. QCViz planner / prepared payload path

#### Entry path
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py`
  - preflight parsing
  - `_detect_ambiguity()`
  - `_explicit_structure_attempt()`
  - `_prepare_or_clarify()`

#### Current broken behavior
1. QCViz uses `normalize_user_text(raw_message)` and planner/prepared payloads to decide whether structure is missing, ambiguous, or explicit.
2. `_explicit_structure_attempt()` is intentionally permissive. It tries:
   - prepared `structure_query`
   - plan `structure_query`
   - `maybe_structure_hint`
   - normalized candidate queries
   - `extract_structure_candidate(raw_message)`
   - even raw message itself
3. The decision logic says: if any candidate looks molecule-like enough, treat it as an explicit structure attempt and switch clarification mode from “discovery” to “disambiguation.”
4. For semantic descriptor queries, that causes the UX to behave like “you typed a molecule approximately” rather than “you described a molecule semantically.”

#### File-level failure boundary
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py::_explicit_structure_attempt()`
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py::_clarification_mode()`

This is where a semantic question gets misclassified into the wrong clarification mode.

---

### 3. QCViz clarification / dropdown construction path

#### Entry path
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py`
  - `_resolver_backed_structure_suggestions()`
  - `_local_structure_suggestions()`
  - `_discovery_structure_suggestions()`
  - `_build_clarification_fields()`
  - `_build_clarification_form()`

#### Current broken behavior
1. `_resolver_backed_structure_suggestions()` calls `resolver.suggest_candidate_queries(cleaned, limit=5)`.
2. `StructureResolver.suggest_candidate_queries()` currently ranks the raw query first:
   - raw query → `raw_exact`, score `120`, source `user_input`
   - translated query → `translated`, score `110`
   - normalized query → `normalized_exact`, score `105`
   - variants after that
3. So once a descriptive phrase has crossed the earlier boundary, it can appear as the top clarification candidate.
4. If resolver-backed suggestions are weak or empty, `_discovery_structure_suggestions()` falls back to `_local_structure_suggestions()` and then to a final generic list:
   - `benzene`
   - `acetone`
   - `ethanol`
5. This violates the “no unrelated generic fallback” requirement for semantic-descriptor queries.

#### File-level failure boundaries
- `qcviz-version03/src/qcviz_mcp/services/structure_resolver.py::suggest_candidate_queries()`
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py::_resolver_backed_structure_suggestions()`
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py::_discovery_structure_suggestions()`
- `qcviz-version03/src/qcviz_mcp/web/routes/chat.py::_build_clarification_fields()`

---

### 4. MolChat chat path

#### Entry path
- `molchat-v3/backend/app/routers/chat.py`
- `molchat-v3/backend/app/services/intelligence/agent.py`
- `molchat-v3/backend/app/schemas/chat.py`

#### Current behavior
1. `/chat` accepts a user message plus optional session/context.
2. `MolChatAgent.chat()` runs LLM + tool calls, then returns `AgentResponse`.
3. `ChatResponse` contains:
   - `message`
   - `molecules_referenced`
   - `tool_results`
   - `confidence`
   - `hallucination_flags`
4. But `molecules_referenced` is assembled by:
   - extracting from tool results with `_extract_molecule_refs()` when a tool returned molecule records, or
   - regex extraction from final assistant text via `_extract_molecules_from_text()`.
5. That means `/chat` does **not** produce a deterministic candidate list suitable for dropdown clarification.

#### Why this matters
QCViz needs a **candidate generation service**, not a conversational answer object. The current chat contract is post-synthesis, partially heuristic, and not provenance-safe enough for molecule disambiguation.

---

### 5. MolChat molecule resolver / search path

#### Entry path
- `molchat-v3/backend/app/services/molecule_engine/query_resolver.py`
- `molchat-v3/backend/app/services/molecule_engine/orchestrator.py`
- `molchat-v3/backend/app/routers/molecules.py`
- `molchat-v3/backend/app/schemas/molecule.py`

#### Current behavior
1. `QueryResolver.resolve(query)` is a 3-tier pipeline:
   - local dictionary
   - PubChem PUG REST exact + autocomplete fallback
   - LLM only for Korean/non-ASCII complex queries
2. Its output is `ResolvedQuery` with:
   - `resolved_query`
   - `method`
   - `confidence`
   - `suggestions`
3. `MoleculeOrchestrator.search()` uses that resolver, then runs actual database search and returns a structured `MoleculeSearchResponse` with:
   - `results`
   - `resolved_query`
   - `original_query`
   - `resolve_method`
   - `resolve_suggestions`
4. This path is structured and grounded, but only for **searchable queries**. It is not yet a semantic-descriptor interpretation pipeline.

#### Important nuance
- `QueryResolver` does include exact alias support such as `tnt -> trinitrotoluene`.
- But `TNT에 들어가는 주물질` is not solved by current `resolve()` because the LLM tier returns one best guess string, not a grounded candidate list, and there is no semantic descriptor schema or candidate validation loop.

## C. Can MolChat Chat Output Be Used For Candidate Dropdowns?

### Final answer
**Hybrid design recommended.**

### Direct justification

#### Why not “Yes, directly”
Do **not** use MolChat `/chat` output directly for dropdown candidates.

Reasons:
1. `molchat-v3/backend/app/schemas/chat.py::ChatResponse` is conversational, not candidate-oriented.
2. `molecules_referenced` in `MolChatAgent` is not guaranteed to be tool-grounded; it may be extracted from free-form response text.
3. `tool_results` in chat are preview-oriented, not a stable candidate contract.
4. There is no per-candidate provenance / rank / identifier / reason object suitable for QCViz clarification.

#### Why not “No, use molecules/search or resolve instead” as the whole answer
Using only `/molecules/search` or `/molecules/resolve` is also insufficient, because descriptive queries are not direct molecule names. QCViz needs one additional semantic interpretation layer to convert descriptor queries into searchable grounded candidates.

### Chosen interpretation
Use a **new MolChat molecule-intelligence contract**, implemented near the molecule engine, not the chat layer:

- keep `/chat` for conversational UX
- keep `/molecules/search` and `/molecules/resolve` for direct structured retrieval
- add a new endpoint such as `/api/v1/molecules/interpret` or `/api/v1/molecules/resolve-candidates`
- implement it with:
  - semantic interpretation
  - grounded retrieval
  - candidate ranking
  - confidence-aware escalation

That is why the answer is **Hybrid design recommended**.

## D. Final Recommended Architecture

### Decision
Use a **two-lane architecture**:

- **Lane A: Direct structure lane** for already molecule-like input
- **Lane B: Semantic descriptor lane** for descriptive queries

### Request flow

```text
User message
   |
   v
QCViz normalizer/planner
   |
   +--> Lane A: direct molecule-like input?
   |       |
   |       +--> existing QCViz path preserved
   |             normalize -> StructureResolver.resolve -> compute
   |
   +--> Lane B: semantic descriptor or low-confidence structure seed?
           |
           +--> MolChat /api/v1/molecules/interpret
                   |
                   +--> semantic intent parse (LLM or resolver-assisted)
                   +--> grounded search phrase generation
                   +--> orchestrator.search() for each phrase
                   +--> merge / dedupe / score / filter candidates
                   +--> return structured candidate objects
           |
           +--> QCViz clarification dropdown
                   |
                   +--> user confirms candidate
                   +--> QCViz StructureResolver.resolve(canonical_name or cid-backed payload)
                   +--> compute
```

### MolChat integration point
**Primary integration point:** new endpoint in `molchat-v3/backend/app/routers/molecules.py`
- recommended route: `POST /api/v1/molecules/interpret`

**Primary service entry:** new method on `MoleculeOrchestrator`
- e.g. `interpret_candidates(query: str, locale: str | None, limit: int, allow_llm: bool)`

**Supporting service:** extend `QueryResolver` with a candidate-mode semantic interpreter
- current `resolve()` remains unchanged for backwards compatibility
- add something like:
  - `interpret_semantic_query()`
  - or `resolve_candidates()`

### QCViz integration point
**Primary integration point:** `qcviz-version03/src/qcviz_mcp/services/molchat_client.py`
- add `interpret_candidates()` client method

**Call site:** `qcviz-version03/src/qcviz_mcp/web/routes/chat.py`
- use only when:
  - no trustworthy direct structure candidate exists, or
  - descriptive/semantic classifier fires, or
  - current hypothesis confidence is below threshold, or
  - raw text contains descriptor patterns like “주성분 / ingredient / used in / 들어가는”

### Candidate generation path

#### Lane A: direct names
- Keep current QCViz normalization and resolver path for:
  - `니트로벤젠`
  - `니트로 벤젠`
  - `베 ㄴ젠`
  - `EMIM+ TFSI-`
  - direct English names, formulas, SMILES

#### Lane B: semantic descriptors
1. QCViz semantic guard detects descriptor query.
2. QCViz does **not** let raw phrase enter `suggest_candidate_queries()`.
3. QCViz calls MolChat `interpret_candidates()`.
4. MolChat semantic interpreter produces **search intents**, not final molecules.
5. MolChat runs grounded search over candidate search phrases.
6. MolChat returns candidate objects only if they correspond to actual retrievable molecules.
7. QCViz uses only those structured candidate objects in dropdown.

### Ranking / filtering logic
Candidate objects returned from MolChat should be ranked by:
1. grounded retrieval success
2. semantic-match confidence
3. exact descriptor-match strength
4. source quality / source multiplicity
5. canonical-name stability
6. charge/composition compatibility

QCViz must then apply UI-side filters:
- remove raw descriptive phrase candidate unless explicitly confirmed by user
- remove candidates with zero grounded identifiers and zero resolver evidence
- remove unrelated generic defaults
- preserve ion-pair composite option when relevant

### Clarification trigger policy

#### Auto-accept
- only when direct molecule lane yields one high-confidence candidate and no semantic ambiguity

#### Ask-for-confirmation
- when semantic lane yields 1–5 grounded candidates
- when there is a direct name but confidence band is medium
- when charge / composition / ion pairing remains ambiguous

#### No-result
- return a **no-grounded-candidate clarification**, not generic molecule suggestions
- ask the user to restate or name the compound more directly

### Final structure-resolution handoff
Once the user selects a candidate:
- QCViz stores candidate payload in clarification session state
- then passes:
  - canonical name
  - optional CID
  - optional canonical SMILES
  - provenance
to `StructureResolver.resolve()`

If CID or SMILES is available, QCViz should bypass raw-name-first ambiguity as much as possible.

## E. Final API Contract Design

### New MolChat endpoint

**Route:** `POST /api/v1/molecules/interpret`

### Request JSON

```json
{
  "query": "TNT에 들어가는 주물질",
  "locale": "ko",
  "max_candidates": 5,
  "mode": "clarification",
  "allow_llm": true,
  "context": {
    "source_system": "qcviz",
    "preserve_ion_pairs": true
  }
}
```

### Response JSON

```json
{
  "query": "TNT에 들어가는 주물질",
  "query_type": "semantic_descriptor",
  "needs_confirmation": true,
  "top_decision": "clarify",
  "semantic_parse": {
    "descriptor_type": "ingredient_of",
    "target_entity": "TNT",
    "target_entity_canonical": "trinitrotoluene",
    "language": "ko",
    "confidence": 0.86
  },
  "candidate_search_phrases": [
    {
      "phrase": "trinitrotoluene precursor",
      "source": "llm_semantic_parse",
      "confidence": 0.74
    },
    {
      "phrase": "2,4,6-trinitrotoluene precursor",
      "source": "llm_semantic_parse",
      "confidence": 0.71
    }
  ],
  "candidates": [
    {
      "display_label": "Toluene",
      "canonical_name": "toluene",
      "cid": 1140,
      "canonical_smiles": "Cc1ccccc1",
      "provenance": {
        "resolver_source": "pubchem_search",
        "matched_via": "semantic_descriptor_grounding"
      },
      "ranking": {
        "score": 0.82,
        "band": "medium"
      },
      "reason": "Grounded candidate from TNT precursor/ingredient semantic search",
      "selection_payload": {
        "name": "toluene",
        "cid": 1140,
        "canonical_smiles": "Cc1ccccc1"
      }
    }
  ],
  "fallback": {
    "kind": "no_unrelated_defaults"
  }
}
```

### Minimal response requirements
Every candidate must include:
- `display_label`
- `canonical_name`
- `provenance`
- `ranking.score`
- `ranking.band`
- `selection_payload`

### Why current MolChat contracts are insufficient

#### `/chat`
Insufficient because it returns conversation artifacts, not candidate artifacts.

#### `/molecules/resolve`
Insufficient because it only maps names to CID and cannot handle semantic descriptors.

#### `/molecules/search`
Closer, but still insufficient alone because semantic descriptor parsing is missing.

### Implementation recommendation
Do **not** overload `/chat`.

Either:
1. add `POST /api/v1/molecules/interpret`, or
2. extend `/molecules/search` with `mode=interpret`.

Final recommendation: **add a dedicated new endpoint**. It keeps search clean and prevents semantic-interpretation complexity from polluting the standard search contract.

## F. Candidate Ranking and Clarification Policy

### 1. `TNT에 들어가는 주물질`

#### Policy
- classify as `semantic_descriptor`
- do not insert raw phrase into QCViz candidate list
- call MolChat `interpret`
- if grounded candidates exist: show confirmation dropdown
- if no grounded candidates: ask user for direct compound name or clearer descriptor

#### No generic fallback
Never show `water`, `benzene`, `acetone`, `ethanol` just because discovery mode triggered.

---

### 2. `니트로벤젠`

#### Policy
- direct structure lane
- QCViz existing normalizer handles this
- no clarification
- resolve directly

---

### 3. `베 ㄴ젠`

#### Policy
- direct structure lane
- keep current Hangul fragment collapse logic
- no clarification if normalized candidate is high-confidence `benzene`

---

### 4. `EMIM+ TFSI-`

#### Policy
- direct/composite lane
- preserve current ion-pair recognition
- do not route into semantic descriptor lane
- do not collapse into a single neutral fallback candidate
- if composition mode needed, ask ion-pair vs separate vs single interpretation

---

### 5. Follow-up with prior context
Example: `ESP도 그려줘`

#### Policy
- preserve current follow-up reuse
- semantic descriptor lane must not run if valid prior structure exists and follow-up context is strong

---

### 6. Follow-up without prior context
Example: `ESP도 그려줘` in a new session

#### Policy
- preserve current continuation-targeting clarification
- do not show semantic descriptor candidates
- ask what previous structure to continue with

---

### Decision thresholds

#### Auto-accept
- direct lane only
- one candidate
- score >= 0.90
- no descriptor ambiguity

#### Ask for confirmation
- score 0.45–0.89
- or multiple grounded candidates
- or semantic descriptor mode

#### Low confidence
- if all candidates < 0.45: do not present a pseudo-authoritative dropdown
- instead return “I could not ground this descriptor into a reliable molecule candidate”

#### No result handling
- no unrelated defaults
- explicit recovery text:
  - “TNT 자체를 말한 것인지, TNT 제조/구성 관련 다른 화합물을 말한 것인지 더 구체적으로 적어주세요.”

## G. File-by-File Final Patch Design

## QCViz changes

### 1. `qcviz-version03/src/qcviz_mcp/llm/normalizer.py`

#### Why
This is where descriptive text first becomes a fake structure candidate.

#### Minimum patch
- Add a semantic-descriptor detector with high-priority patterns, e.g.:
  - `주성분`
  - `주물질`
  - `들어가는`
  - `used in`
  - `ingredient`
  - `compound used in`
  - `made from`
  - `precursor of`
- Add a new analysis field:
  - `descriptor_query_type`
  - `descriptor_target_entity`
  - `descriptor_needs_grounding`
- In `extract_structure_candidate()`:
  - early-return `None` for descriptor queries unless the query also includes a direct confirmed molecule token
- In `build_structure_hypotheses()`:
  - do not add raw descriptive phrases to `candidate_queries`
  - attach semantic flags for downstream routing
- In `normalize_user_text()`:
  - surface semantic-descriptor state explicitly

#### Ideal patch
- Split direct-structure parsing from descriptor parsing into separate helper functions:
  - `_extract_direct_structure_candidate()`
  - `_analyze_semantic_descriptor_query()`
- Keep current direct-name behaviors untouched.

---

### 2. `qcviz-version03/src/qcviz_mcp/services/structure_resolver.py`

#### Why
`suggest_candidate_queries()` currently promotes `raw_query` as top candidate even when raw query is descriptive text.

#### Minimum patch
- Extend `_build_query_plan()` to carry:
  - `query_kind`: `direct_name | formula | composite | semantic_descriptor | unknown`
  - `allow_raw_candidate_promotion: bool`
- In `suggest_candidate_queries()`:
  - if `query_kind == semantic_descriptor`, do **not** add raw query as `raw_exact`
  - do not score descriptive raw text at all
- Add a new method:
  - `async interpret_semantic_candidates(query: str) -> list[dict]`
  - implemented by calling new `MolChatClient.interpret_candidates()`

#### Ideal patch
- Let `StructureResolver` return a structured `QueryPlan` dataclass instead of loose dicts.
- Add support for CID- or SMILES-backed candidate handoff after clarification selection.

---

### 3. `qcviz-version03/src/qcviz_mcp/services/molchat_client.py`

#### Why
QCViz needs a dedicated client method for semantic candidate interpretation.

#### Minimum patch
Add:
- `async interpret_candidates(query: str, locale: str = "ko", max_candidates: int = 5) -> dict`

Target route:
- `POST /api/v1/molecules/interpret`

#### Ideal patch
- add request/response typed wrappers in this module
- validate returned candidate object shape before QCViz UI consumes it

---

### 4. `qcviz-version03/src/qcviz_mcp/web/routes/chat.py`

#### Why
This file currently:
- misclassifies descriptor queries into disambiguation
- builds dropdowns from raw candidates and unrelated defaults

#### Minimum patch
- In `_explicit_structure_attempt()`:
  - return `None` for semantic-descriptor queries unless a direct molecule candidate is separately found
- In `_clarification_mode()`:
  - new mode `semantic_grounding`
- In `_resolver_backed_structure_suggestions()`:
  - if semantic descriptor: call `resolver.interpret_semantic_candidates()` instead of `suggest_candidate_queries()`
- In `_discovery_structure_suggestions()`:
  - remove generic fallback list for semantic-descriptor path
- In `_build_clarification_fields()`:
  - if mode is `semantic_grounding`, dropdown options must come only from structured MolChat candidate objects
  - option values should store canonical payload, not just free text name
- In clarification session state:
  - store `selection_payload` from MolChat candidate object

#### Ideal patch
- split clarification candidate generation into three explicit functions:
  - direct-name disambiguation
  - semantic grounding
  - discovery fallback for truly unspecified molecule requests

---

### 5. `qcviz-version03/src/qcviz_mcp/llm/schemas.py`

#### Why
Current plan schema has no explicit semantic-descriptor fields.

#### Minimum patch
Add:
- `query_kind: Optional[str]`
- `descriptor_query_type: Optional[str]`
- `descriptor_target_entity: Optional[str]`
- `semantic_grounding_needed: bool = False`
- `structured_candidates: List[Dict[str, Any]] = Field(default_factory=list)`

#### Ideal patch
- define a typed `StructuredCandidate` schema instead of raw dicts

---

### 6. `qcviz-version03/tests/test_chat_api.py`

#### Why
Current tests cover many hardened direct-name/follow-up cases, but not the unresolved semantic-descriptor failure boundary.

#### Minimum patch
Add tests for:
- `TNT에 들어가는 주물질`
  - returns clarification
  - mode is `semantic_grounding`
  - dropdown does not contain raw phrase
  - dropdown does not contain unrelated generic defaults
- `폭약 TNT의 주성분`
  - same
- semantic no-result
  - no grounded candidates
  - explicit non-generic recovery prompt

---

### 7. `qcviz-version03/tests/v3/unit/test_structure_resolver.py`

#### Why
Need unit-level protection on query planning and raw-query promotion.

#### Minimum patch
Add tests verifying:
- semantic descriptor query produces `query_kind == semantic_descriptor`
- `suggest_candidate_queries()` does not include raw descriptive phrase
- direct-name cases still preserve existing behavior

---

## MolChat changes

### 1. `molchat-v3/backend/app/services/molecule_engine/query_resolver.py`

#### Why
Current resolver can return one resolved query, but not a grounded candidate set for semantic descriptors.

#### Minimum patch
Add a new semantic interpretation path:
- `async interpret_semantic_query(query: str) -> dict`

Responsibilities:
- classify descriptor type
- detect target entity
- produce candidate search phrases
- when using LLM, require structured JSON output
- do **not** emit final molecule candidates yet

#### Ideal patch
- add a `SemanticInterpretation` dataclass
- keep existing `resolve()` unchanged for backwards compatibility

---

### 2. `molchat-v3/backend/app/services/molecule_engine/orchestrator.py`

#### Why
Grounded candidate generation belongs near search orchestration, not in chat synthesis.

#### Minimum patch
Add:
- `async interpret_candidates(query: str, locale: str | None = None, limit: int = 5) -> dict`

Flow:
1. call `QueryResolver.interpret_semantic_query()`
2. for each generated search phrase:
   - call existing `search()`
3. merge candidate records
4. dedupe by CID / canonical_smiles / normalized name
5. score candidates
6. return structured response for clarification

#### Ideal patch
- separate ranking/filtering helper methods:
  - `_score_interpret_candidate()`
  - `_dedupe_interpret_candidates()`
  - `_to_clarification_candidate()`

---

### 3. `molchat-v3/backend/app/routers/molecules.py`

#### Why
Need a public structured API for QCViz.

#### Minimum patch
Add new route:
- `POST /interpret`

Request body:
- query
- locale
- max_candidates
- mode
- allow_llm
- context

Response body:
- query metadata
- semantic parse
- candidate search phrases
- grounded candidates
- fallback metadata

#### Ideal patch
- keep `/search` and `/resolve` untouched
- document `/interpret` separately as QCViz-facing contract

---

### 4. `molchat-v3/backend/app/schemas/molecule.py`

#### Why
Need typed request/response models for the new endpoint.

#### Minimum patch
Add:
- `MoleculeInterpretRequest`
- `MoleculeInterpretCandidate`
- `MoleculeInterpretResponse`

Required candidate fields:
- `display_label`
- `canonical_name`
- `cid`
- `canonical_smiles`
- `provenance`
- `ranking`
- `reason`
- `selection_payload`

---

### 5. `molchat-v3/backend/app/routers/chat.py`

#### Why
Mostly to document and preserve separation, not to become the integration point.

#### Minimum patch
- no behavioral integration change required
- optional: add explicit comment/docs that `/chat` is not the candidate-clarification contract

---

### 6. `molchat-v3/backend/app/services/intelligence/agent.py`

#### Why
Avoid future misuse.

#### Minimum patch
- no core logic change required for this patch
- optional logging note or docstring that `molecules_referenced` is advisory, not canonical for structure disambiguation

---

### 7. MolChat tests

Add / modify:
- router test for `/api/v1/molecules/interpret`
- unit tests for semantic interpretation and candidate grounding
- failure tests for no grounded candidate
- regression tests for exact-name paths remaining unchanged

## H. Test Plan

### 1. Unit tests

#### QCViz normalizer
- `TNT에 들어가는 주물질`
  - semantic descriptor detected
  - no direct structure candidate emitted
- `폭약 TNT의 주성분`
  - same
- `니트로벤젠`
  - still direct candidate `nitrobenzene`
- `베 ㄴ젠`
  - still direct candidate `benzene`
- `EMIM+ TFSI-`
  - still composite/ion-pair

#### QCViz resolver
- semantic descriptor query
  - `suggest_candidate_queries()` excludes raw descriptive phrase
- direct-name query
  - raw query still present when appropriate

#### MolChat query resolver / orchestrator
- exact alias (`TNT`) still resolves to `trinitrotoluene`
- semantic descriptor query produces search phrases, not hallucinated final molecule
- no grounded match returns empty candidates with `needs_confirmation=true`

---

### 2. API tests

#### QCViz `/api/chat`
- `TNT에 들어가는 주물질`
  - response has `requires_clarification == true`
  - `clarification_kind == semantic_grounding`
  - `structure_choice` options exclude raw phrase
  - exclude unrelated generic defaults

#### MolChat `/api/v1/molecules/interpret`
- returns typed response schema
- candidate list contains provenance/ranking/payload
- handles no-result cleanly

---

### 3. End-to-end clarification tests

#### Semantic grounding round-trip
1. user sends `TNT에 들어가는 주물질`
2. QCViz asks semantic-grounding clarification
3. user selects candidate
4. QCViz executes structure resolution and compute
5. result payload uses selected canonical structure, not raw phrase

#### Direct-name round-trip preservation
- `니트로 벤젠 ESP 보여줘`
  - still runs without clarification

#### Follow-up preservation
- session: `benzene HOMO 보여줘`
- follow-up: `ESP도 그려줘`
  - still reuses previous structure without semantic-grounding detour

---

### 4. Failure-mode tests

- MolChat interpret endpoint times out
  - QCViz shows safe clarification failure, not generic fallback
- MolChat returns malformed candidate object
  - QCViz rejects invalid candidate list and shows safe recovery message
- low-confidence candidate set only
  - QCViz refuses auto-accept

## I. Rollout / Backward Compatibility

### Feature flag
Recommended: yes.

#### MolChat
- `MOLCHAT_ENABLE_INTERPRET_ENDPOINT=true`

#### QCViz
- `QCVIZ_ENABLE_MOLCHAT_SEMANTIC_GROUNDING=true`

### Migration order
1. Ship MolChat new endpoint and schemas first.
2. Validate endpoint independently.
3. Ship QCViz client integration behind flag.
4. Enable only for semantic-descriptor queries.
5. Expand after observing logs.

### Backward compatibility strategy
- keep all existing endpoints unchanged:
  - `/chat`
  - `/molecules/search`
  - `/molecules/resolve`
  - `/molecules/card`
- keep current QCViz direct-name lane unchanged
- only new semantic lane uses new contract

### Fallback policy
If new endpoint unavailable:
- direct-name lane still works
- semantic-descriptor lane should return safe clarification error
- do not fall back to unrelated discovery defaults

## J. Residual Risks

- Some semantic descriptors are genuinely open-world knowledge problems rather than molecule lookup problems. Example: “the main ingredient used in X” may depend on manufacturing context, composition framing, or domain-specific convention.
- Even with grounding, some descriptor queries can produce multiple chemically plausible answers. The patch improves trustworthiness, but cannot eliminate domain ambiguity.
- MolChat LLM semantic parsing still needs strict structured-output prompting and post-validation. If that layer drifts, candidate phrase generation quality will degrade.
- If upstream data sources do not return high-quality results for a descriptor-derived search phrase, the system may still fail to produce candidates. That is acceptable as long as it fails safely and does not hallucinate.
- Session UX for semantic clarification may need a second refinement round after real-user traffic, especially around multilingual explanation text and ranking transparency.

## Final decision summary

- **Do not** use MolChat `/chat` directly for QCViz clarification dropdowns.
- **Do** keep QCViz’s current direct-name hardening path.
- **Do** add a dedicated MolChat molecule-interpretation endpoint that returns grounded structured candidates.
- **Do** route only semantic-descriptor queries through that new endpoint.
- **Do** remove raw descriptive phrase promotion and unrelated generic fallback from the semantic clarification path.
