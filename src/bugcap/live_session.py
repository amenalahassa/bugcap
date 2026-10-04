"""The logic of `bugcap live`, without any GUI: a small state machine plus the save step.
`live.py` is a thin Tk shell over this, so everything here is testable without a display."""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import service
from .store import Report, Store


class LiveState(Enum):
    READY = "ready"
    CAPTURING = "capturing"
    DETAILS = "details"


def initial_tags(repo_cfg, prefill: Optional[dict] = None) -> list:
    """Tags shown when the details window opens: a restored draft's own tags, otherwise
    the launch repo's tag."""
    if prefill and prefill.get("tags") is not None:
        return list(prefill["tags"])
    return [repo_cfg.tag] if repo_cfg is not None else []


class LiveSession:
    def __init__(self, repo_cfg=None, store_factory: Callable[[], Store] = Store):
        self.repo_cfg = repo_cfg
        self.store_factory = store_factory
        self.state = LiveState.READY
        self.saved_count = 0
        self.screenshot: Optional[Path] = None
        self.draft_id: Optional[str] = None
        self.message = ""

    # --- transitions -----------------------------------------------------------

    def start(self) -> bool:
        """Begin a capture. Ignored (False) unless READY, so a double click cannot start twice."""
        if self.state is not LiveState.READY:
            return False
        self.state = LiveState.CAPTURING
        self.message = ""
        return True

    def capture_done(self, path, message: Optional[str] = None) -> None:
        if self.state is not LiveState.CAPTURING:
            return
        if path is None or not Path(path).is_file():
            self.state = LiveState.READY
            self.message = message or "Nothing was captured."
            self.screenshot = None
            return
        self.screenshot = Path(path)
        self.draft_id = None
        self.state = LiveState.DETAILS

    def restore(self, path, draft_id: str) -> None:
        """Open the details step for a recovered draft."""
        if self.state is LiveState.READY:
            self.screenshot = Path(path)
            self.draft_id = draft_id
            self.state = LiveState.DETAILS

    def save(self, fields: dict) -> Report:
        """Save the report (screenshot is image 1). Raises ServiceError (empty title, bad
        `@` reference, ...); the state stays DETAILS so the user can fix it."""
        if self.state is not LiveState.DETAILS or self.screenshot is None:
            raise RuntimeError("nothing to save")
        tags = list(fields.get("tags") or [])
        repo_key = None
        if self.repo_cfg is not None:
            repo_key = self.repo_cfg.key
            if self.repo_cfg.tag not in tags:
                tags.append(self.repo_cfg.tag)
        with self.store_factory() as store:
            report, _ = service.create_report(
                store,
                title=(fields.get("title") or "").strip(),
                notes=fields.get("notes") or "",
                tags=tags,
                repo=repo_key,
                status=fields.get("status") or "open",
                sources=[str(self.screenshot)],
            )
        self._drop_screenshot()
        self.saved_count += 1
        self.state = LiveState.READY
        self.message = f"Saved report #{report.id}"
        return report

    def discard(self, confirmed: bool) -> bool:
        if self.state is not LiveState.DETAILS or not confirmed:
            return False
        self._drop_screenshot()
        self.state = LiveState.READY
        self.message = "Discarded."
        return True

    def request_close(self, has_unsaved: bool) -> str:
        """'close' when nothing would be lost, otherwise 'needs_confirm'."""
        if self.state is LiveState.DETAILS and has_unsaved:
            return "needs_confirm"
        return "close"

    def confirm_close(self, confirmed: bool) -> str:
        """After 'needs_confirm': 'save_draft' keeps the work, 'stay' keeps the window open."""
        return "save_draft" if confirmed else "stay"

    # --- helpers ---------------------------------------------------------------

    def _drop_screenshot(self) -> None:
        from . import drafts

        if self.screenshot is not None:
            try:
                os.unlink(self.screenshot)
            except OSError:
                pass
        if self.draft_id:
            drafts.delete_draft(self.draft_id)
        self.screenshot = None
        self.draft_id = None
