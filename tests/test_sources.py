import json
from datetime import UTC, datetime

import httpx
import respx

from radar.core.config import Settings, SourceConfig
from radar.core.http import make_client
from radar.opportunities.sources import collect, fetch_source
from radar.opportunities.sources.base import Item, clean, iso_any, make_id, passes
from radar.opportunities.sources.jobicy import parse_jobicy
from radar.opportunities.sources.remoteok import parse_remoteok
from radar.opportunities.sources.rss import parse_rss
from tests.conftest import SOURCES, fixture_bytes


def src(**kw) -> SourceConfig:
    return SourceConfig(**{"name": "Test", "type": "rss", "url": "https://x.test/feed", **kw})


# ---------- parsers ----------

def test_parse_blender_artists_rss():
    items = parse_rss(fixture_bytes("blenderartists_paid_work.rss"), src(name="BA"))
    assert len(items) == 3
    first = items[0]
    assert first.title == "Looking for a Blender artist: furniture product renders (20 images)"
    assert first.url.endswith("/1580001")
    assert first.id == make_id(first.url)
    assert "20 photoreal renders" in first.summary and "<" not in first.summary
    assert "$600–$900" in first.summary  # HTML entities decoded
    assert first.published == "2026-11-02T10:15:00+00:00"
    assert first.source == "BA"


def test_parse_wwr_rss_unescapes_html_description():
    items = parse_rss(fixture_bytes("wwr_design.rss"), src())
    assert [i.title for i in items] == ["Lumen Labs: Senior 3D Product Designer", "Brightside: UX Researcher (US only)"]
    assert "Blender renders" in items[0].summary
    assert "<p>" not in items[0].summary


def test_parse_jobicy():
    items = parse_jobicy(json.loads(fixture_bytes("jobicy_design.json")), src(type="jobicy"))
    assert len(items) == 2
    job = items[0]
    assert job.title == "3D Artist (Product Visualization) — Nordic Living"
    assert job.summary.startswith("We’re looking for a 3D artist")
    assert job.meta["jobGeo"] == "Anywhere"
    assert job.meta["annualSalaryMin"] == "30000"
    assert job.published == "2026-11-02T09:30:00+00:00"
    assert items[1].title == "Brand Designer — Pixel & Co"


def test_parse_remoteok_skips_legal_notice():
    items = parse_remoteok(json.loads(fixture_bytes("remoteok.json")), src(type="remoteok"))
    assert len(items) == 2
    video = items[0]
    assert video.title == "Video Editor (After Effects) — Clipwise"
    assert video.meta["location"] == "Worldwide"
    assert video.meta["salary_usd"] == "30000–50000"
    assert video.published == datetime.fromtimestamp(1762100000, tz=UTC).isoformat()


def test_parsers_tolerate_garbage():
    assert parse_rss(b"not xml at all", src()) == []
    assert parse_jobicy({}, src()) == []
    assert parse_jobicy({"jobs": [None, "x"]}, src()) == []
    assert parse_remoteok([], src()) == []
    assert parse_remoteok(None, src()) == []


# ---------- helpers ----------

def test_make_id_matches_v1_so_seen_state_carries_over():
    import hashlib

    url = "https://blenderartists.org/t/some-gig/123/"
    v1 = hashlib.sha1(url.strip().rstrip("/").encode()).hexdigest()[:16]
    assert make_id(url) == v1
    assert make_id(url) == make_id(url.rstrip("/"))


def test_clean_and_iso_any():
    assert clean("<p>Hello&nbsp;<b>world</b></p>   again") == "Hello world again"
    assert clean(None) == ""
    assert iso_any("2026-11-02 09:30:00") == "2026-11-02T09:30:00+00:00"
    assert iso_any("2026-11-02T10:00:00Z") == "2026-11-02T10:00:00+00:00"
    assert iso_any(0) is None or iso_any(0).startswith("1970")
    assert iso_any("not a date") is None
    assert iso_any("") is None


# ---------- filters ----------

def _item(title="Blender product render job", summary="", published=None) -> Item:
    return Item(id="1", source="s", title=title, url="https://x.test/1", summary=summary, published=published)


def test_keyword_filter_uses_word_boundaries():
    s = src(keywords=["3d", "go developer"])
    assert passes(_item("Senior 3D artist"), s, [], 0)
    assert not passes(_item("Senior 3Dish artist"), s, [], 0)
    assert passes(_item("Hiring", "need a Go developer"), s, [], 0)
    assert not passes(_item("Accountant"), s, [], 0)


