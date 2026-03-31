"""
Drug-likeness rule evaluators.
Pure Python - no external API calls, no dependencies beyond pydantic schemas.
"""

from __future__ import annotations

from app.schemas.molecule_card import DrugLikenessResult


def evaluate_lipinski(
    mw: float | None,
    logp: float | None,
    hbd: int | None,
    hba: int | None,
) -> DrugLikenessResult:
    """Lipinski Rule of Five. Pass = at most 1 violation."""
    violations: list[str] = []
    if mw is not None and mw > 500:
        violations.append(f"MW = {mw:.1f} > 500")
    if logp is not None and logp > 5:
        violations.append(f"logP = {logp:.2f} > 5")
    if hbd is not None and hbd > 5:
        violations.append(f"HBD = {hbd} > 5")
    if hba is not None and hba > 10:
        violations.append(f"HBA = {hba} > 10")
    passed = len(violations) <= 1
    return DrugLikenessResult(
        rule_name="Lipinski (Ro5)",
        passed=passed,
        violations=violations,
        details="Pass" if passed else f"{len(violations)} violations",
    )


def evaluate_veber(
    tpsa: float | None,
    rotatable_bonds: int | None,
) -> DrugLikenessResult:
    """Veber Rules for oral bioavailability."""
    violations: list[str] = []
    if tpsa is not None and tpsa > 140:
        violations.append(f"TPSA = {tpsa:.1f} > 140")
    if rotatable_bonds is not None and rotatable_bonds > 10:
        violations.append(f"RotBonds = {rotatable_bonds} > 10")
    passed = len(violations) == 0
    return DrugLikenessResult(
        rule_name="Veber",
        passed=passed,
        violations=violations,
        details="Pass" if passed else f"{len(violations)} violations",
    )


def evaluate_ghose(
    mw: float | None,
    logp: float | None,
    atom_count: int | None = None,
    molar_refractivity: float | None = None,
) -> DrugLikenessResult:
    """Ghose Filter."""
    violations: list[str] = []
    if mw is not None:
        if mw < 160:
            violations.append(f"MW = {mw:.1f} < 160")
        elif mw > 480:
            violations.append(f"MW = {mw:.1f} > 480")
    if logp is not None:
        if logp < -0.4:
            violations.append(f"logP = {logp:.2f} < -0.4")
        elif logp > 5.6:
            violations.append(f"logP = {logp:.2f} > 5.6")
    if atom_count is not None:
        if atom_count < 20:
            violations.append(f"Atoms = {atom_count} < 20")
        elif atom_count > 70:
            violations.append(f"Atoms = {atom_count} > 70")
    if molar_refractivity is not None:
        if molar_refractivity < 40:
            violations.append(f"MR = {molar_refractivity:.1f} < 40")
        elif molar_refractivity > 130:
            violations.append(f"MR = {molar_refractivity:.1f} > 130")
    passed = len(violations) == 0
    return DrugLikenessResult(
        rule_name="Ghose",
        passed=passed,
        violations=violations,
        details="Pass" if passed else f"{len(violations)} violations",
    )


def evaluate_all(
    mw: float | None = None,
    logp: float | None = None,
    hbd: int | None = None,
    hba: int | None = None,
    tpsa: float | None = None,
    rotatable_bonds: int | None = None,
    atom_count: int | None = None,
    molar_refractivity: float | None = None,
) -> list[DrugLikenessResult]:
    """Evaluate all drug-likeness rules at once."""
    return [
        evaluate_lipinski(mw, logp, hbd, hba),
        evaluate_veber(tpsa, rotatable_bonds),
        evaluate_ghose(mw, logp, atom_count, molar_refractivity),
    ]
