"""The logic of `bugcap live`, without any GUI: a small state machine plus the save step.
`live.py` is a thin Tk shell over this, so everything here is testable without a display.

The user *stages* media (screenshots and screen recordings, any number, any mix) and then
either makes a new report from them, adds them to an existing report, or skips media
altogether and files a note-only bug."""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import drafts, refs, service
from .errors import ServiceError
from .paths import drafts_dir, images_dir, media_dir
from .store import Media, Report, Store


class LiveState(Enum):
    READY = "ready"
    CAPTURING = "capturing"
    RECORDING = "recording"
    DETAILS = "details"


@dataclass
class Staged:
    """One captured/recorded item waiting to be attached to a report."""
    kind: str  # image | video | animated | frames
    path: Optional[Path]
    mime: str = "image/png"
    size_bytes: int = 0
    frames: list = field(default_factory=list)  # [(path, size)] for kind "frames"

    def files(self) -> list[Path]:
        return ([self.path] if self.path else []) + [Path(p) for p, _ in self.frames]

    def to_item(self) -> dict:
        return {"kind": self.kind, "path": str(self.path) if self.path else None, "mime": self.mime,
                "size_bytes": self.size_bytes, "frames": [(str(p), s) for p, s in self.frames]}

    @classmethod
    def from_item(cls, item: dict) -> "Staged":
        return cls(item["kind"], Path(item["path"]) if item["path"] else None, item.get("mime", "image/png"),
                   item.get("size_bytes", 0), [(Path(p), s) for p, s in item.get("frames", [])])

    def delete(self) -> None:
        for f in self.files():
            try:
                os.unlink(f)
            except OSError:
                pass
        if self.frames:
            try:
                Path(self.frames[0][0]).parent.rmdir()
            except OSError:
                pass


def initial_tags(repo_cfg, prefill: Optional[dict] = None) -> list:
    """Tags shown when the details window opens: a restored draft's own tags, otherwise
    the launch repo's tag."""
    if prefill and prefill.get("tags") is not None:
        return list(prefill["tags"])
    return [repo_cfg.tag] if repo_cfg is not None else []


def describe(staged: list) -> str:
    """'2 images, 1 video' for the control window."""
    names = {"image": "image", "video": "video", "animated": "GIF", "frames": "frame set"}
    counts: dict = {}
    for s in staged:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    return ", ".join(f"{n} {names[k]}{'' if n == 1 else 's'}" for k, n in counts.items())


