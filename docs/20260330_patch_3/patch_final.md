# Patch Final

Date: 2026-03-30

## Current State

- Current source-of-truth JSON is `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`.
- Current metadata version is `1.2.1`.
- Purpose coverage is already complete for all 8 system types.
- Therefore, the large purpose-gap discussion in `patch_1.md` and `patch_2.md` must be read as **baseline-state analysis**, not as a statement about the current checked-in repo.
- Runtime code already contains normalization/plumbing for several advanced labels, but that is not the same as production-safe promotion.
- In particular, `wB97X-D`, `wB97X-V`, `r2SCAN-3c`, and `PWPB95-D3(BJ)` must still be treated cautiously.

## Final Decision

- `patch_2.md` is the adopted primary reference.
- `patch_1.md` is a secondary reference and is only used for verified supporting phrasing.
- `wB97X-D`, `wB97X-V`, `r2SCAN-3c`, and `PWPB95-D3(BJ)` are all kept as caution/future-candidate only.
- No new default functional is introduced in this pass.
- The current pass is a production-safety alignment pass, not a new benchmark-expansion pass.

## Applied from patch_2

- Adopted the stricter reading of SSE17 for `3d_tm.single_point`; confidence is now `0.62`.
- Tightened the `3d_tm.single_point` rationale and `avoid_when` wording so spin-state-sensitive cases are explicitly flagged as cross-check-required.
- Reclassified every `wB97X-D` alternative as non-production-safe until live PySCF validation is available.
- Standardized `wB97X-D` alternatives to:
  - `future_candidate: true`
  - `pyscf_supported: false`
  - explicit `implementation_notes` referencing upstream PySCF issue `#2069`
- Preserved the composite-only treatment of `r2SCAN-3c`.
- Preserved the future-candidate-only treatment of `PWPB95-D3(BJ)`.

## Cherry-picked from patch_1

- Retained the stronger explanatory framing that missing purpose coverage can cause fallback-driven behavior, but only as historical baseline context.
- Retained the conservative positioning of `PWPB95-D3(BJ)` as a 3d TM spin-state cross-check candidate rather than a production default.
- Retained the idea that additional literature such as BH9, Tikhonov, and Ln-focused studies can enrich rationale text, but only when they do not force new runtime claims.

## Deferred Items

- Do not add `wB97X-V` to the lookup in this pass, even though parts of the local runtime plumbing exist.
- Do not add `ωB97M-*` families in this pass.
- Do not modify `dft_accuracy_table.json` in this pass.
- Do not add new `xc_map` or runner aliases in this pass.
- Do not reinterpret plain `r2SCAN` alias support as `r2SCAN-3c` support.
- Do not move `PWPB95-D3(BJ)` out of future-candidate status without a dedicated double-hybrid execution path.

## Operational Notes

- Existing baseline analysis files are preserved as-is:
  - `docs/20260330_patch_3/patch_1.md`
  - `docs/20260330_patch_3/patch_2.md`
  - `docs/20260330_patch_3/patch_selection_verdict.md`
- This file is the canonical current-state reference for the patch 3 alignment pass.
