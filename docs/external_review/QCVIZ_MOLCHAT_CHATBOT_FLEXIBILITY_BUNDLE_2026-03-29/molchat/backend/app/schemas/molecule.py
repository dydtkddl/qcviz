"""
Pydantic schemas for molecule-related API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════
# Sub-schemas
# ═══════════════════════════════════════════════


class PropertyData(BaseModel):
    """Computed or imported property set."""

    model_config = ConfigDict(from_attributes=True)

    source: str = Field(..., description="Property source: pubchem, rdkit, xtb")
    data: dict[str, Any] = Field(default_factory=dict, description="Property key-value pairs")


class StructureData(BaseModel):
    """3D/2D structure representation."""

    model_config = ConfigDict(from_attributes=True)

    format: str = Field(..., description="Structure format: sdf, mol2, xyz, pdb")
    structure_data: str = Field(..., description="Raw structure content")
    generation_method: str = Field(..., description="How the structure was generated")
    is_primary: bool = False


# ═══════════════════════════════════════════════
# Core Record
# ═══════════════════════════════════════════════


class MoleculeRecord(BaseModel):
    """Full molecule representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cid: int | None = None
    name: str
    canonical_smiles: str
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    properties: dict[str, Any] | None = None
    structures: list[StructureData] = Field(default_factory=list)
    computed_properties: list[PropertyData] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════
# Request / Response
# ═══════════════════════════════════════════════


class MoleculeSearchRequest(BaseModel):
    """Query parameters for molecule search."""

    q: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Search query: name, SMILES, InChIKey, CID, or formula",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    sources: list[str] | None = Field(
        default=None,
        description="Filter sources: pubchem, chembl, chemspider, zinc, local",
    )


class MoleculeSearchResponse(BaseModel):
    """Paginated search results."""

    query: str
    total: int
    limit: int
    offset: int
    results: list[MoleculeRecord]
    sources_queried: list[str]
    cache_hit: bool = False
    resolved_query: str | None = None
    original_query: str | None = None
    resolve_method: str | None = None
    resolve_suggestions: list[str] = []
    elapsed_ms: float


class MoleculeInterpretRequest(BaseModel):
    """Free-form molecule description that needs grounded candidates."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Name-like or semantic molecule description from the user",
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum grounded candidates to return")


class MoleculeInterpretCandidate(BaseModel):
    """Grounded candidate molecule produced from a semantic query."""

    name: str
    cid: int | None = None
    canonical_smiles: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = Field(default="semantic_llm")
    rationale: str | None = None


class MoleculeInterpretResponse(BaseModel):
    """Structured candidate list for semantic grounding in downstream clients."""

    query: str
    query_mode: str
    normalized_query: str | None = None
    resolution_method: str | None = None
    notes: list[str] = Field(default_factory=list)
    candidates: list[MoleculeInterpretCandidate] = Field(default_factory=list)


class MoleculeDetailResponse(BaseModel):
    """Detailed molecule view with all structures and properties."""

    molecule: MoleculeRecord
    available_formats: list[str] = Field(default_factory=list)
    calculation_status: str | None = None  # pending, running, completed, failed
    related_molecules: list[MoleculeRecord] = Field(default_factory=list)
