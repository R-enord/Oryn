"""The /status message (and `python -m radar status`)."""
from __future__ import annotations

from datetime import timedelta
from html import escape

from radar import __version__
from radar.context import Context
from radar.core.timeutil import ago, iso, local, now_utc, parse_iso


def _run_line(label: str, run: dict | None, tz: str) -> str:
    if not run:
        return f"{label}: not run yet"
    at = parse_iso(run.get("finished_at"))
    when = f"{local(at, tz).strftime('%a %H:%M')} ({ago(at)})" if at else "?"
    state = "✅" if run.get("ok") else "❌"
    return f"{label}: {state} {when} · {escape(run.get('summary') or '')}"


def status_text(ctx: Context) -> str:
    tz = ctx.config.service.timezone
    db = ctx.db
    now = now_utc()
    day_ago = iso(now - timedelta(hours=24))
    counts = db.count_opportunities_since(day_ago)
    usage = db.usage_since(day_ago)
    sources = db.sources()
    failing = [s for s in sources if s["fail_count"]]
    lines = [
        f"📡 <b>Money Radar v{__version__}</b> · Phase 0",
        f"Up since {local(ctx.started_at, tz).strftime('%a %d %b %H:%M')} ({ago(ctx.started_at)})"
        + (" · DRY RUN" if ctx.dry_run else "") + (" · FAKE AI" if ctx.fake_ai else ""),
        "",
        _run_line("Last watch", db.last_run("watch"), tz),
        _run_line("Last digest", db.last_run("digest"), tz),
        "",
        f"Last 24 h: {counts['scored']} posts scored, {counts['alerted']} alerts, "
        f"{usage['calls']} Claude calls ({usage['input_tokens']:,} in / {usage['output_tokens']:,} out tokens, "
        f"{usage['searches']} searches)",
        f"Sources: {len(sources) - len(failing)}/{len(sources)} healthy",
    ]
    for s in failing:
        lines.append(f"  ⚠️ {escape(s['name'])}: {s['fail_count']} failure(s) · {escape((s['last_error'] or '')[:120])}")
    lines += ["", f"Watch every {ctx.config.service.watch_every_minutes} min · digest daily at "
                  f"{ctx.config.service.digest_time} ({escape(tz)})"]
    return "\n".join(lines)
