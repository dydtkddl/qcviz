# PySCF Accuracy Asset Pack

This folder is the reusable asset pack for PySCF accuracy, validation, and performance material used in slides and reports.

It keeps three layers separate:

- source markdown documents written for humans
- normalized CSV assets for reuse
- derived presentation figures and summary tables

## Source documents

- [docs/pyscf값전수조사.md](D:/20260305_양자화학시각화MCP서버구축/version03/docs/pyscf값전수조사.md)
  - fenced CSV source for energy, performance, and source registry data
- [docs/presentation/pyscf정확도문헌조사.md](D:/20260305_양자화학시각화MCP서버구축/version03/docs/presentation/pyscf정확도문헌조사.md)
  - presentation-oriented narrative with two markdown tables

## Normalized CSV assets

- `energy_accuracy_comparison.csv`
- `performance_benchmark.csv`
- `source_registry.csv`
- `gh688_total_energy_table.csv`
- `literature_summary_matrix.csv`
- `manifest.json`

## Regenerate normalized assets

```bash
python docs/assets/pyscf_accuracy/build_pyscf_accuracy_assets.py
```

## Accuracy figures for slides

```bash
python docs/assets/pyscf_accuracy/render_pyscf_accuracy_figures.py
```

This generates:

- `pyscf_accuracy_mini_panel.png`
- `pyscf_accuracy_mini_panel.svg`
- `pyscf_accuracy_two_panel.png`
- `pyscf_accuracy_two_panel.svg`

Recommended use:

- `mini_panel`: compact “validated numerical backend” slide figure
- `two_panel`: literature summary plus GH #688 cautionary example

## Performance summary table

```bash
python docs/assets/pyscf_accuracy/build_pyscf_performance_summary.py
```

This generates:

- `pyscf_performance_summary_table.csv`
- `pyscf_performance_summary_table.svg`
- `pyscf_performance_summary_table.png`

Purpose:

- keep the historical PySCF CPU caution visible
- highlight recent validated CPU cost improvements
- show GPU4PySCF scaling separately and cleanly
- provide a slide-ready summary distilled from `performance_benchmark.csv`

## Notes

- All files are UTF-8 text or standard image outputs.
- Use the CSV files as the first source of truth for charts and tables.
- Use the markdown documents as reading material, not as direct plotting input.
