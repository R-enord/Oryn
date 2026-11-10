# Money Radar v2 — Project Brief for Claude Code

**Owner:** Salam (Abdulsalam Jamiu Adeniyi), Lagos, Nigeria (WAT, UTC+1)
**Status:** v1 is built and working (see §3). This brief defines v2: an always-on personal agent with two engines. The **Opportunity Engine** finds and helps win paid work. The **Market Desk** watches markets and news and proposes trades that Salam approves one by one.
**Source of truth:** this file. If something here conflicts with a request in chat, ask Salam before deviating.

---

## 1. Goal

Build a single-owner, 24/7 service on Salam's VPS that:

1. Finds money-making opportunities across the internet that match his skills (core) or that he could realistically take on (stretch), within seconds-to-minutes of them appearing where sources allow.
2. Helps him **act** on them: tailored pitch drafts, deadline reminders, a pipeline tracker, and earnings tracking.
3. Monitors markets and market-moving news, turns them into **structured trade proposals**, and executes **only after he explicitly approves each one**. It runs in paper mode by default.
4. Measures itself honestly: it records how good its opportunity scores and trade proposals turned out to be, and reports that weekly.

Owner context the agent is built around: freelance 3D artist (4+ yrs, Blender product viz/animation, furniture, arch/interior viz, hard-surface, UV work), video editor (DaVinci Resolve, Premiere Pro, After Effects, 3 yrs), learning Substance Painter, ZBrush, Go, web dev, Blender add-on development in Python. He is building toward his own creative agency and works via Upwork today. Full profile: `profile.yaml`.

## 2. Non-negotiables

These are hard requirements. They are not optimisations and must not be traded off for speed or features.

**Trading safety**
- **Every order needs a human approval record.** The executor must refuse any order that has no matching `approved` proposal row, approved by Salam's Telegram user id, inside the proposal's expiry window. No code path may bypass this, including tests run against a live broker.
- **Paper mode is the default.** Live mode requires all three: `trading.mode: live` in config, an env var `LIVE_TRADING_CONFIRM=I_UNDERSTAND_THE_RISK`, and at least 30 days / 30 closed paper trades on record. On first switch to live, the bot asks for a typed confirmation in Telegram.
- **The risk engine is deterministic code, not the LLM.** LLM output can propose; it can never change limits, sizes beyond limits, or the whitelist. Proposals that fail risk checks are dropped and logged, not "adjusted by the AI".
- **Kill switch.** `/halt` stops all new proposals and cancels open unfilled orders within one loop tick. `/resume` requires confirmation.
- **Broker/exchange API keys** must be trade-only (no withdrawals) and IP-restricted to the VPS where the provider supports it. Document this in the setup guide.
- No martingale, no averaging down outside a pre-defined plan, no leverage unless explicitly enabled in config with its own cap.

**General**
- **Single owner.** The Telegram bot must ignore every chat id and user id except Salam's (allowlist from env). Anyone can find and message a public bot.
- **Never send anything to a third party on Salam's behalf** (no auto-applying, no auto-emailing clients). The agent drafts; Salam sends.
- **Respect site terms.** Do not scrape sites that forbid it (Upwork, Fiverr, LinkedIn). Use official feeds/APIs, conditional requests and polite rates. Search (via Claude web search) is fine.
- **Secrets** live in `.env` only, are never committed, logged or echoed into prompts.
- **Honesty in outputs.** Never present a backtest or paper result as a guarantee. Reports always show losses and misses next to wins.

## 3. Current state (v1, working)

v1 runs on GitHub Actions (free, private repo). Code is in `agent/`; setup guide in `docs/V1_SETUP.md`.

