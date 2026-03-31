"""
QueryResolver – 3-tier intelligent query resolution pipeline.

Tier 1: Local dictionary (Korean→English, common aliases, 0ms, free)
Tier 2: PubChem Autocomplete API (fuzzy match + spell-suggest, ~100ms, free)
Tier 3: Gemini Flash LLM (complex NL queries, ~500ms, ~$0.001/query)

Usage:
    resolver = QueryResolver()
    result = await resolver.resolve("카페인")
    # result.resolved_query = "caffeine"
    # result.method = "dictionary"
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_PUBCHEM_AUTOCOMPLETE = "https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound"
_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)
_SEMANTIC_QUERY_PATTERNS = [
    re.compile(
        r"\b("
        r"main ingredient|main component|ingredient|ingredients|component|components|"
        r"precursor|precursors|starting material|starting materials|feedstock|"
        r"reagent|reagents|used in|used for|for making|for synthesis of|"
        r"synthesis of|found in|contained in|related to|associated with"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:주물질|주성분|성분|원료|재료|전구체|출발물질|반응물|시약|"
        r"들어가는|들어간|쓰이는|사용되는|만드는 데|만드는데|합성에 쓰이는|관련된)"
    ),
]


@dataclass
class ResolvedQuery:
    """Result of query resolution."""
    original: str
    resolved_query: str
    method: str  # "passthrough" | "dictionary" | "autocomplete" | "llm"
    confidence: float = 1.0
    suggestions: list[str] = field(default_factory=list)
    language: str = "en"


@dataclass
class InterpretedCandidate:
    """Candidate molecule name inferred from a semantic query."""

    name: str
    source: str
    confidence: float = 0.0
    rationale: str = ""


# ═══════════════════════════════════════════
# Tier 1: Local Korean→English + Common Alias Dictionary
# ═══════════════════════════════════════════

# Top ~300 commonly searched molecules in Korean
_KO_EN_DICT: dict[str, str] = {
    # ── 일상 화합물 ──
    "물": "water",
    "소금": "sodium chloride",
    "설탕": "sucrose",
    "포도당": "glucose",
    "과당": "fructose",
    "젖당": "lactose",
    "녹말": "starch",
    "식초": "acetic acid",
    "알코올": "ethanol",
    "에탄올": "ethanol",
    "메탄올": "methanol",
    "아세톤": "acetone",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "자일렌": "xylene",
    "글리세린": "glycerol",
    "글리세롤": "glycerol",
    "요소": "urea",
    "암모니아": "ammonia",
    "이산화탄소": "carbon dioxide",
    "일산화탄소": "carbon monoxide",
    "산소": "oxygen",
    "수소": "hydrogen",
    "질소": "nitrogen",
    "오존": "ozone",
    "과산화수소": "hydrogen peroxide",
    "염산": "hydrochloric acid",
    "황산": "sulfuric acid",
    "질산": "nitric acid",
    "인산": "phosphoric acid",
    "탄산": "carbonic acid",
    "구연산": "citric acid",
    "아세트산": "acetic acid",
    "옥살산": "oxalic acid",
    "포름산": "formic acid",
    "수산화나트륨": "sodium hydroxide",
    "수산화칼륨": "potassium hydroxide",
    "중탄산나트륨": "sodium bicarbonate",
    "베이킹소다": "sodium bicarbonate",
    "탄산칼슘": "calcium carbonate",
    "염화나트륨": "sodium chloride",
    "염화칼슘": "calcium chloride",
    "염화칼륨": "potassium chloride",

    # ── 카페인/식품 관련 ──
    "카페인": "caffeine",
    "테오브로민": "theobromine",
    "타우린": "taurine",
    "니코틴": "nicotine",
    "캡사이신": "capsaicin",
    "멘톨": "menthol",
    "바닐린": "vanillin",
    "리모넨": "limonene",

    # ── 의약품 ──
    "아스피린": "aspirin",
    "타이레놀": "acetaminophen",
    "아세트아미노펜": "acetaminophen",
    "파라세타몰": "paracetamol",
    "이부프로펜": "ibuprofen",
    "나프록센": "naproxen",
    "페니실린": "penicillin",
    "아목시실린": "amoxicillin",
    "메트포르민": "metformin",
    "인슐린": "insulin",
    "모르핀": "morphine",
    "코데인": "codeine",
    "디아제팜": "diazepam",
    "프로작": "fluoxetine",
    "옴니프라졸": "omeprazole",
    "로라타딘": "loratadine",
    "세티리진": "cetirizine",
    "실데나필": "sildenafil",
    "아토르바스타틴": "atorvastatin",
    "메토프롤롤": "metoprolol",
    "암로디핀": "amlodipine",
    "리시노프릴": "lisinopril",
    "와파린": "warfarin",
    "헤파린": "heparin",
    "독소루비신": "doxorubicin",
    "시스플라틴": "cisplatin",
    "타목시펜": "tamoxifen",
    "프레드니솔론": "prednisolone",
    "덱사메타손": "dexamethasone",
    "히드로코르티손": "hydrocortisone",
    "에피네프린": "epinephrine",
    "아드레날린": "adrenaline",
    "노르에피네프린": "norepinephrine",
    "리도카인": "lidocaine",
    "프로포폴": "propofol",
    "케타민": "ketamine",

    # ── 비타민/영양소 ──
    "비타민A": "retinol",
    "비타민B1": "thiamine",
    "비타민B2": "riboflavin",
    "비타민B3": "niacin",
    "비타민B5": "pantothenic acid",
    "비타민B6": "pyridoxine",
    "비타민B7": "biotin",
    "비타민B9": "folic acid",
    "비타민B12": "cyanocobalamin",
    "비타민C": "ascorbic acid",
    "비타민D": "cholecalciferol",
    "비타민E": "tocopherol",
    "비타민K": "phylloquinone",
    "엽산": "folic acid",
    "코엔자임Q10": "coenzyme Q10",
    "오메가3": "eicosapentaenoic acid",
    "루테인": "lutein",
    "콜라겐": "collagen",
    "글루코사민": "glucosamine",
    "콘드로이틴": "chondroitin",
    "크레아틴": "creatine",
    "카르니틴": "carnitine",

    # ── 신경전달물질/호르몬 ──
    "도파민": "dopamine",
    "세로토닌": "serotonin",
    "멜라토닌": "melatonin",
    "아세틸콜린": "acetylcholine",
    "글루탐산": "glutamic acid",
    "가바": "gamma-aminobutyric acid",
    "히스타민": "histamine",
    "옥시토신": "oxytocin",
    "테스토스테론": "testosterone",
    "에스트로겐": "estrogen",
    "프로게스테론": "progesterone",
    "코르티솔": "cortisol",
    "갑상선호르몬": "thyroxine",

    # ── 아미노산 ──
    "글리신": "glycine",
    "알라닌": "alanine",
    "발린": "valine",
    "류신": "leucine",
    "이소류신": "isoleucine",
    "프롤린": "proline",
    "페닐알라닌": "phenylalanine",
    "트립토판": "tryptophan",
    "메티오닌": "methionine",
    "세린": "serine",
    "트레오닌": "threonine",
    "시스테인": "cysteine",
    "타이로신": "tyrosine",
    "아스파르트산": "aspartic acid",
    "글루타민": "glutamine",
    "라이신": "lysine",
    "아르기닌": "arginine",
    "히스티딘": "histidine",

    # ── 핵산/생화학 ──
    "아데닌": "adenine",
    "구아닌": "guanine",
    "시토신": "cytosine",
    "티민": "thymine",
    "우라실": "uracil",
    "아데노신": "adenosine",

    # ── 지질/콜레스테롤 ──
    "콜레스테롤": "cholesterol",
    "트리글리세리드": "triglyceride",
    "스핑고미엘린": "sphingomyelin",

    # ── 산업/환경 화합물 ──
    "폼알데히드": "formaldehyde",
    "포름알데히드": "formaldehyde",
    "클로로포름": "chloroform",
    "에틸렌글리콜": "ethylene glycol",
    "프로필렌글리콜": "propylene glycol",
    "디메틸설폭사이드": "dimethyl sulfoxide",
    "나프탈렌": "naphthalene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "퓨란": "furan",
    "다이옥신": "dioxin",
    "비스페놀A": "bisphenol A",
    "폴리에틸렌": "polyethylene",
    "나일론": "nylon",
    "실리콘": "silicone",
}

# Build a normalized lookup (lowercase, stripped)
_KO_EN_NORMALIZED: dict[str, str] = {
    k.lower().strip(): v for k, v in _KO_EN_DICT.items()
}

# Common English aliases that PubChem might not match directly
_EN_ALIAS: dict[str, str] = {
    "tylenol": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "aleve": "naproxen",
    "benadryl": "diphenhydramine",
    "zyrtec": "cetirizine",
    "claritin": "loratadine",
    "lipitor": "atorvastatin",
    "viagra": "sildenafil",
    "prozac": "fluoxetine",
    "zoloft": "sertraline",
    "xanax": "alprazolam",
    "valium": "diazepam",
    "adderall": "amphetamine",
    "ritalin": "methylphenidate",
    "ambien": "zolpidem",
    "nexium": "esomeprazole",
    "prilosec": "omeprazole",
    "zantac": "ranitidine",
    "vitamin c": "ascorbic acid",
    "vitamin a": "retinol",
    "vitamin d": "cholecalciferol",
    "vitamin e": "tocopherol",
    "vitamin k": "phylloquinone",
    "vitamin b1": "thiamine",
    "vitamin b2": "riboflavin",
    "vitamin b3": "niacin",
    "vitamin b6": "pyridoxine",
    "vitamin b12": "cyanocobalamin",
    "baking soda": "sodium bicarbonate",
    "table salt": "sodium chloride",
    "rubbing alcohol": "isopropanol",
    "bleach": "sodium hypochlorite",
    "lye": "sodium hydroxide",
    "atp": "adenosine triphosphate",
    "adp": "adenosine diphosphate",
    "nad": "nicotinamide adenine dinucleotide",
    "nadh": "nicotinamide adenine dinucleotide",
    "fad": "flavin adenine dinucleotide",
    "coq10": "coenzyme Q10",
    "dha": "docosahexaenoic acid",
    "epa": "eicosapentaenoic acid",
    "msg": "monosodium glutamate",
    "thc": "tetrahydrocannabinol",
    "cbd": "cannabidiol",
    "lsd": "lysergic acid diethylamide",
    "mdma": "methylenedioxymethamphetamine",
    "dmt": "dimethyltryptamine",
    "ddt": "dichlorodiphenyltrichloroethane",
    "pcb": "polychlorinated biphenyl",
    "pvc": "polyvinyl chloride",
    "tnt": "trinitrotoluene",
}

_EN_ALIAS_NORMALIZED: dict[str, str] = {
    k.lower().strip(): v for k, v in _EN_ALIAS.items()
}


def _has_korean(text: str) -> bool:
    """Check if text contains Korean characters."""
    return bool(re.search(r"[\uAC00-\uD7AF\u3131-\u3163\u1100-\u11FF]", text))


def _normalize(text: str) -> str:
    """Normalize query for dictionary lookup."""
    return re.sub(r"\s+", "", text.lower().strip())


class QueryResolver:
    """3-tier intelligent query resolution."""

    def __init__(self, gemini_client=None):
        self._gemini = gemini_client

    async def resolve(self, query: str) -> ResolvedQuery:
        """Resolve a query through the 3-tier pipeline."""
        original = query.strip()
        if not original:
            return ResolvedQuery(original=original, resolved_query=original, method="passthrough")

        # ── Tier 0: Passthrough for CID-like queries ──
        # Pure digits = CID, "CID 1234" pattern, or CAS numbers → skip resolution
        stripped = original.strip()
        if stripped.isdigit():
            # Pure number → likely a CID, pass through directly
            return ResolvedQuery(original=original, resolved_query=stripped, method="passthrough")
        if re.match(r"^(?:CID\s*)?(\d{2,})$", stripped, re.IGNORECASE):
            return ResolvedQuery(original=original, resolved_query=stripped, method="passthrough")
        if re.match(r"^\d{2,7}-\d{2}-\d$", stripped):
            # CAS number pattern → pass through
            return ResolvedQuery(original=original, resolved_query=stripped, method="passthrough")

        # ── Tier 1: Local dictionary ──
        result = self._tier1_dictionary(original)
        if result is not None:
            logger.info("query_resolved_dictionary", original=original, resolved=result.resolved_query)
            return result

        # ── Tier 2: PubChem Autocomplete (fuzzy + spell-suggest) ──
        result = await self._tier2_pug_rest(original)
        if result is not None:
            logger.info("query_resolved_autocomplete", original=original, resolved=result.resolved_query)
            return result

        # ── Tier 3: Gemini LLM (complex/unknown queries) ──
        if _has_korean(original) or not original.isascii():
            result = await self._tier3_llm(original)
            if result is not None:
                logger.info("query_resolved_llm", original=original, resolved=result.resolved_query)
                return result

        # Passthrough – use as-is
        return ResolvedQuery(original=original, resolved_query=original, method="passthrough")

    # ─── Tier 1: Dictionary ───

    def classify_query_mode(self, query: str) -> str:
        cleaned = str(query or "").strip()
        if not cleaned:
            return "empty"
        if any(pattern.search(cleaned) for pattern in _SEMANTIC_QUERY_PATTERNS):
            return "semantic_descriptor"
        return "direct_name"

    async def interpret_candidates(
        self,
        query: str,
        limit: int = 5,
    ) -> tuple[str, str | None, str | None, list[str], list[InterpretedCandidate]]:
        cleaned = str(query or "").strip()
        if not cleaned:
            return ("empty", None, None, [], [])

        mode = self.classify_query_mode(cleaned)
        notes: list[str] = []
        candidates: list[InterpretedCandidate] = []
        seen: set[str] = set()

        def add_candidate(name: str, *, source: str, confidence: float, rationale: str = "") -> None:
            token = str(name or "").strip()
            if not token:
                return
            key = token.lower()
            if key in seen:
                return
            seen.add(key)
            candidates.append(
                InterpretedCandidate(
                    name=token,
                    source=source,
                    confidence=max(0.0, min(float(confidence), 1.0)),
                    rationale=str(rationale or "").strip(),
                )
            )

        resolved = await self.resolve(cleaned)
        normalized_query = resolved.resolved_query if resolved.method != "passthrough" else None
        resolution_method = resolved.method if resolved.method != "passthrough" else None

        if resolved.method != "passthrough" and resolved.resolved_query:
            add_candidate(
                resolved.resolved_query,
                source=resolved.method,
                confidence=resolved.confidence,
                rationale="resolved from alias, translation, or typo correction",
            )
            notes.append(f"query resolved via {resolved.method}")

        if mode == "semantic_descriptor":
            llm_candidates = await self._semantic_llm_candidates(cleaned, limit=max(3, int(limit or 5)))
            for item in llm_candidates:
                add_candidate(
                    item.name,
                    source=item.source,
                    confidence=item.confidence,
                    rationale=item.rationale,
                )
            if llm_candidates:
                notes.append("semantic candidates proposed by Gemini and require PubChem grounding")
        elif cleaned.lower() not in seen:
            add_candidate(
                cleaned,
                source="user_input",
                confidence=0.60,
                rationale="direct user-supplied molecule name",
            )

        return (
            mode,
            normalized_query,
            resolution_method,
            notes,
            candidates[: max(1, int(limit or 5))],
        )

    def _tier1_dictionary(self, query: str) -> ResolvedQuery | None:
        """Fast local dictionary lookup."""
        normalized = _normalize(query)

        # Korean → English
        if _has_korean(query):
            en = _KO_EN_NORMALIZED.get(normalized)
            if en:
                return ResolvedQuery(
                    original=query,
                    resolved_query=en,
                    method="dictionary",
                    confidence=0.95,
                    language="ko",
                )

        # English alias → canonical name
        en = _EN_ALIAS_NORMALIZED.get(normalized)
        if en:
            return ResolvedQuery(
                original=query,
                resolved_query=en,
                method="dictionary",
                confidence=0.95,
                language="en",
            )

        return None

    # ─── Tier 2: PUG REST (primary) + Autocomplete (fallback) ───

    async def _tier2_pug_rest(self, query: str) -> ResolvedQuery | None:
        """PUG REST exact name→CID resolution (primary path).
        
        Unlike Autocomplete which does fuzzy/spell-suggest matching,
        PUG REST /compound/name/ does EXACT matching against PubChem's
        synonym database. This eliminates false positives like
        "dietary fiber" → "diethyl phthalate".
        """
        if _has_korean(query):
            return None  # Korean must go through dictionary or LLM first

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # Direct exact-match lookup
                url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{query}/cids/JSON"
                resp = await client.get(url)
                
                if resp.status_code == 200:
                    cids = resp.json().get("IdentifierList", {}).get("CID", [])
                    if cids:
                        # Found! Query is a valid PubChem name — passthrough
                        logger.info("pug_rest_exact_match", query=query, cid=cids[0])
                        return None  # None = use original query as-is (passthrough)
                
                # Not found via exact match — try Autocomplete as fallback
                # for genuine typos like "aspirn" → "aspirin"
                return await self._tier2_autocomplete_fallback(query)

        except Exception as exc:
            logger.debug("pug_rest_tier2_error", query=query, error=str(exc))
            return await self._tier2_autocomplete_fallback(query)

    async def _tier2_autocomplete_fallback(self, query: str) -> ResolvedQuery | None:
        """Autocomplete fallback — only for genuine typo correction.
        
        Used ONLY when PUG REST exact match fails. Much more conservative
        than before: only accepts autocomplete suggestions that are very
        close to the original query.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_PUBCHEM_AUTOCOMPLETE}/{query}/json",
                    params={"limit": 5},
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                suggestions = data.get("dictionary_terms", {}).get("compound", [])
                if not suggestions:
                    return None

                ql = query.lower().strip()

                # Only accept if a suggestion is very close (likely a typo fix)
                for s in suggestions:
                    sl = s.lower().strip()
                    # Exact match (case difference) → passthrough
                    if sl == ql:
                        return None
                    # Starts with query and is short → likely the base compound
                    if sl.startswith(ql) and len(s) - len(query) <= 2:
                        return None

                # For genuine typo corrections: verify the suggestion works on PUG REST
                best = suggestions[0]
                try:
                    verify_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{best}/cids/JSON"
                    verify_resp = await client.get(verify_url, timeout=3.0)
                    if verify_resp.status_code == 200:
                        cids = verify_resp.json().get("IdentifierList", {}).get("CID", [])
                        if cids:
                            logger.info("autocomplete_typo_correction",
                                       original=query, corrected=best, cid=cids[0])
                            return ResolvedQuery(
                                original=query,
                                resolved_query=best,
                                method="autocomplete",
                                confidence=0.70,
                                suggestions=suggestions[:5],
                                language="en",
                            )
                except Exception:
                    pass

                return None

        except Exception as exc:
            logger.debug("autocomplete_fallback_error", query=query, error=str(exc))
            return None

    # ─── Tier 3: Gemini LLM ───

    async def _tier3_llm(self, query: str) -> ResolvedQuery | None:
        """Use Gemini Flash to translate/resolve complex queries."""
        if self._gemini is None:
            # Try importing
            try:
                from app.services.intelligence.gemini_client import GeminiClient
                self._gemini = GeminiClient()
            except Exception:
                return None

        prompt = f"""You are a chemistry search assistant. The user entered a search query that may be in Korean, 
contain typos, or use informal names. Convert it to the standard English chemical/molecule name 
that would work on PubChem.

Rules:
- Return ONLY the English chemical name, nothing else.
- If it's already a valid English name, return it as-is.
- If it's Korean, translate to the standard English chemical name.
- If it's an abbreviation or brand name, expand to the generic chemical name.
- If you're not sure, return the best guess.

User query: {query}
English chemical name:"""

        try:
            result = await asyncio.wait_for(
                self._gemini.generate(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=100,
                ),
                timeout=5.0,
            )
            text = str(result.get("content") or result.get("text") or "").strip().strip('"').strip("'").strip()
            if text and len(text) < 200 and not _has_korean(text):
                return ResolvedQuery(
                    original=query,
                    resolved_query=text,
                    method="llm",
                    confidence=0.75,
                    language="ko" if _has_korean(query) else "en",
                )
        except Exception as exc:
            logger.debug("llm_resolve_error", query=query, error=str(exc))

        return None

    async def _semantic_llm_candidates(self, query: str, limit: int = 5) -> list[InterpretedCandidate]:
        """Ask Gemini for grounded molecule-name hypotheses for semantic queries."""
        if self._gemini is None:
            try:
                from app.services.intelligence.gemini_client import GeminiClient

                self._gemini = GeminiClient()
            except Exception:
                return []

        prompt = f"""You are a chemistry retrieval assistant.

The user gave a free-form description that may refer to molecules related to a target compound,
a synthesis context, or a materials description. Return up to {max(1, int(limit))} likely
English molecule names that a PubChem exact-name lookup could verify.

Rules:
- Return ONLY JSON.
- Use this schema:
  {{
    "candidates": [
      {{
        "name": "english molecule name",
        "confidence": 0.0,
        "rationale": "short justification"
      }}
    ]
  }}
- Prefer specific molecule names over generic classes.
- Do not return formulas, explanations outside JSON, or markdown.
- If uncertain, include multiple candidates with lower confidence rather than one overconfident answer.

User query: {query}
"""

        try:
            result = await asyncio.wait_for(
                self._gemini.generate(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=500,
                ),
                timeout=8.0,
            )
            content = str(result.get("content", "") or "").strip()
            payload = self._extract_json_dict(content)
            out: list[InterpretedCandidate] = []
            for item in list(payload.get("candidates") or []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                out.append(
                    InterpretedCandidate(
                        name=name,
                        source="semantic_llm",
                        confidence=float(item.get("confidence") or 0.45),
                        rationale=str(item.get("rationale") or "").strip(),
                    )
                )
            return out[: max(1, int(limit or 5))]
        except Exception as exc:
            logger.debug("semantic_llm_candidates_error", query=query, error=str(exc))
            return []

    def _extract_json_dict(self, text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
