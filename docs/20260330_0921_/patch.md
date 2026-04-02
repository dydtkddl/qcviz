다운로드용 보고서: [QCVIZ_MOLCHAT_final_patch_design_report_2026-03-29.md](sandbox:/mnt/data/QCVIZ_MOLCHAT_final_patch_design_report_2026-03-29.md)
원본 번들: [QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip](sandbox:/mnt/data/QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip)

첨부된 매니페스트, 최종 패치 지시문, 이슈 테이블을 기준으로 ZIP 내부 QCViz/MolChat 코어 코드를 전수 관점에서 연결 추적했고, 그 위에 최신 상용 MCP/툴콜링 기준선을 공식 문서 중심으로 얹어 최종 설계안을 정리했다.

# 1. Executive diagnosis

QCViz + MolChat은 이미 핵심 primitive를 꽤 갖췄다. `chat_only`, `grounding_required`, `compute_ready`, `continuation`, `structure_locked`, `turn_id/job_id binding`이 모두 존재하고, 과거의 구조 오염·clarification 누적·이전 결과 혼입 문제도 상당 부분 줄어들었다.

하지만 제품 레벨의 핵심 병목은 아직 남아 있다.

**현재 시스템의 본질적 문제는 semantic grounding 결과를 “직답”, “단일 확인”, “다중 clarification”, “compute 제출” 중 어디로 끝낼지를 중앙에서 결정하는 authoritative state machine이 없다는 점이다.**

그래서 지금은 같은 MolChat interpret 결과라도 다음처럼 흩어진다.

- `normalizer.py`가 1차로 질문 의도를 가른다.
- `agent.py`가 heuristic plan을 만든다.
- `chat.py`가 semantic direct answer, clarification UI, compute preflight를 혼합 처리한다.
- `compute.py`가 뒤늦게 raw acronym/raw phrase를 막는 2차 안전장치를 건다.
- `chat.js`는 주로 UI lifecycle과 binding만 안정화한다.

정리하면, **기술적 안전성은 많이 올라왔지만 conversational policy는 아직 분산 설계 상태**다.

내 최종 판단은 명확하다.

- MolChat는 resolver backend가 아니라 **semantic grounding engine**으로 취급해야 한다.
- QCViz는 grounding 결과를 받은 뒤 반드시 하나의 중앙 decision layer에서
  - `grounded_direct_answer`
  - `single_candidate_confirm`
  - `grounding_clarification`
  - `custom_only_clarification`
  - `compute_ready`
    중 하나로만 종료해야 한다.

- explanation/factual semantic query는 절대 compute path로 새면 안 된다.
- unknown acronym compute는 grounding을 우회하면 안 된다.
- semantic descriptor 경로에서는 generic fallback과 raw phrase revival을 완전히 금지해야 한다.

# 2. Commercial MCP / LLM ecosystem baseline

최신 상용 기준은 이미 매우 분명하다. Anthropic, OpenAI, Google, Microsoft 모두 “대화 응답”과 “도구 실행”을 같은 자유 텍스트 출력으로 취급하지 않고, structured tool call, JSON Schema, explicit result handoff, approval/trust boundary, stateful orchestration으로 정리하고 있다. MCP 스펙 자체도 lifecycle/capability negotiation, resources/prompts/tools 분리, JSON-RPC, schema validation, human-in-the-loop sampling을 전제로 한다. ([Claude API Docs][1])

Anthropic 쪽은 Claude Code가 MCP를 통해 외부 도구와 데이터 소스를 HTTP·stdio·SSE로 연결하고, 동적 tool update, OAuth, allowlist/denylist 같은 운영 제어를 제공한다. Claude tool use 문서는 모델이 structured tool call을 내고, 앱이 실행한 뒤 `tool_result`를 되돌리는 loop를 명시한다. 이건 곧 “챗봇 답변”과 “실행 단계”를 분리해야 한다는 뜻이다. ([Claude API Docs][1])

OpenAI는 Responses API에서 built-in tools, function calling, tool search, remote MCP servers를 하나의 tool layer로 설명하고, Structured Outputs가 supplied JSON Schema 준수를 보장한다고 명시한다. 또 connector는 OpenAI-maintained MCP wrapper이고, remote MCP는 third-party service라서 approval과 신뢰 경계가 기본값이다. 즉 상용 수준의 기준은 “schema-first, approval-aware, typed outcome”이다. ([OpenAI 개발자][2])

