"""The Item every source produces, plus the cheap filters that run before any AI cost (ported from v1)."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from radar.core.config import SourceConfig

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class Item:
    id: str
    source: str
    title: str
    url: str
    summary: str
    published: str | None  # ISO 8601, UTC
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def clean(text, limit: int = 1200) -> str:
    if not text:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", str(text)))
    return _WS_RE.sub(" ", text).strip()[:limit]


def make_id(key: str) -> str:
    """Same hash as v1, so v1's seen list carries over without duplicate alerts."""
    return hashlib.sha1((key or "").strip().rstrip("/").encode()).hexdigest()[:16]  # noqa: S324 — an id, not security


def iso_from_struct(st) -> str | None:
    if not st:
        return None
    try:
        return datetime(*st[:6], tzinfo=UTC).isoformat()
    except (TypeError, ValueError):
        return None


def iso_any(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def keyword_regex(words):
    if not words:
        return None
    return re.compile(r"(?i)(?<!\w)(" + "|".join(re.escape(str(w)) for w in words) + r")(?!\w)")


def passes(item: Item, src: SourceConfig, global_exclude: list[str], max_age_days: int,
           now: datetime | None = None) -> bool:
    text = f"{item.title} {item.summary}"
    if src.title_must_match and not re.search(src.title_must_match, item.title, re.I):
        return False
    kw = keyword_regex(src.keywords)
    if kw and not kw.search(text):
        return False
    for pattern in list(global_exclude or []) + list(src.exclude or []):
        if re.search(pattern, text, re.I):
            return False
    if item.published and max_age_days:
        try:
            age = (now or datetime.now(UTC)) - datetime.fromisoformat(item.published)
            if age > timedelta(days=max_age_days):
                return False
        except (ValueError, TypeError):
            pass
    return True
