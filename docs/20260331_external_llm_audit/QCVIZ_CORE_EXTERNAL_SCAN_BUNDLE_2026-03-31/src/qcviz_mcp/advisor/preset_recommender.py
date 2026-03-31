"""
Computation Preset Recommender (F1).

Analyzes molecular structure and recommends optimal DFT calculation
settings with literature-backed justifications.

Based on:
  - Bursch et al. Angew. Chem. Int. Ed. 2022, 61, e202205735
  - Goerigk et al. Phys. Chem. Chem. Phys. 2017, 19, 32184
  - Mardirossian & Head-Gordon, Mol. Phys. 2017, 115, 2315

Version: 1.1.0
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import load_functional_recommendations

__all__ = ["PresetRecommender", "PresetRecommendation"]

logger = logging.getLogger(__name__)

# Periodic table classification
_ORGANIC_ELEMENTS = frozenset([
    "H", "C", "N", "O", "F", "Cl", "Br", "S", "P", "Si", "B", "I",
])
_3D_TM = frozenset([
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
])
_4D_TM = frozenset([
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
])
# FIXED #1: La is 5d^1, stays in 5D_TM. Lanthanides (Ce-Lu) separated.
_5D_TM = frozenset([
    "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
])
_LANTHANIDE = frozenset([
    "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
])
_MAIN_GROUP_METALS = frozenset([
    "Li", "Na", "K", "Rb", "Cs",
    "Be", "Mg", "Ca", "Sr", "Ba",
    "Al", "Ga", "In", "Tl",
    "Ge", "Sn", "Pb",
    "As", "Sb", "Bi",
    "Se", "Te",
])
_NOBLE_GASES = frozenset(["He", "Ne", "Ar", "Kr", "Xe", "Rn"])

# All known elements for validation
_ALL_ELEMENTS = (
    _ORGANIC_ELEMENTS | _3D_TM | _4D_TM | _5D_TM
    | _LANTHANIDE | _MAIN_GROUP_METALS | _NOBLE_GASES
)

# Purpose enumeration
VALID_PURPOSES = frozenset([
    "geometry_opt",
    "single_point",
    "bonding_analysis",
    "reaction_energy",
    "spectroscopy",
    "esp_mapping",
])


def _functional_to_pyscf_xc(functional):
    """Normalize advisor functional labels to PySCF xc strings."""
    xc = str(functional or "").strip()
    if len(xc) > 1 and xc[0].upper() in {"U", "R"} and xc[1].isalpha():
        xc = xc[1:]
    for suffix in ("-D3(BJ)", "-D3BJ", "-D3(0)", "-D4", "-D3", "-NL"):
        xc = xc.replace(suffix, "")
    xc_map = {
        "B3LYP": "b3lyp",
        "PBE0": "pbe0",
        "TPSSh": "tpssh",
        "PBE": "pbe",
        "TPSS": "tpss",
        "r2SCAN": "r2scan",
        "M06-2X": "m062x",
        "M062X": "m062x",
        "wB97X-D": "wb97x-d",
        "wB97X-D3": "wb97x-d",
        "wB97X-V": "wb97x-v",
        "PW6B95": "pw6b95",
    }
    return xc_map.get(xc, xc.lower())


@dataclass
class PresetRecommendation:
    """Result of a computation preset recommendation."""

    functional: str
    basis: str
    dispersion: Optional[str]
    spin_treatment: str
    relativistic: bool
    convergence: dict
    alternatives: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    references: list = field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.0
    pyscf_settings: dict = field(default_factory=dict)


class PresetRecommender:
    """Recommends DFT computation presets based on molecular analysis.

    Analyzes a molecular structure to determine the optimal functional,
    basis set, dispersion correction, and other settings for a given
    computational purpose.

    Uses a rule-based decision tree backed by literature benchmarks
    (GMTKN55, Bursch et al. best-practice protocols).
    """

    def __init__(self):
        """Initialize the recommender with reference data."""
        self._recommendations = load_functional_recommendations()

    def recommend(
        self,
        atom_spec,
        purpose="geometry_opt",
        charge=0,
        spin=0,
    ):
        """Generate a computation preset recommendation.

        Args:
            atom_spec (str): Molecular structure in XYZ format
                (lines of 'Element x y z'). May include a 2-line
                header (atom count + comment).
            purpose (str): Calculation purpose. One of:
                geometry_opt, single_point, bonding_analysis,
                reaction_energy, spectroscopy, esp_mapping.
            charge (int): Molecular charge.
            spin (int): Spin multiplicity 2S (0=singlet, 1=doublet).

        Returns:
            PresetRecommendation: Complete recommendation with
                rationale and references.

        Raises:
            ValueError: If purpose is invalid or atom_spec is
                unparseable.
        """
        if purpose not in VALID_PURPOSES:
            raise ValueError(
                "Invalid purpose '%s'. Must be one of: %s"
                % (purpose, ", ".join(sorted(VALID_PURPOSES)))
            )

        elements = self._parse_elements(atom_spec)
        if not elements:
            raise ValueError(
                "Could not parse any atoms from atom_spec."
            )

        n_atoms = len(elements)
        unique_elements = set(elements)
        system_type = self._classify_system(
            unique_elements, n_atoms, charge, spin
        )

        rec = self._build_recommendation(
            system_type, purpose, unique_elements, n_atoms,
            charge, spin,
        )

        logger.info(
            "Recommendation for %s (%s, %d atoms): %s/%s",
            system_type, purpose, n_atoms,
            rec.functional, rec.basis,
        )

        return rec

    def _parse_elements(self, atom_spec):
        """Extract element symbols from XYZ-format atom specification.

        Handles standard XYZ format with optional 2-line header
        (atom count line + comment line).

        Args:
            atom_spec (str): XYZ format string.

        Returns:
            list: List of element symbol strings.
        """
        # FIXED #13: Robust header parsing
        elements = []
        lines = atom_spec.strip().split("\n")

        # Detect and skip XYZ header (line 1: integer atom count,
        # line 2: comment)
        start_idx = 0
        if lines and lines[0].strip().isdigit():
            start_idx = 1
            # Skip comment line too if present
            if len(lines) > 1:
                # Line 2 is always comment in standard XYZ
                start_idx = 2

        for line in lines[start_idx:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                sym = parts[0].strip()
                # Validate: first char must be alphabetic
                if not sym[0].isalpha():
                    continue
                # Capitalize properly: "FE" -> "Fe", "cl" -> "Cl"
                sym = sym[0].upper() + sym[1:].lower()
                # Validate against known elements
                if sym not in _ALL_ELEMENTS:
                    continue
                elements.append(sym)
        return elements

    def _classify_system(self, unique_elements, n_atoms, charge, spin):
        """Classify the molecular system type.

        Priority order: lanthanide > heavy_tm > 3d_tm > radical
        > charged_organic > main_group_metal > organic.
        Note: compound classifications (e.g., lanthanide + radical)
        return the highest-priority match. Radical-specific advice
        (UKS, spin contamination) is still appended as warnings
        in _build_recommendation regardless of system_type.

        Args:
            unique_elements (set): Set of unique element symbols.
            n_atoms (int): Total number of atoms.
            charge (int): Molecular charge.
            spin (int): Spin state (2S).

        Returns:
            str: System type classification. One of:
                organic_small, organic_large, 3d_tm, heavy_tm,
                lanthanide, radical, charged_organic,
                main_group_metal.
        """
        has_3d = bool(unique_elements & _3D_TM)
        has_4d = bool(unique_elements & _4D_TM)
        has_5d = bool(unique_elements & _5D_TM)
        has_lanthanide = bool(unique_elements & _LANTHANIDE)
        has_main_metal = bool(unique_elements & _MAIN_GROUP_METALS)
        is_organic = unique_elements.issubset(_ORGANIC_ELEMENTS)
        is_radical = spin > 0
        is_charged = charge != 0

        # FIXED #1: Lanthanide branch
        if has_lanthanide:
            return "lanthanide"
        if has_5d or has_4d:
            return "heavy_tm"
        if has_3d:
            return "3d_tm"
        if is_radical:
            return "radical"
        if is_charged and is_organic:
            return "charged_organic"
        if has_main_metal:
            return "main_group_metal"
        if is_organic and n_atoms <= 50:
            return "organic_small"
        if is_organic and n_atoms > 50:
            return "organic_large"
        return "organic_small"

    def _build_recommendation(
        self, system_type, purpose, unique_elements,
        n_atoms, charge, spin,
    ):
        """Build a complete recommendation from rules and reference data.

        Args:
            system_type (str): Classified system type.
            purpose (str): Calculation purpose.
            unique_elements (set): Unique element set.
            n_atoms (int): Number of atoms.
            charge (int): Charge.
            spin (int): Spin.

        Returns:
            PresetRecommendation: Complete recommendation.
        """
        # Look up recommendation rules
        rules = self._recommendations.get(system_type, {})
        purpose_rules = rules.get(purpose, rules.get("default", {}))

        functional = purpose_rules.get("functional", "B3LYP")
        basis = purpose_rules.get("basis", "def2-SVP")
        dispersion = purpose_rules.get("dispersion", "d3bj")
        refs = purpose_rules.get("references", [])
        rationale_text = purpose_rules.get("rationale", "")
        confidence = purpose_rules.get("confidence", 0.7)

        # Determine spin treatment
        if spin > 0:
            spin_treatment = "UKS"
        else:
            spin_treatment = "RKS"

        # Determine if relativistic treatment needed
        relativistic = bool(
            unique_elements & (_4D_TM | _5D_TM | _LANTHANIDE)
        )

        # Build convergence criteria
        if purpose == "geometry_opt":
            convergence = {
                "energy": 1e-8,
                "gradient_rms": 3e-4,
                "gradient_max": 4.5e-4,
                "displacement_rms": 1.2e-3,
                "displacement_max": 1.8e-3,
            }
        else:
            convergence = {
                "energy": 1e-9,
            }

        # Build warnings
        warnings = []
        if spin > 0:
            warnings.append(
                "Open-shell system detected. Check spin contamination "
                "(<S^2> value) in the output. Expected <S^2> = %.2f; "
                "deviations > 10%% suggest unreliable results."
                % (spin / 2.0 * (spin / 2.0 + 1))
            )
        if system_type == "3d_tm":
            warnings.append(
                "3d transition metal detected. B3LYP may overestimate "
                "spin-state energy splittings. Consider TPSSh as an "
                "alternative. Multiple spin states should be checked."
            )
        if system_type == "heavy_tm":
            warnings.append(
                "Heavy element detected. Scalar relativistic effects are "
                "included via effective core potentials in the def2 basis "
                "sets for elements beyond Kr."
            )
        if system_type == "lanthanide":
            warnings.append(
                "Lanthanide (4f) element detected. DFT results for "
                "lanthanides should be treated with caution. "
                "Multiconfigurational effects may be important. "
                "Scalar relativistic ECPs are included in def2 basis sets."
            )
        if n_atoms > 100:
            warnings.append(
                "Large system (%d atoms). Consider using a GGA functional "
                "(e.g., r2SCAN-3c) for geometry optimization to reduce "
                "computational cost." % n_atoms
            )
            if "hybrid" in functional.lower() or functional in (
                "B3LYP", "PBE0", "TPSSh"
            ):
                confidence *= 0.8  # Lower confidence for large + hybrid

        # Build alternatives
        alt_rules = rules.get("alternatives", [])
        alternatives = []
        for alt in alt_rules:
            alternatives.append((
                alt.get("functional", ""),
                alt.get("basis", ""),
                alt.get("rationale", ""),
            ))

        # Build PySCF settings
        pyscf_xc_lower = _functional_to_pyscf_xc(functional)

        pyscf_settings = {
            "xc": pyscf_xc_lower,
            "basis": basis.lower(),
            "charge": charge,
            "spin": spin,
            "max_cycle": 200,
            "conv_tol": convergence.get("energy", 1e-9),
        }

        rec = PresetRecommendation(
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            spin_treatment=spin_treatment,
            relativistic=relativistic,
            convergence=convergence,
            alternatives=alternatives,
            warnings=warnings,
            references=refs,
            rationale=rationale_text,
            confidence=round(confidence, 2),
            pyscf_settings=pyscf_settings,
        )

        return rec
