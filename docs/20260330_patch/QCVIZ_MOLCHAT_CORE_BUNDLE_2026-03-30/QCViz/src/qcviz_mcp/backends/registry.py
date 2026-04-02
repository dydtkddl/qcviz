"""QCViz-MCP 백엔드 레지스트리 시스템.

플러그인 형태의 백엔드를 등록하고 관리하며, 사용 가능한 백엔드를 동적으로 제공합니다.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from qcviz_mcp.backends.base import (
    BackendBase,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BackendBase)


class BackendNotAvailableError(Exception):
    """요청한 백엔드를 사용할 수 없거나 필수 의존성이 설치되지 않았을 때 발생하는 예외."""

    pass


class BackendRegistry:
    """백엔드 클래스들을 등록하고 관리하는 레지스트리."""

    def __init__(self) -> None:
        self._backends: dict[str, type[BackendBase]] = {}
        self._instances: dict[str, BackendBase] = {}

    def register(self, backend_class: type[BackendBase]) -> None:
        """새로운 백엔드 클래스를 등록합니다."""
        name = backend_class.name()
        self._backends[name] = backend_class
        logger.debug("백엔드 %s 등록됨", name)

    def get(self, name: str) -> BackendBase:
        """이름으로 백엔드 인스턴스를 가져옵니다(싱글톤)."""
        if name not in self._backends:
            raise ValueError(f"알 수 없는 백엔드: {name}")

        backend_class = self._backends[name]
        if not backend_class.is_available():
            raise BackendNotAvailableError(
                f"백엔드 '{name}'를 사용할 수 없습니다. 의존성 패키지를 설치해주세요."
            )

        if name not in self._instances:
            self._instances[name] = backend_class()

        return self._instances[name]

    def get_by_type(self, backend_type: type[T]) -> list[T]:
        """특정 타입(인터페이스)을 구현한 사용 가능한 모든 백엔드 인스턴스 목록을 반환합니다."""
        instances = []
        for name, cls in self._backends.items():
            if issubclass(cls, backend_type) and cls.is_available():
                instances.append(self.get(name))
        return instances


# 전역 기본 레지스트리 인스턴스
registry = BackendRegistry()
