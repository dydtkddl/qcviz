# QCViz + MolChat External Research and Final Patch Design Prompt

## Mission

You are an external senior software architect / research engineer agent.  
Your task is **not** to produce a light review or a draft.  
Your task is to perform:

1. a **full market/standards scan** of current commercial MCP-capable and LLM service ecosystems,  
2. a **full codebase scan** of the attached QCViz + MolChat core bundle,  
3. a **full user-experience diagnosis** of the current conversational quantum-chemistry workflow, and  
4. a **final, implementation-ready patch design** that can be handed off directly for coding.

You must operate in autonomous mode.  
Do not stop at “possible ideas.”  
Do not give a shallow summary.  
Do not return a brainstorm.  
Return a decision-complete design.

---

## Mandatory Inputs

You will receive the following attachments:

1. `QCVIZ_MOLCHAT_ISSUE_LOOKUP_TABLE_2026-03-30.md`
   - This contains the accumulated issue list, current status, symptoms, and suspected causes.

2. `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip`
   - This contains the current QCViz core Python code, MolChat core backend code, and dependent logic files.

3. Optional supporting documents if attached
   - previous patch design reports
   - runtime debug prompts
   - deep scan reports

You must read all attached materials before concluding anything.

---

## Non-Negotiable Execution Order

You must follow this order exactly.

### Phase 1. Commercial MCP + LLM ecosystem scan first

Before touching the code, research the current commercial ecosystem.

You must investigate the latest state of:

- Anthropic / Claude ecosystem
  - Claude API
  - Claude Desktop
  - Claude Code
  - any official or ecosystem MCP support patterns

- OpenAI ecosystem
  - ChatGPT
  - OpenAI API
  - function calling
  - structured outputs
  - tool calling patterns
  - agent/runtime patterns relevant to scientific tools

- Google ecosystem
  - Gemini API
  - tool calling / function calling patterns
  - structured response or schema guidance

- Microsoft / Azure ecosystem
  - Copilot / Azure AI relevant tool orchestration patterns

- commercial coding / agent products where MCP-like tool orchestration matters
  - Cursor
  - Windsurf
  - Perplexity if relevant
  - any other major commercial LLM product with strong tool integration or MCP-adjacent workflows

For this phase:

- prioritize official docs and primary sources
- use recent sources only
- identify what “good” MCP / tool-calling / structured-output UX looks like today
- identify current best practices for:
  - tool routing
  - structured outputs
  - schema validation
  - clarification flows
  - direct-answer vs tool-execution separation
  - stateful conversation + tool invocation

Output a short but concrete “commercial best-practice baseline” that will later be used to judge QCViz.

---

### Phase 2. Scan the attached code bundle completely

Read the attached ZIP contents thoroughly.

At minimum, inspect and connect the logic of:

- QCViz LLM / normalization / planning layer
- QCViz web chat routes
- QCViz compute submission path
- QCViz clarification building and slot merge logic
- QCViz frontend chat state / clarification rendering if included
- MolChat molecule interpret / search / resolve paths
- MolChat query resolver / orchestrator / molecule schemas
- relevant tests

You must trace end-to-end flows for at least these user messages:

1. `벤젠의 HOMO 오비탈을 보여줘`
2. `TNT에 들어가는 주물질이 뭐지?`
3. `MEA라는 물질이 뭐야?`
4. `MEA HOMO 보여줘`
5. `ESP도 보여줘`
6. a multi-molecule paragraph request

For each, determine:

- chat_only or compute intent
- semantic grounding need
- clarification policy
- structure lock policy
- compute submit policy
- result binding policy
- expected ideal UX
- actual current UX

---

### Phase 3. Evaluate current user experience brutally honestly

You must evaluate the current UX from the perspective of a real experimental chemistry user.

You are not allowed to stop at backend correctness.

You must explicitly judge:

- whether the system feels like a chatbot
- whether it feels too compute-centric
- whether explanation questions are handled naturally
- whether high-confidence single-candidate semantic queries should use direct answer instead of picker UI
- whether clarification is overused
- whether clarification cards are too technical
- whether dropdown labels are too verbose or too raw
- whether current behavior inspires trust or confusion

You must separate:

- technically correct behavior
- scientifically safe behavior
- conversationally natural behavior

These are not the same thing.

---

### Phase 4. Produce a final patch design, not a draft

Your final output must be an implementation-ready patch design.

It must include:

1. Final architectural direction
   - exact routing model
   - exact precedence rules
   - exact chat vs grounding vs compute boundaries

2. State machine
   - `chat_only`
   - `grounding_required`
   - `compute_ready`
   - structure lock
   - continuation
   - clarification lifecycle
   - result binding lifecycle

3. JSON / websocket / UI contract
   - payload fields
   - event fields
   - dropdown option contract
   - direct grounded answer contract
   - clarification contract

4. File-level patch design
   - which files change
   - what exact behavior changes in each file
   - what should be removed
   - what should be added

5. UX policy
   - when to direct-answer
   - when to ask clarification
   - when to compute
   - when to refuse compute and stay in explanation mode
   - when to lock structure
   - when to reuse prior structure

6. Test design
   - unit tests
   - API tests
   - websocket tests
   - Playwright tests
   - regression scenarios

7. Rollout / migration strategy
   - safest order of patching
   - feature flags if needed
   - backward compatibility concerns
   - runtime diagnostics

---

## Critical Problem Focus

You must directly and explicitly solve these priority issues:

- explanation-style semantic queries such as `MEA라는 물질이 뭐야?` must not go into compute/resolve error paths
- single high-confidence semantic grounding results such as `TNT에 들어가는 주물질이 뭐지?` should be evaluated for direct-answer behavior, not blindly routed to picker UI
- unknown acronym compute requests such as `MEA HOMO 보여줘` must not bypass grounding
- semantic descriptor flows must never show unrelated generic fallbacks like `water`, `benzene`, `ethanol`
- raw descriptive phrases must never be revived as candidate options
- canonical candidate selection must not trigger a second composition clarification
- stale turn/job contamination and chat history confusion must be prevented
- Korean clarification strings and UX copy must be audited for corruption / mojibake

---

## Research Discipline Rules

- Do not guess if the code can answer the question.
- Do not rely on old memory for MCP/LLM product facts.
- Use official sources first for commercial ecosystem scanning.
- When comparing against QCViz, distinguish:
  - market best practice
  - current code reality
  - ideal target design

If you infer something rather than directly observe it, mark it as inference.

---

## Required Output Format

Return one integrated Markdown report with these sections:

1. Executive diagnosis
2. Commercial MCP / LLM ecosystem baseline
3. Current QCViz + MolChat architecture diagnosis
4. UX evaluation
5. Root-cause matrix
6. Final patch design
7. File-level change plan
8. Test and validation plan
9. Rollout / migration plan
10. Residual risks

This is not a short memo.
This is not a brainstorming note.
This is the final design specification for implementation.

---

## Success Criteria

Your output is successful only if another engineer could implement it without making product decisions on their own.

That means your design must be:

- technically concrete
- UX-decision complete
- state-machine explicit
- file-change explicit
- testable
- rollout-safe

If your result still says “could”, “might”, or “one option is” in too many places, it is not complete enough.
