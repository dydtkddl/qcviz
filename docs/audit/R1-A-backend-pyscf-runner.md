---
audit_round: 1
category: A
priority: P0 (Critical), P1 (High), Low
related_files: [pyscf_runner.py]
defects: "#1 logger 미선언, #2 regex 이중 이스케이프, #3 frontier gap 변수 명명"
---

# R1-A: 백엔드 내부 결함 — pyscf_runner.py

> 1차 감사 | 카테고리 A | 결함 3건

---

## 결함 #1: `logger` 미선언 — `run_geometry_optimization`에서 NameError — **P0 Critical**

`run_geometry_optimization` 함수 내부에서 `logger.info(...)`, `logger.warning(...)` 호출이 여러 곳에 있으나, 이 모듈에는 `logger = logging.getLogger(__name__)` 선언이 없습니다. 또한 `import logging` 자체도 없습니다. 실행 시 `NameError: name 'logger' is not defined`가 발생하여 **geometry optimization이 완전히 실패**합니다.

```python
# pyscf_runner.py, run_geometry_optimization 내부 (약 line 750+)
logger.info("geometric solver not found, trying berny")   # ← NameError
logger.warning(f"geometric solver failed: {e}, ...")       # ← NameError
logger.warning(f"Geometry optimization failed: {exc}")     # ← NameError
```

**수정:**

```python
# pyscf_runner.py 상단, import 섹션에 추가
import logging
logger = logging.getLogger(__name__)
```

---

## 결함 #2: `_lookup_builtin_xyz` — regex 이중 이스케이프로 noise word 필터링 실패 — **P1 High**

`_lookup_builtin_xyz` 함수의 noise 필터링 코드가 Python raw string이 아닌 일반 string에서 `\\b`를 사용하고 있어 `\b` (word boundary)가 아닌 리터럴 `\b`로 매칭을 시도합니다. 결과적으로 noise 단어가 제거되지 않아 구조체 조회에 실패할 수 있습니다.

```python
# 현재 (잘못됨)
for n in noise:
    qc = re.sub(rf"\\b{n}\\b", " ", qc, flags=re.I)
qc = re.sub(r"\\s+", " ", qc).strip()
```

**수정:**

```python
for n in noise:
    qc = re.sub(rf"\b{n}\b", " ", qc, flags=re.I)
qc = re.sub(r"\s+", " ", qc).strip()
```

---

## 결함 #3: `_extract_frontier_gap` — 변수 명명 혼동 — **Low**

`best_homo`와 `best_lumo`가 동일 `info` 객체를 참조합니다. 같은 channel의 info 객체에 homo와 lumo 정보가 모두 들어있으므로 값 자체는 정확하지만, 의미적 명확성을 위해 수정을 권장합니다.

```python
# 현재 코드
if best_gap is None or gap_ha < best_gap:
    best_gap = gap_ha
    best_homo = info
    best_lumo = info   # ← best_lumo도 같은 info 참조
```

**수정:**

```python
if best_gap is None or gap_ha < best_gap:
    best_gap = gap_ha
    best_channel_info = info

# 이후:
if best_channel_info:
    out["homo_energy_hartree"] = best_channel_info["homo_energy_hartree"]
    out["homo_energy_ev"] = best_channel_info["homo_energy_ev"]
    out["homo_index"] = best_channel_info["homo_index"]
    out["lumo_energy_hartree"] = best_channel_info["lumo_energy_hartree"]
    out["lumo_energy_ev"] = best_channel_info["lumo_energy_ev"]
    out["lumo_index"] = best_channel_info["lumo_index"]
```

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
