"""
GHS safety data fetcher and parser.
Retrieves GHS classification from PubChem PUG-View API.

PUG-View JSON structure (actual):
  Record.Section[0] ("Safety and Hazards")
    .Section[0] ("Hazards Identification")
      .Section[0] ("GHS Classification")
        .Information[] — flat list, each entry is one of:
          - Pictograms  (Markup Type="Icon", Extra="Irritant" etc.)
          - Signal word (Markup Type="Color", Extra="GHSDanger"/"GHSWarning")
          - H-statements (String starts with "H" + 3 digits)
          - P-statements (String starts with "P" + 3 digits, comma-separated)
          - Meta text    (italics, source info — skip)
        Multiple notification sources repeat the same pattern.
"""

from __future__ import annotations

import re
import structlog
import httpx

from app.schemas.molecule_card import GHSSafety

logger = structlog.get_logger(__name__)

_PICTOGRAM_BASE = "https://pubchem.ncbi.nlm.nih.gov/images/ghs"

PICTOGRAM_MAP: dict[str, str] = {
    "Flammable":            "GHS02",
    "Oxidizer":             "GHS03",
    "Compressed Gas":       "GHS04",
    "Corrosive":            "GHS05",
    "Acute Toxic":          "GHS06",
    "Irritant":             "GHS07",
    "Health Hazard":        "GHS08",
    "Environmental Hazard": "GHS09",
    "Explosive":            "GHS01",
}

_H_PATTERN = re.compile(r"^H\d{3}")
_P_PATTERN = re.compile(r"^P\d{3}")


async def fetch_ghs(cid: int, client: httpx.AsyncClient | None = None) -> GHSSafety | None:
    """Fetch GHS classification for a compound from PubChem PUG-View."""
    url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
        f"?heading=GHS+Classification"
    )
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=8.0)
    try:
        resp = await client.get(url, timeout=8.0)
        if resp.status_code != 200:
            logger.warning("ghs_fetch_failed", cid=cid, status=resp.status_code)
            return None
        data = resp.json()
        return _parse_ghs_response(data, cid)
    except httpx.TimeoutException:
        logger.warning("ghs_fetch_timeout", cid=cid)
        return None
    except Exception as e:
        logger.warning("ghs_fetch_error", cid=cid, error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


def _parse_ghs_response(data: dict, cid: int) -> GHSSafety:
    """Parse PUG-View GHS JSON into a GHSSafety object.

    Strategy: walk ALL Information[] entries under GHS Classification
    and classify each by inspecting its Markup and String content.
    """
    pictograms: set[str] = set()
    pictogram_urls: set[str] = set()
    h_statements: list[str] = []
    p_statements: list[str] = []
    signal_word: str | None = None

    try:
        # Navigate: Record > Section[*] > Section[*] > Section[*]
        # until we find TOCHeading == "GHS Classification"
        ghs_section = _find_ghs_section(data.get("Record", {}))
        if ghs_section is None:
            logger.info("ghs_section_not_found", cid=cid)
            return GHSSafety()

        for info in ghs_section.get("Information", []):
            value = info.get("Value", {})
            for swm in value.get("StringWithMarkup", []):
                text = swm.get("String", "").strip()
                markups = swm.get("Markup", [])

                # ── Pictograms: Markup Type="Icon" ──
                for m in markups:
                    if m.get("Type") == "Icon":
                        extra = m.get("Extra", "")
                        url = m.get("URL", "")
                        if extra in PICTOGRAM_MAP:
                            code = PICTOGRAM_MAP[extra]
                            pictograms.add(code)
                            pictogram_urls.add(
                                url if url else f"{_PICTOGRAM_BASE}/{code}.svg"
                            )

                # ── Signal word: short text "Danger" or "Warning" ──
                if text.lower() in ("danger", "warning") and signal_word is None:
                    signal_word = text.capitalize()
                    continue

                # Also detect via Markup Extra
                if signal_word is None:
                    for m in markups:
                        extra = m.get("Extra", "")
                        if extra == "GHSDanger":
                            signal_word = "Danger"
                        elif extra == "GHSWarning":
                            signal_word = "Warning"

                # ── H-statements: "H302: Harmful if swallowed ..." ──
                if _H_PATTERN.match(text):
                    # Truncate the [Warning ...] or [Danger ...] classification suffix
                    clean = _clean_statement(text)
                    if clean and clean not in h_statements:
                        h_statements.append(clean)

                # ── P-statements: comma-separated "P261, P264, ..." ──
                elif _P_PATTERN.match(text):
                    if text not in p_statements:
                        p_statements.append(text)

    except Exception as e:
        logger.warning("ghs_parse_error", cid=cid, error=str(e))

    return GHSSafety(
        signal_word=signal_word,
        pictograms=sorted(pictograms),
        pictogram_urls=sorted(pictogram_urls),
        h_statements=h_statements[:20],
        p_statements=p_statements[:10],
    )


def _find_ghs_section(record: dict) -> dict | None:
    """Recursively find the section with TOCHeading 'GHS Classification'."""
    for section in record.get("Section", []):
        if section.get("TOCHeading") == "GHS Classification":
            return section
        # Recurse into subsections
        result = _find_ghs_section(section)
        if result is not None:
            return result
    return None


def _clean_statement(text: str) -> str:
    """Remove trailing classification bracket from H-statements.

    Example: 'H302: Harmful if swallowed [Warning Acute toxicity, oral]'
          -> 'H302: Harmful if swallowed'
    """
    bracket = text.find(" [")
    if bracket > 0:
        return text[:bracket].strip()
    return text.strip()
