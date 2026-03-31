---
audit_round: 2
category: B
priority: P0 (Critical), P1 (High), P2 (Medium)
related_files: [viewer.js, pyscf_runner.py, chat.js]
defects: "B1 _loadPromise 고착, B2 renderOrbital try-catch, B3 SCF callback 예외, B4 ESP 실패 알림, B5 HTTP 에러 상세, B6 비수렴 경고"
---

# R2-B: 에러 전파 완전성

> 2차 감사 | 축 B | 결함 6건

---

## B1: `_loadPromise` rejected 후 영구 고착 — **P0 Critical**

네트워크 장애로 3Dmol.js 로드가 실패하면, `_loadPromise`가 rejected Promise로 남아 이후 모든 `load3Dmol()` 호출이 즉시 reject됩니다. 페이지 새로고침 없이는 뷰어를 영원히 사용할 수 없습니다.

**수정 (`viewer.js`):**

```javascript
var _loadPromise = null;
function load3Dmol() {
  if (window.$3Dmol) return Promise.resolve();
  if (_loadPromise) return _loadPromise;
  _loadPromise = new Promise(function (resolve, reject) {
    var s = document.createElement("script");
    s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
    s.onload = function () {
      resolve();
    };
    s.onerror = function () {
      _loadPromise = null; // 실패 시 리셋
      if (s.parentNode) s.parentNode.removeChild(s);
      reject(new Error("3Dmol.js load failed"));
    };
    document.head.appendChild(s);
  });
  return _loadPromise;
}
```

---

## B2: `renderOrbital` — `addOrbitalSurfaces`가 try-catch 밖에서 호출됨 — **P1 High**

`$3Dmol.VolumeData` 생성자가 잘못된 cube 데이터를 받으면 예외를 던질 수 있습니다.

**수정:** `addOrbitalSurfaces` 호출을 try-catch로 감쌈.

---

## B3: `_emit_progress` 예외가 SCF 계산을 중단시킬 수 있음 — **P1 High**

**수정:** `_scf_callback` 전체를 try-except로 감쌈.

```python
def _scf_callback(env):
    try:
        cycle_count[0] += 1
        if progress_callback and cycle_count[0] % 2 == 0:
            # ... progress 전송 ...
    except Exception:
        pass  # SCF 계산이 callback 오류로 중단되지 않도록 보호
```

---

## B4: `addESPSurface` 실패 시 사용자 알림 없음 — **P2 Medium**

분자 모델만 표시되고 ESP surface가 없으면 사용자가 원인을 알 수 없습니다.

**수정:** legend 영역을 통해 ESP 렌더링 실패 알림 표시.

---

## B5: `chat.js` `submitMessage` HTTP fallback — 비200 응답 body 미읽기 — **P2 Medium**

서버가 400이나 422를 반환하면 `detail` 필드의 유용한 에러 메시지가 있지만, body를 읽지 못합니다.

**수정:** 에러 응답 body를 JSON으로 읽어 detail 추출.

---

## B6: `_run_scf_with_fallback` — 비수렴 mf 반환으로 부정확한 cubegen — **P2 Medium**

**수정:** `_populate_scf_fields`에서 비수렴 경고를 강조하고, `_finalize_result_contract`에서 프론트엔드 경고 이벤트 추가.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
