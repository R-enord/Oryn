import respx

from radar.core.config import Config
from radar.opportunities.watch import run_watch
from radar.reports.digest import digest_attempts, run_digest
from tests.conftest import (
    FakeClaude,
    RecordingNotifier,
    echo_scores,
    fixture_bytes,
    make_ctx,
    response,
    text,
    write_root,
)


def mock_feeds(router):
    router.get("https://ba.test/paid.rss").respond(200, content=fixture_bytes("blenderartists_paid_work.rss"))
    router.get("https://wwr.test/design.rss").respond(200, content=fixture_bytes("wwr_design.rss"))
    router.get("https://jobicy.test/api").respond(200, content=fixture_bytes("jobicy_design.json"))
    router.get("https://remoteok.test/api").respond(200, content=fixture_bytes("remoteok.json"))


def by_title(item_text: str):
    """Scores like a sensible talent agent would, keyed on the fixture titles."""
    if "furniture product renders" in item_text or "Product Visualization" in item_text:
        return 90, "core", "yes"
    if "product animation" in item_text:
        return 80, "core", "unclear"
    if "UX Researcher" in item_text:
        return 85, "stretch", "no"  # high score but location-restricted: digest only, no ping
    if "Video Editor" in item_text:
        return 60, "core", "yes"
    return 20, "skip", "unclear"


async def test_watch_scores_stores_and_alerts(config, db):
    notifier = RecordingNotifier()
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title)]), notifier)
    with respx.mock as router:
        mock_feeds(router)
        result = await run_watch(ctx)
    assert result.passed == 7 and result.new == 7 and result.scored == 7
    # 3 alerts: two at 90 and one at 80; the US-only 85 is held back; 60 is digest-only.
    assert result.alerts_sent == 3 and len(notifier.sent) == 3
    assert "furniture product renders" in notifier.sent[0] or "Product Visualization" in notifier.sent[0]
    assert all("UX Researcher" not in m for m in notifier.sent)
    assert result.matches == 5  # >= digest_score and not skip
    queue = db.digest_queue(50)
    assert [q["score"] for q in queue] == [90, 90, 85, 80, 60]
    assert sum(1 for q in queue if q["alerted_at"]) == 3
    sources = {s["name"]: s for s in db.sources()}
    assert sources["Remote OK"]["last_item_count"] == 2 and sources["Remote OK"]["fail_count"] == 0


async def test_second_run_sees_nothing_new(config, db):
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title)]), RecordingNotifier())
    with respx.mock as router:
        mock_feeds(router)
        await run_watch(ctx)
        again = await run_watch(ctx)  # FakeClaude has no second reply: it must not be called
    assert again.new == 0 and again.scored == 0


async def test_failed_scoring_batch_is_retried_next_run(tmp_path, db):
    config = Config(root=write_root(tmp_path, settings={"batch_size": 4}))
    claude = FakeClaude([RuntimeError("overloaded"), echo_scores(by_title), echo_scores(by_title)])
    ctx = make_ctx(config, db, claude, RecordingNotifier())
    with respx.mock as router:
        mock_feeds(router)
        first = await run_watch(ctx)
        second = await run_watch(ctx)
    assert first.scored == 3  # batch 1 (4 items) failed, batch 2 (3 items) scored
    assert second.new == 4 and second.scored == 4


async def test_alert_cap_and_failed_alerts(tmp_path, db):
    config = Config(root=write_root(tmp_path, settings={"max_alerts_per_run": 1}))
    notifier = RecordingNotifier(telegram_ok=False)
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title)]), notifier)
    with respx.mock as router:
        mock_feeds(router)
        result = await run_watch(ctx)
    assert len(notifier.sent) == 1 and result.alerts_sent == 0
    assert result.alerts_failed == 1 and result.alerts_held == 2
    assert "1 alerts NOT delivered" in result.summary() and "2 over the per-run cap" in result.summary()
    assert all(q["alerted_at"] is None for q in db.digest_queue(0))  # still goes to the digest


