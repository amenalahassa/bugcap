# Implementation Plan: Live-Mode Form and Capture Improvements

**Branch**: `003-live-form-capture` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-live-form-capture/spec.md`

## Summary

Four improvements to `bugcap live`, shipped together:

1. **Attachments**: remove a staged item (with confirmation) from the form or the control panel, and open any item in the OS default app. Staged items keep stable `@` numbers, rewritten to final media indexes at save (research R1, R2, R10).
2. **Remembered form**: `LiveSession` owns the New bug fields and the in-memory Add-to-existing state. A progress draft with a stable id is written in place (atomic sidecar, media not moved) on Back, close, staging changes and every 5 s, and is restored through the existing draft offer (R3).
3. **Capture target**: a chooser on every Screenshot/Record click (monitor / all screens / region / window). Monitors and windows are listed via `ctypes` (Windows) or existing desktop tools (Linux, macOS), regions are drawn on a Tk overlay (or with `slurp` on Wayland), and the choice becomes pure argv extensions for Flameshot, grim, screencapture, ffmpeg and wf-recorder (R4–R8).
4. **Shortcuts**: one shortcut table drives the Tk bindings, the button labels and an F1 overlay. Single keys on the control panel, modifier keys in the forms (R9).

Central design choice: everything testable lives in pure modules (`live_session.py`, new `screens.py`, `targets.py`, `shortcuts.py`, `opener.py`, and the argv builders). `live.py` stays a thin Tk shell, as in 002.

## Technical Context

**Language/Version**: Python 3.10+ (`requires-python = ">=3.10"`)

**Primary Dependencies**: None new. Standard library only: `tkinter`, `ctypes` (Windows monitor/window/DPI APIs), `subprocess`, `json`, `os`. External binaries used when present: `flameshot` (v12+ for `screen -n`/`--region`; verified on v14), `grim`, `slurp` (new optional, Wayland region), `satty`, `screencapture`, `ffmpeg`, `wf-recorder`, `xrandr`, `wmctrl`/`xwininfo` (X11 windows), `wlr-randr`/`swaymsg` (Wayland outputs), `xdg-open`/`open`.

**Storage**: Unchanged SQLite schema. Drafts sidecar format gains an optional absolute `"path"` per media entry (backward compatible). User config gains `live.capture_target`.

**Testing**: pytest (`uv run --extra dev pytest`, per CI), ruff. New tests are pure: no display needed; Tk-dependent glue is covered by session/state tests and a manual quickstart.

**Target Platform**: Windows 10/11 (including multi-monitor and mixed DPI), Linux X11 and Wayland (wlroots), macOS.

**Project Type**: CLI tool with a Tk desktop control window (live mode).

**Performance Goals**: Chooser opens within 300 ms (monitor/window enumeration ≤ 200 ms); autosave write < 50 ms (sidecar only, media not copied); open-attachment returns to the UI within 3 s at most.

**Constraints**: No new required dependency. CLI/MCP/dashboard behaviour and output unchanged (`capture_screenshot()` and `build_capture_argv()` without a target behave exactly as today). Drafts written by 0.6.x still load. Shortcuts never fire while typing in text fields. Lose at most 5 s of typing on a crash.

**Scale/Scope**: Single user; a handful of staged items; 1–4 monitors; up to a few hundred top-level windows.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template, so there are no ratified gates: **not applicable** (not a pass). The design follows the principles the codebase already applies: stdlib-first / no new dependency, logic in pure testable modules with a thin UI shell, no data loss (atomic draft writes, backward-compatible draft format), and unchanged existing CLI/MCP behaviour.

**Post-design re-check**: unchanged. No violations to justify; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-live-form-capture/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── capture-argv.md  # screenshot/record argv per backend × target (pure builders)
│   ├── drafts-format.md # sidecar format v2 (progress drafts)
│   └── shortcuts.md     # the shortcut table per scope and OS
├── checklists/requirements.md
└── tasks.md             # NOT created here (/speckit-tasks)
```

### Source Code (repository root)

```text
src/bugcap/
├── live.py             # MODIFIED: remove/open on cards and control panel, form rebuilt in place,
│                       #   autosave timer, target chooser + region overlay, shortcut bindings, F1 overlay,
│                       #   DPI awareness on Windows
├── live_session.py     # MODIFIED: stable staging numbers, remove in DETAILS, form/addition state,
│                       #   progress-draft autosave, notes rewrite to final indexes at save/attach
├── drafts.py           # MODIFIED: write_progress() (atomic, media in place), "path" entries in sidecar
├── capture.py          # MODIFIED: build_screenshot_argv() (pure); capture_screenshot(target=None)
├── recorder.py         # MODIFIED: build_capture_argv(..., target=None); fragmented mp4;
│                       #   run_recording(..., target=None, still_valid=None)
├── screens.py          # NEW: Monitor/Window dataclasses; list_monitors()/list_windows() per OS;
│                       #   window_alive()/window_rect(); enable_dpi_awareness()
├── targets.py          # NEW: CaptureTarget, availability per platform/backend (+ reasons),
│                       #   remember/recall via config, monitor matching
├── shortcuts.py        # NEW: SHORTCUTS table, per-OS key/label rendering, help text
└── opener.py           # NEW: open_argv() (pure) + open_path() with friendly errors

tests/
├── test_live_session.py        # EXTENDED: removal, stable numbers, form memory, autosave, rewrite at save
├── test_drafts.py              # EXTENDED: progress drafts, atomic write, old/new format load
├── test_capture.py             # EXTENDED: screenshot argv per backend × target; target=None unchanged
├── test_recorder_argv.py       # EXTENDED: record argv per OS × target; target=None byte-identical
├── test_recorder_run.py        # EXTENDED: still_valid() stop reason, file kept
├── test_screens.py             # NEW: parsers for xrandr/wlr-randr/swaymsg/wmctrl/xwininfo; Windows via fake ctypes
├── test_targets.py             # NEW: availability matrix, remember/recall, monitor fallback
├── test_shortcuts.py           # NEW: completeness vs. FR-020, no duplicates per scope, macOS rendering
└── test_opener.py              # NEW: argv per OS, error mapping
```

Docs: `README.md`, `docs/usage.html` (live-mode section and shortcut table), `CHANGELOG.md` (Unreleased).

**Structure Decision**: Single Python package as today. New behaviour goes into small pure modules beside `live_session.py`, so it can be tested without a display. `live.py` only wires Tk widgets to them.

## Delivery Order (by spec priority)

1. **US1 + US2 (P1)**: session/drafts changes first (pure, test-first), then the `live.py` wiring.
2. **US3 (P2)**: `screens.py` → `targets.py` → argv builders → chooser/overlay UI → watchdog.
3. **US4 (P3)**: `shortcuts.py` → bindings → labels → F1 overlay.
4. Docs and CHANGELOG; run the CI-equivalent `uv run --extra dev pytest` and `ruff`.

## Risks

| Risk | Mitigation |
|---|---|
| DPI awareness changes Tk sizing on Windows | Enable it only in `live.run()`; check the control window at 100/150/200 % in the quickstart |
| Flameshot screen numbering ≠ Win32 order | Order monitors as Qt does; fall back to `gui --region <monitor rect>` (R6) |
| `gdigrab title=` needs an exact, unique title | Pass the title read at selection time; on start failure, fall back to recording the window rect with a status note |
| Wayland compositors differ | Feature-detect tools; disable options with reasons (FR-017) instead of guessing |

## Complexity Tracking

No constitution violations; nothing to justify.
