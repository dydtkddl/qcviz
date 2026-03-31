"""Rule-based LLM provider fallback."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class ParsedPlan:
    intent: str
    query: str
    metadata: Dict[str, Any] = field(default_factory=dict)

def plan_from_message(message: str) -> ParsedPlan:
    """Parse message via simple rules."""
    msg_lower = message.lower()
    intent_type = "resolve_structure"

    if "최적화" in msg_lower or "optimize" in msg_lower:
        intent_type = "geometry_opt"
    elif "에너지" in msg_lower or "단일점" in msg_lower or "single point" in msg_lower:
        intent_type = "single_point"
    elif "결합" in msg_lower or "구조 분석" in msg_lower or "validate" in msg_lower:
        intent_type = "validate"
    elif "전하" in msg_lower or "charge" in msg_lower:
        intent_type = "partial_charges"
    elif "오비탈" in msg_lower or "orbital" in msg_lower or "homo" in msg_lower or "lumo" in msg_lower:
        intent_type = "orbital"

    query = message
    for kw in ["계산해줘", "분석해줘", "보여줘", "그려줘", "알려줘"]:
        query = query.replace(kw, "")

    query = query.strip()

    return ParsedPlan(intent=intent_type, query=query)
