---

description: "Task list for Live-Mode Form and Capture Improvements"
---

# Tasks: Live-Mode Form and Capture Improvements

**Input**: Design documents from `specs/003-live-form-capture/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (Constraints): staged-item removal, form-state persistence/restore, capture/record argv per target and OS, and the shortcut map. Tests are written first and must fail before implementation. Tk glue in `src/bugcap/live.py` is verified through [quickstart.md](quickstart.md), not unit tests.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md
- Run tests the CI way: `uv run --extra dev pytest` and `uv run --extra dev ruff check .`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the baseline before changing anything.

- [X] T001 Run `uv run --extra dev pytest` and `uv run --extra dev ruff check .` on branch `003-live-form-capture` and record that the baseline is green (any pre-existing failure is noted in specs/003-live-form-capture/tasks.md under Notes before continuing)
- [X] T002 [P] Add an "Unreleased" section to CHANGELOG.md with four empty bullets (Attachments, Remembered form, Capture target, Shortcuts) to be filled in by later tasks

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Stable staging numbers (research R1), used by US1 (removal) and US2 (drafts restore numbers).

**⚠️ CRITICAL**: US1 and US2 depend on this phase. US3 and US4 do not, and can start after Phase 1.

- [X] T003 Write failing tests in tests/test_live_session.py: (a) staged items get `number` 1, 2, 3 in staging order; (b) after removing number 2 and staging another item the new item is number 4 ("assigned `max(existing)+1` when staged; never reused within one in-progress bug"); (c) `preview_media()` returns stand-ins whose `idx` equals each item's `number`; (d) `save()` with notes `"see @3"` where staged numbers are [1, 3] stores the report with notes `"see @2"` and the video as media index 2; (e) `attach()` keeps using the final report numbers (a note there can also point at the report's own media, so staging numbers would be ambiguous)
- [X] T004 Add field `number: int = 0` to `Staged` in src/bugcap/live_session.py; include it in `to_item()`/`from_item()` (`from_item` defaults a missing number to the item's 1-based position); add `LiveSession._next_number()` and assign the number in `capture_done`, `recording_done` and `_upload`; restore keeps draft numbers
- [X] T005 Change `LiveSession.preview_media()` in src/bugcap/live_session.py to use `s.number` as the stand-in `idx`
- [X] T006 In src/bugcap/live_session.py make `save()` rewrite notes from staging numbers to final media indexes with `refs.rewrite_references(notes, {str(s.number): str(m.idx) for s, m in zip(self.staged, added)})` after `_attach_all` and before `service.set_notes` (`attach()` is unchanged; see T003 (e)); validation keeps using `preview_media()` (stable numbers). Make T003 pass

**Checkpoint**: Stable numbers in place; existing tests in tests/test_live_session.py still pass.

---

## Phase 3: User Story 1 - Remove and preview attachments (Priority: P1) 🎯 MVP

**Goal**: Remove any staged item (after confirmation) from the form or the control panel, and open any item in the OS default app.

**Independent Test**: Stage two images and one video, open the form, remove the second image, click the video, save. The report holds the first image and the video, the removed file is gone, and the video opened in the system player.

### Tests for User Story 1

- [X] T007 [P] [US1] Write failing tests in tests/test_opener.py per contracts/capture-argv.md: `open_argv(p, "macos") == ["open", p]`, `open_argv(p, "linux") == ["xdg-open", p]`, `open_argv(p, "windows") is None`; for a frames item the folder is opened; `open_path()` returns "File not found: <path>" for a missing file, "No application to open <name>. It is at <path>." for a non-zero exit or an `OSError` from an injected `startfile`, and `None` on success (inject `runner`/`startfile`/`platform`)
- [X] T008 [P] [US1] Write failing tests in tests/test_live_session.py: `remove_staged(number)` works in READY and DETAILS, is ignored in CAPTURING/RECORDING, deletes non-shared files, keeps shared uploads on disk; removing the only item in DETAILS leaves state DETAILS with `staged == []` (note-only); the notes check (`refs.validate_references(notes, session.preview_media())`) rejects `@2` after number 2 was removed

### Implementation for User Story 1

- [X] T009 [P] [US1] Create src/bugcap/opener.py with `open_argv(path, platform=None)` (pure) and `open_path(path, *, platform=None, runner=subprocess.run, startfile=getattr(os, "startfile", None), timeout=3) -> str | None` mapping errors as in contracts/capture-argv.md; make T007 pass
- [X] T010 [US1] In src/bugcap/live_session.py change `remove_staged` to take a staging `number` (not a list index), allow READY and DETAILS, and add `LiveSession.item_path(number)` returning the path to open (main file, or the frames folder); make T008 pass
- [X] T011 [US1] In src/bugcap/live.py extract the thumbnail strip of `open_details()` into `_render_strip(parent)` so it can be rebuilt in place without reopening the window or losing typed fields; each card gets `takefocus=1`, a click/Enter handler that calls `opener.open_path(session.item_path(n))` and shows any returned message via `set_status` and the form's error label, and a small "✕" remove button
- [X] T012 [US1] In src/bugcap/live.py add `on_remove(number, parent)`: `messagebox.askyesno("Remove", f"Remove {describe([item])} (@{number})?", default="yes", parent=parent)`; on yes call `session.remove_staged(number)`, then `refresh()`, rebuild the strip if the form is open (switching the title to "New bug (note only)" when empty) and re-run `check_notes()`
- [X] T013 [US1] In src/bugcap/live.py replace the control panel's single `staged_label` with a compact list (one row per staged item: `@n kind` + open + ✕), rebuilt by `refresh()`; removal there goes through `on_remove(number, self.root)` and updates any open form (spec US1 scenario 2)
- [X] T014 [US1] Fill the "Attachments" CHANGELOG.md bullet and add the remove/open behaviour to the live-mode section of docs/usage.html and README.md

**Checkpoint**: Quickstart scenario 1 passes; US1 is shippable alone.

---

## Phase 4: User Story 2 - Keep what was typed until Discard or Save (Priority: P1)

**Goal**: Back/Cancel keep the typed state; the New bug form and staged items survive restarts and crashes (≤ 5 s of typing lost).

**Independent Test**: Type title, notes and tags, Back, reopen: all fields are restored. Kill the process after 6 s, relaunch, accept the draft: fields and media are restored.

### Tests for User Story 2

- [X] T015 [P] [US2] Write failing tests in tests/test_drafts.py per contracts/drafts-format.md: `write_progress(draft_id=None, …)` creates `<uuid>.json` with `"version": 2`, `updated_at`, per-media `"path"` (absolute), `"number"`, `"source"`, `"shared"`, and does not move media; calling it again with the same id overwrites atomically (write `<uuid>.json.tmp` then `os.replace`; simulate a crash by making `os.replace` raise and check the previous sidecar is intact); `load_draft` reads v2 `path` entries, v1 `file` entries and legacy `<uuid>.png`; a v2 draft with `media: []` and a title loads; `delete_draft` never removes media referenced by absolute `path`
- [X] T016 [P] [US2] Write failing tests in tests/test_live_session.py: `remember_form(fields)` + `cancel_details()` then `form` returns the same title/notes/tags/status/repo; `autosave(fields)` writes a progress draft only when (fields, staged numbers) changed since the last write; staging and removal trigger a write; `save()` success and `discard(True)` delete the progress draft and clear `form`; `discard(False)` changes nothing; `restore(draft)` adopts `draft.id` and `form`, and the next autosave writes to the same id; `addition` (report_id, note) survives `cancel_attach()` and is cleared by a successful `attach()` and by `discard(True)`, and is never written to disk; `keep_as_draft()` on quit moves media into drafts/ and keeps a single draft (no duplicate progress draft)

### Implementation for User Story 2

- [X] T017 [P] [US2] In src/bugcap/drafts.py add `write_progress(draft_id, repo, fields, items) -> str` (atomic temp + `os.replace`, v2 format, media left in place, preserves `created_at` on rewrite); extend `_items_from_meta` to accept `"path"` (absolute) or `"file"` (relative) plus optional `number`, `source`, `shared`; make T015 pass
- [X] T018 [US2] In src/bugcap/live_session.py add `form: dict`, `addition: dict`, `_last_written`, `remember_form(fields)`, `autosave(fields=None) -> bool` (calls `drafts.write_progress` with `repo` = `fields.get("repo")` or the session repo key; skips when unchanged; no-op when nothing staged and no title/notes), `remember_addition(report_id, note)`, `cancel_attach()`; call `autosave()` after `capture_done`, `recording_done`, `_upload` and `remove_staged`; clear `form`/`addition` in `_finish` and `discard`; `restore()` sets `form` from `draft.fields()` and adopts `draft.id`; `keep_as_draft()` reuses/deletes the progress draft so only one draft remains; make T016 pass
- [X] T019 [US2] In src/bugcap/live.py: `on_back()` calls `session.remember_form(self.fields())` and `session.autosave(...)` before closing (update its docstring); `open_details()` prefills from `session.form` when no explicit prefill is given (including repo via `on_repo_change` logic); `fields()` includes `"repo"`
- [X] T020 [US2] In src/bugcap/live.py add a 1 s `after` loop while the New bug form is open that calls `session.remember_form(self.fields())` and, at most every 5 s, `session.autosave(...)`; cancel the loop in `close_details()`; also autosave in `on_close_details()` and `on_close_control()` before any prompt
- [X] T021 [US2] In src/bugcap/live.py `on_existing()`: preselect `session.addition["report_id"]` (if still in the list) and prefill the note; Cancel/close calls `session.remember_addition(...)`; a successful Add clears it (spec US2 scenarios 3 and 8)
- [X] T022 [US2] Fill the "Remembered form" CHANGELOG.md bullet and update docs/usage.html (live-mode list item about drafts) and README.md

**Checkpoint**: Quickstart scenarios 2 and 3 pass; US1 still passes.

---

## Phase 5: User Story 3 - Choose what to capture or record (Priority: P2)

**Goal**: Chooser on every Screenshot/Record click (monitor / all / region / window); output limited to the target; unsupported options disabled with a reason; last choice remembered.

**Independent Test**: On two monitors, screenshot monitor 2 only, then record a drawn region for 5 s. The image size equals monitor 2's and the video frame size equals the region (±2 px).

### Tests for User Story 3

- [X] T023 [P] [US3] Write failing tests in tests/test_screens.py: parse `xrandr --listactivemonitors` (including negative offsets and a primary `*`), `wlr-randr --json`, `swaymsg -t get_outputs`, `wmctrl -lG`, `xwininfo -root -tree` fixtures into `Monitor(id, x, y, width, height, primary, label)` / `Window(handle, title, x, y, width, height)`; Windows enumeration through an injected fake `ctypes` shim returns monitors ordered primary first, then by (x, y), and skips untitled/cloaked/own windows; `label` format "Monitor 2 — 1920×1080 (primary)"
- [X] T024 [P] [US3] Write failing tests in tests/test_targets.py: `availability(platform, session, backend, tools)` matrix: Windows+flameshot+ffmpeg all enabled; Wayland window disabled with "Window capture isn't supported on Wayland."; Wayland region disabled without `slurp` with "Install slurp to draw a region on Wayland."; X11 window disabled without `wmctrl` and `xwininfo`; macOS window recording disabled; region rects with w or h < 16 are rejected ("treated as cancelled"); recording rects are rounded down to even; `remember()`/`recall()` via config key `live.capture_target` matches a monitor by id, then rect, else returns `all` with a fallback message
- [X] T025 [P] [US3] Write failing tests in tests/test_capture.py per contracts/capture-argv.md: `build_screenshot_argv` for flameshot all/monitor (`screen -n N -e --path D`)/region (`gui --region WxH+X+Y --path D`)/window, satty+grim (`-o OUTPUT`, `-g "X,Y WxH"`), screencapture (`-D N+1`, `-R X,Y,W,H`, `-i -w`); unsupported combinations raise `TargetUnsupported`; `capture_screenshot()` with no argument still produces today's flameshot/satty/screencapture commands (existing tests unchanged)
- [X] T026 [P] [US3] Write failing tests in tests/test_recorder_argv.py: gdigrab monitor/region (`-offset_x X -offset_y Y -video_size WxH -i desktop`, negative offsets), gdigrab window (`-i title=<title>`), x11grab region (`-video_size WxH -i :0.0+X,Y`), wf-recorder monitor (`-o OUTPUT`) and region (`-g "X,Y WxH"`), avfoundation monitor index and region crop; mp4 with a target adds `-movflags +frag_keyframe+empty_moov`; `target=None` output is byte-identical to the current builder for every existing case
- [X] T027 [P] [US3] Write failing tests in tests/test_recorder_run.py: `run_recording(..., still_valid=f)` stops when `f()` returns "window closed", keeps the file, and sets `RecordResult.reason == "window closed"`; `still_valid=None` behaves as today

### Implementation for User Story 3

- [X] T028 [P] [US3] Create src/bugcap/screens.py: `Monitor` and `Window` dataclasses; `list_monitors(platform=None, env=None, runner=subprocess.run, win=None)` and `list_windows(...)` per research R4 (Windows via `ctypes` `EnumDisplayMonitors`/`GetMonitorInfoW`/`EnumWindows`/`IsWindowVisible`/`GetWindowTextW`/`DwmGetWindowAttribute`; X11 via `xrandr`, `wmctrl -lG` or `xwininfo`; Wayland via `wlr-randr --json` or `swaymsg`; macOS via avfoundation device list); `window_state(window) -> None | "window closed" | "window minimised" | "window moved"`; `enable_dpi_awareness()` (`SetProcessDpiAwareness(2)`, fallback `SetProcessDPIAware`, no-op off Windows); make T023 pass
- [X] T029 [US3] Create src/bugcap/targets.py: `CaptureTarget(kind, monitor, rect, window)` with kinds `all | monitor | region | window`; `availability(...)` returning `{kind: (enabled, reason)}` (FR-017); `normalize_rect(rect, for_recording)` (min 16×16, even sizes for recording); `remember(target)`/`recall(monitors)` via `config.set_value`/`config.get` key `live.capture_target` storing `{"kind", "monitor_id", "monitor_rect"}`; make T024 pass (depends on T028)
- [X] T030 [P] [US3] In src/bugcap/capture.py add `TargetUnsupported`, pure `build_screenshot_argv(backend, target, dest, platform=None, raw=None)` per contracts/capture-argv.md, and `capture_screenshot(target=None)` that runs the built commands (no-target path unchanged); for flameshot monitor targets, fall back to `gui --region <monitor rect>` when the monitor index is out of range; make T025 pass
- [X] T031 [P] [US3] In src/bugcap/recorder.py add `target=None` to `build_capture_argv` (input section per contracts/capture-argv.md, fragmented mp4 only with a target) and `target=None, still_valid=None` to `run_recording` (polled each loop next to `wait_for_stop`; reason from `still_valid()`); make T026 and T027 pass
- [X] T032 [US3] In src/bugcap/live.py add `_choose_target(kind)`: a modal "Capture what?" `Toplevel` listing `screens.list_monitors()` rows, "All screens", "Region…", "Window…" (with a window list from `screens.list_windows()`), each disabled with its reason from `targets.availability(...)`; preselect `targets.recall(...)` and show its fallback message in the status line; Enter confirms, Esc cancels; opened from `on_start()` and `on_record()` before anything is captured (FR-011); `remember()` the confirmed choice
- [X] T033 [US3] In src/bugcap/live.py add `_draw_region()`: withdraw live windows, show a borderless topmost `-alpha 0.25` overlay covering the virtual desktop (union of monitors) with a `Canvas` rubber-band and a live "W×H" label; release confirms, Esc cancels, < 16×16 cancels with a status message; on Wayland run `slurp` instead and parse `X,Y WxH`
- [X] T034 [US3] In src/bugcap/live.py pass the chosen target to `capture.capture_screenshot(target)` and `recorder.run_recording(..., target=target, still_valid=...)` (window targets use `screens.window_state`); show the stop reason ("window closed", …) in the status line; call `screens.enable_dpi_awareness()` at the start of `run()` before `tk.Tk()`
- [X] T035 [US3] Fill the "Capture target" CHANGELOG.md bullet; document the chooser, per-OS support table and the optional `slurp` dependency in docs/usage.html and README.md

**Checkpoint**: Quickstart scenarios 4–7 and 9 pass on Windows; 5–7 on Ubuntu.

---

## Phase 6: User Story 4 - Drive live mode from the keyboard (Priority: P3)

**Goal**: Every live-mode action has a shortcut (single keys on the control panel, modifiers in forms), shown on buttons and in an F1 overlay; only while a bugcap window is focused.

**Independent Test**: Capture, describe, remove/open an attachment and save using only the keyboard; F1 lists every shortcut used; typing `s`/`n` in Notes types the letters.

### Tests for User Story 4

- [X] T036 [P] [US4] Write failing tests in tests/test_shortcuts.py against contracts/shortcuts.md: every FR-020 action appears exactly once in its scope; no duplicate key within a scope; no `form`/`attach` key is an unmodified printable character; `{mod}` renders `Control`/"Ctrl" on win32/linux and `Command`/"⌘" on darwin and Alt renders "Option" on darwin; `help_lines(platform)` lists every shortcut grouped by scope; control-panel letters bind both cases

### Implementation for User Story 4

- [X] T037 [P] [US4] Create src/bugcap/shortcuts.py with `Shortcut(scope, action, key, label)`, `SHORTCUTS` exactly as the table in contracts/shortcuts.md, `sequences(shortcut, platform)` (Tk sequences, both letter cases for control keys), `label(shortcut, platform)`, `help_lines(platform)`; make T036 pass
- [X] T038 [US4] In src/bugcap/live.py add `_bind_scope(widget, scope, handlers)` that binds `shortcuts.sequences(...)` for that scope; handlers check the matching button is `instate(["!disabled"])` (FR-025) and return `"break"` only for keys they handle; bind the control scope on the root (ignored while a dialog has a grab), the form scope on the New bug `Toplevel`, the attach scope on the Add dialog, the chooser keys on the chooser, and `<F1>` everywhere
- [X] T039 [US4] In src/bugcap/live.py add the attachment selection for the form strip (`Left`/`Right` when a card has focus, `Alt+X` remove via `on_remove`, `Alt+O` open) and `Alt+B` focus of the bug picker in the Add dialog
- [X] T040 [US4] In src/bugcap/live.py show shortcuts on buttons (e.g. "Screenshot  S", "Save  Ctrl+Enter") via `shortcuts.label(...)`, and add `_show_help()`: an F1 `Toplevel` listing `shortcuts.help_lines(sys.platform)`, closed by F1 or Esc
- [X] T041 [US4] Fill the "Shortcuts" CHANGELOG.md bullet and add the shortcut table to docs/usage.html and README.md

**Checkpoint**: Quickstart scenario 8 passes.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update the module docstrings of src/bugcap/live.py and src/bugcap/live_session.py (remove "what was typed is dropped"; describe progress drafts, stable numbers, chooser, shortcuts) and the architecture table in README.md (new modules `screens.py`, `targets.py`, `shortcuts.py`, `opener.py`)
- [X] T043 Run `uv run --extra dev pytest` and `uv run --extra dev ruff check .`; fix failures; confirm no existing CLI/MCP/dashboard test file was modified (SC-008) with `git diff --stat master -- tests/test_cli_* tests/test_mcp* tests/test_dashboard_*`
- [ ] T044 Walk through all scenarios in specs/003-live-form-capture/quickstart.md on Windows (two monitors, 100 % and 150 % scaling) and on Ubuntu (X11; Wayland if available); record results and any deviations under Notes in this file

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup; blocks US1 and US2 only.
- **US1 (Phase 3)** and **US2 (Phase 4)**: after Phase 2. Both edit src/bugcap/live_session.py and src/bugcap/live.py, so run them **sequentially** (US1 then US2).
- **US3 (Phase 5)**: after Setup. Its new modules (screens/targets/capture/recorder) can be built in parallel with US1/US2; its live.py tasks (T032–T034) wait until the US1/US2 live.py tasks are done.
- **US4 (Phase 6)**: after Setup for T036–T037; T038–T040 wait for the live.py work of US1–US3 (they bind actions those stories add).
- **Polish (Phase 7)**: after all stories.

### Within Each Story

Tests first (must fail) → pure modules → session logic → live.py wiring → docs.

### Parallel Opportunities

- T002 alongside T001.
- US1: T007, T008 together; T009 alongside T010.
- US2: T015, T016 together; T017 alongside the start of T018.
- US3: T023–T027 together; T028, T030, T031 together (different files); T029 after T028.
- US4: T036 and T037 can run any time after Setup.
- Cross-story: all of US3's pure work (T023–T031) and US4's T036–T037 can run while US1/US2 are in progress.

## Parallel Example: User Story 3

```text
Task: "T023 [P] [US3] tests/test_screens.py"
Task: "T025 [P] [US3] tests/test_capture.py"
Task: "T026 [P] [US3] tests/test_recorder_argv.py"
Task: "T027 [P] [US3] tests/test_recorder_run.py"
Task: "T024 [P] [US3] tests/test_targets.py"
# then
Task: "T028 [P] [US3] src/bugcap/screens.py"
Task: "T030 [P] [US3] src/bugcap/capture.py"
Task: "T031 [P] [US3] src/bugcap/recorder.py"
```

## Implementation Strategy

### MVP First

1. Phase 1 → Phase 2 → Phase 3 (US1). Stop and validate with quickstart scenario 1: removing and opening attachments is the most visible fix.
2. Add Phase 4 (US2): the data-loss fix. US1 + US2 together are the recommended first release slice.

### Incremental Delivery

3. Phase 5 (US3): the multi-monitor / region / window capture. It is the largest phase and the most platform-dependent, so validate on real hardware (T044).
4. Phase 6 (US4): shortcuts, last because they bind actions added by earlier stories.
5. Phase 7: docs, full CI-equivalent run, manual walkthrough.

## Notes

- T001 baseline (2026-10-25): 507 passed, 3 skipped; ruff clean.
- T043 (2026-10-25): 592 passed, 3 skipped; ruff clean; no `tests/test_cli_*`, `tests/test_mcp*` or `tests/test_dashboard_*` file changed.
- T044 partial (Windows 11, one 1920×1080 monitor, Flameshot 14, ffmpeg): driven by scripts, not by hand: remove/open, Back/reopen, Add-to-existing memory, chooser (default, region drag, Esc), keyboard flow and F1 all behave as specified. Real gdigrab recordings: region 640×360 → 640×360, monitor → 1920×1080, window → the window's size; `window_state` reports "window closed". **Not yet checked:** Flameshot `screen -n` on a second monitor, 150 % scaling, Ubuntu X11/Wayland, macOS, and opening a real video in the OS player.
- Phase 8 (2026-10-25): 599 passed, 3 skipped; ruff clean. Deviations from the task text: T046 crops relative to the drawn screen size (`CaptureTarget.space`, `crop=w=iw*W/SW:…`) instead of reading a scale factor from Tk, because Tk on macOS doesn't report the Retina backing scale; T047 records a `launch_repo` in the progress draft and lists it for that repo too, instead of listing progress drafts of every repo.
- Decision during implementation: "Add to existing" keeps final report numbers in its note (T003 (e)), and a successful Add keeps a remembered new-bug form (FR-008).

- Keep `live.py` thin: any logic that can be tested without Tk goes into `live_session.py`, `screens.py`, `targets.py`, `shortcuts.py` or `opener.py`.
- Never change the output of `capture_screenshot()` / `build_capture_argv()` without a target (CLI/MCP parity).
- Commit after each task or logical group; run the CI command before pushing.

## Phase 8: Convergence

- [X] T045 In src/bugcap/live.py `_draw_region`, compute the overlay bounds only from monitors with a non-zero size and fall back to the Tk screen size otherwise (macOS monitors come from the avfoundation list with 0x0 geometry, so today the overlay is 0x0 and no region can be drawn) per plan: research R5 / FR-015 (partial)
- [X] T046 Scale a drawn region from Tk points to captured pixels for macOS recordings (Retina screens capture at 2x, so the `crop=` in src/bugcap/recorder.py is off by the backing scale); read the scale from Tk (`winfo_fpixels('1i') / 72`) when building the target, and add an argv test in tests/test_recorder_argv.py per FR-012 / SC-006 (partial)
- [X] T047 Offer a progress draft at launch even when its form repo differs from the launch repo (src/bugcap/live.py `start_ui` and src/bugcap/drafts.py `list_drafts`: also include progress drafts, i.e. `"version": 2` sidecars, of any repo), with a test in tests/test_drafts.py per US2/AC7 / FR-009 (partial)
- [X] T048 Refresh the "Add to existing bug" dialog's "Adding: …" summary when a staged item is removed from the control window while the dialog is open (src/bugcap/live.py `on_remove`) per FR-002 (partial)
- [X] T049 Show shortcut hints on the chooser's Cancel/confirm buttons ("Cancel  (Esc)", "Record  (Enter)") in src/bugcap/live.py `_choose_target` per FR-024 (partial)
- [X] T050 Leave bugcap's own windows ("New bug report", "Add to existing bug", "Capture what?") out of the window picker by filtering on this process id (Win32 `GetWindowThreadProcessId`; `_NET_WM_PID` via `xprop` on X11) instead of the "bugcap live" title prefix in src/bugcap/screens.py, with a test in tests/test_screens.py per plan: research R4 (partial)
- [X] T051 Bind macOS `Command-Option-<letter>` alongside `Option-<letter>` for form shortcuts, and list a layout-independent alternative in the F1 help for any shortcut whose key a non-US layout may lack (src/bugcap/shortcuts.py, tests/test_shortcuts.py) per plan: research R9 / spec Edge Cases (partial)
- [X] T052 Review the unrequested change in src/bugcap/drafts.py `save_draft` (shared uploads are now copied into drafts/ instead of moved): keep it and record it in CHANGELOG.md under Fixed, or revert it per plan: research R3 (unrequested)

## Phase 9: Convergence

- [X] T053 Bring the design contracts in line with the Phase 8 code: add `launch_repo` to the sidecar example and rules in specs/003-live-form-capture/contracts/drafts-format.md, add the space-relative macOS `crop=w=iw*W/SW:…` form and `wmctrl -lpG` to specs/003-live-form-capture/contracts/capture-argv.md, and add `Window.pid`, `CaptureTarget.space` and `Draft.launch_repo` to specs/003-live-form-capture/data-model.md per plan: Phase 1 contracts (partial)
