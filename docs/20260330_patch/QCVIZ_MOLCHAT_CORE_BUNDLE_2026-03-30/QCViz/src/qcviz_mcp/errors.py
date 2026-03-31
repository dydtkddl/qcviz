from enum import Enum

class ErrorCategory(str, Enum):
    VALIDATION = "validation"       # 입력 검증 실패
    CONVERGENCE = "convergence"     # SCF 수렴 실패
    RESOURCE = "resource"           # 메모리/타임아웃
    BACKEND = "backend"             # 백엔드 라이브러리 오류
    INTERNAL = "internal"           # 예상치 못한 오류

class QCVizError(Exception):
    """모든 QCViz 에러의 기본 클래스."""
    
    def __init__(self, message: str, category: ErrorCategory, 
                 suggestion: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.category = category
        self.suggestion = suggestion
        self.details = details or {}
    
    def to_mcp_response(self) -> dict:
        """MCP 프로토콜 호환 에러 응답 생성."""
        resp = {
            "error": {
                "category": self.category.value,
                "message": str(self),
            }
        }
        if self.suggestion:
            resp["error"]["suggestion"] = self.suggestion
        return resp


class ValidationError(QCVizError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorCategory.VALIDATION, **kwargs)

class ConvergenceError(QCVizError):
    def __init__(self, message: str, strategies_tried: list[str] | None = None, **kwargs):
        suggestion = (
            "Try: (1) a smaller basis set, (2) adaptive=True for 5-level escalation, "
            "(3) providing an initial guess, or (4) checking molecular geometry."
        )
        super().__init__(message, ErrorCategory.CONVERGENCE, suggestion=suggestion, **kwargs)
        self.strategies_tried = strategies_tried or []

class ResourceError(QCVizError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorCategory.RESOURCE, **kwargs)

class BackendError(QCVizError):
    def __init__(self, message: str, backend_name: str = "", **kwargs):
        super().__init__(message, ErrorCategory.BACKEND, **kwargs)
        self.backend_name = backend_name
