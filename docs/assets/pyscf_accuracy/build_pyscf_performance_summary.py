from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent
SOURCE_CSV = ASSET_DIR / "performance_benchmark.csv"
SUMMARY_CSV = ASSET_DIR / "pyscf_performance_summary_table.csv"
SVG_OUT = ASSET_DIR / "pyscf_performance_summary_table.svg"
PNG_OUT = ASSET_DIR / "pyscf_performance_summary_table.png"
ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")

os.environ.setdefault("MPLCONFIGDIR", str(ASSET_DIR / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


def read_csv_safe(path: Path) -> list[dict[str, str]]:
    for encoding in ENCODINGS:
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read CSV with supported encodings: {path}")


def find_row(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(str(row.get(key, "")).strip() == value for key, value in criteria.items()):
            return row
    raise KeyError(f"Could not find row matching {criteria}")


def _extra_tail(row: dict[str, str]) -> str:
    extra = row.get(None)
    if not extra:
        return ""
    if isinstance(extra, list):
        return " ".join(part.strip() for part in extra if str(part).strip())
    return str(extra).strip()


def normalized_value(row: dict[str, str], field: str) -> str:
    value = str(row.get(field, "") or "").strip()
    if value:
        return value

    # Some imported CSV rows have cost values shifted into the notes column,
    # with the real note text spilling into the extra unnamed tail.
    if field == "cost_usd":
        note_value = str(row.get("notes", "") or "").strip()
        try:
            float(note_value)
            return note_value
        except Exception:
            return ""

    if field == "notes":
        note_value = str(row.get("notes", "") or "").strip()
        tail = _extra_tail(row)
        if note_value and tail:
            try:
                float(note_value)
                return tail
            except Exception:
                return f"{note_value}; {tail}"
        return note_value or tail

    return ""


def fmt_seconds(value: str) -> str:
    try:
        return f"{float(value):.1f} s"
    except Exception:
        return value or "-"


def fmt_cost(value: str) -> str:
    try:
        return f"${float(value):.2f}"
    except Exception:
        return value or "-"


def build_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    g09_1 = find_row(rows, source_id="r2bench", code="Gaussian 09", hardware="CPU", n_cores_or_gpu="1")
    pyscf_1 = find_row(rows, source_id="r2bench", code="PySCF 1.7", hardware="CPU", n_cores_or_gpu="1")
    g09_16 = find_row(rows, source_id="r2bench", code="Gaussian 09", hardware="CPU", n_cores_or_gpu="16")
    pyscf_16 = find_row(rows, source_id="r2bench", code="PySCF 1.7", hardware="CPU", n_cores_or_gpu="16")
    scipy_cpu = find_row(rows, source_id="SciPy2025", code="PySCF", hardware="CPU")
    scipy_gpu = find_row(rows, source_id="SciPy2025", code="GPU4PySCF", hardware="GPU")
    scipy_ref = find_row(rows, source_id="SciPy2025", code="SIESTA", hardware="CPU")
    rowan_gpu = find_row(rows, source_id="Rowan2025", code="GPU4PySCF", hardware="GPU")

    return [
        {
            "profile": "Historical CPU caution",
            "year": "2020",
            "scenario": "C20, B3LYP/6-31G(d), single core",
            "pyscf_variant": "PySCF 1.7 CPU",
            "compared_against": "Gaussian 09 CPU",
            "headline_metric": f"{fmt_seconds(pyscf_1['wall_time_seconds'])} vs {fmt_seconds(g09_1['wall_time_seconds'])}",
            "takeaway": "Old PySCF CPU benchmark was much slower than established CPU codes.",
            "caveat": "Historical version with tight defaults; not representative of the current GPU path.",
            "source": "r2compchem benchmark (2020)",
        },
        {
            "profile": "Historical CPU caution",
            "year": "2020",
            "scenario": "C20, B3LYP/6-31G(d), 16 cores",
            "pyscf_variant": "PySCF 1.7 CPU",
            "compared_against": "Gaussian 09 CPU",
            "headline_metric": f"{fmt_seconds(pyscf_16['wall_time_seconds'])} vs {fmt_seconds(g09_16['wall_time_seconds'])}",
            "takeaway": "Even multicore historical CPU performance remained behind Gaussian in this benchmark.",
            "caveat": "Still a useful cautionary baseline for honest performance framing.",
            "source": "r2compchem benchmark (2020)",
        },
        {
            "profile": "Recent validated CPU result",
            "year": "2025",
            "scenario": "38-atom phosphate + 4H2O, RPBE/DZP",
            "pyscf_variant": "PySCF CPU",
            "compared_against": "SIESTA CPU",
            "headline_metric": f"{normalized_value(scipy_cpu, 'speedup_factor')} faster; {fmt_cost(normalized_value(scipy_cpu, 'cost_usd'))} vs {fmt_cost(normalized_value(scipy_ref, 'cost_usd'))}",
            "takeaway": "Chemical accuracy was retained while total cost dropped substantially.",
            "caveat": "Result is reported over 85 configurations, not a single isolated job.",
            "source": "Sahara et al. (SciPy 2025)",
        },
        {
            "profile": "GPU scaling result",
            "year": "2025",
            "scenario": "38-atom phosphate + 4H2O, RPBE/DZP",
            "pyscf_variant": "GPU4PySCF",
            "compared_against": "SIESTA CPU",
            "headline_metric": f"{normalized_value(scipy_gpu, 'speedup_factor')} faster; {fmt_cost(normalized_value(scipy_gpu, 'cost_usd'))} vs {fmt_cost(normalized_value(scipy_ref, 'cost_usd'))}",
            "takeaway": "GPU acceleration gives a large performance and cost advantage while preserving chemical accuracy.",
            "caveat": "Best used as the forward-looking scaling story rather than the default CPU baseline.",
            "source": "Sahara et al. (SciPy 2025)",
        },
        {
            "profile": "GPU scaling result",
            "year": "2025",
            "scenario": "Linear alkanes, r2SCAN/def2-TZVP",
            "pyscf_variant": "GPU4PySCF",
            "compared_against": "Psi4 CPU",
            "headline_metric": rowan_gpu["speedup_factor"],
            "takeaway": "Independent benchmark reports 10-50x speedup for GPU4PySCF on representative systems.",
            "caveat": "Figure benchmark / blog source, useful for direction rather than strict primary evidence.",
            "source": "Rowan blog benchmark (2025)",
        },
    ]


def write_summary_csv(rows: list[dict[str, str]], path: Path) -> None:
    fieldnames = [
        "profile",
        "year",
        "scenario",
        "pyscf_variant",
        "compared_against",
        "headline_metric",
        "takeaway",
        "caveat",
        "source",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_summary_table(rows: list[dict[str, str]], output_path: Path) -> None:
    fig = plt.figure(figsize=(12, 5.6), dpi=200, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()

    panel = FancyBboxPatch(
        (0.02, 0.05),
        0.96,
        0.90,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        facecolor="white",
        edgecolor="#D5D9E0",
        linewidth=1.2,
        transform=ax.transAxes,
    )
    ax.add_patch(panel)

    ax.text(
        0.05,
        0.92,
        "PySCF performance summary",
        transform=ax.transAxes,
        fontsize=18,
        fontweight="bold",
        color="#111827",
        va="top",
    )
    ax.text(
        0.05,
        0.875,
        "Historical CPU limitations and recent validated GPU / cost improvements from the CSV asset pack.",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#475569",
        va="top",
    )

    headers = ["Profile", "Scenario", "Metric", "Takeaway"]
    col_x = [0.05, 0.23, 0.57, 0.75]
    header_y = 0.80
    row_h = 0.125

    for x, header in zip(col_x, headers, strict=True):
        ax.text(
            x,
            header_y,
            header,
            transform=ax.transAxes,
            fontsize=10.5,
            fontweight="bold",
            color="#334155",
            va="center",
        )

    for i, row in enumerate(rows):
        y_top = header_y - 0.04 - i * row_h
        bg = "#FFF7ED" if "Historical" in row["profile"] else "#ECFDF5"
        edge = "#FDBA74" if "Historical" in row["profile"] else "#86EFAC"
        rect = FancyBboxPatch(
            (0.04, y_top - row_h + 0.01),
            0.92,
            row_h - 0.015,
            boxstyle="round,pad=0.008,rounding_size=0.01",
            facecolor=bg,
            edgecolor=edge,
            linewidth=1.0,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        ax.text(0.05, y_top - 0.045, row["profile"], transform=ax.transAxes, fontsize=9.5, fontweight="bold", color="#9A3412" if "Historical" in row["profile"] else "#047857", va="center")
        ax.text(0.23, y_top - 0.03, row["scenario"], transform=ax.transAxes, fontsize=9.5, color="#0F172A", va="center")
        ax.text(0.23, y_top - 0.062, f"{row['pyscf_variant']} vs {row['compared_against']}", transform=ax.transAxes, fontsize=8.6, color="#64748B", va="center")
        ax.text(0.57, y_top - 0.045, row["headline_metric"], transform=ax.transAxes, fontsize=9.5, fontweight="bold", color="#0F172A", va="center")
        ax.text(0.75, y_top - 0.03, row["takeaway"], transform=ax.transAxes, fontsize=8.8, color="#0F172A", va="center")
        ax.text(0.75, y_top - 0.062, row["source"], transform=ax.transAxes, fontsize=8.2, color="#64748B", va="center")

    ax.text(
        0.05,
        0.085,
        "Recommended talk track: be honest about old PySCF CPU benchmarks, then emphasize recent validated CPU cost gains and GPU4PySCF scaling.",
        transform=ax.transAxes,
        fontsize=8.8,
        color="#475569",
    )
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a presentation-ready PySCF performance summary table.")
    parser.add_argument("--csv-only", action="store_true", help="Only write the summary CSV.")
    args = parser.parse_args()

    rows = read_csv_safe(SOURCE_CSV)
    summary_rows = build_summary_rows(rows)
    write_summary_csv(summary_rows, SUMMARY_CSV)

    if not args.csv_only:
        render_summary_table(summary_rows, SVG_OUT)
        render_summary_table(summary_rows, PNG_OUT)


if __name__ == "__main__":
    main()