Google Gemini는 function calling과 compositional function calling을 공식 지원하고, structured outputs를 JSON Schema/Pydantic/Zod와 연결해 typed output을 권장한다. Microsoft Foundry Agent Service는 function_call → function_call_output loop, structured outputs, tracing, RBAC, content safety를 전면에 놓고 있고, Copilot Studio도 MCP tools/resources를 동적으로 반영한다. 이 조합은 QCViz에도 그대로 적용된다. **grounding 결과는 typed object여야 하고, direct answer / clarify / execute는 정책적으로 분리되어야 하며, tracing 가능한 상태 전이여야 한다.** ([Google AI for Developers][3])

이 기준으로 보면 QCViz의 목표 baseline은 6개다.

1. conversation lane와 tool lane 분리
2. schema-validated intermediate state 유지
3. direct answer / clarify / execute를 typed outcome으로 구분
4. single high-confidence result는 picker보다 direct answer 또는 compact confirm 우선
5. third-party grounding output의 provenance/confidence 유지
6. turn/job/result/continuation binding과 tracing 일관화

# 3. Current QCViz + MolChat architecture diagnosis

## 3.1 Normalizer

`src/qcviz_mcp/llm/normalizer.py`는 현재 스택에서 가장 건강한 계층이다.

실제 코드상 확인된 점:

- `semantic_descriptor` 탐지가 들어가 있다.
- `chat_only`는 explanation phrase, question-like 입력, unknown acronym without direct molecule-like candidate 등으로 잡힌다.
- `semantic_grounding_needed`는 semantic descriptor 또는 unknown acronym + explicit compute action에서 켜진다.
- explicit multi-molecule selection이 있으면 semantic grounding보다 batch compute를 우선한다.
- `MEA HOMO 보여줘` 같은 경우 raw acronym이 구조 후보로 남지 않도록 지운다.

직접 추적한 6개 기준 입력도 이 계층에서 거의 이상적으로 분류된다.

| 입력                            | 현재 normalizer 분류                      |
| ------------------------------- | ----------------------------------------- |
| `벤젠의 HOMO 오비탈을 보여줘`   | `compute_ready`                           |
| `TNT에 들어가는 주물질이 뭐지?` | `chat_only` + `semantic_grounding_needed` |
| `MEA라는 물질이 뭐야?`          | `chat_only` + `semantic_grounding_needed` |
| `MEA HOMO 보여줘`               | `grounding_required`                      |
| `ESP도 보여줘`                  | `compute_ready` + follow-up continuation  |
| multi-molecule paragraph        | `compute_ready` + batch intent            |

문제는 여기서 끝나지 않는다는 점이다. normalizer는 coarse routing은 잘하지만, 제품 UX에 필요한 `grounded_direct_answer_allowed`, `single_candidate_confirm_required`, `semantic_question_kind` 같은 정책 상태는 아직 없다.

## 3.2 Agent

`src/qcviz_mcp/llm/agent.py`는 heuristic planner로서

- `chat_only`면 chat intent
- `grounding_required`면 semantic clarification
- compute면 orbital/ESP/optimization job_type

을 만든다.

문제는 agent의 `chat_response`가 grounded answer라기보다 generic acronym fallback에 가깝다는 점이다. 즉, **grounded semantic answer의 최종 정책은 agent가 아니라 chat route로 밀려 있다.**

## 3.3 Chat route

`src/qcviz_mcp/web/routes/chat.py`가 현재 병목이다.

좋은 점:

- chat-only semantic lane가 있다.
- MolChat interpret 결과가 single candidate면 direct grounded answer를 만들 수 있다.
- canonical candidate 선택 후 `structure_locked=True`, `composition_mode='single'`로 2차 composition clarification을 막는다.
- REST/WS 둘 다 turn-aware 흐름을 가진다.

핵심 문제:

