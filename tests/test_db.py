import gzip
import os
import sqlite3
import time

from radar.core.db import MIGRATIONS, Database
from radar.importer import import_v1_state
from tests.conftest import FIXTURES


def test_migrations_and_wal(tmp_path):
    path = tmp_path / "radar.db"
    db = Database.open(path)
    assert db.schema_version == len(MIGRATIONS)
    assert db.journal_mode() == "wal"
    db.close()
    again = Database.open(path)  # re-opening is a no-op
    assert again.schema_version == len(MIGRATIONS)
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sources", "seen", "opportunities", "research_picks", "usage", "runs", "kv"} <= tables
    again.close()


def test_seen_and_opportunities(db):
    db.mark_seen(["a", "b"], "2026-11-01T00:00:00+00:00")
    assert db.seen_ids(["a", "c"]) == {"a"}
    item = {"id": "a", "source": "BA", "url": "https://x/a", "title": "T", "summary": "S", "published": None,
            "meta": {"k": "v"}}
    db.save_opportunity(item, {"score": 77, "track": "core", "location_ok": "yes", "why": "w"}, "2026-11-01T01:00:00+00:00")
    db.save_opportunity({**item, "title": "T2"}, {"score": 79, "track": "core"}, "2026-11-01T02:00:00+00:00")  # upsert
    opp = db.get_opportunity("a")
    assert opp["title"] == "T2" and opp["score"] == 79 and opp["meta"] == {"k": "v"} and opp["status"] == "new"
    assert [o["id"] for o in db.digest_queue(50)] == ["a"]
    db.mark_digested(["a"])
    assert db.digest_queue(50) == []


def test_skip_and_low_scores_stay_out_of_digest(db):
    for i, (score, track) in enumerate([(90, "skip"), (40, "core"), (60, "stretch")]):
        db.save_opportunity({"id": str(i)}, {"score": score, "track": track}, "2026-11-01T00:00:00+00:00")
    assert [o["id"] for o in db.digest_queue(50)] == ["2"]


def test_source_health_counts_consecutive_failures(db):
    db.record_source_result("BA", "rss", "u", ok=False, error="boom")
    db.record_source_result("BA", "rss", "u", ok=False, error="boom again")
    row = db.sources()[0]
    assert row["fail_count"] == 2 and row["last_error"] == "boom again"
    db.record_source_result("BA", "rss", "u", ok=True, count=12)
    row = db.sources()[0]
    assert row["fail_count"] == 0 and row["last_item_count"] == 12 and row["last_ok_at"]


def test_runs_and_kv(db):
    run = db.start_run("watch")
    assert db.last_run("watch") is None  # unfinished runs don't count
    db.finish_run(run, True, "fine")
    assert db.last_run("watch")["summary"] == "fine"
    bad = db.start_run("watch")
    db.finish_run(bad, False, "broke")
    assert db.last_run("watch")["ok"] == 0
    assert db.last_run("watch", ok_only=True)["summary"] == "fine"
    db.set("k", "1")
    db.set("k", "2")
    assert db.get("k") == "2" and db.get("missing", "d") == "d"


def test_dry_run_never_touches_the_file(tmp_path):
    path = tmp_path / "radar.db"
    real = Database.open(path)
    real.set("k", "real")
    real.close()
    dry = Database.open(path, dry_run=True)
    assert dry.get("k") == "real"  # sees existing data
    dry.set("k", "dry")
    dry.mark_seen(["x"])
    dry.close()
    check = Database.open(path)
    assert check.get("k") == "real" and check.seen_ids(["x"]) == set()
    check.close()


def test_dry_run_without_existing_db_creates_nothing(tmp_path):
    db = Database.open(tmp_path / "nope.db", dry_run=True)
    db.set("k", "v")
    db.close()
    assert not (tmp_path / "nope.db").exists()


def test_backup_snapshot_and_prune(db, tmp_path):
    db.set("k", "v")
    backups = tmp_path / "backups"
    backups.mkdir()
    stale = backups / "radar-20200101-000000.db.gz"
    stale.write_bytes(b"old")
    old = time.time() - 20 * 86400
    os.utime(stale, (old, old))
    path = db.backup_to(backups, keep_days=14)
    assert path.exists() and not stale.exists()
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(path.read_bytes()))
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT value FROM kv WHERE key='k'").fetchone()[0] == "v"
    conn.close()


def test_import_v1_state_is_idempotent(db):
    counts = import_v1_state(db, FIXTURES / "v1_state")
    assert counts == {"seen": 2, "queued": 1, "research_urls": 2}
    assert db.seen_ids(["aaaaaaaaaaaaaaaa", "cccccccccccccccc"]) == {"aaaaaaaaaaaaaaaa", "cccccccccccccccc"}
    queued = db.digest_queue(50)
    assert len(queued) == 1 and queued[0]["title"] == "Old queued gig" and queued[0]["alerted_at"]
    assert db.recent_research_urls() == ["https://example.com/contest", "https://example.com/grant"]
    assert import_v1_state(db, FIXTURES / "v1_state") == {"seen": 2, "queued": 0, "research_urls": 0}


def test_import_v1_handles_missing_files(db, tmp_path):
    assert import_v1_state(db, tmp_path / "nothing") == {"seen": 0, "queued": 0, "research_urls": 0}