class LiveSession:
    def __init__(self, repo_cfg=None, store_factory: Callable[[], Store] = Store):
        self.repo_cfg = repo_cfg
        self.store_factory = store_factory
        self.state = LiveState.READY
        self.saved_count = 0
        self.staged: list[Staged] = []
        self.draft_id: Optional[str] = None
        self.message = ""

    # --- capturing -------------------------------------------------------------

    def start(self, kind: str = "image") -> bool:
        """Begin a screenshot (or, with kind="video", a recording). Ignored (False) unless
        READY, so a double click cannot start twice."""
        if self.state is not LiveState.READY:
            return False
        self.state = LiveState.RECORDING if kind == "video" else LiveState.CAPTURING
        self.message = ""
        return True

    def capture_done(self, path, message: Optional[str] = None) -> None:
        """A screenshot finished; stage it (or report why there is none)."""
        if self.state is not LiveState.CAPTURING:
            return
        self.state = LiveState.READY
        if path is None or not Path(path).is_file():
            self.message = message or "Nothing was captured."
            return
        self.staged.append(Staged("image", Path(path), "image/png", Path(path).stat().st_size))
        self.message = ""

    def recording_done(self, result, message: Optional[str] = None) -> None:
        """A recording finished; `result` is a `recorder.RecordResult` (or None on failure)."""
        if self.state is not LiveState.RECORDING:
            return
        self.state = LiveState.READY
        if result is None:
            self.message = message or "Nothing was recorded."
            return
        self.staged.append(Staged(result.kind, Path(result.path) if result.path else None, result.mime,
                                  result.size_bytes, [(Path(p), s) for p, s in result.frames]))
        self.message = ""

    def remove_staged(self, index: int) -> None:
        if self.state is LiveState.READY and 0 <= index < len(self.staged):
            self.staged.pop(index).delete()

    def clear_staged(self) -> None:
        for s in self.staged:
            s.delete()
        self.staged = []

    # --- drafts ----------------------------------------------------------------

    def restore(self, draft: "drafts.Draft") -> None:
        """Open the details step for a recovered draft (its media become the staged set)."""
        if self.state is LiveState.READY and not self.staged:
            self.staged = [Staged.from_item(i) for i in draft.items]
            self.draft_id = draft.id
            self.state = LiveState.DETAILS

    def keep_as_draft(self, fields: Optional[dict] = None) -> bool:
        """Save the staged media and typed fields as a draft and reset. False if empty."""
        fields = fields or {}
        typed = any(fields.get(k) for k in ("title", "notes"))
        if not self.staged and not typed:
            self._reset()
            return False
        if self.draft_id:
            drafts.delete_draft(self.draft_id)
        key = self.repo_cfg.key if self.repo_cfg else None
        drafts.save_draft(key, None, fields, items=[s.to_item() for s in self.staged])
        self.staged, self.draft_id = [], None
        self._reset()
        return True

    # --- the details step ------------------------------------------------------

    def begin_details(self) -> bool:
        """Open the new-report form for the staged media; with nothing staged it is a
        note-only bug."""
        if self.state is not LiveState.READY:
            return False
        self.state = LiveState.DETAILS
        return True

    def cancel_details(self) -> None:
        """Back to READY, keeping the staged media."""
        if self.state is LiveState.DETAILS:
            self.state = LiveState.READY

    def preview_media(self) -> list[Media]:
        """Stand-ins for the staged media (numbered as they will be) to validate `@` references."""
        return [Media(0, 0, n, None, s.kind, None, s.mime, s.size_bytes, None, "")
                for n, s in enumerate(self.staged, start=1)]

    def save(self, fields: dict) -> Report:
        """Save a new report with the staged media (none for a note-only bug). Raises
        ServiceError (empty title, bad `@` reference, ...); the state stays DETAILS so the
        user can fix it."""
        if self.state is not LiveState.DETAILS:
            raise RuntimeError("nothing to save")
        title = (fields.get("title") or "").strip()
        notes = fields.get("notes") or ""
        if not title:
            raise ServiceError("invalid_title", "title must not be empty")
        refs.validate_references(notes, self.preview_media())
        tags = list(fields.get("tags") or [])
        repo_key = None
        if self.repo_cfg is not None:
            repo_key = self.repo_cfg.key
            if self.repo_cfg.tag not in tags:
                tags.append(self.repo_cfg.tag)
        with self.store_factory() as store:
            report, _ = service.create_report(
                store, title=title, tags=tags, repo=repo_key, status=fields.get("status") or "open",
            )
            try:
                self._attach_all(store, report.id)
                if notes:
                    service.set_notes(store, report.id, notes)
            except BaseException:
                service.delete_report(store, report.id)
                raise
            report = store.get(report.id)
        self._finish(f"Saved report #{report.id}")
        return report

    def attach(self, report_id: int, note: str = "") -> Report:
        """Add the staged media (and an optional note) to an existing report. Allowed from
        READY; raises ServiceError for an unknown report, a bad `@` reference, or nothing to add."""
        if self.state is not LiveState.READY:
            raise RuntimeError("finish the open report first")
        note = (note or "").strip()
        if not self.staged and not note:
            raise ServiceError("invalid_note", "nothing to add: capture something or write a note")
        with self.store_factory() as store:
            existing = service._require(store, report_id).media
            top = max([m.idx for m in existing], default=0)
            ahead = [Media(0, 0, top + n, None, s.kind, None, s.mime, 0, None, "")
                     for n, s in enumerate(self.staged, start=1)]
            refs.validate_references(note, existing + ahead)
            added = self._attach_all(store, report_id)
            report = service.append_note(store, report_id, note, added) if note else store.get(report_id)
        self._finish(f"Added to report #{report_id}")
        return report

    def discard(self, confirmed: bool) -> bool:
        """Throw away the staged media and everything typed."""
        if self.state is not LiveState.DETAILS or not confirmed:
            return False
        self.clear_staged()
        if self.draft_id:
            drafts.delete_draft(self.draft_id)
            self.draft_id = None
        self.state = LiveState.READY
        self.message = "Discarded."
        return True

    def request_close(self, has_unsaved: bool) -> str:
        """'close' when nothing would be lost, otherwise 'needs_confirm'."""
        if self.state is LiveState.DETAILS and has_unsaved:
            return "needs_confirm"
        if self.staged:
            return "needs_confirm"
        return "close"

    def confirm_close(self, confirmed: bool) -> str:
        """After 'needs_confirm': 'save_draft' keeps the work, 'stay' keeps the window open."""
        return "save_draft" if confirmed else "stay"

    # --- helpers ---------------------------------------------------------------

    def _reset(self) -> None:
        self.state = LiveState.READY

    def _finish(self, message: str) -> None:
        if self.draft_id:
            drafts.delete_draft(self.draft_id)
        self.staged, self.draft_id = [], None
        self.saved_count += 1
        self.state = LiveState.READY
        self.message = message

    def _attach_all(self, store: Store, report_id: int) -> list[Media]:
        """Attach every staged item in order; each is moved into the store first if it
        still sits in drafts/."""
        added = []
        for s in self.staged:
            s = _into_store(s)
            if s.kind == "image":
                added.append(service.attach_captured(store, report_id, str(s.path)))
            else:
                _, media = service.add_recording(
                    store, report_id, str(s.path) if s.path else None, s.kind, s.mime, s.size_bytes,
                    frame_paths=[(str(p), size) for p, size in s.frames] or None,
                )
                added.append(media)
        return added


def _into_store(s: Staged) -> Staged:
    """Move a staged item restored from a draft out of drafts/ so deleting the draft cannot
    take its files along. Items captured this session are already in the store."""
    root = drafts_dir()
    if not any(f.parent == root for f in s.files()):
        return s
    base = images_dir() if s.kind == "image" else media_dir()
    stem = uuid.uuid4().hex
    path = None
    if s.path:
        path = Path(shutil.move(str(s.path), base / f"{stem}{s.path.suffix}"))
    frames = []
    if s.frames:
        folder = base / f"{stem}-frames"
        folder.mkdir(parents=True, exist_ok=True)
        for n, (p, size) in enumerate(s.frames, start=1):
            frames.append((Path(shutil.move(str(p), folder / f"frame-{n:03d}.png")), size))
    return Staged(s.kind, path, s.mime, s.size_bytes, frames)