- 같은 semantic grounding 결과라도 chat-only일 때만 직답 lane로 특혜를 받는다.
- direct answer / clarification / compute preflight가 하나의 중앙 helper가 아니라 분산 로직으로 나뉘어 있다.
- `_discovery_structure_suggestions()`에 generic fallback(`[benzene, acetone, ethanol]`)이 남아 있다.
- clarification option label이 rationale/description까지 섞여 장황해질 수 있다.

즉 `chat.py`는 지금 너무 많은 역할을 동시에 맡고 있다.

## 3.4 Compute route

`src/qcviz_mcp/web/routes/compute.py`는 상당히 안정적이다.

- `_safe_plan_message()`가 normalizer 결과를 다시 덮어써 chat_only/grounding_required를 강제한다.
- `_apply_session_continuation()`이 follow-up compute에서 이전 구조·메서드·기저를 이어받는다.
- `_merge_plan_into_payload()`가 semantic descriptor raw phrase를 다시 구조명으로 살리지 않도록 막는다.
- successful execution 후에만 conversation state를 업데이트한다.

즉 compute route는 지금도 “뒤늦은 안전장치”로는 잘 작동한다. 다만 최종 구조에서는 이 역할을 줄이고, semantic policy는 chat route에서 끝내는 편이 맞다.

## 3.5 Frontend state

`src/qcviz_mcp/web/static/chat.js`와 `templates/index.html` 쪽은 많이 좋아졌다.

확인된 상태:

- `turn_id` / `job_id` binding이 분리돼 있다.
- clarification/confirm card가 active card 방식으로 교체된다.
- history hydration dedupe가 있다.
- session 전환 시 chat store 정리가 있다.
- turn 기준 메시지를 나중에 job에 retroactive bind한다.

따라서 QV-005, QV-006, QV-007 류는 구조적으로 거의 닫혀 있다.

## 3.6 MolChat interpret

MolChat backend는 candidate service로서 꽤 적절하다.

- `/api/v1/molecules/interpret`가 존재한다.
- `query_mode`가 `semantic_descriptor` / `direct_name`으로 나뉜다.
- semantic descriptor면 candidate list를 만들고,
- orchestrator가 PubChem grounding으로 CID를 붙여 반환한다.

중요한 판단:

**MolChat는 candidate engine이지, UX policy engine이 아니다.**

single high-confidence일 때 직답할지, compute면 확인할지, clarification으로 갈지는 QCViz가 결정해야 한다.

## 3.7 Contract drift

`molchat_client.py`는 interpret 호출 때 backend 공식 schema 밖의 필드도 일부 보내고 있다. 지금은 extras가 무시돼서 치명적 장애는 아니지만, enterprise-grade 기준에서는 명백한 schema drift다. 이건 이번 패치에서 같이 정리해야 한다.

# 4. UX evaluation

현재 시스템은 예전보다 훨씬 낫다. 하지만 여전히 완전히 “화학 대화 비서” 같지는 않고, “계산 시스템에 대화형 입구를 붙인 제품”의 흔적이 남아 있다.

그 이유는 세 가지다.

첫째, 질문형 semantic query는 자연스럽게 답할 수 있게 개선됐지만, 그 정책이 아직 전면화되지 않았다.
둘째, compute-intent semantic query에서는 여전히 사용자가 “구조를 계산기에 먹이기 위한 전처리”를 겪는 느낌이 난다.
셋째, clarification option이 사람 친화적 선택지라기보다 reasoning trace처럼 보일 때가 있다.

기술적으로 맞는 것과, 과학적으로 안전한 것과, 대화적으로 자연스러운 것은 다르다.

- 기술적으로 맞는 것: raw acronym을 그대로 계산하지 않음, raw phrase를 후보로 재승격하지 않음, canonical 선택 후 2차 composition clarification 방지
- 과학적으로 안전한 것: 애매한 acronym 자동 계산 금지, semantic descriptor에 generic fallback 금지, 설명형 질문을 compute error로 끝내지 않음
- 대화적으로 자연스러운 것: `MEA라는 물질이 뭐야?`에 바로 “보통 ethanolamine입니다”라고 답하고, `MEA HOMO 보여줘`에는 “MEA를 ethanolamine으로 보고 진행할까요?”라고 묻는 것

현재 코드는 첫째는 꽤 잘하고, 둘째는 대부분 맞아가며, 셋째가 아직 미완이다.

## 4.1 Six target journeys

