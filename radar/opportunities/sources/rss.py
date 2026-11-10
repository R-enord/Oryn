"""RSS/Atom feeds (Blender Artists, We Work Remotely, any forum or board with a feed)."""
from __future__ import annotations

import feedparser

from radar.core.config import SourceConfig

from .base import Item, clean, iso_from_struct, make_id


def parse_rss(content: bytes | str, src: SourceConfig) -> list[Item]:
    feed = feedparser.parse(content)
    items = []
    for e in feed.entries:
        link = e.get("link") or ""
        content_value = (e.get("content") or [{}])[0].get("value")
        items.append(Item(
            id=make_id(link or e.get("id", "")),
            source=src.name,
            title=clean(e.get("title"), 300),
            url=link,
            summary=clean(e.get("summary") or content_value),
            published=iso_from_struct(e.get("published_parsed") or e.get("updated_parsed")),
        ))
    return items
