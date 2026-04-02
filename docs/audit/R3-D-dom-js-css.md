---
audit_round: 3
category: D (DOM-JS-CSS)
priority: P0 (Critical → dead ref 제거), P2 (Medium)
related_files: [viewer.js, index.html, style.css]
defects: "D1 DOM ID 교차 참조 매트릭스, D2 grpESP 미존재, D5 chat-msg--system CSS"
---

# R3-D: DOM-JS-CSS 삼각 정합성

> 3차 감사 | Perspective 2 | 결함 2건 + 매트릭스

---

## D1: DOM ID 교차 참조 매트릭스

### JS에서 참조하지만 HTML에 없는 ID

| JS 파일     | 참조 ID  | 존재?          |
| ----------- | -------- | -------------- |
| `viewer.js` | `grpESP` | ❌ **결함 D2** |

### Dead HTML ID들 (CSS/구조용으로 무해)

`appShell`, `topbar`, `viewerContainer`, `panelChat`, `chatInputArea`, `panelResults`, `panelHistory`, `grpColorScheme`

---

## D2: `grpESP` DOM 존재 여부 — **P0 Critical (dead reference)**

`viewer.js`의 `collectDom()`에서 `document.getElementById("grpESP")`를 참조하지만, `index.html`에 `id="grpESP"`는 존재하지 않습니다. `dom.$grpESP`가 `null`이므로 `showControls`에서 해당 줄이 실행되지 않습니다. 기능적 문제는 없지만 dead reference입니다.

**수정 (옵션 A — dead reference 제거):**

```javascript
// collectDom()에서 제거:
// dom.$grpESP = document.getElementById("grpESP");
// showControls()에서 제거:
// if (dom.$grpESP) dom.$grpESP.hidden = !hasESP;
```

---

## D5: `chat-msg--system` CSS 정의 — **P2 Medium**

`.chat-msg--system`이 `style.css`에 정의되지 않았습니다. `.chat-msg`의 기본 스타일이 적용되므로 기능적 문제는 없습니다.

**수정 (선택적):**

```css
.chat-msg--system {
  opacity: 0.85;
}
.chat-msg--system .chat-msg__text {
  font-size: 12px;
  color: var(--text-2);
}
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
