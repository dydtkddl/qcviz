from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

KO_TO_EN: Dict[str, str] = {
    "물": "water",
    "에탄올": "ethanol",
    "메탄올": "methanol",
    "메탄": "methane",
    "에탄": "ethane",
    "메틸아민": "methylamine",
    "메탄아민": "methylamine",
    "에틸아민": "ethylamine",
    "에탄아민": "ethylamine",
    "디메틸아민": "dimethylamine",
    "트리메틸아민": "trimethylamine",
    "프로필아민": "propylamine",
    "부틸아민": "butylamine",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "아세톤": "acetone",
    "암모니아": "ammonia",
    "이산화탄소": "carbon dioxide",
    "일산화탄소": "carbon monoxide",
    "포름알데히드": "formaldehyde",
    "아세트산": "acetic acid",
    "아세트알데하이드": "acetaldehyde",
    "글리신": "glycine",
    "요소": "urea",
    "피리딘": "pyridine",
    "페놀": "phenol",
    "아닐린": "aniline",
    "아스피린": "aspirin",
    "카페인": "caffeine",
    "포도당": "glucose",
    "과산화수소": "hydrogen peroxide",
    "황산": "sulfuric acid",
    "염산": "hydrochloric acid",
    "수산화나트륨": "sodium hydroxide",
    "아세틸렌": "acetylene",
    "프로판": "propane",
    "부탄": "butane",
    "나프탈렌": "naphthalene",
    "글루탐산": "glutamic acid",
    "세로토닌": "serotonin",
    "부타다이엔": "butadiene",
    "뷰타다이엔": "butadiene",
    "부타 다이엔": "butadiene",
    "뷰타 다이엔": "butadiene",
    "1,3-뷰타다이엔": "1,3-butadiene",
    "1,3-뷰타 다이엔": "1,3-butadiene",
}


ABBREVIATION_MAP: Dict[str, str] = {
    "tfsi": "bis(trifluoromethanesulfonyl)azanide",
    "tfsi-": "bis(trifluoromethanesulfonyl)azanide",
    "ntf2": "bis(trifluoromethanesulfonyl)azanide",
    "ntf2-": "bis(trifluoromethanesulfonyl)azanide",
    "bistriflimide": "bis(trifluoromethanesulfonyl)azanide",
    "fsi": "bis(fluorosulfonyl)azanide",
    "fsi-": "bis(fluorosulfonyl)azanide",
    "hntf2": "bis(trifluoromethanesulfonyl)imide",
    "tf2nh": "bis(trifluoromethanesulfonyl)imide",
    "pf6": "hexafluorophosphate",
    "pf6-": "hexafluorophosphate",
    "bf4": "tetrafluoroborate",
    "bf4-": "tetrafluoroborate",
    "ec": "ethylene carbonate",
    "pc": "propylene carbonate",
    "dmc": "dimethyl carbonate",
    "emc": "ethyl methyl carbonate",
    "dec": "diethyl carbonate",
    "dme": "1,2-dimethoxyethane",
    "fec": "fluoroethylene carbonate",
    "vc": "vinylene carbonate",
    "emim": "1-ethyl-3-methylimidazolium",
    "emim+": "1-ethyl-3-methylimidazolium",
    "bmim": "1-butyl-3-methylimidazolium",
    "bmim+": "1-butyl-3-methylimidazolium",
    "thf": "tetrahydrofuran",
    "dmf": "dimethylformamide",
    "dmso": "dimethyl sulfoxide",
    "nmp": "n-methyl-2-pyrrolidone",
    "acn": "acetonitrile",
    "meoh": "methanol",
    "etoh": "ethanol",
    "dcm": "dichloromethane",
}

_TASK_HINT_PATTERNS = [
    (re.compile(r"\b(homo|lumo|orbital|mo)\b|오비탈", re.IGNORECASE), "orbital_preview"),
    (re.compile(r"\b(esp|electrostatic)\b|전위|정전기", re.IGNORECASE), "esp_map"),
    (re.compile(r"\b(charge|charges|mulliken)\b|전하", re.IGNORECASE), "partial_charges"),
    (re.compile(r"\b(opt|optimize|optimization)\b|최적화", re.IGNORECASE), "geometry_optimization"),
    (re.compile(r"\b(geometry|bond|angle|dihedral)\b|구조|결합", re.IGNORECASE), "geometry_analysis"),
    (re.compile(r"\b(energy|single point|singlepoint)\b|에너지", re.IGNORECASE), "single_point"),
]

_KOREAN_TASK_TOKENS = [
    "오비탈", "계산", "최적화", "전하", "분석", "에너지", "구조", "보여줘", "해줘", "맵", "전위",
]

_EXPLICIT_TEXT_REPLACEMENTS = {
    "무ㄹ": "물",
    "ㅁㅜㄹ": "물",
    "머ㄹ": "물",
    "오비탈계산": "오비탈 계산",
    "아세톤최적화": "아세톤 최적화",
}

_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")

_TASK_NOISE_WORDS = [
    "오비탈", "esp", "맵", "map", "전하", "구조", "계산", "analysis", "analyze",
    "show", "render", "visualize", "optimize", "optimization", "energy", "homo", "lumo",
    "이온쌍", "이온", "보여줘", "해줘", "그려줘", "분석",
    "궁금", "알려줘", "뭐야", "질문", "curious", "question",
    "ㄱㄱ", "ㄱ", "가자", "go", "gogo",
]

_INVALID_STRUCTURE_WORDS = set(_TASK_NOISE_WORDS + ["of", "for", "about", "on", "the"])
_PLAIN_MOLECULE_STOPWORDS = _INVALID_STRUCTURE_WORDS | {
    "show", "render", "visualize", "display", "calculate", "compute", "analysis",
    "please", "help", "what", "which", "why", "how", "tell", "explain",
}
_DEICTIC_FOLLOW_UP_TERMS = {
    "그거", "이거", "저거",
    "그걸", "이걸", "저걸",
    "그 분자", "이 분자", "저 분자",
    "그 구조", "이 구조", "저 구조",
    "방금 거", "아까 거",
}
_PLAIN_MOLECULE_STOPWORDS |= _DEICTIC_FOLLOW_UP_TERMS

_STRUCTURE_EDGE_NOISE_WORDS = {
    "show", "render", "visualize", "display", "calculate", "compute", "analyze",
    "analysis", "optimize", "optimization", "map", "esp", "homo", "lumo",
    "orbital", "structure", "molecule", "system", "for", "of", "on", "about",
    "the", "using", "with", "please", "and", "or", "in", "at", "to",
    "보여줘", "해줘", "그려줘", "계산", "분석", "구조", "전하", "오비탈", "전위", "맵",
    "궁금", "알려줘", "뭐야", "질문", "ㄱㄱ", "ㄱ", "가자", "go", "gogo",
    "의", "를", "을", "이", "가", "은", "는", "도",
}

_STRUCTURE_EDGE_NOISE_WORDS.update(_DEICTIC_FOLLOW_UP_TERMS)
_KOREAN_DEICTIC_FOLLOW_UP_TERMS = {
    "\uadf8\uac70",
    "\uc774\uac70",
    "\uc800\uac70",
    "\uadf8\uac78",
    "\uc774\uac78",
    "\uc800\uac78",
    "\uadf8 \ubd84\uc790",
    "\uc774 \ubd84\uc790",
    "\uc800 \ubd84\uc790",
    "\uadf8 \uad6c\uc870",
    "\uc774 \uad6c\uc870",
    "\uc800 \uad6c\uc870",
    "\ubc29\uae08 \uac70",
    "\uc544\uae4c \uac70",
    "\uc774\ubc88\uc5d4",
    "\uc774\ubc88\uc5d0\ub294",
    "\u3147\u3147",
    "\u3131\u3131",
}
_PLAIN_MOLECULE_STOPWORDS |= _KOREAN_DEICTIC_FOLLOW_UP_TERMS
_STRUCTURE_EDGE_NOISE_WORDS.update(_KOREAN_DEICTIC_FOLLOW_UP_TERMS)

