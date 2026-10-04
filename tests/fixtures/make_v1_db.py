"""Build a database in the pre-feature-002 shape (user_version = 1, image_paths JSON)."""
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

V1_SCHEMA = """
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    image_paths TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    repo TEXT,
    synced_refs TEXT NOT NULL DEFAULT '{}'
);
"""


def build(path: Path, images: list[str] | None = None, outside: str | None = None) -> Path:
    """`images`: two paths for report 1; `outside`: a path outside the data dir for report 3."""
    images = images or ["/data/images/a.png", "/data/images/b.png"]
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    rows = [
        ("2025-01-01T00:00:00+00:00", "two images", "", "see screenshots", json.dumps(images),
         json.dumps(["auth", "proj"]), "open", "proj", json.dumps({"github.issue": "o/r#1"})),
        ("2025-01-02T00:00:00+00:00", "no images", "", "", "[]", "[]", "resolved", None, "{}"),
    ]
    if outside:
        rows.append(("2025-01-03T00:00:00+00:00", "outside", "", "", json.dumps([outside]),
                     "[]", "open", None, "{}"))
    conn.executemany(
        "INSERT INTO reports (created_at, title, body, notes, image_paths, tags, status, repo, synced_refs) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "v1.db"
    out.unlink(missing_ok=True)
    build(out)
    print(out)
