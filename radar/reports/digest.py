"""The digest job: daily web research + every unsent match → email + Telegram summary (v1 `digest`)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from radar.context import Context
from radar.core.db import Database
from radar.core.timeutil import iso, local, now_utc
from radar.opportunities import researcher

from . import render

log = logging.getLogger(__name__)


@dataclass
class DigestResult:
    matches: int = 0
    picks: int = 0
    emailed: bool | None = None
    telegram_sent: bool = False
    delivered: bool = False
    research_error: str | None = None

    def summary(self) -> str:
        email = {True: "sent", False: "FAILED", None: "not configured"}[self.emailed]
        text = (f"{self.matches} matches, {self.picks} research picks, email {email}, "
                f"telegram {'sent' if self.telegram_sent else 'not sent'}")
        if self.research_error:
            text += f", research: {self.research_error}"
        return text


def digest_attempts(db: Database, today: str) -> int:
    """How many digests were started today (Lagos date)."""
    date, _, count = (db.get("digest.attempts") or "").partition(":")
    return int(count) if date == today and count.isdigit() else 0


async def run_digest(ctx: Context) -> DigestResult:
    settings = ctx.config.settings
    tz = ctx.config.service.timezone
    now = now_utc()
    now_local = local(now, tz)  # focus rotation and "Today is …" follow Salam's calendar, not UTC
    date_label = now_local.strftime("%a %d %b %Y")
    today = now_local.date().isoformat()
    ctx.db.set("digest.attempts", f"{today}:{digest_attempts(ctx.db, today) + 1}")

    if ctx.fake_ai:
        research = researcher.fake_research(now_local)
    else:
        try:
            research = await researcher.run_research(ctx.llm, ctx.config.profile_text, settings,
                                                     ctx.db.recent_research_urls(), now_local)
        except Exception as exc:  # noqa: BLE001 — still send the matches
            label, _ = researcher.todays_focus(now_local)
            log.warning("research failed: %s", exc)
            research = {"focus": label, "picks": [], "insight": "",
                        "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}

    matches = ctx.db.digest_queue(settings.digest_score)
    picks = research.get("picks", [])
    result = DigestResult(matches=len(matches), picks=len(picks), research_error=research.get("error"))
    subject = f"Money Radar · {date_label} · {len(matches)} matches, {len(picks)} research picks"

    if ctx.notifier.email_ready or ctx.dry_run:
        result.emailed = await ctx.notifier.email(subject, render.digest_html(date_label, matches, research),
                                                  render.digest_text(date_label, matches, research))
    result.telegram_sent = await ctx.notifier.send(
        render.telegram_digest(date_label, matches, research, email_sent=result.emailed))

    # Matches leave the queue once they reached Salam: by email if email is set up, else by Telegram.
    result.delivered = bool(result.emailed) if result.emailed is not None else result.telegram_sent
    if result.delivered:
        ctx.db.mark_digested([m["id"] for m in matches])
    ctx.db.save_research_picks(iso(now), research.get("focus", ""), picks)
    if result.delivered:
        ctx.db.set("digest.last_sent_date", today)
    log.info("digest: %s", result.summary())
    return result
