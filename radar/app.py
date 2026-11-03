"""The always-on service: scheduler (watch, digest, backups, heartbeat) + Salam's Telegram bot."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.ext import ContextTypes

from radar import __version__
from radar.context import Context
from radar.core.bot import build_application, set_command_menu
from radar.core.config import Config, ServiceConfig
from radar.core.db import Database
from radar.core.http import make_client
from radar.core.llm import LLM
from radar.core.notify import Notifier
from radar.core.timeutil import iso, local, now_utc
from radar.jobs import run_job
from radar.opportunities.watch import run_watch
from radar.reports.digest import digest_attempts, run_digest
from radar.reports.status import status_text

log = logging.getLogger(__name__)

HELP = """📡 <b>Money Radar</b> (Phase 0)
I check your job sources every {every} min and ping you when a post scores {alert}+.
Every morning at {digest} you get the digest: research picks plus every match since the last one.

/status · is everything running?
/scan · check all sources now
/today · send today's digest now (runs web research, costs a few cents)
/help · this message

Coming next: feedback buttons, pitch drafts, pipeline and earnings (Phase 2)."""


def build_context(config: Config, *, dry_run: bool = False, fake_ai: bool = False, bot=None,
                  db: Database | None = None) -> Context:
    s = config.secrets
    db = db or Database.open(config.paths.db, dry_run=dry_run)
    llm = LLM(s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None, db)
    notifier = Notifier(
        bot, s.telegram_chat_id,
        email_user=s.email_user,
        email_password=s.email_app_password.get_secret_value() if s.email_app_password else None,
        email_to=s.email_to, smtp_host=s.smtp_host, smtp_port=s.smtp_port, dry_run=dry_run,
    )
    return Context(config=config, db=db, http=make_client(), llm=llm, notifier=notifier,
                   fake_ai=fake_ai, dry_run=dry_run)


MAX_DIGEST_ATTEMPTS_PER_DAY = 3


def digest_catch_up_due(now_local: datetime, digest_time: time, last_sent_date: str | None,
                        attempts_today: int) -> bool:
    """True if today's digest time has passed and today's digest hasn't reached Salam (e.g. after downtime).

    The attempt cap stops a crash loop from re-running paid research on every restart.
    """
    return (now_local.time() >= digest_time and last_sent_date != now_local.date().isoformat()
            and attempts_today < MAX_DIGEST_ATTEMPTS_PER_DAY)


# ---------- scheduled jobs ----------

async def _quiet(coro) -> None:
    """Top of a scheduled task: a shutdown cancellation is expected, not an error."""
    try:
        await coro
    except asyncio.CancelledError:
        log.info("job cancelled because the service is stopping")


async def watch_job(ctx: Context) -> None:
    await _quiet(run_job(ctx, "watch", run_watch))


async def digest_job(ctx: Context) -> None:
    await _quiet(run_job(ctx, "digest", run_digest))


async def backup_job(ctx: Context) -> None:
    if ctx.dry_run:
        return

    async def _backup(c: Context):
        path = await asyncio.to_thread(c.db.backup_to, c.config.paths.backups, c.config.service.backup_keep_days)
        return _Summary(f"saved {path.name}")

    await _quiet(run_job(ctx, "backup", _backup))


async def housekeeping_job(ctx: Context) -> None:
    ctx.db.prune_seen(days=90)
    ctx.db.prune_runs(days=60)


async def heartbeat_job(ctx: Context) -> None:
    ctx.db.set("heartbeat", iso())


class _Summary:
    def __init__(self, text: str):
        self.text = text

    def summary(self) -> str:
        return self.text


# ---------- Telegram commands ----------

def _ctx(context: ContextTypes.DEFAULT_TYPE) -> Context:
    return context.application.bot_data["ctx"]


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    svc, st = ctx.config.service, ctx.config.settings
    await ctx.notifier.send(HELP.format(every=svc.watch_every_minutes, alert=st.alert_score,
                                        digest=escape(svc.digest_time)))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    await ctx.notifier.send(status_text(ctx))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    if ctx.lock("watch").locked():
        await ctx.notifier.send("🔎 A scan is already running; results will arrive shortly.")
        return
    await ctx.notifier.send("🔎 Scanning all sources now…")

    async def _run():
        result = await run_job(ctx, "watch", run_watch)
        if result is not None:
            await ctx.notifier.send(f"🔎 Scan done: {escape(result.summary())}")
        else:
            await ctx.notifier.send("🔎 Scan didn't finish; see /status.")

    context.application.create_task(_run())


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    if ctx.lock("digest").locked():
        await ctx.notifier.send("☀️ The digest is already being prepared.")
        return
    await ctx.notifier.send("☀️ Preparing today's digest. Research takes a minute or two…")
    context.application.create_task(digest_job(ctx))


COMMANDS = {"start": cmd_help, "help": cmd_help, "status": cmd_status, "scan": cmd_scan, "today": cmd_today}


# ---------- service ----------

def build_scheduler(ctx: Context) -> AsyncIOScheduler:
    svc: ServiceConfig = ctx.config.service
    tz = ZoneInfo(svc.timezone)
    now = now_utc()
    digest_at = svc.as_time(svc.digest_time)
    backup_at = svc.as_time(svc.backup_time)
    sched = AsyncIOScheduler(timezone=tz)
    common = {"args": [ctx], "max_instances": 1, "coalesce": True}
    sched.add_job(watch_job, IntervalTrigger(minutes=svc.watch_every_minutes),
                  next_run_time=now + timedelta(seconds=20), id="watch", misfire_grace_time=600, **common)
    sched.add_job(digest_job, CronTrigger(hour=digest_at.hour, minute=digest_at.minute, timezone=tz),
                  id="digest", misfire_grace_time=3600, **common)
    sched.add_job(backup_job, CronTrigger(hour=backup_at.hour, minute=backup_at.minute, timezone=tz),
                  id="backup", misfire_grace_time=3600, **common)
    sched.add_job(housekeeping_job, CronTrigger(hour=4, minute=10, timezone=tz), id="housekeeping", **common)
    sched.add_job(heartbeat_job, IntervalTrigger(minutes=1), next_run_time=now, id="heartbeat", **common)
    today = local(now, tz).date().isoformat()
    if digest_catch_up_due(local(now, tz), digest_at, ctx.db.get("digest.last_sent_date"),
                           digest_attempts(ctx.db, today)):
        log.info("today's digest hasn't run yet; running it shortly")
        sched.add_job(digest_job, DateTrigger(now + timedelta(seconds=90)), id="digest-catch-up", **common)
    return sched


async def serve(config: Config, *, dry_run: bool = False, fake_ai: bool = False) -> None:
    s = config.secrets
    application = None
    if s.telegram_ready:
        application = build_application(s.telegram_bot_token.get_secret_value(), s.owner_id, s.telegram_chat_id,
                                        COMMANDS)
    else:
        log.warning("Telegram is not configured; alerts will be printed to the log only")
    ctx = build_context(config, dry_run=dry_run, fake_ai=fake_ai, bot=application.bot if application else None)
    if not ctx.llm.available and not fake_ai:
        log.warning("ANTHROPIC_API_KEY is not set; scoring and research will fail until it is")

    log.info("Money Radar v%s starting · db %s · %d sources · watch every %d min · digest %s %s%s",
             __version__, "in-memory (dry run)" if dry_run else config.paths.db, len(config.app.enabled_sources),
             config.service.watch_every_minutes, config.service.digest_time, config.service.timezone,
             " · DRY RUN" if dry_run else "")

    scheduler = build_scheduler(ctx)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        if application:
            application.bot_data["ctx"] = ctx
            await application.initialize()
            await application.start()
            await application.updater.start_polling(drop_pending_updates=True,
                                                    allowed_updates=["message", "callback_query"])
            await set_command_menu(application, s.telegram_chat_id)
        scheduler.start()
        if config.service.startup_message:
            await ctx.notifier.send(
                f"📡 Money Radar v{escape(__version__)} is running. Watching {len(config.app.enabled_sources)} "
                f"sources every {config.service.watch_every_minutes} min; digest daily at "
                f"{escape(config.service.digest_time)}. Send /help.")
        await stop.wait()
        log.info("shutting down")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if application:
            with contextlib.suppress(Exception):
                if application.updater and application.updater.running:
                    await application.updater.stop()
                if application.running:
                    await application.stop()
                await application.shutdown()
        await ctx.aclose()
