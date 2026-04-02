"""QCViz-MCP: 양자화학 시각화 및 전자 구조 분석을 위한 MCP 서버.

이 패키지는 빠른 MCP 연동을 위한 백엔드 구조와 도구들을 제공합니다.
"""

from __future__ import annotations

from .env_bootstrap import bootstrap_runtime_env

bootstrap_runtime_env()

__version__ = "0.1.0"
