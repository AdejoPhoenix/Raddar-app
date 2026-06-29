"""Shared HTTP helper: retry with exponential backoff + jitter on 429/5xx.

Every Tier-1 API client should fetch through this so transient upstream failures and rate
limits don't abort a pipeline run. Structured-logs each retry.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
from loguru import logger

_RETRY_STATUS = {429, 500, 502, 503, 504}


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    base_delay: float = 0.5,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request, retrying retryable statuses with backoff. Raises after the last try."""
    last: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code not in _RETRY_STATUS:
            return response
        last = response
        if attempt == max_attempts:
            break
        # honor Retry-After when present, else exponential backoff + jitter
        retry_after = response.headers.get("Retry-After")
        delay = (
            float(retry_after)
            if retry_after and retry_after.isdigit()
            else base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
        )
        logger.warning(
            "retrying {} {} after {} (attempt {}/{}, sleep {:.2f}s)",
            method, url, response.status_code, attempt, max_attempts, delay,
        )
        await asyncio.sleep(delay)

    assert last is not None
    last.raise_for_status()
    return last  # pragma: no cover
