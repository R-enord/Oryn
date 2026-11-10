"""One shared HTTP client for all sources: polite user agent, timeouts and a small retry policy.

Phase 1 adds conditional GET (ETag / If-Modified-Since) and per-host rate limits here.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

USER_AGENT = "money-radar/2.0 (personal job-alert service; single user)"
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
RETRY_STATUSES = {429, 500, 502, 503, 504}

log = logging.getLogger(__name__)


def make_client(**kwargs) -> httpx.AsyncClient:
    # No custom transport: httpx ignores HTTP(S)_PROXY settings when one is passed. Retries live in get().
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=TIMEOUT,
        follow_redirects=True,
        **kwargs,
    )


async def get(client: httpx.AsyncClient, url: str, *, attempts: int = 3, backoff: float = 2.0) -> httpx.Response:
    """GET with retries on 429/5xx and network errors. Raises on the final failure."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url)
            if resp.status_code in RETRY_STATUSES and attempt < attempts:
                await asyncio.sleep(_retry_after(resp) or backoff * attempt)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < attempts:
                await asyncio.sleep(backoff * attempt)
    raise last_exc or RuntimeError(f"GET {url} failed")


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return min(float(value), 60.0) if value else None
    except ValueError:
        return None
