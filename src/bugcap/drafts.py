"""Live-mode drafts: unsaved staged media (any number of images / recordings, or none) plus
whatever was typed, kept on disk until it is saved as a report or discarded. One
`<uuid>.json` sidecar per draft; its media files sit beside it as `<uuid>-*`. A draft made by
an older version is just `<uuid>.png` + `<uuid>.json` and still loads."""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import drafts_dir

FIELDS = ("title", "notes", "tags", "status")


@dataclass
class Draft:
    id: str
    created_at: str
    repo: Optional[str]
    title: str = ""
    notes: str = ""
    tags: list = None  # type: ignore[assignment]
    status: str = "open"
    # [{"kind", "path" (absolute or None), "mime", "size_bytes", "frames": [(path, size)]}]
    items: list = field(default_factory=list)

    def fields(self) -> dict:
        return {"title": self.title, "notes": self.notes, "tags": list(self.tags or []), "status": self.status}

    @property
    def png_path(self) -> Optional[Path]:
        """The first stored file (the screenshot of a single-image draft), if any."""
        for item in self.items:
            if item["path"]:
                return Path(item["path"])
        return None


def _move(source, target: Path) -> Path:
    shutil.move(str(source), target)
    return target


def save_draft(repo: Optional[str], png_path, fields: dict, items: Optional[list] = None) -> Draft:
    """Move the media into drafts/ and write the sidecar. `items` are dicts shaped like
    `Draft.items`; for a plain screenshot pass `png_path` instead."""
    if items is None:
        items = [{"kind": "image", "path": str(png_path), "mime": "image/png", "size_bytes": 0, "frames": []}] if png_path else []
    draft_id = str(uuid.uuid4())
    directory = drafts_dir()
    listed = []
    for n, item in enumerate(items, start=1):
        path = item.get("path")
        new_path = _move(path, directory / f"{draft_id}-{n}{Path(path).suffix}") if path else None
        frames = []
        for m, (frame_path, size) in enumerate(item.get("frames") or [], start=1):
            frames.append([_move(frame_path, directory / f"{draft_id}-{n}-f{m:03d}.png").name, size])
        listed.append({
            "kind": item["kind"], "file": new_path.name if new_path else None,
            "mime": item.get("mime", "image/png"), "size_bytes": item.get("size_bytes", 0), "frames": frames,
        })
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "title": fields.get("title", ""),
        "notes": fields.get("notes", ""),
        "tags": list(fields.get("tags") or []),
        "status": fields.get("status", "open"),
        "media": listed,
    }
    (directory / f"{draft_id}.json").write_text(json.dumps(meta, indent=2))
    return load_draft(draft_id)  # type: ignore[return-value]


def _items_from_meta(directory: Path, draft_id: str, meta: dict) -> list:
    if "media" not in meta:  # legacy: one screenshot
        png = directory / f"{draft_id}.png"
        if not png.is_file():
            raise ValueError("incomplete draft")
        return [{"kind": "image", "path": str(png), "mime": "image/png", "size_bytes": png.stat().st_size, "frames": []}]
    items = []
    for entry in meta["media"]:
        path = directory / entry["file"] if entry.get("file") else None
        frames = [(str(directory / name), int(size)) for name, size in entry.get("frames", [])]
        files = ([path] if path else []) + [Path(p) for p, _ in frames]
        if not files or not all(f.is_file() for f in files):
            raise ValueError("incomplete draft")
        items.append({
            "kind": str(entry["kind"]), "path": str(path) if path else None, "mime": str(entry.get("mime", "")),
            "size_bytes": int(entry.get("size_bytes", 0)), "frames": frames,
        })
    return items


def load_draft(draft_id: str) -> Optional[Draft]:
    directory = drafts_dir()
    sidecar = directory / f"{draft_id}.json"
    try:
        meta = json.loads(sidecar.read_text())
        if not isinstance(meta, dict):
            raise ValueError("incomplete draft")
        return Draft(
            draft_id, meta.get("created_at", ""), meta.get("repo"),
            str(meta.get("title", "")), str(meta.get("notes", "")),
            [str(t) for t in meta.get("tags", [])], str(meta.get("status", "open")),
            _items_from_meta(directory, draft_id, meta),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
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
    (directory / f"{draft_id}.json").unlink(missing_ok=True)
    (directory / f"{draft_id}.png").unlink(missing_ok=True)
    for leftover in directory.glob(f"{draft_id}-*"):
        leftover.unlink(missing_ok=True)