| Piece | File | What it does |
|---|---|---|
| Config | `config.yaml`, `agent/config.py` | Settings + source list; loads `.env` locally |
| Profile | `profile.yaml` | Skills, avoid list, rates, payment methods (Claude reads it raw) |
| Sources | `agent/sources.py` | RSS, Jobicy API, Remote OK API → `Item`; keyword/regex/age filters; dedupe by URL hash; one failing source never breaks others |
| Scorer | `agent/scorer.py` | Batches of 12 → Claude Haiku with a forced tool (`save_scores`) → score 0–100, track core/stretch/skip, pay, location_ok, why, pitch, red_flags |
| Researcher | `agent/researcher.py` | Daily Claude Sonnet + `web_search_20250305` (max 8 searches); weekday focus rotation; handles `pause_turn`; JSON in `<json>` tags; marks links not seen in search results as unverified |
| Notify | `agent/notify.py` | Telegram (HTML, chunked) + Gmail SMTP |
| Render | `agent/render.py` | Telegram alert, Telegram digest, HTML email |
| State | `agent/state.py`, `state/*.json` | seen ids (45-day prune), digest queue, reported research URLs |
| Schedules | `.github/workflows/watch.yml`, `digest.yml` | Hourly watch; 06:05 UTC digest; state committed back to repo |

Sources in v1: Blender Artists "Paid Work" RSS, We Work Remotely (design, full-stack), Jobicy (design-multimedia; worldwide + keywords), Remote OK (+ keywords). Reddit feeds exist but are disabled.

**Known limitations to fix in v2**
- Hourly polling only; no real-time.
- Reddit blocks datacenter IPs (GitHub Actions and most VPSs), even for RSS. Use Reddit's official API with OAuth if Salam can get API access approved; otherwise keep covering Reddit through Claude web search.
- No feedback loop: scores never learn from what Salam likes.
- No pipeline/earnings tracking, no pitch drafts, no deadline reminders.
- JSON state files; no database.
- No cost tracking.
- Feed URLs were verified from documentation but not live-tested from a server; v2 needs a `sources doctor` command and health alerts.

## 4. Target architecture

One Python service, always on, deployed with Docker Compose on Salam's VPS (he already uses SSH/Termius).

```
                ┌──────────────── scheduler (APScheduler, asyncio) ────────────────┐
                │                                                                  │
 Sources ──► Ingest ──► Prefilter ──► Dedupe ──► LLM scoring ──► Router ──► Telegram (instant)
 (RSS/API/    (async      (keywords,    (URL hash +   (Haiku, batched,   │       Email (daily)
  search)      httpx,      regex, age)   fuzzy title)  cached prompt)    │       Dashboard
               ETag/IMS)                                                  ▼
                                                                    SQLite (WAL)
 News feeds ─► Ingest ─► Watchlist match ─► LLM analyst ─► Proposal ─► RISK ENGINE ─► Telegram
 Price data ─► Indicators ───────────────────────┘          (schema)   (pure code)    Approve/Reject
                                                                                         │
                                                       Broker adapter ◄── Executor ◄─────┘
                                                       (paper | ccxt | stock broker)
                                                                │
                                                          Journal + Shadow tracker ─► Weekly report
```

### Proposed layout
```
radar/
  app.py                  # entry: starts scheduler + Telegram bot
  core/
    config.py             # Pydantic settings from config.yaml + .env
    db.py                 # SQLite (WAL) + migrations
    llm.py                # Anthropic client, model tiers, prompt caching, usage logging
    budget.py             # daily/monthly spend guard
    telegram.py           # bot, allowlist, commands, inline buttons
    http.py               # shared httpx client, retries, conditional GET, per-host rate limits
  opportunities/
    sources/              # rss.py, jobicy.py, remoteok.py, reddit_oauth.py, search_sweep.py
    scorer.py             # v1 logic + feedback few-shots
    researcher.py         # v1 logic + more focuses
    pitch.py              # proposal/cover-letter drafter
    vetting.py            # scam/risk heuristics (rules first, LLM second)
    pipeline.py           # status tracking, reminders
  markets/
    news/                 # feed ingesters (official + reputable outlets)
    data/                 # price/candle adapters
    indicators.py
    analyst.py            # LLM: news → structured assessment
    strategy.py           # assessment + indicators → proposal (rules)
    risk.py               # deterministic checks
    brokers/              # base.py, paper.py, ccxt_adapter.py, <stock_broker>.py
    executor.py           # approval-gated order placement
    journal.py            # fills, P&L, R-multiples
    shadow.py             # tracks outcome of EVERY proposal, approved or not
  reports/
    digest.py  weekly.py  goals.py
  web/                    # optional read-only dashboard (FastAPI), behind auth
tests/
deploy/  Dockerfile  docker-compose.yml  radar.service  backup.sh
```

