# QCViz + MolChat 챗봇 유연성 하드닝 최종 패치 설계서

작성 기준: 2026-03-29  
검토 범위: 사용자 첨부 마크다운 지시문, QCViz bundle, MolChat bundle, 번들 내 기존 deep scan/patch docs, 공식 웹 문서(OpenAI / MCP / PubChem / RDKit)

---

## 0. 검토 범위와 전제

이번 결과물은 단순 의견서가 아니라 **실제 구현에 바로 착수할 수 있는 패치 설계서**다.

실제 확인한 핵심 파일은 아래다.

### QCViz
- `qcviz/src/qcviz_mcp/llm/agent.py`
- `qcviz/src/qcviz_mcp/llm/normalizer.py`
- `qcviz/src/qcviz_mcp/llm/schemas.py`
- `qcviz/src/qcviz_mcp/services/molchat_client.py`
- `qcviz/src/qcviz_mcp/services/structure_resolver.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`
- `qcviz/src/qcviz_mcp/web/routes/compute.py`
- `qcviz/src/qcviz_mcp/web/static/chat.js`
- 관련 unit / integration / playwright test 파일

### MolChat
- `molchat/backend/app/routers/molecules.py`
- `molchat/backend/app/routers/chat.py`
- `molchat/backend/app/services/molecule_engine/query_resolver.py`
- `molchat/backend/app/services/molecule_engine/orchestrator.py`
- `molchat/backend/app/services/molecule_engine/pug_rest_resolver.py`
- `molchat/backend/app/schemas/molecule.py`
- `molchat/backend/app/schemas/chat.py`

### 번들 한계
- `qcviz/src/qcviz_mcp/web/conversation_state.py`, `auth_store.py`, `session_auth.py` 등 일부 의존 파일은 번들에 포함되지 않았다.
- `molchat/backend/app/services/intelligence/agent.py` 실제 구현은 번들에 없고, `routers/chat.py` import 흔적만 존재한다.

따라서 아래 설계는 **포함된 코드 경로 기준의 확정 분석 + 누락된 구현에 대한 안전한 인터페이스 설계**를 결합한 최종안이다.

---

## 1. Executive Diagnosis

### 1-1. 왜 지금 시스템이 챗봇처럼 느껴지지 않는가

핵심 이유는 단순하다.

현재 QCViz는 **대화 라우팅보다 계산 준비를 우선하는 구조**다. 사용자의 발화가 들어오면,

1. planner/normalizer가 구조 후보를 뽑고,
2. chat route와 compute route가 그 후보를 바탕으로 clarification 또는 job submission을 준비하고,
3. 구조가 명확하지 않아도 “질문”을 “계산 준비 중인 구조 입력”으로 해석하려는 경향이 강하다.

즉, 시스템의 기본 mental model이

- “사용자는 분자를 말하려고 한다”
- “분자명만 추출하면 계산으로 넘어갈 수 있다”

에 가깝고,

- “사용자는 설명을 원할 수도 있다”
- “사용자는 아직 구조를 고르지 않았을 수도 있다”
- “약어의 뜻부터 묻는 것일 수도 있다”

라는 챗봇적 해석이 기본값이 아니다.

### 1-2. 가장 치명적인 구조적 문제

가장 큰 구조적 결함은 **intent classification과 entity grounding이 분리되지 않은 채, compute payload preparation 단계까지 연결되어 있다는 점**이다.

현재는 다음이 한 덩어리처럼 붙어 있다.

- 질문/설명 요청 판별
- 구조 후보 추출
- ambiguity 판정
- clarification form 생성
- continuation context 재사용
- 최종 compute payload 생성

이 때문에 상위 단계에서 한 번만 잘못 해석해도, 하위 단계가 그 잘못된 해석을 강화한다.

예를 들어:

- planner가 `intent=analyze` 로 시작
- normalizer가 애매한 structure hint를 남김
- `_merge_plan_into_payload()` 가 이를 payload에 반영
- `_prepare_payload()` 가 fallback extraction을 다시 수행
- resolver가 raw-like query를 후보로 재사용
- clarification UI가 그 후보를 사람에게 다시 보여줌

즉, **오염된 raw question이 파이프라인 전체를 따라 계속 살아남는 구조**다.

### 1-3. 가장 치명적인 heuristic 문제

가장 위험한 heuristic은 두 가지다.

#### A. `QCVizAgent._heuristic_plan()` 의 기본 intent가 `analyze`
`agent.py` 를 보면 heuristic planner는 시작값을 `intent = "analyze"` 로 둔다. 이후 ESP/HOMO/전하/최적화/구조/에너지 같은 키워드가 있으면 더 구체적인 compute intent로 바꾸지만, **질문형/설명형 요청을 `chat` 으로 내리는 분기 자체가 없다.**

따라서 `MEA 알아?` 같은 입력은 compute keyword가 없더라도 결국 `analyze` 로 남는다.

#### B. downstream fallback이 raw 질문을 다시 구조 후보로 살린다
`normalize_user_text()` 와 `build_structure_hypotheses()` 는 semantic descriptor인 경우 raw phrase를 제거하려고 노력한다. 이 부분은 이미 개선되어 있다. 하지만 그 아래 레이어인

- `_explicit_structure_attempt()`
- `_merge_plan_into_payload()`
- `_prepare_payload()`
- `StructureResolver.suggest_candidate_queries()`

가 raw-like 후보를 다시 살리거나 높은 순위로 밀어 올린다.

즉, **normalizer 단독으로는 문제를 해결할 수 없고, router/payload/resolver 전부가 같은 contract를 공유해야 한다.**

### 1-4. 왜 MolChat을 붙였는데도 여전히 경직적인가

MolChat 자체는 생각보다 준비가 잘 되어 있다.

- `/molecules/resolve`: exact name → CID
- `/molecules/search`: 검색 결과
- `/molecules/interpret`: semantic descriptor → grounded candidates
- `/chat`: conversational agent entrypoint
- `QueryResolver.classify_query_mode()` 는 semantic descriptor와 direct name을 구분
- `QueryResolver.interpret_candidates()` 는 semantic descriptor면 LLM candidates를 생성
- `MoleculeOrchestrator.interpret_candidates()` 는 candidate names를 다시 PubChem으로 검증해 grounded response를 반환

문제는 **QCViz가 MolChat을 1급 grounding 엔진이 아니라 2급 resolver backend처럼 쓰고 있다는 점**이다.

현재 QCViz의 실제 계산 경로는 대부분 아래 수준에 머문다.

