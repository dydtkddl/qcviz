# Cross-Validation Matrix

Date: 2026-03-30

## Synthesis Summary

- Both proposal sets were conservative and agreed that shipped defaults should remain unchanged.
- Both proposal sets favored metadata enrichment, stronger 3d TM caution, stronger radical guidance, and keeping non-trivial methods out of defaults.
- Conflicts were resolved with the following precedence:
  - peer-reviewed support over community signal,
  - runtime compatibility over theoretical superiority,
  - baseline retention over speculative promotion.

## System x Purpose Adoption Matrix

Legend:

- `keep`: keep baseline functional/basis/dispersion
- `add`: add explicit purpose entry using a conservative runtime-compatible rule
- `tighten`: same default retained, but rationale/confidence/metadata strengthened

| System type | `default` | `geometry_opt` | `single_point` | `bonding_analysis` | `reaction_energy` | `spectroscopy` | `esp_mapping` | Alternatives outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `organic_small` | `tighten` | `keep` | `keep` | `keep` | `keep` | `keep` | `keep` | keep `PBE0-D3(BJ)`, keep `r2SCAN-3c` as advisory, add `wB97X-D` |
| `organic_large` | `keep` | `keep` | `keep` | `keep` | `add` | `add` | `add` | keep `PBE-D3(BJ)`, keep `r2SCAN-3c` as future candidate |
| `3d_tm` | `tighten` | `keep` | `tighten` | `keep` | `add` | `add` | `add` | keep `TPSSh-D3(BJ)`, keep `PBE0-D3(BJ)`, add `PWPB95-D3(BJ)` as future candidate |
| `heavy_tm` | `keep` | `keep` | `keep` | `keep` | `add` | `add` | `add` | keep `B3LYP-D3(BJ)` |
| `lanthanide` | `tighten` | `keep` | `keep` | `add` | `add` | `add` | `add` | keep `TPSSh-D3(BJ)` with stronger caution |
| `radical` | `tighten` | `keep` | `keep` | `keep` | `add` | `add` | `add` | keep `UM06-2X-D3(0)`, add `wB97X-D` |
| `charged_organic` | `tighten` | `keep` | `keep` | `add` | `add` | `add` | `add` | keep `wB97X-D` |
| `main_group_metal` | `keep` | `keep` | `keep` | `keep` | `add` | `add` | `add` | keep `PBE0-D3(BJ)` |

## Adoption / Conflict Table

| Item | `set_rule01.md` | `set_rule02.md` | Alignment | Final decision | Rationale |
| --- | --- | --- | --- | --- | --- |
| Baseline defaults | Keep all defaults | Keep all defaults | Agreement | Adopted | Both proposals and runtime safety checks support retaining current defaults. |
| Backward-compatible metadata fields | Add enriched metadata | Add enriched metadata | Agreement | Adopted | Safe for consumers because code reads known keys with `dict.get(...)`. |
| Missing purpose coverage | Implicitly expanded in proposed JSON | Explicitly expanded across all purpose keys | Agreement | Adopted | Filled all seven purpose keys for all eight systems to remove silent default fallback. |
| `3d_tm` caution | Strengthen SSE17 warning and modestly lower confidence | Strengthen SSE17 warning and lower confidence more aggressively | Partial conflict | Adopted conservatively | Kept default but tightened rationale; confidence reduced conservatively to avoid overreacting without changing runtime behavior. |
| `radical` guidance | Strengthen with 2024 radical benchmark | Strengthen with 2024 radical benchmark; highlight better-performing alternatives | Agreement | Adopted | Default retained; rationale strengthened; `wB97X-D` added as runtime-safe cross-check. |
| `organic_small` alternatives | Add `wB97X-D`, keep `r2SCAN-3c` non-default | Add higher-end `ωB97*` family as future candidates | Partial conflict | Adopt `wB97X-D`, reject `ωB97M-*` import | `wB97X-D` is runtime-ready in the current stack; `ωB97M-*` requires additional NLC/runtime work. |
| `3d_tm` future candidate | Add `PWPB95-D3(BJ)` future candidate | Emphasize double-hybrid superiority but do not require import | Agreement | Adopted as future candidate only | Supported by SSE17, but not safe as a shipped default or runtime method. |
| `r2SCAN-3c` status | Alternative but not default | Alternative/future candidate; not production ready | Agreement | Kept as future candidate | PySCF/QCViz does not ship composite 3c execution support. |
| Spectroscopy scale-factor details | Suggested updated scale-factor wording | No corresponding schema change | Conflict in representability | Not imported into JSON schema | Current lookup schema and consumers do not consume explicit scale-factor fields. |
| `ωB97X-V` / `ωB97M-*` addition | Not central | Proposed as future candidates | One-sided proposal | Rejected from production JSON | Not currently wired through `advisor_flow` and compute runner; would raise support expectations the runtime does not meet. |
| D4 upgrade path | Not central | Mentions D4 upgrade path | One-sided proposal | Deferred | Useful future work, but not needed for the runtime-compatible production lookup. |

## Conflict Log

1. `3d_tm` confidence depth:
   - `rule01`: lower confidence, but keep the downgrade modest.
   - `rule02`: lower more aggressively.
   - Final: conservative downgrade only. Reason: the production goal is safer messaging without destabilizing the current preset baseline.

2. High-end `ωB97*` future candidates:
   - `rule02` proposed broader `ωB97*` future-candidate coverage.
   - Final: not imported into the production JSON.
   - Reason: current runtime support and mapping are not complete enough to advertise them cleanly in a product lookup.

3. Spectroscopy scale factors:
   - `rule01` included a more detailed spectroscopy update.
   - Final: not represented as a new schema field.
   - Reason: current consumers do not read or apply scale-factor metadata, so adding it here would create dead data.

4. Composite-method alternatives:
   - Both proposals liked `r2SCAN-3c`.
   - Final: retained only as a future/advisory alternative with explicit implementation notes.
   - Reason: no PySCF-native composite execution path exists in the current product.

## DOI Consistency Check

- No new DOI was introduced unless it was already present in one of the proposals or independently verified during the research pass.
- The working DOI set imported into the final JSON is:
  - `10.1002/anie.202205735`
  - `10.1002/jcc.21759`
  - `10.1021/acs.jctc.4c01783`
  - `10.1021/acs.jpca.5c02406`
  - `10.1021/ct400687b`
  - `10.1039/B508541A`
  - `10.1039/C7CP04913G`
  - `10.1039/D4OB00532E`
  - `10.1039/D4SC05471G`
  - `10.1063/5.0040021`
  - `10.1080/00268976.2017.1333644`
