from datetime import datetime, time

import pytest

from radar.app import MAX_DIGEST_ATTEMPTS_PER_DAY, build_scheduler, digest_catch_up_due
from radar.core.timeutil import LAGOS
from radar.jobs import ALERT_AFTER_FAILURES, run_job
from tests.conftest import RecordingNotifier, make_ctx

SEVEN = time(7, 0)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=LAGOS)


@pytest.mark.parametrize(("now", "last_sent", "attempts", "due"), [
    (at(6, 59), None, 0, False),                 # before digest time
    (at(7, 0), None, 0, True),                   # missed this morning's run
    (at(15), "2026-11-02", 0, True),             # last one was yesterday
    (at(15), "2026-11-03", 1, False),            # already sent today
    (at(15), None, MAX_DIGEST_ATTEMPTS_PER_DAY, False),  # crash loop: stop re-running paid research
])
def test_digest_catch_up(now, last_sent, attempts, due):
    assert digest_catch_up_due(now, SEVEN, last_sent, attempts) is due


async def test_job_failures_alert_once_then_recover(config, db):
    notifier = RecordingNotifier()
    ctx = make_ctx(config, db, notifier=notifier)

    async def broken(_ctx):
        raise RuntimeError("feed parser exploded")

    for _ in range(ALERT_AFTER_FAILURES + 2):
        assert await run_job(ctx, "watch", broken) is None
    assert len(notifier.sent) == 1 and "failed 3 times" in notifier.sent[0]
    assert db.last_run("watch")["ok"] == 0

    class Ok:
        def summary(self):
            return "all good"

    async def fine(_ctx):
        return Ok()

    assert await run_job(ctx, "watch", fine) is not None
    assert "working again" in notifier.sent[-1]
    assert db.last_run("watch")["summary"] == "all good"


async def test_job_does_not_run_twice_at_once(config, db):
    ctx = make_ctx(config, db)
    async with ctx.lock("watch"):
        assert await run_job(ctx, "watch", lambda c: None) is None
    assert db.last_run("watch") is None


def test_scheduler_jobs(config, db):
    ctx = make_ctx(config, db)
    sched = build_scheduler(ctx)
    ids = {j.id for j in sched.get_jobs()}
    assert {"watch", "digest", "backup", "housekeeping", "heartbeat"} <= ids
