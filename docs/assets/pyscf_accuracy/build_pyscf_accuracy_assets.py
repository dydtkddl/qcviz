from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = ROOT / "docs"
ASSET_DIR = Path(__file__).resolve().parent


@dataclass
class ArtifactSpec:
    filename: str
    kind: str
    description: str
    source_document: Path
    source_locator: str


def _find_values_doc() -> Path:
    candidates = [
        p
        for p in DOCS_DIR.rglob("*.md")
        if p.parent == DOCS_DIR and "pyscf" in p.name.lower() and "전수조사" in p.name
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly 1 values source document, found {len(candidates)}: {candidates}")
    return candidates[0]


def _find_presentation_doc() -> Path:
    presentation_dir = DOCS_DIR / "presentation"
    candidates = [
        p
        for p in presentation_dir.rglob("*.md")
        if "pyscf" in p.name.lower() and "정확도" in p.name
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly 1 presentation source document, found {len(candidates)}: {candidates}"
        )
    return candidates[0]


def _strip_markdown(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = cleaned.replace(r"\*", "*")
    cleaned = cleaned.replace(r"\_", "_")
    cleaned = cleaned.replace("&nbsp;", " ")
    return cleaned.strip()


def _parse_markdown_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    raw_rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        raw_rows.append(cells)

    if len(raw_rows) < 2:
        raise ValueError("Markdown table must include a header and separator row.")

    header = [_strip_markdown(cell) for cell in raw_rows[0]]
    data_rows = []
    for row in raw_rows[2:]:
        normalized = [_strip_markdown(cell) for cell in row]
        if any(normalized):
            data_rows.append(normalized)
    return header, data_rows


def _write_csv(path: Path, header: list[str], rows: Iterable[list[str]]) -> int:
    row_count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            row_count += 1
    return row_count


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _extract_fenced_csv_blocks(source: Path) -> list[dict]:
    text = source.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    blocks: list[dict] = []
    current_heading = ""
    inside_csv = False
    buffer: list[str] = []
    start_line = 0

    for line_no, line in enumerate(lines, start=1):
        if line.startswith("## "):
            current_heading = line[3:].strip()

        if line.strip() == "```csv":
            inside_csv = True
            buffer = []
            start_line = line_no
            continue

        if inside_csv and line.strip() == "```":
            csv_text = "\n".join(buffer).strip() + "\n"
            csv_lines = [item for item in csv_text.splitlines() if item.strip()]
            blocks.append(
                {
                    "heading": current_heading,
                    "start_line": start_line,
                    "end_line": line_no,
                    "csv_text": csv_text,
                    "header": csv_lines[0].split(","),
                    "row_count": max(len(csv_lines) - 1, 0),
                }
            )
            inside_csv = False
            buffer = []
            continue

        if inside_csv:
            buffer.append(line)

    return blocks


def _extract_markdown_table_blocks(source: Path) -> list[dict]:
    text = source.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    blocks: list[dict] = []
    current_heading = ""
    current_block: list[str] = []
    start_line = 0

    for line_no, line in enumerate(lines, start=1):
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()

        if line.strip().startswith("|"):
            if not current_block:
                start_line = line_no
            current_block.append(line)
            continue

        if current_block:
            header, rows = _parse_markdown_table(current_block)
            blocks.append(
                {
                    "heading": current_heading,
                    "start_line": start_line,
                    "end_line": line_no - 1,
                    "header": header,
                    "rows": rows,
                    "row_count": len(rows),
                }
            )
            current_block = []

    if current_block:
        header, rows = _parse_markdown_table(current_block)
        blocks.append(
            {
                "heading": current_heading,
                "start_line": start_line,
                "end_line": len(lines),
                "header": header,
                "rows": rows,
                "row_count": len(rows),
            }
        )

    return blocks


def _generate_manifest(
    values_doc: Path,
    presentation_doc: Path,
    artifact_specs: list[ArtifactSpec],
    artifact_columns: dict[str, list[str]],
    artifact_rows: dict[str, int],
    values_blocks: list[dict],
    table_blocks: list[dict],
) -> dict:
    source_mtime = max(values_doc.stat().st_mtime, presentation_doc.stat().st_mtime)
    generated_at = datetime.fromtimestamp(source_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()

    return {
        "dataset_id": "pyscf_accuracy_assets",
        "dataset_name": "PySCF Literature and Numerical Accuracy Asset Pack",
        "dataset_version": "2026-03-30",
        "generated_at": generated_at,
        "encoding": "utf-8",
        "source_documents": [
            {
                "path": values_doc.relative_to(ROOT).as_posix(),
                "role": "fenced CSV source",
            },
            {
                "path": presentation_doc.relative_to(ROOT).as_posix(),
                "role": "presentation narrative + markdown tables",
            },
        ],
        "artifacts": [
            {
                "filename": spec.filename,
                "kind": spec.kind,
                "description": spec.description,
                "source_document": spec.source_document.relative_to(ROOT).as_posix(),
                "source_locator": spec.source_locator,
                "row_count": artifact_rows[spec.filename],
                "columns": artifact_columns[spec.filename],
            }
            for spec in artifact_specs
        ],
        "regeneration": {
            "command": "python docs/assets/pyscf_accuracy/build_pyscf_accuracy_assets.py",
            "outputs": [spec.filename for spec in artifact_specs] + ["manifest.json"],
        },
        "source_provenance": {
            "fenced_csv_blocks": [
                {
                    "heading": block["heading"],
                    "line_range": [block["start_line"], block["end_line"]],
                    "row_count": block["row_count"],
                }
                for block in values_blocks
            ],
            "markdown_table_blocks": [
                {
                    "heading": block["heading"],
                    "line_range": [block["start_line"], block["end_line"]],
                    "row_count": block["row_count"],
                }
                for block in table_blocks
            ],
        },
    }


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    values_doc = _find_values_doc()
    presentation_doc = _find_presentation_doc()

    values_blocks = _extract_fenced_csv_blocks(values_doc)
    if len(values_blocks) != 3:
        raise RuntimeError(f"Expected 3 fenced CSV blocks in {values_doc}, found {len(values_blocks)}")

    table_blocks = _extract_markdown_table_blocks(presentation_doc)
    if len(table_blocks) != 2:
        raise RuntimeError(f"Expected 2 markdown tables in {presentation_doc}, found {len(table_blocks)}")

    artifact_specs = [
        ArtifactSpec(
            filename="energy_accuracy_comparison.csv",
            kind="csv",
            description="PySCF energy accuracy comparison values extracted from the fenced CSV source.",
            source_document=values_doc,
            source_locator=f"{values_blocks[0]['heading']} (lines {values_blocks[0]['start_line']}-{values_blocks[0]['end_line']})",
        ),
        ArtifactSpec(
            filename="performance_benchmark.csv",
            kind="csv",
            description="Performance and cost benchmark rows extracted from the fenced CSV source.",
            source_document=values_doc,
            source_locator=f"{values_blocks[1]['heading']} (lines {values_blocks[1]['start_line']}-{values_blocks[1]['end_line']})",
        ),
        ArtifactSpec(
            filename="source_registry.csv",
            kind="csv",
            description="Source-level registry of papers, issues, and benchmark references.",
            source_document=values_doc,
            source_locator=f"{values_blocks[2]['heading']} (lines {values_blocks[2]['start_line']}-{values_blocks[2]['end_line']})",
        ),
        ArtifactSpec(
            filename="gh688_total_energy_table.csv",
            kind="csv",
            description="Presentation table for GitHub Issue #688 total-energy comparison.",
            source_document=presentation_doc,
            source_locator=f"{table_blocks[0]['heading']} (lines {table_blocks[0]['start_line']}-{table_blocks[0]['end_line']})",
        ),
        ArtifactSpec(
            filename="literature_summary_matrix.csv",
            kind="csv",
            description="Presentation summary matrix of major PySCF comparison evidence.",
            source_document=presentation_doc,
            source_locator=f"{table_blocks[1]['heading']} (lines {table_blocks[1]['start_line']}-{table_blocks[1]['end_line']})",
        ),
    ]

    artifact_columns: dict[str, list[str]] = {}
    artifact_rows: dict[str, int] = {}

    for spec, block in zip(artifact_specs[:3], values_blocks, strict=True):
        output_path = ASSET_DIR / spec.filename
        _write_text(output_path, block["csv_text"])
        artifact_columns[spec.filename] = block["header"]
        artifact_rows[spec.filename] = block["row_count"]

    for spec, block in zip(artifact_specs[3:], table_blocks, strict=True):
        output_path = ASSET_DIR / spec.filename
        row_count = _write_csv(output_path, block["header"], block["rows"])
        artifact_columns[spec.filename] = block["header"]
        artifact_rows[spec.filename] = row_count

    manifest = _generate_manifest(
        values_doc=values_doc,
        presentation_doc=presentation_doc,
        artifact_specs=artifact_specs,
        artifact_columns=artifact_columns,
        artifact_rows=artifact_rows,
        values_blocks=values_blocks,
        table_blocks=table_blocks,
    )

    with (ASSET_DIR / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
