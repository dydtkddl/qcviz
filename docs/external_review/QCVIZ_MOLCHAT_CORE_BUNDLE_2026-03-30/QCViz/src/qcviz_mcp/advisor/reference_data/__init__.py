"""
Reference data loader for QCViz-MCP advisor modules.

Loads curated JSON reference databases for functional recommendations,
NIST bond lengths, GMTKN55 subsets, and DFT accuracy tables.

All data is sourced from peer-reviewed literature with DOI citations.
"""

import json
import logging
import os

__all__ = [
    "load_nist_bonds",
    "load_gmtkn55_subset",
    "load_dft_accuracy_table",
    "load_functional_recommendations",
    "normalize_func_key",
]

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# In-memory cache to avoid repeated file reads
_CACHE = {}


def _load_json(filename):
    """Load a JSON file from the reference_data directory.

    Args:
        filename (str): JSON filename (not full path).

    Returns:
        dict: Parsed JSON content.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    if filename in _CACHE:
        return _CACHE[filename]

    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.isfile(filepath):
        logger.error("Reference data file not found: %s", filepath)
        raise FileNotFoundError(
            "Reference data file not found: %s. "
            "Ensure the qcviz_mcp package was installed correctly "
            "with reference data included." % filepath
        )
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON in reference data file %s: %s",
            filepath, exc,
        )
        raise

    _CACHE[filename] = data
    return data


def normalize_func_key(functional):
    """Normalize functional name to match dft_accuracy_table.json keys.

    Strips dispersion correction suffixes, resolves Minnesota
    functional naming conventions, and uppercases the result.

    Examples:
        'B3LYP-D3(BJ)' -> 'B3LYP'
        'M06-2X-D3(0)' -> 'M062X'
        'wB97X-V'      -> 'WB97X'
        'PBE0-D3(BJ)'  -> 'PBE0'
        'TPSSh-D3(BJ)' -> 'TPSSH'
        'PW6B95-D3(BJ)'-> 'PW6B95'
        'r2SCAN'       -> 'R2SCAN'

    Args:
        functional (str): Raw functional name, possibly with
            dispersion suffixes.

    Returns:
        str: Normalized uppercase key for accuracy table lookup.
    """
    s = functional
    # Strip dispersion suffixes (longest first to avoid partial match)
    for suffix in [
        "-D3(BJ)", "-D3BJ", "-D3(0)", "-D4", "-D3", "-NL",
    ]:
        s = s.replace(suffix, "")
    # Strip -V for wB97X-V (VV10 NLC is set separately in PySCF)
    s_up = s.upper()
    if s_up.startswith("WB97X"):
        s = s.replace("-V", "").replace("-D", "")
    # Handle Minnesota functionals with internal hyphens
    _MINN_MAP = {
        "M06-2X": "M062X",
        "M06-L": "M06L",
        "M05-2X": "M052X",
        "M06-HF": "M06HF",
        "M08-HX": "M08HX",
        "M11-L": "M11L",
    }
    s_upper = s.upper()
    for pattern, replacement in _MINN_MAP.items():
        if s_upper == pattern.upper():
            return replacement
    return s_upper


def load_nist_bonds():
    """Load NIST CCCBDB experimental bond length data.

    Returns:
        dict: Molecule-keyed dictionary of bond length data.
    """
    return _load_json("nist_bonds.json")


def load_gmtkn55_subset():
    """Load GMTKN55 benchmark subset reference energies.

    Returns:
        dict: Reaction-keyed dictionary of reference energies.
    """
    return _load_json("gmtkn55_subset.json")


def load_dft_accuracy_table():
    """Load DFT method accuracy statistics from benchmarks.

    Returns:
        dict: Method-keyed dictionary of accuracy metrics.
    """
    return _load_json("dft_accuracy_table.json")


def load_functional_recommendations():
    """Load functional recommendation decision tree data.

    Returns:
        dict: System-type-keyed recommendation rules.
    """
    return _load_json("functional_recommendations.json")
