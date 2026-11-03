"""Small JSON files in state/ remember what the agent has already seen and sent."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR


def load(name: str, default):
    path = STATE_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save(name: str, data) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def prune_seen(seen: dict, days: int = 45) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}
