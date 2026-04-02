---
audit_round: 1
category: F
priority: 확인완료
related_files: [chat.js]
defects: "#18 ghost callback (확인완료), #19 basis 필드명, #20 에너지 fallback (확인완료)"
---

# R1-F: 프론트엔드 결함 — chat.js

> 1차 감사 | 카테고리 F | 결함 3건 (2건 확인완료)

---

## 결함 #18: WebSocket `connectWS` — ghost callback — **확인 완료 (결함 아님)**

현재 코드는 이미 handler에 `if (this !== state.ws) return;` 가드를 추가하여 이 문제를 해결하고 있습니다.

---

## 결함 #19: `handleServerEvent` "result" case — basis 필드명 불일치 — **Medium**

Backend 결과에는 `basis_set`이 아닌 `basis`가 있으므로, `job.result.basis_set`은 `undefined`입니다. `chat.js`에서 `basis_set: result.basis || result.basis_set`로 설정하므로 job 레벨에서는 올바르게 설정되지만 일관성이 없습니다.

**수정 (app.js `getJobDetailLine` 보강):**

```javascript
var basis =
  job.basis_set ||
  job.basis ||
  (job.result && (job.result.basis || job.result.basis_set)) ||
  (job.payload && (job.payload.basis || job.payload.basis_set)) ||
  "";
```

---

## 결함 #20: `handleServerEvent` — energy fallback — **확인 완료 (정상)**

Backend는 `_finalize_result_contract`에서 `total_energy_hartree`를 항상 설정하므로, `result.energy` fallback은 레거시 호환용입니다. 정상.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
