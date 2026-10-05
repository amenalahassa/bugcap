from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import absolute_stored_path, db_path, to_data_relative

SCHEMA_VERSION = 2

MEDIA_KINDS = ("image", "video", "frames", "animated")

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def guess_mime(path) -> str:
    return _MIME.get(Path(str(path)).suffix.lower(), "application/octet-stream")


# Added in schema version 2 (created by _migrate for fresh and upgraded databases).
MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
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
CREATE UNIQUE INDEX IF NOT EXISTS media_label_unique
    ON media (report_id, lower(label)) WHERE label IS NOT NULL;
CREATE TABLE IF NOT EXISTS media_frames (
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    frame_no INTEGER NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (media_id, frame_no)
);
"""

# `reports` table in its version 1 shape; _migrate() brings every database to SCHEMA_VERSION
# (adding the media tables).
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
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

# Allowed statuses for `edit --status`; free-text legacy values are tolerated on read.
STATUSES = ("open", "in-progress", "resolved", "closed", "wontfix")


def normalize_tags(tags) -> list[str]:
    """Trim, drop empties, de-duplicate while preserving order and case."""
    seen: dict[str, None] = {}
    for tag in tags or []:
        cleaned = str(tag).strip()
        if cleaned and cleaned not in seen:
            seen[cleaned] = None
    return list(seen)


@dataclass
class MediaFrame:
    media_id: int
    frame_no: int
    path: str
    size_bytes: int = 0


@dataclass
class Media:
    id: int
    report_id: int
    idx: int
    label: Optional[str]
    kind: str
    path: Optional[str]
    mime: str
    size_bytes: int
    source: Optional[str]
    created_at: str
    frames: list[MediaFrame] = field(default_factory=list)

    @property
    def abs_path(self) -> Optional[str]:
        return absolute_stored_path(self.path) if self.path else None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Media":
        return cls(
            id=row["id"],
            report_id=row["report_id"],
            idx=row["idx"],
            label=row["label"],
            kind=row["kind"],
            path=row["path"],
            mime=row["mime"],
            size_bytes=row["size_bytes"],
            source=row["source"],
            created_at=row["created_at"],
        )


@dataclass
class Report:
    id: Optional[int]
    created_at: str
    title: str
    body: str = ""
    notes: str = ""
    image_paths: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = "open"
    repo: Optional[str] = None
    synced_refs: dict[str, str] = field(default_factory=dict)
    media: list[Media] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Report":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            title=row["title"],
            body=row["body"] if "body" in row.keys() else "",
            notes=row["notes"],
            image_paths=[],  # compatibility view, filled from media by Store._hydrate
            tags=json.loads(row["tags"]),
            status=row["status"],
            repo=row["repo"] if "repo" in row.keys() else None,
            synced_refs=json.loads(row["synced_refs"]),
        )


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or db_path()
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute(SCHEMA)
        self._depth = 0
        self._migrate()
        self._conn.commit()

    # --- transactions ----------------------------------------------------------

    def _commit(self) -> None:
        if self._depth == 0:
            self._conn.commit()

    @contextmanager
    def transaction(self):
        """Group several store calls into one atomic unit (re-entrant)."""
        if self._depth == 0:
            self._conn.commit()
            self._conn.execute("BEGIN")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("COMMIT")

    # --- migration -------------------------------------------------------------

    def _migrate(self) -> None:
        """PRAGMA user_version-based migration to SCHEMA_VERSION, idempotent and row-preserving."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(reports)")}
        try:
            self._conn.execute("BEGIN")
            if version < 1:
                if "repo" not in columns:
                    self._conn.execute("ALTER TABLE reports ADD COLUMN repo TEXT")
                if "body" not in columns:
                    self._conn.execute("ALTER TABLE reports ADD COLUMN body TEXT NOT NULL DEFAULT ''")
            if version < 2:
                self._migrate_media()
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _migrate_media(self) -> None:
        """v1 -> v2: create the media tables and copy each legacy image_paths entry into them.
        The image_paths column is left untouched."""
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(reports)")}
        if "media_seq" not in columns:  # high-water mark: media indexes are never reused
            self._conn.execute("ALTER TABLE reports ADD COLUMN media_seq INTEGER NOT NULL DEFAULT 0")
        for statement in MEDIA_SCHEMA.split(";"):
            if statement.strip():
                self._conn.execute(statement)
        rows = self._conn.execute("SELECT id, created_at, image_paths FROM reports").fetchall()
        for row in rows:
            try:
                paths = json.loads(row["image_paths"] or "[]")
            except ValueError:
                paths = []
            for position, legacy in enumerate(paths):
                legacy = str(legacy)
                try:
                    size = Path(legacy).stat().st_size
                except OSError:
                    size = 0
                self._conn.execute(
                    "INSERT INTO media (report_id, idx, kind, path, mime, size_bytes, source, created_at) "
                    "VALUES (?, ?, 'image', ?, ?, ?, 'legacy', ?)",
                    (row["id"], position + 1, to_data_relative(legacy), guess_mime(legacy), size, row["created_at"]),
                )
            if paths:
                self._conn.execute("UPDATE reports SET media_seq = ? WHERE id = ?", (len(paths), row["id"]))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- reports ---------------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> Report:
        report = Report.from_row(row)
        report.media = self.list_media(report.id)
        report.image_paths = [m.abs_path for m in report.media if m.kind == "image" and m.path]
        return report

    def add(
        self,
        title: str,
        notes: str = "",
        image_paths: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        repo: Optional[str] = None,
        body: str = "",
        status: str = "open",
        synced_refs: Optional[dict[str, str]] = None,
    ) -> Report:
        if not (title or "").strip():
            raise ValueError("title must not be empty")
        created_at = datetime.now(timezone.utc).isoformat()
        with self.transaction():
            cur = self._conn.execute(
                "INSERT INTO reports "
                "(created_at, title, body, notes, image_paths, tags, status, repo, synced_refs) "
                "VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?)",
                (
                    created_at,
                    title,
                    body,
                    notes,
                    json.dumps(normalize_tags(tags)),
                    status,
                    repo,
                    json.dumps(synced_refs or {}),
                ),
            )
            report_id = cur.lastrowid
            for path in image_paths or []:
                self.insert_media(report_id, kind="image", path=str(path), source="legacy")
        return self.get(report_id)

    def get(self, report_id: int) -> Optional[Report]:
        row = self._conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def list(self, repo: Optional[str] = None) -> list[Report]:
        if repo is None:
            rows = self._conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reports WHERE repo = ? ORDER BY id DESC", (repo,)
            ).fetchall()
        return [self._hydrate(row) for row in rows]

    def update(
        self,
        report_id: int,
        *,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None,
        body: Optional[str] = None,
    ) -> Optional[Report]:
        fields: dict[str, str] = {}
        if title is not None:
            if not title.strip():
                raise ValueError("title must not be empty")
            fields["title"] = title
        if notes is not None:
            fields["notes"] = notes
        if body is not None:
            fields["body"] = body
        if status is not None:
            if status not in STATUSES:
                raise ValueError(
                    f"invalid status {status!r}; choose one of: {', '.join(STATUSES)}"
                )
            fields["status"] = status
        if not fields:
            return self.get(report_id)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE reports SET {assignments} WHERE id = ?",
            (*fields.values(), report_id),
        )
        self._commit()
        return self.get(report_id)

    def set_tags(self, report_id: int, tags: list[str]) -> Optional[Report]:
        self._conn.execute(
            "UPDATE reports SET tags = ? WHERE id = ?",
            (json.dumps(normalize_tags(tags)), report_id),
        )
        self._commit()
        return self.get(report_id)

    def delete(self, report_id: int) -> None:
        """Remove a report with its media and frame rows (image files are the caller's job)."""
        with self.transaction():
            self._conn.execute(
                "DELETE FROM media_frames WHERE media_id IN (SELECT id FROM media WHERE report_id = ?)",
                (report_id,),
            )
            self._conn.execute("DELETE FROM media WHERE report_id = ?", (report_id,))
            self._conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    def add_image(self, report_id: int, path: str, source: Optional[str] = None) -> Optional[Report]:
        if self.get(report_id) is None:
            return None
        self.insert_media(report_id, kind="image", path=str(path), source=source)
        return self.get(report_id)

    def set_ref(self, report_id: int, key: str, value: str) -> Optional[Report]:
        report = self.get(report_id)
        if report is None:
            return None
        refs = dict(report.synced_refs)
        refs[key] = value
        self._conn.execute(
            "UPDATE reports SET synced_refs = ? WHERE id = ?",
            (json.dumps(refs), report_id),
        )
        self._commit()
        return self.get(report_id)

    def move_repo(self, old_key: str, new_key: str, old_tag: Optional[str], new_tag: Optional[str]) -> int:
        """Re-home every report stored under `old_key`: set its repo to `new_key` and, when the
        tag changed, swap `old_tag` for `new_tag` in its tags. Returns the number of reports."""
        with self.transaction():
            reports = self.list(repo=old_key)
            for report in reports:
                tags = list(report.tags)
                if old_tag and new_tag and old_tag != new_tag and old_tag in tags:
                    tags[tags.index(old_tag)] = new_tag
                self._conn.execute(
                    "UPDATE reports SET repo = ?, tags = ? WHERE id = ?",
                    (new_key, json.dumps(normalize_tags(tags)), report.id),
                )
        return len(reports)

    def find_by_ref(self, key: str, value: str) -> Optional[Report]:
        for report in self.list():
            if report.synced_refs.get(key) == value:
                return report
        return None

    # --- media -----------------------------------------------------------------

    def _load_media(self, row: sqlite3.Row) -> Media:
        media = Media.from_row(row)
        if media.kind == "frames":
            media.frames = [
                MediaFrame(r["media_id"], r["frame_no"], r["path"], r["size_bytes"])
                for r in self._conn.execute(
                    "SELECT * FROM media_frames WHERE media_id = ? ORDER BY frame_no", (media.id,)
                )
            ]
        return media

    def list_media(self, report_id: int) -> list[Media]:
        rows = self._conn.execute(
            "SELECT * FROM media WHERE report_id = ? ORDER BY idx", (report_id,)
        ).fetchall()
        return [self._load_media(r) for r in rows]

    def get_media(self, media_id: int) -> Optional[Media]:
        row = self._conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return self._load_media(row) if row else None

    def insert_media(
        self,
        report_id: int,
        *,
        kind: str = "image",
        path: Optional[str] = None,
        label: Optional[str] = None,
        mime: Optional[str] = None,
        size_bytes: Optional[int] = None,
        source: Optional[str] = None,
        frames: Optional[list[tuple[str, int]]] = None,
    ) -> Media:
        """Insert a media item at the next never-used index (computed inside the transaction)."""
        if kind not in MEDIA_KINDS:
            raise ValueError(f"invalid media kind {kind!r}")
        stored = to_data_relative(path) if path else None
        if size_bytes is None:
            try:
                size_bytes = Path(path).stat().st_size if path else 0
            except OSError:
                size_bytes = 0
        if mime is None:
            mime = guess_mime(path) if path else "image/png"
        created_at = datetime.now(timezone.utc).isoformat()
        with self.transaction():
            idx = self._next_index(report_id)
            cur = self._conn.execute(
                "INSERT INTO media (report_id, idx, label, kind, path, mime, size_bytes, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (report_id, idx, label, kind, stored, mime, size_bytes, source, created_at),
            )
            media_id = cur.lastrowid
            if frames:
                self.insert_frames(media_id, frames)
        return self.get_media(media_id)

    def _next_index(self, report_id: int) -> int:
        """Next index: above both the current maximum and the report's high-water mark, so an
        index is never reused, even after the item that had it was removed."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(idx), 0), (SELECT media_seq FROM reports WHERE id = ?) "
            "FROM media WHERE report_id = ?", (report_id, report_id),
        ).fetchone()
        idx = max(row[0], row[1] or 0) + 1
        self._conn.execute("UPDATE reports SET media_seq = ? WHERE id = ?", (idx, report_id))
        return idx

    def update_media_label(self, media_id: int, label: Optional[str]) -> None:
        self._conn.execute("UPDATE media SET label = ? WHERE id = ?", (label, media_id))
        self._commit()

    def delete_media(self, media_id: int) -> None:
        self._conn.execute("DELETE FROM media_frames WHERE media_id = ?", (media_id,))
        self._conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
        self._commit()

    def insert_frames(self, media_id: int, frames: list[tuple[str, int]]) -> None:
        """frames: [(path, size_bytes)] in order; frame_no is 1-based."""
        for number, (path, size) in enumerate(frames, start=1):
            self._conn.execute(
                "INSERT INTO media_frames (media_id, frame_no, path, size_bytes) VALUES (?, ?, ?, ?)",
                (media_id, number, to_data_relative(path), size),
            )
        self._commit()
