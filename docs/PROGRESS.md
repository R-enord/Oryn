# Build log

Where v2 stands, what was decided along the way, and what's open. Newest phase first.

## Phase 0: v1 ported to an always-on service ✅ built · ⏳ awaiting Salam's 24-hour VPS run

**Done when (brief §11):** v1 behaviour reproduced ✅ · tests pass ✅ (79, `make check`) · runs 24h on the VPS without errors ⏳ (Salam)

### What was built
- `radar/` package, one async process: APScheduler (watch every 30 min, digest 07:00 Lagos, backup 03:30, housekeeping, heartbeat) + python-telegram-bot polling.
- v1 logic ported, prompts and schema unchanged: sources (RSS, Jobicy, Remote OK) with v1 filters and the **same item ids** (v1's seen list imports cleanly); Haiku scorer with forced `save_scores` tool; Sonnet researcher with web search, weekday focus, `pause_turn` resume, link verification; v1 alert/digest rendering.
- SQLite (WAL) with forward-only migrations (`PRAGMA user_version`): `sources`, `seen`, `opportunities`, `research_picks`, `usage`, `runs`, `kv`. Every scored post is stored, including skips, for Phase 2 calibration.
- Telegram bot locked to `TELEGRAM_OWNER_ID` + `TELEGRAM_CHAT_ID`: a group −1 guard drops every other update before any handler, and each command also carries a user+chat filter. Tested through the real dispatcher. Commands: `/status`, `/scan`, `/today`, `/help`.
- Reliability: one failing source never breaks the others; a failed scoring batch is retried next run; a job that fails 3 times in a row sends one Telegram notice and one on recovery; a missed 07:00 digest is caught up after downtime (max 3 attempts/day, so a crash loop can't keep paying for research); config.yaml/profile.yaml edits apply on the next run (a broken config.yaml keeps the last good one).
- Secrets: `.env` via pydantic-settings `SecretStr`; a log filter masks every secret and the bot token inside Telegram API URLs (httpx logs them otherwise).
- Usage logging: every Claude call writes tokens and web-search count to `usage` (no cost estimate yet; Phase 1).
- Deploy: `Dockerfile` (non-root, healthcheck = fresh heartbeat), `docker-compose.yml` (restart unless-stopped, bind-mounted config/profile/data, log rotation), `deploy/radar.service` (no-Docker alternative), nightly gzip snapshots kept 14 days + `deploy/backup.sh` (rclone to a second location).
- CLI: `python -m radar run | watch | digest | sources doctor | status | telegram-id | import-v1 | backup | health`, with `--dry-run` (in-memory DB copy, prints instead of sending) and `--fake-ai`.
- CI: `.github/workflows/ci.yml` runs `make check` (ruff + pytest).

### Decisions and deviations from the brief
- `config.yaml` `web_search_tool` changed from `web_search_20250305` to `web_search_20260209`, the current version for Sonnet 5.5 (brief §10 asks to check). v1 reads the same file and works with it.
- Claude Python SDK is 2.x (`anthropic>=2,<3`), which talks API version `2026-10-21`. No code relies on `temperature` / `top_p` / `top_k`.
- Scorer keeps forced `tool_choice` because Claude Haiku 5.5 accepts it. Sonnet 5.5 / Opus 5.5 reject forced tool use, so Phase 2's pitch drafter (Sonnet) must use `tool_choice: auto` + `strict: true` or structured outputs.
- Module names: `core/bot.py` (brief: `core/telegram.py`) and `core/logs.py`, to avoid shadowing the `telegram` and `logging` packages.
- `sources doctor` exists now as v1's `check` (live fetch report); the persistent health alerts are Phase 1.
- Matches leave the digest queue once delivered: by email when email is configured, otherwise by Telegram (v1 kept them forever without email).
- Feed fixtures in `tests/fixtures/` follow each site's documented format; the build sandbox couldn't reach the sites. `sources doctor` on the VPS is the live check.

### Open for Salam (from brief §13)
1. VPS provider/specs → then follow `docs/V2_SETUP.md`.
2. Keep v1 on GitHub Actions as a backup during Phases 0–1? (recommended; may double-alert)
3. Monthly API budget (needed for Phase 1's budget guard).
4. Later: broker/exchange, watchlist, paper account size, risk defaults (Phases 3–5).

## Next: Phase 1 (not started)
Per-source cadence with ETag / If-Modified-Since, source health alerts (5 failures → one notice) and `/sources`, fuzzy title+company dedupe (14 days), cost estimates + daily/monthly budget guard + `/spend`. Done when new Blender Artists posts alert within 5 min.