| 입력                            | 의도                      | grounding 필요 | 이상적 UX                                             | 현재 UX                                                                            |
| ------------------------------- | ------------------------- | -------------: | ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `벤젠의 HOMO 오비탈을 보여줘`   | compute_ready             |         아니오 | 즉시 compute submit                                   | 현재도 대체로 정상                                                                 |
| `TNT에 들어가는 주물질이 뭐지?` | chat semantic             |             예 | single high-confidence면 direct answer                | 현재 code reality상 direct answer 가능, 다만 typed contract 부재                   |
| `MEA라는 물질이 뭐야?`          | explanation semantic      |             예 | compute 금지, grounded answer 또는 짧은 clarification | 현재 grounded chat lane 존재, 정책 중앙화 미완                                     |
| `MEA HOMO 보여줘`               | compute + unknown acronym |             예 | single confirm 또는 clarification 후 compute          | 현재 grounding clarification 방향은 맞음                                           |
| `ESP도 보여줘`                  | follow-up compute         |      문맥 의존 | 이전 구조 재사용 후 ESP submit                        | 현재 continuation은 상당 부분 정상                                                 |
| multi-molecule paragraph        | batch compute             |    보통 아니오 | 문단 구조 추출 후 batch submit                        | 현재 explicit multi-molecule 우선 처리됨. 다만 formula fragment acronym noise 잔존 |

# 5. Root-cause matrix

| 문제군                          | 근본 원인                                                      | 최종 처방                                                 |
| ------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------- |
| explanation semantic misrouting | `chat_only`와 semantic grounding의 결합 정책이 중앙화되지 않음 | grounding outcome state machine 도입                      |
| single-candidate UX 미완        | direct answer vs confirm 정책 부재                             | `grounded_direct_answer`, `single_candidate_confirm` 도입 |
| generic fallback 오염           | discovery fallback이 semantic-safe하지 않음                    | semantic/discovery path에서 generic fallback 제거         |
| raw descriptive phrase revival  | 후보 소스 merge가 분산                                         | raw phrase revival 금지 rule 중앙화                       |
| dropdown verbosity              | option label에 rationale/description 과적재                    | label/subtitle/meta 분리                                  |
| contract drift                  | client/backend evolve drift                                    | interpret request/response schema 정렬                    |
| stale turn/job confusion        | 과거에는 binding 부실                                          | 현재 구조 유지 + tracing 강화                             |
| Korean copy audit               | 과거 문자열 손상 잔재 가능성                                   | copy catalog + snapshot test                              |

# 6. Final patch design

## 6.1 Final architectural direction

최종 구조는 3계층으로 고정한다.

1. **Normalization layer**
   입력에서 `intent_mode`, `query_kind`, `analysis_bundle`, `follow_up_mode`, `semantic_grounding_needed`를 만든다.

2. **Grounding decision layer**
   MolChat interpret 결과와 normalizer 결과를 합쳐 authoritative outcome을 만든다.

3. **Execution/UI layer**
   그 outcome이 direct answer인지, single confirm인지, clarification인지, compute submit인지 렌더링/실행한다.

핵심은 2번이다. 지금 분산된 semantic policy를 여기로 모아야 한다.

## 6.2 Exact precedence rules

정책은 아래처럼 고정한다.

### Rule A. Explanation intent wins over compute

`chat_only` 또는 `intent_mode in {explanation, factual_semantic}`면 compute 금지.

이 경우 허용되는 종료 상태는 아래뿐이다.

- `grounded_direct_answer`
- `grounding_clarification`
- `safe_unresolved_chat_answer`

### Rule B. Unknown acronym + explicit compute never bypasses grounding

`explicit_compute_action == true`이고 unknown acronym이 있으며 concrete molecule이 없으면 무조건 `grounding_required`.

허용되는 종료 상태:

- `single_candidate_confirm`
- `grounding_clarification`
- `custom_only_clarification`

즉 raw acronym compute 금지.

### Rule C. Semantic descriptor never becomes a raw structure

`semantic_descriptor == true`이면 raw phrase를 structure query로 승격하지 않는다. dropdown option으로도 노출하지 않는다. generic example fallback도 병합하지 않는다.

