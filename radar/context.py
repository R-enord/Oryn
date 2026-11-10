"""Everything a job needs, built once and shared: config, database, HTTP client, Claude, notifier."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from radar.core.config import Config
from radar.core.db import Database
from radar.core.llm import LLM
from radar.core.notify import Notifier
from radar.core.timeutil import now_utc


@dataclass
class Context:
    config: Config
    db: Database
    http: httpx.AsyncClient
    llm: LLM
    notifier: Notifier
    fake_ai: bool = False
    dry_run: bool = False
    started_at: datetime = field(default_factory=now_utc)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)

    def lock(self, name: str) -> asyncio.Lock:
        if name not in self.locks:
            self.locks[name] = asyncio.Lock()
        return self.locks[name]

    async def aclose(self) -> None:
        await self.http.aclose()
        self.db.close()
