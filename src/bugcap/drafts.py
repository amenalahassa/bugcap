"""Live-mode drafts: an unsaved capture plus whatever was typed, kept on disk until it is
saved as a report or discarded. One `<uuid>.png` and one `<uuid>.json` per draft."""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import drafts_dir

FIELDS = ("title", "notes", "tags", "status")


@dataclass
class Draft:
    id: str
    png_path: Path
    created_at: str
    repo: Optional[str]
    title: str = ""
    notes: str = ""
    tags: list = None  # type: ignore[assignment]
    status: str = "open"

    def fields(self) -> dict:
        return {"title": self.title, "notes": self.notes, "tags": list(self.tags or []), "status": self.status}


def save_draft(repo: Optional[str], png_path, fields: dict) -> Draft:
    """Move the screenshot into drafts/ and write its sidecar."""
    draft_id = str(uuid.uuid4())
    directory = drafts_dir()
    target = directory / f"{draft_id}.png"
    shutil.move(str(png_path), target)
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "title": fields.get("title", ""),
        "notes": fields.get("notes", ""),
        "tags": list(fields.get("tags") or []),
        "status": fields.get("status", "open"),
    }
    (directory / f"{draft_id}.json").write_text(json.dumps(meta, indent=2))
    return Draft(draft_id, target, **meta)


def load_draft(draft_id: str) -> Optional[Draft]:
    directory = drafts_dir()
    sidecar = directory / f"{draft_id}.json"
    png = directory / f"{draft_id}.png"
    try:
        meta = json.loads(sidecar.read_text())
        if not png.is_file() or not isinstance(meta, dict):
            raise ValueError("incomplete draft")
        return Draft(
            draft_id, png, meta.get("created_at", ""), meta.get("repo"),
            str(meta.get("title", "")), str(meta.get("notes", "")),
            [str(t) for t in meta.get("tags", [])], str(meta.get("status", "open")),
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"warning: skipping unreadable draft {draft_id}: {exc}", file=sys.stderr)
        return None


def list_drafts(repo: Optional[str]) -> list[Draft]:
    """Drafts saved for this repo (or without a repo), oldest first."""
    found = []
    for sidecar in sorted(drafts_dir().glob("*.json")):
        draft = load_draft(sidecar.stem)
        if draft is not None and draft.repo == repo:
            found.append(draft)
    return sorted(found, key=lambda d: d.created_at)


def delete_draft(draft_id: str) -> None:
    directory = drafts_dir()
    for suffix in (".png", ".json"):
        (directory / f"{draft_id}{suffix}").unlink(missing_ok=True)
