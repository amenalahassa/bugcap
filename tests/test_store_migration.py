"""T005: store migration (user_version 0 -> current) is lossless and idempotent."""
import json
import sqlite3

import pytest

from bugcap.store import SCHEMA_VERSION, Store

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
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.close()


def test_second_open_is_noop(tmp_path):
    db = tmp_path / "bugcap.db"
    _legacy_db(db)
    Store(db).close()
    store = Store(db)  # reopening a migrated DB must not error or duplicate
    assert len(store.list()) == 1
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.close()


def test_fresh_db_gets_new_schema(tmp_path):
    db = tmp_path / "bugcap.db"
    store = Store(db)
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(reports)")}
    assert {"repo", "body"} <= cols
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    rep = store.add("new bug", repo="owner/repo", body="desc")
    assert rep.repo == "owner/repo"
    assert rep.body == "desc"
    store.close()


# --- v1 -> v2 (media table) ----------------------------------------------------


from fixtures.make_v1_db import build  # noqa: E402


def _media(store, report_id):
    return [
        dict(r)
        for r in store._conn.execute("SELECT * FROM media WHERE report_id = ? ORDER BY idx", (report_id,))
    ]


def test_v1_to_v2_keeps_every_report_and_column(tmp_path):
    db = build(tmp_path / "v1.db")
    before = sqlite3.connect(db)
    before.row_factory = sqlite3.Row
    old = [dict(r) for r in before.execute("SELECT * FROM reports ORDER BY id")]
    before.close()

    store = Store(db)
    new = [dict(r) for r in store._conn.execute("SELECT * FROM reports ORDER BY id")]
    # every original column is untouched; the only addition is the media_seq high-water mark
    assert [{k: v for k, v in r.items() if k != "media_seq"} for r in new] == old
    assert [r["media_seq"] for r in new] == [2, 0]
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.close()


def test_legacy_images_become_media_rows(tmp_path):
    store = Store(build(tmp_path / "v1.db"))
    rows = _media(store, 1)
    assert [(r["idx"], r["kind"], r["source"], r["path"]) for r in rows] == [
        (1, "image", "legacy", "/data/images/a.png"),
        (2, "image", "legacy", "/data/images/b.png"),
    ]
    assert all(r["mime"] == "image/png" for r in rows)
    assert _media(store, 2) == []
    assert store.get(1).image_paths == ["/data/images/a.png", "/data/images/b.png"]
    store.close()


def test_legacy_path_under_images_dir_becomes_relative(tmp_path, bugcap_home):
    from bugcap.paths import images_dir

    img = images_dir() / "x.png"
    img.write_bytes(b"12345")
    store = Store(build(tmp_path / "v1.db", images=[str(img), "/elsewhere/y.png"]))
    first, second = _media(store, 1)
    assert first["path"] == "images/x.png" and first["size_bytes"] == 5
    assert second["path"] == "/elsewhere/y.png" and second["size_bytes"] == 0
    assert store.get(1).image_paths[0] == str(img)
    store.close()


def test_reopen_is_noop(tmp_path):
    db = build(tmp_path / "v1.db")
    Store(db).close()
    store = Store(db)
    assert len(_media(store, 1)) == 2
    store.close()


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    db = build(tmp_path / "v1.db")
    import bugcap.store as store_mod

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(store_mod, "guess_mime", boom)
    with pytest.raises(RuntimeError):
        Store(db)
    monkeypatch.undo()

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "media" not in tables
    conn.close()


def test_media_constraints(tmp_path):
    store = Store(tmp_path / "bugcap.db")
    rid = store.add("t").id
    store.insert_media(rid, kind="image", path="/x.png", label="Shot")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_media(rid, kind="image", path="/y.png", label="shot")  # case-insensitive
    with pytest.raises(ValueError):
        store.insert_media(rid, kind="bogus")
    assert [m.idx for m in store.list_media(rid)] == [1]
    store.close()


def test_deleting_report_cascades_media(tmp_path):
    store = Store(tmp_path / "bugcap.db")
    rid = store.add("t", image_paths=["/x.png"]).id
    store._conn.execute("DELETE FROM reports WHERE id = ?", (rid,))
    store._conn.commit()
    assert store._conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0
    store.close()


def test_transaction_rolls_back_everything(tmp_path):
    store = Store(tmp_path / "bugcap.db")
    rid = store.add("t").id
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.insert_media(rid, kind="image", path="/x.png")
            store.update(rid, notes="changed")
            raise RuntimeError("fail")
    report = store.get(rid)
    assert report.media == [] and report.notes == ""
    store.close()


def test_index_never_reused_after_removal(tmp_path):
    store = Store(tmp_path / "bugcap.db")
    rid = store.add("t").id
    a = store.insert_media(rid, path="/a.png")
    b = store.insert_media(rid, path="/b.png")
    store.delete_media(b.id)
    c = store.insert_media(rid, path="/c.png")
    assert (a.idx, b.idx, c.idx) == (1, 2, 3)
    store.close()


def test_migrated_legacy_images_set_high_water_mark(tmp_path):
    store = Store(build(tmp_path / "v1.db"))
    first = store.list_media(1)
    store.delete_media(first[1].id)
    assert store.insert_media(1, path="/n.png").idx == 3
    store.close()


V2_MEDIA = """
CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL CHECK (idx >= 1),
    label TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('image','video','frames','animated')),
    path TEXT,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (report_id, idx)
);
CREATE UNIQUE INDEX media_label_unique ON media (report_id, lower(label)) WHERE label IS NOT NULL;
CREATE TABLE media_frames (
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    frame_no INTEGER NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (media_id, frame_no)
);
"""


def test_v2_to_v3_allows_files_and_keeps_media_and_frames(tmp_path):
    db = tmp_path / "v2.db"
    conn = sqlite3.connect(db)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("ALTER TABLE reports ADD COLUMN repo TEXT")
    conn.execute("ALTER TABLE reports ADD COLUMN body TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE reports ADD COLUMN media_seq INTEGER NOT NULL DEFAULT 0")
    conn.executescript(V2_MEDIA)
    conn.execute("INSERT INTO reports (created_at, title, media_seq) VALUES ('2026-01-01', 'r', 2)")
    conn.execute("INSERT INTO media (report_id, idx, label, kind, path, mime, created_at) "
                 "VALUES (1, 1, 'shot', 'image', 'images/a.png', 'image/png', 'x')")
    conn.execute("INSERT INTO media (report_id, idx, kind, mime, created_at) VALUES (1, 2, 'frames', 'image/png', 'x')")
    conn.execute("INSERT INTO media_frames (media_id, frame_no, path) VALUES (2, 1, 'media/f1.png')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    store = Store(db)
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    media = store.list_media(1)
    assert [(m.idx, m.kind, m.label) for m in media] == [(1, "image", "shot"), (2, "frames", None)]
    assert [f.path for f in media[1].frames] == ["media/f1.png"]
    added = store.insert_media(1, kind="file", path="/tmp/x.pdf", label="spec")
    assert (added.idx, added.kind, added.mime) == (3, "file", "application/pdf")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_media(1, kind="file", path="/tmp/y.pdf", label="SPEC")  # label index survived
    store.close()
