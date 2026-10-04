"""`bugcap live`: a small always-on-top control window for reporting many bugs in a row.

Thin Tk shell over `live_session.LiveSession`: Start runs the existing capture backend (the
control window hides itself so it is not in the screenshot), a details window collects the
title/notes/tags/status, and Save returns to the ready state."""
from __future__ import annotations

import os
import queue
import sys
import threading
from pathlib import Path

from . import capture, drafts, refs, repo
from .errors import ServiceError
from .live_session import LiveSession, LiveState, initial_tags
from .store import STATUSES

TK_HINT = (
    "Live mode needs tkinter. On Linux install your distro's python3-tk package "
    "(e.g. sudo apt install python3-tk)."
)
NO_DESKTOP = "Live mode needs a desktop session (no DISPLAY or WAYLAND_DISPLAY is set)."
THUMB = 420


def check_environment() -> tuple[int, str]:
    """(0, "") when a window can be opened, else (3, explanation)."""
    if sys.platform not in ("win32", "darwin") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return 3, NO_DESKTOP
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return 3, TK_HINT
    return 0, ""


def run(repo_dir=None) -> int:
    code, message = check_environment()
    if code:
        print(f"error: {message}", file=sys.stderr)
        return code
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"error: cannot open a window ({exc}). {NO_DESKTOP}", file=sys.stderr)
        return 3

    cfg = repo.load_repo_config(Path(repo_dir)) if repo_dir else repo.load_repo_config()
    app = _App(root, LiveSession(cfg), cfg)
    app.start_ui()
    root.mainloop()
    return 0


