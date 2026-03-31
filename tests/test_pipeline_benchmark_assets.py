from __future__ import annotations

from tests.semantic_benchmark import (
    PIPELINE_BENCHMARK_DATASETS,
    count_dataset_variants,
    load_pipeline_benchmark_datasets,
)


def test_pipeline_benchmark_asset_suite_covers_at_least_100_variants():
    datasets = load_pipeline_benchmark_datasets()
    total_variants = sum(count_dataset_variants(dataset) for dataset in datasets)
    assert total_variants >= 100


def test_each_pipeline_benchmark_dataset_has_required_shape():
    for dataset_name, dataset in zip(PIPELINE_BENCHMARK_DATASETS, load_pipeline_benchmark_datasets()):
        assert dataset["dataset_id"] == dataset_name
        assert isinstance(dataset.get("cases"), list)
        assert dataset["cases"], f"{dataset_name} must contain at least one case"
        for case in dataset["cases"]:
            assert str(case.get("id") or "").strip()
            assert str(case.get("input") or "").strip()
            assert isinstance(case.get("variants") or [], list)
            assert str(case.get("category") or "").strip()
            assert isinstance(case.get("must_not_happen") or [], list)
            if "semantic_" in dataset_name:
                assert str(case.get("expected_outcome") or "").strip()
            else:
                assert str(case.get("expected_lane") or "").strip()
