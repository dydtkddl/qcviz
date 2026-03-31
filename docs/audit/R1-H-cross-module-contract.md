---
audit_round: 1
category: H
priority: Medium
related_files: [compute.py, app.js]
defects: "#23 snapshot에 job_type 누락"
---

# R1-H: 크로스-모듈 데이터 계약 불일치

> 1차 감사 | 카테고리 H | 결함 1건

---

## 결함 #23: `_snapshot` 에 `job_type` 필드 없음 — **Medium**

Backend `compute.py`의 `_snapshot` 메서드가 반환하는 job 구조에 `job_type` 필드가 없어, 프론트엔드 `app.js`의 `getJobDetailLine`과 `getJobDisplayName`에서 항상 `"computation"` fallback이 사용됩니다.

**수정 (compute.py `_snapshot`):**

```python
snap = {
    "job_id": job.job_id,
    "status": job.status,
    "user_query": job.user_query,
    "job_type": job.payload.get("job_type", ""),  # 추가
    "molecule_name": job.payload.get("structure_query", ""),
    "method": job.payload.get("method", ""),
    "basis_set": job.payload.get("basis", ""),
    # ...
}
```

---

## 1차 감사 최종 보고 요약

| #   | 파일                      | 결함 유형                       | 심각도       | 상태    |
| --- | ------------------------- | ------------------------------- | ------------ | ------- |
| 1   | `pyscf_runner.py`         | `logger` 미선언 (NameError)     | **Critical** | ✅ 수정 |
| 2   | `pyscf_runner.py`         | regex 이중 이스케이프           | **High**     | ✅ 수정 |
| 3   | `pyscf_runner.py`         | frontier gap 변수 명명 혼동     | Low          | ✅ 수정 |
| 4   | `compute.py`              | Race condition (방어적)         | Medium       | ✅ 수정 |
| 5   | `compute.py`              | 디스크 저장 누락                | Medium       | ✅ 수정 |
| 7   | `agent.py`                | focus_tab "orbitals" 불일치     | **High**     | ✅ 수정 |
| 8   | `providers.py`            | focus_tab "orbitals" 불일치     | **High**     | ✅ 수정 |
| 9   | `providers.py`            | 한국어 키워드 오류              | Medium       | ✅ 수정 |
| 10  | `compute.py` ↔ `agent.py` | plan() 호출 시그니처 불일치     | **High**     | ✅ 수정 |
| 11  | `compute.py`              | advisor_focus_tab 매핑 누락     | **High**     | ✅ 수정 |
| 13  | `results.js`              | Object.keys on Array            | Low          | ✅ 수정 |
| 14  | `results.js`              | is_selected 필드 미존재         | Medium       | ✅ 수정 |
| 15  | `viewer.js`               | ESP isovalue 순서 오류          | **High**     | ✅ 수정 |
| 16  | `viewer.js`               | switchVizMode molecule fallback | Low          | ✅ 수정 |
| 17  | `viewer.js`               | 3Dmol 로드 실패 시 UI 미복원    | Medium       | ✅ 수정 |
| 19  | `app.js`                  | basis/basis_set 필드 불일치     | Medium       | ✅ 수정 |
| 23  | `compute.py`              | snapshot에 job_type 누락        | Medium       | ✅ 수정 |

**Critical 1건, High 5건, Medium 7건, Low 4건**

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
