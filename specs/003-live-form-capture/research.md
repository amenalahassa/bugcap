# Research: Live-Mode Form and Capture Improvements

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-25

Each section: Decision, Rationale, Alternatives considered.

## R1. `@` tags of staged items after a removal

**Decision**: Staged items get a **stable staging number** when they are staged (1, 2, 3, … never reused within one in-progress bug). Removing item 2 leaves items 1 and 3 showing `@1` and `@3`. At Save/Add, the notes are rewritten from staging numbers to the final media indexes with the existing `refs.rewrite_references`, in the same step that attaches the media.

**Rationale**: Renumbering by position (what `LiveSession.preview_media()` does today) would silently re-point `@3` to a different item once `@2` is removed: the notes check would pass while the meaning changed. Stable numbers mean a removed tag becomes invalid (flagged by FR-003) and every other tag keeps its target. The spec allows "renumbers or updates the @ tags shown"; this is the "updates" variant and is the only one that cannot mislead.

**Alternatives considered**: Renumber by position and rewrite notes on removal (rejected: the spec says notes are left as typed). Renumber and leave notes (rejected: silent wrong references).

## R2. Opening an attachment in the OS default application

**Decision**: New pure helper `opener.open_argv(path, platform)` returns the command (`["open", p]` on macOS, `["xdg-open", p]` on Linux); on Windows `os.startfile(p)` is called. `opener.open_path()` runs it, waits up to 3 s for the launcher to return, and maps failures to a message: file missing → "File not found: <path>"; `OSError` from `startfile` (no association) or a non-zero `xdg-open`/`open` exit → "No application to open <name>. It is at <path>." Never raises into Tk.

**Rationale**: No dependency, matches each OS's file associations, works for every kind (image, video, GIF, frames folder, file). For a frame set the folder is opened. `xdg-open` and `open` return quickly and report "no handler" by exit code, so a short wait is enough.

**Alternatives considered**: `webbrowser.open(file://…)` (rejected: opens a browser for videos on many setups, gives no error signal). In-app player (rejected in clarification).

## R3. Remembering the New bug form across Back and crashes

**Decision**:
- `LiveSession` keeps the form fields (`form: dict`) and the Add-to-existing state (`addition: dict`, memory only) independently of the Tk widgets. Back stores the current fields; `open_details()` prefills from `session.form`.
- One **progress draft** per in-progress bug, written in place with a stable id: `drafts.write_progress(draft_id, repo, fields, items)`. It writes the sidecar atomically (temp file + `os.replace`) and records each item's **absolute path** (`"path"`) without moving the media, which stays where it was staged. Writes happen on Back, window close, quit, any staging change (capture, upload, remove), and every 5 s while fields differ from the last write (a Tk `after` timer comparing a snapshot).
- `_items_from_meta` accepts either `"file"` (relative, existing format) or `"path"` (absolute, new). Old drafts load unchanged; `list_drafts`/`offer_drafts` show progress drafts like any other draft.
- Save/Add success and confirmed Discard delete the progress draft (already done for `draft_id` in `_finish`/`discard`). Restoring a draft adopts its id, so autosave keeps writing to it.
- On quit with unsaved work the existing "Save as draft?" prompt stays. "Yes" keeps the progress draft (and moves its media into `drafts/` via the existing `save_draft` path so the store's orphan cleanup can't take it). "No" deletes it.

**Rationale**: Moving media into `drafts/` on every autosave (what `save_draft` does) would churn files every 5 s and break the staged paths in memory. Writing a sidecar that points at media in place is cheap and crash-safe, and reuses the existing restore offer as the clarification asked. Atomic replace means a crash mid-write never leaves an unreadable sidecar.

**Alternatives considered**: A separate `progress.json` store (rejected: a second restore path to maintain). Saving only on Back/close (rejected: FR-010 needs a 5 s bound after a crash). Persisting Add-to-existing too (rejected in clarification Q5).

## R4. Listing monitors and windows without new dependencies

**Decision**: New module `screens.py` with a `list_monitors()` and `list_windows()` per platform. Each returns plain dataclasses, and both are injectable (`runner=`, `ctypes` shim) for tests:

