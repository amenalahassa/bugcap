"""T005: store migration (user_version 0 -> 1) is lossless and idempotent."""
import json
import sqlite3

import pytest

from bugcap.store import Store

LEGACY_SCHEMA = """
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    image_paths TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    synced_refs TEXT NOT NULL DEFAULT '{}'
);
"""


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO reports (created_at, title, notes, tags, status) VALUES (?,?,?,?,?)",
        ("2025-01-01T00:00:00+00:00", "old bug", "legacy note", json.dumps(["x"]), "wontfix"),
    )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()


def test_legacy_db_migrates_losslessly(tmp_path):
    db = tmp_path / "bugcap.db"
    _legacy_db(db)

    store = Store(db)
    reports = store.list()
    assert len(reports) == 1
    r = reports[0]
    assert r.title == "old bug"
    assert r.notes == "legacy note"
    assert r.status == "wontfix"  # free-text legacy status tolerated on read
    assert r.repo is None
    assert r.body == ""

    cols = {row[1]: row for row in store._conn.execute("PRAGMA table_info(reports)")}
    assert "repo" in cols and cols["repo"][2] == "TEXT"
    assert "body" in cols and cols["body"][2] == "TEXT"
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    store.close()


def test_second_open_is_noop(tmp_path):
    db = tmp_path / "bugcap.db"
    _legacy_db(db)
    Store(db).close()
    store = Store(db)  # reopening a migrated DB must not error or duplicate
    assert len(store.list()) == 1
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    store.close()


def test_half_migrated_db(tmp_path):
    db = tmp_path / "bugcap.db"
    _legacy_db(db)
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE reports ADD COLUMN repo TEXT")  # only repo added
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    store = Store(db)  # should add only `body`, without error
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(reports)")}
    assert {"repo", "body"} <= cols
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    store.close()


def test_fresh_db_gets_new_schema(tmp_path):
    db = tmp_path / "bugcap.db"
    store = Store(db)
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(reports)")}
    assert {"repo", "body"} <= cols
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    rep = store.add("new bug", repo="owner/repo", body="desc")
    assert rep.repo == "owner/repo"
    assert rep.body == "desc"
    store.close()
