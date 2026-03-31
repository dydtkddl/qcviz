# Validation Report

Date: 2026-03-30

## Validation Scope

- Production lookup:
  - `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
- Backup artifact:
  - `docs/20260330_patch_2/functional_recommendations_v2_final.json`
- Runtime consumers:
  - `src/qcviz_mcp/advisor/preset_recommender.py`
  - `src/qcviz_mcp/advisor/confidence_scorer.py`
  - `src/qcviz_mcp/web/advisor_flow.py`
  - `src/qcviz_mcp/compute/pyscf_runner.py`

## Commands Executed

### JSON + schema checks

```powershell
@'
import json
from pathlib import Path
data = json.loads(Path('src/qcviz_mcp/advisor/reference_data/functional_recommendations.json').read_text(encoding='utf-8'))
...
'@ | python -
```

### Import-level validation against `version03`

```powershell
$env:PYTHONPATH='src'
@'
import qcviz_mcp.advisor.preset_recommender as pr
import qcviz_mcp.web.advisor_flow as af
import qcviz_mcp.advisor.confidence_scorer as cs
print(pr.__file__)
print(af.__file__)
print(cs.__file__)
'@ | python -
```

### Recommendation smoke matrix

```powershell
$env:PYTHONPATH='src'
@'
from qcviz_mcp.advisor.preset_recommender import PresetRecommender
...
'@ | python -
```

### Advisor-focused test bundle

```powershell
$env:PYTHONPATH='src'
pytest tests/test_advisor_new.py tests/test_advisor_preset.py tests/test_advisor_scorer.py tests/test_advisor_script.py tests/test_advisor_drafter.py tests/test_advisor_flow.py -q
```

## Results

### JSON Integrity

| Check | Result |
| --- | --- |
| `json.loads()` parse success | pass |
| 8 top-level system keys present | pass |
| all 7 purpose keys present in every system | pass |
| required fields present in every purpose entry | pass |
| `alternatives` array present in every purpose entry | pass |
| metadata version aligned to patch 3 safety pass (`1.2.1`) | pass |
| backup JSON byte-identical to production JSON | pass |

Backup parity:

- SHA-256 of production JSON: `e4baf5c67f01d30e66700b019ec45f2896a874206c4fd0b0acd33d38c0292dbc`
- SHA-256 of backup JSON: `e4baf5c67f01d30e66700b019ec45f2896a874206c4fd0b0acd33d38c0292dbc`

### Code Compatibility

| Check | Result |
| --- | --- |
| `preset_recommender.py` import success | pass |
| `advisor_flow.py` import success | pass |
| `confidence_scorer.py` import success | pass |
| `recommend()` smoke matrix across 8 systems x 7 purposes | pass (`56/56`) |
| all default functionals map to runtime-safe `xc` values | pass |
| unrestricted labels normalize correctly for scoring | pass |

### Data Quality

| Check | Result |
| --- | --- |
| purpose-entry rationale backed by at least one DOI/URL reference | pass |
| alternatives backed by at least one DOI/URL reference | pass |
| all confidence values in `[0.0, 1.0]` | pass |
| new alternatives include `pyscf_supported` or `implementation_notes` | pass |
| all `wB97X-D` alternatives downgraded to caution/future-candidate status with issue note | pass |
| fabricated DOI introduced during merge | not detected |

Working DOI set present in the final JSON:

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

### Test Results

Advisor-focused pytest bundle:

- `84 passed in 0.11s`

## Non-Blocking Gaps Confirmed

| Functional | Gap | Handling |
| --- | --- | --- |
| `wB97X-D` | local plumbing exists, but upstream PySCF caveat remains | kept as cautionary future candidate with `pyscf_supported: false` and issue `#2069` note |
| `r2SCAN-3c` | not in accuracy table; not production-mapped as plain `xc` | kept as future candidate with `pyscf_supported: false` |
| `PWPB95-D3(BJ)` | not in accuracy table; not production-mapped | kept as future candidate with `pyscf_supported: false` |

These are not blockers because neither functional is used as a shipped default.

## Validation Notes

1. The workspace contains another sibling `src/qcviz_mcp` tree outside `version03`. Raw `python` imports can resolve to the wrong package unless `PYTHONPATH=src` is set explicitly.
2. For this reason, all final compatibility checks and pytest runs were executed with `PYTHONPATH=src`.
3. No rollback was required. Validation passed on the first full run after schema completion and alternative-reference enrichment.
