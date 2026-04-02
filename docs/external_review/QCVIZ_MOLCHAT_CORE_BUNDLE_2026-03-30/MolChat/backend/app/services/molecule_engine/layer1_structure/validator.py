"""
StructureValidator – comprehensive validation of molecular identifiers
and 3D coordinates.

Validation levels:
  1. Syntactic  – is the string well-formed?
  2. Chemical   – does it represent a chemically plausible molecule?
  3. Geometric  – are 3D coordinates reasonable (bond lengths, angles)?

Returns structured ``ValidationReport`` with severity, messages, and auto-fix suggestions.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import _check_rdkit

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    suggestion: str = ""


@dataclass
class ValidationReport:
    is_valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    corrected_value: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity == Severity.ERROR:
            self.is_valid = False


class StructureValidator:
    """Validate molecular identifiers and 3D structures."""

    # ═══════════════════════════════════════════
    # SMILES
    # ═══════════════════════════════════════════

    async def validate_smiles(self, smiles: str) -> ValidationReport:
        """Full SMILES validation: syntax → chemical → sanitization."""
        return await asyncio.to_thread(self._validate_smiles_sync, smiles)

    @staticmethod
    def _validate_smiles_sync(smiles: str) -> ValidationReport:
        report = ValidationReport()
        smiles = smiles.strip()

        if not smiles:
            report.add(ValidationIssue(
                Severity.ERROR, "SMILES_EMPTY", "SMILES string is empty"
            ))
            return report

        if len(smiles) > 5000:
            report.add(ValidationIssue(
                Severity.ERROR, "SMILES_TOO_LONG",
                f"SMILES exceeds maximum length (5000 chars, got {len(smiles)})"
            ))
            return report

        if not _check_rdkit():
            report.add(ValidationIssue(
                Severity.WARNING, "RDKIT_UNAVAILABLE",
                "RDKit not available; only syntactic checks performed"
            ))
            return report

        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        if mol is None:
            report.add(ValidationIssue(
                Severity.ERROR, "SMILES_PARSE_FAILED",
                "Cannot parse SMILES string"
            ))
            return report

        # Sanitization
        try:
            Chem.SanitizeMol(mol)
        except Exception as exc:
            report.add(ValidationIssue(
                Severity.ERROR, "SMILES_SANITIZE_FAILED",
                f"Sanitization failed: {exc}"
            ))
            return report

        # Canonical form
        canonical = Chem.MolToSmiles(mol, canonical=True)
        if canonical != smiles:
            report.corrected_value = canonical
            report.add(ValidationIssue(
                Severity.WARNING, "SMILES_NOT_CANONICAL",
                "Input is not in canonical form",
                suggestion=f"Canonical: {canonical}",
            ))

        # Chemical plausibility checks
        problems = Chem.DetectChemistryProblems(mol)
        for p in problems:
            report.add(ValidationIssue(
                Severity.WARNING, "CHEM_PROBLEM",
                p.Message(),
            ))

        # Metadata
        report.metadata = {
            "heavy_atoms": mol.GetNumHeavyAtoms(),
            "rings": mol.GetRingInfo().NumRings(),
            "formal_charge": Chem.GetFormalCharge(mol),
        }

        return report

    # ═══════════════════════════════════════════
    # InChI / InChIKey
    # ═══════════════════════════════════════════

    async def validate_inchikey(self, inchikey: str) -> ValidationReport:
        """Validate an InChIKey string."""
        return await asyncio.to_thread(self._validate_inchikey_sync, inchikey)

    @staticmethod
    def _validate_inchikey_sync(inchikey: str) -> ValidationReport:
        report = ValidationReport()
        inchikey = inchikey.strip()

        pattern = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
        if not pattern.match(inchikey):
            report.add(ValidationIssue(
                Severity.ERROR, "INCHIKEY_FORMAT",
                "Invalid InChIKey format (expected XXXXXXXXXXXXXX-XXXXXXXXXX-X)",
            ))
            return report

        if _check_rdkit():
            from rdkit.Chem.inchi import CheckInchiKey

            status = CheckInchiKey(inchikey)
            if status != 0:
                report.add(ValidationIssue(
                    Severity.WARNING, "INCHIKEY_CHECK_FAILED",
                    f"RDKit InChIKey check returned status {status}",
                ))

        report.metadata = {"length": len(inchikey)}
        return report

    # ═══════════════════════════════════════════
    # 3D Structure
    # ═══════════════════════════════════════════

    async def validate_3d_structure(
        self,
        structure_data: str,
        fmt: str = "sdf",
    ) -> ValidationReport:
        """Validate a 3D molecular structure for geometric plausibility."""
        return await asyncio.to_thread(
            self._validate_3d_sync, structure_data, fmt
        )

    @staticmethod
    def _validate_3d_sync(structure_data: str, fmt: str) -> ValidationReport:
        report = ValidationReport()

        if not structure_data or not structure_data.strip():
            report.add(ValidationIssue(
                Severity.ERROR, "STRUCTURE_EMPTY", "Structure data is empty"
            ))
            return report

        if not _check_rdkit():
            report.add(ValidationIssue(
                Severity.WARNING, "RDKIT_UNAVAILABLE",
                "Cannot perform 3D validation without RDKit"
            ))
            return report

        from rdkit import Chem
        from rdkit.Chem import rdMolTransforms

        # Parse
        mol = None
        if fmt in ("sdf", "mol"):
            mol = Chem.MolFromMolBlock(structure_data, removeHs=False)
        elif fmt == "xyz":
            mol = Chem.MolFromXYZBlock(structure_data)
        elif fmt == "pdb":
            mol = Chem.MolFromPDBBlock(structure_data, removeHs=False)

        if mol is None:
            report.add(ValidationIssue(
                Severity.ERROR, "STRUCTURE_PARSE_FAILED",
                f"Cannot parse {fmt.upper()} structure"
            ))
            return report

        # Check for 3D conformer
        if mol.GetNumConformers() == 0:
            report.add(ValidationIssue(
                Severity.ERROR, "NO_CONFORMER",
                "Structure contains no 3D conformer"
            ))
            return report

        conf = mol.GetConformer(0)
        if not conf.Is3D():
            report.add(ValidationIssue(
                Severity.WARNING, "NOT_3D",
                "Conformer is flagged as 2D, not 3D"
            ))

        # Bond length checks
        num_atoms = mol.GetNumAtoms()
        for bond in mol.GetBonds():
            i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            dist = rdMolTransforms.GetBondLength(conf, i, j)
            if dist < 0.5:
                report.add(ValidationIssue(
                    Severity.ERROR, "BOND_TOO_SHORT",
                    f"Bond {i}-{j} length {dist:.3f} Å < 0.5 Å"
                ))
            elif dist > 3.0:
                report.add(ValidationIssue(
                    Severity.WARNING, "BOND_TOO_LONG",
                    f"Bond {i}-{j} length {dist:.3f} Å > 3.0 Å"
                ))

        # All-zero coordinates check
        all_zero = all(
            math.isclose(conf.GetAtomPosition(i).x, 0.0, abs_tol=1e-6)
            and math.isclose(conf.GetAtomPosition(i).y, 0.0, abs_tol=1e-6)
            and math.isclose(conf.GetAtomPosition(i).z, 0.0, abs_tol=1e-6)
            for i in range(num_atoms)
        )
        if all_zero:
            report.add(ValidationIssue(
                Severity.ERROR, "ALL_ZERO_COORDS",
                "All atomic coordinates are (0, 0, 0)"
            ))

        report.metadata = {
            "num_atoms": num_atoms,
            "num_bonds": mol.GetNumBonds(),
            "num_conformers": mol.GetNumConformers(),
            "is_3d": conf.Is3D(),
        }

        return report