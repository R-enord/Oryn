# Money Radar v2 — VPS setup guide 🖥️

v2 runs all the time on your own server instead of once an hour on GitHub. This guide covers **Phase 0**: everything v1 does, as an always-on service with a database, a locked-down Telegram bot, automatic restarts and nightly backups.

| | v1 (GitHub Actions) | v2 Phase 0 (your VPS) |
|---|---|---|
| Checks job sources | every hour | every 30 min (set `service.watch_every_minutes`) |
| Morning digest | 07:05 Lagos | 07:00 Lagos, and it catches up if the server was down at 7 |
| Memory | JSON files committed to the repo | SQLite database in `data/`, backed up nightly |
| Telegram | sends only | sends, and answers **you** (`/status`, `/scan`, `/today`); ignores everyone else |
| If something breaks | you check the Actions tab | one Telegram warning after 3 failures in a row, and another when it recovers |

Time needed: about 30–45 minutes. You'll use Termius (or any SSH app) to type the commands.

---

## 1. Get a small VPS

Any provider works. 1 vCPU and 1–2 GB RAM is plenty. Pick **Ubuntu 24.04** (or 22.04). Nothing needs to be reachable from the internet except SSH: the bot connects *out* to Telegram, nothing connects *in*.

Once you can SSH in, turn on the firewall:
```bash
sudo ufw allow OpenSSH
```
```bash
sudo ufw enable
```

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
```
```bash
sudo usermod -aG docker $USER
```
Log out and back in (close and reopen the Termius session) so the second command takes effect. Check it works:
```bash
docker compose version
```

## 3. Put the code on the server

If the repository is private, the easiest way is GitHub's own CLI:
```bash
sudo apt-get install -y gh git
```
```bash
gh auth login
```
```bash
gh repo clone R-enord/Oryn ~/money-radar
```
```bash
cd ~/money-radar
```
(You can also upload the folder with Termius's SFTP panel instead.)

## 4. Fill in your settings

```bash
cp .env.example .env
```
```bash
chmod 600 .env
```
```bash
nano .env
```
Fill in `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN` and, if you want the email digest, `EMAIL_APP_PASSWORD` (the same values as your v1 GitHub secrets). Then set `RADAR_UID` and `RADAR_GID` to the numbers these print:
```bash
id -u
```
```bash
id -g
```
Save with Ctrl+O, Enter, Ctrl+X. Then create the data folder:
```bash
mkdir -p data
```

## 5. Find your Telegram ids

Open your bot in Telegram, press **Start**, send it "hi". Then:
```bash
docker compose run --rm radar python -m radar telegram-id
```
It prints `TELEGRAM_CHAT_ID=…` and `TELEGRAM_OWNER_ID=…`. Put both in `.env`. **The bot only ever answers the person and chat in these two lines**; messages from anyone else are dropped and logged.

## 6. Check the sources from this server

```bash
docker compose run --rm radar python -m radar sources doctor
```
Every line should say `OK`. A `FAIL` line means that site blocks your server or the feed moved: tell Claude Code which one, or set `enabled: false` on it in `config.yaml`. One failing source never stops the others.

## 7. Bring over v1's memory (optional, recommended)

So v2 doesn't re-alert posts v1 already sent you. Copy v1's `state/` folder from the GitHub repo (the `main` branch, where the Actions commit it) into `~/money-radar/state/`, then:
```bash
docker compose run --rm -v "$PWD/state:/app/state:ro" radar python -m radar import-v1
```
Running it twice is safe.

## 8. Start it

```bash
docker compose up -d --build
```
Within a few seconds Telegram says **"📡 Money Radar … is running"**. Watch it work:
```bash
docker compose logs -f
```
(Ctrl+C stops watching the log; the service keeps running.) Docker restarts it if it crashes and starts it again when the server reboots.

In Telegram, try:
- `/status`: last runs, source health, Claude usage in the last 24 h
- `/scan`: check every source right now
- `/today`: send today's digest now (runs web research: a few cents)
- `/help`

## 9. v1 and v2 side by side

While v2 proves itself (the brief recommends a few days), you can leave v1 running on GitHub as a backup. You may get the same alert twice during that time. When you're happy with v2, open the GitHub repo → **Actions** → **watch (hourly alerts)** → **⋯ → Disable workflow**, and do the same for **digest**. Re-enable them any time to switch back.

---

## Everyday commands

All from `~/money-radar`:

| What | Command |
|---|---|
| Is it running and healthy? | `docker compose ps` (look for `healthy`) |
| Live log | `docker compose logs -f --tail 100` |
| Status (same as `/status`) | `docker compose exec radar python -m radar status` |
| Restart after editing `service:` in config.yaml or `.env` | `docker compose restart` |
| Update to the newest code | `git pull` then `docker compose up -d --build` |
| Stop / start | `docker compose stop` / `docker compose start` |

Changes to **profile.yaml** and to the `settings:` / `sources:` parts of **config.yaml** apply on the next run, no restart needed. If you make a typo in config.yaml, the service keeps the last good version and logs a warning.

## Backups

Every night at 03:30 Lagos the service saves a compressed copy of the database to `data/backups/` and keeps 14 days. To also keep copies **off** the server (recommended: if the VPS dies, your history survives):

1. Install rclone: `sudo -v ; curl https://rclone.org/install.sh | sudo bash`
2. `rclone config` → add a remote, e.g. Google Drive, named `gdrive`.
3. In `.env`: `BACKUP_REMOTE=gdrive:money-radar-backups`
4. `crontab -e` and add:
   ```
   45 3 * * * /home/YOUR_USER/money-radar/deploy/backup.sh >> /home/YOUR_USER/money-radar/data/backup.log 2>&1
   ```

To restore: stop the service, unzip a backup over `data/radar.db` (`gunzip -c data/backups/radar-….db.gz > data/radar.db`), start it again.

## Without Docker (alternative)

If you'd rather not use Docker: install Python 3.12, then in `~/money-radar`:
```bash
python3.12 -m venv .venv
```
```bash
.venv/bin/pip install .
```
```bash
.venv/bin/python -m radar sources doctor
```
Then use `deploy/radar.service` (instructions at the top of that file) so systemd keeps it running. Use one method, not both.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No "is running" message in Telegram | `docker compose logs --tail 50`. "Telegram is not configured" = a missing value in `.env`. Then `docker compose restart`. |
| The bot doesn't answer `/status` | `TELEGRAM_OWNER_ID` / `TELEGRAM_CHAT_ID` don't match your account. Look for "ignored Telegram update from user_id=…" in the log; that number is you. |
| `telegram-id` says the service is reading updates | Stop it first (`docker compose stop`), run the command, start it again. |
| `PermissionError` on `data/` | `RADAR_UID`/`RADAR_GID` in `.env` must match `id -u`/`id -g`, or run `sudo chown -R $(id -u):$(id -g) data`. |
| `unhealthy` in `docker compose ps` | The service stopped writing its heartbeat. `docker compose restart`, then check the log. |
| A source keeps failing | `/status` lists it with the error. Run `sources doctor`; if it's blocked from your server, disable it in `config.yaml`. |
| "Model not found" | Update the model names at the top of `config.yaml` to current ones from the Claude docs. |

## Safety notes
- `.env` holds your keys. Keep it `chmod 600`, never commit or share it. The service masks keys and the bot token in its logs.
- The bot never messages anyone but you, and Money Radar never applies or emails anyone on your behalf.
