# Money Radar — Owner's Guide

Your personal money-making agent: it hunts for paid work that fits your skills, helps you win it, and (in v2) watches the markets and proposes trades that **you** approve one by one.

This guide is for you, Salam. The technical plan for Claude Code is in `docs/PROJECT_BRIEF.md`.

---

## Where things stand

| | Status | Runs on | What you get |
|---|---|---|---|
| **v1** | ✅ Built, ready to set up | GitHub Actions (free) | Hourly Telegram alerts, daily research + email digest |
| **v2 Phase 0** | ✅ Built, ready to test on your VPS | Your VPS, 24/7 | v1's alerts and digest as an always-on service: checks every 30 min, a database, a Telegram bot that only answers you (`/status`, `/scan`, `/today`), failure warnings, nightly backups |
| **v2 Phases 1–5** | 📋 Planned | Your VPS, 24/7 | Everything below |

- To use v1 now, follow `docs/V1_SETUP.md`. It keeps working while v2 is built.
- To set up v2 on your VPS, follow `docs/V2_SETUP.md`.

### Build phases
| Phase | What it adds | Status |
|---|---|---|
| 0 | v1 ported to an always-on service: SQLite, Docker, locked-down Telegram bot, backups | ✅ Done, waiting for your 24-hour VPS test |
| 1 | Faster checks (every 1–5 min where feeds allow), source health alerts, smarter duplicate detection, spending cap + `/spend` | Next |
| 2 | 👍/👎 buttons that teach it your taste, pitch drafts, pipeline, deadline reminders, earnings, weekly review | |
| 3 | Market Desk in signals-only mode: news, analysis, trade proposals, no orders | |
| 4 | Paper trading with the risk engine, approval buttons and `/halt` | |
| 5 | A real broker in test mode, then live (only when you choose a broker and the safety gates are met) | |

---

## How v2 works, day to day

**Opportunity alerts, within minutes.** When a matching gig appears (Blender Artists, remote job boards, contest and grant listings, plus regular web-search sweeps of Reddit, X and LinkedIn), you get a Telegram message with the score, pay, why it fits, and red flags. Each one has buttons:

- 👍 / 👎 teach it your taste. Scores improve every week.
- ✍️ **Draft pitch** writes two versions of a proposal using your portfolio. You edit and send it yourself.
- ✅ **Applied** moves it into your pipeline, which reminds you to follow up.

**Morning brief, 7am Lagos.** Top opportunities, deadlines coming up, research picks, your open pipeline, a market overview, trading results, and what the agent spent yesterday.

**Weekly review, Sunday.** What you applied to and won, your earnings, which sources actually pay off, how accurate the agent's scores were, trading stats, and three concrete suggestions for next week.

**Earnings and goals.** Send `/earned 250 sofa renders` whenever you get paid. The agent tracks progress toward your goals and tells you plainly whether you're on track.

---

## The trading assistant (Market Desk)

