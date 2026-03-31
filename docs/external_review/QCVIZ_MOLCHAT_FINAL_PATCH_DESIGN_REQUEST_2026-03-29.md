# QCViz + MolChat Integration Hardening Request

## Mission

You are being asked to produce a **final patch design**, not a draft, for a real integration problem between:

- `QCViz version03`
- `MolChat v3`

The goal is to make molecule resolution and clarification behave correctly for **descriptive user queries**, **non-canonical molecule mentions**, **Korean chemistry input**, and **LLM-assisted molecule candidate dropdown generation**.

You must treat this as an implementation handoff request for a production-facing research tool.  
Do **not** answer with vague brainstorming, generic product advice, or “possible ideas only.”  
You must read the attached code and produce a **concrete, file-level, implementation-ready final patch design**.

---

## What Is Attached

You will receive:

1. A ZIP bundle containing the relevant code from both repositories:
   - `QCViz version03`
   - `MolChat v3`
2. Deep scan reports for both repositories
3. This markdown instruction file

The ZIP is intentionally scoped to the code paths relevant to:

- user natural-language molecule interpretation
- structure normalization
- candidate suggestion / dropdown clarification
- MolChat chat and molecule-orchestration flows
- QCViz chat / compute preparation and follow-up handling
- existing tests for these behaviors

---

## Core Problem To Solve

At the moment, QCViz can still fail badly on descriptive molecule requests such as:

- `TNT에 들어가는 주물질`
- `TNT에 들어가는 주 물질`
- `폭약 TNT의 주성분`
- `니트로벤젠`
- `니트로 벤젠`
- `베 ㄴ젠`
- `EMIM+ TFSI-`

The system currently has partial hardening for Korean spacing noise, alias recovery, follow-up reuse, and ion-pair handling.  
However, it still breaks on **descriptive semantic references** where the user is **not naming the molecule directly**, but is instead describing it.

Example failure pattern:

- User asks something like `TNT에 들어가는 주물질`
- The planner/normalizer heuristics incorrectly treat the whole phrase as a molecule-like structure query
- QCViz may:
  - compute something unrelated or semi-related
  - ask a malformed clarification question
  - present the raw phrase itself as a dropdown candidate
  - include bad fallback candidates such as `water`
- The resulting UX is not trustworthy

This must be redesigned properly.

---

## Key Architectural Question

MolChat v3 appears to have a richer conversation and molecule-resolution stack than QCViz:

- `backend/app/services/intelligence/agent.py`
- `backend/app/services/molecule_engine/query_resolver.py`
- `backend/app/services/molecule_engine/orchestrator.py`
- `backend/app/routers/chat.py`
- `backend/app/routers/molecules.py`
- `backend/app/schemas/chat.py`

The specific question is:

> When QCViz receives descriptive queries like “the main ingredient used in TNT,” can it use MolChat’s chatbot/molecule-intelligence path to obtain structured molecule candidates and then build the clarification dropdown from that result?

You must answer this based on the attached code, not on assumptions.

If the answer is yes:

- specify exactly **which MolChat route/service/schema path** should be integrated
- specify exactly **what structured response contract** QCViz should consume
- specify exactly **how QCViz should rank, filter, and present candidates**

If the answer is no:

- explain precisely why not
- identify the closest workable MolChat path
- provide the final alternative integration design

---

## Non-Negotiable Requirements

Your design must satisfy all of the following:

### 1. No raw descriptive phrase as final molecule candidate

Queries like:

- `TNT에 들어가는 주물질`
- `TNT main ingredient`
- `the compound used in TNT`

must **not** be treated as literal molecule names unless explicitly confirmed by the user.

### 2. No unrelated generic fallback

If the system does not know the answer, it must **not** jump to unrelated defaults like:

- `water`
- generic common-molecule pickers

Unrelated fallback suggestions are considered a design failure.

### 3. Minimize dictionary-only behavior

Do not propose a solution that is primarily:

- adding more hardcoded aliases
- adding bigger rule dictionaries
- adding more regex-only exceptions

Rule-based normalization can still exist, but the **main improvement path** should rely on:

- grounded search / resolver orchestration
- structured outputs
- confidence-aware candidate generation
- safe clarification policy

### 4. LLM must not hallucinate molecule identity

The design must clearly separate:

- semantic interpretation
- candidate retrieval
- candidate ranking
- user confirmation
- actual structure resolution

If LLM reasoning is used, it must be **grounded into actual retrievable molecule candidates** before QCViz proceeds.

### 5. Preserve current strengths

Your proposed design must not regress the current hardened behaviors already present in QCViz, including:

