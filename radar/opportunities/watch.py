"""The watch job: fetch sources → drop seen posts → score new ones → store → instant alerts (v1 `watch`)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from radar.context import Context
from radar.core.db import OPPORTUNITY_RESULT_FIELDS
from radar.core.timeutil import iso
from radar.reports import render

from . import scorer
from .sources import SourceResult, collect

log = logging.getLogger(__name__)


@dataclass
class WatchResult:
    passed: int = 0
    new: int = 0
    scored: int = 0
    matches: int = 0
    alerts_sent: int = 0
    alerts_failed: int = 0  # tried, but Telegram didn't take it (still goes in the digest)
    alerts_held: int = 0    # over max_alerts_per_run (digest only)
    sources: list[SourceResult] = field(default_factory=list)

    @property
    def failed_sources(self) -> list[str]:
        return [r.source.name for r in self.sources if not r.ok]

    def summary(self) -> str:
        text = (f"{self.passed} passed filters · {self.new} new · {self.scored} scored · {self.matches} matches · "
                f"{self.alerts_sent} alerts sent")
        if self.alerts_failed:
            text += f" · {self.alerts_failed} alerts NOT delivered (Telegram)"
        if self.alerts_held:
            text += f" · {self.alerts_held} over the per-run cap (digest only)"
        if self.failed_sources:
            text += f" · failed sources: {', '.join(self.failed_sources)}"
        return text


async def run_watch(ctx: Context) -> WatchResult:
    settings = ctx.config.settings
    items, source_results = await collect(ctx.http, ctx.config.app.enabled_sources, settings)
    result = WatchResult(passed=len(items), sources=source_results)

    for res in source_results:
        log.info("[source] %s: %s", res.source.name, res.message)
        ctx.db.record_source_result(res.source.name, res.source.type, res.source.url, ok=res.ok,
                                    count=res.fetched if res.ok else None, error=res.error)

    seen = ctx.db.seen_ids(i.id for i in items)
    new = sorted((i for i in items if i.id not in seen), key=lambda i: i.published or "", reverse=True)
    batch = new[: settings.max_items_per_run]
    result.new = len(new)
    if not batch:
        log.info("watch: %s", result.summary())
        return result

    if ctx.fake_ai:
        scores, processed = scorer.fake_score(batch)
    else:
        scores, processed = await scorer.score_items(ctx.llm, batch, ctx.config.profile_text, settings)

    now = iso()
    alerts: list[dict] = []
    for item in batch:
        if item.id not in processed:
            continue  # its batch failed; it stays unseen and is retried next run
        r = scores.get(item.id)
        if not r:
            continue
        result.scored += 1
        rec = {**item.to_dict(), "fetched_at": now, **{k: r.get(k) for k in OPPORTUNITY_RESULT_FIELDS}}
        ctx.db.save_opportunity(rec, r, now)
        if r["track"] == "skip" or r["score"] < settings.digest_score:
            continue
        result.matches += 1
        if r["score"] >= settings.alert_score and r.get("location_ok") != "no":
            alerts.append(rec)
    ctx.db.mark_seen(processed, now)

    alerts.sort(key=lambda r: r["score"], reverse=True)
    to_send = alerts[: settings.max_alerts_per_run]
    for rec in to_send:
        if await ctx.notifier.send(render.telegram_alert(rec)):
            ctx.db.mark_alerted(rec["id"])
            result.alerts_sent += 1
        else:
            result.alerts_failed += 1
    result.alerts_held = len(alerts) - len(to_send)
    log.info("watch: %s", result.summary())
    return result
