from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import db_path

SCHEMA_VERSION = 1

# Schema at version 1 (fresh databases are created directly in this shape;
# older databases are brought here by _migrate()).
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

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Report":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            title=row["title"],
            body=row["body"] if "body" in row.keys() else "",
            notes=row["notes"],
            image_paths=json.loads(row["image_paths"]),
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
        self._conn.execute(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """PRAGMA user_version-based migration to SCHEMA_VERSION, idempotent and row-preserving."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(reports)")}
        try:
            self._conn.execute("BEGIN")
            if "repo" not in columns:
                self._conn.execute("ALTER TABLE reports ADD COLUMN repo TEXT")
            if "body" not in columns:
                self._conn.execute("ALTER TABLE reports ADD COLUMN body TEXT NOT NULL DEFAULT ''")
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

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
        report = Report(
            id=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            title=title,
            body=body,
            notes=notes,
            image_paths=image_paths or [],
            tags=normalize_tags(tags),
            status=status,
            repo=repo,
            synced_refs=synced_refs or {},
        )
        cur = self._conn.execute(
            "INSERT INTO reports "
            "(created_at, title, body, notes, image_paths, tags, status, repo, synced_refs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.created_at,
                report.title,
                report.body,
                report.notes,
                json.dumps(report.image_paths),
                json.dumps(report.tags),
                report.status,
                report.repo,
                json.dumps(report.synced_refs),
            ),
        )
        self._conn.commit()
        report.id = cur.lastrowid
        return report

    def get(self, report_id: int) -> Optional[Report]:
        row = self._conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return Report.from_row(row) if row else None

    def list(self, repo: Optional[str] = None) -> list[Report]:
        if repo is None:
            rows = self._conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reports WHERE repo = ? ORDER BY id DESC", (repo,)
            ).fetchall()
        return [Report.from_row(row) for row in rows]

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
        self._conn.commit()
        return self.get(report_id)

    def set_tags(self, report_id: int, tags: list[str]) -> Optional[Report]:
        self._conn.execute(
            "UPDATE reports SET tags = ? WHERE id = ?",
            (json.dumps(normalize_tags(tags)), report_id),
        )
        self._conn.commit()
        return self.get(report_id)

    def add_image(self, report_id: int, path: str) -> Optional[Report]:
        report = self.get(report_id)
        if report is None:
            return None
        images = [*report.image_paths, str(path)]
        self._conn.execute(
            "UPDATE reports SET image_paths = ? WHERE id = ?",
            (json.dumps(images), report_id),
        )
        self._conn.commit()
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
        self._conn.commit()
        return self.get(report_id)

    def find_by_ref(self, key: str, value: str) -> Optional[Report]:
        for report in self.list():
            if report.synced_refs.get(key) == value:
                return report
        return None