- `resolve(names)`
- `get_card(q)`
- `generate_3d_sdf(smiles)`

`interpret_candidates()` 는 clarification/semantic discovery 쪽에서만 제한적으로 쓰고 있고, `/chat` 은 아예 QCViz client에 연결되어 있지 않다. 즉 **MolChat의 대화형 분자 grounding 능력이 상위 orchestration contract에 반영되지 않는다.**

### 1-5. 최종 진단 한 줄

현재 실패의 본질은 alias 부족이 아니라 다음이다.

> **QCViz가 “질문 → grounding → clarification → structure lock → compute”의 다단계 챗봇 구조가 아니라, “질문 → 구조 추출 → 계산 준비” 구조로 설계되어 있기 때문에, MolChat을 붙여도 결국 계산기처럼만 동작한다.**

---

## 2. Failure Taxonomy

## 2-1. Chat-vs-compute intent confusion

### Trigger
- `MEA알아?`
- `HOMO가 뭐야?`
- `니트로 벤젠 알아?`

### Root cause
- heuristic planner 기본값이 `analyze`
- question/explanation intent를 `chat` 으로 강등하는 deterministic 분기 부재
- planner 결과가 compute payload path로 바로 연결됨

### Affected files
- `qcviz/src/qcviz_mcp/llm/agent.py`
- `qcviz/src/qcviz_mcp/web/routes/compute.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`

### Why trust breaks
사용자는 질문을 했는데 시스템은 “계산하려는 구조 입력”으로 받아들인다. 한 번 이 신호가 뒤틀리면, 이후 clarification도 자연스럽지 않다.

---

## 2-2. Raw question promotion bug

### Trigger
- `MEA 알아?`
- `TNT에 들어가는 주물질`
- `이거 뭐야?`

### Root cause
- normalizer가 일부 semantic_descriptor case를 방어하지만,
- `_merge_plan_into_payload()` / `_prepare_payload()` 의 fallback extraction,
- `_explicit_structure_attempt()` 의 permissive candidate list,
- `StructureResolver.suggest_candidate_queries()` 의 raw-first ranking이 raw text를 다시 후보화한다.

### Affected files
- `qcviz/src/qcviz_mcp/llm/normalizer.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`
- `qcviz/src/qcviz_mcp/web/routes/compute.py`
- `qcviz/src/qcviz_mcp/services/structure_resolver.py`

### Why trust breaks
사용자는 “내 질문을 이해하지 못하고 문장을 그대로 분자명으로 던진다”고 느낀다. 이 순간 챗봇 신뢰는 크게 떨어진다.

---

## 2-3. Acronym ambiguity mishandling

### Trigger
- `MEA`
- `MEA의 HOMO 보여줘`
- `DMA`, `TNT`

### Root cause
- acronym-only 입력에 대한 별도 ambiguity state 없음
- planner는 structure slot을 빨리 채우려 하고,
- resolver는 가능한 해석 중 하나로 진행하거나 clarification이 late-stage에서만 발생
- “설명형 acronym query” 와 “계산형 acronym query”의 처리 정책이 다르지 않다.

### Affected files
- `qcviz/src/qcviz_mcp/llm/agent.py`
- `qcviz/src/qcviz_mcp/llm/normalizer.py`
- `molchat/backend/app/services/molecule_engine/query_resolver.py`
- `molchat/backend/app/services/molecule_engine/orchestrator.py`

### Why trust breaks
약어는 실험실 문맥에 따라 의미가 달라지는데, 시스템이 이를 모른 척하면 결과보다 먼저 UX가 깨진다.

---

## 2-4. Semantic grounding fallback failure

### Trigger
- `TNT에 들어가는 주물질`
- `리튬이온전지 전해질에 많이 쓰는 용매`
- `아세트산이 들어간 대표 분자`

### Root cause
- MolChat `/interpret` 가 있으나 상위 contract에서 1급 경로가 아님
- semantic grounding 결과와 compute-ready 구조가 같은 필드(`structure_query`)에 섞일 수 있음
- interpret 실패 시 generic fallback 또는 local suggestion이 섞여 relevance가 흐려짐

### Affected files
- `qcviz/src/qcviz_mcp/services/molchat_client.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`
- `molchat/backend/app/routers/molecules.py`
- `molchat/backend/app/services/molecule_engine/query_resolver.py`
- `molchat/backend/app/services/molecule_engine/orchestrator.py`

### Why trust breaks
semantic query는 “후보를 제시하고 고르게 해주는 것”이 핵심인데, irrelevant generic suggestion이 끼면 시스템이 엉뚱한 후보를 뿌리는 것처럼 보인다.

---

## 2-5. Clarification UX failure

### Trigger
- `MEA의 HOMO 보여줘`
- `같은 분자 ESP도`
- follow-up but no locked context

### Root cause
- clarification reason/state가 분자 ambiguity, semantic grounding, continuation targeting, parameter completion으로 깔끔히 분리되지 않음
- 카드 생성과 session state 저장은 있으나, backend route state와 UI event contract가 완전히 분리되어 있지 않음

### Affected files
- `qcviz/src/qcviz_mcp/web/routes/chat.py`
- `qcviz/src/qcviz_mcp/web/static/chat.js`
- 번들 외 세션 상태 파일들

### Why trust breaks
“왜 지금 이걸 묻는지”가 명확해야 사용자가 따라온다. 설명이 아니라 계산 slot form처럼 보이면 챗봇 느낌이 사라진다.

---

## 2-6. Tool/result boundary ambiguity

### Trigger
- explanation + compute mixed turns
- clarification 직후 바로 계산 시작
- `같은 분자 ESP도` 같은 follow-up

### Root cause
- planner가 intent/clarification/compute plan을 한 객체에 뒤섞어 담음
- compute route는 planner 결과를 곧바로 payload로 병합
- result explanation과 tool execution planning이 명확히 분리되지 않음

### Affected files
- `qcviz/src/qcviz_mcp/llm/schemas.py`
- `qcviz/src/qcviz_mcp/web/routes/compute.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`

### Why trust breaks
사용자는 “설명 받고 있는 중인지, 실제 계산이 이미 도는 중인지”를 분명히 알기 어렵다.

---

## 2-7. Follow-up context reuse mismatch

### Trigger
- `같은 분자 ESP도`
- `그거 basis만 더 키워봐`
- `벤젠의 HOMO 보여줘` 후 `TNT에 들어가는 주물질`

