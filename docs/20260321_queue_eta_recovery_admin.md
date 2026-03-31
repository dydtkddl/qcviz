# 2026-03-21 Queue ETA / Stale Recovery / Admin Dashboard Upgrade

## Summary

This update hardens the split `web + Redis/arq worker` runtime by adding queue ETA estimation, stale-running-job recovery, worker heartbeat awareness, and richer admin/user queue visibility in the web UI.

## Backend changes

- `RedisJobStore`
  - tracks `worker_id` on running/progress updates
  - computes `avg_runtime_seconds` from recent completed jobs
  - exposes `estimated_queue_drain_seconds`
  - exposes per-job `estimated_start_in_seconds`, `estimated_finish_in_seconds`, and `estimated_remaining_seconds`
  - annotates worker heartbeat entries with `age_seconds` and `is_stale`
  - can recover stale `running` jobs via `recover_stale_running_jobs()`
  - can clear worker heartbeats via `clear_worker_heartbeat()`

- `ArqJobManager`
  - periodically runs stale-job recovery
  - includes recovery metadata in queue summaries
  - exposes `operational_summary()` for health/admin endpoints
  - wait loop now re-checks stale recovery while polling

- `arq_worker`
  - sends periodic busy heartbeats during long computations
  - records `worker_id` onto running jobs
  - clears its heartbeat on graceful shutdown

## API changes

- `/compute/health`
  - now includes:
    - `queue.avg_runtime_seconds`
    - `queue.estimated_queue_drain_seconds`
    - `recovery`
    - `workers`

- `/admin/overview`
  - now includes:
    - `overview.recovery`
    - `overview.workers`
    - worker/recovery counts in `overview.counts`

## Frontend changes

- top-bar quota chip now shows:
  - active jobs for session or signed-in user
  - queue depth
  - queue ETA

- admin modal now includes:
  - `Workers` table
  - `Queue Recovery` table
  - richer queue stats
  - ETA hints on active jobs

## Validation

- `node --check src/qcviz_mcp/web/static/app.js`
- `node --check src/qcviz_mcp/web/static/chat.js`
- `pytest -q tests/test_redis_job_store.py tests/test_compute_api.py tests/test_admin_api.py tests/test_chat_api.py tests/test_auth_api.py tests/test_job_backend.py tests/test_web_server_smoke.py`

Result at implementation time:

- `42 passed, 2 warnings`

## Live runtime

Public service remains:

- `http://psid.aizen.co.kr/qcviz8817/`

Runtime mode:

- `redis-arq`

Observed health after rollout:

- queue ETA fields present
- stale recovery fields present
- worker heartbeat list present
