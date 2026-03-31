from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.semantic_benchmark import load_semantic_benchmark

CORE_DECISION_FILES = [
    Path("src/qcviz_mcp/llm/normalizer.py"),
    Path("src/qcviz_mcp/llm/agent.py"),
    Path("src/qcviz_mcp/llm/pipeline.py"),
    Path("src/qcviz_mcp/web/routes/chat.py"),
    Path("src/qcviz_mcp/web/routes/compute.py"),
]


def _token_regex(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(token.lower())}(?![A-Za-z0-9_])")


def _conditional_source_segments(source_text: str) -> list[str]:
    tree = ast.parse(source_text)
    segments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)):
            segment = ast.get_source_segment(source_text, node) or ""
            if segment:
                segments.append(segment)
    return segments


def test_benchmark_case_names_do_not_appear_in_core_decision_branches():
    datasets = [
        load_semantic_benchmark("semantic_explanation_benchmark"),
        load_semantic_benchmark("semantic_compute_benchmark"),
    ]
    tokens = sorted(
        {
            str(token).strip()
            for dataset in datasets
            for token in list(dataset.get("benchmark_tokens") or [])
            if str(token).strip()
        }
    )
    assert tokens

    for relative_path in CORE_DECISION_FILES:
        source_text = relative_path.read_text(encoding="utf-8")
        conditional_segments = _conditional_source_segments(source_text)
        for token in tokens:
            matcher = _token_regex(token)
            assert not any(matcher.search(segment.lower()) for segment in conditional_segments), (
                f"Benchmark token {token!r} leaked into a core decision branch in {relative_path}"
            )
