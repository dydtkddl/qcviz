# External Research Prompt

You are reviewing the design of a production-oriented conversational quantum chemistry web platform called QCViz.

## Product Context
- Web-first user experience for experimental chemists.
- Natural-language requests should lead to structure grounding, real PySCF execution, and browser visualization.
- The system already has:
  - a rule-based normalizer and heuristic planner
  - MolChat-based semantic grounding
  - deterministic compute safety gates
- We are moving to an LLM-first prompt pipeline, but we do **not** want to delegate compute safety to the LLM.

## What We Need
Design an enterprise-grade, multi-stage prompt pipeline that improves flexibility while preserving deterministic safety.

## Required Investigation Areas
1. Query rewrite and typo-cleaning stages in production LLM systems
2. Intent routing and action planning in enterprise agent systems
3. Semantic retrieval and entity grounding patterns
4. Structured output failure handling and repair loops
5. Retry and fallback matrices that avoid wobbling
6. Acronym disambiguation UX
7. Explanation-only vs action-intent separation
8. Chemical or biomedical entity-grounding analogs
9. Latency, cost, and observability tradeoffs

## Constraints
- No benchmark-case hardcoding
- No molecule-specific whitelist for direct answers
- No compute submission before structure lock
- No “just use a stronger model” style answers

## Required Deliverables
1. Final architecture for a 4-stage or 5-stage pipeline
2. Stage-by-stage prompt drafts
3. JSON schemas per stage
4. Retry and repair policy
5. Fallback matrix
6. Observability and logging plan
7. Red-team cases and benchmark suite
8. Code patch design that can be applied to an existing Python codebase with:
   - `normalizer.py`
   - `agent.py`
   - `chat.py`
   - `compute.py`
   - MolChat semantic grounding integration

## Output Format
- Executive summary
- Architecture diagram or structured outline
- Stage definitions
- Prompt drafts
- Schemas
- Fallback matrix
- Latency/cost budget
- Benchmark and red-team plan
- Concrete patch design
