"""Tests for follow-up regex definition hygiene."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


def test_follow_up_regex_names_are_uniquely_defined():
    path = Path("src/qcviz_mcp/llm/normalizer.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = Counter()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("_FOLLOW_UP_"):
                    assignments[target.id] += 1

    duplicates = {name: count for name, count in assignments.items() if count > 1}
    assert not duplicates, f"Duplicate follow-up regex definitions found: {duplicates}"