_FORMULA_LIKE_RE = re.compile(r"^(?:[A-Z][a-z]?\d*){2,}(?:[+-]\d*|\d*[+-])?$")
_STRUCTURAL_FORMULA_RE = re.compile(
    r"^(?:[A-Z][a-z]?\d*|[=#\-]){3,}[A-Za-z0-9=#\-]*$"
)
_CONDENSED_STRUCTURAL_FORMULA_RE = re.compile(
    r"^(?:[A-Z][a-z]?\d*|\(|\)|[=#\-])+$"
)
_FORMULA_TOKEN_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9]*(?:[=#\-][A-Za-z0-9]+)+\b|\b(?:[A-Z][a-z]?\d*){2,}(?:[+-]\d*|\d*[+-])?\b"
)
_PAREN_MIXED_RE = re.compile(r"(?P<left>[^()]{1,120}?)\s*\((?P<right>[^()]{1,120})\)")
_LIST_MIXED_SPLIT_RE = re.compile(r"\s*(?:/|,|;)\s*")
_ENUMERATION_MARKER_RE = re.compile(r"(?<![A-Za-z0-9가-힣])\(\s*(?:[A-Za-z]|\d+)\s*\)\s*")
_SYSTEMATIC_NAME_SYNONYMS: Dict[str, List[str]] = {
    "acetic acid": ["ethanoic acid"],
    "methylamine": ["methanamine"],
    "1,3-butadiene": ["buta-1,3-diene"],
}
_FOLLOW_UP_ONLY_RE = re.compile(
    r"\b(esp|electrostatic|lumo|homo|orbital|charge|charges|optimize|optimization|basis)\b|"
    r"전하|오비탈|최적화|기저|같은 구조|이걸|그것도|그것도 해줘|도 보여줘|도 그려줘|더 키워",
    re.IGNORECASE,
)
_FOLLOW_UP_REUSE_LAST_JOB_RE = re.compile(
    r"(계산 끝난 뒤|계산 후|결과 나온 뒤|after\s+(the\s+)?calculation|after\s+that)",
    re.IGNORECASE,
)
_FOLLOW_UP_BASIS_RE = re.compile(
    r"\b(sto-?3g|3-21g|6-31g[*]{0,2}|6-311g[*]{0,2}|def2-?svp|def2-?tzvp|cc-pv[dt]z|aug-cc-pv[dt]z)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_METHOD_TOKEN_RE = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|bp86|blyp|mp2|ccsd|tpssh|scan|r2scan)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_ESP_RE = re.compile(
    r"\b(esp|electrostatic)\b|전위|정전기",
    re.IGNORECASE,
)
_FOLLOW_UP_CHARGE_RE = re.compile(
    r"\b(charge|charges|mulliken)\b|차지|전하",
    re.IGNORECASE,
)
_FOLLOW_UP_OPT_RE = re.compile(
    r"\b(opt|optimize|optimization)\b|최적화",
    re.IGNORECASE,
)
_FOLLOW_UP_ORBITAL_RE = re.compile(
    r"\b(homo|lumo|orbital|mo)\b|궤도",
    re.IGNORECASE,
)
_FOLLOW_UP_SAME_STRUCTURE_RE = re.compile(
    r"(?:"
    r"same structure|same molecule|this one|that one|it too|this too|that too|"
    r"그거|이거|저거|"
    r"그걸|이걸|저걸|"
    r"그 분자|이 분자|저 분자|"
    r"그 구조|이 구조|저 구조|"
    r"방금 거|아까 거|"
    r"이번엔|이번에는|"
    r"동일 구조|같은 구조"
    r")",
    re.IGNORECASE,
)
_FOLLOW_UP_PLACEHOLDER_RE = re.compile(
    r"^(?:"
    r"this|that|it|it too|this too|that too|same structure|same molecule|"
    r"basis|esp|homo|lumo|orbital|charge|charges|optimize|optimization|"
    r"그거|이거|저거|"
    r"그걸|이걸|저걸|"
    r"그 분자|이 분자|저 분자|"
    r"그 구조|이 구조|저 구조|"
    r"방금 거|아까 거|"
    r"이번엔|이번에는|"
    r"동일 구조|같은 구조"
    r")$",
    re.IGNORECASE,
)
_FOLLOW_UP_CONTINUATION_CUE_RE = re.compile(
    r"(?:\b(?:also|too|same structure|same molecule|this|that)\b|"
    r"\b(?:it|this|that)\s+too\b|"
    r"그거|이거|저거|"
    r"그걸|이걸|저걸|"
    r"그 분자|이 분자|저 분자|"
    r"그 구조|이 구조|저 구조|"
    r"방금 거|아까 거|"
    r"이번엔|이번에는|"
    r"동일 구조|같은 구조|"
    r"ㅇㅇ|ㄱㄱ|"
    r"(?:\bgo(?:\s+go)?\b)|also|too|again|more|next"
    r")",
    re.IGNORECASE,
)
_FOLLOW_UP_QUERY_CUE_RE = re.compile(
    r"(?:\b(?:also|too|again|more|next)\b|"
    r"궁금|더|추가|다시|"
    r"방금 거|아까 거|"
    r"이번엔|이번에는|"
    r"ㅇㅇ|ㄱㄱ|"
    r"(?:\bgo(?:\s+go)?\b))",
    re.IGNORECASE,
)
_FOLLOW_UP_ANALYSIS_SUFFIX_RE = re.compile(
    r"(?:homo|lumo|esp|orbital|charge|charges|mulliken|opt|optimize|optimization|basis)\s*도(?:\b|$)",
    re.IGNORECASE,
)
_BATCH_ALL_MENTIONED_RE = re.compile(
    r"(전부\s*다|싹다|모두|여기에\s*나오는\s*물질들|all of them|all mentioned molecules|all mentioned|all of those)",
    re.IGNORECASE,
)
_BATCH_FIRST_TWO_RE = re.compile(r"(둘 다|both of them|both)", re.IGNORECASE)
_BATCH_FIRST_ONLY_RE = re.compile(r"(첫\s*번째만|첫번째만|first one only|only the first)", re.IGNORECASE)
_ANALYSIS_STRUCTURE_RE = re.compile(r"\b(structure|structures?)\b|구조", re.IGNORECASE)
_ANALYSIS_HOMO_RE = re.compile(r"\bhomo\b", re.IGNORECASE)
_ANALYSIS_LUMO_RE = re.compile(r"\blumo\b", re.IGNORECASE)
_ANALYSIS_ESP_RE = re.compile(r"esp|electrostatic|전위|정전기", re.IGNORECASE)


_SEMANTIC_DESCRIPTOR_PATTERNS = [
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
_SEMANTIC_GENERIC_NOUN_RE = re.compile(
    r"\b(material|substance|molecule|compound|chemical)\b",
    re.IGNORECASE,
)

_CHAT_EXPLANATION_RE = re.compile(
    r"\b(what is|what's|who is|tell me about|explain|meaning of|difference between|do you know|know about)\b|"
    r"(알아|뭐야|뭔지|무엇|설명|뜻|의미|차이|알려줘|궁금)",
    re.IGNORECASE,
)
_EXPLICIT_COMPUTE_ACTION_RE = re.compile(
    r"\b(show|render|visualize|display|plot|draw|compute|calculate|run|optimize|optimization|analyze|analysis|preview)\b|"
    r"(보여줘|그려줘|계산|구해|최적화|분석|실행|돌려줘|렌더|시각화)",
    re.IGNORECASE,
)
_NON_STRUCTURE_PARAMETER_ACRONYM_RE = re.compile(
    r"\b(?:using\s+)?([A-Z]{2,6})\s+(?:preset|palette|colormap|colourmap|theme|style)\b|"
    r"\b(?:method|functional|basis)\s+([A-Z]{2,6})\b",
    re.IGNORECASE,
)
_NON_STRUCTURE_ACRONYM_TERMS = {
    "HOMO",
    "LUMO",
    "ESP",
    "MO",
    "SCF",
    "DFT",
    "HF",
    "NMR",
    "IR",
    "UV",
    "TDDFT",
    "TD-DFT",
    "AIMD",
    "MD",
    "ACS",
    "RSC",
    "PBE",
    "BLYP",
}
_POSSIBLE_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}(?:[+\-])?\b")


def _translate_korean_aliases(text: str) -> str:
    result = str(text or "").strip()
    for ko_name, en_name in sorted(KO_TO_EN.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name not in result:
            continue
        pattern = re.compile(
            rf"(?<![가-힣A-Za-z0-9])({re.escape(ko_name)})"
            r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지)?"
            r"(?![가-힣A-Za-z0-9])"
        )
        result = pattern.sub(en_name, result)
    return result.strip()


def _normalize_formula_text(text: str) -> str:
    result = str(text or "").translate(_SUBSCRIPT_MAP)
    result = re.sub(r"[‐‑‒–—−]", "-", result)
    result = re.sub(r"\s*/+\s*$", "", result).strip()
    return result


def is_condensed_structural_formula(text: str) -> bool:
    raw = _normalize_formula_text(str(text or "").strip())
    compact = re.sub(r"\s+", "", raw)
    if not compact or len(compact) < 6:
        return False
    if "+" in compact or "." in compact:
        return False
    if not any(symbol in compact for symbol in ("(", ")", "-", "=", "#")):
        return False
    if not _CONDENSED_STRUCTURAL_FORMULA_RE.fullmatch(compact):
        return False
    tokens = re.findall(r"[A-Z][a-z]?\d*", compact)
    if len(tokens) < 3:
        return False
    if not any(any(ch.isdigit() for ch in token) for token in tokens):
        return False
    return True


_COMPAT_JONGSEONG_INDEX: Dict[str, int] = {
    "ㄱ": 1,
    "ㄲ": 2,
    "ㄳ": 3,
    "ㄴ": 4,
    "ㄵ": 5,
    "ㄶ": 6,
    "ㄷ": 7,
    "ㄹ": 8,
    "ㄺ": 9,
    "ㄻ": 10,
    "ㄼ": 11,
    "ㄽ": 12,
    "ㄾ": 13,
    "ㄿ": 14,
    "ㅀ": 15,
    "ㅁ": 16,
    "ㅂ": 17,
    "ㅄ": 18,
    "ㅅ": 19,
    "ㅆ": 20,
    "ㅇ": 21,
    "ㅈ": 22,
    "ㅊ": 23,
    "ㅋ": 24,
    "ㅌ": 25,
    "ㅍ": 26,
    "ㅎ": 27,
}

_STRUCTURE_PARENT_ALIASES: Dict[str, str] = {
    "benzene": "benzene",
    "벤젠": "benzene",
    "toluene": "toluene",
    "톨루엔": "toluene",
    "phenol": "phenol",
    "페놀": "phenol",
    "aniline": "aniline",
    "아닐린": "aniline",
    "pyridine": "pyridine",
    "피리딘": "pyridine",
    "naphthalene": "naphthalene",
    "나프탈렌": "naphthalene",
    "amine": "amine",
    "\uc544\ubbfc": "amine",
}

_SUBSTITUENT_PREFIX_ALIASES: Dict[str, str] = {
    "nitro": "nitro",
    "니트로": "nitro",
    "amino": "amino",
    "아미노": "amino",
    "hydroxy": "hydroxy",
    "하이드록시": "hydroxy",
    "hydroxyl": "hydroxy",
    "methyl": "methyl",
    "메틸": "methyl",
    "ethyl": "ethyl",
    "에틸": "ethyl",
    "propyl": "propyl",
    "프로필": "propyl",
    "butyl": "butyl",
    "부틸": "butyl",
    "fluoro": "fluoro",
    "플루오로": "fluoro",
    "fluor": "fluoro",
    "chloro": "chloro",
    "클로로": "chloro",
    "bromo": "bromo",
    "브로모": "bromo",
    "iodo": "iodo",
    "아이오도": "iodo",
    "cyano": "cyano",
    "시아노": "cyano",
    "formyl": "formyl",
    "포밀": "formyl",
    "acetyl": "acetyl",
    "아세틸": "acetyl",
}

_HALF_NORMALIZED_STRUCTURE_RE = re.compile(r"(?=.*[A-Za-z])(?=.*[가-힣ㄱ-ㅎㅏ-ㅣ])")
_HANGUL_FRAGMENT_GAP_RE = re.compile(r"(?<=[가-힣ㄱ-ㅎㅏ-ㅣ])\s+(?=[가-힣ㄱ-ㅎㅏ-ㅣ])")
_STRUCTURE_PARTICLE_TOKENS = {"도", "가", "이", "을", "를", "은", "는", "의", "에", "로", "만", "과", "와"}


def _is_hangul_syllable(ch: str) -> bool:
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3


def _hangul_jongseong_index(ch: str) -> Optional[int]:
    if not ch or not _is_hangul_syllable(ch):
        return None
    return (ord(ch) - 0xAC00) % 28


def _compose_trailing_compat_jamo(text: str) -> str:
    out: List[str] = []
    for ch in str(text or ""):
        jong = _COMPAT_JONGSEONG_INDEX.get(ch)
        if jong is not None and out:
            prev = out[-1]
            prev_jong = _hangul_jongseong_index(prev)
            if prev_jong == 0:
                out[-1] = chr(ord(prev) + jong)
                continue
        out.append(ch)
    return "".join(out)


def _compact_structure_phrase(text: str) -> str:
    token = _normalize_formula_text(str(text or "").strip())
    if not token:
        return ""
    token = _HANGUL_FRAGMENT_GAP_RE.sub("", token)
    token = _compose_trailing_compat_jamo(token)
    token = re.sub(r"\s+", " ", token).strip()
    return token


def _looks_like_half_normalized_structure(text: str) -> bool:
    token = str(text or "").strip()
    if not token:
        return False
    if _HALF_NORMALIZED_STRUCTURE_RE.search(token):
        return True
    return bool(re.search(r"[가-힣]\s+[ㄱ-ㅎㅏ-ㅣ]|[ㄱ-ㅎㅏ-ㅣ]\s+[가-힣]", token))


def _is_plausible_structure_candidate(text: str) -> bool:
    token = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;/")
    if not token:
        return False
    lower = token.lower()
    if re.fullmatch(r"(?:[\u3131-\u3163]+)(?:\s+[\u3131-\u3163]+)*", token):
        return False
    if not re.search(r"[A-Za-z0-9\uac00-\ud7a3\u3131-\u3163]", token):
        return False
    if sum(1 for char in token if char in {"?", "�"}) >= max(1, len(token) // 2):
        return False
    if token in _STRUCTURE_PARTICLE_TOKENS or lower in _PLAIN_MOLECULE_STOPWORDS or lower in _INVALID_STRUCTURE_WORDS:
        return False
    if len(token) == 1 and not _is_formula_like(token):
        return False
    words = [part for part in re.split(r"[\s,/]+", lower) if part]
    if words and all(part in _PLAIN_MOLECULE_STOPWORDS or part in _STRUCTURE_PARTICLE_TOKENS for part in words):
        return False
    if detect_task_hint(token) and not _is_formula_like(token):
        return False
    return True


def _expand_compositional_candidates(text: str) -> List[str]:
    raw = _compact_structure_phrase(text)
    if not raw:
        return []

    translated = _expand_abbreviations(_translate_korean_aliases(raw))
    lowered_compact = translated.lower().replace(" ", "")
    candidates: List[str] = []

    def add_candidate(value: Optional[str]) -> None:
        token = str(value or "").strip()
        if not token:
            return
        if token.lower() not in {item.lower() for item in candidates}:
            candidates.append(token)

    def add_joined_candidates(prefix_tokens: List[str], parent_name: str) -> None:
        if not prefix_tokens:
            return
        joined = "".join(prefix_tokens) + parent_name
        add_candidate(joined)
        add_candidate(" ".join(prefix_tokens + [parent_name]))

    normalized_prefix_lookup = {
        re.sub(r"[\s\-]+", "", str(key).lower()): value
        for key, value in _SUBSTITUENT_PREFIX_ALIASES.items()
        if str(key).strip() and str(value).strip()
    }
    sorted_prefix_aliases = sorted(normalized_prefix_lookup.keys(), key=len, reverse=True)

    def split_substituent_prefixes(prefix_text: str) -> List[str]:
        remaining = re.sub(r"[\s\-]+", "", str(prefix_text or "").lower())
        if not remaining:
            return []
        resolved: List[str] = []
        while remaining:
            matched = next((alias for alias in sorted_prefix_aliases if remaining.startswith(alias)), None)
            if not matched:
                return []
            resolved.append(normalized_prefix_lookup[matched])
            remaining = remaining[len(matched):]
        return resolved

    for parent_alias, parent_name in sorted(_STRUCTURE_PARENT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        parent_alias_lc = parent_alias.lower().replace(" ", "")
        if not lowered_compact.endswith(parent_alias_lc):
            continue
        prefix_part = lowered_compact[: -len(parent_alias_lc)].strip(" -")
        if not prefix_part:
            continue
        prefix_tokens = [tok for tok in re.split(r"[\s\-]+", prefix_part) if tok]
        if not prefix_tokens and prefix_part:
            prefix_tokens = [prefix_part]
        mapped_prefixes: List[str] = []
        for token in prefix_tokens:
            mapped = _SUBSTITUENT_PREFIX_ALIASES.get(token)
            if not mapped:
                mapped_prefixes = []
                break
            mapped_prefixes.append(mapped)
        if not mapped_prefixes:
            mapped_prefixes = split_substituent_prefixes(prefix_part)
        add_joined_candidates(mapped_prefixes, parent_name)

    token_list = [tok for tok in re.split(r"[\s,/;]+", translated) if tok]
    if len(token_list) >= 2:
        parent_name = _STRUCTURE_PARENT_ALIASES.get(token_list[-1].lower())
        if parent_name:
            mapped_prefixes: List[str] = []
            for token in token_list[:-1]:
                mapped = _SUBSTITUENT_PREFIX_ALIASES.get(token.lower())
                if not mapped:
                    mapped_prefixes = []
                    break
                mapped_prefixes.append(mapped)
            add_joined_candidates(mapped_prefixes, parent_name)

    return candidates


def _find_korean_molecule_name(text: str) -> Optional[str]:
    cleaned = _space_korean_compounds(str(text or "").strip())
    for ko_name, en_name in sorted(KO_TO_EN.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(
            rf"(?<![가-힣A-Za-z0-9]){re.escape(ko_name)}"
            r"(?:은|는|이|가|을|를|의|에|에서|로|부터|에\s*대해|에\s*대한|도|만|까지)?"
            r"(?![가-힣A-Za-z0-9])"
        )
        if pattern.search(cleaned):
            return en_name
    return None


def _clean_structure_candidate(candidate: str) -> Optional[str]:
    text = _compact_structure_phrase(candidate)
    text = _translate_korean_aliases(text)
    text = _expand_abbreviations(text)
    compositional_candidates = _expand_compositional_candidates(text)
    if compositional_candidates:
        text = compositional_candidates[0]
    text = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;")
    text = re.sub(r"^(?:[\u3131-\u3163]{2,4})\s+", "", text).strip(" .,:;")
    text = re.sub(r"^(?:[\u3131-\u3163]{2,4})(?=[\uac00-\ud7a3])", "", text).strip(" .,:;")
    if not text:
        return None
    text = re.sub(r"([+\-])(?:이온쌍|이온)\b", r"\1", text)

    changed = True
    while changed and text:
        changed = False
        for word in _TASK_NOISE_WORDS:
            patterns = [
                rf"(?:\s+|^){re.escape(word)}$",
                rf"{re.escape(word)}$",
            ]
            for pattern in patterns:
                new_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" .,:;")
                if new_text != text:
                    text = new_text
                    changed = True
                    break
            if changed:
                break

    text = re.sub(
        r"(?:\s+|^)(?:구조|오비탈|전하|계산|분석|맵)(?:만)?$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" .,:;")

    if not text:
        return None

    lowered = text.lower()
    if lowered in _INVALID_STRUCTURE_WORDS:
        return None

    tokens = [tok for tok in re.split(r"\s+", lowered) if tok]
    if tokens and all(tok in _INVALID_STRUCTURE_WORDS for tok in tokens):
        return None

    return text


def _strip_structure_edge_noise(text: str) -> str:
    token = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;/")
    if not token:
        return ""

    words = [word for word in token.split(" ") if word]
    while words and words[0].lower() in _STRUCTURE_EDGE_NOISE_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _STRUCTURE_EDGE_NOISE_WORDS:
        words.pop()
    return " ".join(words).strip(" .,:;/")


def _normalize_structure_mention(text: str) -> Optional[str]:
    token = _normalize_formula_text(_space_korean_compounds(str(text or "").strip()))
    token = _translate_korean_aliases(token)
    token = _expand_abbreviations(token)
    token = _strip_structure_edge_noise(token)
    return _clean_structure_candidate(token)


def _looks_like_follow_up_placeholder_candidate(text: str) -> bool:
    token = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;/")
    if not token:
        return False
    if _FOLLOW_UP_PLACEHOLDER_RE.fullmatch(token):
        return True
    compact = token.replace(" ", "")
    if compact in {"\u3147\u3147", "\u3131\u3131"}:
        return True
    if re.fullmatch(r"[?\u3131-\u3163]+", compact):
        return True
    return compact in {
        "\uadf8\uac70",
        "\uc774\uac70",
        "\uc800\uac70",
        "\uadf8\uac78",
        "\uc774\uac78",
        "\uc800\uac78",
        "\ubc29\uae08\uac70",
        "\uc544\uae4c\uac70",
        "\uadf8\ubd84\uc790",
        "\uc774\ubd84\uc790",
        "\uc800\ubd84\uc790",
        "\uadf8\uad6c\uc870",
        "\uc774\uad6c\uc870",
        "\uc800\uad6c\uc870",
        "\uc774\ubc88\uc5d4",
        "\uc774\ubc88\uc5d0\ub294",
    }


def analyze_semantic_structure_query(
    text: str,
    *,
    structure_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    if not raw:
        return {
            "semantic_descriptor": False,
            "query_mode": "empty",
            "descriptor_hits": [],
            "has_concrete_candidate": False,
            "reasoning_notes": [],
        }

    analysis = dict(structure_analysis or analyze_structure_input(raw))
    compact = _compact_structure_phrase(raw)
    translated = _translate_korean_aliases(_space_korean_compounds(raw))
    search_text = re.sub(r"\s+", " ", translated or compact or raw).strip()

    descriptor_hits: List[str] = []
    reasoning_notes: List[str] = []
    for pattern in _SEMANTIC_DESCRIPTOR_PATTERNS:
        if pattern.search(search_text):
            descriptor_hits.append(pattern.pattern)

    raw_variants = {
        variant.lower()
        for variant in (raw, compact, search_text)
        if str(variant or "").strip()
    }
    raw_signatures = {
        _structure_text_signature(variant)
        for variant in (raw, compact, search_text)
        if _structure_text_signature(variant)
    }
    canonical_candidates = [
        str(item).strip()
        for item in list(analysis.get("canonical_candidates") or [])
        if str(item).strip()
    ]
    primary_candidate = str(analysis.get("primary_candidate") or "").strip()
    direct_input_confident = bool(analysis.get("direct_input_confident"))
    direct_name_like = bool(
        primary_candidate
        and (
            _looks_like_plain_molecule_name(primary_candidate)
            or _is_formula_like(primary_candidate)
            or bool(_find_korean_molecule_name(raw))
        )
    )

    concrete_candidates = [
        candidate
        for candidate in canonical_candidates
        if _looks_like_plain_molecule_name(candidate)
        and candidate.lower() not in raw_variants
        and _structure_text_signature(candidate) not in raw_signatures
    ]
    if (
        primary_candidate
        and _looks_like_plain_molecule_name(primary_candidate)
        and primary_candidate.lower() not in raw_variants
        and _structure_text_signature(primary_candidate) not in raw_signatures
    ):
        concrete_candidates.insert(0, primary_candidate)

    has_concrete_candidate = bool(concrete_candidates or (direct_input_confident and direct_name_like))
    if (
        not descriptor_hits
        and not has_concrete_candidate
        and any("\uac00" <= char <= "\ud7a3" for char in search_text)
        and len([token for token in search_text.split() if token.strip()]) >= 3
        and not detect_task_hint(search_text)
    ):
        descriptor_hits.append("korean_descriptive_phrase")
    semantic_descriptor = bool(descriptor_hits) and not has_concrete_candidate

    if semantic_descriptor:
        reasoning_notes.append("detected semantic descriptor wording without grounded molecule name")
        if _SEMANTIC_GENERIC_NOUN_RE.search(search_text):
            reasoning_notes.append("generic material/component noun present in query")
    elif descriptor_hits and has_concrete_candidate:
        reasoning_notes.append("descriptor wording present but explicit molecule candidate is available")

    query_mode = "semantic_descriptor" if semantic_descriptor else "direct_name"
    return {
        "semantic_descriptor": semantic_descriptor,
        "query_mode": query_mode,
        "descriptor_hits": descriptor_hits,
        "has_concrete_candidate": has_concrete_candidate,
        "reasoning_notes": _dedupe_keep_order(reasoning_notes),
    }


def _is_formula_like(token: str) -> bool:
    compact = re.sub(r"\s+", "", _normalize_formula_text(str(token or "").strip()))
    if not compact:
        return False
    return bool(
        _FORMULA_LIKE_RE.fullmatch(compact)
        or _STRUCTURAL_FORMULA_RE.fullmatch(compact)
        or is_condensed_structural_formula(compact)
    )


def _looks_like_enumeration_label(token: str) -> bool:
    text = str(token or "").strip(" .,:;()[]")
    return bool(re.fullmatch(r"[A-Za-z]|\d+", text))


def _split_multi_molecule_segments(text: str) -> List[str]:
    raw = _normalize_formula_text(str(text or "").strip())
    if not raw:
        return []

    matches = list(_ENUMERATION_MARKER_RE.finditer(raw))
    if len(matches) >= 2:
        segments: List[str] = []
        for idx, match in enumerate(matches):
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
            segment = raw[start:end].strip(" \n\t.;")
            if segment:
                segments.append(segment)
        return segments

    chunks = [
        part.strip(" \n\t.;")
        for part in re.split(r"\n\s*\n+|(?:^|\n)\s*[-*]\s+", raw)
        if part.strip(" \n\t.;")
    ]
    if len(chunks) >= 2:
        return chunks
    return [raw] if raw else []


def _extract_formula_tokens(text: str) -> List[str]:
    head = _normalize_formula_text(str(text or "")[:160])
    return _dedupe_keep_order(
        [token for token in _FORMULA_TOKEN_RE.findall(head) if _is_formula_like(token)]
    )


def _extract_parenthetical_aliases(text: str) -> List[str]:
    head = str(text or "")[:160]
    aliases: List[str] = []
    for candidate in re.findall(r"\(([^()]{1,80})\)", head):
        normalized = _normalize_structure_mention(candidate)
        if not normalized:
            continue
        if _looks_like_enumeration_label(normalized):
            continue
        if len(normalized) > 40:
            continue
        aliases.append(normalized)
    return _dedupe_keep_order(aliases)


def _extract_multi_molecule_set(text: str) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    segments = _split_multi_molecule_segments(raw)
    if len(segments) < 2:
        return {
            "mentions": [],
            "canonical_names": [],
            "raw_segments": [],
            "multi_molecule": False,
        }

    mentions: List[Dict[str, Any]] = []
    canonical_names: List[str] = []
    raw_segments: List[str] = []

    for index, segment in enumerate(segments):
        translated = _translate_korean_aliases(_space_korean_compounds(segment))
        translated = re.sub(r"\s+", " ", translated).strip()
        formulas = _extract_formula_tokens(translated)
        aliases = _extract_parenthetical_aliases(translated)
        if not aliases:
            head = translated[:120]
            for ko_name, en_name in sorted(KO_TO_EN.items(), key=lambda item: len(item[0]), reverse=True):
                if ko_name in segment:
                    aliases.append(en_name)
            aliases = _dedupe_keep_order(aliases)
            if not aliases:
                for match in re.findall(r"\b(?:[A-Z][a-z]+(?:[- ,][A-Za-z0-9]+){0,3})\b", head):
                    cleaned = _normalize_structure_mention(match)
                    if cleaned and not _looks_like_enumeration_label(cleaned):
                        aliases.append(cleaned)
                aliases = _dedupe_keep_order(aliases)

        alias = aliases[0] if aliases else None
        formula = formulas[0] if formulas else None
        if not alias and not formula:
            continue

        canonical = alias or formula
        if not canonical:
            continue
        if _looks_like_enumeration_label(canonical):
            continue
        if len(canonical) > 64:
            continue

        mention = {
            "raw_text": segment,
            "formula": formula,
            "alias": alias,
            "canonical_name": canonical,
            "segment_index": index,
            "confidence": 0.92 if alias and formula else 0.75,
        }
        mentions.append(mention)
        canonical_names.append(canonical)
        raw_segments.append(segment)

    canonical_names = _dedupe_keep_order(canonical_names)
    mentions = [
        item for item in mentions
        if str(item.get("canonical_name") or "").strip().lower() in {name.lower() for name in canonical_names}
    ]
    return {
        "mentions": mentions,
        "canonical_names": canonical_names,
        "raw_segments": raw_segments,
        "multi_molecule": len(canonical_names) >= 2,
    }


def analyze_target_selection(text: str, canonical_names: List[str]) -> Dict[str, Any]:
    raw = str(text or "").strip()
    names = list(canonical_names or [])
    if not names:
        return {
            "target_scope": None,
            "selection_mode": None,
            "selection_hint": None,
            "selected_molecules": [],
        }

    if _BATCH_ALL_MENTIONED_RE.search(raw):
        return {
            "target_scope": "all_mentioned",
            "selection_mode": "explicit_all",
            "selection_hint": "all_mentioned",
            "selected_molecules": names,
        }
    if _BATCH_FIRST_TWO_RE.search(raw):
        return {
            "target_scope": "subset",
            "selection_mode": "subset_picker",
            "selection_hint": "first_two",
            "selected_molecules": names[:2],
        }
    if _BATCH_FIRST_ONLY_RE.search(raw):
        return {
            "target_scope": "subset",
            "selection_mode": "subset_picker",
            "selection_hint": "first_only",
            "selected_molecules": names[:1],
        }
    return {
        "target_scope": None,
        "selection_mode": None,
        "selection_hint": None,
        "selected_molecules": [],
    }


def analyze_analysis_bundle(text: str) -> List[str]:
    raw = str(text or "")
    bundle: List[str] = []
    if _ANALYSIS_STRUCTURE_RE.search(raw):
        bundle.append("structure")
    if _ANALYSIS_HOMO_RE.search(raw):
        bundle.append("HOMO")
    if _ANALYSIS_LUMO_RE.search(raw):
        bundle.append("LUMO")
    if _ANALYSIS_ESP_RE.search(raw):
        bundle.append("ESP")
    return _dedupe_keep_order(bundle)


def _collect_structure_mentions(text: str) -> Dict[str, Any]:
    raw_input = _normalize_formula_text(str(text or "").strip())
    multi_set = _extract_multi_molecule_set(raw_input)
    if multi_set.get("multi_molecule"):
        mentions = list(multi_set.get("mentions") or [])
        canonical_names = list(multi_set.get("canonical_names") or [])
        return {
            "raw_input": raw_input,
            "mentions": canonical_names,
            "formula_mentions": _dedupe_keep_order([str(item.get("formula") or "") for item in mentions if str(item.get("formula") or "").strip()]),
            "alias_mentions": _dedupe_keep_order([str(item.get("alias") or item.get("canonical_name") or "") for item in mentions if str(item.get("alias") or item.get("canonical_name") or "").strip()]),
            "canonical_candidates": canonical_names,
            "mixed_input": False,
            "primary_candidate": None,
            "direct_input_confident": False,
            "multi_molecule": True,
            "mentioned_molecules": mentions,
            "raw_segments": list(multi_set.get("raw_segments") or []),
            "condensed_formula": False,
        }

    if is_condensed_structural_formula(raw_input):
        return {
            "raw_input": raw_input,
            "mentions": [raw_input],
            "formula_mentions": [raw_input],
            "alias_mentions": [],
            "canonical_candidates": [raw_input],
            "mixed_input": False,
            "primary_candidate": raw_input,
            "direct_input_confident": True,
            "multi_molecule": False,
            "mentioned_molecules": [],
            "raw_segments": [],
            "condensed_formula": True,
        }

    mentions: List[str] = []
    direct_input_confident = False

    def add_mention(value: str) -> None:
        normalized = _normalize_structure_mention(value)
        if not normalized:
            return
        if normalized.lower() not in {item.lower() for item in mentions}:
            mentions.append(normalized)

    for match in _PAREN_MIXED_RE.finditer(raw_input):
        add_mention(match.group("left"))
        add_mention(match.group("right"))
        direct_input_confident = True

    if not mentions and any(sep in raw_input for sep in ("/", ",", ";")):
        for part in _LIST_MIXED_SPLIT_RE.split(raw_input):
            add_mention(part)
        if len(mentions) >= 2:
            direct_input_confident = True

    if not mentions:
        candidate = _normalize_structure_mention(raw_input)
        if candidate:
            mentions.append(candidate)
            if not detect_task_hint(raw_input):
                direct_input_confident = True

    formula_mentions = [item for item in mentions if _is_formula_like(item)]
    alias_mentions = [item for item in mentions if item not in formula_mentions]

    canonical_candidates = _dedupe_keep_order(
        alias_mentions
        + [syn for alias in alias_mentions for syn in _SYSTEMATIC_NAME_SYNONYMS.get(alias.lower(), [])]
        + formula_mentions
    )
    mixed_input = bool(formula_mentions and alias_mentions)
    primary_candidate = canonical_candidates[0] if canonical_candidates else None

    return {
        "raw_input": raw_input,
        "mentions": mentions,
        "formula_mentions": formula_mentions,
        "alias_mentions": alias_mentions,
        "canonical_candidates": canonical_candidates,
        "mixed_input": mixed_input,
        "primary_candidate": primary_candidate,
        "direct_input_confident": direct_input_confident,
        "multi_molecule": False,
        "mentioned_molecules": [],
        "raw_segments": [],
        "condensed_formula": False,
    }


def analyze_structure_input(text: str) -> Dict[str, Any]:
    return _collect_structure_mentions(text)


def _extract_unknown_acronyms(text: str) -> List[str]:
    raw = str(text or "")
    tokens = [match.group(0) for match in _POSSIBLE_ACRONYM_RE.finditer(raw)]
    parameter_tokens = {
        match.group(1).upper()
        for match in _NON_STRUCTURE_PARAMETER_ACRONYM_RE.finditer(raw)
        if match.group(1)
    }
    parameter_tokens.update(
        {
            match.group(2).upper()
            for match in _NON_STRUCTURE_PARAMETER_ACRONYM_RE.finditer(raw)
            if match.group(2)
        }
    )
    out: List[str] = []
    seen = set()
    for token in tokens:
        if token.upper() in _NON_STRUCTURE_ACRONYM_TERMS:
            continue
        if token.upper() in parameter_tokens:
            continue
        if re.search(rf"\b(?:def2[- ]?|cc-pv|aug-cc-pv){re.escape(token)}\b", raw, re.IGNORECASE):
            continue
        lowered = token.lower()
        if lowered in ABBREVIATION_MAP:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(token)
    return out


def analyze_query_routing(
    text: str,
    *,
    structure_analysis: Optional[Dict[str, Any]] = None,
    semantic_info: Optional[Dict[str, Any]] = None,
    follow_up_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    if not raw:
        return {
            "query_kind": "compute_ready",
            "chat_only": False,
            "semantic_grounding_needed": False,
            "question_like": False,
            "explicit_compute_action": False,
            "unknown_acronyms": [],
            "reasoning_notes": [],
        }

    structure_analysis = dict(structure_analysis or analyze_structure_input(raw))
    semantic_info = dict(
        semantic_info or analyze_semantic_structure_query(raw, structure_analysis=structure_analysis)
    )
    follow_up_analysis = dict(follow_up_analysis or analyze_follow_up_request(raw))
    normalized_text = re.sub(r"\s+", " ", _space_korean_compounds(raw)).strip()

    if structure_analysis.get("condensed_formula"):
        return {
            "query_kind": "compute_ready",
            "chat_only": False,
            "semantic_grounding_needed": False,
            "question_like": False,
            "explicit_compute_action": False,
            "unknown_acronyms": [],
            "reasoning_notes": ["condensed structural formula locked as a single structure input"],
        }

    stripped_raw = raw.rstrip()
    has_terminal_question_mark = stripped_raw.endswith("?") or stripped_raw.endswith("？")
    has_explanation_phrase = bool(_CHAT_EXPLANATION_RE.search(normalized_text))
    question_like = bool(has_terminal_question_mark or has_explanation_phrase)
    explicit_compute_action = bool(_EXPLICIT_COMPUTE_ACTION_RE.search(normalized_text))
    unknown_acronyms = _extract_unknown_acronyms(normalized_text)
    analysis_bundle = analyze_analysis_bundle(raw)

    primary_candidate = str(structure_analysis.get("primary_candidate") or "").strip()
    direct_molecule_like = bool(
        primary_candidate and (_looks_like_plain_molecule_name(primary_candidate) or _is_formula_like(primary_candidate))
    )
    explanation_priority = bool(
        has_explanation_phrase
        and not follow_up_analysis.get("requires_context")
        and not analysis_bundle
        and not semantic_info.get("semantic_descriptor")
        and not direct_molecule_like
    )

    chat_only = bool(
        explanation_priority
        or (
            not follow_up_analysis.get("requires_context")
            and not explicit_compute_action
            and not analysis_bundle
            and (
                has_explanation_phrase
                or has_terminal_question_mark
                or bool(unknown_acronyms and not direct_molecule_like)
            )
        )
    )

    semantic_grounding_needed = bool(semantic_info.get("semantic_descriptor"))
    if follow_up_analysis.get("follow_up_mode"):
        semantic_grounding_needed = False
    if chat_only and unknown_acronyms and question_like:
        semantic_grounding_needed = True
    if unknown_acronyms and explicit_compute_action:
        semantic_grounding_needed = True

    query_kind = "compute_ready"
    if chat_only:
        query_kind = "chat_only"
    elif semantic_grounding_needed:
        query_kind = "grounding_required"

    reasoning_notes: List[str] = []
    if chat_only:
        reasoning_notes.append("question-like input without explicit compute action -> chat_only")
    if explanation_priority and explicit_compute_action:
        reasoning_notes.append("explanation phrase without explicit structure takes priority over compute wording")
    if semantic_grounding_needed:
        reasoning_notes.append("descriptor or unresolved acronym requires grounding before compute")
    elif follow_up_analysis.get("follow_up_mode"):
        reasoning_notes.append("follow-up request should be resolved through session continuation, not semantic grounding")
    if unknown_acronyms:
        reasoning_notes.append("unknown uppercase acronym detected")

    return {
        "query_kind": query_kind,
        "chat_only": chat_only,
        "semantic_grounding_needed": semantic_grounding_needed,
        "question_like": question_like,
        "explicit_compute_action": explicit_compute_action,
        "unknown_acronyms": unknown_acronyms,
        "reasoning_notes": _dedupe_keep_order(reasoning_notes),
    }


def build_structure_hypotheses(
    text: str,
    *,
    base_analysis: Optional[Dict[str, Any]] = None,
    translated_text: Optional[str] = None,
    expanded_text: Optional[str] = None,
) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    compact = _compact_structure_phrase(raw)
    analysis = dict(base_analysis or analyze_structure_input(raw))
    translated = translated_text or _translate_korean_aliases(_space_korean_compounds(compact or raw))
    expanded = expanded_text or _expand_abbreviations(translated)
    semantic_info = analyze_semantic_structure_query(raw, structure_analysis=analysis)
    raw_variants = {
        variant.lower()
        for variant in (raw, compact, translated, expanded)
        if str(variant or "").strip()
    }
    raw_signatures = {
        _structure_text_signature(variant)
        for variant in (raw, compact, translated, expanded)
        if _structure_text_signature(variant)
    }

    candidates: List[str] = []
    reasoning_notes: List[str] = []

    def add_candidate(value: Optional[str], *, reason: Optional[str] = None) -> None:
        token = _clean_structure_candidate(value or "")
        if not token:
            return
        if not _is_plausible_structure_candidate(token):
            return
        if semantic_info.get("semantic_descriptor"):
            token_lower = token.lower()
            if (
                (token_lower in raw_variants or _structure_text_signature(token) in raw_signatures)
                and not _is_formula_like(token)
            ):
                return
            if not (_looks_like_plain_molecule_name(token) or _is_formula_like(token)):
                return
        if token.lower() in {item.lower() for item in candidates}:
            return
        candidates.append(token)
        if reason:
            reasoning_notes.append(reason)

    if compact and compact != raw:
        reasoning_notes.append("collapsed spaced Hangul fragments before structure matching")

    for value in list(analysis.get("canonical_candidates") or []):
        add_candidate(value, reason="structure analysis candidate")

    if analysis.get("primary_candidate"):
        add_candidate(analysis.get("primary_candidate"), reason="primary structure analysis candidate")

    extracted = None
    if raw and not semantic_info.get("semantic_descriptor"):
        extracted = extract_structure_candidate(raw)
    if extracted:
        add_candidate(extracted, reason="candidate extracted from raw message")

    seeds: List[Optional[str]] = [compact, translated]
    if not semantic_info.get("semantic_descriptor"):
        seeds.append(expanded)
    for seed in seeds:
        normalized_seed = _normalize_structure_mention(seed)
        add_candidate(normalized_seed, reason="normalized structure mention")
        for extra in _expand_compositional_candidates(seed):
            add_candidate(extra, reason="compositional substituent-parent reconstruction")

    if extracted:
        extracted_candidate = _clean_structure_candidate(extracted)
        if extracted_candidate and _looks_like_locant_structure_name(extracted_candidate):
            candidates = [extracted_candidate] + [
                item for item in candidates if str(item).strip().lower() != extracted_candidate.lower()
            ]

    primary_candidate = candidates[0] if candidates else None
    suspicious_input = _looks_like_half_normalized_structure(raw) or bool(re.search(r"[ㄱ-ㅎㅏ-ㅣ]", raw))
    suspicious_primary = _looks_like_half_normalized_structure(primary_candidate or "")

    confidence = 0.0
    if primary_candidate:
        confidence = 0.82
        if analysis.get("direct_input_confident"):
            confidence = 0.95
        elif suspicious_input:
            confidence = 0.88
        elif primary_candidate.lower() != raw.lower():
            confidence = 0.86
    if suspicious_input and not primary_candidate:
        confidence = max(confidence, 0.35)
    if suspicious_primary:
        confidence = min(confidence, 0.60)

    needs_clarification = bool((not primary_candidate and raw) or suspicious_primary or semantic_info.get("semantic_descriptor"))

    for note in list(semantic_info.get("reasoning_notes") or []):
        if note and note not in reasoning_notes:
            reasoning_notes.append(str(note))

    return {
        "raw_query": raw,
        "compact_query": compact,
        "translated_query": translated,
        "expanded_query": expanded,
        "primary_candidate": primary_candidate,
        "candidate_queries": candidates,
        "confidence": confidence,
        "needs_clarification": needs_clarification,
        "suspicious_input": suspicious_input,
        "semantic_descriptor": bool(semantic_info.get("semantic_descriptor")),
        "reasoning_notes": _dedupe_keep_order(reasoning_notes),
    }


def analyze_composite_structure_input(text: str) -> Dict[str, Any]:
    raw = _normalize_formula_text(_space_korean_compounds(str(text or "").strip()))
    if not raw:
        return {
            "raw_input": raw,
            "composition_kind": None,
            "structures": [],
            "charge_hint": None,
            "component_names": [],
        }
    if is_condensed_structural_formula(raw):
        return {
            "raw_input": raw,
            "composition_kind": None,
            "structures": [],
            "charge_hint": None,
            "component_names": [],
        }

    try:
        from qcviz_mcp.services.ion_pair_handler import ION_ALIASES
    except Exception:
        ION_ALIASES = {}

    alias_lookup: Dict[str, Dict[str, Any]] = {}
    for key, value in dict(ION_ALIASES or {}).items():
        alias_lookup[str(key).upper()] = dict(value or {})
        alias_lookup[str(key).rstrip("+-").upper()] = dict(value or {})

    translated = _translate_korean_aliases(raw)
    cleaned = re.sub(
        r"\b(using|with|show|render|visualize|calculate|compute|analysis|energy|orbital|esp|charge|charges|optimization|optimize)\b|"
        r"보여줘|그려줘|계산|분석|오비탈|전하|최적화|에너지|구조|이온쌍",
        " ",
        translated,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[(),;/]", " ", cleaned)
    tokens = [tok for tok in re.findall(r"[A-Za-z][A-Za-z0-9+\-]{0,31}", cleaned) if tok]

    cation_keys = sorted(
        {key.rstrip("+-").upper() for key, info in alias_lookup.items() if str((info or {}).get("type")) == "cation"},
        key=len,
        reverse=True,
    )
    anion_keys = sorted(
        {key.rstrip("+-").upper() for key, info in alias_lookup.items() if str((info or {}).get("type")) == "anion"},
        key=len,
        reverse=True,
    )

    def _component_from_token(token: str) -> Optional[Dict[str, Any]]:
        cleaned_token = str(token or "").strip()
        if not cleaned_token:
            return None
        upper = cleaned_token.upper()
        info = alias_lookup.get(upper) or alias_lookup.get(upper.rstrip("+-"))
        if not info:
            return None
        explicit_charge = None
        if cleaned_token.endswith("+"):
            explicit_charge = 1
        elif cleaned_token.endswith("-"):
            explicit_charge = -1
        charge = explicit_charge if explicit_charge is not None else int(info.get("default_charge", 0) or 0)
        return {
            "name": cleaned_token.rstrip("+-") or cleaned_token,
            "charge": charge,
            "resolved_name": str(info.get("name") or cleaned_token),
            "ion_type": str(info.get("type") or "unknown"),
        }

    def _split_concatenated_salt(token: str) -> List[Dict[str, Any]]:
        upper = str(token or "").upper().rstrip("+-")
        if not upper:
            return []
        for cation in cation_keys:
            if not upper.startswith(cation):
                continue
            for anion in anion_keys:
                if upper == f"{cation}{anion}":
                    cation_component = _component_from_token(cation)
                    anion_component = _component_from_token(anion)
                    if cation_component and anion_component:
                        return [cation_component, anion_component]
        return []

    components: List[Dict[str, Any]] = []
    composition_kind: Optional[str] = None

    for token in tokens:
        component = _component_from_token(token)
        if component:
            components.append(component)
            continue
        split_components = _split_concatenated_salt(token)
        if split_components:
            components.extend(split_components)
            composition_kind = composition_kind or "salt"

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for component in components:
        key = (str(component.get("name")).lower(), int(component.get("charge") or 0))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(component)

    has_cation = any(int(item.get("charge") or 0) > 0 for item in deduped)
    has_anion = any(int(item.get("charge") or 0) < 0 for item in deduped)
    if composition_kind is None and len(deduped) >= 2 and has_cation and has_anion:
        composition_kind = "ion_pair"

    charge_hint = None
    if len(deduped) == 1:
        charge_hint = int(deduped[0].get("charge") or 0) or None

    return {
        "raw_input": raw,
        "composition_kind": composition_kind,
        "structures": [{"name": item["name"], "charge": int(item.get("charge") or 0)} for item in deduped],
        "charge_hint": charge_hint,
        "component_names": [str(item.get("resolved_name") or item.get("name") or "") for item in deduped if str(item.get("resolved_name") or item.get("name") or "").strip()],
    }


def _format_composite_structure_query(structures: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in structures:
        name = str(item.get("name") or "").strip()
        charge = int(item.get("charge") or 0)
        if not name:
            continue
        if charge > 0:
            parts.append(f"{name} +")
        elif charge < 0:
            parts.append(name if name.endswith("-") else f"{name}-")
        else:
            parts.append(name)
    return " ".join(parts).strip()


def analyze_follow_up_request(text: str) -> Dict[str, Any]:
    raw = _normalize_formula_text(str(text or "").strip())
    if not raw:
        return {
            "follow_up_mode": None,
            "job_type": None,
            "orbital": None,
            "basis_hint": None,
            "method_hint": None,
            "requires_context": False,
        }

    structure_analysis = analyze_structure_input(raw)
    primary_candidate = str(structure_analysis.get("primary_candidate") or "").strip()
    placeholder_candidate = _looks_like_follow_up_placeholder_candidate(primary_candidate)
    explicit_structure_candidate = primary_candidate
    if (
        not explicit_structure_candidate
        or placeholder_candidate
        or detect_task_hint(explicit_structure_candidate)
        or not _is_plausible_structure_candidate(explicit_structure_candidate)
    ):
        fallback_candidate = str(extract_structure_candidate(raw) or "").strip()
        if (
            fallback_candidate
            and not _looks_like_follow_up_placeholder_candidate(fallback_candidate)
            and not detect_task_hint(fallback_candidate)
            and (_looks_like_plain_molecule_name(fallback_candidate) or _is_formula_like(fallback_candidate))
        ):
            explicit_structure_candidate = fallback_candidate
    placeholder_candidate = placeholder_candidate or _looks_like_follow_up_placeholder_candidate(
        explicit_structure_candidate
    )
    explicit_structure = bool(explicit_structure_candidate) and not placeholder_candidate and (
        _looks_like_plain_molecule_name(explicit_structure_candidate) or _is_formula_like(explicit_structure_candidate)
    )
    lower = raw.lower()
    spaced_raw = _space_korean_compounds(raw)
    search_text = spaced_raw or raw
    has_continuation_cue = bool(_FOLLOW_UP_CONTINUATION_CUE_RE.search(spaced_raw))
    has_analysis_suffix_cue = bool(_FOLLOW_UP_ANALYSIS_SUFFIX_RE.search(search_text))
    has_explanation_phrase = bool(_CHAT_EXPLANATION_RE.search(search_text))
    explicit_compute_action = bool(_EXPLICIT_COMPUTE_ACTION_RE.search(search_text))
    same_structure_cue = bool(_FOLLOW_UP_SAME_STRUCTURE_RE.search(search_text))
    preliminary_analysis_signal_count = sum(
        [
            bool(_FOLLOW_UP_ORBITAL_RE.search(search_text)),
            bool(_FOLLOW_UP_ESP_RE.search(search_text)),
            bool(_FOLLOW_UP_CHARGE_RE.search(search_text)),
            bool(_FOLLOW_UP_OPT_RE.search(search_text)),
            bool(_FOLLOW_UP_BASIS_RE.search(search_text)),
        ]
    )

    if (
        has_explanation_phrase
        and not explicit_compute_action
        and not explicit_structure
        and not same_structure_cue
        and preliminary_analysis_signal_count <= 1
        and not has_continuation_cue
        and not has_analysis_suffix_cue
    ):
        return {
            "follow_up_mode": None,
            "job_type": None,
            "orbital": None,
            "basis_hint": None,
            "method_hint": None,
            "requires_context": False,
        }

    follow_up_mode: Optional[str] = None
    job_type: Optional[str] = None
    orbital: Optional[str] = None
    basis_hint: Optional[str] = None
    method_hint: Optional[str] = None

    if _FOLLOW_UP_REUSE_LAST_JOB_RE.search(search_text):
        follow_up_mode = "reuse_last_job"

    if _FOLLOW_UP_ORBITAL_RE.search(search_text):
        job_type = "orbital_preview"
        orbital_match = re.search(r"(homo|lumo)", search_text, re.IGNORECASE)
        if orbital_match:
            orbital = orbital_match.group(1).upper()
        if not follow_up_mode and not explicit_structure and (has_continuation_cue or has_analysis_suffix_cue):
            follow_up_mode = "add_analysis"
    elif _FOLLOW_UP_ESP_RE.search(search_text):
        job_type = "esp_map"
        if not follow_up_mode and not explicit_structure and (has_continuation_cue or has_analysis_suffix_cue):
            follow_up_mode = "add_analysis"
    elif _FOLLOW_UP_CHARGE_RE.search(search_text):
        job_type = "partial_charges"
        if not follow_up_mode and not explicit_structure and (has_continuation_cue or has_analysis_suffix_cue):
            follow_up_mode = "add_analysis"
    elif _FOLLOW_UP_OPT_RE.search(search_text):
        job_type = "geometry_optimization"
        if same_structure_cue or (
            not explicit_structure and (has_continuation_cue or has_analysis_suffix_cue or placeholder_candidate)
        ):
            follow_up_mode = "optimize_same_structure"

    basis_match = _FOLLOW_UP_BASIS_RE.search(search_text)
    if basis_match:
        basis_hint = basis_match.group(1)

    method_signal = bool(
        re.search(
            r"\b(method|functional|xc)\b|(?:method|functional|xc)(?=[\uac00-\ud7a3])|\uba54\uc11c\ub4dc|\ud568\uc218",
            search_text,
            re.IGNORECASE,
        )
    )
    method_change_cue = bool(
        re.search(r"\b(change|switch|set|use)\b|\ubc14\uafd4|\ubcc0\uacbd|\uad50\uccb4|\uc4f0", search_text, re.IGNORECASE)
    )
    method_match = _FOLLOW_UP_METHOD_TOKEN_RE.search(search_text)
    if not method_match:
        method_match = re.search(
            r"(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|bp86|blyp|mp2|ccsd|tpssh|scan|r2scan)"
            r"(?=(?:\s|$|[.,;:!?)]|(?:\ub85c|\uc73c\ub85c|\ub97c|\uc744|\uc740|\ub294|\uacfc|\uc640|\uc5d0|\ub3c4|\ub9cc|\ubd80\ud130|\uae4c\uc9c0)))",
            search_text,
            re.IGNORECASE,
        )
    if method_match and (method_signal or method_change_cue):
        method_hint = method_match.group(1)
        follow_up_mode = "modify_parameters"

    if ("basis" in lower or "기저" in raw or "더 키워" in raw or "bigger basis" in lower):
        follow_up_mode = "modify_parameters"
    if follow_up_mode == "modify_parameters" and not (
        _looks_like_plain_molecule_name(explicit_structure_candidate) or _is_formula_like(explicit_structure_candidate)
    ):
        explicit_structure = False

    if same_structure_cue and not follow_up_mode:
        follow_up_mode = "reuse_last_structure"

    analysis_signals = set()
    if _FOLLOW_UP_ORBITAL_RE.search(search_text):
        analysis_signals.add("orbital")
    if _FOLLOW_UP_ESP_RE.search(search_text):
        analysis_signals.add("esp")
    if _FOLLOW_UP_CHARGE_RE.search(search_text):
        analysis_signals.add("charge")
    if _FOLLOW_UP_OPT_RE.search(search_text):
        analysis_signals.add("optimize")
    if basis_hint or ("basis" in lower or "기저" in raw or "더 키워" in raw or "bigger basis" in lower):
        analysis_signals.add("basis")
    if method_hint:
        analysis_signals.add("method")

    analysis_only_follow_up = bool(
        not explicit_structure
        and analysis_signals
        and (
            has_continuation_cue
            or has_analysis_suffix_cue
            or len(analysis_signals) >= 2
            or bool(_FOLLOW_UP_QUERY_CUE_RE.search(search_text))
            or placeholder_candidate
            or same_structure_cue
        )
    )
    if not follow_up_mode and analysis_only_follow_up:
        follow_up_mode = "add_analysis"

    requires_context = bool(follow_up_mode and not explicit_structure)
    if follow_up_mode == "modify_parameters" and not explicit_structure:
        requires_context = True
    return {
        "follow_up_mode": follow_up_mode,
        "job_type": job_type,
        "orbital": orbital,
        "basis_hint": basis_hint,
        "method_hint": method_hint,
        "requires_context": requires_context,
    }


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _structure_text_signature(text: str) -> str:
    token = _compact_structure_phrase(_normalize_formula_text(str(text or "").strip()))
    return re.sub(r"\s+", "", token).lower()


def _looks_like_plain_molecule_name(text: str) -> bool:
    candidate = _clean_structure_candidate(text)
    if not candidate:
        return False
    lower = candidate.lower()
    if lower in _PLAIN_MOLECULE_STOPWORDS:
        return False
    if detect_task_hint(candidate):
        return False
    if re.search(r"[가-힣]", candidate):
        return False
    if len(candidate) > 64:
        return False
    tokens = [tok for tok in re.split(r"[\s,/]+", lower) if tok]
    if not tokens or len(tokens) > 3:
        return False
    if any(tok in _PLAIN_MOLECULE_STOPWORDS for tok in tokens):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9\-\+\(\), ]+$", candidate))


def _looks_like_locant_structure_name(text: str) -> bool:
    candidate = _clean_structure_candidate(text)
    if not candidate:
        return False
    if detect_task_hint(candidate):
        return False
    if len(candidate) > 96:
        return False
    return bool(re.match(r"^\d+(?:,\d+)+(?:-[A-Za-z][A-Za-z0-9\-\+\(\), ]*|\s+[A-Za-z][A-Za-z0-9\-\+\(\), ]*)$", candidate))


def _space_korean_compounds(text: str) -> str:
    out = str(text or "")
    for ko_name in sorted(KO_TO_EN.keys(), key=len, reverse=True):
        for task in _KOREAN_TASK_TOKENS:
            out = out.replace(f"{ko_name}{task}", f"{ko_name} {task}")
    out = re.sub(r"([가-힣])([A-Za-z])", r"\1 \2", out)
    out = re.sub(r"([A-Za-z])([가-힣])", r"\1 \2", out)
    return out


def _expand_abbreviations(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return ABBREVIATION_MAP.get(token.lower(), token)

    if not text:
        return ""
    pattern = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, ABBREVIATION_MAP.keys()), key=len, reverse=True)) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return pattern.sub(repl, text)


def detect_task_hint(text: str) -> Optional[str]:
    for pattern, hint in _TASK_HINT_PATTERNS:
        if pattern.search(text or ""):
            return hint
    return None


def extract_structure_candidate(text: str) -> Optional[str]:
    raw = _normalize_formula_text(str(text or "").strip())
    if not raw:
        return None
    if is_condensed_structural_formula(raw):
        return raw

    base_analysis = analyze_structure_input(raw)
    primary_candidate = str(base_analysis.get("primary_candidate") or "").strip()
    if primary_candidate and _FOLLOW_UP_PLACEHOLDER_RE.fullmatch(primary_candidate):
        return None
    semantic_info = analyze_semantic_structure_query(raw, structure_analysis=base_analysis)

    multi_set = _extract_multi_molecule_set(raw)
    if multi_set.get("multi_molecule"):
        return None

    composite_analysis = analyze_composite_structure_input(raw)
    composite_structures = list(composite_analysis.get("structures") or [])
    if composite_analysis.get("composition_kind") in {"ion_pair", "salt"} and len(composite_structures) >= 2:
        return _format_composite_structure_query(composite_structures) or None

    if len(re.findall(r"\n", raw)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", raw, re.M):
        return raw

    locant_task_match = re.match(
        r"^\s*(\d+(?:,\d+)+(?:-[A-Za-z][A-Za-z0-9\-\+\(\), ]*|\s+[A-Za-z][A-Za-z0-9\-\+\(\), ]*))\s+"
        r"(?:homo|lumo|esp|charge|charges|mulliken|opt(?:imize|imization)?|geometry|single point(?: energy)?|singlepoint)\b",
        raw,
        re.IGNORECASE,
    )
    if locant_task_match:
        return _clean_structure_candidate(locant_task_match.group(1))

    if (
        primary_candidate
        and not _looks_like_follow_up_placeholder_candidate(primary_candidate)
        and not detect_task_hint(primary_candidate)
        and _is_plausible_structure_candidate(primary_candidate)
        and (_looks_like_plain_molecule_name(primary_candidate) or _is_formula_like(primary_candidate))
    ):
        return primary_candidate

    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw)
    if quoted:
        first = quoted[0][0] or quoted[0][1]
        if first.strip():
            analysis = analyze_structure_input(first.strip())
            if analysis.get("mixed_input") and analysis.get("primary_candidate"):
                return analysis.get("primary_candidate")
            return _clean_structure_candidate(first.strip())

    translated = _translate_korean_aliases(_space_korean_compounds(raw))

    ion_parts = re.findall(r"\b[\w]+[+\-]\b", translated)
    if len(ion_parts) >= 2:
        return _clean_structure_candidate(" ".join(ion_parts))

    patterns = [
        r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})",
        r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})\s+(?:molecule|structure|system)",
        r"(?i)([A-Za-z][A-Za-z0-9_\-\+\(\), ]{1,80}?)\s+"
        r"(?:opt(?:imize|imization)?|geometry|single point(?: energy)?|singlepoint|"
        r"energy|homo|lumo|esp|charge|charges|mulliken)\b",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
        r"(?i)(?:analyze|compute|calculate|show|render|visualize|optimize)\s+(?:the\s+)?([A-Za-z0-9_\-\+\(\), ]{2,80})",
    ]
    for pat in patterns:
        match = re.search(pat, translated, re.I)
        if not match:
            continue
        candidate = match.group(1).strip(" .,:;")
        candidate = re.split(
            r"\b(using|with|at|in|and show|and render|method|basis|charge|multiplicity|spin|preset)\b",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" .,:;")
        for noise in ["의", "에 대한", "에대한", "분자", "구조", "계산", "해줘", "보여줘"]:
            if candidate.endswith(noise):
                candidate = candidate[: -len(noise)].strip(" .,:;")
        candidate = _clean_structure_candidate(candidate)
        if candidate and (
            _FOLLOW_UP_PLACEHOLDER_RE.fullmatch(candidate)
            or _looks_like_follow_up_placeholder_candidate(candidate)
            or detect_task_hint(candidate)
        ):
            continue
        if candidate and len(candidate) >= 2:
            analysis = analyze_structure_input(candidate)
            if analysis.get("mixed_input") and analysis.get("primary_candidate"):
                return analysis.get("primary_candidate")
            return candidate

    direct_ko = _find_korean_molecule_name(raw)
    if direct_ko:
        return _clean_structure_candidate(direct_ko)

    mixed_analysis = analyze_structure_input(translated)
    if mixed_analysis.get("mixed_input") and mixed_analysis.get("primary_candidate"):
        return mixed_analysis.get("primary_candidate")

    if semantic_info.get("semantic_descriptor"):
        primary_candidate = _clean_structure_candidate(base_analysis.get("primary_candidate") or "")
        if primary_candidate and _looks_like_plain_molecule_name(primary_candidate):
            return primary_candidate
        return None

    direct_en = _clean_structure_candidate(translated)
    if direct_en and (_looks_like_plain_molecule_name(direct_en) or _looks_like_locant_structure_name(direct_en)):
        return direct_en

    common = [
        "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
        "formaldehyde", "carbon dioxide", "co2", "nh3", "h2o", "caffeine",
        "naphthalene", "biphenyl", "toluene", "phenol", "aniline", "styrene",
        "pyridine", "fluorobenzene", "benzoic acid",
    ]
    lower = translated.lower()
    for name in common:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", lower):
            return _clean_structure_candidate(name)
    return None


def normalize_text_only(text: str) -> Dict[str, str]:
    raw_text = _normalize_formula_text(str(text or "").strip())
    normalized = raw_text
    for src, dst in _EXPLICIT_TEXT_REPLACEMENTS.items():
        normalized = normalized.replace(src, dst)
    normalized = _space_korean_compounds(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    translated = _translate_korean_aliases(normalized)
    translated = re.sub(r"\s+", " ", translated).strip()

    expanded = _expand_abbreviations(translated)
    expanded = re.sub(r"\s+", " ", expanded).strip()

    return {
        "raw_text": raw_text,
        "normalized_compact_text": normalized,
        "translated_text": translated or normalized or raw_text,
        "expanded_text": expanded or translated or normalized or raw_text,
        "normalized_text": expanded or translated or normalized or raw_text,
    }


def normalize_user_text(text: str) -> Dict[str, Any]:
    text_only = normalize_text_only(text)
    raw_text = text_only["raw_text"]
    normalized = text_only["normalized_compact_text"]
    translated = text_only["translated_text"]
    expanded = text_only["expanded_text"]

    structure_hint = (
        extract_structure_candidate(raw_text)
        or extract_structure_candidate(normalized)
        or extract_structure_candidate(expanded)
    )
    composite_analysis = analyze_composite_structure_input(raw_text or expanded)
    raw_structure_analysis = analyze_structure_input(raw_text)
    hint_structure_analysis = analyze_structure_input(structure_hint or expanded)
    structure_analysis = (
        raw_structure_analysis
        if raw_structure_analysis.get("mixed_input") or raw_structure_analysis.get("direct_input_confident")
        else hint_structure_analysis
    )
    semantic_info = analyze_semantic_structure_query(raw_text or expanded, structure_analysis=raw_structure_analysis)
    structure_hypotheses = build_structure_hypotheses(
        raw_text or expanded,
        base_analysis=structure_analysis,
        translated_text=translated,
        expanded_text=expanded,
    )
    mentioned_molecules = list(structure_analysis.get("mentioned_molecules") or [])
    mentioned_names = _dedupe_keep_order(
        [str(item.get("canonical_name") or "") for item in mentioned_molecules if str(item.get("canonical_name") or "").strip()]
    )
    selection_analysis = analyze_target_selection(raw_text or expanded, mentioned_names)
    analysis_bundle = analyze_analysis_bundle(raw_text or expanded)
    task_hint = detect_task_hint(expanded) or detect_task_hint(normalized)

    extra_candidates = [
        structure_hint or "",
        _expand_abbreviations(structure_hint or ""),
    ]
    if (
        not semantic_info.get("semantic_descriptor")
        and not structure_analysis.get("mixed_input")
        and not structure_analysis.get("multi_molecule")
    ):
        extra_candidates.extend([expanded, translated])
    candidate_queries = _dedupe_keep_order(
        list(structure_hypotheses.get("candidate_queries") or [])
        + list(structure_analysis.get("canonical_candidates") or [])
        + extra_candidates
    )
    candidate_queries = [item for item in candidate_queries if _is_plausible_structure_candidate(item)]
    raw_structure_input = str(structure_analysis.get("raw_input") or raw_text or "").strip()
    if structure_analysis.get("mixed_input") and raw_structure_input:
        candidate_queries = [item for item in candidate_queries if str(item).strip().lower() != raw_structure_input.lower()]
    if structure_analysis.get("multi_molecule"):
        candidate_queries = list(structure_analysis.get("canonical_candidates") or [])
        structure_hint = None
    composite_structures = list(composite_analysis.get("structures") or [])
    if len(composite_structures) >= 2:
        candidate_queries = []
        structure_hint = None
    if semantic_info.get("semantic_descriptor"):
        raw_variants = {
            variant.lower()
            for variant in (raw_text, normalized, translated, expanded)
            if str(variant or "").strip()
        }
        raw_signatures = {
            _structure_text_signature(variant)
            for variant in (raw_text, normalized, translated, expanded)
            if _structure_text_signature(variant)
        }
        candidate_queries = [
            item
            for item in candidate_queries
            if str(item).strip().lower() not in raw_variants
            and _structure_text_signature(item) not in raw_signatures
        ]
        maybe_hint = (
            structure_hypotheses.get("primary_candidate")
            if _is_plausible_structure_candidate(structure_hypotheses.get("primary_candidate"))
            else None
        ) or structure_analysis.get("primary_candidate")
        if (
            not maybe_hint
            or str(maybe_hint).strip().lower() in raw_variants
            or _structure_text_signature(maybe_hint) in raw_signatures
        ):
            structure_hint = None
        else:
            structure_hint = maybe_hint
    follow_up_analysis = analyze_follow_up_request(raw_text or expanded)
    query_routing = analyze_query_routing(
        raw_text or expanded,
        structure_analysis=raw_structure_analysis,
        semantic_info=semantic_info,
        follow_up_analysis=follow_up_analysis,
    )
    explicit_batch_targets = _dedupe_keep_order(
        [str(item).strip() for item in list(selection_analysis.get("selected_molecules") or []) if str(item).strip()]
    )
    if not explicit_batch_targets and selection_analysis.get("target_scope") == "all_mentioned":
        explicit_batch_targets = list(mentioned_names)
    if len(explicit_batch_targets) >= 2:
        query_routing = dict(query_routing)
        query_routing["query_kind"] = "compute_ready"
        query_routing["semantic_grounding_needed"] = False
        query_routing["reasoning_notes"] = [
            note
            for note in list(query_routing.get("reasoning_notes") or [])
            if "requires grounding" not in str(note)
        ]
        query_routing["reasoning_notes"] = _dedupe_keep_order(
            list(query_routing.get("reasoning_notes") or [])
            + ["explicit multi-molecule selection overrides semantic grounding"]
        )

    canonical_terms = []
    for token in re.findall(r"[A-Za-z0-9+\-]+", expanded):
        mapped = ABBREVIATION_MAP.get(token.lower())
        if mapped:
            canonical_terms.append(mapped)
    canonical_terms = _dedupe_keep_order(canonical_terms)

    canonical_candidates = [
        item
        for item in (
            [
                item
                for item in _dedupe_keep_order(
                    list(structure_hypotheses.get("candidate_queries") or [])
                    + list(structure_analysis.get("canonical_candidates") or [])
                )
                if _is_plausible_structure_candidate(item)
                and (not raw_structure_input or not structure_analysis.get("mixed_input") or str(item).strip().lower() != raw_structure_input.lower())
            ] if len(composite_structures) < 2 else []
        )
    ]
    if semantic_info.get("semantic_descriptor"):
        raw_variants = {
            variant.lower()
            for variant in (raw_text, normalized, translated, expanded)
            if str(variant or "").strip()
        }
        raw_signatures = {
            _structure_text_signature(variant)
            for variant in (raw_text, normalized, translated, expanded)
            if _structure_text_signature(variant)
        }
        canonical_candidates = [
            item
            for item in canonical_candidates
            if str(item).strip().lower() not in raw_variants
            and _structure_text_signature(item) not in raw_signatures
            and (_looks_like_plain_molecule_name(item) or _is_formula_like(item))
        ]
    if query_routing.get("chat_only"):
        candidate_queries = [
            item
            for item in candidate_queries
            if (_looks_like_plain_molecule_name(item) or _is_formula_like(item))
        ]
        canonical_candidates = [
            item
            for item in canonical_candidates
            if (_looks_like_plain_molecule_name(item) or _is_formula_like(item))
        ]
        if structure_hint and not (_looks_like_plain_molecule_name(structure_hint) or _is_formula_like(structure_hint)):
            structure_hint = None
    if query_routing.get("query_kind") == "grounding_required" and query_routing.get("unknown_acronyms"):
        banned = {str(item).strip().lower() for item in list(query_routing.get("unknown_acronyms") or []) if str(item).strip()}
        candidate_queries = [
            item for item in candidate_queries if str(item).strip().lower() not in banned
        ]
        canonical_candidates = [
            item for item in canonical_candidates if str(item).strip().lower() not in banned
        ]
        if structure_hint and str(structure_hint).strip().lower() in banned:
            structure_hint = None

    if follow_up_analysis.get("follow_up_mode"):
        candidate_queries = [
            item for item in candidate_queries if not _looks_like_follow_up_placeholder_candidate(item)
        ]
        canonical_candidates = [
            item for item in canonical_candidates if not _looks_like_follow_up_placeholder_candidate(item)
        ]
        if structure_hint and _looks_like_follow_up_placeholder_candidate(structure_hint):
            structure_hint = None

    resolved_hint = None
    for candidate in [
        structure_hypotheses.get("primary_candidate"),
        structure_analysis.get("primary_candidate"),
        structure_hint,
    ]:
        if _looks_like_follow_up_placeholder_candidate(str(candidate or "")):
            continue
        if _is_plausible_structure_candidate(str(candidate or "")):
            resolved_hint = candidate
            break

    return {
        "raw_text": raw_text,
        "normalized_text": expanded or translated or normalized or raw_text,
        "translated_text": translated or normalized or raw_text,
        "candidate_queries": candidate_queries,
        "canonical_terms": canonical_terms,
        "maybe_structure_hint": None if semantic_info.get("semantic_descriptor") or query_routing.get("chat_only") or structure_analysis.get("multi_molecule") or len(composite_structures) >= 2 or follow_up_analysis.get("requires_context") else resolved_hint,
        "maybe_task_hint": task_hint,
        "raw_input": structure_analysis.get("raw_input") or raw_text,
        "formula_mentions": list(structure_analysis.get("formula_mentions") or []),
        "alias_mentions": list(structure_analysis.get("alias_mentions") or []),
        "canonical_candidates": canonical_candidates,
        "mixed_input": bool(structure_analysis.get("mixed_input")),
        "condensed_formula": bool(structure_analysis.get("condensed_formula")),
        "multi_molecule": bool(structure_analysis.get("multi_molecule")),
        "mentioned_molecules": mentioned_molecules,
        "raw_segments": list(structure_analysis.get("raw_segments") or []),
        "target_scope": selection_analysis.get("target_scope"),
        "selection_mode": selection_analysis.get("selection_mode"),
        "selection_hint": selection_analysis.get("selection_hint"),
        "selected_molecules": list(selection_analysis.get("selected_molecules") or []),
        "analysis_bundle": analysis_bundle,
        "batch_request": len(selection_analysis.get("selected_molecules") or []) > 1,
        "structures": list(composite_analysis.get("structures") or []),
        "composition_kind": composite_analysis.get("composition_kind"),
        "charge_hint": composite_analysis.get("charge_hint"),
        "component_names": list(composite_analysis.get("component_names") or []),
        "follow_up_mode": follow_up_analysis.get("follow_up_mode"),
        "follow_up_job_type": follow_up_analysis.get("job_type"),
        "follow_up_orbital": follow_up_analysis.get("orbital"),
        "follow_up_basis_hint": follow_up_analysis.get("basis_hint"),
        "follow_up_method_hint": follow_up_analysis.get("method_hint"),
        "follow_up_requires_context": bool(follow_up_analysis.get("requires_context")),
        "structure_confidence": float(structure_hypotheses.get("confidence") or 0.0),
        "structure_needs_clarification": bool(structure_hypotheses.get("needs_clarification")),
        "structure_reasoning_notes": list(structure_hypotheses.get("reasoning_notes") or []),
        "structure_suspicious_input": bool(structure_hypotheses.get("suspicious_input")),
        "semantic_descriptor": bool(semantic_info.get("semantic_descriptor")),
        "semantic_query_mode": semantic_info.get("query_mode"),
        "semantic_reasoning_notes": list(semantic_info.get("reasoning_notes") or []),
        "query_kind": query_routing.get("query_kind"),
        "chat_only": bool(query_routing.get("chat_only")),
        "semantic_grounding_needed": bool(query_routing.get("semantic_grounding_needed")),
        "question_like": bool(query_routing.get("question_like")),
        "explicit_compute_action": bool(query_routing.get("explicit_compute_action")),
        "unknown_acronyms": list(query_routing.get("unknown_acronyms") or []),
        "routing_reasoning_notes": list(query_routing.get("reasoning_notes") or []),
    }
