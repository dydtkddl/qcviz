# QCViz Enterprise LLM Pipeline Plan

## Goal
- Make the primary interpretation path LLM-first.
- Keep compute submission behind deterministic validation.
- Fall back to the existing rule-based stack without wobbling when LLM quality is low.

## Architecture
1. Stage 1: Ingress Rewrite
   - Fix spacing, noise, and obvious typos.
   - Preserve scientific tokens.
2. Stage 2: Semantic Expansion
   - Generate short semantic variants for grounding and explanation.
3. Stage 3: Action Planner
   - Produce the execution lane and structured plan.
4. Execution Guard
   - Allow compute only when the structure and required slots are fully locked.

## Current Rollout
- `QCVIZ_ENABLE_LLM_PIPELINE`
  - Turns on the pipeline coordinator.
- `QCVIZ_LLM_PIPELINE_STAGE1`
  - Enables LLM ingress rewrite.
- `QCVIZ_LLM_PIPELINE_STAGE2`
  - Enables LLM semantic expansion.
- `QCVIZ_LLM_PIPELINE_STAGE3`
  - Enables LLM-first planner routing.
- `QCVIZ_LLM_PIPELINE_FORCE_HEURISTIC`
  - Forces deterministic fallback.
- `QCVIZ_LLM_PIPELINE_REPAIR_MAX`
  - Limits repair attempts per stage.

## Deterministic Guarantees
- Each stage gets one repair attempt at most.
- After repair failure, the turn is locked to heuristic fallback.
- A chat-only turn is never promoted to compute-ready inside the same turn.
- A grounding-required turn cannot bypass structure lock.
- Compute safety stays in the existing route guard.

## Code Touchpoints
- [pipeline.py](D:/20260305_양자화학시각화MCP서버구축/version03/src/qcviz_mcp/llm/pipeline.py)
- [agent.py](D:/20260305_양자화학시각화MCP서버구축/version03/src/qcviz_mcp/llm/agent.py)
- [schemas.py](D:/20260305_양자화학시각화MCP서버구축/version03/src/qcviz_mcp/llm/schemas.py)
- [compute.py](D:/20260305_양자화학시각화MCP서버구축/version03/src/qcviz_mcp/web/routes/compute.py)

## Next Steps
- Centralize semantic grounding outcome consumption in the routes.
- Add observability counters for stage success, repair, and fallback reasons.
- Shadow-run Stage 1 and Stage 2 in staging before turning them on broadly.
