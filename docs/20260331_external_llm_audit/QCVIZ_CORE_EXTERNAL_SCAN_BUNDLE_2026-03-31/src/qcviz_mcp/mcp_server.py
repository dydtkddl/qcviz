"""FastMCP 서버 엔트리포인트 (스텁).
Phase 2와 Phase 3 사이에서 유닛 테스트와 통합 테스트를 원활하게 진행하기 위해 뼈대만 작성합니다.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 초기화
mcp = FastMCP("QCViz-MCP")

# Tools 등록
import qcviz_mcp.tools.core  # noqa: F401
import qcviz_mcp.tools.advisor_tools  # noqa: F401  — v5.0 advisor

if __name__ == "__main__":
    logger.info("QCViz-MCP 서버 시작 중...")
    mcp.run()
