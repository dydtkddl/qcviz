"""
Base class and data structures for Layer-0 search providers.

Every provider must implement ``search()`` and ``get_by_identifier()``.
Providers are stateless — HTTP clients are created per-call or
injected from a shared pool.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SearchType(str, Enum):
    """Type of identifier used for searching."""

    NAME = "name"
    SMILES = "smiles"
    INCHIKEY = "inchikey"
    CID = "cid"
    FORMULA = "formula"
    CAS = "cas"


@dataclass
class RawSearchResult:
    """Single molecule result returned by a search provider."""

    # Identity
    name: str = ""
    canonical_smiles: str = ""
    inchi: str | None = None
    inchikey: str | None = None
    cid: int | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None

    # Provider metadata
    source: str = ""
    source_id: str = ""
    source_url: str = ""
    confidence: float = 1.0  # 0.0–1.0

    # Extended properties (provider-specific)
    properties: dict[str, Any] = field(default_factory=dict)

    # Raw 3D structure if available from provider
    structure_3d: str | None = None  # SDF block
    structure_format: str = "sdf"

    def dedup_key(self) -> str:
        """Key for deduplication across providers.

        Priority: InChIKey > CID > canonical SMILES > name.
        """
        if self.inchikey:
            return f"inchikey:{self.inchikey}"
        if self.cid:
            return f"cid:{self.cid}"
        if self.canonical_smiles:
            return f"smiles:{self.canonical_smiles}"
        return f"name:{self.name.lower().strip()}"


@dataclass
class AggregatedSearchResult:
    """Aggregated results from all providers."""

    results: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    sources_queried: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def classify_query(query: str) -> SearchType:
    """Heuristic classification of a free-form search query.

    Rules (applied in order):
      1. Pure digits → CID
      2. 14-char InChIKey pattern (XXXXXXXXXXXXXX-XXXXXXXXXX-X) → INCHIKEY
      3. Starts with "InChI=" → treated as SMILES (InChI string)
      4. Molecular formula (e.g. C6H12O6) → FORMULA
      5. CAS pattern (digits-digits-digit) → CAS
      6. Looks like SMILES (has brackets, =, #, @, ring digits after atoms) → SMILES
      7. Fallback → NAME
    """
    q = query.strip()

    # CID – pure digits
    if q.isdigit():
        return SearchType.CID

    # InChIKey (XXXXXXXXXXXXXX-XXXXXXXXXX-X, 27 chars)
    if len(q) == 27 and q.count("-") == 2:
        parts = q.split("-")
        if len(parts[0]) == 14 and len(parts[1]) == 10 and len(parts[2]) == 1:
            if all(c.isalpha() and c.isupper() for part in parts for c in part):
                return SearchType.INCHIKEY

    # InChI string
    if q.startswith("InChI="):
        return SearchType.SMILES  # PubChem accepts InChI via smiles endpoint

    # Molecular formula (e.g. C6H12O6, H2O, NaCl – letters+digits, no spaces)
    import re
    formula_pattern = re.compile(r"^[A-Z][a-z]?(\d+)?([A-Z][a-z]?(\d+)?)*$")
    if formula_pattern.match(q) and any(c.isdigit() for c in q):
        return SearchType.FORMULA

    # CAS number (e.g. 50-78-2)
    cas_pattern = re.compile(r"^\d{2,7}-\d{2}-\d$")
    if cas_pattern.match(q):
        return SearchType.CAS

    # SMILES detection – must contain SMILES-specific characters
    # Key: hyphens alone do NOT make it SMILES (e.g. "3-Hydroxypropionic-acid" is a name)
    # Also, if query contains spaces it's almost certainly a name, not SMILES
    smiles_strong_chars = set("[]=#@/\\")
    has_strong_smiles = any(c in smiles_strong_chars for c in q)

    # Parentheses in chemical context (not just at word boundaries)
    has_smiles_parens = "(" in q and ")" in q and " " not in q

    # Ring closure digits attached to atoms (e.g. c1ccccc1, C1CC1)
    ring_pattern = re.compile(r"[A-Za-z][0-9]")
    has_ring_closure = bool(ring_pattern.search(q)) and " " not in q

    # If it has spaces, it's almost certainly a name
    if " " in q:
        return SearchType.NAME

    # If it has strong SMILES characters, it's SMILES
    if has_strong_smiles:
        return SearchType.SMILES

    # If it has parentheses (like C(=O)O) without spaces, likely SMILES
    if has_smiles_parens:
        return SearchType.SMILES

    # If it looks like atom-digit patterns (ring closures) and is short-ish
    if has_ring_closure and len(q) < 200:
        # But check: could it be a name like "vitamin-B12"?
        # Names typically have many lowercase letters in a row
        long_alpha_runs = re.findall(r"[a-zA-Z]{4,}", q)
        if long_alpha_runs:
            # Likely a chemical name with numbers (e.g. "3-methylbutan-1-ol")
            return SearchType.NAME
        return SearchType.SMILES

    # Aromatic SMILES – all lowercase letters with digits, no spaces
    # e.g. c1ccccc1, c1cc(O)ccc1, n1cccc1
    if " " not in q and re.fullmatch(r"[a-z0-9()]+", q) and any(c in "cnos" for c in q):
        # Check it's not a real word (real words have vowels + consonants in natural patterns)
        # Aromatic SMILES uses only c, n, o, s as "atoms"
        aromatic_atoms = set("cnos")
        non_aromatic_alpha = set(c for c in q if c.isalpha() and c not in aromatic_atoms)
        if not non_aromatic_alpha:
            return SearchType.SMILES

    # Default: treat as name
    return SearchType.NAME

class BaseSearchProvider(abc.ABC):
    """Abstract base class for all L0 search providers."""

    @property
    @abc.abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this provider (e.g., 'pubchem')."""

    @property
    def priority(self) -> int:
        """Lower = higher priority. Used for result ranking."""
        return 50

    @property
    def timeout(self) -> float:
        """Per-provider timeout in seconds."""
        return 15.0

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        search_type: SearchType,
        limit: int = 10,
    ) -> list[RawSearchResult]:
        """Search for molecules matching the query.

        Must return a list of ``RawSearchResult`` (may be empty, never raises).
        """

    @abc.abstractmethod
    async def get_by_identifier(
        self, identifier: str, id_type: SearchType
    ) -> RawSearchResult | None:
        """Fetch a single molecule by exact identifier.

        Returns None if not found.
        """

    async def health_check(self) -> bool:
        """Return True if the provider's upstream is reachable."""
        return True