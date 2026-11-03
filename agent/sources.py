"""Pulls new posts from job feeds and filters out obvious non-matches before any AI cost."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

USER_AGENT = "money-radar/1.0 (personal job-alert script)"
TIMEOUT = 25

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
    return hashlib.sha1((key or "").strip().rstrip("/").encode()).hexdigest()[:16]


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def _iso_from_struct(st) -> str | None:
    if not st:
        return None
    return datetime(*st[:6], tzinfo=timezone.utc).isoformat()


def _iso_any(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


# ---------- fetchers ----------

def fetch_rss(src: dict) -> list[Item]:
    feed = feedparser.parse(_get(src["url"]).content)
    items = []
    for e in feed.entries:
        link = e.get("link") or ""
        content = (e.get("content") or [{}])[0].get("value")
        items.append(Item(
            id=make_id(link or e.get("id", "")),
            source=src["name"],
            title=clean(e.get("title"), 300),
            url=link,
            summary=clean(e.get("summary") or content),
            published=_iso_from_struct(e.get("published_parsed") or e.get("updated_parsed")),
        ))
    return items


def fetch_jobicy(src: dict) -> list[Item]:
    data = _get(src["url"]).json()
    items = []
    for j in data.get("jobs", []):
        url = j.get("url") or ""
        meta_keys = ("jobGeo", "jobType", "jobLevel", "annualSalaryMin", "annualSalaryMax", "salaryCurrency")
        meta = {k: j[k] for k in meta_keys if j.get(k)}
        items.append(Item(
            id=make_id(url or str(j.get("id"))),
            source=src["name"],
            title=clean(f'{j.get("jobTitle", "")} — {j.get("companyName", "")}', 300),
            url=url,
            summary=clean(j.get("jobExcerpt") or j.get("jobDescription")),
            published=_iso_any(j.get("pubDate")),
            meta=meta,
        ))
    return items


def fetch_remoteok(src: dict) -> list[Item]:
    data = _get(src["url"]).json()
    items = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue  # first element is Remote OK's legal notice
        url = j.get("url") or j.get("apply_url") or ""
        meta = {"location": j.get("location"), "tags": ", ".join(j.get("tags") or [])}
        if j.get("salary_min"):
            meta["salary_usd"] = f'{j.get("salary_min")}–{j.get("salary_max")}'
        items.append(Item(
            id=make_id(url),
            source=src["name"],
            title=clean(f'{j.get("position", "")} — {j.get("company", "")}', 300),
            url=url,
            summary=clean(j.get("description")),
            published=_iso_any(j.get("epoch") or j.get("date")),
            meta={k: v for k, v in meta.items() if v},
        ))
    return items


FETCHERS = {"rss": fetch_rss, "jobicy": fetch_jobicy, "remoteok": fetch_remoteok}


# ---------- filtering ----------

def _keyword_regex(words):
    if not words:
        return None
    return re.compile(r"(?i)(?<!\w)(" + "|".join(re.escape(str(w)) for w in words) + r")(?!\w)")


def passes(item: Item, src: dict, global_exclude: list[str], max_age_days: int) -> bool:
    text = f"{item.title} {item.summary}"
    must = src.get("title_must_match")
    if must and not re.search(must, item.title, re.I):
        return False
    kw = _keyword_regex(src.get("keywords"))
    if kw and not kw.search(text):
        return False
    for pattern in list(global_exclude or []) + list(src.get("exclude") or []):
        if re.search(pattern, text, re.I):
            return False
    if item.published and max_age_days:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(item.published)
            if age > timedelta(days=max_age_days):
                return False
        except ValueError:
            pass
    return True


def collect(sources: list[dict], settings: dict) -> tuple[list[Item], list[tuple[str, str]]]:
    """Fetches every source; one broken feed never stops the others."""
    gathered, report = [], []
    for src in sources:
        fetch = FETCHERS.get(src.get("type", "rss"))
        if not fetch:
            report.append((src["name"], f"unknown type '{src.get('type')}'"))
            continue
        try:
            raw = fetch(src)
        except Exception as exc:  # noqa: BLE001 — log and move on
            report.append((src["name"], f"FAILED ({exc.__class__.__name__}: {str(exc)[:120]})"))
            continue
        kept = [i for i in raw if i.url and passes(i, src, settings["exclude"], settings["max_age_days"])]
        report.append((src["name"], f"{len(raw)} fetched, {len(kept)} passed filters"))
        gathered.extend(kept)

    unique, ids = [], set()
    for item in gathered:
        if item.id not in ids:
            ids.add(item.id)
            unique.append(item)
    return unique, report
