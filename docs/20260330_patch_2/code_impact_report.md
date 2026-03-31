# Code Impact Report

Date: 2026-03-30

## Executive Summary

- No default functional in the upgraded lookup is blocked by the current runtime.
- The production JSON can be shipped without changing `dft_accuracy_table.json`.
- Three alternatives intentionally remain non-production or caution-only:
  - `wB97X-D`
  - `r2SCAN-3c`
  - `PWPB95-D3(BJ)`

## Files Reviewed

- `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
- `src/qcviz_mcp/advisor/preset_recommender.py`
- `src/qcviz_mcp/advisor/confidence_scorer.py`
- `src/qcviz_mcp/web/advisor_flow.py`
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `src/qcviz_mcp/advisor/reference_data/dft_accuracy_table.json`

## Implemented Compatibility Changes

### 1. Functional normalization

- `reference_data/__init__.py`
  - `normalize_func_key(...)` now strips leading unrestricted/restricted prefixes (`U*`, `R*`) before accuracy-table normalization.
  - This fixes scoring parity for labels such as `UB3LYP-D3(BJ)` and `UM06-2X-D3(0)`.

### 2. Advisor preset to PySCF `xc` conversion

- `preset_recommender.py`
  - added `_functional_to_pyscf_xc(...)`
  - strips advisor-only suffixes (`-D3(BJ)`, `-D3(0)`, `-D4`, `-NL`)
  - recognizes `B3LYP`, `PBE0`, `TPSSh`, `TPSS`, `r2SCAN`, `M06-2X`, `wB97X-D`, `wB97X-V`, `PW6B95`

### 3. Advisor flow to compute runner method mapping

- `web/advisor_flow.py`
  - added `_ADVISOR_XC_TO_RUNNER_METHOD`
  - added `_advisor_functional_to_runner_method(...)`
  - prevents raw advisor labels such as `UM06-2X-D3(0)` from leaking unchanged into runner kwargs

### 4. Compute runner alias expansion

- `compute/pyscf_runner.py`
  - added aliases for `wB97X-V`, `TPSSh`, `TPSS`, `r2SCAN`, `PW6B95`

### 5. Script / citation consistency

- `advisor/script_generator.py`
  - now strips `-D3(0)` and unrestricted prefixes when building executable script snippets
- `advisor/methods_drafter.py`
  - now resolves unrestricted advisor labels and recognizes `wB97X-D` citation mapping

## Functional Impact Matrix

| Functional label in lookup | Used as default | Normalized accuracy key | Advisor `xc` conversion | Accuracy table entry | Status |
| --- | --- | --- | --- | --- | --- |
| `B3LYP-D3(BJ)` | yes | `B3LYP` | `b3lyp` | yes | safe |
| `UB3LYP-D3(BJ)` | yes | `B3LYP` | `b3lyp` | yes | safe after unrestricted-prefix normalization |
| `PBE0-D3(BJ)` | yes | `PBE0` | `pbe0` | yes | safe |
| `PBE-D3(BJ)` | no | `PBE` | `pbe` | yes | safe alternative |
| `TPSSh-D3(BJ)` | no | `TPSSH` | `tpssh` | yes | safe alternative |
| `UM06-2X-D3(0)` | no | `M062X` | `m062x` | yes | safe alternative after normalization fix |
| `wB97X-D` | no | `WB97X` | `wb97x-d` | yes | cautionary future candidate only |
| `r2SCAN-3c` | no | `R2SCAN-3C` | `r2scan-3c` | no | future candidate only |
| `PWPB95-D3(BJ)` | no | `PWPB95` | `pwpb95` | no | future candidate only |

## BLOCKER Check

Phase 4 blocker rule:

> If any default functional is not mappable through the current runtime, the JSON must be rolled back.

Result:

- Passed.
- All defaults route safely through the upgraded normalization path.

## `dft_accuracy_table.json` Decision

- No production change was made to `dft_accuracy_table.json`.
- Reason:
  - all shipped defaults already resolve to existing accuracy-table keys,
  - the alignment pass did not promote any new default functional,
  - the remaining gaps belong only to future candidates (`wB97X-D`, `r2SCAN-3c`, `PWPB95-D3(BJ)`), with `wB97X-D` retained only as a cautionary candidate despite local plumbing.

### Deferred accuracy-table gaps

| Functional | Why not added now |
| --- | --- |
| `r2SCAN-3c` | Composite method, not a plain functional alias; current table is organized around standard functional identifiers. |
| `PWPB95-D3(BJ)` | Double-hybrid future candidate only; not mapped through the production runner path. |

## `xc_map` / Runtime Gap Assessment

### Fully supported now

- `B3LYP-D3(BJ)`
- `UB3LYP-D3(BJ)`
- `PBE0-D3(BJ)`
- `PBE-D3(BJ)`
- `TPSSh-D3(BJ)`
- `UM06-2X-D3(0)`

### Plumbed locally but not promotion-safe

- `wB97X-D`

Local normalization and aliasing exist, but this lookup now treats `wB97X-D` as a cautionary future candidate because upstream PySCF name-resolution and dispersion integration remain fragile (`#2069`).

### Intentionally not production-enabled

- `r2SCAN-3c`
- `PWPB95-D3(BJ)`

These remain in the JSON only as documented alternatives/future candidates with explicit `pyscf_supported: false` and implementation notes.

## Risk Notes

1. The workspace contains another sibling `src/qcviz_mcp` tree outside `version03`. Validation must set `PYTHONPATH=src` to guarantee the `version03` package is the one being tested.
2. `wB97X-D` has local runtime plumbing but is still not treated as production-safe in the lookup until live PySCF validation closes the upstream caveat.
3. `r2SCAN-3c` should not be treated as a normal `xc` alias. It needs composite-method orchestration, not just label normalization.
4. `PWPB95-D3(BJ)` has literature support for TM spin-state cross-checking, but promoting it beyond future-candidate status would require new execution and validation pathways.
