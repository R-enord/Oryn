"""Fetch every enabled source concurrently. One broken source never stops the others."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from radar.core import http
from radar.core.config import Settings, SourceConfig

from .base import Item, passes
from .jobicy import parse_jobicy
from .remoteok import parse_remoteok
from .rss import parse_rss

log = logging.getLogger(__name__)

__all__ = ["FETCHERS", "Item", "SourceResult", "collect", "fetch_source"]


async def _fetch_rss(client: httpx.AsyncClient, src: SourceConfig) -> list[Item]:
    return parse_rss((await http.get(client, src.url)).content, src)


async def _fetch_jobicy(client: httpx.AsyncClient, src: SourceConfig) -> list[Item]:
    return parse_jobicy(json.loads((await http.get(client, src.url)).content), src)


async def _fetch_remoteok(client: httpx.AsyncClient, src: SourceConfig) -> list[Item]:
    return parse_remoteok(json.loads((await http.get(client, src.url)).content), src)


FETCHERS: dict[str, Callable[[httpx.AsyncClient, SourceConfig], Awaitable[list[Item]]]] = {
    "rss": _fetch_rss,
    "jobicy": _fetch_jobicy,
    "remoteok": _fetch_remoteok,
}


@dataclass
class SourceResult:
    source: SourceConfig
    ok: bool
    fetched: int = 0
    kept: int = 0
    error: str | None = None
    items: list[Item] | None = None

    @property
    def message(self) -> str:
        if not self.ok:
            return f"FAILED ({self.error})"
        return f"{self.fetched} fetched, {self.kept} passed filters"


async def fetch_source(client: httpx.AsyncClient, src: SourceConfig, settings: Settings) -> SourceResult:
    fetch = FETCHERS.get(src.type)
    if not fetch:
        return SourceResult(src, ok=False, error=f"unknown type '{src.type}'")
    try:
        raw = await fetch(client, src)
    except Exception as exc:  # noqa: BLE001 — log and move on
        return SourceResult(src, ok=False, error=f"{exc.__class__.__name__}: {str(exc)[:160]}")
    kept = [i for i in raw if i.url and passes(i, src, settings.exclude, settings.max_age_days)]
    return SourceResult(src, ok=True, fetched=len(raw), kept=len(kept), items=kept)


async def collect(client: httpx.AsyncClient, sources: list[SourceConfig],
                  settings: Settings) -> tuple[list[Item], list[SourceResult]]:
    results = await asyncio.gather(*(fetch_source(client, s, settings) for s in sources))
    unique: list[Item] = []
    ids: set[str] = set()
    for res in results:
        for item in res.items or []:
            if item.id not in ids:
                ids.add(item.id)
                unique.append(item)
    return unique, list(results)
