# Money Radar v1 — setup guide 📡

Your personal opportunity-hunting agent. It runs in GitHub's cloud for free, so your PC can stay off.

| When | What it does | Where you see it |
|---|---|---|
| Every hour | Pulls new posts from job feeds, drops obvious junk, has Claude score each one against **profile.yaml** | Instant Telegram ping for scores ≥ 75 |
| Every day, 07:05 Lagos | Claude does open web research (a different focus each weekday) and bundles it with every match ≥ 50 | Email digest + Telegram summary |

**Weekly research focus:** Mon contests & prizes · Tue marketplace demand · Wed brands needing visuals · Thu AI training work · Fri fresh freelance gigs · Sat stretch gigs · Sun grants & business ideas. Every day also includes a sweep of Reddit hiring subs and the Blender Artists forum.

---

## Setup (about 30 minutes, best done on a PC)

### 1. Claude API key
1. Go to **platform.claude.com**, sign in, add a little credit under Billing.
2. **Settings → Privacy:** turn **web search** on (the daily research needs it).
3. **API Keys → Create key.** Copy it somewhere safe.
4. Optional but smart: set a monthly spend limit under **Limits**.

### 2. Telegram bot
1. In Telegram, open **@BotFather**, send `/newbot`, pick a name. Copy the **token** it gives you.
2. Open your new bot, press **Start**, and send it any message ("hi").
3. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and find `"chat":{"id":123456789` — that number is your **chat id**.

### 3. Gmail app password
1. Make sure 2-Step Verification is on for your Google account.
2. Go to **myaccount.google.com/apppasswords**, create one called "Money Radar", copy the 16-character password.

### 4. Put the code on GitHub
1. Create a **private** repository on github.com (e.g. `money-radar`). Private keeps your profile to yourself and still gets 2,000 free Action minutes a month; this uses roughly 800.
2. Upload this folder. Easiest with **GitHub Desktop** (File → Add local repository → Publish), or from a terminal:
   ```bash
   cd money-radar
   git init && git add . && git commit -m "Money Radar"
   git branch -M main
   git remote add origin https://github.com/<you>/money-radar.git
   git push -u origin main
   ```
   ⚠️ If you upload through the website instead, check that the hidden **.github/workflows** folder made it. Without it nothing runs.

### 5. Add your secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add each:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from step 1 |
| `TELEGRAM_BOT_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 2 |
| `EMAIL_USER` | your Gmail address |
| `EMAIL_APP_PASSWORD` | from step 3 |
| `EMAIL_TO` | optional, if the digest should go somewhere else |

### 6. Turn it on
1. Repo → **Actions** tab → enable workflows if GitHub asks.
2. Click **watch (hourly alerts)** → **Run workflow**. Within a minute or two you should get Telegram pings (if anything scores high).
3. Click **digest (daily research + email)** → **Run workflow** to get your first email.

From now on it runs by itself.

---

## Make it yours

**profile.yaml** is the most important file. Fill in your real minimum budget, hourly target and how you can receive payments. Add skills as you learn them. Claude reads the whole file, so plain English works.

**config.yaml**
- `alert_score` / `digest_score`: raise them if you get too much noise, lower them if it's too quiet.
- `sources`: add any RSS feed (`type: rss`) — many forums, blogs and job boards have one. Use `keywords:` to only keep posts that mention certain words.
- `max_items_per_run` and `research_max_searches` cap what you spend.

**agent/researcher.py → `FOCUS_BY_WEEKDAY`** changes what the daily research hunts for.

**How often:** edit the `cron:` line in `.github/workflows/watch.yml`. `"23 * * * *"` is hourly; `"23 */2 * * *"` is every 2 hours. GitHub can't go faster than every 5 minutes, and scheduled runs sometimes start a few minutes late.

---

## Costs
- **GitHub:** free on a private repo at this schedule.
- **Claude:** scoring uses the small, cheap model; the bigger model only runs once a day. Web search is billed per search (about a cent each), so 8 searches a day is pennies plus tokens. Watch your usage in the Console for the first week and set a spend limit.

## Good to know
- **Reddit** blocks cloud servers, GitHub included, so the Reddit feeds in config.yaml are switched off. The daily researcher searches Reddit for you instead. If you ever run Money Radar on your own PC, you can switch them on.
- **Upwork and Fiverr** don't allow automated scraping. Keep their own saved-search alerts on; Money Radar covers everything else.
- **Feeds change.** Run the **check** command (below) or read the watch logs in the Actions tab; any source that says FAILED can be fixed or removed without breaking the others.
- **Always vet clients.** The scorer flags common scam signs, but never pay to apply, and be careful with big unpaid "tests".

---

## Run it on your own PC or VPS (optional)
```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in your keys
python -m agent check         # tests every source, no AI, nothing sent
python -m agent telegram-id   # prints your Telegram chat id
python -m agent watch --dry-run
python -m agent digest --dry-run
```
`--dry-run` prints messages instead of sending them and doesn't save state. To run it on a VPS on a schedule, add two cron lines that call `python -m agent watch` hourly and `python -m agent digest` daily.

## Troubleshooting
| Problem | Fix |
|---|---|
| No Telegram messages | Run **watch** by hand and read the log. "Telegram not configured" = a secret name is wrong. Error 400/403 = wrong chat id, or you never pressed Start on your bot. |
| No email | Gmail needs an **app password**, not your normal password. Check the digest log. |
| Research step error | Make sure web search is enabled in the Console and you have credit. |
| Model not found | Update the model names at the top of config.yaml to current ones from the Claude docs. |
| Workflows stopped running | Open the Actions tab and re-enable them. |

## Files
```
agent/            the code (sources → scorer → notify; researcher for the daily run)
config.yaml       settings + feed list
profile.yaml      who the agent hunts for
state/            what's been seen/sent (updated automatically)
.github/workflows hourly + daily schedules
```
