import asyncio
import concurrent.futures
import os
import functools
from typing import Callable, Any

# SCF 계산은 CPU-bound이므로 ProcessPoolExecutor 사용
# 0으로 설정하면 직접 실행 (테스트 및 단일 프로세스 환경용)
_MAX_WORKERS = int(os.environ.get("QCVIZ_MAX_WORKERS", "2"))

if _MAX_WORKERS > 0:
    _executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=_MAX_WORKERS
    )
else:
    _executor = None

async def run_in_executor(func: Callable[..., Any], *args, **kwargs) -> Any:
    """CPU-bound 함수를 별도 프로세스에서 실행 (executor가 있을 경우)."""
    if _executor is None:
        return func(*args, **kwargs)
        
    loop = asyncio.get_running_loop()
    partial_func = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_executor, partial_func)


# 타임아웃 래퍼
async def run_with_timeout(func: Callable, timeout_seconds: float = 300.0, 
                           *args, **kwargs) -> Any:
    """계산에 타임아웃을 적용. 기본 5분."""
    try:
        return await asyncio.wait_for(
            run_in_executor(func, *args, **kwargs),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Computation timed out after {timeout_seconds}s."
        )
