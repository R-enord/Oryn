"""SQLite storage (WAL mode) with simple, forward-only migrations.

The database is small and local, so calls are synchronous; each one takes well under a millisecond.
Migrations are append-only: never edit one that has shipped, add a new one instead.
"""
from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from .timeutil import iso, now_utc

MIGRATIONS: list[str] = [
    # 1 — Phase 0: v1 ported (seen ids, scored opportunities, research picks), plus service bookkeeping.
    """
    CREATE TABLE sources (
        name TEXT PRIMARY KEY,
        type TEXT,
        url TEXT,
        etag TEXT,
        last_modified TEXT,
        last_ok_at TEXT,
        last_error TEXT,
        last_error_at TEXT,
        fail_count INTEGER NOT NULL DEFAULT 0,
        last_item_count INTEGER,
        muted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE seen (
        id TEXT PRIMARY KEY,
        seen_at TEXT NOT NULL
    );
    CREATE TABLE opportunities (
        id TEXT PRIMARY KEY,
        source TEXT,
        url TEXT,
        title TEXT,
        summary TEXT,
        meta TEXT,
        published_at TEXT,
        fetched_at TEXT,
        scored_at TEXT,
        score INTEGER,
        track TEXT,
        pay TEXT,
        location_ok TEXT,
        why TEXT,
        pitch TEXT,
        red_flags TEXT,
        status TEXT NOT NULL DEFAULT 'new',
        feedback TEXT,
        value_usd REAL,
        alerted_at TEXT,
        digested_at TEXT
    );
    CREATE INDEX idx_opp_digest ON opportunities (digested_at, score);
    CREATE INDEX idx_opp_scored ON opportunities (scored_at);
    CREATE TABLE research_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT NOT NULL,
        focus TEXT,
        title TEXT,
        url TEXT,
        verified INTEGER,
        track TEXT,
        potential TEXT,
        first_step TEXT,
        what TEXT,
        why_you TEXT,
        deadline TEXT
    );
    CREATE INDEX idx_research_run ON research_picks (run_at);
    CREATE TABLE usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        purpose TEXT,
        model TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        cache_read_tokens INTEGER,
        cache_write_tokens INTEGER,
        searches INTEGER,
        est_cost_usd REAL
    );
    CREATE INDEX idx_usage_at ON usage (at);
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        ok INTEGER,
        summary TEXT
    );
    CREATE INDEX idx_runs_job ON runs (job, started_at);
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
]

OPPORTUNITY_RESULT_FIELDS = ("score", "track", "pay", "location_ok", "why", "pitch", "red_flags")


class Database:
    def __init__(self, conn: sqlite3.Connection, path: Path | None):
        self.conn = conn
        self.path = path

    # ---------- lifecycle ----------

    @classmethod
    def open(cls, path: Path | str, *, dry_run: bool = False) -> Database:
        """Opens (and migrates) the database.

        dry_run=True works on an in-memory copy, so nothing is written to disk.
        """
        path = Path(path)
        if dry_run:
            conn = cls._connect(":memory:")
            if path.exists():
                src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    src.backup(conn)
                finally:
                    src.close()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = cls._connect(str(path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        db = cls(conn, None if dry_run else path)
        db.migrate()
        return db

    @staticmethod
    def _connect(target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    @property
    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> int:
        current = self.schema_version
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            # executescript commits implicitly, so wrap the script itself in a transaction.
            self.conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        return self.schema_version

    def journal_mode(self) -> str:
        return str(self.conn.execute("PRAGMA journal_mode").fetchone()[0])

    # ---------- key/value ----------

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---------- seen ids ----------

    def seen_ids(self, ids: Iterable[str]) -> set[str]:
        ids = list(ids)
        found: set[str] = set()
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            found.update(r[0] for r in self.conn.execute(f"SELECT id FROM seen WHERE id IN ({marks})", chunk))
        return found

    def mark_seen(self, ids: Iterable[str], at: str | None = None) -> None:
        at = at or iso()
        with self.tx() as c:
            c.executemany("INSERT OR IGNORE INTO seen (id, seen_at) VALUES (?, ?)", [(i, at) for i in ids])

    def prune_seen(self, days: int = 90) -> int:
        cutoff = iso(now_utc() - timedelta(days=days))
        cur = self.conn.execute("DELETE FROM seen WHERE seen_at < ? AND id NOT IN (SELECT id FROM opportunities)",
                                (cutoff,))
        return cur.rowcount

    # ---------- opportunities ----------

    def save_opportunity(self, item: dict, result: dict, scored_at: str) -> None:
        """Stores a scored post. `item` is Item.to_dict(); `result` is the scorer's output for it."""
        values = {
            "id": item["id"], "source": item.get("source"), "url": item.get("url"), "title": item.get("title"),
            "summary": item.get("summary"), "meta": json.dumps(item.get("meta") or {}, ensure_ascii=False),
            "published_at": item.get("published"), "fetched_at": item.get("fetched_at") or scored_at,
            "scored_at": scored_at,
        }
        for key in OPPORTUNITY_RESULT_FIELDS:
            values[key] = result.get(key)
        cols = ", ".join(values)
        marks = ", ".join(f":{k}" for k in values)
        updates = ", ".join(f"{k} = excluded.{k}" for k in values if k != "id")
        self.conn.execute(f"INSERT INTO opportunities ({cols}) VALUES ({marks}) "
                          f"ON CONFLICT(id) DO UPDATE SET {updates}", values)

    def get_opportunity(self, opp_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        return _opp_dict(row) if row else None

    def mark_alerted(self, opp_id: str, at: str | None = None) -> None:
        self.conn.execute("UPDATE opportunities SET alerted_at = ? WHERE id = ?", (at or iso(), opp_id))

    def digest_queue(self, min_score: int, limit: int = 300) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM opportunities WHERE digested_at IS NULL AND score >= ? AND COALESCE(track, '') != 'skip' "
            "ORDER BY score DESC, scored_at DESC LIMIT ?", (min_score, limit)).fetchall()
        return [_opp_dict(r) for r in rows]

    def mark_digested(self, ids: Iterable[str], at: str | None = None) -> None:
        at = at or iso()
        with self.tx() as c:
            c.executemany("UPDATE opportunities SET digested_at = ? WHERE id = ?", [(at, i) for i in ids])

    def count_opportunities_since(self, since: str) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS scored, SUM(alerted_at IS NOT NULL) AS alerted FROM opportunities WHERE scored_at >= ?",
            (since,)).fetchone()
        return {"scored": row["scored"] or 0, "alerted": row["alerted"] or 0}

    # ---------- research ----------

    def recent_research_urls(self, limit: int = 60) -> list[str]:
        rows = self.conn.execute("SELECT url FROM research_picks WHERE url IS NOT NULL AND url != '' "
                                 "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in reversed(rows)]

    def save_research_picks(self, run_at: str, focus: str, picks: list[dict]) -> None:
        rows = [(run_at, focus, p.get("title"), p.get("url"), int(bool(p.get("verified"))), p.get("track"),
                 _s(p.get("potential")), p.get("first_step"), p.get("what"), p.get("why_you"), _s(p.get("deadline")))
                for p in picks]
        with self.tx() as c:
            c.executemany("INSERT INTO research_picks (run_at, focus, title, url, verified, track, potential, "
                          "first_step, what, why_you, deadline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # ---------- sources ----------

    def record_source_result(self, name: str, type_: str, url: str, *, ok: bool, count: int | None = None,
                             error: str | None = None, at: str | None = None) -> None:
        at = at or iso()
        self.conn.execute("INSERT INTO sources (name, type, url) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                          "type = excluded.type, url = excluded.url", (name, type_, url))
        if ok:
            self.conn.execute("UPDATE sources SET last_ok_at = ?, fail_count = 0, last_item_count = ? WHERE name = ?",
                              (at, count, name))
        else:
            self.conn.execute("UPDATE sources SET last_error = ?, last_error_at = ?, fail_count = fail_count + 1 "
                              "WHERE name = ?", ((error or "")[:500], at, name))

    def sources(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM sources ORDER BY name")]

    # ---------- usage ----------

    def record_usage(self, *, purpose: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
                     cache_read_tokens: int = 0, cache_write_tokens: int = 0, searches: int = 0,
                     est_cost_usd: float | None = None, at: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO usage (at, purpose, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
            "searches, est_cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (at or iso(), purpose, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             searches, est_cost_usd))

    def usage_since(self, since: str) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            "SUM(searches) AS searches FROM usage WHERE at >= ?", (since,)).fetchone()
        return {k: int(row[k] or 0) for k in ("calls", "input_tokens", "output_tokens", "searches")}

    # ---------- job runs ----------

    def start_run(self, job: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (job, started_at) VALUES (?, ?)", (job, iso()))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, ok: bool, summary: str = "") -> None:
        self.conn.execute("UPDATE runs SET finished_at = ?, ok = ?, summary = ? WHERE id = ?",
                          (iso(), int(ok), summary[:1000], run_id))

    def last_run(self, job: str, *, ok_only: bool = False) -> dict | None:
        sql = "SELECT * FROM runs WHERE job = ? AND finished_at IS NOT NULL"
        if ok_only:
            sql += " AND ok = 1"
        row = self.conn.execute(sql + " ORDER BY id DESC LIMIT 1", (job,)).fetchone()
        return dict(row) if row else None

    def prune_runs(self, days: int = 60) -> None:
        self.conn.execute("DELETE FROM runs WHERE started_at < ?", (iso(now_utc() - timedelta(days=days)),))

    # ---------- backups ----------

    def backup_to(self, backup_dir: Path, keep_days: int = 14) -> Path:
        """Consistent snapshot (safe while the service runs), gzipped, older ones pruned."""
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_utc().strftime("%Y%m%d-%H%M%S")
        raw = backup_dir / f"radar-{stamp}.db"
        dest = sqlite3.connect(str(raw))
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        gz = raw.with_suffix(".db.gz")
        with open(raw, "rb") as src, gzip.open(gz, "wb") as out:
            shutil.copyfileobj(src, out)
        raw.unlink()
        cutoff = (now_utc() - timedelta(days=keep_days)).timestamp()
        for old in backup_dir.glob("radar-*.db.gz"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
        return gz


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _opp_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except json.JSONDecodeError:
        d["meta"] = {}
    d["published"] = d.get("published_at")
    return d
