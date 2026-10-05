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
# Light palette; the control and details windows share it (see `_App.style`).
BG, CARD, TEXT, MUTED = "#f4f5f7", "#ffffff", "#111827", "#6b7280"
ACCENT, ACCENT_ACTIVE, BORDER = "#2563eb", "#1d4ed8", "#d1d5db"
DANGER, WARNING = "#b91c1c", "#b45309"


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

    # --- styling ---------------------------------------------------------------

    def style(self) -> None:
        """One consistent look for every window: a flat light theme with an accent button."""
        tk, ttk = self.tk, self.ttk
        import tkinter.font as tkfont

        base = tkfont.nametofont("TkDefaultFont")
        self.body_font = base
        self.title_font = base.copy()
        self.title_font.configure(size=base.cget("size") + 4, weight="bold")
        self.heading_font = base.copy()
        self.heading_font.configure(weight="bold")
        self.root.configure(background=BG)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=base)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, bordercolor=BORDER, relief="solid", borderwidth=1)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD)
        style.configure("Title.TLabel", font=self.title_font)
        style.configure("Heading.TLabel", font=self.heading_font)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("Error.TLabel", foreground=DANGER)
        style.configure("Warning.TLabel", foreground=WARNING)
        style.configure("TButton", padding=(14, 6), background=CARD, bordercolor=BORDER, lightcolor=CARD,
                        darkcolor=CARD, focuscolor=CARD)
        style.map("TButton", background=[("active", BG), ("disabled", BG)], foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", padding=(18, 8), background=ACCENT, foreground="#ffffff",
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ACCENT)
        style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE), ("disabled", BORDER)],
                  foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=CARD, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, padding=4)
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        style.configure("TCombobox", fieldbackground=CARD, bordercolor=BORDER, padding=3)

    # --- control window --------------------------------------------------------

    def start_ui(self) -> None:
        tk, ttk, root = self.tk, self.ttk, self.root
        root.title("bugcap live")
        root.resizable(False, False)
        self.style()
        notice = ""
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            notice = "Always-on-top is not supported here; the window may be hidden by others."
        frame = ttk.Frame(root, padding=16)
        frame.grid()
        ttk.Label(frame, text="bugcap live", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.start_button = ttk.Button(frame, text="Start capture", style="Accent.TButton", command=self.on_start)
        self.start_button.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.counter = ttk.Label(frame, text="0 saved this session", style="Muted.TLabel")
        self.counter.grid(row=2, column=0, pady=(10, 0))
        self.status = ttk.Label(frame, text=notice, wraplength=260, style="Warning.TLabel")
        self.status.grid(row=3, column=0, pady=(6, 0), sticky="w")
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
        self.style()
        frame = ttk.Frame(win, padding=16)
        frame.grid()
        w = self.widgets = {}
        ttk.Label(frame, text="New bug report", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        preview = ttk.Frame(frame, style="Card.TFrame", padding=6)
        preview.grid(row=1, column=0, columnspan=2, pady=(10, 12))
        try:
            image = tk.PhotoImage(file=str(self.session.screenshot))
            factor = max(1, -(-max(image.width(), image.height()) // THUMB))
            w["photo"] = image.subsample(factor, factor) if factor > 1 else image
            ttk.Label(preview, image=w["photo"], style="Card.TLabel").grid()
        except tk.TclError:
            ttk.Label(preview, text="(preview unavailable)", style="Muted.Card.TLabel").grid()

        prefill = prefill or {}
        form = ttk.Frame(frame)
        form.grid(row=2, column=0, columnspan=2, sticky="ew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Title", style="Heading.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=4)
        w["title"] = ttk.Entry(form, width=48)
        w["title"].grid(row=0, column=1, sticky="ew", pady=4)
        w["title"].insert(0, prefill.get("title", ""))
        ttk.Label(form, text="Notes", style="Heading.TLabel").grid(row=1, column=0, sticky="nw", padx=(0, 12), pady=4)
        w["notes"] = tk.Text(
            form, width=48, height=6, wrap="word", relief="flat", background=CARD, foreground=TEXT,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=6, pady=4,
            font=self.body_font,
        )
        w["notes"].grid(row=1, column=1, sticky="ew", pady=4)
        w["notes"].insert("1.0", prefill.get("notes", ""))
        w["notes"].bind("<KeyRelease>", lambda e: self.check_notes())
        ttk.Label(form, text="Tags", style="Heading.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        w["tags"] = ttk.Entry(form, width=48)
        w["tags"].grid(row=2, column=1, sticky="ew", pady=4)
        w["tags"].insert(0, ", ".join(initial_tags(self.cfg, prefill)))
        ttk.Label(form, text="Status", style="Heading.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=4)
        w["status"] = ttk.Combobox(form, values=list(STATUSES), state="readonly", width=16)
        w["status"].set(prefill.get("status", "open"))
        w["status"].grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Repo", style="Heading.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Label(form, text=(self.cfg.key if self.cfg else "(none)"), style="Muted.TLabel").grid(
            row=4, column=1, sticky="w", pady=4)
        w["error"] = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        w["error"].grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Discard", command=self.on_discard).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self.on_save).grid(row=0, column=1)
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
