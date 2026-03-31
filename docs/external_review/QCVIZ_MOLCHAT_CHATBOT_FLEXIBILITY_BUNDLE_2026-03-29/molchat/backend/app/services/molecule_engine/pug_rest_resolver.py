"""
PUG REST Resolver — PubChem Name→CID exact-match resolution.

Replaces the old Autocomplete + Jaro-Winkler + Synonym 3-stage validator.
PUG REST /compound/name/{name} does EXACT matching against PubChem's
119M+ compound synonym database. No fuzzy matching, no spell-suggest,
no false positives like "dietary fiber" → "diethyl phthalate".

Response time: typically 100-300ms.
Rate limit: 5 req/s, 400 req/min (shared with all PUG REST).
Cost: $0 (NIH public API).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger(__name__)

_PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=3.0, pool=3.0)


@dataclass
class PugRestResult:
    """Result of PUG REST name resolution."""
    found: bool
    cid: int | None = None
    name: str | None = None          # canonical name from PubChem
    iupac_name: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    canonical_smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    synonyms: list[str] | None = None
    elapsed_ms: float = 0.0
    error: str | None = None

    # Full property dict for downstream use
    properties: dict | None = None


async def resolve_name_to_cid(query: str, timeout: float = 8.0) -> PugRestResult:
    """Resolve a chemical name to PubChem CID via PUG REST exact match.

    This replaces the 3-stage validator (Autocomplete + Jaro-Winkler + Synonym).
    PUG REST name search matches against PubChem's synonym database,
    which includes common names, IUPAC names, trade names, CAS numbers, etc.

    Args:
        query: Chemical name string (e.g., "aspirin", "caffeine", "glucose")
        timeout: HTTP timeout in seconds

    Returns:
        PugRestResult with found=True and full properties, or found=False
    """
    t0 = time.perf_counter()
    query_clean = query.strip()

    if not query_clean or len(query_clean) < 2:
        return PugRestResult(
            found=False,
            error="Query too short",
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Step 1: Name → CID (exact match against synonym DB)
            cid_url = f"{_PUG_REST_BASE}/compound/name/{query_clean}/cids/JSON"
            cid_resp = await client.get(cid_url)

            if cid_resp.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                logger.info(
                    "pug_rest_name_not_found",
                    query=query_clean,
                    status=cid_resp.status_code,
                    elapsed_ms=round(elapsed, 1),
                )
                return PugRestResult(
                    found=False,
                    error=f"Not found in PubChem (HTTP {cid_resp.status_code})",
                    elapsed_ms=elapsed,
                )

            cid_data = cid_resp.json()
            cids = cid_data.get("IdentifierList", {}).get("CID", [])
            if not cids:
                return PugRestResult(
                    found=False,
                    error="No CID returned",
                    elapsed_ms=(time.perf_counter() - t0) * 1000,
                )

            cid = cids[0]

            # Step 2: Fetch properties + synonyms in parallel
            prop_url = (
                f"{_PUG_REST_BASE}/compound/cid/{cid}"
                f"/property/IUPACName,MolecularFormula,MolecularWeight,"
                f"CanonicalSMILES,InChI,InChIKey,XLogP,TPSA,"
                f"HBondDonorCount,HBondAcceptorCount,RotatableBondCount,"
                f"HeavyAtomCount,Complexity,ExactMass,Charge/JSON"
            )
            syn_url = f"{_PUG_REST_BASE}/compound/cid/{cid}/synonyms/JSON"

            prop_resp, syn_resp = await asyncio.gather(
                client.get(prop_url),
                client.get(syn_url),
                return_exceptions=True,
            )

            # Parse properties
            props = {}
            if isinstance(prop_resp, httpx.Response) and prop_resp.status_code == 200:
                props = prop_resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]

            # Parse synonyms
            synonyms = []
            canonical_name = props.get("IUPACName", query_clean)
            if isinstance(syn_resp, httpx.Response) and syn_resp.status_code == 200:
                syn_list = (
                    syn_resp.json()
                    .get("InformationList", {})
                    .get("Information", [{}])[0]
                    .get("Synonym", [])
                )
                synonyms = syn_list[:20]
                if syn_list:
                    canonical_name = syn_list[0]  # First synonym is usually the common name

            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "pug_rest_resolved",
                query=query_clean,
                cid=cid,
                name=canonical_name,
                elapsed_ms=round(elapsed, 1),
            )

            return PugRestResult(
                found=True,
                cid=cid,
                name=canonical_name,
                iupac_name=props.get("IUPACName"),
                molecular_formula=props.get("MolecularFormula"),
                molecular_weight=props.get("MolecularWeight"),
                canonical_smiles=props.get("CanonicalSMILES"),
                inchi=props.get("InChI"),
                inchikey=props.get("InChIKey"),
                synonyms=synonyms,
                elapsed_ms=elapsed,
                properties={
                    "iupac_name": props.get("IUPACName"),
                    "xlogp": props.get("XLogP"),
                    "tpsa": props.get("TPSA"),
                    "hbond_donor": props.get("HBondDonorCount"),
                    "hbond_acceptor": props.get("HBondAcceptorCount"),
                    "rotatable_bonds": props.get("RotatableBondCount"),
                    "heavy_atom_count": props.get("HeavyAtomCount"),
                    "complexity": props.get("Complexity"),
                    "exact_mass": str(props.get("ExactMass", "")),
                    "charge": props.get("Charge"),
                    "synonyms": synonyms,
                },
            )

    except httpx.TimeoutException:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning("pug_rest_timeout", query=query_clean, elapsed_ms=round(elapsed, 1))
        return PugRestResult(found=False, error="PubChem timeout", elapsed_ms=elapsed)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning("pug_rest_error", query=query_clean, error=str(exc), elapsed_ms=round(elapsed, 1))
        return PugRestResult(found=False, error=str(exc), elapsed_ms=elapsed)


# Need asyncio for gather
import asyncio
