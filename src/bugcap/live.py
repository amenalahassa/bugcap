"""`bugcap live`: a small always-on-top control window (top-right corner) for reporting many
bugs in a row.

Thin Tk shell over `live_session.LiveSession`. Screenshot and Record first ask what to capture
(all screens, a monitor, a drawn region or a window; see `screens.py` and `targets.py`), then run
the capture backend (the control window hides itself so it is not in the picture) or the screen
recorder until Stop. Each capture is *staged*; staged items can be opened or removed, and any mix
can become a new report, be added to an existing one, or - with nothing staged - become a
note-only bug. The new-bug form is remembered and autosaved until Save or Discard. Every action
has a keyboard shortcut (`shortcuts.py`), F1 lists them."""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import backends, capture, drafts, opener, recorder, refs, repo, screens, shortcuts, targets
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
AUTOSAVE_MS = 2000  # the new-bug form is autosaved this often while open (FR-010: <= 5 s)
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

    screens.enable_dpi_awareness()  # so Tk, Win32 and gdigrab agree on pixel coordinates
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


def _hint(scope: str, action: str) -> str:
    """The shortcut shown on a button, e.g. "  (S)"."""
    key = shortcuts.label_for(scope, action, sys.platform)
    return f"  ({key})" if key else ""


def _adding(staged) -> str:
    return f"Adding: {describe(staged)}" if staged else "Nothing staged: only the note is added."


def _kind_name(item) -> str:
    """'image', 'video', 'GIF', 'frame set' or 'file' for one staged item."""
    return describe([item]).split(" ", 1)[1]


