"""LLM bridge for QCViz web UI."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

from qcviz_mcp.llm.rule_provider import plan_from_message

logger = logging.getLogger(__name__)


@dataclass
class Intent:
    """Normalized intent."""

    intent: str
    query: str
    metadata: Dict[str, Any]


class LLMBridge:
    """Tiered LLM bridge.

    Bootstrap implementation:
    - rule_based
    - auto -> rule_based
    - advisor direct-call helper
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode or "auto"

    def interpret_user_intent(self, message: str) -> Intent:
        """Interpret natural language into structured intent."""
        parsed = plan_from_message(message)
        return Intent(
            intent=parsed.intent,
            query=parsed.query,
            metadata=parsed.metadata,
        )

    def _load_advisor_module(self):
        """Load advisor tool module."""
        return importlib.import_module("qcviz_mcp.tools.advisor_tools")

    def call_advisor_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Call an advisor MCP tool directly as a Python function.

        Args:
            tool_name: Advisor tool name.
            params: Candidate kwargs.

        Returns:
            Tool output, parsed as JSON when possible.
        """
        module = self._load_advisor_module()

        if not hasattr(module, tool_name):
            raise AttributeError("advisor tool not found: %s" % tool_name)

        func = getattr(module, tool_name)
        sig = inspect.signature(func)
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )

        kwargs = {}
        for key, value in dict(params or {}).items():
            if accepts_kwargs or key in sig.parameters:
                kwargs[key] = value

        raw = func(**kwargs)

        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return raw

        return raw

    def generate_response(self, intent: Intent, results: Dict[str, Any]) -> str:
        """Generate a user-facing response."""
        if results.get("status") == "error":
            return "요청을 처리하지 못했습니다. %s" % results.get("error", "알 수 없는 오류")

        advisor = results.get("advisor") or {}
        confidence = advisor.get("confidence") or {}
        confidence_data = confidence.get("data") if isinstance(confidence, dict) else None

        literature = advisor.get("literature") or {}
        literature_data = literature.get("data") if isinstance(literature, dict) else None

        if intent.intent == "geometry_opt":
            base = "구조 최적화 계산이 완료되었습니다. 오른쪽 뷰어에서 최적화된 3D 구조를 확인하세요."
        elif intent.intent == "validate":
            base = "기하구조 분석이 완료되었습니다. 결합 길이와 각도 표를 확인하세요."
        elif intent.intent == "partial_charges":
            base = "부분 전하 계산이 완료되었습니다. Charges 탭에서 원자별 전하를 확인하세요."
        elif intent.intent == "orbital":
            base = "오비탈 프리뷰 계산이 완료되었습니다. Orbitals 탭에서 HOMO/LUMO 근처 궤도를 확인하세요."
        elif intent.intent == "single_point":
            base = "단일점 에너지 계산이 완료되었습니다."
        else:
            base = "요청한 구조 또는 계산 작업이 완료되었습니다."

        parts = [base]

        if results.get("method") and results.get("basis"):
            parts.append(
                "advisor 추천 또는 기본 설정으로 %s/%s 조건을 사용했습니다."
                % (results.get("method"), results.get("basis"))
            )

        if isinstance(confidence_data, dict):
            score = (
                confidence_data.get("score")
                or confidence_data.get("confidence")
                or confidence_data.get("final_score")
            )
            if score is not None:
                parts.append("신뢰도 점수는 %s 입니다." % score)

        if isinstance(literature_data, dict):
            status = (
                literature_data.get("status")
                or literature_data.get("summary")
                or literature_data.get("message")
            )
            if status:
                parts.append("문헌 검증 요약: %s" % status)

        return " ".join(parts)