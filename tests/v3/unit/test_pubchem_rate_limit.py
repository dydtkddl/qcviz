"""Tests for PubChem start-interval rate limiting."""
from __future__ import annotations

import asyncio
import time

import pytest

from qcviz_mcp.services.pubchem_client import PubChemClient, _TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_no_wait_on_first_call():
    limiter = _TokenBucketRateLimiter(max_rps=4.0)
    t0 = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_token_bucket_enforces_rate():
    limiter = _TokenBucketRateLimiter(max_rps=4.0)
    times = []
    for _ in range(5):
        await limiter.acquire()
        times.append(time.monotonic())

    total = times[-1] - times[0]
    assert total >= 0.9


@pytest.mark.asyncio
async def test_token_bucket_burst_after_idle():
    limiter = _TokenBucketRateLimiter(max_rps=4.0)
    await limiter.acquire()
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_first_call_is_immediate_unlike_old_sleep():
    client = PubChemClient(rate_limit_rps=4.0)
    t0 = time.monotonic()
    await client._rate_limit()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05