### What it does
1. Watches a short list of markets you choose and reads market-moving news within seconds of it arriving: official announcements, filings, central-bank releases and reputable outlets.
2. Decides whether the news actually matters for your markets. Most of the time the right answer is "no trade", and it's built to say so.
3. When something does pass, it sends you a **trade proposal**: what to buy or sell, entry price, stop-loss (where you'd exit if wrong), target, exact size, how much money is at risk, the reasoning, and what would prove it wrong.
4. You tap **Approve**, **Reject** or **Half size**. Nothing is placed without your tap. Proposals expire after about 10 minutes, and if the price has moved too much by the time you approve, it cancels instead of chasing.
5. It records every proposal, including the ones you rejected, and tracks how each would have turned out. Over time you'll see whether the system has an edge and whether your overrides help or hurt.

### Safety rules (built in; the AI can't change them)
- **Paper trading first.** It starts with pretend money and real prices. Live trading stays locked until you've had at least 30 days and 30 trades on paper *and* you unlock it deliberately.
- **Risk limits in code, not AI.** Defaults: risk at most 1% of the account per trade, stop for the day after a 3% loss, stop for the week after 6%, max 3 positions at once, no leverage. Only you can change these, in `config.yaml`.
- **Kill switch:** send `/halt` and it stops everything immediately.
- **Your exchange keys can trade but never withdraw**, and only work from your server.
- **Only you can talk to the bot.** It ignores everyone else.

### What it won't do, and why
It won't beat the market to headlines. Big trading firms react to news in microseconds with servers sitting next to the exchanges; any AI on a VPS takes seconds. So the agent doesn't try to win that race. Its advantage is reading far more news than you could, never trading on emotion, sticking to risk limits every time, and keeping an honest scorecard.

Most people who day-trade lose money. Treat this as a disciplined tool you test patiently, not a money machine. Only ever trade money you can afford to lose. I'm not a financial advisor, and nothing the agent says is financial advice.

---

## About the big goal

Your goal is $10M by the end of 2027. That works out to roughly $700,000 every month from now. Freelance rates can't get there in that time, and trouble starts when a trading bot is pushed to: chasing a target that size means huge risk, and huge risk usually ends the account. So the agent will never raise risk to "catch up".

What it will do is push the levers that actually compound:
- winning more and better-paid gigs,
- raising your rates as your win rate climbs,
- turning your skills into products (assets, Blender add-ons) that sell while you sleep,
- tracking real numbers that show when you're ready to hire and grow your agency.

The weekly review shows your run-rate honestly, so you can set milestones that stretch you without breaking you. You can change the targets in `goals.yaml` anytime.

---

## What you'll need to decide

1. **A VPS**: a small one is enough (1–2 vCPU, 2 GB RAM).
2. **A broker or exchange** for trading, which must be legal for you to use in Nigeria, have an API and a paper/test mode. Claude Code will research options and show you a comparison; you choose.
3. **Which markets** to watch, starting small.
4. **Your risk limits**: keep the defaults or tighten them.
5. **A monthly API budget.** The agent pauses non-essential AI work when it hits your cap (default $3/day).

---

## Handing this to Claude Code

The project lives in the GitHub repo `R-enord/Oryn`. Open it in Claude Code (claude.ai/code, Claude Code Desktop, or `claude` in a terminal inside the folder).

Phase 0 is built. Once it has run on your VPS for a day without problems, start the next phase with:

> Read CLAUDE.md and docs/PROJECT_BRIEF.md. Phase 0 is running on my VPS. Propose your Phase 1 plan, then wait for my go-ahead. Don't start any trading code until I say so.

1. Work through the phases one at a time. At the end of each, Claude Code will summarise and wait for you. Test each phase for a few days before moving on.
2. When it reaches Phase 3 (market signals), ask it to research brokers/exchanges available to you and give you the comparison before writing any broker code.

`CLAUDE.md` holds the standing rules (safety, testing, no live trading by default), so they apply to every session automatically.

---

## Costs (rough)
- **VPS:** a few dollars a month, depending on provider.
- **Claude API:** cheap model for scoring, smarter model only for research, pitches and market analysis. Web search is about a cent per search. A daily cap keeps it predictable.
- **Market data / broker:** many offer free paper/test accounts; trading fees apply when live.

## Quick glossary
- **Paper trading:** practice trading with fake money and real prices.
- **Stop-loss:** a preset exit that limits your loss if the trade goes wrong.
- **R / reward-to-risk:** 2R means the target makes twice what the stop would lose.
- **Drawdown:** how far the account fell from its peak.
- **Expectancy:** average profit or loss per trade over many trades. It's the number that shows whether a strategy works.

## Files
```
README.md               this guide
CLAUDE.md               standing rules for Claude Code
docs/PROJECT_BRIEF.md   full technical spec for v2
docs/V1_SETUP.md        how to set up v1 on GitHub today
docs/V2_SETUP.md        how to run v2 on your VPS
config.yaml             settings + sources (shared by v1 and v2; `service:` is v2 only)
profile.yaml            who the agent hunts for
goals.yaml              income targets the reviews track
.env.example            the keys you fill in (copy to .env)
agent/                  v1 code
radar/                  v2 code (the always-on service)
tests/                  automated checks for v2 (`make check`)
Dockerfile, docker-compose.yml, deploy/   how v2 runs on the VPS
.github/workflows/      v1 schedules + v2 test runs
```
