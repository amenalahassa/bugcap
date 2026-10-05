"""`bugcap live`: a small always-on-top control window (top-right corner) for reporting many
bugs in a row.

Thin Tk shell over `live_session.LiveSession`. Screenshot runs the capture backend (the control
window hides itself so it is not in the picture); Record runs the screen recorder until Stop.
Each capture is *staged*; any mix can then become a new report, be added to an existing one,
or - with nothing staged - become a note-only bug."""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path

from . import capture, drafts, recorder, refs, repo
from .errors import ServiceError
from .live_session import LiveSession, LiveState, describe, initial_tags
from .store import STATUSES, Store

TK_HINT = (
    "Live mode needs tkinter. On Linux install your distro's python3-tk package "
    "(e.g. sudo apt install python3-tk)."
)
NO_DESKTOP = "Live mode needs a desktop session (no DISPLAY or WAYLAND_DISPLAY is set)."
THUMB = 110
MARGIN = 16
RECORD_FORMAT, RECORD_FPS, RECORD_MAX_SECONDS, RECORD_MAX_MB = "video", 30, 120, 50
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
        self.stop_recording = threading.Event()
        self.record_started = 0.0
        self.attach_win = None

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
        style.configure("Danger.TButton", padding=(14, 6), background=DANGER, foreground="#ffffff",
                        bordercolor=DANGER, lightcolor=DANGER, darkcolor=DANGER, focuscolor=DANGER)
        style.map("Danger.TButton", background=[("active", "#991b1b")])
        style.configure("TEntry", fieldbackground=CARD, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, padding=4)
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        style.configure("TCombobox", fieldbackground=CARD, bordercolor=BORDER, padding=3)

    # --- placement -------------------------------------------------------------

    def anchor_control(self) -> None:
        """Keep the control window in the top-right corner of the screen."""
        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - self.root.winfo_reqwidth() - MARGIN
        self.root.geometry(f"+{max(x, 0)}+{MARGIN}")

    def place_beside_control(self, win) -> None:
        """Open a dialog just left of the control window, so neither hides the other."""
        win.update_idletasks()
        x = self.root.winfo_screenwidth() - self.root.winfo_reqwidth() - 2 * MARGIN - win.winfo_reqwidth()
        win.geometry(f"+{max(x, 0)}+{MARGIN}")

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
        frame = ttk.Frame(root, padding=14)
        frame.grid()
        frame.columnconfigure((0, 1), weight=1, uniform="half")
        ttk.Label(frame, text="bugcap live", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.shot_button = ttk.Button(frame, text="Screenshot", style="Accent.TButton", command=self.on_start)
        self.shot_button.grid(row=1, column=0, sticky="ew", pady=(10, 0), padx=(0, 4))
        self.record_button = ttk.Button(frame, text="Record", command=self.on_record)
        self.record_button.grid(row=1, column=1, sticky="ew", pady=(10, 0), padx=(4, 0))
        self.staged_label = ttk.Label(frame, text="", style="Heading.TLabel", wraplength=230)
        self.staged_label.grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.clear_button = ttk.Button(frame, text="Clear", command=self.on_clear)
        self.clear_button.grid(row=2, column=1, sticky="e", pady=(12, 0))
        self.new_button = ttk.Button(frame, text="New bug (note only)", command=self.on_new)
        self.new_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.existing_button = ttk.Button(frame, text="Add to existing bug...", command=self.on_existing)
        self.existing_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.counter = ttk.Label(frame, text="0 saved this session", style="Muted.TLabel")
        self.counter.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="w")
        self.status = ttk.Label(frame, text=notice, wraplength=230, style="Warning.TLabel")
        self.status.grid(row=6, column=0, columnspan=2, pady=(4, 0), sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.on_close_control)
        self.refresh()
        self.anchor_control()
        self.pending_drafts = drafts.list_drafts(self.cfg.key if self.cfg else None)
        root.after(200, self.offer_drafts)

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def refresh(self) -> None:
        """Bring every control-window widget in line with the session."""
        s = self.session
        ready = s.state is LiveState.READY
        recording = s.state is LiveState.RECORDING
        self.counter.configure(text=f"{s.saved_count} saved this session")
        self.shot_button.state(["!disabled"] if ready else ["disabled"])
        self.record_button.state(["!disabled"] if (ready or recording) else ["disabled"])
        self.record_button.configure(text="Stop" if recording else "Record",
                                     style="Danger.TButton" if recording else "TButton")
        n = len(s.staged)
        self.staged_label.configure(text=f"Staged: {describe(s.staged)}" if n else "")
        if n:
            self.clear_button.grid()
            self.new_button.configure(text=f"New bug from {n} item{'' if n == 1 else 's'}...")
        else:
            self.clear_button.grid_remove()
            self.new_button.configure(text="New bug (note only)")
        self.clear_button.state(["!disabled"] if ready else ["disabled"])
        self.new_button.state(["!disabled"] if ready else ["disabled"])
        self.existing_button.state(["!disabled"] if ready else ["disabled"])
        self.anchor_control()

    def on_clear(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("Clear", "Throw away everything staged?", parent=self.root):
            self.session.clear_staged()
            self.refresh()

    # --- screenshot ------------------------------------------------------------

    def on_start(self) -> None:
        if not self.session.start():
            return
        self.refresh()
        self.set_status("Capturing...")
        self.root.withdraw()
        self.root.after(350, self._launch_capture)

    def _launch_capture(self) -> None:
        def worker():
            try:
                self.results.put(("shot", str(capture.capture_screenshot()), None))
            except capture.CaptureError as exc:
                self.results.put(("shot", None, str(exc)))
            except Exception as exc:  # never lose the window to a backend crash
                self.results.put(("shot", None, f"capture failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll)

    # --- recording -------------------------------------------------------------

    def on_record(self) -> None:
        if self.session.state is LiveState.RECORDING:
            self.stop_recording.set()
            self.set_status("Finishing the recording...")
            return
        backend = recorder.detect_recorder()
        if backend is None:
            self.set_status("No screen recorder found. Run `bugcap setup` to install one.")
            return
        if not self.session.start("video"):
            return
        self.stop_recording.clear()
        self.record_started = time.monotonic()
        self.refresh()
        self._tick_recording()

        def worker():
            try:
                result = recorder.run_recording(
                    backend.name, RECORD_FORMAT, RECORD_FPS, RECORD_MAX_SECONDS, RECORD_MAX_MB,
                    wait_for_stop=self.stop_recording.is_set,
                )
                self.results.put(("rec", result, None))
            except recorder.RecorderError as exc:
                self.results.put(("rec", None, " ".join(filter(None, [str(exc), exc.guidance]))))
            except Exception as exc:
                self.results.put(("rec", None, f"recording failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll)

    def _tick_recording(self) -> None:
        if self.session.state is not LiveState.RECORDING:
            return
        if not self.stop_recording.is_set():
            seconds = int(time.monotonic() - self.record_started)
            self.set_status(f"Recording {seconds // 60:02d}:{seconds % 60:02d} (max {RECORD_MAX_SECONDS} s)")
        self.root.after(500, self._tick_recording)

    # --- results ---------------------------------------------------------------

    def _poll(self) -> None:
        try:
            kind, payload, message = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        self.root.deiconify()
        if kind == "shot":
            self.session.capture_done(payload, message)
        else:
            self.session.recording_done(payload, message)
        self.refresh()
        self.set_status(self.session.message or ("Staged. Add more, or file a bug." if self.session.staged else ""))

    # --- drafts ----------------------------------------------------------------

    def offer_drafts(self) -> None:
        from tkinter import messagebox

        while self.pending_drafts and self.session.state is LiveState.READY and not self.session.staged:
            draft = self.pending_drafts.pop(0)
            title = draft.title or "(untitled)"
            answer = messagebox.askyesnocancel(
                "Unsaved draft", f"Restore the unsaved draft {title!r}?\n\nYes: restore   No: discard   Cancel: keep for later",
                parent=self.root,
            )
            if answer is None:
                continue
            if answer:
                self.session.restore(draft)
                self.refresh()
                self.open_details(draft.fields())
                return
            drafts.delete_draft(draft.id)

    # --- new report ------------------------------------------------------------

    def on_new(self) -> None:
        if self.session.begin_details():
            self.refresh()
            self.open_details()

    def open_details(self, prefill: dict | None = None) -> None:
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.root)
        self.details = win
        staged = self.session.staged
        win.title("New bug report" if staged else "New bug (note only)")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.style()
        frame = ttk.Frame(win, padding=16)
        frame.grid()
        w = self.widgets = {}
        ttk.Label(frame, text=win.title(), style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        row = 1
        if staged:
            strip = ttk.Frame(frame)
            strip.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 4))
            w["photos"] = []
            for number, (item, media) in enumerate(zip(staged, self.session.preview_media())):
                card = ttk.Frame(strip, style="Card.TFrame", padding=4)
                card.grid(row=0, column=number, padx=(0, 6))
                image = None
                if item.kind == "image":
                    try:
                        image = tk.PhotoImage(file=str(item.path))
                        factor = max(1, -(-max(image.width(), image.height()) // THUMB))
                        image = image.subsample(factor, factor) if factor > 1 else image
                    except tk.TclError:
                        image = None
                if image is not None:
                    w["photos"].append(image)
                    ttk.Label(card, image=image, style="Card.TLabel").grid()
                else:
                    ttk.Label(card, text=describe([item]), style="Muted.Card.TLabel", width=12,
                              anchor="center").grid()
                ttk.Label(card, text=f"@{refs.media_token(media).lstrip('@')}", style="Muted.Card.TLabel").grid()
            row += 1
            ttk.Label(frame, text="Refer to them in the notes with the @ tags shown.", style="Muted.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
            row += 1

        prefill = prefill or {}
        form = ttk.Frame(frame)
        form.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8 if not staged else 0, 0))
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
        row += 1
        w["error"] = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        w["error"].grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Discard", command=self.on_discard).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Back", command=self.on_back).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self.on_save).grid(row=0, column=2)
        win.protocol("WM_DELETE_WINDOW", self.on_close_details)
        self.place_beside_control(win)
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
        """Show an inline message for an unknown `@` reference."""
        notes = self.widgets["notes"].get("1.0", "end-1c")
        try:
            refs.validate_references(notes, self.session.preview_media())
        except ServiceError as exc:
            valid = ", ".join(exc.details.get("valid", [])) or "none: nothing is staged"
            self.widgets["error"].configure(text=f"{exc.message} (valid: {valid})")
            return False
        self.widgets["error"].configure(text="")
        return True

    def close_details(self) -> None:
        if self.details is not None:
            self.details.destroy()
        self.details = None
        self.widgets = {}
        self.refresh()

    def on_save(self) -> None:
        try:
            report = self.session.save(self.fields())
        except ServiceError as exc:
            self.widgets["error"].configure(text=exc.message)
            return
        self.close_details()
        self.set_status(f"Saved report #{report.id}")
        self.offer_drafts()

    def on_back(self) -> None:
        """Close the form but keep the staged media (what was typed is dropped)."""
        self.session.cancel_details()
        self.close_details()

    def on_discard(self) -> None:
        from tkinter import messagebox

        ok = messagebox.askyesno("Discard", "Discard everything staged and typed?", parent=self.details)
        if self.session.discard(ok):
            self.close_details()
            self.set_status("Discarded.")
            self.offer_drafts()

    def _has_unsaved(self) -> bool:
        f = self.fields()
        return bool(f["title"] or f["notes"].strip() or self.session.staged)

    def on_close_details(self) -> None:
        from tkinter import messagebox

        if self.session.request_close(self._has_unsaved()) == "needs_confirm":
            ok = messagebox.askyesno("Close", "Save this report as a draft?", parent=self.details)
            if self.session.confirm_close(ok) == "save_draft":
                self.session.keep_as_draft(self.fields())
                self.close_details()
                self.set_status("Draft saved.")
        else:
            self.on_back()

    # --- add to an existing report ---------------------------------------------

    def on_existing(self) -> None:
        tk, ttk = self.tk, self.ttk
        if self.attach_win is not None or self.session.state is not LiveState.READY:
            return
        try:
            with Store() as store:
                reports = sorted(store.list(self.cfg.key if self.cfg else None), key=lambda r: -r.id)
        except Exception as exc:
            self.set_status(f"Cannot list bugs: {exc}")
            return
        if not reports:
            self.set_status("No bugs yet: use \"New bug\" first.")
            return
        win = tk.Toplevel(self.root)
        self.attach_win = win
        win.title("Add to existing bug")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=16)
        frame.grid()
        ttk.Label(frame, text="Add to existing bug", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        staged = self.session.staged
        ttk.Label(frame, text=(f"Adding: {describe(staged)}" if staged else "Nothing staged: only the note is added."),
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
        labels = {f"#{r.id}  {r.title}  [{r.status}]": r.id for r in reports}
        ttk.Label(frame, text="Bug", style="Heading.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        pick = ttk.Combobox(frame, values=list(labels), state="readonly", width=52)
        pick.set(next(iter(labels)))
        pick.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Note", style="Heading.TLabel").grid(row=3, column=0, sticky="nw", padx=(0, 12), pady=4)
        note = tk.Text(
            frame, width=52, height=4, wrap="word", relief="flat", background=CARD, foreground=TEXT,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=6, pady=4,
            font=self.body_font,
        )
        note.grid(row=3, column=1, sticky="ew", pady=4)
        error = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        error.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def close():
            win.destroy()
            self.attach_win = None

        def add():
            try:
                report = self.session.attach(labels[pick.get()], note.get("1.0", "end-1c"))
            except ServiceError as exc:
                error.configure(text=exc.message)
                return
            close()
            self.refresh()
            self.set_status(f"Added to report #{report.id}")

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=close).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Add", style="Accent.TButton", command=add).grid(row=0, column=1)
        win.protocol("WM_DELETE_WINDOW", close)
        self.place_beside_control(win)
        note.focus_set()

    # --- quitting --------------------------------------------------------------

    def on_close_control(self) -> None:
        from tkinter import messagebox

        session = self.session
        if session.state is LiveState.RECORDING:
            self.set_status("Stop the recording first.")
            return
        if session.state is LiveState.DETAILS and self.details is not None:
            if session.request_close(self._has_unsaved()) == "needs_confirm":
                ok = messagebox.askyesno("Quit", "Save the open report as a draft and quit?", parent=self.details)
                if session.confirm_close(ok) != "save_draft":
                    return
                session.keep_as_draft(self.fields())
        elif session.staged:
            answer = messagebox.askyesnocancel(
                "Quit", "Keep the staged captures as a draft?\n\nYes: save draft   No: discard   Cancel: stay",
                parent=self.root,
            )
            if answer is None:
                return
            if answer:
                session.keep_as_draft()
            else:
                session.clear_staged()
        self.root.destroy()
