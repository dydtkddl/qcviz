---
audit_round: 1
category: G
priority: 확인완료
related_files: [app.js]
defects: "#21 Unix timestamp (확인완료), #22 빈 method 괄호 (확인완료)"
---

# R1-G: 프론트엔드 결함 — app.js

> 1차 감사 | 카테고리 G | 결함 2건 (모두 확인완료)

---

## 결함 #21: `fetchHistory` — Unix timestamp 변환 — **확인 완료 (정상)**

```javascript
var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
```

Backend의 `_now_ts()`는 `time.time()`을 사용하며, 현재 시점의 Unix timestamp는 약 `1.7e9`이므로 `1e12` 미만. 정상 변환됩니다.

---

## 결함 #22: `renderSessionTabs` — 빈 method 괄호 — **확인 완료 (정상)**

```javascript
var displayStr = name + (method ? " (" + method + ")" : "") + badge;
```

`method`가 `""`이면 falsy이므로 괄호가 표시되지 않습니다. 정상.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
