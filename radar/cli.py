"""Money Radar v2 — command line.

  python -m radar run              the always-on service (scheduler + Telegram bot)
  python -m radar watch            one watch pass now: fetch, score, alert
  python -m radar digest           one digest now: research + email + Telegram summary
  python -m radar sources doctor   test every source live (no AI, nothing sent)
  python -m radar status           what /status shows in Telegram
  python -m radar telegram-id      print your Telegram chat id and user id
  python -m radar import-v1        copy v1's state/ files into the database (no duplicate alerts)
  python -m radar backup           snapshot the database to data/backups now
  python -m radar health           exit 0 if the service is alive (used by Docker)

Add --dry-run to print messages instead of sending and keep the database unchanged,
--fake-ai to skip Claude (testing only).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

import httpx

from radar import __version__
from radar.core.config import Config
from radar.core.db import Database
from radar.core.logs import setup_logging
from radar.core.timeutil import ago, now_utc, parse_iso

HEALTHY_WITHIN = timedelta(minutes=5)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m radar", description=f"Money Radar v{__version__}")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    def with_flags(name: str, help_: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--dry-run", action="store_true", help="print messages instead of sending; don't save")
        sp.add_argument("--fake-ai", action="store_true", help="skip Claude (testing only)")
        return sp

    with_flags("run", "run the always-on service")
    with_flags("watch", "one watch pass now")
    with_flags("digest", "one digest now")
    src = sub.add_parser("sources", help="source tools")
    src.add_argument("action", choices=["doctor"])
    sub.add_parser("status", help="print the status summary")
    sub.add_parser("telegram-id", help="print your Telegram chat id and user id")
    imp = sub.add_parser("import-v1", help="import v1 state/ files")
    imp.add_argument("--state-dir", default=None, help="defaults to ./state")
    sub.add_parser("backup", help="snapshot the database now")
    sub.add_parser("health", help="exit 0 if the service heartbeat is fresh")
    return p


async def _one_shot(config: Config, job: str, dry_run: bool, fake_ai: bool) -> int:
    from radar.app import build_context
    from radar.jobs import run_job
    from radar.opportunities.watch import run_watch
    from radar.reports.digest import run_digest

    s = config.secrets
    bot = None
    if s.telegram_ready and not dry_run:
        from telegram import Bot

        bot = Bot(s.telegram_bot_token.get_secret_value())
        await bot.initialize()
    ctx = build_context(config, dry_run=dry_run, fake_ai=fake_ai, bot=bot)
    try:
        result = await run_job(ctx, job, run_watch if job == "watch" else run_digest)
    finally:
        await ctx.aclose()
        if bot:
            await bot.shutdown()
    if result is None:
        return 1
    print(f"{job}: {result.summary()}")
    return 0


async def _doctor(config: Config) -> int:
    from radar.core.http import make_client
    from radar.opportunities.sources import fetch_source

    sources = config.app.enabled_sources
    async with make_client() as client:
        results = await asyncio.gather(*(fetch_source(client, s, config.settings) for s in sources))
    bad = 0
    items = []
    for r in results:
        print(f"{'OK  ' if r.ok else 'FAIL'} {r.source.name}: {r.message}")
        bad += not r.ok
        items.extend(r.items or [])
    disabled = [s.name for s in config.app.sources if not s.enabled]
    if disabled:
        print(f"(disabled: {', '.join(disabled)})")
    print(f"\n{len(items)} posts passed filters. Newest:")
    for item in sorted(items, key=lambda i: i.published or "", reverse=True)[:10]:
        print(f"  · {item.title[:90]}  ({item.source})")
    return 1 if bad else 0


async def _telegram_id(config: Config) -> int:
    token = config.secrets.telegram_bot_token
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first.")
        return 1
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"https://api.telegram.org/bot{token.get_secret_value()}/getUpdates")
    data = resp.json()
    if resp.status_code == 409:
        print("The service is running and reading updates. Stop it first (docker compose stop), then retry.")
        return 1
    found = {}
    for update in data.get("result", []):
        msg = update.get("message") or {}
        chat, user = msg.get("chat") or {}, msg.get("from") or {}
        if chat.get("id"):
            found[(chat["id"], user.get("id"))] = user.get("username") or user.get("first_name") or chat.get("title")
    if not found:
        print("No messages found. Open your bot in Telegram, press Start, send it any message, then run this again.")
        return 1
    for (chat_id, user_id), name in found.items():
        print(f"TELEGRAM_CHAT_ID={chat_id}\nTELEGRAM_OWNER_ID={user_id}   ({name})")
    return 0


def _health(config: Config) -> int:
    if not config.paths.db.exists():
        print("no database yet")
        return 1
    db = Database.open(config.paths.db)
    try:
        beat = parse_iso(db.get("heartbeat"))
    finally:
        db.close()
    if beat and now_utc() - beat <= HEALTHY_WITHIN:
        print(f"ok · heartbeat {ago(beat)}")
        return 0
    print(f"stale · heartbeat {ago(beat)}")
    return 1


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config = Config()
    setup_logging(config.secrets.secret_values())
    cmd = args.command

    if cmd == "run":
        from radar.app import serve

        asyncio.run(serve(config, dry_run=args.dry_run, fake_ai=args.fake_ai))
        code = 0
    elif cmd in ("watch", "digest"):
        code = asyncio.run(_one_shot(config, cmd, args.dry_run, args.fake_ai))
    elif cmd == "sources":
        code = asyncio.run(_doctor(config))
    elif cmd == "status":
        from radar.app import build_context
        from radar.core.notify import plain
        from radar.reports.status import status_text

        async def _status() -> None:
            ctx = build_context(config)
            ctx.started_at = parse_iso(ctx.db.get("heartbeat")) or now_utc()
            print(plain(status_text(ctx)).replace("Up since", "Last heartbeat"))
            await ctx.aclose()

        asyncio.run(_status())
        code = 0
    elif cmd == "telegram-id":
        code = asyncio.run(_telegram_id(config))
    elif cmd == "import-v1":
        from pathlib import Path

        from radar.importer import import_v1_state

        db = Database.open(config.paths.db)
        counts = import_v1_state(db, Path(args.state_dir) if args.state_dir else config.paths.v1_state)
        db.close()
        print(f"imported from v1: {counts['seen']} seen posts, {counts['queued']} queued matches, "
              f"{counts['research_urls']} research links")
        code = 0
    elif cmd == "backup":
        db = Database.open(config.paths.db)
        path = db.backup_to(config.paths.backups, config.service.backup_keep_days)
        db.close()
        print(f"backup saved: {path}")
        code = 0
    elif cmd == "health":
        code = _health(config)
    else:  # pragma: no cover — argparse rejects unknown commands
        code = 2
    sys.exit(code)
