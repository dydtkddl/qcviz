# QCViz Pipeline Heuristic Failover Runbook

## Trigger Conditions

Switch to heuristic-primary mode immediately when one or more are true:

- `pipeline.stage2.fallback_rate` rises above the agreed threshold
- provider outage or authentication failure affects the planner path
- `pipeline.lane_lock_violation_rate` is non-zero
- `pipeline.guard_rejection_rate` spikes unexpectedly after a prompt/model change

## Immediate Actions

1. Set `QCVIZ_PIPELINE_FORCE_HEURISTIC=true`
2. Keep `QCVIZ_PIPELINE_ENABLED=true` only if shadow traces are still useful
3. Disable `QCVIZ_PIPELINE_SERVE_LLM`
4. Keep `QCVIZ_PIPELINE_SHADOW_MODE=true` only if provider stability allows shadow comparison

## Validate

Run:

- `pytest -q tests/test_compute_api.py`
- `pytest -q tests/test_chat_api.py -k "semantic_descriptor or unknown_acronym or analysis_only_followup"`
- `pytest -q tests/v3/unit/test_pipeline.py`

## Recovery Checklist

- confirm provider status
- inspect recent trace logs for fallback reasons
- compare lane distribution before and after the incident
- rerun benchmark assets before re-enabling serve mode
