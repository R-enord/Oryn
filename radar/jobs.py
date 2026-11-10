"""Runs a job safely: one at a time, recorded in the `runs` table, and never allowed to crash the service.

If the same job fails 3 times in a row, Salam gets one Telegram notice (not one per failure),
and another when it recovers.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

from radar.context import Context

log = logging.getLogger(__name__)

ALERT_AFTER_FAILURES = 3


async def run_job(ctx: Context, name: str, fn: Callable[[Context], Awaitable[Any]]) -> Any | None:
    lock = ctx.lock(name)
    if lock.locked():
        log.info("%s is already running; skipping this trigger", name)
        return None
    async with lock:
        if name in ("watch", "digest"):
            error = ctx.config.reload()
            if error:
                log.warning(error)
        run_id = ctx.db.start_run(name)
        try:
            result = await fn(ctx)
        except asyncio.CancelledError:
            ctx.db.finish_run(run_id, False, "cancelled (service stopping)")
            raise
        except Exception as exc:  # noqa: BLE001 — log, count, alert once
            log.exception("%s failed", name)
            message = f"{exc.__class__.__name__}: {str(exc)[:300]}"
            ctx.db.finish_run(run_id, False, message)
            ctx.failures[name] = ctx.failures.get(name, 0) + 1
            if ctx.failures[name] == ALERT_AFTER_FAILURES:
                await ctx.notifier.send(f"⚠️ <b>{escape(name)}</b> has failed {ALERT_AFTER_FAILURES} times in a row.\n"
                                        f"Last error: <code>{escape(message)}</code>\n"
                                        "I'll keep retrying and tell you when it recovers.")
            return None
        summary = result.summary() if hasattr(result, "summary") else ""
        ctx.db.finish_run(run_id, True, summary)
        if ctx.failures.get(name, 0) >= ALERT_AFTER_FAILURES:
            await ctx.notifier.send(f"✅ <b>{escape(name)}</b> is working again.")
        ctx.failures[name] = 0
        return result
