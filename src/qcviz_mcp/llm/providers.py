"""
LLM Provider implementations (Gemini, OpenAI).
"""

import json
import os
import logging
from typing import Optional
from pydantic import ValidationError

from .schemas import PlannerRequest, PlannerResponse, ToolCall
from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("qcviz_mcp.llm.providers")

try:
    from google import genai
    from google.genai import types
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False


class LLMProvider:
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        raise NotImplementedError()


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        if not _HAS_GEMINI:
            raise ImportError("google-genai is not installed. Run: pip install google-genai")
        
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
            
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-2.5-flash"
        
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        user_prompt = request.user_prompt
        
        prompt_text = f"""
        User Request: {user_prompt}
        
        Available Tools: {request.available_tools}
        
        Return a JSON object that perfectly matches the PlannerResponse schema.
        """
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=PlannerResponse.model_json_schema(),
                    temperature=0.1,
                ),
            )
            
            raw_text = response.text
            data = json.loads(raw_text)
            return PlannerResponse(**data)
            
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            # Fallback to rule-based logic or default response
            return PlannerResponse(
                thought_process=f"Failed to call LLM: {str(e)}",
                assistant_message="AI 에이전트 호출에 실패하여 기본 룰(Rule-based) 모드로 동작합니다.",
                tool_calls=[],
                is_help_only=True
            )


class DummyProvider(LLMProvider):
    """Fallback provider when no API key is available. Simulates basic rule-based routing."""
    
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        text = request.user_prompt.lower()
        tool = "run_single_point"
        focus = "summary"
        
        if any(x in text for x in ["orbital", "homo", "lumo", "오비탈"]):
            tool = "run_orbital_preview"
            focus = "orbitals"
        elif any(x in text for x in ["esp", "potential", "map", "전기정전위"]):
            tool = "run_esp_map"
            focus = "esp"
        elif any(x in text for x in ["charge", "mulliken", "부분 전하"]):
            tool = "run_partial_charges"
            focus = "charges"
        elif any(x in text for x in ["opt", "최적화"]):
            tool = "run_geometry_optimization"
            focus = "geometry"
            
        return PlannerResponse(
            thought_process="Rule-based fallback routing.",
            assistant_message="API 키가 설정되지 않아 로컬 규칙 기반 엔진이 요청을 처리합니다.",
            tool_calls=[ToolCall(tool_name=tool, parameters={"query": request.user_prompt})],
            is_help_only=False,
            suggested_focus_tab=focus
        )


def get_provider() -> LLMProvider:
    if os.environ.get("GEMINI_API_KEY") and _HAS_GEMINI:
        return GeminiProvider()
    
    logger.warning("No LLM API key found or SDK missing. Using DummyProvider (Rule-based fallback).")
    return DummyProvider()