async def test_fake_ai_needs_no_key(config, db):
    ctx = make_ctx(config, db, None, RecordingNotifier(), fake_ai=True)
    with respx.mock as router:
        mock_feeds(router)
        result = await run_watch(ctx)
    assert result.scored == 7


RESEARCH = response(text('<json>{"picks":[{"title":"Contest","url":"https://c.example","track":"core",'
                         '"what":"w","why_you":"y","first_step":"s"}],"insight":"i"}</json>'))


async def _seed_matches(ctx):
    with respx.mock as router:
        mock_feeds(router)
        await run_watch(ctx)


async def test_digest_sends_and_clears_queue(config, db):
    notifier = RecordingNotifier()
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title), RESEARCH]), notifier)
    await _seed_matches(ctx)
    notifier.sent.clear()
    result = await run_digest(ctx)
    assert result.matches == 5 and result.picks == 1 and result.emailed is True and result.delivered
    assert len(notifier.emails) == 1 and "5 matches, 1 research picks" in notifier.emails[0][0]
    assert "Full digest is in your inbox." in notifier.sent[0]
    assert db.digest_queue(50) == []
    assert db.recent_research_urls() == ["https://c.example"]
    assert db.get("digest.last_sent_date") is not None


async def test_digest_keeps_queue_when_email_fails(config, db):
    notifier = RecordingNotifier(email_ok=False)
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title), RESEARCH]), notifier)
    await _seed_matches(ctx)
    result = await run_digest(ctx)
    assert result.emailed is False and not result.delivered
    assert len(db.digest_queue(50)) == 5  # kept for tomorrow
    assert "could not be sent" in notifier.sent[-1]
    assert db.get("digest.last_sent_date") is None


async def test_digest_without_email_counts_telegram_as_delivery(config, db):
    notifier = RecordingNotifier(email_ok=None)
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title), RESEARCH]), notifier)
    await _seed_matches(ctx)
    result = await run_digest(ctx)
    assert result.emailed is None and result.delivered and notifier.emails == []
    assert db.digest_queue(50) == []


async def test_digest_still_sends_matches_when_research_fails(config, db):
    notifier = RecordingNotifier()
    ctx = make_ctx(config, db, FakeClaude([echo_scores(by_title), RuntimeError("search is off")]), notifier)
    await _seed_matches(ctx)
    result = await run_digest(ctx)
    assert result.matches == 5 and result.picks == 0
    assert "search is off" in result.research_error
    assert "Research step" in notifier.sent[-1]


async def test_digest_attempts_are_counted_per_day(config, db):
    ctx = make_ctx(config, db, None, RecordingNotifier(), fake_ai=True)
    await run_digest(ctx)
    await run_digest(ctx)
    today = db.get("digest.attempts").split(":")[0]
    assert digest_attempts(db, today) == 2
    assert digest_attempts(db, "1999-01-01") == 0


async def test_digest_uses_lagos_date_for_focus_and_label(config, db, monkeypatch):
    """23:30 UTC on Tuesday is already Wednesday in Lagos: label, focus and prompt must all say Wednesday."""
    from datetime import UTC, datetime

    import radar.reports.digest as digest_mod

    monkeypatch.setattr(digest_mod, "now_utc", lambda: datetime(2026, 11, 3, 23, 30, tzinfo=UTC))
    notifier = RecordingNotifier()
    claude = FakeClaude([RESEARCH])
    ctx = make_ctx(config, db, claude, notifier)
    await run_digest(ctx)
    assert "Wed 04 Nov 2026" in notifier.sent[-1]
    assert "(Brands needing visuals)" in notifier.sent[-1]
    assert "Today is Wednesday 04 November 2026" in claude.calls[0]["messages"][0]["content"]
    assert digest_attempts(db, "2026-11-04") == 1