**Stack:** Python 3.12, asyncio, `httpx`, `feedparser`, `anthropic`, `python-telegram-bot` (v21+, async), `APScheduler`, `pydantic`/`pydantic-settings`, `sqlite3` or SQLModel, `pandas` (indicators), `ccxt` (crypto, has sandbox/testnet support on many exchanges), `pytest` + `respx` for HTTP mocks. Keep dependencies lean.

## 5. Opportunity Engine (v1 → v2)

### 5.1 Ingestion
- Per-source cadence in config (`every: 60s` … `every: 6h`). Fast sources (forums, RSS job boards) poll every 1–5 min using **ETag / If-Modified-Since**, so polls that find nothing are nearly free.
- Source health: record last success, consecutive failures, item counts. If a source fails 5 times in a row, send one Telegram notice (not one per failure). Command: `python -m radar sources doctor`.
- Keep every v1 source; add (verify each before enabling): more We Work Remotely categories, Blender Artists Jobs subcategories, Polycount job threads if a feed exists, BlenderNation job roundups, contest/grant listing feeds, company-careers feeds Salam adds by hand, Reddit via OAuth if approved.
- **Search sweeps:** scheduled Claude web-search runs for things without feeds (e.g. "hiring Blender product animator" posts from the last 24h on X/LinkedIn/Reddit). Run every 2–4 h, max 3–5 searches each, results go through the same scorer.

### 5.2 Dedupe
URL hash (v1), plus a fuzzy match on normalised title + company within 14 days, so cross-posted gigs alert once.

### 5.3 Scoring v2
- Keep v1's forced-tool schema and rubric.
- **Prompt caching** on the system prompt + profile + few-shot examples (they rarely change).
- **Feedback loop:** every Telegram alert has buttons 👍 Good fit · 👎 Not for me · ✅ Applied · 🔕 Mute source. Store the feedback. Include the last ~20 labelled examples as few-shots so scores adapt to Salam's taste.
- **Calibration report** (weekly): for each score band, how many alerts got 👍 / Applied / Won. Raise or lower `alert_score` suggestions based on it. Never auto-change thresholds; suggest them.
- Non-urgent sources can use the **Message Batches API** (discounted, async) instead of real-time calls.

### 5.4 Act on it
- **Pitch drafter:** "✍️ Draft pitch" button → Claude Sonnet writes a short, specific proposal using `profile.yaml` + a `portfolio.yaml` (project titles, links, one-line results) that Salam maintains. Returns 2 variants (short and detailed). Never sends.
- **Vetting:** rule-based red flags first (upfront fees, off-platform payment pressure, Telegram/WhatsApp-only recruiters, crypto-only pay from unknown parties, unpaid tests larger than ~1 hour of work), then the LLM's red_flags. Show a clear ⚠️ line.
- **Deadlines:** contests/grants with dates get reminders 7 days, 2 days and the morning of.
- **Pipeline:** statuses new → saved → applied → interviewing → won/lost. `/pipeline` lists open items. Won items ask for the amount and add it to earnings.

### 5.5 Research
Keep the v1 weekday rotation. Add: "repeat the best-performing focus" (whichever produced the most 👍 last month gets an extra slot), and a monthly "productise" run: assets/add-ons Salam could build and sell, with demand evidence and rough effort.

## 6. Market Desk (trading assistant)

### 6.1 Reality check (put this in the README and the first-run message)
- Professional firms react to headlines in microseconds with co-located servers and paid low-latency feeds. An LLM pipeline on a VPS reacts in seconds at best. **Racing to trade headlines first is not a realistic edge and must not be the design goal.**
- Studies of retail day traders consistently find most lose money. The design goal is the opposite of hype: **disciplined, risk-capped, slower-timeframe decisions** (hours to weeks), broad news synthesis, and an honest record of what works.
- Build it so Salam can watch it prove itself in paper mode before any real money is involved.

### 6.2 Scope
- Markets: configurable watchlist. Start with a small one (e.g. a few large-cap crypto pairs and/or a few liquid stocks/ETFs). Salam picks.
- **Broker/exchange: undecided. Ask Salam.** Requirements: legally usable from Nigeria by Salam, official API, paper/testnet/sandbox mode, trade-only keys, bracket or OCO orders (stop + target) preferred. Build `brokers/base.py` interface + `paper.py` first so everything works before a provider is chosen.

