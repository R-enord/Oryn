"""Money Radar — command line entry point.

  python -m agent watch        hourly: fetch feeds, score, instant Telegram alerts
  python -m agent digest       daily: web research + morning email + Telegram summary
  python -m agent check        test every source (no AI, nothing sent)
  python -m agent telegram-id  print your Telegram chat id

Add --dry-run to print messages instead of sending, --fake-ai to skip Claude (testing only).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import requests

from . import config, notify, render, researcher, scorer, sources, state

LAGOS = timezone(timedelta(hours=1))


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.env("ANTHROPIC_API_KEY", required=True))


def _telegram():
    return config.env("TELEGRAM_BOT_TOKEN"), config.env("TELEGRAM_CHAT_ID")


def cmd_watch(args) -> None:
    settings, srcs = config.load_config()
    seen: dict = state.load("seen.json", {})
    queue: list = state.load("queue.json", [])

    items, report = sources.collect(srcs, settings)
    for name, msg in report:
        print(f"[source] {name}: {msg}")

    new = sorted((i for i in items if i.id not in seen), key=lambda i: i.published or "", reverse=True)
    batch = new[: int(settings["max_items_per_run"])]
    print(f"{len(items)} posts passed filters · {len(new)} new · scoring {len(batch)}")

    if batch:
        if args.fake_ai:
            results, processed = scorer.fake_score(batch)
        else:
            results, processed = scorer.score_items(_client(), batch, config.load_profile_text(), settings)

        now = datetime.now(timezone.utc).isoformat()
        alerts = []
        for item in batch:
            if item.id not in processed:
                continue  # batch failed; try again next run
            seen[item.id] = now
            r = results.get(item.id)
            if not r or r.get("track") == "skip" or int(r.get("score", 0)) < int(settings["digest_score"]):
                continue
            rec = {**item.to_dict(), "scored_at": now,
                   **{k: r.get(k) for k in ("score", "track", "pay", "location_ok", "why", "pitch", "red_flags")}}
            queue.append(rec)
            if rec["score"] >= int(settings["alert_score"]) and rec.get("location_ok") != "no":
                alerts.append(rec)

        alerts.sort(key=lambda r: r["score"], reverse=True)
        token, chat = _telegram()
        for rec in alerts[: int(settings["max_alerts_per_run"])]:
            rec["alerted"] = notify.telegram_send(render.telegram_alert(rec), token, chat, args.dry_run)
        print(f"{len(alerts)} instant alerts · {len(queue)} saved for the digest")

    if not args.dry_run:
        state.save("seen.json", state.prune_seen(seen))
        state.save("queue.json", queue[-300:])


def cmd_digest(args) -> None:
    settings, _ = config.load_config()
    queue: list = state.load("queue.json", [])
    reported: list = state.load("reported.json", [])
    now = datetime.now(timezone.utc)
    date_label = now.astimezone(LAGOS).strftime("%a %d %b %Y")

    if args.fake_ai:
        research = researcher.fake_research(now)
    else:
        try:
            research = researcher.run_research(_client(), config.load_profile_text(), settings, reported, now)
        except Exception as exc:  # noqa: BLE001 — still send the matches
            label, _ = researcher.todays_focus(now)
            research = {"focus": label, "picks": [], "insight": "", "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}

    matches = sorted(queue, key=lambda r: r.get("score", 0), reverse=True)
    picks = research.get("picks", [])
    subject = f"Money Radar · {date_label} · {len(matches)} matches, {len(picks)} research picks"

    emailed = notify.email_send(
        subject,
        render.digest_html(date_label, matches, research),
        render.digest_text(date_label, matches, research),
        config.env("EMAIL_USER"), config.env("EMAIL_APP_PASSWORD"), config.env("EMAIL_TO"),
        config.env("SMTP_HOST") or "smtp.gmail.com", int(config.env("SMTP_PORT") or 465),
        args.dry_run,
    )
    token, chat = _telegram()
    notify.telegram_send(render.telegram_digest(date_label, matches, research), token, chat, args.dry_run)

    if emailed and not args.dry_run:
        state.save("queue.json", [])  # keep matches for tomorrow if the email failed
    reported.extend(p["url"] for p in picks if p.get("url"))
    if not args.dry_run:
        state.save("reported.json", reported[-300:])
    status = "dry run" if args.dry_run else ("sent" if emailed else "NOT sent")
    print(f"digest: {len(matches)} matches, {len(picks)} picks, email {status}")


def cmd_check(args) -> None:
    settings, srcs = config.load_config()
    items, report = sources.collect(srcs, settings)
    for name, msg in report:
        print(f"[source] {name}: {msg}")
    print(f"\n{len(items)} unique posts passed filters. Newest:")
    for item in sorted(items, key=lambda i: i.published or "", reverse=True)[:10]:
        print(f"  · {item.title[:90]}  ({item.source})")


def cmd_telegram_id(args) -> None:
    token = config.env("TELEGRAM_BOT_TOKEN", required=True)
    data = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    chats = {}
    for update in data.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not chats:
        print("No messages found. Open your bot in Telegram, press Start, send it any message, then run this again.")
    for cid, name in chats.items():
        print(f"TELEGRAM_CHAT_ID = {cid}   ({name})")


def cli() -> None:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Money Radar")
    parser.add_argument("command", choices=["watch", "digest", "check", "telegram-id"])
    parser.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    parser.add_argument("--fake-ai", action="store_true", help="skip Claude (testing only)")
    args = parser.parse_args()
    {"watch": cmd_watch, "digest": cmd_digest, "check": cmd_check, "telegram-id": cmd_telegram_id}[args.command](args)
