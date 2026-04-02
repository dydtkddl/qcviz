"""
Molecule-related ORM models.
Tables: molecules, molecule_structures, molecule_properties
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Molecule(Base):
    """Core molecule table – one row per unique compound."""

    __tablename__ = "molecules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cid: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    canonical_smiles: Mapped[str] = mapped_column(Text, nullable=False)
    inchi: Mapped[str | None] = mapped_column(Text)
    inchikey: Mapped[str | None] = mapped_column(
        String(27), unique=True, index=True
    )
    molecular_formula: Mapped[str | None] = mapped_column(String(256))
    molecular_weight: Mapped[float | None] = mapped_column(Float)
    properties: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    # Soft-delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    structures: Mapped[list[MoleculeStructure]] = relationship(
        "MoleculeStructure", back_populates="molecule", cascade="all, delete-orphan"
    )
    computed_properties: Mapped[list[MoleculeProperty]] = relationship(
        "MoleculeProperty", back_populates="molecule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_molecules_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_molecules_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "gin_trgm_ops"}),
        Index("ix_molecules_properties_gin", "properties", postgresql_using="gin"),
        Index("ix_molecules_not_deleted", "is_deleted",
              postgresql_where=(is_deleted.is_(False))),
    )

    def __repr__(self) -> str:
        return f"<Molecule(id={self.id}, name='{self.name}', cid={self.cid})>"


class MoleculeStructure(Base):
    """3D/2D structure data for a molecule (SDF, MOL2, XYZ, etc.)."""

    __tablename__ = "molecule_structures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    molecule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("molecules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format: Mapped[str] = mapped_column(
        String(20), nullable=False  # sdf, mol2, xyz, pdb, mol
    )
    structure_data: Mapped[str] = mapped_column(Text, nullable=False)
    generation_method: Mapped[str] = mapped_column(
        String(50), nullable=False  # pubchem, rdkit, xtb-optimized
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    molecule: Mapped[Molecule] = relationship("Molecule", back_populates="structures")

    __table_args__ = (
        UniqueConstraint(
            "molecule_id", "format", "is_primary",
            name="uq_mol_struct_primary",
        ),
        Index("ix_molstruct_mol_format", "molecule_id", "format"),
    )

    def __repr__(self) -> str:
        return (
            f"<MoleculeStructure(id={self.id}, format='{self.format}', "
            f"method='{self.generation_method}')>"
        )


class MoleculeProperty(Base):
    """Computed / imported property set for a molecule."""

    __tablename__ = "molecule_properties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    molecule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("molecules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False  # pubchem, rdkit, xtb
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    molecule: Mapped[Molecule] = relationship(
        "Molecule", back_populates="computed_properties"
    )

    __table_args__ = (
        Index("ix_molprop_mol_source", "molecule_id", "source"),
        Index("ix_molprop_data_gin", "data", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<MoleculeProperty(id={self.id}, source='{self.source}')>"