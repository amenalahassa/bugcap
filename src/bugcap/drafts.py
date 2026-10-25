"""Live-mode drafts: unsaved staged media (any number of images / recordings, or none) plus
whatever was typed, kept on disk until it is saved as a report or discarded. One
`<uuid>.json` sidecar per draft; its media files sit beside it as `<uuid>-*`. A draft made by
an older version is just `<uuid>.png` + `<uuid>.json` and still loads.

Live mode also autosaves the bug being written as a *progress* draft (`write_progress`): the
same sidecar, rewritten atomically under a stable id, pointing at the media where it was
staged (absolute `"path"`) instead of moving it here."""
from __future__ import annotations

import json
import os
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
    launch_repo: Optional[str] = None  # where live mode ran when a progress draft was written

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


def _copy(source, target: Path) -> Path:
    shutil.copyfile(str(source), target)
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
        # a shared upload is stored once under its content hash and may belong to reports: copy it
        keep = _copy if item.get("shared") else _move
        new_path = keep(path, directory / f"{draft_id}-{n}{Path(path).suffix}") if path else None
        frames = []
        for m, (frame_path, size) in enumerate(item.get("frames") or [], start=1):
            frames.append([_move(frame_path, directory / f"{draft_id}-{n}-f{m:03d}.png").name, size])
        listed.append({
            "kind": item["kind"], "file": new_path.name if new_path else None,
            "mime": item.get("mime", "image/png"), "size_bytes": item.get("size_bytes", 0), "frames": frames,
            "number": item.get("number") or n, "source": item.get("source"), "shared": bool(item.get("shared")),
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


def write_progress(draft_id: Optional[str], repo: Optional[str], fields: dict, items: list,
                   launch_repo: Optional[str] = None) -> str:
    """Write (or rewrite) the progress draft `draft_id` (a new id when None) and return its id.
    The media stays where it is; the sidecar records absolute paths. Written to a temporary
    file and then renamed, so a crash leaves either the old sidecar or the new one."""
    draft_id = draft_id or str(uuid.uuid4())
    directory = drafts_dir()
    sidecar = directory / f"{draft_id}.json"
    now = datetime.now(timezone.utc).isoformat()
    try:
        created = json.loads(sidecar.read_text()).get("created_at") or now
    except (OSError, ValueError, AttributeError):
        created = now
    meta = {
        "version": 2,
        "created_at": created,
        "updated_at": now,
        "repo": repo,
        "launch_repo": launch_repo if launch_repo is not None else repo,
        "title": fields.get("title", ""),
        "notes": fields.get("notes", ""),
        "tags": list(fields.get("tags") or []),
        "status": fields.get("status") or "open",
        "media": [{
            "number": item.get("number"), "kind": item["kind"], "path": item.get("path"), "file": None,
            "mime": item.get("mime", "image/png"), "size_bytes": item.get("size_bytes", 0),
            "frames": [[str(p), size] for p, size in item.get("frames") or []],
            "source": item.get("source"), "shared": bool(item.get("shared")),
        } for item in items],
    }
    temp = directory / f"{draft_id}.json.tmp"
    temp.write_text(json.dumps(meta, indent=2))
    try:
        os.replace(temp, sidecar)
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    return draft_id


def _items_from_meta(directory: Path, draft_id: str, meta: dict) -> list:
    if "media" not in meta:  # legacy: one screenshot
        png = directory / f"{draft_id}.png"
        if not png.is_file():
            raise ValueError("incomplete draft")
        return [{"kind": "image", "path": str(png), "mime": "image/png", "size_bytes": png.stat().st_size, "frames": []}]
    items = []
    for position, entry in enumerate(meta["media"], start=1):
        # `path` (absolute, media left in place) for a progress draft, `file` (in drafts/) otherwise
        path = Path(entry["path"]) if entry.get("path") else directory / entry["file"] if entry.get("file") else None
        frames = [(str(directory / name), int(size)) for name, size in entry.get("frames", [])]
        files = ([path] if path else []) + [Path(p) for p, _ in frames]
        if not files or not all(f.is_file() for f in files):
            raise ValueError("incomplete draft")
        items.append({
            "kind": str(entry["kind"]), "path": str(path) if path else None, "mime": str(entry.get("mime", "")),
            "size_bytes": int(entry.get("size_bytes", 0)), "frames": frames,
            "number": int(entry.get("number") or position), "source": entry.get("source"),
            "shared": bool(entry.get("shared", False)),
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
            meta.get("launch_repo", meta.get("repo")),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"warning: skipping unreadable draft {draft_id}: {exc}", file=sys.stderr)
        return None


def list_drafts(repo: Optional[str]) -> list[Draft]:
    """Drafts saved for this repo (or without a repo), oldest first. A bug in progress is
    listed both for the repo picked in its form and for the repo live mode ran in."""
    found = []
    for sidecar in sorted(drafts_dir().glob("*.json")):
        draft = load_draft(sidecar.stem)
        if draft is not None and repo in (draft.repo, draft.launch_repo):
            found.append(draft)
    return sorted(found, key=lambda d: d.created_at)


def delete_draft(draft_id: str) -> None:
    directory = drafts_dir()
    (directory / f"{draft_id}.json").unlink(missing_ok=True)
    (directory / f"{draft_id}.png").unlink(missing_ok=True)
    for leftover in directory.glob(f"{draft_id}-*"):
        leftover.unlink(missing_ok=True)
