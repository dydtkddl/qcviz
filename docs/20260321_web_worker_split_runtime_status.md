# 2026-03-21 Web/Worker Split Runtime Status

## What Is Implemented Now

현재 런타임은 기본적으로 `inmemory-threadpool` 백엔드를 사용한다. 즉 FastAPI 웹 프로세스가 `InMemoryJobManager`를 통해 계산 작업을 직접 thread pool에 제출하고, queue/depth/quota/admin overview도 같은 프로세스 메모리를 기준으로 노출한다. 이번 변경으로 중요한 점은 계산 제출 경로가 더 이상 `InMemoryJobManager` 생성 코드에 직접 고정되지 않고, `src/qcviz_mcp/web/job_backend.py`의 backend factory seam을 통해 초기화된다는 것이다. 따라서 지금은 in-memory로 안정적으로 돌리되, 이후 Redis/arq 외부 큐 백엔드로 넘어갈 때 compute route 전체를 다시 뜯지 않고 factory와 backend implementation만 교체하면 된다.

## Runtime Metadata Exposure

`/compute/health`와 `/admin/overview`에는 이제 `job_backend` 필드가 포함된다. 여기에는 `name`, `mode`, `external_queue`, `split_ready`, `worker_count`, `queue_driver`, `notes`가 들어간다. 현재 기본값은 `name=inmemory-threadpool`, `mode=single-process`, `external_queue=false`이다. 이 메타데이터를 프론트와 운영자가 같이 볼 수 있게 해 둔 이유는, 현재 서버가 단일 프로세스 기반인지 외부 큐 기반인지 실시간으로 구분하고 향후 운영 실수, 예를 들면 multi-worker uvicorn을 실수로 올리거나 아직 외부 큐가 연결되지 않은 상태에서 분리 배포를 시도하는 문제를 줄이기 위해서다.

## Environment Switch

새 환경 변수는 `QCVIZ_JOB_BACKEND`이다. 지금 지원되는 값은 사실상 `inmemory/threadpool/local`이며, `arq/redis/external`은 의도적으로 아직 활성화되지 않는다. 즉 운영자가 `QCVIZ_JOB_BACKEND=arq` 같은 값을 먼저 넣으면, 조용히 fallback하는 것이 아니라 명시적으로 runtime error를 내도록 했다. 이유는 반쯤 연결된 상태로 서비스가 떠서 job이 유실되는 상황이 더 위험하기 때문이다. 현재 코드는 “외부 큐로 갈 준비가 된 seam”을 제공하지만, 실제 외부 worker backend가 구현되기 전까지는 안정적으로 single-process 모드만 허용하는 상태다.

## Recommended Migration Path

다음 단계는 `Redis + arq`를 별도 서비스로 붙이고, 웹은 submit/list/get/cancel과 session/auth/clarification만 맡고, worker는 실제 `_run_direct_compute`를 수행하게 나누는 것이다. 이때 최소 단위는 1) Redis 연결 설정, 2) arq worker entrypoint, 3) job payload/result/event serialization, 4) worker heartbeat와 stale job recovery, 5) WebSocket progress를 위한 event polling/store다. 지금 queue overlay, quota, admin overview는 이미 있으므로, 외부 큐가 붙으면 그 데이터 소스만 바꾸면 된다. 즉 UX를 다시 짜는 단계가 아니라 backend 교체 단계가 된다.

## Operational Guardrails

지금 구조에서는 웹과 계산이 같은 머신을 공유하므로 `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `max_workers=1~2`처럼 conservative하게 두는 편이 낫다. 분리 이후에도 동일한 원칙이 중요하다. worker 프로세스 수를 늘리는 것보다 먼저 각 worker가 BLAS 스레드를 1로 고정하고, job별 time limit와 active quota를 지키는 편이 사이트 응답성 보호에 유리하다. 현재 quota, queue depth, admin overview, backend metadata는 그 운영 전환을 준비하기 위한 기반이며, 다음 구현 단계는 실제 Redis/arq worker backend를 이 seam 뒤에 넣는 것이다.
