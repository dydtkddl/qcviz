"""
Pydantic schemas for the Molecule Card endpoint.
Comprehensive single-molecule view: properties, safety, drug-likeness, similar molecules, AI summary.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DrugLikenessResult(BaseModel):
    """Result of a single drug-likeness rule evaluation."""
    rule_name: str = Field(..., description="Rule name: Lipinski, Veber, Ghose")
    passed: bool = Field(..., description="Whether the molecule passes this rule")
    violations: list[str] = Field(default_factory=list, description="List of violated criteria")
    details: str = ""


class GHSSafety(BaseModel):
    """GHS (Globally Harmonized System) safety classification."""
    signal_word: str | None = Field(default=None, description="Danger / Warning / None")
    pictograms: list[str] = Field(default_factory=list, description="GHS pictogram codes: GHS01~GHS09")
    pictogram_urls: list[str] = Field(default_factory=list, description="PubChem pictogram image URLs")
    h_statements: list[str] = Field(default_factory=list, description="Hazard statements")
    p_statements: list[str] = Field(default_factory=list, description="Precautionary statements")
    ld50: str | None = Field(default=None, description="LD50 data if available")


class SimilarMolecule(BaseModel):
    """A molecule similar to the queried one."""
    cid: int
    name: str = "Unknown"
    similarity: float = Field(..., ge=0.0, le=1.0, description="Tanimoto similarity 0~1")
    molecular_formula: str | None = None
    thumbnail_url: str = ""


class MoleculeCardResponse(BaseModel):
    """Comprehensive molecule card - everything you need in one response."""

    model_config = ConfigDict(from_attributes=True)

    # Identity
    id: uuid.UUID
    cid: int | None = None
    name: str = Field(..., description="Common name (enriched from synonyms)")
    iupac_name: str | None = None
    synonyms: list[str] = Field(default_factory=list)

    # Structure identifiers
    canonical_smiles: str
    inchi: str | None = None
    inchikey: str | None = None
    image_url: str = Field(default="", description="PubChem 2D structure PNG URL")

    # Core properties
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    xlogp: float | None = None
    tpsa: float | None = None
    hbond_donor: int | None = None
    hbond_acceptor: int | None = None
    rotatable_bonds: int | None = None
    heavy_atom_count: int | None = None
    complexity: float | None = None
    exact_mass: str | None = None
    charge: int | None = None

    # Drug-likeness
    drug_likeness: list[DrugLikenessResult] = Field(default_factory=list)

    # Safety
    ghs_safety: GHSSafety | None = None

    # Similar molecules
    similar_molecules: list[SimilarMolecule] = Field(default_factory=list)

    # AI Summary
    ai_summary: str | None = Field(default=None, description="LLM-generated 1-2 sentence summary")

    # Metadata
    source: str = "pubchem"
    source_url: str | None = None
    elapsed_ms: float = 0.0
    cached: bool = False
