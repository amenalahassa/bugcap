import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
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


@dataclass
class Report:
    id: Optional[int]
    created_at: str
    title: str
    notes: str = ""
    image_paths: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = "open"
    synced_refs: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Report":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            title=row["title"],
            notes=row["notes"],
            image_paths=json.loads(row["image_paths"]),
            tags=json.loads(row["tags"]),
            status=row["status"],
            synced_refs=json.loads(row["synced_refs"]),
        )


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or db_path()
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(SCHEMA)
        self._conn.commit()

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
    ) -> Report:
        report = Report(
            id=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            title=title,
            notes=notes,
            image_paths=image_paths or [],
            tags=tags or [],
        )
        cur = self._conn.execute(
            "INSERT INTO reports (created_at, title, notes, image_paths, tags, status, synced_refs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.created_at,
                report.title,
                report.notes,
                json.dumps(report.image_paths),
                json.dumps(report.tags),
                report.status,
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

    def list(self) -> list[Report]:
        rows = self._conn.execute(
            "SELECT * FROM reports ORDER BY id DESC"
        ).fetchall()
        return [Report.from_row(row) for row in rows]
