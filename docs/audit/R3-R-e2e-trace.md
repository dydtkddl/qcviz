---
audit_round: 3
category: R (E2E Trace)
priority: P1 (High)
related_files:
  [chat.js, compute.py, pyscf_runner.py, results.js, viewer.js, app.js]
defects: "R3 연속 계산 progress 혼동, IVS-1 HOMO 전 구간 흐름 검증 (완료), IVS-4 에러 후 status 고착"
---

# R3-R: 복원 체인 E2E 추적

> 3차 감사 | Perspective 5 + IVS 검증 | 결함 2건 + 검증 2건

---

## R3: 연속 계산 시 progress UI 혼동 — **P1 High**

첫 번째 job의 나머지 progress 이벤트가 뒤늦게 도착하면, `ensureProgressUI()`는 두 번째 job의 progress UI를 업데이트합니다.

**수정 (`chat.js`):** progress event에서 job ID 검증:

```javascript
if (jid2 && jid2 === state.activeJobId) {
  var prog2 = ensureProgressUI();
  // ... progress UI 업데이트
}
```

---

## IVS-1: "물 분자의 HOMO 오비탈 보여줘" — 전체 추적 ✅

```
1. chat.js: submitMessage → WebSocket/HTTP
2. compute.py: _prepare_payload → agent.plan → intent="orbital_preview", orbital="HOMO"
3. pyscf_runner: run_orbital_preview → SCF → _resolve_orbital_selection("HOMO") → homo_idx=4
4. cubegen → orbital_cube_b64 (≈3MB base64)
5. chat.js: handleServerEvent → App.upsertJob → emit("result:changed")
6. results.js: normalizeResult → decideFocusTab → "orbital"
7. viewer.js: handleResult → renderOrbital → addOrbitalSurfaces → 3D 렌더링
```

**전체 체인 정합성: ✅ 모든 단계에서 데이터가 올바르게 변환·전달됩니다.**

---

## IVS-4: "xyz123" 에러 경로 추적 — 결함 발견

에러 상태가 영구적으로 남습니다. `status:changed` handler에서 `success`/`completed`만 자동 복귀합니다.

**수정 (`app.js`):**

```javascript
App.on("status:changed", function (s) {
  if (s.kind === "success" || s.kind === "completed" || s.kind === "error") {
    var delay = s.kind === "error" ? 6000 : 4000;
    setTimeout(function () {
      if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
        App.setStatus("Ready", "idle", "app");
      }
    }, delay);
  }
});
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
