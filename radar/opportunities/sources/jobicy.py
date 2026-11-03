"""Jobicy remote-jobs API (https://jobicy.com/jobs-rss-feed)."""
from __future__ import annotations

from radar.core.config import SourceConfig

from .base import Item, clean, iso_any, make_id

META_KEYS = ("jobGeo", "jobType", "jobLevel", "annualSalaryMin", "annualSalaryMax", "salaryCurrency")


def parse_jobicy(data: dict, src: SourceConfig) -> list[Item]:
    items = []
    for j in (data or {}).get("jobs", []) or []:
        if not isinstance(j, dict):
            continue
        url = j.get("url") or ""
        meta = {k: j[k] for k in META_KEYS if j.get(k)}
        items.append(Item(
            id=make_id(url or str(j.get("id"))),
            source=src.name,
            title=clean(f'{j.get("jobTitle", "")} — {j.get("companyName", "")}', 300),
            url=url,
            summary=clean(j.get("jobExcerpt") or j.get("jobDescription")),
            published=iso_any(j.get("pubDate")),
            meta=meta,
        ))
    return items
