# 2026-03-21 Redis/arq Worker Activation Guide

## 목적

이 문서는 현재 QCViz 코드베이스에 추가된 `Redis/arq` 외부 작업 큐 백엔드를 실제로 켜는 최소 절차를 정리한다. 기본 동작은 여전히 `inmemory-threadpool`이지만, 이제 `QCVIZ_JOB_BACKEND=arq`로 바꾸면 웹 프로세스는 Redis에 job record를 저장하고, 실제 계산은 arq worker가 가져가서 실행하는 구조로 넘어갈 수 있다. 단, 이 모드는 `redis`, `arq` Python 패키지와 실행 중인 Redis 서버가 있어야 한다.

## 필요한 패키지

프로젝트의 optional dependency에 `worker` extra를 추가해 두었다. 따라서 worker 모드를 쓰려면 대략 다음 형태로 설치하면 된다.

```bash
pip install ".[worker]"
```

여기에는 최소한 다음이 포함된다.

- `redis>=5`
- `arq>=0.26`

## 필요한 환경 변수

외부 큐 모드를 켜려면 웹과 worker 양쪽 모두 아래 값을 공유해야 한다.

```bash
export QCVIZ_JOB_BACKEND=arq
export QCVIZ_REDIS_URL=redis://127.0.0.1:6379/0
export QCVIZ_REDIS_PREFIX=qcviz
export QCVIZ_ARQ_QUEUE_NAME=qcviz-jobs
export QCVIZ_JOB_MAX_WORKERS=1
export QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION=2
export QCVIZ_MAX_ACTIVE_JOBS_PER_USER=3
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
```

중요한 점은 `QCVIZ_JOB_MAX_WORKERS`가 이제 웹 threadpool 의미가 아니라, 외부 worker 운영 기준의 concurrency 힌트이자 queue summary 기준값으로도 쓰인다는 것이다. CPU-bound 계산이 많으므로 처음에는 `1` 또는 `2`처럼 보수적으로 시작하는 편이 낫다.

## 웹 프로세스 실행

웹 서버는 기존과 거의 같지만, backend env만 external queue 쪽으로 바꾸면 된다.

```bash
uvicorn qcviz_mcp.web.app:app --host 0.0.0.0 --port 8817 --root-path /qcviz8817 --ws wsproto
```

이 상태에서 `/compute/health`와 `/admin/overview`의 `job_backend` 필드는 `redis-arq`로 바뀌게 된다.

## arq worker 실행

worker는 아래 모듈을 기준으로 실행한다.

```bash
arq qcviz_mcp.worker.arq_worker.WorkerSettings
```

worker는 `run_compute_job(job_id, payload)`를 받아 Redis에 저장된 job record를 `queued -> running -> completed/failed/cancelled`로 갱신한다. 진행 이벤트는 같은 Redis record에 누적되므로, 웹의 polling/WebSocket은 기존 API 계약을 유지한 채 그대로 쓸 수 있다.

## 현재 구현 범위

이번 단계에서 구현된 것은 다음까지다.

- Redis 기반 job record 저장
- session/owner/status index 저장
- queue summary / quota summary 계산
- arq enqueue bridge
- worker-side progress update
- external cancel flag 전달
- worker heartbeat key 작성

아직 다음은 운영 단계에서 추가로 보강하면 좋다.

- worker heartbeat 집계 대시보드
- stale running job recovery daemon
- retry/backoff 정책
- result payload 압축 또는 object storage 분리
- long-running job timeout 정책의 환경 변수화

## 검증 포인트

외부 큐 모드가 정상적으로 켜지면 아래를 우선 확인하면 된다.

1. `/compute/health`에서 `job_backend.name == "redis-arq"`
2. `/admin/overview`에서 `job_backend.external_queue == true`
3. job submit 직후 `status=queued`
4. worker가 잡으면 `status=running`
5. 완료 후 `result`와 `events`가 채워짐
6. cancel 요청 시 worker progress callback이 cancellation flag를 감지함

## 주의사항

현재 worker 구현은 progress callback 기반으로 cancel flag를 감지한다. 즉 아주 긴 블로킹 구간에서 callback 호출이 늦으면 cancel 반응도 늦어질 수 있다. 하지만 SCF/geometry/cube 단계는 이미 progress callback을 비교적 자주 올리도록 되어 있어 1차 운영에는 충분하다. 더 공격적인 cancel responsiveness가 필요하면 추후 PySCF callback 레벨에서 Redis flag를 직접 읽는 방향으로 더 내려가면 된다.
