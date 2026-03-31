# QCViz Pipeline Benchmark Rerun Checklist

Re-run the benchmark gate whenever one of the following changes:

- planner prompt assets
- provider or model version
- grounding threshold config
- execution guard behavior
- follow-up continuation policy

## Required Checks

1. `pytest -q tests/test_pipeline_benchmark_assets.py`
2. `pytest -q tests/test_semantic_grounding_policy.py`
3. `pytest -q tests/test_chat_semantic_grounded_chat.py`
4. `pytest -q tests/v3/unit/test_pipeline.py`
5. selected chat/compute regression shards

## Required Review Questions

- Did any direct molecule compute path regress into clarification?
- Did any explanation-style semantic query leak into compute?
- Did any follow-up parameter-only request lose structure reuse?
- Did fallback rate or disagreement rate move materially?