### Rule D. Explicit concrete molecule + explicit compute is compute_ready

예: `benzene HOMO 보여줘`
이 경우 즉시 compute submit.

### Rule E. Single high-confidence semantic result policy

다음 조건이면 high-confidence로 본다.

- `candidate_count == 1`
- `confidence >= 0.85`
- `confidence_gap >= 0.20`
- canonical name/CID 존재

정책:

- explanation/factual semantic query → `grounded_direct_answer`
- compute query → `single_candidate_confirm`

즉 **직답은 채팅 질문에서만**, **계산은 확인 한 번** 둔다.

### Rule F. Multiple candidates

후보가 여러 개면 explanation이든 compute든 `grounding_clarification`으로 간다. 다만 explanation 질문에서는 intro copy를 더 대화형으로 만든다.

### Rule G. No safe candidate

후보가 없으면

- explanation query → `safe_unresolved_chat_answer`
- compute query → `custom_only_clarification`

generic molecule 예시를 던지지 않는다.

## 6.3 State machine

```text
user_message
  -> normalize
    -> chat_only | grounding_required | compute_ready

chat_only + semantic_grounding_needed
  -> interpret
    -> 0 safe candidates -> safe_unresolved_chat_answer
    -> 1 high-confidence -> grounded_direct_answer
    -> multi/low-confidence -> grounding_clarification

grounding_required
  -> interpret
    -> 0 safe candidates -> custom_only_clarification
    -> 1 high-confidence -> single_candidate_confirm
    -> multi/low-confidence -> grounding_clarification

compute_ready
  -> if follow-up and no explicit structure
       -> continuation binding
         -> bound structure found -> compute_submit
         -> none -> continuation_targeting_clarification
     else
       -> compute_submit
```

보조 상태:

- `structure_locked = true` when canonical candidate selected/confirmed
- `continuation_bound = true` when follow-up compute reuses prior structure
- `result_bound = true` when successful job updates conversation state
- `clarification_active = true` until superseded/answered/cancelled

## 6.4 JSON / WebSocket / UI contract

모든 REST/WS assistant 응답에 아래 공통 envelope를 넣는다.

```json
{
  "routing_state": "chat_only|grounding_required|compute_ready",
  "response_mode": "grounded_direct_answer|single_candidate_confirm|grounding_clarification|custom_only_clarification|compute_submitted|compute_result|safe_unresolved_chat_answer",
  "grounding": {
    "needed": true,
    "query_mode": "semantic_descriptor|direct_name|unknown_acronym|none",
    "candidate_count": 1,
    "confidence_policy": "single_high_confidence",
    "selected_candidate": {
      "canonical_name": "ethanolamine",
      "formula": "C2H7NO",
      "cid": 700,
      "source": "molchat_interpret",
      "confidence": 0.93
    }
  },
  "structure_lock": {
    "locked": false,
    "lock_source": null
  },
  "turn_id": "...",
  "job_id": null
}
```

clarification option도 바꾼다. label 하나에 다 밀어넣지 않는다.

```json
{
  "value": "ethanolamine",
  "label": "Ethanolamine",
  "subtitle": "C2H7NO",
  "meta": {
    "cid": 700,
    "confidence": 0.93,
    "source": "molchat_interpret",
    "rationale": "MEA의 가장 일반적인 확장"
  }
}
```

직답 lane은 별도 response_mode를 갖는다.

```json
{
  "response_mode": "grounded_direct_answer",
  "message": "MEA는 보통 ethanolamine을 의미합니다.",
  "grounding": {
    "selected_candidate": {
      "canonical_name": "ethanolamine",
      "formula": "C2H7NO",
      "cid": 700,
      "confidence": 0.93
    }
  },
  "next_actions": [
    {
      "type": "suggest_compute",
      "analysis": "HOMO",
      "label": "이 분자의 HOMO 보기"
    }
  ]
}
```

compute query + single candidate는 direct answer가 아니라 compact confirm으로 간다.

```json
{
  "response_mode": "single_candidate_confirm",
  "message": "MEA는 보통 ethanolamine을 의미합니다. 이 분자로 HOMO 계산을 진행할까요?",
  "confirm": {
    "candidate": {
      "canonical_name": "ethanolamine",
      "formula": "C2H7NO",
      "cid": 700,
      "confidence": 0.93
    },
    "confirm_action": "accept_grounded_candidate",
    "cancel_action": "choose_other_candidate"
  }
}
```

