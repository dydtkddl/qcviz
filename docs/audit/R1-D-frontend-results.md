---
audit_round: 1
category: D
priority: Low, Medium
related_files: [results.js]
defects: "#12 xyz_block (확인완료), #13 Array.isArray, #14 is_selected 미존재"
---

# R1-D: 프론트엔드 결함 — results.js

> 1차 감사 | 카테고리 D | 결함 3건 (1건 확인완료)

---

## 결함 #12: `normalizeResult` — xyz_block 설정 — **확인 완료 (결함 아님)**

Backend의 `_finalize_result_contract`는 `visualization.xyz`와 `visualization.molecule_xyz`를 설정하고, `normalizeResult`가 `viz.xyz_block`으로 올바르게 복사합니다. 정상 동작 확인.

---

## 결함 #13: `getAvailableTabs` — `Object.keys()` on Array — **Low**

배열에 `Object.keys()`를 사용하면 동작은 하지만 의미적으로 부정확합니다.

**수정:**

```javascript
var hasMulliken =
  Array.isArray(r.mulliken_charges) && r.mulliken_charges.length > 0;
var hasLowdin = Array.isArray(r.lowdin_charges) && r.lowdin_charges.length > 0;
```

---

## 결함 #14: `renderOrbital` — `is_selected` 필드 미존재 — **Medium**

Backend의 `_build_orbital_items`는 `is_selected` 필드를 포함하지 않아 `selIdx`가 항상 0입니다. 실제 선택 정보는 `r.selected_orbital`에 있습니다.

**수정:**

```javascript
var orbLabel = "MO";
if (result.selected_orbital && result.selected_orbital.label) {
  orbLabel = result.selected_orbital.label;
} else if (orbs.length > 0 && orbs[0] && orbs[0].label) {
  orbLabel = orbs[0].label;
}
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