### Root cause
- continuation logic는 꽤 강하지만 “새 구조 요청인지, 이전 구조 재사용인지”의 locking contract가 약함
- `last_structure_query`, `last_resolved_name`, `last_resolved_artifact` 기반 재사용은 가능하나 turn/job binding 및 stale clarification 문제와 결합 시 contamination 위험 존재

### Affected files
- `qcviz/src/qcviz_mcp/web/routes/compute.py`
- `qcviz/src/qcviz_mcp/web/routes/chat.py`
- 번들 내 state-integrity fix prompt에서 지적한 session/history 관련 파일들

### Why trust breaks
이전 분자의 결과가 새 질문에 섞이면 도구형 연구 시스템으로서 신뢰를 잃는다.

---

## 3. End-to-End Desired Architecture

## 3-1. 핵심 원칙

새 구조의 핵심은 이것이다.

1. **질문 해석**과 **구조 grounding**을 분리한다.
2. 구조가 lock 되기 전에는 compute plan을 submit하지 않는다.
3. MolChat은 name resolver가 아니라 **grounding engine**으로 쓴다.
4. compute engine은 항상 **구조가 lock 된 뒤**에만 호출한다.
5. explanation response와 tool result를 엄격히 구분한다.

## 3-2. 타겟 플로우

```text
User message
   │
   ▼
Turn Router
   ├─ chat_only
   │    └─ explain_only_response
   │
   ├─ grounding_required
   │    ├─ direct_name_lane
   │    │    └─ resolve / search / ambiguity check
   │    ├─ acronym_lane
   │    │    └─ disambiguation candidates
   │    └─ semantic_descriptor_lane
   │         └─ MolChat /molecules/interpret
   │
   └─ compute_candidate
        │
        ▼
Entity Grounding Manager
   ├─ structure_locked = false
   │    └─ clarification_required(candidate_list)
   └─ structure_locked = true
        │
        ▼
Compute Planner
   ├─ validate required slots
   ├─ build compute_plan
   └─ if missing params -> clarification_required(parameter_completion)
        │
        ▼
Tool Orchestrator
   ├─ resolve_structure
   ├─ run_compute
   ├─ build_visualization
   └─ explain_result
        │
        ▼
UI Renderer
   ├─ assistant chat bubble
   ├─ candidate dropdown
   ├─ job submitted
   ├─ progress stream
   └─ result card (bound to turn_id + job_id)
```

## 3-3. 구조 lock 개념

이 설계에서 가장 중요한 새로운 개념은 `structure_locked` 다.

- `structure_locked = false`
  - 아직 분자가 확정되지 않음
  - clarification/dropdown 가능
  - compute submit 금지

- `structure_locked = true`
  - canonical molecule identity가 결정됨
  - 이후 follow-up은 이 구조를 재사용 가능
  - compute plan 생성 가능

즉, 기존의 `structure_query가 있으면 일단 진행` 이 아니라,
**canonical identity가 lock 되어야 계산 가능** 으로 바뀌어야 한다.

---

## 4. Final Patch Design

## 4-1. 설계 결정

### 최종 결정
- **MolChat `/molecules/interpret` 를 semantic grounding의 1급 엔드포인트로 승격한다.**
- **MolChat `/chat` 은 dropdown 후보 생성의 기본 경로로 쓰지 않는다.**
- **QCViz 내부에서 route → grounding → compute_plan → execution 을 분리하는 상태 기계를 도입한다.**
- **현재 `PlanResponse` 는 1차 호환층으로 유지하되, 실제 운영 로직은 더 명시적인 route/grounding/compute contract를 사용하도록 바꾼다.**

---

## 4-2. QCViz 파일별 패치

### A. `qcviz/src/qcviz_mcp/llm/schemas.py`

#### 현재 문제
`PlanResponse` 하나에
- intent
- structure_query
- clarification
- missing_slots
- chat_response
- batch/selection/follow_up
가 혼합되어 있다.

이 구조는 초기 실험용으로는 편하지만, 실제 운영에서는
- chat-only 응답
- grounding-required 상태
- compute-ready 상태
를 구분하기 어렵게 만든다.

#### 변경안
기존 `PlanResponse` 는 유지하되 아래 새 모델을 추가한다.

```python
class GroundingStatus(BaseModel):
    mode: Literal["direct_name", "acronym", "semantic_descriptor", "follow_up", "none"]
    status: Literal["not_needed", "pending", "locked", "failed"]
    raw_query: str = ""
    normalized_query: Optional[str] = None
    locked_name: Optional[str] = None
    locked_cid: Optional[int] = None
    ambiguity_reason: Optional[str] = None
    candidates: List[Dict[str, Any]] = Field(default_factory=list)

class ComputePlan(BaseModel):
    job_type: str
    structure_query: Optional[str] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    ready: bool = False
    missing_slots: List[str] = Field(default_factory=list)

class TurnDecision(BaseModel):
    route_kind: Literal[
        "chat_only",
        "grounding_required",
        "compute_ready",
        "follow_up_needs_context",
    ]
    confidence: float = 0.0
    chat_response: Optional[str] = None
    grounding: GroundingStatus = Field(default_factory=GroundingStatus)
    compute_plan: Optional[ComputePlan] = None
    clarification_kind: Optional[str] = None
    notes: List[str] = Field(default_factory=list)
```

#### 호환 전략
- 기존 planner/provider는 여전히 `PlanResponse` 를 반환 가능
- `_safe_plan_message()` 에서 `PlanResponse -> TurnDecision` 변환기를 둔다
- 구형 route는 `TurnDecision.compute_plan` 기반으로 동작하도록 이행

---

### B. `qcviz/src/qcviz_mcp/llm/agent.py`

#### 현재 문제
`_heuristic_plan()` 기본 intent가 `analyze` 이다. 설명형 질문을 `chat` 으로 내리는 로직이 없다.

#### 최소 패치
`_heuristic_plan()` 시작부를 다음 원칙으로 교체한다.

1. 먼저 `question/explanation/acronym-only/semantic-descriptor/follow-up` 시그널을 판정
2. compute keyword가 없고 설명형 질문이면 `intent = "chat"`
3. acronym-only + no compute keyword면 `intent = "chat"`, `clarification_kind = "acronym_disambiguation"`
4. acronym + compute keyword면 `intent = <compute>`, `needs_clarification = True`, `clarification_kind = "acronym_disambiguation"`
5. semantic descriptor면 `intent` 는 곧바로 compute로 보내지 않고 `grounding_required`

#### 구체 구현
추가 함수:

```python
def _detect_chat_only_question(text: str, normalized: Dict[str, Any]) -> bool: ...
def _detect_acronym_ambiguity(text: str, normalized: Dict[str, Any]) -> Optional[List[str]]: ...
def _detect_compute_signal(text: str) -> Optional[str]: ...
```