| Platform | Monitors | Windows |
|---|---|---|
| Windows | `ctypes`: `EnumDisplayMonitors` + `GetMonitorInfoW` (physical pixels, primary flag, device name) | `ctypes`: `EnumWindows`, `IsWindowVisible`, `GetWindowTextW`, `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`; skip untitled, cloaked and bugcap's own windows |
| Linux X11 | `xrandr --listactivemonitors` (parse `W/mmxH/mm+X+Y name`) | `wmctrl -lG` if installed, else `xwininfo -root -tree`; window option disabled if neither exists |
| Linux Wayland (wlroots) | `wlr-randr --json`, falling back to `swaymsg -t get_outputs` | Not available: disabled with "Window capture isn't supported on Wayland." |
| macOS | `ffmpeg -f avfoundation -list_devices true` screen entries (index only), geometry from Tk for the main screen | Not available: disabled with "Window recording needs macOS screen-capture APIs bugcap doesn't use." Screenshots of a window use `screencapture -i -w`. |

On Windows, live mode calls `SetProcessDpiAwareness(2)` (per-monitor v2, falling back to `SetProcessDPIAware`) at startup, so Tk, Win32 and gdigrab all use physical pixels.

**Rationale**: Standard library (`ctypes`) on Windows and tools that ship with or beside the existing backends elsewhere. DPI awareness is required: without it, region and monitor rectangles are scaled on high-DPI or mixed-DPI setups (spec edge case: region across monitors with different scaling, SC-006 ±2 px).

**Alternatives considered**: `screeninfo`, `mss` or `pywin32` (rejected: new dependencies, and the request asked to avoid them). Tk `winfo_screenwidth` only (rejected: primary screen only).

## R5. Drawing a region

**Decision**:
- **Windows, X11, macOS**: a Tk overlay. One borderless (`overrideredirect`), topmost, semi-transparent (`-alpha 0.25`) `Toplevel` covering the virtual desktop (Windows: `GetSystemMetrics` `SM_XVIRTUALSCREEN…`; X11: union of monitors; macOS: one overlay per screen is unreliable, so the main screen only, with other screens via the monitor option). The user drags a rectangle drawn on a `Canvas`, and the size shows next to the cursor. Release confirms, Esc cancels, and anything under 16×16 px is treated as cancelled.
- **Wayland**: `slurp` (wlroots companion of `grim`/`wf-recorder`) returns `X,Y WxH`. If it's missing, Region is disabled with "Install slurp to draw a region on Wayland."

The control and form windows are withdrawn while the overlay is up, as Screenshot already does.

**Rationale**: No dependency on the platforms Tk handles well. On Wayland, Tk runs under XWayland and cannot see global coordinates, so the compositor-side tool is the only correct source.

**Alternatives considered**: Flameshot's own `gui` selection, then `--print-geometry` (rejected as the general solution: only works when Flameshot is the backend and doesn't help recording). It is still used for Flameshot screenshots of a region (R6).

## R6. Screenshot command per backend and target

**Decision**: `capture.build_screenshot_argv(backend, target, dest, platform)` is a pure function. `capture_screenshot(target=None)` keeps today's behaviour when `target` is `None`, so CLI, MCP and the tests' `lambda: shot` mocks are unchanged.

| Backend | All screens | Monitor N | Region | Window |
|---|---|---|---|---|
| flameshot (verified on v14) | `gui --path D` (today) | `screen -n N -e --path D` (annotate on that screen only) | `gui --region WxH+X+Y --path D` | `gui --region <window rect> --path D` |
| satty + grim | `grim raw` | `grim -o OUTPUT raw` | `grim -g "X,Y WxH" raw` | disabled (Wayland) |
| screencapture | `-i D` (today) | `-D N+1 D` | `-R X,Y,W,H D` | `-i -w D` |

