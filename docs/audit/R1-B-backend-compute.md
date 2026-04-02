---
audit_round: 1
category: B
priority: P1 (Medium)
related_files: [compute.py]
defects: "#4 Race Condition, #5 디스크 저장 누락, #6 빈 메시지 처리 (확인완료)"
---

# R1-B: 백엔드 라우팅/상태 관리 결함 — compute.py

> 1차 감사 | 카테고리 B | 결함 3건 (1건 확인완료)

---

## 결함 #4: `InMemoryJobManager._run_job` — Race Condition — **Medium**

`_run_job` 내부에서 `job` 변수가 lock 바깥에서 참조됩니다. `job.payload`는 submit 시점에 설정되고 이후 변경되지 않으므로 실질적인 data race는 아니지만, 방어적 코딩 원칙에 따라 lock 내에서 payload를 복사하는 것이 안전합니다.

```python
# 현재 (lock 밖에서 job.payload 접근)
try:
    result = _run_direct_compute(job.payload, ...)  # ← job은 lock 밖에서 참조!
```

**수정:**

```python
def _run_job(self, job_id: str) -> None:
    with self.lock:
        job = self.jobs[job_id]
        job.status = "running"
        job.started_at = _now_ts()
        job.updated_at = job.started_at
        job.step = "starting"
        job.message = "Starting job"
        self._append_event(job, "job_started", "Job started")
        payload_copy = dict(job.payload)  # ← lock 내에서 복사

    try:
        result = _run_direct_compute(payload_copy, progress_callback=progress_callback)
```

---

## 결함 #5: `InMemoryJobManager` — `_save_to_disk` 미호출 — **Medium**

Job이 완료되거나 실패해도 `_save_to_disk()`가 호출되지 않아 서버 재시작 시 최신 완료 결과가 유실됩니다.

**수정:** `_run_job`의 `completed`와 `failed` 블록 끝에 추가:

```python
# completed 블록 끝
self._save_to_disk()

# failed 블록(들) 끝
self._save_to_disk()
```

---

## 결함 #6: `_prepare_payload` — 빈 string 처리 — **확인 완료 (결함 아님)**

`raw_message`가 빈 string이면 `_safe_plan_message("")`가 호출되지만, 이후 `_merge_plan_into_payload`에서 `structure_query`가 없는 상태로 진행되어 HTTP 400이 발생합니다. 이는 의도된 동작입니다.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