#### 강제 규칙
- `compute signal` 이 없으면 기본 intent는 `chat`
- `semantic_descriptor == True` 이고 compute signal이 있어도 먼저 grounding_required
- `chat` intent에서는 `_apply_structure_hypotheses()` 가 structure_query를 강제로 주입하지 못하게 막는다.

#### 추가 수정
Gemini planner 경로도 `chat_response` 를 끝까지 보존해야 한다.
현재 `GeminiResult.to_plan_dict()` 는 `chat_response` 를 포함하지 않으므로,

```python
chat_response: Optional[str] = None
```
를 `GeminiResult` 에 추가하고 `to_plan_dict()` 에 포함시킨다.

---

### C. `qcviz/src/qcviz_mcp/llm/normalizer.py`

#### 현재 문제
normalizer 자체는 많이 개선되어 있다. 특히 semantic descriptor일 때 raw phrase를 제거하려는 방어가 이미 들어가 있다. 문제는 normalizer가 아니라 downstream이 다시 raw phrase를 살린다는 점이다.

#### 유지할 부분
- `베 ㄴ젠` 재구성
- `니트로 벤젠` → `nitrobenzene` 계열 재구성
- semantic_descriptor 감지
- multi_molecule/composite 분석
- `structure_needs_clarification`

#### 변경할 부분
1. acronym-only case를 별도 표식으로 노출
2. `maybe_structure_hint` 를 더 보수적으로 설정
3. question marker가 남아 있는 경우 low-confidence hint를 explicit flag로 내려줌

새 필드 제안:

```python
"acronym_only": bool,
"acronym_candidates": List[str],
"question_like": bool,
"grounding_lane": Literal["direct_name", "semantic_descriptor", "acronym", "follow_up", "none"],
```

#### 정책
- `MEA` 같이 짧은 uppercase token은 direct molecule candidate로 확정하지 않는다.
- acronym-only + no compute keyword -> `grounding_lane="acronym"`, `maybe_structure_hint=None`
- acronym + compute keyword -> `grounding_lane="acronym"`, `candidate_queries=[]`, clarification으로 넘긴다.

---

### D. `qcviz/src/qcviz_mcp/services/molchat_client.py`

#### 현재 문제
QCViz는 MolChat `/resolve`, `/search`, `/interpret`, `/card`, `/generate-3d` 는 사용하지만, `/chat` client는 없다. 또한 interpret 결과는 UI fallback utility처럼만 취급된다.

#### 최소 패치
`MolChatClient` 에 아래를 추가한다.

```python
async def chat(self, message: str, session_id: Optional[str] = None, context: Optional[dict] = None) -> Dict[str, Any]:
    ...
```

다만 **기본 운영 경로에서는 `/chat` 을 dropdown candidate source로 쓰지 않는다.**

#### 실제 사용 원칙
- `/molecules/interpret` : semantic descriptor grounding
- `/molecules/search` : grounded candidate 보강/verification
- `/resolve` : direct name exact resolution
- `/chat` : explain-only / extended conversational chemistry assistant 용 보조 경로

즉 `/chat` 은 candidate dropdown의 primary source가 아니라 **설명형 대화의 보조 채널**이다.

---

### E. `qcviz/src/qcviz_mcp/services/structure_resolver.py`

#### 현재 문제
resolver는 실제 계산 직전 구조를 만드는 데는 좋지만, clarification UX에 raw query가 섞일 수 있다. 특히 `suggest_candidate_queries()` 가 raw query를 `raw_exact` score 120으로 가장 높게 넣는다.

#### 최소 패치
`_build_query_plan()` 은 유지하되,
`self.suggest_candidate_queries()` 정책을 바꾼다.

##### 기존
- raw_exact 120
- translated 110
- normalized 105
- query_variant 100...

##### 변경
- semantic_descriptor / acronym ambiguity / question-like input이면 `raw_exact` 제거
- resolver suggestion은 **direct-name lane에서만** raw_exact 허용
- semantic grounding lane에서는 이 함수 대신 MolChat interpret 결과만 사용

#### 추가 규칙
- `resolve()` 는 **structure_locked 상태에서만 호출**한다.
- clarification 단계에서는 `resolve()` 가 아니라 `suggest_*` 또는 MolChat interpret만 호출한다.

즉 resolver를 **grounding tool이 아니라 execution-time structure materializer** 로 역할 축소한다.

---

### F. `qcviz/src/qcviz_mcp/web/routes/chat.py`

#### 현재 문제
이 파일이 실제로 가장 중요하다.

여기서
- `_explicit_structure_attempt()`
- `_clarification_mode()`
- `_molchat_interpret_candidates()`
- `_discovery_structure_suggestions()`
- `_prepare_or_clarify()`
- `websocket_chat()`
가 모두 얽혀 있다.

#### 현재 장점
- semantic descriptor면 `_molchat_interpret_candidates()` 를 타는 경로가 있다.
- `intent == chat` 면 websocket에서 conversational response를 보내는 분기가 있다.
- clarification session state도 이미 존재한다.

#### 핵심 결함
- planner가 잘못 intent를 주면 websocket chat branch에 도달하지 못한다.
- `_explicit_structure_attempt()` 는 permissive 하여 raw_message도 후보군에 넣는다.
- discovery fallback에 generic catalog가 섞여 semantic relevance를 흐릴 수 있다.
- `clarify` event는 있으나 candidate list와 locked structure의 상태 기계가 약하다.

#### 최종 리팩터링
새 진입 함수:

```python
async def _route_turn(body, raw_message, session_id, turn_id) -> TurnDecision: ...
async def _ground_entity(turn: TurnDecision, session_id: str) -> TurnDecision: ...
async def _build_compute_or_clarify(turn: TurnDecision, body: dict, raw_message: str) -> dict: ...
```

#### `_explicit_structure_attempt()` 수정
다음 경우에는 무조건 `None` 반환:
- `semantic_descriptor == True`
- `acronym_only == True`
- `question_like == True and compute signal absent`
- raw_message == candidate and question/task marker 존재

#### `_discovery_structure_suggestions()` 수정
- semantic lane: MolChat interpret only
- acronym lane: acronym disambiguation candidates only
- direct-name lane: local + resolver-backed suggestions
- generic fallback `[benzene, acetone, ethanol]` 제거

#### `websocket_chat()` 수정
현재는
- planner chat intent면 바로 assistant bubble
- 아니면 `_prepare_or_clarify()` -> compute path

