from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from qcviz_mcp.observability import metrics

logger = logging.getLogger(__name__)


@dataclass
class PipelineTrace:
    trace_id: str
    session_id: Optional[str] = None
    raw_input: str = ""
    stage_outputs: Dict[str, Any] = field(default_factory=dict)
    stage_latencies_ms: Dict[str, float] = field(default_factory=dict)
    provider: Optional[str] = None
    fallback_stage: Optional[str] = None
    fallback_reason: Optional[str] = None
    locked_lane: Optional[str] = None
    repair_count: int = 0
    serve_mode: Optional[str] = None
    llm_vs_heuristic_agreement: Optional[bool] = None
    total_latency_ms: Optional[float] = None

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "raw_input": self.raw_input,
            "stage_outputs": self.stage_outputs,
            "stage_latencies_ms": self.stage_latencies_ms,
            "provider": self.provider,
            "fallback_stage": self.fallback_stage,
            "fallback_reason": self.fallback_reason,
            "locked_lane": self.locked_lane,
            "repair_count": self.repair_count,
            "serve_mode": self.serve_mode,
            "llm_vs_heuristic_agreement": self.llm_vs_heuristic_agreement,
            "total_latency_ms": self.total_latency_ms,
        }


def emit_pipeline_trace(trace: PipelineTrace) -> None:
    metrics.increment("pipeline.trace.count")
    if trace.stage_outputs.get("stage1_ingress", {}).get("llm_rewrite_used"):
        metrics.increment("pipeline.stage1.rewrite_rate")
    if trace.stage_outputs.get("stage2_router"):
        metrics.increment("pipeline.stage2.main_success_rate")
    if trace.repair_count > 0 and not trace.fallback_stage:
        metrics.increment("pipeline.stage2.repair_success_rate")
    if trace.fallback_stage:
        metrics.increment("pipeline.stage2.fallback_rate")
        metrics.increment(f"pipeline.fallback_stage.{trace.fallback_stage}")
    if trace.locked_lane:
        metrics.increment(f"pipeline.lane_distribution.{trace.locked_lane}")
    if trace.total_latency_ms is not None:
        metrics.observe("pipeline.e2e_latency_ms", trace.total_latency_ms)
    for stage_name, latency_ms in trace.stage_latencies_ms.items():
        metrics.observe(f"pipeline.{stage_name}.latency_ms", latency_ms)
    if trace.llm_vs_heuristic_agreement is not None:
        metrics.increment(
            "pipeline.llm_vs_heuristic_agreement.match"
            if trace.llm_vs_heuristic_agreement
            else "pipeline.llm_vs_heuristic_agreement.mismatch"
        )
    logger.info("QCViz pipeline trace: %s", trace.to_log_dict())