### 6.3 Pipeline
1. **News ingest** every 15–60 s with conditional GET: official sources (regulator filings feeds, central-bank press releases, exchange announcements, company press/IR feeds) plus reputable outlets' RSS. Log `published_at` vs `received_at` so actual latency is measured, not assumed. Verify each feed's terms.
2. **Fast prefilter** (no LLM): does it mention a watchlist instrument, its sector, or macro keywords (rates, CPI, jobs report, regulation)? Drop the rest.
3. **Analyst (LLM, forced tool):** returns `{instruments[], direction_bias, materiality 1–5, confidence 0–1, time_horizon, summary, why, what_would_invalidate}`. Keep the prompt focused on what's new versus already priced in; ask it to say "no trade" often.
4. **Strategy (code):** combine the assessment with indicators (trend, ATR volatility, recent range, liquidity/spread). Only materiality ≥ 4 and confidence ≥ threshold proceed. Compute entry, stop (ATR-based), target (min 2:1 reward:risk), size from risk %.
5. **Risk engine (code):** see 6.4. Failures are logged with the reason.
6. **Proposal → Telegram:**
   ```
   📈 PROPOSAL (PAPER) · BTC/USDT · LONG
   Entry ~ 68,200 · Stop 66,900 · Target 70,800 (2.0R)
   Size 0.015 BTC · Risk $19.50 (1.0% of account)
   Why: <2 lines>   Invalidates if: <1 line>
   News: <title> (<source>, 42s ago)
   Expires in 10 min
   [✅ Approve] [❌ Reject] [½ Half size]
   ```
7. **Executor:** on approval, re-check price. If it moved more than the slippage tolerance or the proposal expired, cancel and say why. Otherwise place the order with stop and target (bracket/OCO, or managed stops if the venue lacks them). Confirm the fill in Telegram.
8. **Journal + shadow tracker:** every proposal, including rejected and expired ones, is tracked to its hypothetical outcome. This tells Salam whether his overrides help or hurt and whether the system has any edge.

### 6.4 Risk engine defaults (`config.yaml → risk:`), all editable by Salam only
```yaml
risk:
  max_risk_per_trade_pct: 1.0      # of account equity
  max_daily_loss_pct: 3.0          # hit it → halt until next day
  max_weekly_loss_pct: 6.0         # hit it → halt + require /resume
  max_open_positions: 3
  max_position_pct: 20             # of equity in one instrument
  min_reward_risk: 2.0
  leverage: 1                      # no leverage unless changed here
  cooldown_after_losses: 3         # consecutive losses → 24h pause
  news_blackout_minutes: 2         # no entries in the first minutes after major scheduled releases
  whitelist: [BTC/USDT, ETH/USDT]  # Salam edits
  proposal_expiry_minutes: 10
  max_slippage_pct: 0.3
```

### 6.5 Modes
`off` → `signals` (proposals only, no executor) → `paper` (default; simulated fills with realistic fees + slippage) → `live` (gated per §2).

## 7. Daily, weekly and goals

- **Morning brief (07:00 Lagos):** top opportunities, deadlines this week, research picks, open pipeline, market overview (watchlist moves, notable news), paper/live P&L, spend yesterday.
- **Weekly review (Sunday):** opportunity calibration, applications sent / won, earnings, trading stats (win rate, average R, expectancy, max drawdown) for approved vs. shadow trades, source health, API spend, and 3 concrete suggestions for next week.
- **Goals:** `goals.yaml` holds Salam's targets. `/earned 250 furniture renders` logs income. The weekly report shows progress and the monthly run-rate needed. It must be blunt when a goal is off-track, and suggest the highest-leverage moves (raise rates, productise, agency hires), not riskier trading.

## 8. Telegram commands

`/today` brief now · `/pipeline` · `/saved` · `/earned <amount> <note>` · `/goals` · `/positions` · `/proposals` · `/mode` (show) · `/halt` · `/resume` · `/mute <source>` · `/sources` (health) · `/spend` · `/help`. Inline buttons as in §5.3 and §6.3.

## 9. Data model (SQLite, WAL)

