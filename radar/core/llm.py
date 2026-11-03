"""Single entry point for Claude calls, so usage is logged in one place.

Phase 1 adds cost estimates and the daily/monthly budget guard here.
"""
from __future__ import annotations

import logging
from typing import Any

from .db import Database

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No API key configured."""


class LLM:
    def __init__(self, api_key: str | None, db: Database | None = None, *, client: Any = None):
        self.db = db
        if client is not None:
            self.client = client
        elif api_key:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=api_key, max_retries=3, timeout=600.0)
        else:
            self.client = None

    @property
    def available(self) -> bool:
        return self.client is not None

    async def create(self, purpose: str, **params: Any) -> Any:
        if self.client is None:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        resp = await self.client.messages.create(**params)
        self._record(purpose, params.get("model", ""), resp)
        return resp

    def _record(self, purpose: str, model: str, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        server_tools = getattr(usage, "server_tool_use", None)
        row = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            "searches": int(getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0,
        }
        log.info("claude %s · %s · in %d · out %d · cache %d · searches %d", purpose, model, row["input_tokens"],
                 row["output_tokens"], row["cache_read_tokens"], row["searches"])
        if self.db is not None:
            try:
                self.db.record_usage(purpose=purpose, model=model, **row)
            except Exception:  # noqa: BLE001 — bookkeeping must never break a run
                log.exception("could not record usage")