Flameshot monitor numbers follow Qt screen order. `screens.py` orders Windows monitors with the primary monitor first, then by `(x, y)`, which is Qt's order on Windows. A Flameshot screen whose geometry doesn't match is reported, and the region form `gui --region` is used instead (it always works, because Flameshot's region uses virtual-desktop coordinates).

**Rationale**: Flameshot's `screen -n` is exactly what the multi-monitor Windows bug needs, and `-e` keeps annotation. The region and window forms keep annotation through `gui`.

## R7. Recording command per backend and target

**Decision**: Extend the pure `recorder.build_capture_argv(…, target=None)`. With `None` the output is byte-identical to today (existing `test_recorder_argv.py` must still pass).

| Recorder / OS | Monitor or region `(x, y, w, h)` | Window |
|---|---|---|
| ffmpeg gdigrab (Windows) | `-offset_x x -offset_y y -video_size wxh -i desktop` (negative offsets are valid for monitors left of or above the primary) | `-i title=<exact title>` (follows the window) |
| ffmpeg x11grab (X11) | `-video_size wxh -i :0.0+x,y` | window rect as a region, plus a geometry watchdog (below) |
| wf-recorder (Wayland) | monitor: `-o OUTPUT`; region: `-g "x,y wxh"` | disabled |
| ffmpeg avfoundation (macOS) | monitor: device index `N:none`; region: `-vf crop=w:h:x:y,pad…` | disabled |

- Odd sizes are rounded down to even before building the command, since the existing `pad=` filter only pads up.
- For partial-file safety, mp4 output gets `-movflags +frag_keyframe+empty_moov`, so a recording cut short by a closed window or a crash is still playable.
- Window watchdog: `run_recording` takes an optional `still_valid()` callback, polled like `wait_for_stop`. On Windows it checks that the window still exists and isn't minimised; on X11 it also checks that its geometry is unchanged. When it fails, recording stops with reason "window closed" or "window moved", the file is kept, and the status line names the reason (spec edge case).

**Rationale**: The flags are standard ffmpeg/wf-recorder options, and keeping the builder pure meets FR-019. `title=` is the only gdigrab mode that records one window even when it's covered.

**Alternatives considered**: Recording a full screen and cropping afterwards (rejected: records unrelated content, so worse privacy and size).

## R8. Target chooser and remembering the last choice

**Decision**: A small modal `Toplevel` ("Capture what?") opens on every Screenshot/Record click (clarification Q1). It has radio rows for each monitor ("Monitor 2 — 1920×1080, primary"), "All screens", "Region…", and "Window…" (with a list). Unsupported rows are shown disabled with their reason (FR-017). The last target is preselected, Enter confirms and Esc cancels.

The last choice is stored in the existing user config (`config.set_value("live.capture_target", …)`) as `{"kind": …, "monitor": <device name + geometry>}`. A remembered monitor is matched by device name, then by geometry; if neither matches it falls back to "All screens" with a status note (FR-018). Window and region targets remember their kind only, so the next run starts the picker or the overlay.

**Rationale**: Reuses the config store, and needs no new file.

## R9. Keyboard shortcuts

**Decision**: A single table `shortcuts.py: SHORTCUTS = [(scope, action, key, label)]` with per-OS rendering (`Ctrl` ↔ `Cmd`, `Alt` ↔ `Option`). It drives the Tk bindings, the button text (e.g. "Screenshot  S") and the F1 overlay, and is unit-tested without Tk.

- **Control panel** (no text fields; bound on the root window, but not when focus is in a dialog): `s` Screenshot, `r` Record/Stop, `i` Upload image, `f` Attach file, `n` New bug, `e` Add to existing, `Delete` Clear. Both upper and lower case.
- **New bug form**: `Ctrl/Cmd+Return` Save, `Escape` Back, `Alt+D` Discard, `Alt+X` remove selected attachment, `Alt+O` open selected attachment, `Left`/`Right` move the attachment selection only when focus is on the strip.
- **Add to existing**: `Ctrl/Cmd+Return` Add, `Escape` Cancel, `Alt+B` focus the bug picker.
- **Everywhere**: `F1` opens and closes the overlay.
- On macOS, `Alt` is bound as `Option` and also as `Command-Option` where Option+letter types a character.

Text fields keep their default class bindings: form shortcuts use modifiers, and handlers `return "break"` only for the keys they own. Attachment cards become focusable (`takefocus=1`) so Tab reaches them. Each action calls the same method as its button, and that method already ignores a disabled state (FR-025); the handler also checks `button.instate(["!disabled"])`.

**Rationale**: Follows clarification Q4 exactly. One table removes drift between the bindings, the labels and the help text.

## R10. Remove confirmation

**Decision**: `messagebox.askyesno("Remove", f"Remove {describe([item])} (@{n})?", default="yes")`, parented to the window it was triggered from. Enter accepts the default and Esc cancels (clarification Q3). An item still being recorded or captured can't be removed: removal works only in READY or DETAILS, and the in-flight item isn't staged yet.

`LiveSession.remove_staged` is widened to allow DETAILS (today it is READY-only). After a removal, both the control panel and the open form re-render their staged views. The form keeps its typed fields, because its strip is rebuilt in place instead of reopening the window.
