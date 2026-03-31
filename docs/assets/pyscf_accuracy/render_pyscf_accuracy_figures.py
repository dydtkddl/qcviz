from __future__ import annotations

import argparse
import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent
ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")
os.environ.setdefault("MPLCONFIGDIR", str(ASSET_DIR / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FormatStrFormatter


@dataclass(frozen=True)
class ValidationBar:
    label: str
    plot_value: float
    annotation: str


def read_csv_safe(path: Path) -> list[dict[str, str]]:
    for encoding in ENCODINGS:
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read CSV file with supported encodings: {path}")


def parse_microhartree_value(value: str) -> tuple[float, bool] | None:
    text = value.strip()
    if not text:
        return None

    upper_match = re.search(r"[<≤]\s*([0-9]+(?:\.[0-9]+)?)", text)
    if upper_match:
        return float(upper_match.group(1)), True

    numeric_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if numeric_match:
        return float(numeric_match.group(1)), False
    return None


def normalize_energy_value(value: str) -> float:
    return float(value.strip().replace("−", "-").replace("–", "-").replace(",", ""))


def extract_validation_bars(rows: list[dict[str, str]]) -> list[ValidationBar]:
    groups = [
        ("Q-Chem", ("q-chem",)),
        ("ORCA/\nLSDalton", ("orca", "lsdalton")),
        ("PySCF\nCPU", ("pyscf_cpu", "pyscf cpu")),
    ]
    bars: list[ValidationBar] = []

    for label, keywords in groups:
        parsed_values: list[tuple[float, bool]] = []
        for row in rows:
            haystack = " ".join(
                [
                    row.get("comparison_pair", ""),
                    row.get("code_A", ""),
                    row.get("code_B", ""),
                    row.get("notes", ""),
                ]
            ).lower()
            if any(keyword in haystack for keyword in keywords):
                parsed = parse_microhartree_value(row.get("energy_diff_microhartree", ""))
                if parsed is not None:
                    parsed_values.append(parsed)

        if not parsed_values:
            raise RuntimeError(f"Could not derive validation value for {label}")

        upper_bound = max(value for value, _ in parsed_values)
        upper_bound_only = all(is_bound for _, is_bound in parsed_values)
        plot_value = upper_bound * 0.8 if upper_bound_only else upper_bound

        if upper_bound <= 1.0:
            annotation = "< 1 μEh"
        elif upper_bound_only:
            annotation = f"≤ {int(upper_bound)} μEh"
        else:
            annotation = f"{upper_bound:.1f} μEh"

        bars.append(ValidationBar(label=label, plot_value=plot_value, annotation=annotation))

    return bars


def load_gh688_rows(rows: list[dict[str, str]]) -> list[tuple[str, float]]:
    parsed_rows = [(row["코드"], normalize_energy_value(row["Total Energy (a.u.)"])) for row in rows]
    parsed_rows.sort(key=lambda item: item[1], reverse=True)
    return parsed_rows


def add_panel_background(ax) -> None:
    panel = FancyBboxPatch(
        (0.0, 0.0),
        1.0,
        1.0,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        transform=ax.transAxes,
        facecolor="white",
        edgecolor="#D5D9E0",
        linewidth=1.1,
        zorder=-10,
    )
    ax.add_patch(panel)


def style_axes(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#A9B1BC")
    ax.spines["bottom"].set_color("#A9B1BC")
    ax.tick_params(colors="#3C4856")


def render_mini_panel(
    validation_bars: list[ValidationBar],
    output_path: Path,
    source_note: str = "Sources: literature_summary_matrix.csv, energy_accuracy_comparison.csv",
) -> None:
    fig = plt.figure(figsize=(8, 6), dpi=200, facecolor="white")
    ax = fig.add_axes([0.08, 0.19, 0.84, 0.66])
    add_panel_background(ax)
    style_axes(ax)

    labels = [bar.label for bar in validation_bars]
    values = [bar.plot_value for bar in validation_bars]
    annotations = [bar.annotation for bar in validation_bars]
    colors = ["#97A3B6", "#97A3B6", "#0F766E"]

    x = np.arange(len(labels))
    bars = ax.bar(x, values, width=0.58, color=colors, edgecolor="#F8FAFC", linewidth=0.8)
    ax.set_yscale("log")
    ax.set_ylim(0.3, 20)
    ax.set_xlim(-0.55, len(labels) - 0.45)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Energy difference (μHartree)", fontsize=11, color="#27313E")
    ax.set_title("Validated numerical backend", fontsize=14, weight="bold", color="#111827", pad=12)
    ax.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.35, color="#94A3B8")

    for rect, annotation in zip(bars, annotations, strict=True):
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            rect.get_height() * 1.16,
            annotation,
            ha="center",
            va="bottom",
            fontsize=10,
            weight="bold",
            color="#0F172A",
        )

    fig.text(
        0.08,
        0.085,
        "Cross-validation against established quantum chemistry codes shows μHartree-level agreement.\n"
        "The LLM interprets the request; PySCF generates the numbers.",
        fontsize=9.5,
        color="#334155",
    )
    fig.text(0.08, 0.03, source_note, fontsize=8, color="#64748B")
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_two_panel(
    validation_bars: list[ValidationBar],
    gh688_rows: list[tuple[str, float]],
    output_path: Path,
) -> None:
    fig = plt.figure(figsize=(8, 6), dpi=200, facecolor="white")

    ax1 = fig.add_axes([0.08, 0.18, 0.40, 0.68])
    add_panel_background(ax1)
    style_axes(ax1)

    labels = [bar.label for bar in validation_bars]
    values = [bar.plot_value for bar in validation_bars]
    annotations = [bar.annotation for bar in validation_bars]
    colors = ["#97A3B6", "#97A3B6", "#0F766E"]

    x = np.arange(len(labels))
    bars = ax1.bar(x, values, width=0.56, color=colors, edgecolor="#F8FAFC", linewidth=0.8)
    ax1.set_yscale("log")
    ax1.set_ylim(0.3, 20)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Energy difference (μHartree)", fontsize=10, color="#27313E")
    ax1.set_title("Cross-code agreement", fontsize=12, weight="bold", color="#111827", pad=10)
    ax1.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.35, color="#94A3B8")

    for rect, annotation in zip(bars, annotations, strict=True):
        ax1.text(
            rect.get_x() + rect.get_width() / 2,
            rect.get_height() * 1.15,
            annotation,
            ha="center",
            va="bottom",
            fontsize=8.5,
            weight="bold",
            color="#0F172A",
        )

    ax2 = fig.add_axes([0.56, 0.18, 0.36, 0.68])
    add_panel_background(ax2)
    style_axes(ax2)

    codes = [code for code, _ in gh688_rows]
    energies = [energy for _, energy in gh688_rows]
    bar_colors = ["#64748B" if code == "PySCF" else "#C2410C" for code in codes]
    positions = np.arange(len(codes))

    bars2 = ax2.barh(positions, energies, color=bar_colors, edgecolor="#F8FAFC", linewidth=0.8)
    ax2.set_yticks(positions)
    ax2.set_yticklabels(codes, fontsize=10)
    ax2.invert_yaxis()
    ax2.set_title("GH #688 cautionary example", fontsize=12, weight="bold", color="#111827", pad=10)
    ax2.set_xlabel("Total energy (a.u.)", fontsize=10, color="#27313E")
    ax2.xaxis.set_major_formatter(FormatStrFormatter("%.4f"))

    padding = 0.0007
    ax2.set_xlim(min(energies) - padding, max(energies) + padding)
    ax2.grid(axis="x", linestyle="--", linewidth=0.8, alpha=0.25, color="#94A3B8")

    for rect, energy in zip(bars2, energies, strict=True):
        ax2.text(
            energy + 0.00006,
            rect.get_y() + rect.get_height() / 2,
            f"{energy:.6f}",
            va="center",
            fontsize=8.5,
            color="#0F172A",
        )

    fig.suptitle("PySCF accuracy evidence", fontsize=15, weight="bold", color="#111827", y=0.95)
    fig.text(
        0.08,
        0.06,
        "Left: literature-level validation. Right: a single default-grid example where total energies diverge.\n"
        "Refined settings reduce the GH #688 gap.",
        fontsize=9,
        color="#334155",
    )
    fig.text(
        0.08,
        0.025,
        "Sources: literature_summary_matrix.csv, energy_accuracy_comparison.csv, gh688_total_energy_table.csv",
        fontsize=8,
        color="#64748B",
    )
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render PPT-ready PySCF accuracy figures from CSV assets.")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ASSET_DIR,
        help="Directory where rendered image files will be written.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=("png", "svg"),
        choices=("png", "svg"),
        help="Image formats to generate.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    energy_rows = read_csv_safe(ASSET_DIR / "energy_accuracy_comparison.csv")
    gh688_rows = read_csv_safe(ASSET_DIR / "gh688_total_energy_table.csv")

    validation_bars = extract_validation_bars(energy_rows)
    gh688_plot_rows = load_gh688_rows(gh688_rows)

    for image_format in args.formats:
        render_mini_panel(
            validation_bars,
            outdir / f"pyscf_accuracy_mini_panel.{image_format}",
        )
        render_two_panel(
            validation_bars,
            gh688_plot_rows,
            outdir / f"pyscf_accuracy_two_panel.{image_format}",
        )


if __name__ == "__main__":
    main()