def test_title_must_match_and_excludes():
    assert not passes(_item("[For Hire] me"), src(), [r"\[for hire\]"], 0)
    assert passes(_item("[Hiring] 3D artist"), src(title_must_match=r"\[hiring\]"), [], 0)
    assert not passes(_item("3D artist"), src(title_must_match=r"\[hiring\]"), [], 0)
    assert not passes(_item("Crypto gig"), src(exclude=["crypto"]), [], 0)


def test_age_filter():
    now = datetime(2026, 11, 3, tzinfo=UTC)
    fresh = _item(published="2026-11-01T00:00:00+00:00")
    old = _item(published="2026-10-01T00:00:00+00:00")
    assert passes(fresh, src(), [], 7, now=now)
    assert not passes(old, src(), [], 7, now=now)
    assert passes(old, src(), [], 0, now=now)  # 0 disables the age filter
    assert passes(_item(published=None), src(), [], 7, now=now)


# ---------- fetching ----------

def _mock_all(router):
    router.get("https://ba.test/paid.rss").respond(200, content=fixture_bytes("blenderartists_paid_work.rss"))
    router.get("https://wwr.test/design.rss").respond(200, content=fixture_bytes("wwr_design.rss"))
    router.get("https://jobicy.test/api").respond(200, content=fixture_bytes("jobicy_design.json"))
    router.get("https://remoteok.test/api").respond(200, content=fixture_bytes("remoteok.json"))


async def test_collect_all_sources_and_dedupe():
    settings = Settings(max_age_days=0, exclude=[r"\[for hire\]"])
    sources = [SourceConfig(**s) for s in SOURCES]
    sources.append(SourceConfig(name="BA mirror", type="rss", url="https://mirror.test/paid.rss"))
    with respx.mock(assert_all_called=True) as router:
        _mock_all(router)
        router.get("https://mirror.test/paid.rss").respond(200, content=fixture_bytes("blenderartists_paid_work.rss"))
        async with make_client() as client:
            items, results = await collect(client, sources, settings)
    assert all(r.ok for r in results)
    by_name = {r.source.name: r for r in results}
    assert by_name["Blender Artists · Paid Work"].fetched == 3
    assert by_name["Blender Artists · Paid Work"].kept == 2  # [For Hire] dropped
    assert by_name["Remote OK"].kept == 1  # keyword filter keeps only the video editor
    assert len({i.id for i in items}) == len(items)  # the mirror's copies were deduplicated
    assert len(items) == 2 + 2 + 2 + 1


async def test_one_failing_source_never_breaks_the_others(monkeypatch):
    monkeypatch.setattr("radar.core.http.asyncio.sleep", _no_sleep)
    settings = Settings(max_age_days=0)
    sources = [SourceConfig(**s) for s in SOURCES]
    with respx.mock as router:
        _mock_all(router)
        router.get("https://wwr.test/design.rss").respond(503)
        router.get("https://jobicy.test/api").mock(side_effect=httpx.ConnectError("boom"))
        async with make_client() as client:
            items, results = await collect(client, sources, settings)
    by_name = {r.source.name: r for r in results}
    assert not by_name["WWR · Design"].ok and "503" in by_name["WWR · Design"].error
    assert not by_name["Jobicy · Design"].ok and "ConnectError" in by_name["Jobicy · Design"].error
    assert by_name["Blender Artists · Paid Work"].ok and by_name["Remote OK"].ok
    assert len(items) == 3 + 1


async def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("radar.core.http.asyncio.sleep", _no_sleep)
    with respx.mock as router:
        route = router.get("https://ba.test/paid.rss")
        route.side_effect = [httpx.Response(502), httpx.Response(200, content=fixture_bytes("wwr_design.rss"))]
        async with make_client() as client:
            res = await fetch_source(client, SourceConfig(**SOURCES[0]), Settings(max_age_days=0))
    assert res.ok and res.fetched == 2
    assert route.call_count == 2


async def test_unknown_source_type_is_reported_not_raised():
    async with make_client() as client:
        res = await fetch_source(client, src(type="carrier-pigeon"), Settings())
    assert not res.ok and "unknown type" in res.error


async def test_bad_json_is_a_source_failure():
    with respx.mock as router:
        router.get("https://jobicy.test/api").respond(200, content=b"<html>maintenance</html>")
        async with make_client() as client:
            res = await fetch_source(client, SourceConfig(**SOURCES[2]), Settings())
    assert not res.ok and "JSONDecodeError" in res.error


async def _no_sleep(_seconds):
    return None
