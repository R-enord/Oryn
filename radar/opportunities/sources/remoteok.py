"""Remote OK public API (https://remoteok.com/api). The first element is a legal notice, not a job."""
from __future__ import annotations

from radar.core.config import SourceConfig

from .base import Item, clean, iso_any, make_id


def parse_remoteok(data: list, src: SourceConfig) -> list[Item]:
    items = []
    for j in data or []:
        if not isinstance(j, dict) or "position" not in j:
            continue
        url = j.get("url") or j.get("apply_url") or ""
        meta = {"location": j.get("location"), "tags": ", ".join(j.get("tags") or [])}
        if j.get("salary_min"):
            meta["salary_usd"] = f'{j.get("salary_min")}–{j.get("salary_max")}'
        items.append(Item(
            id=make_id(url),
            source=src.name,
            title=clean(f'{j.get("position", "")} — {j.get("company", "")}', 300),
            url=url,
            summary=clean(j.get("description")),
            published=iso_any(j.get("epoch") or j.get("date")),
            meta={k: v for k, v in meta.items() if v},
        ))
    return items