`sources` (name, type, url, cadence, etag, last_modified, last_ok_at, fail_count, muted)
`opportunities` (id, source, url, title, summary, published_at, fetched_at, score, track, pay, location_ok, why, pitch, red_flags, status, feedback, value_usd)
`feedback` (opportunity_id, label, at)
`research_picks` (id, run_at, focus, title, url, verified, track, potential, first_step)
`reminders` (id, opportunity_id, due_at, sent)
`earnings` (id, at, amount_usd, source, note)
`news_items` (id, source, url, title, published_at, received_at, instruments, materiality, confidence, summary)
`proposals` (id, created_at, mode, instrument, side, entry, stop, target, size, risk_usd, rr, rationale, invalidation, news_id, expires_at, status, decided_by, decided_at, risk_check_log)
`orders` (id, proposal_id, broker_order_id, type, price, qty, status, at)
`trades` (id, proposal_id, entry_at, exit_at, entry_px, exit_px, pnl_usd, r_multiple, fees, shadow BOOLEAN)
`usage` (at, model, input_tokens, output_tokens, cache_read_tokens, searches, est_cost_usd)

Nightly backup of the DB file to a second location (e.g. compressed copy in a private repo or object storage), keeping 14 days.

## 10. Cost control

- Model tiers in config: Haiku for scoring/prefilter-level judgments, Sonnet for research, pitches and market analysis. Opus only if Salam enables it.
- Log usage per call. **Budget guard:** daily cap (default $3) and monthly cap; at 80% send a warning, at 100% pause non-essential LLM work (research, sweeps) but keep cheap scoring and all safety functions running.
- Prompt caching for stable system prompts; Message Batches for non-urgent work; prefilter before every LLM call.
- Check current model names and tool versions in the Claude docs when building; v1 uses `claude-haiku-5-5`, `claude-sonnet-5-5`, `web_search_20250305`.

## 11. Build phases (stop after each, report to Salam, wait for go-ahead)

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Port v1 into `radar/` as an always-on service with SQLite, Docker Compose, systemd, `.env`, allowlisted Telegram bot | v1 behaviour reproduced; tests pass; runs 24h on VPS without errors |
| 1 | Fast ingestion, conditional GET, source health, fuzzy dedupe, budget guard + usage log | New Blender Artists posts alert within 5 min; `/sources` and `/spend` work |
| 2 | Feedback buttons, few-shot learning, pitch drafter, vetting rules, pipeline, reminders, earnings, weekly review | Salam can go alert → draft → applied → won → earnings without leaving Telegram |
| 3 | Market Desk in `signals` mode: news ingest with latency logging, analyst, indicators, proposals (no execution), shadow tracker | Proposals arrive with full rationale; shadow P&L shows in the weekly report |
| 4 | `paper` mode: risk engine, approval flow, paper broker with fees/slippage, journal, `/halt` | Unit tests prove no order without approval; halt works; 30-day paper record accumulating |
| 5 | Real broker adapter in sandbox/testnet, then gated `live` | Only after Salam picks a provider and the §2 gates are met |

## 12. Testing requirements
- Unit tests for every source parser (fixtures of real feed samples), dedupe, scorer parsing, risk engine (table-driven: each rule has pass/fail cases), executor approval gate (including expired, wrong user, replayed callback, price moved), budget guard.
- HTTP mocked with `respx`; LLM mocked with recorded responses. No test may hit a live broker.
- `make check` runs lint + tests; CI on GitHub Actions.

## 13. Open decisions for Salam
1. VPS provider/specs (1–2 vCPU, 2 GB RAM is plenty).
2. Broker/exchange (see §6.2). Claude Code should research options that are legal and available to him in Nigeria and present a short comparison. Salam decides.
3. Starting watchlist and paper account size.
4. Risk defaults (§6.4): keep or change.
5. Monthly API budget.
6. Whether to keep v1 on GitHub Actions as a backup while v2 beds in (recommended for Phase 0–1).

## 14. Instructions to Claude Code
- Read this file, `CLAUDE.md`, `README.md`, `profile.yaml` and `config.yaml` first. Then propose a Phase 0 plan and wait.
- Reuse v1 logic (prompts, schema, filters, render) rather than rewriting from scratch.
- Ask before adding paid services, choosing a broker, or changing anything in §2.
- Keep `README.md` (owner guide, plain English) and `docs/` up to date as features land.