class _App:
    def __init__(self, root, session: LiveSession, cfg):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root, self.session, self.cfg = root, session, cfg
        self.results: "queue.Queue" = queue.Queue()
        self.details = None
        self.widgets: dict = {}
        self.repo_choices: list = []
        self.pending_drafts: list = []
        self.stop_recording = threading.Event()
        self.record_started = 0.0
        self.attach_win = None
        self.attach_widgets: dict = {}
        self.chooser = None
        self.help_win = None
        self._autosave_job = None

    # --- styling ---------------------------------------------------------------

    def style(self) -> None:
        """One consistent look for every window: a flat light theme with an accent button."""
        ttk = self.ttk
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
        style.configure("Selected.Card.TFrame", background=CARD, bordercolor=ACCENT, relief="solid", borderwidth=2)
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
        style.configure("Small.TButton", padding=(2, 0))
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
        self.shot_button = ttk.Button(frame, text="Screenshot" + _hint("control", "screenshot"),
                                      style="Accent.TButton", command=self.on_start)
        self.shot_button.grid(row=1, column=0, sticky="ew", pady=(10, 0), padx=(0, 4))
        self.record_button = ttk.Button(frame, text="Record", command=self.on_record)
        self.record_button.grid(row=1, column=1, sticky="ew", pady=(10, 0), padx=(4, 0))
        self.upload_button = ttk.Button(frame, text="Upload image..." + _hint("control", "upload_image"),
                                        command=self.on_upload_image)
        self.upload_button.grid(row=2, column=0, sticky="ew", pady=(6, 0), padx=(0, 4))
        self.file_button = ttk.Button(frame, text="Attach file..." + _hint("control", "attach_file"),
                                      command=self.on_upload_file)
        self.file_button.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(4, 0))
        self.staged_label = ttk.Label(frame, text="", style="Heading.TLabel", wraplength=230)
        self.staged_label.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.clear_button = ttk.Button(frame, text="Clear" + _hint("control", "clear"), command=self.on_clear)
        self.clear_button.grid(row=3, column=1, sticky="e", pady=(12, 0))
        self.staged_list = ttk.Frame(frame)
        self.staged_list.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.new_button = ttk.Button(frame, text="New bug (note only)", command=self.on_new)
        self.new_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.existing_button = ttk.Button(frame, text="Add to existing bug..." + _hint("control", "add_existing"),
                                          command=self.on_existing)
        self.existing_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.counter = ttk.Label(frame, text="0 saved this session", style="Muted.TLabel")
        self.counter.grid(row=7, column=0, columnspan=2, pady=(10, 0), sticky="w")
        self.status = ttk.Label(frame, text=notice, wraplength=230, style="Warning.TLabel")
        self.status.grid(row=8, column=0, columnspan=2, pady=(4, 0), sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.on_close_control)
        self._bind_keys(root, "control", control_keys := {
            "screenshot": self._when(self.shot_button, self.on_start),
            "record": self._when(self.record_button, self.on_record),
            "upload_image": self._when(self.upload_button, self.on_upload_image),
            "attach_file": self._when(self.file_button, self.on_upload_file),
            "new_bug": self._when(self.new_button, self.on_new),
            "add_existing": self._when(self.existing_button, self.on_existing),
            "clear": self._when(self.clear_button, self.on_clear),
        })

        def by_position(event):
            # a non-Latin layout sends another character for the letter keys; Windows still
            # gives the key's position (virtual key code), see shortcuts.action_for_keycode
            if event.char and event.char.isascii():
                return None
            action = shortcuts.action_for_keycode("control", event.keycode, sys.platform)
            if action is None:
                return None
            control_keys[action]()
            return "break"

        root.bind("<Key>", by_position)
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
        self.record_button.configure(text=("Stop" if recording else "Record") + _hint("control", "record"),
                                     style="Danger.TButton" if recording else "TButton")
        n = len(s.staged)
        self.staged_label.configure(text=f"Staged: {describe(s.staged)}" if n else "")
        if n:
            self.clear_button.grid()
            self.new_button.configure(text=f"New bug from {n} item{'' if n == 1 else 's'}..." + _hint("control", "new_bug"))
        else:
            self.clear_button.grid_remove()
            self.new_button.configure(text="New bug (note only)" + _hint("control", "new_bug"))
        self.upload_button.state(["!disabled"] if ready else ["disabled"])
        self.file_button.state(["!disabled"] if ready else ["disabled"])
        self.clear_button.state(["!disabled"] if ready else ["disabled"])
        self.new_button.state(["!disabled"] if ready else ["disabled"])
        self.existing_button.state(["!disabled"] if ready else ["disabled"])
        self._render_staged_list()
        self.anchor_control()

    def _render_staged_list(self) -> None:
        """One row per staged item on the control window: its @ tag and kind (click to open)
        and a remove button."""
        ttk = self.ttk
        for child in self.staged_list.winfo_children():
            child.destroy()
        editable = self.session.state in (LiveState.READY, LiveState.DETAILS)
        for row, (item, media) in enumerate(zip(self.session.staged, self.session.preview_media())):
            name = ttk.Label(self.staged_list, text=f"{refs.media_token(media)}  {_kind_name(item)}",
                             style="Muted.TLabel", cursor="hand2")
            name.grid(row=row, column=0, sticky="w", pady=(2, 0))
            name.bind("<Button-1>", lambda _e, n=item.number: self.on_open_item(n))
            remove = ttk.Button(self.staged_list, text="\u2715", width=2, style="Small.TButton",
                                command=lambda n=item.number: self.on_remove(n, self.root))
            remove.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=(2, 0))
            remove.state(["!disabled"] if editable else ["disabled"])
        self.staged_list.columnconfigure(0, weight=1)

    # --- staged items: open and remove -----------------------------------------

    def on_open_item(self, number: int) -> None:
        path = self.session.item_path(number)
        message = opener.open_path(path) if path is not None else "That item is no longer staged."
        if message:
            self.set_status(message)
            if self.details is not None and self.widgets.get("error") is not None:
                self.widgets["error"].configure(text=message)

    def on_remove(self, number: int, parent) -> None:
        from tkinter import messagebox

        item = self.session.find_staged(number)
        if item is None:
            return
        token = next((refs.media_token(m) for m in self.session.preview_media() if m.idx == number), "")
        if not messagebox.askyesno("Remove", f"Remove {_kind_name(item)} {token}?", default="yes", parent=parent):
            return
        if not self.session.remove_staged(number):
            self.set_status("Finish the current capture first.")
            return
        self.set_status(f"Removed {token}.")
        self.refresh()
        if self.details is not None:
            self._render_strip()
            self.check_notes()
        if self.attach_widgets.get("summary") is not None:
            self.attach_widgets["summary"].configure(text=_adding(self.session.staged))

    def on_clear(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("Clear", "Throw away everything staged?", parent=self.root):
            self.session.clear_staged()
            self.refresh()

    # --- screenshot ------------------------------------------------------------

    def on_start(self) -> None:
        if self.session.state is not LiveState.READY:
            return
        backend = backends.detect()
        target = self._choose_target("shot", backend.name if backend else "")
        if target is None or not self.session.start():
            return
        self.refresh()
        self.set_status(f"Capturing {target.describe()}...")
        self.root.withdraw()
        self.root.after(350, lambda: self._launch_capture(target))

    def _launch_capture(self, target=None) -> None:
        def worker():
            try:
                self.results.put(("shot", str(capture.capture_screenshot(target)), None))
            except capture.CaptureError as exc:
                self.results.put(("shot", None, str(exc)))
            except Exception as exc:  # never lose the window to a backend crash
                self.results.put(("shot", None, f"capture failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll)

    # --- uploads ---------------------------------------------------------------

    def on_upload_image(self) -> None:
        self._pick_and_stage("Choose image(s)", self.session.upload_images, [
            ("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All files", "*.*")])

    def on_upload_file(self) -> None:
        self._pick_and_stage("Choose file(s) to attach", self.session.upload_files, [("All files", "*.*")])

    def _pick_and_stage(self, title: str, stage, filetypes) -> None:
        from tkinter import filedialog, messagebox

        if self.session.state is not LiveState.READY:
            return
        paths = filedialog.askopenfilenames(title=title, parent=self.root, filetypes=filetypes)
        if not paths:
            return
        errors = stage(paths)
        self.refresh()
        if errors:
            messagebox.showerror("Not added", "\n".join(errors), parent=self.root)
        self.set_status("Staged. Add more, or file a bug." if self.session.staged else "")

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
        target = self._choose_target("record", backend.name)
        if target is None or not self.session.start("video"):
            return
        still_valid = self._window_watch(target.window) if target.kind == "window" else None
        self.stop_recording.clear()
        self.record_started = time.monotonic()
        self.refresh()
        self._tick_recording()

        def worker():
            try:
                result = recorder.run_recording(
                    backend.name, RECORD_FORMAT, RECORD_FPS, RECORD_MAX_SECONDS, RECORD_MAX_MB,
                    wait_for_stop=self.stop_recording.is_set, target=target, still_valid=still_valid,
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
        if kind == "rec" and payload is not None and payload.reason.startswith("window "):
            self.set_status(f"Recording stopped: {payload.reason}. What was recorded is staged.")

    # --- keyboard ----------------------------------------------------------------

    def _bind_keys(self, widget, scope: str, handlers: dict) -> None:
        """Bind `scope`'s shortcuts (see shortcuts.py) on `widget`, plus F1 for the help. A
        handled key stops there, so a text field never also types it."""
        def run(handler):
            def on_key(_event=None):
                handler()
                return "break"
            return on_key

        handlers = {**handlers, "help": self.toggle_help}
        for shortcut in shortcuts.SHORTCUTS:
            if shortcut.scope in (scope, "global") and shortcut.action in handlers:
                for sequence in shortcuts.sequences(shortcut, sys.platform):
                    widget.bind(sequence, run(handlers[shortcut.action]))

    @staticmethod
    def _when(button, action):
        """A shortcut does what its button does, and nothing while the button is disabled or hidden."""
        def guarded():
            if button.winfo_ismapped() and button.instate(["!disabled"]):
                action()
        return guarded

    def toggle_help(self) -> None:
        """F1: a window listing every shortcut for this OS; F1 or Esc closes it."""
        tk, ttk = self.tk, self.ttk
        if self.help_win is not None:
            self.help_win.destroy()
            self.help_win = None
            return
        win = tk.Toplevel(self.root)
        self.help_win = win
        win.title("bugcap live: keyboard shortcuts")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=16)
        frame.grid()
        for row, line in enumerate(shortcuts.help_lines(sys.platform)):
            heading = bool(line) and not line.startswith(" ")
            ttk.Label(frame, text=line.strip() if heading else line, style="Heading.TLabel" if heading else "TLabel",
                      font=None if heading else "TkFixedFont").grid(row=row, column=0, sticky="w")

        def close(_event=None):
            win.destroy()
            self.help_win = None
            return "break"

        for sequence in ("<F1>", "<Escape>"):
            win.bind(sequence, close)
        win.protocol("WM_DELETE_WINDOW", close)
        win.update_idletasks()  # centred, so it never sits on top of the dialog it explains
        x = (win.winfo_screenwidth() - win.winfo_reqwidth()) // 2
        y = (win.winfo_screenheight() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.focus_force()

    # --- what to capture -------------------------------------------------------

    def _choose_target(self, purpose: str, backend: str):
        """The "Capture what?" dialog, shown on every Screenshot/Record click: all screens,
        one monitor, a region (drawn next) or a window. Options the platform or tool cannot
        honour are disabled with the reason. The last choice is preselected; Enter confirms,
        Esc cancels (None)."""
        tk, ttk = self.tk, self.ttk
        session = screens.session_type()
        try:
            monitors = screens.list_monitors()
        except Exception:
            monitors = []
        try:
            windows = screens.list_windows()
        except Exception:
            windows = []
        allowed = targets.availability(session, backend, purpose)
        if allowed["window"][0] and not windows:
            allowed["window"] = (False, "No windows to pick from.")
        last, note = targets.recall(monitors)

        win = tk.Toplevel(self.root)
        self.chooser = win
        win.title("Capture what?")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=16)
        frame.grid()
        verb = "Record" if purpose == "record" else "Screenshot"
        ttk.Label(frame, text=f"{verb}: capture what?", style="Title.TLabel").grid(row=0, column=0, columnspan=2,
                                                                                    sticky="w", pady=(0, 8))
        choice = tk.StringVar(win)
        rows = [("all", "Whole screen" if len(monitors) <= 1 else "All screens", allowed["all"])]
        if len(monitors) > 1:
            rows += [(f"monitor:{m.number}", m.label, allowed["monitor"]) for m in monitors]
        rows += [("region", "Region (drag on the screen next)", allowed["region"]),
                 ("window", "Window", allowed["window"])]
        row = 1
        for value, text, (enabled, reason) in rows:
            button = ttk.Radiobutton(frame, text=text, value=value, variable=choice)
            button.grid(row=row, column=0, sticky="w", pady=2)
            if not enabled:
                button.state(["disabled"])
                ttk.Label(frame, text=reason, style="Muted.TLabel").grid(row=row, column=1, sticky="w", padx=(12, 0))
            row += 1
        titles = {f"{w.title}"[:70]: w for w in windows}
        pick = ttk.Combobox(frame, values=list(titles), state="readonly", width=48)
        if titles:
            pick.set(next(iter(titles)))
        if allowed["window"][0]:
            pick.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(24, 0), pady=(0, 4))
            pick.bind("<<ComboboxSelected>>", lambda _e: choice.set("window"))
        row += 1
        if note:
            ttk.Label(frame, text=note, style="Warning.TLabel", wraplength=360).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
            row += 1

        enabled_values = [value for value, _, (enabled, _) in rows if enabled]
        preferred = {"all": "all", "region": "region", "window": "window"}.get(last.kind)
        if last.kind == "monitor" and last.monitor is not None:
            preferred = f"monitor:{last.monitor.number}" if len(monitors) > 1 else "all"
        choice.set(preferred if preferred in enabled_values else enabled_values[0])

        result: dict = {}

        def confirm(_event=None):
            value = choice.get()
            result["value"] = value
            result["window"] = titles.get(pick.get())
            win.destroy()

        def cancel(_event=None):
            win.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel" + _hint("chooser", "cancel"), command=cancel).grid(
            row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text=verb + _hint("chooser", "confirm"), style="Accent.TButton",
                   command=confirm).grid(row=0, column=1)
        self._bind_keys(win, "chooser", {"confirm": confirm, "cancel": cancel})
        win.bind("<KP_Enter>", confirm)
        win.protocol("WM_DELETE_WINDOW", cancel)
        self.place_beside_control(win)
        win.focus_force()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(win)
        self.chooser = None

        value = result.get("value")
        if value is None:
            return None
        if value.startswith("monitor:"):
            number = int(value.split(":", 1)[1])
            target = targets.CaptureTarget("monitor", monitor=next(m for m in monitors if m.number == number))
        elif value == "window":
            if result.get("window") is None:
                self.set_status("No window was picked.")
                return None
            target = targets.CaptureTarget("window", window=result["window"])
        elif value == "region":
            rect = self._draw_region(monitors, for_recording=purpose == "record")
            if rect is None:
                self.set_status("No region drawn: nothing was captured.")
                return None
            space = None
            if purpose == "record" and session == "macos":
                space = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
            target = targets.CaptureTarget("region", rect=rect, space=space)
        else:
            target = targets.CaptureTarget("all")
        targets.remember(target)
        return target

    def _draw_region(self, monitors, for_recording: bool):
        """Let the user drag a rectangle over the screen; (x, y, w, h) or None when cancelled
        (Esc, or smaller than 16x16). On Wayland the compositor's `slurp` draws it."""
        if screens.session_type() == "wayland":
            return self._slurp_region(for_recording)
        tk = self.tk
        sized = [m for m in monitors if m.width and m.height]  # macOS lists screens without geometry
        if sized:
            left = min(m.x for m in sized)
            top = min(m.y for m in sized)
            right = max(m.x + m.width for m in sized)
            bottom = max(m.y + m.height for m in sized)
        else:
            left, top = 0, 0
            right, bottom = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        hidden = [w for w in (self.root, self.details, self.attach_win) if w is not None]
        for w in hidden:
            w.withdraw()
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
        try:
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", 0.25)
        except tk.TclError:
            pass
        canvas = tk.Canvas(overlay, background="#000000", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        state: dict = {}

        def press(event):
            state["start"] = (event.x_root, event.y_root)

        def drag(event):
            if "start" not in state:
                return
            x0, y0 = state["start"]
            canvas.delete("sel")
            ax, ay = x0 - left, y0 - top
            bx, by = event.x_root - left, event.y_root - top
            canvas.create_rectangle(ax, ay, bx, by, outline="#ffffff", width=2, tags="sel")
            canvas.create_text(bx + 12, by + 12, anchor="nw", fill="#ffffff", tags="sel",
                               text=f"{abs(bx - ax)}×{abs(by - ay)}")

        def release(event):
            if "start" in state:
                x0, y0 = state["start"]
                x1, y1 = event.x_root, event.y_root
                state["rect"] = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", release)
        overlay.bind("<Escape>", lambda _e: overlay.destroy())
        overlay.focus_force()
        try:
            overlay.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(overlay)
        for w in hidden:
            w.deiconify()
        rect = state.get("rect")
        return targets.normalize_rect(rect, for_recording) if rect else None

    def _slurp_region(self, for_recording: bool):
        exe = shutil.which("slurp")
        if exe is None:
            return None
        try:
            out = subprocess.run([exe], capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.match(r"\s*(-?\d+),(-?\d+) (\d+)x(\d+)", out or "")
        if not match:
            return None
        return targets.normalize_rect(tuple(int(v) for v in match.groups()), for_recording)

    def _window_watch(self, window):
        """`still_valid` for a window recording: checks at most once a second."""
        last = {"at": 0.0}

        def check():
            now = time.monotonic()
            if now - last["at"] < 1.0:
                return None
            last["at"] = now
            try:
                return screens.window_state(window)
            except Exception:
                return None
        return check

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
                self.open_details()
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

        w["title_label"] = frame.grid_slaves(row=0, column=0)[0]
        w["strip"] = ttk.Frame(frame)
        w["strip"].grid(row=1, column=0, columnspan=2, sticky="w")
        self._render_strip()
        row = 2

        prefill = prefill or self.session.form or {}
        form = ttk.Frame(frame)
        form.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
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
        self.repo_choices = repo.known_repos()
        if self.cfg is not None and all(c.root != self.cfg.root for c in self.repo_choices):
            self.repo_choices.append(self.cfg)
        if self.repo_choices:
            current_key = self.cfg.key if self.cfg else ""
            w["repo"] = ttk.Combobox(
                form, values=[c.key for c in self.repo_choices], state="readonly", width=30,
            )
            remembered = prefill.get("repo")
            match = next((c for c in self.repo_choices if c.key == remembered), None) if remembered else None
            if match is not None:
                current_key = match.key
                self.cfg = self.session.repo_cfg = match  # its tag is already in the remembered tags
            elif remembered and remembered != current_key:
                self.set_status(f"Repo {remembered} is no longer set up; using {current_key or 'none'}.")
            w["repo"].set(current_key)
            w["repo"].grid(row=4, column=1, sticky="w", pady=4)
            w["repo"].bind("<<ComboboxSelected>>", self.on_repo_change)
        else:
            ttk.Label(form, text="(none - run `bugcap init` in a repo to tag reports)",
                      style="Muted.TLabel").grid(row=4, column=1, sticky="w", pady=4)
        row += 1
        w["error"] = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        w["error"].grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Discard" + _hint("form", "discard"), command=self.on_discard).grid(
            row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Back" + _hint("form", "back"), command=self.on_back).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="Save" + _hint("form", "save"), style="Accent.TButton",
                   command=self.on_save).grid(row=0, column=2)
        win.protocol("WM_DELETE_WINDOW", self.on_close_details)
        form_keys = {"save": self.on_save, "back": self.on_back, "discard": self.on_discard,
                     "remove_item": lambda: self._on_selected_item(remove=True),
                     "open_item": lambda: self._on_selected_item(remove=False)}
        for widget in (win, w["title"], w["notes"], w["tags"]):  # on the fields too, before their own keys
            self._bind_keys(widget, "form", form_keys)
        self.place_beside_control(win)
        w["title"].focus_set()
        self.check_notes()
        self._autosave_job = win.after(AUTOSAVE_MS, self._autosave_tick)

    def _autosave_tick(self) -> None:
        """Remember and autosave the open form (the session skips unchanged writes)."""
        if self.details is None:
            return
        self.session.autosave(self.fields())
        self._autosave_job = self.details.after(AUTOSAVE_MS, self._autosave_tick)

    def _render_strip(self) -> None:
        """(Re)draw the staged items in the details form: a thumbnail (or the kind) per card,
        its @ tag and a remove button; clicking a card opens the item. Rebuilt in place after a
        removal, so whatever was typed stays."""
        tk, ttk, w = self.tk, self.ttk, self.widgets
        holder = w["strip"]
        for child in holder.winfo_children():
            child.destroy()
        w["photos"], w["cards"] = [], []
        staged = self.session.staged
        title = "New bug report" if staged else "New bug (note only)"
        self.details.title(title)
        w["title_label"].configure(text=title)
        if not staged:
            return
        strip = ttk.Frame(holder)
        strip.grid(row=0, column=0, sticky="w", pady=(10, 4))
        for column, (item, media) in enumerate(zip(staged, self.session.preview_media())):
            card = ttk.Frame(strip, style="Card.TFrame", padding=4, takefocus=1, cursor="hand2")
            card.grid(row=0, column=column, padx=(0, 6))
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
                face = ttk.Label(card, image=image, style="Card.TLabel")
            else:
                face = ttk.Label(card, text=_kind_name(item), style="Muted.Card.TLabel", width=12, anchor="center")
            face.grid(row=0, column=0, columnspan=2)
            tag = ttk.Label(card, text=refs.media_token(media), style="Muted.Card.TLabel")
            tag.grid(row=1, column=0, sticky="w")
            ttk.Button(card, text="\u2715", width=2, style="Small.TButton",
                       command=lambda n=item.number: self.on_remove(n, self.details)).grid(row=1, column=1, sticky="e")
            for widget in (card, face, tag):
                widget.bind("<Button-1>", lambda _e, n=item.number: self.on_open_item(n))
            card.bind("<Return>", lambda _e, n=item.number: self.on_open_item(n))
            card.bind("<FocusIn>", lambda _e, c=card: self._select_card(c))
            card.bind("<FocusOut>", lambda _e, c=card: c.configure(style="Card.TFrame"))
            self._bind_keys(card, "form", {"prev_item": lambda c=card: self._move_selection(c, -1),
                                           "next_item": lambda c=card: self._move_selection(c, 1)})
            card.number = item.number
            w["cards"].append(card)
        ttk.Label(holder, text="Click an item to open it. Refer to them in the notes with the @ tags shown.",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))

    def _select_card(self, card) -> None:
        card.configure(style="Selected.Card.TFrame")
        self.widgets["selected"] = card.number

    def _move_selection(self, card, step: int) -> None:
        cards = self.widgets.get("cards", [])
        if card in cards:
            cards[(cards.index(card) + step) % len(cards)].focus_set()

    def _on_selected_item(self, remove: bool) -> None:
        """Alt+X / Alt+O: act on the selected item (the first one if none was selected)."""
        numbers = [c.number for c in self.widgets.get("cards", [])]
        if not numbers:
            return
        number = self.widgets.get("selected")
        number = number if number in numbers else numbers[0]
        if remove:
            self.on_remove(number, self.details)
        else:
            self.on_open_item(number)

    def on_repo_change(self, _event=None) -> None:
        """The details form's repo picker changed: this report (and its auto tag) now
        belongs to the newly-selected repo instead of the one `live` launched in."""
        selected_key = self.widgets["repo"].get()
        match = next((c for c in self.repo_choices if c.key == selected_key), None)
        if match is None:
            return
        previous = self.cfg
        self.cfg = self.session.repo_cfg = match
        tags_entry = self.widgets["tags"]
        current_tags = [t.strip() for t in tags_entry.get().split(",") if t.strip()]
        if previous is not None and previous.tag in current_tags and previous.tag != match.tag:
            current_tags = [match.tag if t == previous.tag else t for t in current_tags]
        elif match.tag not in current_tags:
            current_tags.append(match.tag)
        tags_entry.delete(0, "end")
        tags_entry.insert(0, ", ".join(current_tags))

    def fields(self) -> dict:
        w = self.widgets
        return {
            "title": w["title"].get().strip(),
            "notes": w["notes"].get("1.0", "end-1c"),
            "tags": [t.strip() for t in w["tags"].get().split(",") if t.strip()],
            "status": w["status"].get() or "open",
            "repo": w["repo"].get() if "repo" in w else (self.cfg.key if self.cfg else None),
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
            if self._autosave_job is not None:
                self.details.after_cancel(self._autosave_job)
            self.details.destroy()
        self._autosave_job = None
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
        """Close the form, keeping the staged media and what was typed (it comes back the next
        time the form opens, and is autosaved so a quit or a crash does not lose it)."""
        self.session.autosave(self.fields())
        self.session.cancel_details()
        self.close_details()

    def on_discard(self) -> None:
        from tkinter import messagebox

        ok = messagebox.askyesno("Discard", "Discard everything staged and typed?", parent=self.details)
        if self.session.discard(ok):
            self.close_details()
            self.set_status("Discarded.")
            self.offer_drafts()

    def on_close_details(self) -> None:
        """Closing the form window is Back: nothing typed is lost."""
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
        summary = ttk.Label(frame, text=_adding(staged), style="Muted.TLabel")
        summary.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
        labels = {f"#{r.id}  {r.title}  [{r.status}]": r.id for r in reports}
        remembered = self.session.addition
        ttk.Label(frame, text="Bug", style="Heading.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        pick = ttk.Combobox(frame, values=list(labels), state="readonly", width=52)
        pick.set(next((label for label, rid in labels.items() if rid == remembered.get("report_id")),
                      next(iter(labels))))
        pick.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Note", style="Heading.TLabel").grid(row=3, column=0, sticky="nw", padx=(0, 12), pady=4)
        note = tk.Text(
            frame, width=52, height=4, wrap="word", relief="flat", background=CARD, foreground=TEXT,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=6, pady=4,
            font=self.body_font,
        )
        note.grid(row=3, column=1, sticky="ew", pady=4)
        note.insert("1.0", remembered.get("note", ""))
        error = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        error.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def close(remember: bool = True):
            if remember:
                self.session.remember_addition(labels.get(pick.get()), note.get("1.0", "end-1c"))
            win.destroy()
            self.attach_win = None
            self.attach_widgets = {}

        def add():
            try:
                report = self.session.attach(labels[pick.get()], note.get("1.0", "end-1c"))
            except ServiceError as exc:
                error.configure(text=exc.message)
                return
            close(remember=False)
            self.refresh()
            self.set_status(f"Added to report #{report.id}")

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        cancel_button = ttk.Button(buttons, text="Cancel" + _hint("attach", "cancel"), command=close)
        cancel_button.grid(row=0, column=0, padx=(0, 8))
        add_button = ttk.Button(buttons, text="Add" + _hint("attach", "add"), style="Accent.TButton", command=add)
        add_button.grid(row=0, column=1)
        attach_keys = {"add": add, "cancel": close, "focus_bug": pick.focus_set}
        for widget in (win, note):
            self._bind_keys(widget, "attach", attach_keys)
        self.attach_widgets = {"pick": pick, "note": note, "add": add, "close": close, "summary": summary,
                               "add_button": add_button, "cancel_button": cancel_button}
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
        if self.details is not None:
            session.autosave(self.fields())  # whatever happens next, the typing is on disk
        form = session.form
        typed = bool((form.get("title") or "").strip() or (form.get("notes") or "").strip())
        if session.staged or typed:
            parent = self.details or self.root
            answer = messagebox.askyesnocancel(
                "Quit", "Keep the bug in progress as a draft?\n\nYes: save draft   No: discard   Cancel: stay",
                parent=parent,
            )
            if answer is None:
                return
            if answer:
                session.keep_as_draft()
            else:
                session.abandon()
        self.root.destroy()