# 7. File-level change plan

## `src/qcviz_mcp/llm/normalizer.py`

추가:

- `intent_mode`: `explanation`, `factual_semantic`, `compute`, `follow_up_compute`, `batch_compute`
- `semantic_question_kind`: `definition`, `constituent`, `identity`, `other`
- acronym detector 개선: formula fragment (`CH`, `CH-`) 노이즈 억제
- `direct_answer_allowed` 초안 플래그

## `src/qcviz_mcp/llm/agent.py`

변경:

- heuristic plan에 `response_mode` placeholder, `grounding_policy` 추가
- generic acronym chat response는 last-resort fallback으로만 유지
- semantic query 최종 UX 결정을 agent가 아니라 grounding decision layer로 넘김

## `src/qcviz_mcp/services/molchat_client.py`

변경:

- interpret request payload를 backend schema와 정렬
- response parsing 시 `query_mode`, confidence, provenance를 보존

## `MolChat/backend/app/schemas/molecule.py`

변경:

- optional `locale`, `mode`, `context` 추가
- candidate schema에 `confidence`, `source`, `canonical_name`, `cid`, `formula` 정리
- response에 `candidate_count`, `top_confidence` 추가

## `MolChat/backend/app/services/molecule_engine/query_resolver.py`

변경:

- confidence normalization 일관화
- semantic descriptor 후보 생성 시 raw phrase echo 금지 강화
- alias resolution provenance 명시화

## `src/qcviz_mcp/web/routes/chat.py` — 핵심 패치

추가:

- `_decide_grounding_outcome(...)`
- `_build_grounded_direct_answer_payload(...)`
- `_build_single_candidate_confirm_payload(...)`
- `_build_custom_only_clarification(...)`
- `_compact_candidate_option(...)`

변경:

- REST/WS 둘 다 동일 grounding outcome helper 사용
- semantic-safe path에서 generic example fallback 제거
- clarification copy를 짧고 자연스럽게 개편
- option label/subtitle/meta 분리

제거:

- semantic/discovery path의 `[benzene, acetone, ethanol]` fallback
- semantic direct answer/clarification을 ad hoc로 나누는 분산 로직

## `src/qcviz_mcp/web/routes/compute.py`

변경:

- `accept_grounded_candidate` confirm action 수용
- single-confirm 후 canonical structure lock 반영
- continuation precedence를 `structure_locked` 중심으로 재정렬
- compute preflight는 policy-decision 완료 payload만 받도록 단순화

## `src/qcviz_mcp/web/static/chat.js`

추가:

- `grounded_direct_answer` renderer
- `single_candidate_confirm` renderer
- candidate detail disclosure UI

변경:

- `response_mode` 기반 렌더링 통일
- 기존 active card lifecycle 유지
- option label/subtitle/meta 분리 반영

## `src/qcviz_mcp/web/templates/index.html`

변경:

- turn-level grounding metadata 저장
- confirmed candidate / structure lock metadata를 history와 함께 보존

# 8. Test and validation plan

## Unit

- `MEA라는 물질이 뭐야?` → explanation + grounding
- `TNT에 들어가는 주물질이 뭐지?` → constituent semantic question
- `MEA HOMO 보여줘` → grounding_required
- batch paragraph → batch_compute, formula-fragment acronym 오탐 없음

## Grounding decision helper

- 1 candidate / high confidence / explanation → `grounded_direct_answer`
- 1 candidate / high confidence / compute → `single_candidate_confirm`
- multi → `grounding_clarification`
- 0 / explanation → `safe_unresolved_chat_answer`
- 0 / compute → `custom_only_clarification`

## API

- direct answer lane
- single confirm lane
- canonical pick 후 no second composition clarification
- no generic fallback
- no raw descriptive phrase option
- Korean copy snapshot

## WebSocket

- grounded direct answer에도 `turn_id` 유지
- `single_candidate_confirm` payload 검증
- clarification supersession
- follow-up `ESP도 보여줘`의 continuation binding 검증

## Playwright