이 구조다.
이를 아래로 바꾼다.

```python
turn = await _route_turn(...)
if turn.route_kind == "chat_only":
    send assistant
elif turn.route_kind == "grounding_required":
    send clarify(candidate_list)
elif turn.route_kind == "follow_up_needs_context":
    send clarify(target previous structure?)
elif turn.route_kind == "compute_ready":
    submit job
```

즉 websocket 레벨에서도 **compute-ready 여부**를 먼저 본다.

---

### G. `qcviz/src/qcviz_mcp/web/routes/compute.py`

#### 현재 문제
compute route는 planner 결과를 payload에 병합한 뒤, 구조가 없으면 fallback extraction을 수행한다. 이 로직이 chat-vs-compute 혼선을 확대한다.

#### 반드시 제거할 로직
다음 동작은 제거 또는 feature flag behind migration 해야 한다.

- `_merge_plan_into_payload()` 에서 raw_message fallback으로 `structure_query` 재주입
- `_prepare_payload()` 에서 planner가 clarification을 요구하지 않으면 raw_message로 structure candidate 재시도

#### 새 규칙
compute route는 아래 중 하나만 허용한다.

1. `compute_plan.ready == true` 이고 `structure_locked == true`
2. explicit XYZ / atom_spec / pre-validated structures payload

그 외에는 400이 아니라 **grounding_required response** 로 되돌려야 한다.

#### 구체 변경
- `_safe_plan_message()` 는 `TurnDecision` 반환
- `_merge_plan_into_payload()` 는 compute fields만 merge
- `_prepare_payload()` 는 structure extraction을 하지 않는다
- `_apply_session_continuation()` 은 `locked structure reuse` 만 담당한다

즉 compute route는 더 이상 “질문을 구조로 해석하는 곳”이 아니다.

---

### H. `qcviz/src/qcviz_mcp/web/static/chat.js`

#### 현재 문제
frontend는 이미 interactive card를 retire/replace 하는 함수가 있고 turn_id/job_id도 들고 있다. 하지만 backend contract가 명확하지 않아 stale clarify/result contamination을 완전히 막기 어렵다.

#### 최종 수정
1. `clarification_id` 도입
2. `candidate_list_id` 도입
3. `structure_lock_id` 도입
4. 동일 `turn_id` 의 clarify card는 append가 아니라 replace
5. result는 `turn_id + job_id` 매칭이 안 되면 active result로 승격하지 않음
6. restored history와 live stream message를 `message_id` 로 dedupe

#### label 정책
현재 MolChat rationale/confidence/CID가 description에 모두 붙는다. 기본 표시를 아래처럼 단순화한다.

- primary label: `Monoethanolamine (C2H7NO)`
- secondary text: `CID 700 / common amine solvent`
- hidden metadata: `confidence`, `rationale`, `source`

즉 dropdown은 사람이 고르기 쉽게, reasoning trace는 debug용으로 분리한다.

---

## 4-3. MolChat 파일별 패치

### A. `molchat/backend/app/schemas/molecule.py`

#### 현재 장점
`MoleculeInterpretResponse` 는 이미 semantic grounding downstream contract에 가깝다.

#### 보강안
다음 필드를 추가한다.

```python
class MoleculeInterpretCandidate(BaseModel):
    name: str
    display_name: Optional[str] = None
    cid: int | None = None
    canonical_smiles: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source: str = "semantic_llm"
    rationale: str | None = None
    match_type: Literal["direct", "alias", "typo_corrected", "semantic", "acronym"] = "semantic"
```

이렇게 하면 QCViz가 UI label simplification을 쉽게 할 수 있다.

---

### B. `molchat/backend/app/services/molecule_engine/query_resolver.py`

#### 현재 장점
- direct_name / semantic_descriptor 분리 존재
- alias / typo correction / PubChem autocomplete / LLM tier 존재

#### 현재 부족점
- acronym ambiguity가 별도 mode가 아니다.
- `MEA`, `DMA`, `TNT` 를 semantic_descriptor도 direct_name도 아닌 **ambiguous_abbreviation** 으로 다뤄야 한다.

#### 변경안
`classify_query_mode()` 를 확장한다.

```python
def classify_query_mode(self, query: str) -> str:
    if empty: return "empty"
    if acronym_ambiguous: return "ambiguous_abbreviation"
    if semantic_pattern: return "semantic_descriptor"
    return "direct_name"
```

#### `interpret_candidates()` 정책
- `ambiguous_abbreviation` 이면 LLM semantic query를 돌리지 말고 abbreviation candidate set을 반환
- 이 candidate set은 PubChem grounding을 거친 canonical molecules여야 한다.

예:

```python
MEA -> [monoethanolamine, methylethylamine, ...]
TNT -> [2,4,6-trinitrotoluene, trinitrotoluene]
```

여기서 핵심은 **abbreviation을 설명형/계산형 모두에서 공통 grounding primitive로 다루는 것**이다.

---

### C. `molchat/backend/app/services/molecule_engine/orchestrator.py`

#### 현재 장점
`interpret_candidates()` 가 candidate names를 `resolve_name_to_cid()` 로 다시 PubChem 검증한다. 이 설계는 매우 좋다.

#### 변경안
1. `query_mode == ambiguous_abbreviation` 지원
2. grounded candidate가 0개일 때 notes를 더 명시적으로 반환
3. resolution_method를 `semantic_llm+pubchem_grounding`, `abbreviation_map+pubchem_grounding` 처럼 더 구체화
4. candidate ranking을 confidence + exactness 기준으로 정렬

즉 orchestrator는 QCViz가 그대로 UI candidate list로 쓸 수 있는 품질까지 끌어올려야 한다.

---

### D. `molchat/backend/app/routers/molecules.py`

#### 현재 장점
- `/search`
- `/interpret`
- `/resolve`
이 이미 있다.

#### 변경안
기존 endpoint는 유지하고 아래를 보강한다.

1. `/interpret` request에 optional field 추가
   - `context_structure: str | None`
   - `prefer_exact_name: bool = False`
   - `mode_hint: str | None`

2. `/interpret` response에 optional field 추가
   - `query_mode`
   - `normalized_query`
   - `notes`
   - `candidates[*].match_type`
   - `candidates[*].display_name`

3. `/resolve` 는 backward compatibility용 exact lane으로 유지

이렇게 하면 QCViz는 semantic lane과 direct lane을 REST contract 수준에서 구분할 수 있다.

---

### E. `molchat/backend/app/routers/chat.py`

