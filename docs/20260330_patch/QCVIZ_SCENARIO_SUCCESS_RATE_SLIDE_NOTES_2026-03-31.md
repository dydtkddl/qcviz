# End-to-End Success Rate Across Scenarios

## Recommended framing

If the slide title stays as **"End-to-End Success Rate Across Scenarios"**, only include rows that are backed by executed tests.

If you want to show the broader asset pack as well, use a subtitle like:

> Executed route benchmarks plus prepared benchmark coverage

This keeps the claim honest.

## Defensible numbers right now

### Slide table

| Scenario | What it validates | Current result | Evidence |
|---|---|---:|---|
| Semantic explanation queries | explanation-only chemistry questions do not leak into compute | **12 / 12 passed** | `tests/test_chat_semantic_grounded_chat.py` explanation benchmark |
| Semantic compute with ambiguous names | ambiguous or acronym-based compute requests require grounding first | **12 / 12 passed** | `tests/test_chat_semantic_grounded_chat.py` compute benchmark |
| Benchmark asset integrity | benchmark suite shape and total coverage are valid | **2 / 2 passed** | `tests/test_pipeline_benchmark_assets.py` |
| Prepared benchmark coverage | total benchmark variants prepared across datasets | **102 variants** | `tests/assets/*.json` |

### Prepared but not yet fully reported as end-to-end rates

| Dataset | Variants | Category summary |
|---|---:|---|
| `semantic_explanation_benchmark` | 12 | semantic explanation, single-candidate semantic, multi-candidate semantic |
| `semantic_compute_benchmark` | 12 | semantic compute, unknown acronym compute, multi-candidate semantic |
| `direct_molecule_compute_benchmark` | 30 | direct molecule compute |
| `follow_up_parameter_only_benchmark` | 24 | parameter-only follow-up |
| `red_team_benchmark` | 24 | bare acronym, compound request, concept question, garbage input, missing-structure compute, no-context follow-up |

## Suggested slide version

### Option A: strict and honest

Use only the executed rows:

| Scenario | Success rate |
|---|---:|
| Semantic explanation queries | **100%** (12 / 12) |
| Semantic compute with grounding | **100%** (12 / 12) |
| Benchmark asset validation | **100%** (2 / 2) |

Callout under the table:

> Additional benchmark coverage is prepared across **102 variants** in 5 datasets, including direct-molecule compute, follow-up, and red-team cases.

### Option B: broader but careful

| Scenario group | Status |
|---|---|
| Semantic explanation benchmark | **12 / 12 passed** |
| Semantic compute benchmark | **12 / 12 passed** |
| Direct molecule compute benchmark | **30 variants prepared** |
| Follow-up parameter-only benchmark | **24 variants prepared** |
| Red-team benchmark | **24 variants prepared** |

This version is safer if you want to emphasize test coverage growth rather than overclaim finished pass rates.

## Speaker note

Recommended wording:

> Rather than saying only that the system works well, we evaluated it by scenario.  
> At the moment, the semantic explanation benchmark and the semantic compute benchmark both pass all current route-level cases, 12 out of 12 each.  
> In parallel, we have already prepared a broader benchmark suite with 102 variants covering direct molecule compute, parameter-only follow-up, and red-team inputs.  
> So the point is not only that the core path works, but that the validation is being organized as a scenario-based benchmark, not as a single demo.

## Important caveat before final presentation

One governance-style anti-hardcode check is currently failing:

- `tests/test_semantic_grounding_anti_hardcode.py`
- reason: a TNT-specific decision branch still exists in `src/qcviz_mcp/web/routes/chat.py`

That means:

- the semantic benchmark pass rates above are still defensible
- but the broader claim of "no benchmark-token hardcoding" is **not** yet presentation-safe until that regression is fixed

## Raw dataset counts

These counts were computed from the benchmark asset JSON files in `tests/assets`.

- Semantic explanation: 12 variants
- Semantic compute: 12 variants
- Direct molecule compute: 30 variants
- Follow-up parameter-only: 24 variants
- Red-team: 24 variants
- Total: **102 variants**