여기는 반드시 fixture를 query-sensitive하게 바꿔야 한다. 지금처럼 모든 semantic 질의에 TNT 하나만 주는 stub는 챗봇 UX 회귀를 가릴 수 있다.

필수 시나리오:

- `MEA라는 물질이 뭐야?` → direct grounded answer, no dropdown
- `TNT에 들어가는 주물질이 뭐지?` → single high-confidence direct answer
- `MEA HOMO 보여줘` → single confirm 또는 clarification, no raw acronym compute
- canonical 선택 후 composition 재질문 없음
- 세션 전환 후 stale turn contamination 없음
- 한국어 렌더링 snapshot

# 9. Rollout / migration plan

가장 안전한 순서는 이렇다.

1. 새 typed response contract를 feature flag 뒤에 추가
2. `chat.py`에 grounding decision helper 구현
3. semantic generic fallback 제거
4. single-candidate confirm UI 도입
5. MolChat client/backend schema 정렬
6. 테스트/fixture 전면 수정
7. regression 통과 후 flag 기본 활성화

권장 feature flag:

- `GROUNDING_POLICY_V2`
- `GROUNDING_SINGLE_CONFIRM_UI`
- `SEMANTIC_GENERIC_FALLBACK_DISABLED`
- `CHAT_RESPONSE_MODE_V2`

하위 호환은 한 버전 정도 유지하면 된다.

- 새 `response_mode`가 있으면 새 렌더러 사용
- 없으면 구 clarification renderer fallback
- MolChat request 확장은 optional field만 추가해서 호환 유지

진단 로그도 추가해야 한다.

- `routing_state`
- `response_mode`
- `grounding_candidate_count`
- `grounding_top_confidence`
- `structure_locked_before/after`
- `continuation_bound`
- `turn_id`, `job_id`, `session_id`

이 메트릭이 있어야 “왜 direct answer가 아니라 clarification이었는가”를 사후 분석할 수 있다.

# 10. Residual risks

첫째, confidence threshold는 시작점일 뿐이다. `0.85 / 0.20 gap`은 좋은 초기값이지만, 실제 MolChat 결과 분포에 맞춰 조정이 필요하다.

둘째, MolChat candidate 품질은 여전히 외부 semantic expansion 품질의 영향을 받는다. 그래서 결정권은 반드시 MolChat가 아니라 QCViz에 있어야 한다.

셋째, Korean copy/mojibake는 핵심 파일에서 치명적인 수준은 아니어도 완전 종료라고 단정하긴 이르다. copy catalog와 snapshot test가 필요하다.

넷째, batch paragraph에서 화학식 조각이 acronym처럼 잡히는 parser roughness가 남아 있다. UX를 깨는 P0는 아니지만 정리해야 한다.

다섯째, runtime drift는 fingerprint로 감지할 수 있어도 운영 절차가 약하면 다시 재발한다. health/debug만이 아니라 배포 절차도 묶어야 한다.

---

## Final implementation verdict

이건 프롬프트를 조금 손보는 수준으로는 끝나지 않는다.

반드시 해야 할 일은 다섯 가지다.

- semantic grounding을 first-class state machine으로 승격
- direct answer / confirm / clarification / compute를 typed outcome으로 분리
- semantic-safe path에서 generic fallback 제거
- MolChat candidate provenance/confidence 보존
- REST/WS/UI를 동일 contract로 정렬

이 방향으로 패치하면 이슈 테이블의 P0인 QV-014, QV-015, QV-016, QV-029를 구조적으로 닫을 수 있고, QV-020, QV-024, QV-026, QV-030도 같은 설계 아래서 정리 가능하다.

이 설계는 첨부된 외부 연구/최종 패치 지시문이 요구한 순서—상용 생태계 기준선, 전수 코드 스캔, UX 진단, 구현 준비 완료 패치 설계—에 맞춰 작성했다.

[1]: https://docs.anthropic.com/en/docs/claude-code/mcp "https://docs.anthropic.com/en/docs/claude-code/mcp"
[2]: https://developers.openai.com/api/docs/guides/tools/ "https://developers.openai.com/api/docs/guides/tools/"
[3]: https://ai.google.dev/gemini-api/docs/function-calling "https://ai.google.dev/gemini-api/docs/function-calling"