#### 현재 상황
chat route는 존재하지만, 실제 agent implementation이 번들에 없다. 따라서 QCViz가 여기를 1차 grounding 경로로 삼는 것은 위험하다.

#### 최종 권고
- `/chat` 은 설명형 chemistry assistant로는 유지
- **QCViz grounding UI에는 `/chat` 을 직접 쓰지 않는다**
- candidate generation은 `/interpret`
- explain-only response가 필요하면 `/chat` 또는 QCViz local chat_direct를 사용

즉 `/chat` 은 UI candidate contract가 아니라 **natural-language assistant contract** 다.

---

## 5. MCP / Tool Integration Strategy

## 5-1. 결론

**지금 당장 QCViz 전체를 외부 MCP 서버 기반으로 재설계할 필요는 없다.**

대신 내부적으로 먼저 MCP-style tool abstraction을 도입하고, 이후 remote MCP exposure는 선택적으로 추가하는 것이 맞다.

## 5-2. 이유

공식 문서 기준으로 MCP는
- JSON-RPC 기반의 stateful protocol이고,
- 서버가 resources / prompts / tools 를 제공하며,
- progress tracking / cancellation / logging / elicitation 같은 유틸리티도 중요하다.

QCViz의 현재 병목은 프로토콜 부재가 아니라 **tool boundary와 state contract 부재**다.

즉, 먼저 해야 할 일은
- 어떤 단계가 tool인지,
- 어떤 입력/출력을 받는지,
- 어떤 상태에서 clarification이 필요한지,
- 어떤 결과가 compute-ready인지
를 내부에서 고정하는 것이다.

## 5-3. 권장 tool boundary

### Tool 1: `ground_molecule`
입력:
- raw user query
- lane hint (`direct_name`, `semantic_descriptor`, `acronym`, `follow_up`)
- optional conversation context

출력:
- `semantic_grounding_result`
- `structure_locked`
- candidate list

### Tool 2: `resolve_structure_materialization`
입력:
- locked molecule name / cid / smiles

출력:
- xyz / sdf / smiles / cid / source

### Tool 3: `plan_compute`
입력:
- grounded structure
- requested analysis (`HOMO`, `ESP`, charges, optimize, ...)
- optional method/basis overrides

출력:
- `compute_plan`
- missing slots

### Tool 4: `run_compute`
입력:
- compute_plan
- resolved structure artifact

출력:
- job_id / progress / result

### Tool 5: `explain_result`
입력:
- result payload
- focus tab
- optional user question

출력:
- `tool_result` + `result_explanation`

## 5-4. MCP 적용 수준

### 단계 1
내부 Python abstraction만 도입
- FastAPI route 내부에서 위 tool contracts 사용
- 아직 remote MCP server 아님

### 단계 2
MolChat grounding을 remote MCP tool or HTTP tool로 감싼다
- `ground_molecule` 만 MCP化 가능

### 단계 3
compute backend도 MCP server 化 가능
- `run_compute`, `resolve_structure_materialization`, `explain_result`

즉 당장 필요한 건 “MCP라는 이름”보다 **MCP 수준의 명시적 schema discipline** 이다.

---

## 6. API Contract Proposal

## 6-1. chat_response

```json
{
  "type": "chat_response",
  "turn_id": "turn_123",
  "route_kind": "chat_only",
  "message": "MEA는 문맥에 따라 monoethanolamine 또는 methylethylamine을 뜻할 수 있습니다.",
  "suggested_next_action": {
    "kind": "clarify_acronym",
    "choices": ["monoethanolamine", "methylethylamine"]
  }
}
```

## 6-2. clarification_required

```json
{
  "type": "clarification_required",
  "turn_id": "turn_123",
  "clarification_id": "clar_456",
  "clarification_kind": "acronym_disambiguation",
  "message": "MEA가 어떤 분자를 뜻하는지 먼저 골라주세요.",
  "fields": [
    {
      "id": "molecule_choice",
      "type": "radio",
      "label": "분자 선택",
      "required": true,
      "options": [
        {"value": "monoethanolamine", "label": "Monoethanolamine (C2H7NO)"},
        {"value": "methylethylamine", "label": "Methylethylamine (C3H9N)"}
      ]
    }
  ],
  "candidate_list_id": "cand_789"
}
```

## 6-3. candidate_list

```json
{
  "type": "candidate_list",
  "candidate_list_id": "cand_789",
  "source": "molchat_interpret",
  "query_mode": "semantic_descriptor",
  "items": [
    {
      "name": "2,4,6-trinitrotoluene",
      "display_name": "2,4,6-Trinitrotoluene (C7H5N3O6)",
      "cid": 8376,
      "match_type": "semantic",
      "confidence": 0.89,
      "secondary_text": "CID 8376"
    }
  ]
}
```

## 6-4. semantic_grounding_result

```json
{
  "type": "semantic_grounding_result",
  "query": "TNT에 들어가는 주물질",
  "query_mode": "semantic_descriptor",
  "status": "candidate_selection_required",
  "normalized_query": null,
  "resolution_method": "semantic_llm+pubchem_grounding",
  "structure_locked": false,
  "candidates": [
    {
      "name": "2,4,6-trinitrotoluene",
      "cid": 8376,
      "canonical_smiles": "CC1=C(C(=C(C(=C1)[N+](=O)[O-])[N+](=O)[O-])[N+](=O)[O-])",
      "molecular_formula": "C7H5N3O6",
      "confidence": 0.89,
      "source": "semantic_llm",
      "rationale": "대표적 TNT 구성 후보"
    }
  ],
  "notes": ["semantic candidates proposed and PubChem grounded"]
}
```

## 6-5. compute_plan

```json
{
  "type": "compute_plan",
  "turn_id": "turn_124",
  "structure_locked": true,
  "locked_structure": {
    "name": "monoethanolamine",
    "cid": 700,
    "source": "molchat_interpret"
  },
  "job_type": "orbital_preview",
  "method": "B3LYP",
  "basis": "def2-SVP",
  "charge": 0,
  "multiplicity": 1,
  "orbital": "HOMO",
  "ready": true,
  "missing_slots": []
}
```

## 6-6. tool_result

```json
{
  "type": "tool_result",
  "turn_id": "turn_124",
  "job_id": "job_001",
  "tool": "run_compute",
  "success": true,
  "result": {
    "structure_name": "monoethanolamine",
    "job_type": "orbital_preview",
    "orbital": "HOMO",
    "visualization": {
      "orbital_cube_b64": "..."
    }
  }
}
```

## 6-7. explain_only_response