class _App:
    def __init__(self, root, session: LiveSession, cfg):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root, self.session, self.cfg = root, session, cfg
        self.results: "queue.Queue" = queue.Queue()
        self.details = None
        self.widgets: dict = {}
        self.pending_drafts: list = []

    # --- control window --------------------------------------------------------

    def start_ui(self) -> None:
        tk, ttk, root = self.tk, self.ttk, self.root
        root.title("bugcap live")
        root.resizable(False, False)
        notice = ""
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            notice = "Always-on-top is not supported here; the window may be hidden by others."
        frame = ttk.Frame(root, padding=12)
        frame.grid()
        self.start_button = ttk.Button(frame, text="Start", command=self.on_start)
        self.start_button.grid(row=0, column=0, sticky="ew")
        self.counter = ttk.Label(frame, text="0 saved this session")
        self.counter.grid(row=1, column=0, pady=(8, 0))
        self.status = ttk.Label(frame, text=notice, wraplength=240, foreground="#a15c00")
        self.status.grid(row=2, column=0, pady=(4, 0))
        root.protocol("WM_DELETE_WINDOW", self.on_close_control)
        self.pending_drafts = drafts.list_drafts(self.cfg.key if self.cfg else None)
        root.after(200, self.offer_drafts)

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def refresh_counter(self) -> None:
        self.counter.configure(text=f"{self.session.saved_count} saved this session")
        self.start_button.state(["!disabled"] if self.session.state is LiveState.READY else ["disabled"])

    def on_start(self) -> None:
        if not self.session.start():
            return
        self.refresh_counter()
        self.set_status("Capturing...")
        self.root.withdraw()
        self.root.after(350, self._launch_capture)

    def _launch_capture(self) -> None:
        def worker():
            try:
                self.results.put((str(capture.capture_screenshot()), None))
            except capture.CaptureError as exc:
                self.results.put((None, str(exc)))
            except Exception as exc:  # never lose the window to a backend crash
                self.results.put((None, f"capture failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll)

    def _poll(self) -> None:
        try:
            path, message = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        self.root.deiconify()
        self.session.capture_done(path, message)
        self.refresh_counter()
        if self.session.state is LiveState.DETAILS:
            self.set_status("")
            self.open_details()
        else:
            self.set_status(self.session.message)

    # --- drafts ----------------------------------------------------------------

    def offer_drafts(self) -> None:
        from tkinter import messagebox

        while self.pending_drafts and self.session.state is LiveState.READY:
            draft = self.pending_drafts.pop(0)
            title = draft.title or "(untitled)"
            answer = messagebox.askyesnocancel(
                "Unsaved draft", f"Restore the unsaved draft {title!r}?\n\nYes: restore   No: discard   Cancel: keep for later",
                parent=self.root,
            )
            if answer is None:
                continue
            if answer:
                self.session.restore(draft.png_path, draft.id)
                self.refresh_counter()
                self.open_details(draft.fields())
                return
            drafts.delete_draft(draft.id)

    # --- details window --------------------------------------------------------

    def open_details(self, prefill: dict | None = None) -> None:
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.root)
        self.details = win
        win.title("New bug report")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=12)
        frame.grid()
        w = self.widgets = {}

        try:
            image = tk.PhotoImage(file=str(self.session.screenshot))
            factor = max(1, -(-max(image.width(), image.height()) // THUMB))
            w["photo"] = image.subsample(factor, factor) if factor > 1 else image
            ttk.Label(frame, image=w["photo"]).grid(row=0, column=0, columnspan=2, pady=(0, 8))
        except tk.TclError:
            ttk.Label(frame, text="(preview unavailable)").grid(row=0, column=0, columnspan=2)

        prefill = prefill or {}
        ttk.Label(frame, text="Title").grid(row=1, column=0, sticky="w")
        w["title"] = ttk.Entry(frame, width=48)
        w["title"].grid(row=1, column=1, sticky="ew")
        w["title"].insert(0, prefill.get("title", ""))
        ttk.Label(frame, text="Notes").grid(row=2, column=0, sticky="nw")
        w["notes"] = tk.Text(frame, width=48, height=6, wrap="word")
        w["notes"].grid(row=2, column=1, sticky="ew")
        w["notes"].insert("1.0", prefill.get("notes", ""))
        w["notes"].bind("<KeyRelease>", lambda e: self.check_notes())
        ttk.Label(frame, text="Tags").grid(row=3, column=0, sticky="w")
        w["tags"] = ttk.Entry(frame, width=48)
        w["tags"].grid(row=3, column=1, sticky="ew")
        w["tags"].insert(0, ", ".join(initial_tags(self.cfg, prefill)))
        ttk.Label(frame, text="Status").grid(row=4, column=0, sticky="w")
        w["status"] = ttk.Combobox(frame, values=list(STATUSES), state="readonly", width=16)
        w["status"].set(prefill.get("status", "open"))
        w["status"].grid(row=4, column=1, sticky="w")
        ttk.Label(frame, text="Repo").grid(row=5, column=0, sticky="w")
        ttk.Label(frame, text=(self.cfg.key if self.cfg else "(none)")).grid(row=5, column=1, sticky="w")
        w["error"] = ttk.Label(frame, text="", foreground="#b00020", wraplength=420)
        w["error"].grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Discard", command=self.on_discard).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Save", command=self.on_save).grid(row=0, column=1)
        win.protocol("WM_DELETE_WINDOW", self.on_close_details)
        w["title"].focus_set()
        self.check_notes()

    def fields(self) -> dict:
        w = self.widgets
        return {
            "title": w["title"].get().strip(),
            "notes": w["notes"].get("1.0", "end-1c"),
            "tags": [t.strip() for t in w["tags"].get().split(",") if t.strip()],
            "status": w["status"].get() or "open",
        }

    def check_notes(self) -> bool:
        """Show an inline message for an unknown `@` reference (image 1 is the screenshot)."""
        from .store import Media

        notes = self.widgets["notes"].get("1.0", "end-1c")
        shot = [Media(0, 0, 1, None, "image", None, "image/png", 0, None, "")]
        try:
            refs.validate_references(notes, shot)
        except ServiceError as exc:
            self.widgets["error"].configure(
                text=f"{exc.message} (valid: {', '.join(exc.details.get('valid', []))})"
            )
            return False
        self.widgets["error"].configure(text="")
        return True

    def close_details(self) -> None:
        if self.details is not None:
            self.details.destroy()
        self.details = None
        self.widgets = {}
        self.refresh_counter()

    def on_save(self) -> None:
        try:
            report = self.session.save(self.fields())
        except ServiceError as exc:
            self.widgets["error"].configure(text=exc.message)
            return
        self.close_details()
        self.set_status(f"Saved report #{report.id}")
        self.offer_drafts()

    def on_discard(self) -> None:
        from tkinter import messagebox

        ok = messagebox.askyesno("Discard", "Discard this capture and everything typed?", parent=self.details)
        if self.session.discard(ok):
            self.close_details()
            self.set_status("Discarded.")
            self.offer_drafts()

    def _keep_as_draft(self) -> None:
        if self.session.screenshot is None:
            return
        if self.session.draft_id:
            drafts.delete_draft(self.session.draft_id)
        drafts.save_draft(self.cfg.key if self.cfg else None, self.session.screenshot, self.fields())
        self.session.screenshot = None
        self.session.draft_id = None
        self.session.state = LiveState.READY

    def on_close_details(self) -> None:
        from tkinter import messagebox

        if self.session.request_close(True) == "needs_confirm":
            ok = messagebox.askyesno("Close", "Save this report as a draft?", parent=self.details)
            if self.session.confirm_close(ok) == "save_draft":
                self._keep_as_draft()
                self.close_details()
                self.set_status("Draft saved.")

    def on_close_control(self) -> None:
        from tkinter import messagebox

        if self.session.state is LiveState.DETAILS and self.details is not None:
            decision = self.session.request_close(True)
            if decision == "needs_confirm":
                ok = messagebox.askyesno("Quit", "Save the open report as a draft and quit?", parent=self.details)
                if self.session.confirm_close(ok) != "save_draft":
                    return
                self._keep_as_draft()
        self.root.destroy()
