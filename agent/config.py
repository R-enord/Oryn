"""Loads config.yaml, profile.yaml and environment variables."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"

DEFAULT_SETTINGS = {
    "scorer_model": "claude-haiku-5-5",
    "research_model": "claude-sonnet-5-5",
    "web_search_tool": "web_search_20250305",
    "alert_score": 75,
    "digest_score": 50,
    "max_alerts_per_run": 5,
    "max_items_per_run": 60,
    "max_age_days": 7,
    "research_max_searches": 8,
    "batch_size": 12,
    "exclude": [],
}


def _load_dotenv() -> None:
    """Reads a local .env file (for running on your own PC/VPS). GitHub uses Secrets instead."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> tuple[dict, list[dict]]:
    cfg = _load_yaml("config.yaml")
    settings = {**DEFAULT_SETTINGS, **(cfg.get("settings") or {})}
    sources = [s for s in (cfg.get("sources") or []) if s.get("enabled", True)]
    return settings, sources


def load_profile_text() -> str:
    return (ROOT / "profile.yaml").read_text(encoding="utf-8")


def env(name: str, required: bool = False) -> str | None:
    value = os.getenv(name) or None
    if required and not value:
        raise SystemExit(f"Missing environment variable / GitHub secret: {name}")
    return value