```json
{
  "type": "explain_only_response",
  "turn_id": "turn_125",
  "message": "HOMO는 가장 높은 점유 분자 오비탈입니다. 전자 공여 성향 해석에 자주 사용됩니다.",
  "used_tools": []
}
```

---

## 7. UX / Conversation Policy

## 7-1. 언제 바로 대답할 것인가

다음은 바로 대답한다.

- 계산 keyword가 없는 설명형 질문
- 개념 설명 요청
- acronym meaning을 묻는 질문이지만 계산 요청이 없는 경우
- structure lock 없이도 답할 수 있는 일반 chemistry explanation

예:
- `MEA 알아?`
- `HOMO가 뭐야?`
- `ESP map이 뭔데?`

단, acronym ambiguity가 크면 설명 + 짧은 선택지를 같이 제시한다.

---

## 7-2. 언제 분자를 고르라고 물을 것인가

다음 경우는 분자 선택을 요구한다.

1. acronym-only ambiguity
2. semantic descriptor 결과가 여러 후보
3. direct name 후보가 복수로 match
4. follow-up인데 이전 structure lock이 없음

예:
- `MEA의 HOMO 보여줘`
- `TNT에 들어가는 주물질`
- `same molecule ESP too` but no prior lock

---

## 7-3. 언제 계산을 시작할 것인가

계산 시작 조건은 두 개다.

1. `structure_locked == true`
2. `compute_plan.ready == true`

둘 중 하나라도 false이면 계산 금지.

이 규칙은 예외 없이 적용한다.

---

## 7-4. 언제 후보 dropdown을 띄울 것인가

### 띄운다
- acronym ambiguity
- semantic descriptor candidate selection
- direct name ambiguity
- follow-up target disambiguation

### 띄우지 않는다
- 설명형 대화 only
- 구조가 이미 lock 된 동일 분자 follow-up
- direct exact name + high confidence auto-accept

---

## 7-5. acronym은 어떻게 물을 것인가

원칙:
- 후보를 2~4개로 압축
- 가장 흔한 lab-context candidate를 위에 배치
- 계산 요청이면 “어느 분자로 계산할지”를 묻고,
- 설명 요청이면 “어떤 뜻으로 쓰셨는지”를 묻는다.

예시:

### 설명형
`MEA는 보통 monoethanolamine을 뜻하지만 다른 약어일 수도 있습니다. 어떤 뜻으로 쓰셨나요?`

### 계산형
`MEA의 HOMO를 계산하려면 먼저 어떤 분자인지 정해야 합니다. 아래에서 선택해 주세요.`

---

## 7-6. semantic descriptor는 어떻게 처리할 것인가

semantic descriptor는 구조 입력이 아니라 **grounding query** 다.

따라서 정책은 아래와 같다.

1. raw phrase를 `structure_query` 로 사용하지 않는다.
2. MolChat `/interpret` 로 candidate list를 받는다.
3. grounded candidates만 dropdown에 보여준다.
4. 선택 후에만 structure lock.
5. structure lock 이후에만 compute plan 생성.

---

## 8. Test Strategy

## 8-1. Unit tests

### QCViz planner / normalizer
- `MEA알아?` -> `route_kind=chat_only` or `grounding_required`, never compute-ready
- `MEA의 HOMO 보여줘` -> `clarification_kind=acronym_disambiguation`
- `TNT에 들어가는 주물질` -> semantic_descriptor true, no raw structure promotion
- `베 ㄴ젠` -> normalized direct molecule candidate
- `니트로 벤젠` -> reconstructed direct candidate
- `같은 분자 ESP도` -> follow_up_mode detected

### Structure resolver
- semantic_descriptor queries must not get `raw_exact` ranking
- direct name queries may keep `raw_exact`
- acronym ambiguity queries must be excluded from raw structure suggestion path

### MolChat resolver/orchestrator
- `MEA` -> `ambiguous_abbreviation`
- `TNT에 들어가는 주물질` -> `semantic_descriptor`
- grounded candidate list contains only PubChem-verified candidates

---

## 8-2. API tests

### QCViz `/chat`
- `MEA알아?` returns chat/explain response, no job submit
- `MEA의 HOMO 보여줘` returns clarification_required
- `TNT에 들어가는 주물질` returns semantic candidate list
- selecting candidate then posting clarify response creates compute-ready payload

### MolChat `/molecules/interpret`
- semantic descriptor returns candidates
- acronym ambiguity returns candidates
- direct name returns direct candidate or normalized exact match

---

## 8-3. WebSocket tests

- `clarify` event contains stable `turn_id`, `clarification_id`, `candidate_list_id`
- repeated clarification replaces previous card for same turn
- `result` event only binds to matching `job_id` and `turn_id`
- follow-up without context emits clarification, not compute job

---

## 8-4. Playwright end-to-end tests

반드시 포함:

1. `MEA알아?`
2. `MEA의 HOMO 보여줘`
3. `TNT에 들어가는 주물질`
4. `니트로 벤젠`
5. `같은 분자 ESP도`
6. `벤젠의 HOMO를 보여줘` 후 전혀 다른 질문을 했을 때 이전 결과 미오염 검증

추가 권장:

7. semantic descriptor → candidate select → compute submit → result render
8. acronym disambiguation → candidate select → compute submit
9. history restore 후 clarify/result dedupe
10. stale job result arriving after new turn does not overwrite active turn

---

## 8-5. Regression assertions

### 반드시 고정할 acceptance criteria
- raw question text must never be used as final structure query for semantic/acronym questions
- compute must not start before structure lock
- follow-up without prior structure lock must not inherit unrelated job
- dropdown labels must be concise and human-readable
- result messages must not attach to wrong turn/job

---

## 9. Migration / Deployment Plan

## 9-1. 배포 순서

### Phase 0 — MolChat first, additive only
먼저 MolChat을 바꾼다.

이유:
- QCViz가 semantic grounding 1급 경로로 쓸 `/interpret` contract가 먼저 안정돼야 한다.
- acronym ambiguity support도 MolChat에서 먼저 확정하는 편이 맞다.

#### 배포 내용
- `query_mode=ambiguous_abbreviation` 추가
- `display_name`, `match_type`, `aliases` 추가
- interpret response 안정화
- backward compatible 유지

### Phase 1 — QCViz routing patch behind feature flag
`QCVIZ_CHAT_ROUTER_V2=true`

#### 배포 내용
- TurnDecision 도입
- heuristic default chat 전환
- raw fallback extraction 차단
- semantic descriptor → MolChat interpret 직결
- compute-ready only submit

