---
audit_round: 3
category: W (WebSocket)
priority: P0 (Critical)
related_files: [compute.py, chat.js]
defects: "W5 Progress 값 범위 0~1 vs 0~100, W1 이벤트 매핑 확인"
---

# R3-W: WebSocket 메시지 프로토콜

> 3차 감사 | Perspective 4 | 결함 1건 + 매핑 검증

---

## W5: Progress 값 범위 불일치 — **P0 Critical**

서버(`compute.py`)는 progress를 0.0~1.0 범위로 전송합니다. `chat.js`의 `setProgress`는 `fill.style.width = Math.min(100, Math.max(0, pct)) + "%"`를 사용합니다.

서버가 `progress: 0.5`를 보내면 → `fill.style.width = "0.5%"` → progress bar가 거의 보이지 않음.

**수정 (`chat.js`):**

```javascript
if (typeof progress === "number") {
  var pctValue = progress <= 1.0 ? progress * 100 : progress;
  prog2.setProgress(pctValue);
}
```

---

## W1: 서버 이벤트 타입 ↔ 클라이언트 handler 매핑

| 서버 이벤트 type | chat.js case 매핑   | 매핑됨? |
| ---------------- | ------------------- | ------- |
| `job_submitted`  | `"job_submitted"`   | ✅      |
| `job_started`    | (간접 → job_update) | ✅      |
| `job_progress`   | `"job_progress"`    | ✅      |
| `job_completed`  | (간접 → result)     | ✅      |
| `job_failed`     | `"job_failed"`      | ✅      |

chat.js의 `assistant`, `stream_*`, `ready`/`pong` 등은 WebSocket chat handler에서 전송하는 것으로 추정됩니다.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
