---
audit_round: 1
category: C
priority: P1 (High)
related_files: [agent.py, providers.py, compute.py]
defects: "#7 focus_tab 불일치, #8 DummyProvider focus_tab, #9 한국어 키워드, #10 plan() 시그니처, #11 advisor_focus_tab 매핑"
---

# R1-C: Agent/LLM 모듈 결함

> 1차 감사 | 카테고리 C | 결함 5건

---

## 결함 #7: `agent.py` INTENT_DEFAULTS — focus_tab "orbitals" vs "orbital" — **P1 High**

`INTENT_DEFAULTS`에서 `focus_tab`이 `"orbitals"`로 설정되어 있으나, 프론트엔드와 백엔드의 나머지 코드는 모두 `"orbital"`을 사용합니다.

```python
# agent.py (잘못됨)
INTENT_DEFAULTS = {
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbitals"},  # ← "orbitals"
}
```

`compute.py`와 `pyscf_runner.py`의 유효 값 set에 `"orbitals"`가 포함되지 않으므로, LLM agent가 반환하면 프론트엔드에서 orbital 탭으로 자동 전환이 실패합니다.

**수정:**

```python
INTENT_DEFAULTS = {
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},
}

# PLAN_TOOL_SCHEMA도 동일하게:
"focus_tab": {
    "type": "string",
    "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
},
```

---

## 결함 #8: `providers.py` DummyProvider — focus_tab "orbitals" — **P1 High**

동일한 불일치 문제. `"orbitals"` → `"orbital"`로 수정 필요.

**수정:**

```python
focus = "orbital"  # "orbitals" → "orbital"
```

---

## 결함 #9: `providers.py` DummyProvider — 한국어 키워드 오류 — **Medium**

`"전기정전위"`는 정확한 한국어가 아닙니다. `compute.py`의 heuristic에서는 `"정전기"`, `"전위"`를 사용합니다.

**수정:**

```python
elif any(x in text for x in ["esp", "potential", "map", "정전기", "전위"]):
```

---

## 결함 #10: `compute.py` ↔ `agent.py` — plan() 호출 시그니처 불일치 — **P1 High**

`compute.py`는 `agent.plan(message, payload=payload)`로 호출하지만, `QCVizAgent.plan()`의 시그니처는 `plan(self, message, context=None)`입니다. `payload` 키워드가 없으므로 `TypeError` 발생 → 재시도 시 `context`가 전달되지 않습니다.

**수정:**

```python
# compute.py
if hasattr(agent, "plan") and callable(agent.plan):
    return _coerce_plan_to_dict(agent.plan(message, context=dict(payload)))
```

---

## 결함 #11: `compute.py` — advisor_focus_tab 매핑 누락 — **P1 High**

`AgentPlan.to_dict()`는 `focus_tab` 키를 반환하지만, `_merge_plan_into_payload`는 `advisor_focus_tab`을 기대합니다. 따라서 advisor_focus_tab이 항상 None이 됩니다.

**수정:**

```python
# _merge_plan_into_payload에 추가
if not out.get("advisor_focus_tab"):
    out["advisor_focus_tab"] = plan.get("advisor_focus_tab") or plan.get("focus_tab")
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