### Phase 2 — Frontend clarification/result contract patch
`QCVIZ_CHAT_STATE_V2=true`

#### 배포 내용
- clarification_id / candidate_list_id / structure_lock_id
- same-turn clarification replacement
- result dedupe by turn_id + job_id
- concise labels

### Phase 3 — Cleanup legacy fallbacks
운영 안정성 확인 후 제거:
- generic discovery fallback list
- raw_exact ranking for non-direct lanes
- compute route inline extraction fallback

---

## 9-2. Backward compatibility

### MolChat
- `/search`, `/resolve`, `/card`, `/generate-3d` 유지
- `/interpret` response는 additive change만 허용

### QCViz
- 기존 `PlanResponse` 유지
- 구형 planner/provider 결과를 `TurnDecision` 으로 변환하는 adapter 제공
- legacy JS consumers가 깨지지 않도록 event 필드는 additive하게 확장

---

## 9-3. 운영 검증

### Canary metrics
- `chat_only_rate`
- `grounding_required_rate`
- `semantic_interpret_success_rate`
- `acronym_disambiguation_rate`
- `raw_question_promotion_count` (반드시 0으로 수렴)
- `clarification_rounds_per_turn`
- `wrong_turn_result_bind_count`
- `compute_started_without_lock_count` (반드시 0)

### Log probes
- route_kind
- grounding lane
- structure_locked 여부
- candidate source (`molchat_interpret`, `resolver`, `user_input`, `continuation`)
- clarification_kind
- job_id / turn_id / session_id correlation

---

## 10. File-by-File Patch Pseudo-Diff

## 10-1. `agent.py`

```diff
- intent = "analyze"
+ intent = "chat"
+
+ compute_signal = self._detect_compute_signal(lower)
+ chat_only = self._detect_chat_only_question(text, normalized)
+ acronym_candidates = self._detect_acronym_ambiguity(text, normalized)
+
+ if compute_signal:
+     intent = compute_signal
+ elif chat_only:
+     intent = "chat"
+
+ if acronym_candidates and not compute_signal:
+     intent = "chat"
+     needs_clarification = True
+     clarification_kind = "acronym_disambiguation"
+ elif acronym_candidates and compute_signal:
+     needs_clarification = True
+     clarification_kind = "acronym_disambiguation"
```

## 10-2. `compute.py`

```diff
- if not planner_requires_structure_clarification and not out.get("structure_query") ...:
-     candidate = _fallback_extract_structure_query(raw)
-     if candidate:
-         out["structure_query"] = candidate
+ if not out.get("structure_locked") and out.get("job_type") != "resolve_structure":
+     raise GroundingRequiredError(...)
```

## 10-3. `structure_resolver.py`

```diff
- if raw_query and not query_plan.get("semantic_descriptor"):
-     add(raw_query, match_kind="raw_exact", score=120, source="user_input")
+ if raw_query and query_plan.get("lane") == "direct_name":
+     add(raw_query, match_kind="raw_exact", score=120, source="user_input")
```

## 10-4. `chat.py`

```diff
- preflight = await _prepare_or_clarify(...)
+ turn = await _route_turn(...)
+ if turn.route_kind == "chat_only":
+     send assistant
+ elif turn.route_kind == "grounding_required":
+     send clarify(candidate_list)
+ elif turn.route_kind == "compute_ready":
+     submit job
```

---

## 11. WebSocket Event Contract Proposal

```json
{
  "type": "clarify",
  "session_id": "qcviz-...",
  "turn_id": "turn_123",
  "clarification_id": "clar_456",
  "candidate_list_id": "cand_789",
  "clarification_kind": "semantic_grounding",
  "form": { ... }
}
```

```json
{
  "type": "job_submitted",
  "session_id": "qcviz-...",
  "turn_id": "turn_123",
  "job": { "job_id": "job_001", ... }
}
```

```json
{
  "type": "result",
  "session_id": "qcviz-...",
  "turn_id": "turn_123",
  "job_id": "job_001",
  "structure_lock_id": "lock_abc",
  "result": { ... }
}
```

### 클라이언트 규칙
- same `turn_id` + `clarification_kind` -> replace existing clarify card
- `result.job_id` 가 current active job와 다르면 passive history insert or ignore
- `structure_lock_id` 가 다르면 old locked structure context를 현재 turn에 자동 상속하지 않음

---

## 12. Chat Intent Classifier Decision Table

| User input | Compute keyword | Acronym ambiguity | Semantic descriptor | Prior lock | Route |
|---|---:|---:|---:|---:|---|
| `MEA알아?` | No | Yes | No | No | `chat_only` + optional acronym clarify |
| `MEA의 HOMO 보여줘` | Yes | Yes | No | No | `grounding_required` |
| `TNT에 들어가는 주물질` | No | No | Yes | No | `grounding_required` |
| `TNT에 들어가는 주물질 HOMO 보여줘` | Yes | No | Yes | No | `grounding_required` then `compute_ready` |
| `니트로 벤젠` | No | No | No | No | `chat_only` or `grounding_required` depending UI mode |
| `니트로 벤젠 HOMO` | Yes | No | No | No | `compute_ready` if exact lockable |
| `같은 분자 ESP도` | Yes | No | No | Yes | `compute_ready` via continuation |
| `같은 분자 ESP도` | Yes | No | No | No | `follow_up_needs_context` |

---

## 13. 최종 결론

이 문제의 해법은 alias 몇 개 더 넣는 것이 아니다.

정답은 다음 네 가지를 동시에 하는 것이다.

1. **QCViz 기본 라우팅을 compute-first 에서 chat-first / grounding-first 로 전환한다.**
2. **MolChat `/interpret` 를 semantic grounding의 주 경로로 승격한다.**
3. **structure lock 이전에는 계산을 절대 시작하지 않는다.**
4. **chat / grounding / compute / result explanation 을 서로 다른 contract로 분리한다.**

이 네 가지를 적용하면 다음이 가능해진다.

- `MEA알아?` -> 자연스러운 설명 또는 acronym clarification
- `MEA의 HOMO 보여줘` -> 후보 선택 후 계산
- `TNT에 들어가는 주물질` -> semantic grounding dropdown
- `같은 분자 ESP도` -> 이전 lock 재사용
- tool output과 assistant text의 경계 분리
- stale turn/job contamination 감소

즉, 이 설계는 QCViz를 “분자명을 억지로 뽑아 계산하는 UI” 에서 **실험 화학자용 유연한 분자 계산 챗봇** 으로 바꾸는 실제 구현 경로다.
