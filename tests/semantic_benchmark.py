from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from qcviz_mcp.web.routes import chat as chat_route
from qcviz_mcp.web.routes import compute as compute_route

ASSET_DIR = Path(__file__).resolve().parent / "assets"
GENERIC_FALLBACK_NAMES = {"water", "methane", "ethanol", "methanol", "benzene"}
PIPELINE_BENCHMARK_DATASETS = (
    "semantic_explanation_benchmark",
    "semantic_compute_benchmark",
    "direct_molecule_compute_benchmark",
    "follow_up_parameter_only_benchmark",
    "red_team_benchmark",
)


def load_semantic_benchmark(name: str) -> Dict[str, Any]:
    path = ASSET_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def iter_case_variants(dataset: Dict[str, Any]) -> Iterable[Tuple[Dict[str, Any], str]]:
    for case in list(dataset.get("cases") or []):
        for text in [case.get("input"), *(case.get("variants") or [])]:
            if str(text or "").strip():
                yield case, str(text)


def benchmark_param_id(case: Dict[str, Any], text: str) -> str:
    variants = [case.get("input"), *(case.get("variants") or [])]
    index = variants.index(text) if text in variants else 0
    return f"{case['id']}[{index}]"


def install_semantic_case_stub(monkeypatch, case: Dict[str, Any]) -> None:
    payload = copy.deepcopy(case.get("molchat_result") or {})

    class _DummyMolChat:
        async def interpret_candidates(self, query: str, limit: int = 5):
            out = copy.deepcopy(payload)
            out["query"] = query
            out.setdefault("notes", [])
            out["candidates"] = list(out.get("candidates") or [])[:limit]
            return out

    class _DummyResolver:
        molchat = _DummyMolChat()

        def suggest_candidate_queries(self, query: str, limit: int = 5):
            return []

    monkeypatch.setattr(chat_route, "_get_resolver", lambda: _DummyResolver(), raising=False)
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)


def expected_candidate_names(case: Dict[str, Any]) -> List[str]:
    return [str(item.get("name")).strip() for item in list(case.get("molchat_result", {}).get("candidates") or []) if str(item.get("name") or "").strip()]


def count_dataset_variants(dataset: Dict[str, Any]) -> int:
    return sum(1 + len(case.get("variants") or []) for case in list(dataset.get("cases") or []))


def load_pipeline_benchmark_datasets() -> List[Dict[str, Any]]:
    return [load_semantic_benchmark(name) for name in PIPELINE_BENCHMARK_DATASETS]
