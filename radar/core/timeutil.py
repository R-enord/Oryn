"""Times are stored in UTC (ISO 8601) and shown to Salam in Lagos time."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LAGOS = ZoneInfo("Africa/Lagos")


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    """UTC ISO string with second precision; sorts correctly as text."""
    return (dt or now_utc()).astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def local(dt: datetime, tz: str | ZoneInfo = LAGOS) -> datetime:
    return dt.astimezone(ZoneInfo(tz) if isinstance(tz, str) else tz)


def ago(dt: datetime | None, now: datetime | None = None) -> str:
    if not dt:
        return "never"
    secs = int(((now or now_utc()) - dt).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 90:
        return f"{secs}s ago"
    if secs < 90 * 60:
        return f"{secs // 60} min ago"
    if secs < 36 * 3600:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"
