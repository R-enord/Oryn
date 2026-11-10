"""One-off import of v1's state/ JSON files, so switching to v2 doesn't re-alert old posts."""
from __future__ import annotations

import json
from pathlib import Path

from radar.core.db import Database
from radar.core.timeutil import iso


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def import_v1_state(db: Database, state_dir: Path) -> dict[str, int]:
    seen: dict = _load(state_dir / "seen.json", {})
    queue: list = _load(state_dir / "queue.json", [])
    reported: list = _load(state_dir / "reported.json", [])

    seen_ids = [k for k in seen if isinstance(k, str)] if isinstance(seen, dict) else []
    with db.tx() as c:
        c.executemany("INSERT OR IGNORE INTO seen (id, seen_at) VALUES (?, ?)",
                      [(k, str(seen[k] or iso())) for k in seen_ids])

    queued = 0
    for rec in queue if isinstance(queue, list) else []:
        if not isinstance(rec, dict) or not rec.get("id") or db.get_opportunity(rec["id"]):
            continue
        scored_at = rec.get("scored_at") or iso()
        db.save_opportunity(rec, rec, scored_at)
        if rec.get("alerted"):
            db.mark_alerted(rec["id"], scored_at)
        db.mark_seen([rec["id"]], scored_at)
        queued += 1

    known = set(db.recent_research_urls(limit=100000))
    urls = [u for u in reported if isinstance(u, str) and u and u not in known] if isinstance(reported, list) else []
    if urls:
        db.save_research_picks(iso(), "imported from v1", [{"url": u, "title": "(v1 pick)"} for u in urls])
    return {"seen": len(seen_ids), "queued": queued, "research_urls": len(urls)}
