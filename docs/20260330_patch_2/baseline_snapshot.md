# Baseline Snapshot

Date: 2026-03-30

## Scope

- Project root: `D:\20260305_양자화학시각화MCP서버구축\version03`
- Upgrade target: `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
- Baseline reference used for comparison:
  - `docs/20260330_patch/QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30/QCViz/src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
  - This snapshot preserves the pre-upgrade `v1.1.0` lookup structure after the production file was upgraded in-place.

## Runtime Consumers

| File | Responsibility | Data read from lookup |
| --- | --- | --- |
| `src/qcviz_mcp/advisor/preset_recommender.py` | Builds advisor presets and PySCF settings | `functional`, `basis`, `dispersion`, `references`, `rationale`, `confidence`; top-level `alternatives` |
| `src/qcviz_mcp/advisor/confidence_scorer.py` | Scores method appropriateness | normalized functional keys + default functional per system |
| `src/qcviz_mcp/web/advisor_flow.py` | Applies advisor presets to compute runner kwargs | normalized advisor functional labels routed to runner-safe method names |
| `src/qcviz_mcp/compute/pyscf_runner.py` | Runs actual PySCF jobs | method aliases for normalized functionals |

## `preset_recommender.py` Baseline Behavior

- Purpose validation is strict: only `geometry_opt`, `single_point`, `bonding_analysis`, `reaction_energy`, `spectroscopy`, `esp_mapping` are accepted.
- Rule lookup pattern:
  - `rules = self._recommendations.get(system_type, {})`
  - `purpose_rules = rules.get(purpose, rules.get("default", {}))`
- Field access pattern is non-breaking for extra metadata because it relies on `dict.get(...)`.
- Top-level `alternatives` are read separately with `rules.get("alternatives", [])`.
- Missing purpose keys silently fall back to `default`; this made incomplete system coverage easy to ship unnoticed.

### Current advisor-to-PySCF normalization keys

`preset_recommender.py` currently recognizes these base functional labels for PySCF `xc` construction:

- `B3LYP`
- `PBE0`
- `TPSSh`
- `PBE`
- `TPSS`
- `r2SCAN`
- `M06-2X`
- `M062X`
- `wB97X-D`
- `wB97X-D3`
- `wB97X-V`
- `PW6B95`

## `dft_accuracy_table.json` Baseline Keys

The accuracy table currently contains:

- `B3LYP`
- `PBE0`
- `PBE`
- `TPSS`
- `TPSSH`
- `WB97X`
- `M062X`
- `PW6B95`
- `R2SCAN`

## Baseline Lookup Coverage (`v1.1.0`)

| System type | Default | Missing purpose keys in baseline | Top-level alternatives |
| --- | --- | --- | --- |
| `organic_small` | `B3LYP-D3(BJ) / def2-SVP` | none | `PBE0-D3(BJ)`, `r2SCAN-3c` |
| `organic_large` | `B3LYP-D3(BJ) / def2-SVP` | `reaction_energy`, `spectroscopy`, `esp_mapping` | `PBE-D3(BJ)`, `r2SCAN-3c` |
| `3d_tm` | `B3LYP-D3(BJ) / def2-SVP` | `reaction_energy`, `spectroscopy`, `esp_mapping` | `TPSSh-D3(BJ)`, `PBE0-D3(BJ)` |
| `heavy_tm` | `PBE0-D3(BJ) / def2-SVP` | `reaction_energy`, `spectroscopy`, `esp_mapping` | `B3LYP-D3(BJ)` |
| `lanthanide` | `PBE0-D3(BJ) / def2-SVP` | `bonding_analysis`, `reaction_energy`, `spectroscopy`, `esp_mapping` | `TPSSh-D3(BJ)` |
| `radical` | `UB3LYP-D3(BJ) / def2-SVP` | `reaction_energy`, `spectroscopy`, `esp_mapping` | `UM06-2X-D3(0)` |
| `charged_organic` | `B3LYP-D3(BJ) / def2-TZVP` | `bonding_analysis`, `reaction_energy`, `spectroscopy`, `esp_mapping` | `wB97X-D` |
| `main_group_metal` | `B3LYP-D3(BJ) / def2-SVP` | `reaction_energy`, `spectroscopy`, `esp_mapping` | `PBE0-D3(BJ)` |

## Baseline Risks Observed

1. Schema completeness was uneven. Several systems did not define all purpose keys, so behavior depended on implicit `default` fallback.
2. Baseline metadata was thin. The lookup shipped with `version 1.1.0`, a short source list, and no structured applicability/avoidance metadata.
3. Alternative methods mixed production-safe and advisory-only choices without consistent implementation notes.
4. Raw advisor labels such as unrestricted or dispersion-suffixed names could drift into downstream runtime layers without centralized normalization.

## Test Surface Identified

Advisor-relevant tests present in `tests/`:

- `test_advisor_new.py`
- `test_advisor_preset.py`
- `test_advisor_scorer.py`
- `test_advisor_script.py`
- `test_advisor_drafter.py`
- `test_advisor_flow.py`

These form the validation bundle for the lookup upgrade and related compatibility fixes.
