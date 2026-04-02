---
audit_round: 3
category: S (Semantic)
priority: P0 (Critical), P1 (High), P2 (Medium)
related_files: [pyscf_runner.py, results.js, viewer.js]
defects: "S1/S2 Orbital index 0/1-based 혼용, S4 ESP range clipping, S5 _COVALENT_RADII 누락, S6 isovalue 모드별 분리"
---

# R3-S: 시맨틱 정확성

> 3차 감사 | Perspective 1 | 결함 4건

---

## S1/S2: Orbital Index 일관성 매트릭스 — **P1 High**

### pyscf_runner.py

| 함수                         | 필드명             | 의미        | 기준        |
| ---------------------------- | ------------------ | ----------- | ----------- |
| `_build_orbital_items`       | `index`            | MO 번호     | **1-based** |
| `_build_orbital_items`       | `zero_based_index` | 배열 인덱스 | **0-based** |
| `_resolve_orbital_selection` | `index`            | MO 번호     | **1-based** |
| `_resolve_orbital_selection` | `zero_based_index` | 배열 인덱스 | **0-based** |

### results.js — 결함 발견

Legacy path에서 `"MO " + realIdx`는 **0-based**이고, `_build_orbital_items`의 `label`은 `"MO {idx+1}"`으로 **1-based**. 혼재 시 같은 orbital이 다른 번호로 표시됩니다.

**수정 (`results.js`):**

```javascript
var realIdx = j + offset;
var lbl = labels[j] || "MO " + (realIdx + 1); // 1-based로 통일
```

**수정 (`viewer.js`):**

```javascript
var label = "MO " + (j + 1); // 1-based 표시
```

---

## S4: ESP range clipping 상한 — **P2 Medium**

이온성 화합물(LiF, NaCl 등)의 ESP 범위는 0.3 a.u. 이상. 상한 0.18이면 양 극단이 포화됩니다.

**수정:** 동적 상한 `max(0.18, min(p995 * 1.2, 0.50))`

---

## S5: `_COVALENT_RADII` 누락 원소 — **P1 High**

현재 12개 원소만 포함. Li, Na, K, Mg, Ca, Fe, Zn 등 일반 유기/무기 원소를 50+ 원소로 확장합니다.

---

## S6: `state.isovalue` 모드별 분리 — **P0 Critical**

현재 orbital(기본 0.03)과 ESP(기본 0.002) 양쪽에서 공유. orbital에서 ESP로 전환 후 다시 orbital로 돌아가면 isovalue가 0.002로 남아 orbital이 거의 보이지 않습니다.

**수정:**

```javascript
var state = {
  isovalue: 0.03, // 현재 모드의 active 값
  orbitalIsovalue: 0.03, // orbital 전용
  espDensityIso: 0.002, // ESP 전용
};
```

`showControls`, slider handler, `renderESP`, `renderOrbital`, `saveViewerSnapshot`, `restoreViewerSnapshot` 모두 수정.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