- Korean noise recovery such as `베 ㄴ젠`, `베ㄴ젠`
- canonicalization of `니트로 벤젠` / `니트로벤젠`
- follow-up reuse like `ESP도 그려줘`
- continuation targeting when there is no prior structure
- ion-pair recognition like `EMIM+ TFSI-`

### 6. Dropdown candidates must be structured and defensible

A clarification dropdown should be built from a **structured candidate object list**, not from free text alone.

Each candidate should ideally have:

- display label
- canonical name
- provenance/source
- confidence score or ranking band
- optional explanation/reason
- optional identifier payload usable in the next step

### 7. Korean + mixed-language chemistry input must remain first-class

The final design must explicitly account for:

- Korean molecule aliases
- mixed Korean/English names
- descriptive Korean semantic questions
- formula + alias mixed input
- charged species / ion-pair expressions

---

## What You Must Deliver

Produce a **single final report** in Markdown with the following sections.

### A. Executive Diagnosis

- What is the actual failure boundary?
- Why is the current QCViz behavior wrong?
- Which parts are already good and should be preserved?

### B. Code-Path Failure Map

Trace the current broken path end to end using the attached code.

At minimum, cover:

- `QCViz` normalizer path
- `QCViz` planner/prepared payload path
- `QCViz` clarification / dropdown construction path
- `MolChat` chat path
- `MolChat` molecule resolver / search path

You must identify the exact file-level boundary where descriptive text becomes a fake molecule candidate.

### C. Can MolChat Chat Output Be Used For Candidate Dropdowns?

Give a direct answer:

- `Yes, directly`
- `Yes, but only through a transformed structured contract`
- `No, use molecules/search or resolve instead`
- `Hybrid design recommended`

Then justify that answer with actual code evidence.

### D. Final Recommended Architecture

Describe the final architecture you recommend.

This section must include:

- request flow
- MolChat integration point
- QCViz integration point
- candidate generation path
- ranking / filtering logic
- clarification trigger policy
- final structure-resolution handoff

Use an ASCII diagram.

### E. Final API Contract Design

Define the exact request/response shape QCViz should consume from MolChat.

If MolChat’s current contract is insufficient, define:

- the minimal new response schema
- which existing endpoint should be extended
- or whether QCViz should call multiple MolChat endpoints

You must include example JSON payloads.

### F. Candidate Ranking and Clarification Policy

Specify the final policy for:

- direct auto-accept
- ask-for-confirmation
- ambiguity escalation
- no-result handling
- low-confidence handling

You must explicitly cover:

- `TNT에 들어가는 주물질`
- `니트로벤젠`
- `베 ㄴ젠`
- `EMIM+ TFSI-`
- follow-up requests with and without prior context

### G. File-by-File Final Patch Design

This is the most important section.

List the exact files to change in:

#### QCViz

- which file
- why it changes
- what exact logic must be added/removed/refactored

#### MolChat

- which file
- why it changes
- what exact logic/schema/endpoint behavior must change

Do not stop at module-level statements.  
This must be detailed enough that an implementation engineer can patch from it.

### H. Test Plan

Define the full regression test plan.

You must include:

- unit tests
- API tests
- end-to-end clarification tests
- failure-mode tests

Include concrete test cases and expected results.

### I. Rollout / Backward Compatibility

Explain how to ship this safely:

- feature flag or not
- fallback policy
- API compatibility strategy
- migration order between MolChat and QCViz

### J. Residual Risks

State what remains hard even after the patch.

---

## Strict Output Rules

- Do **not** give a draft.
- Do **not** answer with “possible options” only.
- You may compare alternatives briefly, but you must choose one final design.
- Every important claim must tie back to attached code paths.
- Use actual file paths from the attached repositories.
- Prefer implementation-specific language over abstract product language.
- If a current MolChat path is too unstable to trust, say so explicitly and propose the final replacement path.

---

## Important Context From Current QCViz State

QCViz has already been partially hardened in these areas:

- Korean spacing/jamo normalization
- candidate filtering to reduce raw-task-string promotion
- follow-up continuation handling
- ion-pair preservation
- clarification-mode branching

So this task is **not** “start molecule resolution from scratch.”

This task is:

> finish the hardening by solving the unresolved semantic-descriptor problem properly, and define the final cross-system patch architecture between QCViz and MolChat.

---

## What A Good Final Answer Looks Like

A good answer should read like:

- a senior architect reviewed both codebases,
- decided exactly where the MolChat integration belongs,
- defined the exact contract,
- specified the exact QCViz and MolChat patches,
- and left behind a design that can be implemented without another design round.

That is the bar.
