# QCViz v3 Structure Recognition and Clarification Issue Dossier

## 목적

이 문서는 현재 QCViz v3에서 발생하는 `분자명 인식`, `structure clarification`, `후보 추천`, `직접 입력 vs 추천 목록` 문제를 코드 단위로 정리한 내부 문제정의 문서다.  
핵심 관심사는 다음과 같다.

- 사용자가 이미 분자명을 명확하게 입력했는데도 구조가 인식되지 않고 clarification으로 떨어지는 문제
- clarification에 들어갔을 때 추천 목록이 입력과 무관한 generic molecule로 채워지는 문제
- 추천 목록이 resolver-grounded 하지 않고 LLM/generic fallback에 의존하는 구조
- 사용자가 입력한 raw molecule name을 system이 보존하지 못하고 중간 heuristic에서 덮어쓰는 문제
- `image upload`, `image-based fallback`, `attachment-based rescue` 같은 경로는 이번 문제 해결 범위에서 제외해야 한다는 점

이번 문서의 결론은 단순하다.

> 이 문제는 이미지로 때우는 문제가 아니라,  
> `text-based molecule recognition -> resolver-grounded candidate generation -> minimal clarification`  
> 의 설계 문제다.

---

## 문제 요약

현재 구조에서는 `Biphenyl`, `fluorobenzene`, `benzoic acid` 같은 비교적 명확한 영문 분자명도 경우에 따라 바로 계산으로 가지 못하고 clarification으로 떨어질 수 있다. 그리고 clarification에 들어간 뒤에도 추천 목록이 입력과 의미적으로 가까운 후보 대신 `water`, `methane`, `ethanol`, `benzene` 같은 generic 분자들로 채워질 수 있다. 이건 사용자가 보기에는 “내 입력을 못 알아들었고, fallback도 엉뚱하다”로 느껴진다.

이 UX는 특히 다음 상황에서 치명적이다.

- 사용자는 이미 명확한 molecule name을 알고 입력했다.
- 시스템은 그 이름을 바로 resolver에 넘기지 않았다.
- clarification이 떠도 후보가 raw input 보존이 아니라 generic 추천으로 나온다.
- 사용자는 시스템이 chemistry-aware 하지 않다고 느낀다.

즉, 문제의 본질은 “LLM이 똑똑하지 않다”가 아니라 `clarification 이전 단계의 routing`과 `clarification candidate sourcing`이 잘못 설계되어 있다는 점이다.

---

## 사용자 관점에서 보이는 실패 양상

### 1. 명확한 분자명을 넣었는데도 추가 질문이 뜬다

예:

- `Biphenyl`
- `Biphenyl HOMO`
- `fluorobenzene esp`
- `benzoic acid optimize`

기대 동작:

- structure_query를 바로 해당 분자명으로 잡는다.
- job_type만 파싱하고 즉시 resolver 또는 compute로 넘어간다.
- 꼭 필요한 정보가 비어 있을 때만 clarification을 띄운다.

실제 문제:

- 일부 케이스는 `no_structure`로 분류된다.
- 그 결과 `structure_choice + structure_custom` clarification이 뜬다.

### 2. clarification 후보가 입력과 상관없다

예:

- 입력: `Biphenyl`
- 후보: `water`, `methane`, `ethanol`, `benzene`, `custom`

이건 사용자가 “system이 내 입력을 제대로 읽지도 않았다”고 느끼게 만든다.

### 3. 추천 목록이 resolver 기반이 아니라 generic fallback 기반이다

현재 추천 후보는 크게 두 소스에서 온다.

- local hardcoded suggestions
- `QCVizAgent.suggest_molecules()`의 Gemini 기반 제안

문제는 둘 다 `resolver-grounded verification`이 없다는 점이다.  
즉 “지금 사용자가 입력한 문자열과 가장 가까운 실제 분자 후보”가 아니라 “설명에 어울릴 법한 분자”가 나온다.

---

## 현재 관련 코드 경로

핵심 관련 파일:

- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/llm/agent.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/web/routes/compute.py`
- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`

이번 문제의 직접 원인은 특히 아래 세 파일에 집중되어 있다.

- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/agent.py`

---

## 코드 블록별 현황

### A. `extract_structure_candidate()` in `llm/normalizer.py`

현재 구조 후보 추출은 여기서 시작한다.

```python
def extract_structure_candidate(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw:
        return None

    if len(re.findall(r"\n", raw)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", raw, re.M):
        return raw

    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw)
    if quoted:
        first = quoted[0][0] or quoted[0][1]
        if first.strip():
            return _clean_structure_candidate(first.strip())

    translated = _translate_korean_aliases(_space_korean_compounds(raw))
```

그리고 패턴 매칭, 공통 분자명 목록, bare English fallback이 뒤따른다.

```python
    direct_en = _clean_structure_candidate(translated)
    if direct_en and _looks_like_plain_molecule_name(direct_en):
        return direct_en

    common = [
        "water", "methane", "ammonia", "benzene", "ethanol", "acetone",
        "formaldehyde", "carbon dioxide", "co2", "nh3", "h2o", "caffeine",
        "naphthalene", "biphenyl", "toluene", "phenol", "aniline", "styrene",
        "pyridine", "fluorobenzene", "benzoic acid",
    ]
```

문제:

- bare English molecule detection이 heuristic에 의존한다.
- resolver success/failure를 보기 전에 “looks like molecule” 같은 local rule로 구조를 판정한다.
- known/common list와 pattern match가 늘수록 유지보수성이 떨어진다.
- IUPAC/functionalized/aromatic 계열 확장이 hardcoded 방향으로 흘러간다.

즉, 여기서는 “구조 후보를 뽑는 정도”까지만 해야지, “이게 실제 molecule인지 거의 최종 판정”까지 맡기면 안 된다.

---

### B. `_looks_like_molecule()` in `web/routes/chat.py`

현재 ambiguity 판단에서 구조명처럼 보이는지 확인할 때 사용한다.

```python
def _looks_like_molecule(query: str) -> bool:
    if not query:
        return False
    korean_chars = sum(1 for c in query if '\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163')
    if korean_chars > len(query) * 0.3:
        return False
    if re.match(r'^[A-Za-z][A-Za-z0-9()\[\]\-+.,\s#=\\/]*$', query.strip()):
        return True
    if re.match(r'^[A-Z][a-z]?\d*', query.strip()):
        return True
    return False
```

문제:

- 너무 느슨한 부분과 너무 거친 부분이 동시에 있다.
- “영문처럼 보이면 molecule” 쪽으로 기울어질 수 있고,
- 반대로 한국어가 조금 섞이면 false가 나서 `no_structure`로 빠질 수 있다.
- 실제 chemistry vocabulary/alias/resolver availability와 연결돼 있지 않다.

즉 이 함수는 “molecule-like text” 판정일 뿐인데, 현재 흐름에서는 사실상 structure handling 정책을 좌우한다.

---

### C. `_detect_ambiguity()` in `web/routes/chat.py`

clarification을 띄울지 결정하는 핵심 분기다.

```python
def _detect_ambiguity(plan: Dict[str, Any], prepared: Dict[str, Any], raw_message: str) -> List[str]:
    reasons: List[str] = []
    confidence = float(plan.get("confidence", 0.0))
    query = _safe_str(prepared.get("structure_query"))
    missing_slots = _current_missing_slots(plan, prepared)

    if confidence < CONFIDENCE_THRESHOLD and not missing_slots:
        reasons.append("low_confidence")

    tokens = [t for t in re.split(r"[\s,;/]+", query) if len(t) > 1]
    if query and "structure_query" not in missing_slots and _looks_like_molecule(query) and len(tokens) >= 2 and not any(c in query for c in "+-"):
        reasons.append("multiple_molecules")

    if "structure_query" in missing_slots:
        reasons.append("no_structure")
    elif query and not _looks_like_molecule(query):
        reasons.append("no_structure")
```

문제:

- whitespace token 수가 많으면 `multiple_molecules`로 흘러가기 쉽다.
- `benzoic acid`, `carbon dioxide`, `ethyl methyl carbonate` 같은 정상 분자명이 다중 분자처럼 오해될 수 있다.
- resolver/MolChat에서 실제 resolve 가능한지를 보기 전에 token heuristic으로 ambiguity를 판단한다.

즉, `ambiguity detection`이 resolver-aware 하지 않다.

---

### D. `_build_clarification_fields()` in `web/routes/chat.py`

현재 structure clarification 후보를 만드는 부분이다.

```python
if "no_structure" in reasons and "structure_choice" not in asked:
    from qcviz_mcp.web.routes.compute import get_qcviz_agent
    agent = get_qcviz_agent()
    suggestion_seed = extract_structure_candidate(raw_message) or query or raw_message
    local_suggestions = _local_structure_suggestions(suggestion_seed)
    gemini_suggestions: List[Dict[str, Any]] = []
    if agent and hasattr(agent, 'suggest_molecules'):
        try:
            gemini_suggestions = agent.suggest_molecules(raw_message)
        except Exception:
            pass
    suggestions = _merge_structure_suggestions(local_suggestions, gemini_suggestions)
```

그리고 fallback은 여전히 hardcoded다.

```python
if not options:
    options = [
        ClarificationOption(value="biphenyl", label="biphenyl — 입력한 이름 그대로 사용"),
        ClarificationOption(value="benzene", label="벤젠 (C6H6, 12 atoms)"),
        ClarificationOption(value="methane", label="메탄 (CH4, 5 atoms)"),
        ClarificationOption(value="water", label="물 (H2O, 3 atoms)"),
        ClarificationOption(value="ethanol", label="에탄올 (C2H5OH, 9 atoms)"),
    ]
```

문제:

- local suggestions가 chemistry ontology라기보다 hand-picked aromatic examples다.
- Gemini suggestions는 설명형 suggestion이지 resolver-grounded candidate가 아니다.
- fallback이 여전히 generic chemistry set이라 사용자 입력과 관련 없을 수 있다.
- `custom`이 항상 마지막에 붙지만, 실제로는 raw input을 그냥 유지하는 옵션이 더 중요하다.

즉, clarification candidate sourcing이 chemistry backend 기반이 아니라 UI fallback 중심으로 설계돼 있다.

---

### E. `suggest_molecules()` in `llm/agent.py`

현재 Gemini suggestion helper:

```python
def suggest_molecules(self, description: str) -> List[Dict[str, str]]:
    prompt = f"""You are a chemistry expert. The user described a molecule they want:
"{description}"

Suggest exactly 5 specific molecules that match this description.
...
Return ONLY the JSON array, nothing else."""
```

fallback:

```python
return [
    {"name": "water", "formula": "H2O", "atoms": 3, "description": "물 — 3 atoms"},
    {"name": "methane", "formula": "CH4", "atoms": 5, "description": "메탄 — 5 atoms"},
    {"name": "ethanol", "formula": "C2H5OH", "atoms": 9, "description": "에탄올 — 9 atoms"},
    {"name": "methanol", "formula": "CH3OH", "atoms": 6, "description": "메탄올 — 6 atoms"},
    {"name": "benzene", "formula": "C6H6", "atoms": 12, "description": "벤젠 — 12 atoms"},
]
```

문제:

- 이 함수는 vague molecule discovery용이면 괜찮지만,
- 현재는 structure clarification candidate sourcing에도 섞여 들어간다.
- 즉 “정확히 뭘 입력했는지 모를 때의 분자 추천기”가 “내 입력과 가장 가까운 분자 후보 생성기” 역할까지 떠안고 있다.

이건 역할이 다르다.

---

## 현재 설계의 핵심 문제

### 1. Recognition과 Clarification Suggestion이 분리되지 않았다

현재 시스템은 아래 두 문제를 같은 방식으로 다룬다.

- 사용자가 vague description만 준 경우  
  예: `대표적인 5원자 분자`
- 사용자가 explicit molecule name을 줬지만 system이 자신 없어하는 경우  
  예: `Biphenyl`

이 둘은 UX와 backend 처리 전략이 완전히 달라야 한다.

### 2. Resolver-grounded 후보 생성이 없다

이상적인 순서는:

1. raw text candidate 추출
2. alias normalization
3. resolver candidate probing
4. success score/charge/synonym matching 기반 후보 정렬
5. 그래도 애매하면 clarification

현재는:

1. heuristic text 판정
2. generic/gemini suggestion
3. clarification

이 순서라 chemistry backend의 장점이 충분히 활용되지 않는다.

### 3. `multiple_molecules` heuristic이 token count에 너무 의존한다

`benzoic acid` 같은 2-token 이름은 정상 분자명인데도 ambiguity 로직과 긴장 관계가 있다.  
이건 white-space token 수가 아니라 `known multiword molecule`, `resolve success`, `chemical phrase likelihood`로 봐야 한다.

### 4. “입력한 이름 그대로 사용”이 1순위 정책이 아니다

사용자가 `Biphenyl`이라고 쳤으면, system은 기본적으로 이렇게 해야 한다.

- 우선 raw input 그대로 resolver에 넘긴다.
- alias/normalization을 추가 후보로 붙인다.
- 실패했을 때만 clarification한다.

즉 raw input preservation이 가장 중요하다.

### 5. 이미지 첨부/이미지 fallback은 이번 문제의 해법이 아니다

이 문제는 이미지 업로드로 우회해서 해결할 성격이 아니다.

- 사용자가 text molecule name을 명확히 입력했다.
- system이 text routing을 잘못했다.
- 그러므로 해결도 text pipeline에서 해야 한다.

명시적 제외 범위:

- image attachment fallback
- screenshot-based molecule rescue
- OCR/image-to-structure fallback

---

## 바람직한 목표 상태

### 목표 1. Explicit molecule name은 가능한 한 clarification 없이 바로 통과

예:

- `Biphenyl HOMO`
- `fluorobenzene esp`
- `benzoic acid optimize`
- `TFSI- energy`

이런 경우는 structure resolver path로 바로 가야 한다.

### 목표 2. Clarification은 “무지성 generic 추천”이 아니라 resolver-backed disambiguation이어야 한다

예:

- `biphenyl` 입력 실패 시  
  후보:
  - `biphenyl`
  - `1,1'-biphenyl`
  - `diphenyl`
  - `benzene`
  - `naphthalene`

이런 식이어야 한다.

### 목표 3. Vague discovery와 explicit clarification을 분리

- discovery mode  
  예: `대표적인 방향족 분자`
- explicit clarification mode  
  예: `Biphenyl`

이 둘은 prompt도 다르고 source도 달라야 한다.

---

## 해결 방향 가설

### 방향 A. Resolver-first clarification

clarification 후보를 Gemini fallback이 아니라 아래 우선순위로 구성:

1. raw input 그대로
2. alias-normalized form
3. MolChat resolve candidate
4. PubChem synonym/CID-based close candidate
5. 마지막에만 LLM suggestion

### 방향 B. Candidate scoring 도입

후보마다 점수를 부여:

- exact string match
- normalized exact match
- synonym hit
- formal charge consistency
- multiword molecule whitelist hit
- resolver success

그 점수 순서로 clarification 후보를 정렬.

### 방향 C. Clarification mode 분리

- `clarification_type = "disambiguation"`  
  사용자가 molecule name을 넣었는데 후보가 여러 개일 때
- `clarification_type = "discovery"`  
  사용자가 vague description만 줬을 때

현재는 둘 다 `Choose a molecule` UI로 합쳐져 있다.

### 방향 D. LLM 역할 축소 및 재배치

이번 문제에서 LLM은 아래 역할까지만 맡는 것이 적절하다.

- vague description을 explicit chemistry examples로 바꾸기
- user language 맞춤 표현
- disambiguation 질문 wording

반대로 아래 역할은 맡기면 안 된다.

- explicit molecule candidate의 1차 소스
- resolver보다 우선하는 molecule truth source

---

## 다른 LLM에게 연구시킬 때 반드시 물어봐야 할 질문

1. chemistry-aware text-to-molecule disambiguation에서 best practice는 무엇인가?
2. MolChat/PubChem 같은 resolver 앞단의 candidate generation은 어떻게 설계하는가?
3. generic suggestion fallback을 줄이고 explicit molecule names를 우선 보존하는 설계 패턴은 무엇인가?
4. multiword molecule names와 true multi-molecule queries를 어떻게 구분하는가?
5. clarification UX에서 `discovery`와 `disambiguation`을 어떻게 분리하는가?
6. charge-bearing species, ionic liquids, salts, multiword aromatic molecules를 robust하게 다루는 규칙은 무엇인가?
7. LLM을 molecule recommender가 아니라 orchestration layer로 제한하려면 어떤 architecture가 적절한가?

---

## 요구사항 요약

다음 조건은 반드시 지켜야 한다.

- 이미지 fallback은 고려하지 않는다.
- text pipeline만 다룬다.
- resolver-backed architecture를 우선한다.
- raw user input preservation을 최우선으로 둔다.
- generic fallback molecules는 최소화한다.
- vague discovery와 explicit disambiguation을 분리한다.

---

## 참고 파일

- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/agent.py`
- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`

