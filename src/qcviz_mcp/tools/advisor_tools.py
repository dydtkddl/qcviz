"""QCViz-MCP v5.0 — Advisor Module MCP Tool Registration.

Registers 5 advisor tools that provide AI-driven chemistry research guidance:
  1. recommend_preset - DFT calculation settings recommendation
  2. draft_methods_section - Publication-ready methods text generation
  3. generate_script - Standalone PySCF script export
  4. validate_against_literature - NIST reference data validation
  5. score_confidence - Composite confidence scoring
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.advisor import (
    PresetRecommender,
    MethodsSectionDrafter,
    CalculationRecord,
    ReproducibilityScriptGenerator,
    LiteratureEnergyValidator,
    ValidationRequest,
    ConfidenceScorer,
)

logger = logging.getLogger(__name__)

# Singleton instances — created once at import time
_recommender = PresetRecommender()
_drafter = MethodsSectionDrafter()
_script_gen = ReproducibilityScriptGenerator()
_validator = LiteratureEnergyValidator()
_scorer = ConfidenceScorer()


@mcp.tool()
def recommend_preset(
    atom_spec: str,
    purpose: str = "geometry_opt",
    charge: int = 0,
    spin: int = 0,
) -> str:
    """Analyze molecular structure and recommend optimal DFT calculation
    settings (functional, basis set, dispersion correction) with
    literature-backed justification.

    Args:
        atom_spec: Molecular structure in XYZ format.
        purpose: Calculation purpose (geometry_opt, single_point,
                 bonding_analysis, reaction_energy, spectroscopy,
                 esp_mapping).
        charge: Molecular charge.
        spin: Spin multiplicity (2S, e.g. 0=singlet, 1=doublet).

    Returns:
        JSON string with recommendation details.
    """
    try:
        rec = _recommender.recommend(
            atom_spec=atom_spec,
            purpose=purpose,
            charge=charge,
            spin=spin,
        )
        return json.dumps({
            "functional": rec.functional,
            "basis": rec.basis,
            "dispersion": rec.dispersion,
            "spin_treatment": rec.spin_treatment,
            "relativistic": rec.relativistic,
            "convergence": rec.convergence,
            "alternatives": [
                {"functional": a[0], "basis": a[1], "rationale": a[2]}
                for a in rec.alternatives
            ],
            "warnings": rec.warnings,
            "references": rec.references,
            "rationale": rec.rationale,
            "confidence": rec.confidence,
            "pyscf_settings": rec.pyscf_settings,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("recommend_preset error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def draft_methods_section(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    software_version: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    citation_style: str = "acs",
    energy_hartree: float = 0.0,
    converged: bool = True,
    n_cycles: int = 0,
) -> str:
    """Generate publication-ready Computational Methods text with BibTeX
    citations from calculation metadata.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional used (e.g. B3LYP-D3(BJ)).
        basis: Basis set used (e.g. def2-SVP).
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction (e.g. D3BJ).
        software_version: PySCF version string.
        optimizer: Geometry optimizer (e.g. geomeTRIC).
        analysis_type: Analysis performed (ibo, iao, esp).
        citation_style: Citation style (acs, rsc, nature).
        energy_hartree: Total energy in Hartree.
        converged: Whether SCF converged.
        n_cycles: Number of SCF cycles.

    Returns:
        JSON with methods_text, bibtex_entries, reviewer_notes, disclaimer.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            software="PySCF",
            software_version=software_version,
            optimizer=optimizer,
            analysis_type=analysis_type,
            energy_hartree=energy_hartree,
            converged=converged,
            n_cycles=n_cycles,
        )
        draft = _drafter.draft(
            [record],
            citation_style=citation_style,
            include_bibtex=True,
        )
        return json.dumps({
            "methods_text": draft.methods_text,
            "bibtex_entries": draft.bibtex_entries,
            "reviewer_notes": draft.reviewer_notes,
            "disclaimer": draft.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("draft_methods_section error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def generate_script(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    include_analysis: bool = True,
) -> str:
    """Generate standalone PySCF Python script that reproduces a
    calculation without QCViz-MCP.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional.
        basis: Basis set.
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction.
        optimizer: Geometry optimizer.
        analysis_type: Analysis type (ibo, esp, etc).
        include_analysis: Whether to include analysis code.

    Returns:
        Complete Python script as a string.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            optimizer=optimizer,
            analysis_type=analysis_type,
        )
        return _script_gen.generate(record, include_analysis=include_analysis)
    except Exception as e:
        logger.error("generate_script error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def validate_against_literature(
    system_formula: str,
    functional: str,
    basis: str,
    bond_lengths: Optional[dict] = None,
    bond_angles: Optional[dict] = None,
) -> str:
    """Compare computed molecular properties against NIST CCCBDB
    reference data and flag deviations.

    Args:
        system_formula: Hill-system molecular formula (e.g. H2O, CH4).
        functional: DFT functional used.
        basis: Basis set used.
        bond_lengths: Dict of bond_type to length in Angstrom.
        bond_angles: Dict of angle_type to angle in degrees.

    Returns:
        JSON with validation results, status, and recommendations.
    """
    try:
        req = ValidationRequest(
            system_formula=system_formula,
            functional=functional,
            basis=basis,
            bond_lengths=bond_lengths or {},
            bond_angles=bond_angles or {},
        )
        result = _validator.validate(req)
        return json.dumps({
            "overall_status": result.overall_status,
            "confidence": result.confidence,
            "method_assessment": result.method_assessment,
            "bond_validations": [
                {
                    "bond": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                    "comment": v.comment,
                }
                for v in result.bond_validations
            ],
            "angle_validations": [
                {
                    "angle": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                }
                for v in result.angle_validations
            ],
            "recommendations": result.recommendations,
            "disclaimer": result.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("validate_against_literature error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def score_confidence(
    functional: str,
    basis: str,
    converged: bool = True,
    n_scf_cycles: int = 0,
    max_cycles: int = 200,
    system_type: str = "organic_small",
    spin: int = 0,
    s2_expected: float = 0.0,
    s2_actual: float = 0.0,
    validation_status: str = None,
) -> str:
    """Compute composite confidence score (0-1) for a quantum chemistry
    calculation based on convergence, method quality, and reference
    agreement.

    Args:
        functional: DFT functional used.
        basis: Basis set used.
        converged: Whether SCF converged.
        n_scf_cycles: Number of SCF cycles taken.
        max_cycles: Maximum allowed SCF cycles.
        system_type: System classification (organic_small, organic_large,
                     3d_tm, heavy_tm, lanthanide, radical,
                     charged_organic, main_group_metal).
        spin: Spin multiplicity.
        s2_expected: Expected <S^2> value.
        s2_actual: Actual <S^2> value.
        validation_status: Literature validation status (PASS/WARN/FAIL).

    Returns:
        JSON with overall_score, sub-scores, breakdown, and recommendations.
    """
    try:
        report = _scorer.score(
            converged=converged,
            n_scf_cycles=n_scf_cycles,
            max_cycles=max_cycles,
            functional=functional,
            basis=basis,
            system_type=system_type,
            spin=spin,
            s2_expected=s2_expected,
            s2_actual=s2_actual,
            validation_status=validation_status,
        )
        return json.dumps({
            "overall_score": report.overall_score,
            "convergence_score": report.convergence_score,
            "basis_score": report.basis_score,
            "method_score": report.method_score,
            "spin_score": report.spin_score,
            "reference_score": report.reference_score,
            "breakdown": report.breakdown_text,
            "recommendations": report.recommendations,
            "disclaimer": report.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("score_confidence error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})
