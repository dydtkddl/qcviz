# Changelog

Date: 2026-03-30

## Scope Summary

- Upgraded `functional_recommendations.json` from baseline `v1.1.0` to `v1.2.1`.
- Kept all shipped default functionals unchanged.
- Expanded the lookup to full 8-system x 7-purpose coverage.
- Added backward-compatible advisory metadata fields.
- Strengthened runtime normalization so unrestricted and dispersion-suffixed advisor labels remain safe through scoring, script generation, web flow, and compute runner handoff.
- Generated the supporting phase documents required for review and handoff.
- Applied a patch 3 safety alignment pass that adopts `patch_2` as the safer baseline for wording and future-candidate policy.

## Production Files Changed

- `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
- `src/qcviz_mcp/advisor/reference_data/__init__.py`
- `src/qcviz_mcp/advisor/preset_recommender.py`
- `src/qcviz_mcp/advisor/script_generator.py`
- `src/qcviz_mcp/advisor/methods_drafter.py`
- `src/qcviz_mcp/web/advisor_flow.py`
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `tests/test_advisor_new.py`
- `tests/test_advisor_script.py`
- `tests/test_advisor_drafter.py`
- `tests/test_advisor_flow.py`

## Adopted Proposal Source

| Change area | Source adopted |
| --- | --- |
| Keep all shipped defaults | both |
| Add structured metadata fields | both |
| Fill missing purpose coverage | both |
| Strengthen 3d TM caution | both |
| Strengthen radical rationale | both |
| Keep `wB97X-D` only as a cautionary future candidate | patch_2 + patch selection verdict |
| Add `PWPB95-D3(BJ)` as future candidate only | rule01 |
| Keep `r2SCAN-3c` non-default and explicitly non-production | both |
| Reject direct `ωB97M-*` import into production JSON | neither; held back for runtime compatibility reasons |

## Conflict Resolution Log

1. `3d_tm` confidence recalibration:
   - `rule01` and `rule02` both lowered confidence, but `rule02` lowered it more aggressively.
   - Resolution: conservative downgrade only.

2. High-end `ωB97*` families:
   - `rule02` proposed broader future-candidate coverage.
   - Resolution: not imported into the production JSON because the runtime path is not complete enough to advertise them safely.

3. Spectroscopy scale-factor detail:
   - `rule01` wanted richer spectroscopy detail.
   - Resolution: not added to the lookup schema because current consumers do not read such fields.

4. `wB97X-D` classification:
   - Earlier alignment left it as a runtime-ready alternative because local plumbing exists.
   - Resolution: patch 3 reclassified it to caution/future-candidate only, because upstream PySCF issue `#2069` remains a release-safety caveat.

## Residual Risks

1. `3d_tm` defaults remain operationally conservative, not accuracy-maximal. Spin-state-sensitive users still need explicit cross-check workflows.
2. `lanthanide` recommendations remain low-confidence by design because DFT limitations are methodological, not just lookup-data issues.
3. `wB97X-D` has local runtime plumbing but remains caution-only until live PySCF validation closes the upstream caveat.
4. `r2SCAN-3c` and `PWPB95-D3(BJ)` remain documented but intentionally not executable through the production path.
5. The surrounding workspace contains a sibling `src/qcviz_mcp` tree; validation must pin `PYTHONPATH=src` for version03-specific checks.

## Follow-Up Work

- Add an explicit composite-method execution path if `r2SCAN-3c` is meant to become actionable.
- Add a validated double-hybrid execution path before promoting `PWPB95-D3(BJ)` beyond future-candidate status.
- Run a live PySCF environment validation pass before treating `wB97X-D` or `wB97X-V` as production-safe lookup candidates.
- Decide whether `ωB97X-V` / `ωB97M-*` should be integrated after a dedicated NLC/VV10 runtime design.
- Consider a dedicated spectroscopy-specific schema if scale factors or calibration metadata should become first-class runtime data.
