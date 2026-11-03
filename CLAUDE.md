# CLAUDE.md — rules for working on Money Radar

**Start here:** read `docs/PROJECT_BRIEF.md` (source of truth), then `README.md`, `profile.yaml` and `config.yaml`. v1 code lives in `agent/` and works. Port it into v2; don't throw its logic away.

## Always
- Work in the phases in the brief (§11). At the end of each phase: run the tests, summarise what changed and what's next, and wait for Salam's go-ahead.
- Write tests alongside code. Run them before calling anything done.
- Keep `README.md` (Salam's plain-English guide) current as features land.
- Ask before adding a paid service, choosing a broker/exchange, or changing anything in the brief's §2.
- Keep secrets in `.env`. Never commit, log, print or put them in prompts.

## Never
- Never write a code path that places an order without an approved proposal record from Salam's Telegram user id inside its expiry window. Tests must prove this.
- Never enable live trading or switch the default mode away from `paper`.
- Never let LLM output change risk limits, the whitelist, or position sizes beyond limits.
- Never send messages, applications or emails to third parties on Salam's behalf.
- Never scrape sites whose terms forbid it (Upwork, Fiverr, LinkedIn).
- Never describe backtests or paper results as guarantees.

## Conventions
- Python 3.12, async (httpx, python-telegram-bot), SQLite (WAL), Pydantic settings, pytest + respx.
- Structured LLM output via forced tool use (see `agent/scorer.py`).
- One failing source or model call must never crash the service. Log it, count it, alert once.
- Times stored in UTC; shown to Salam in Lagos time (UTC+1).
