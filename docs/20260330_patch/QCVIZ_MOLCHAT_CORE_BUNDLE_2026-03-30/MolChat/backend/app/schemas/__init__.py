"""
Pydantic schemas (request / response models) for MolChat API.
"""

from app.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    SessionCreate,
    SessionResponse,
    SessionListResponse,
)
from app.schemas.common import (
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
    SuccessResponse,
)
from app.schemas.molecule import (
    MoleculeRecord,
    MoleculeSearchRequest,
    MoleculeSearchResponse,
    MoleculeDetailResponse,
    PropertyData,
    StructureData,
)

__all__ = [
    # Chat
    "ChatRequest",
    "ChatResponse",
    "ChatMessageResponse",
    "SessionCreate",
    "SessionResponse",
    "SessionListResponse",
    # Common
    "ErrorResponse",
    "HealthResponse",
    "PaginatedResponse",
    "SuccessResponse",
    # Molecule
    "MoleculeRecord",
    "MoleculeSearchRequest",
    "MoleculeSearchResponse",
    "MoleculeDetailResponse",
    "PropertyData",
    "StructureData",
]