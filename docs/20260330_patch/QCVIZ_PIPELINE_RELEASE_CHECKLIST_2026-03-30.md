# QCViz Pipeline Release Checklist

## Before Release

- confirm target model versions are pinned
- confirm prompt asset diffs were reviewed
- confirm `pipeline.py`, `grounding_merge.py`, and `execution_guard.py` tests are green
- confirm benchmark asset suite still exceeds 100 variants
- confirm no benchmark-token hardcoding was introduced in core decision files

## Staging

- enable shadow mode
- keep heuristic serve path primary
- inspect `pipeline.llm_vs_heuristic_agreement.*`
- inspect fallback reasons and lane distribution

## Canary

- set `QCVIZ_PIPELINE_SERVE_LLM=true`
- set `QCVIZ_PIPELINE_CANARY_PERCENT=5`
- hold, inspect metrics, then move to `25`, `50`, `100`

## Blockers

Do not promote if:

- lane-lock violations are non-zero
- guard rejection rate regresses materially
- explanation semantic requests submit compute
- unknown acronym compute requests bypass grounding
