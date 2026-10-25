# Quickstart: Validate Live-Mode Form and Capture Improvements

## Prerequisites

- Repo checkout on `003-live-form-capture`; `uv` installed.
- A desktop session. For US3: two monitors on Windows with Flameshot (≥ 12) and ffmpeg; an Ubuntu X11 or Wayland session with ffmpeg / wf-recorder (+ `slurp` for Wayland regions).

## Automated checks (CI parity)

```bash
uv run --extra dev pytest
```

```bash
uv run --extra dev ruff check .
```

Both must pass with no changes to existing CLI/MCP/dashboard tests (SC-008).

## Manual scenarios

Start live mode in a repo: `uv run bugcap live`.

1. **Remove and open (US1)**: take 2 screenshots and record 3 s. Open New bug; the tags shown are `@1 @2 @3`. Remove `@2` (confirm with Enter) → the strip shows `@1 @3`. Type `see @2` → an inline error appears and Save is blocked. Click the video card → it opens in the system player. Save with `see @3` → the report shows the video as `@2` (rewritten to its final index).
2. **Back keeps the form (US2)**: type a title, notes and tags; press Esc (Back); press `n` → all fields are back. Open Add to existing (`e`), pick a bug, type a note, press Esc, press `e` → the bug and note are restored.
3. **Crash recovery (US2)**: type a title, wait 6 s, kill the process (Task Manager / `kill -9`). Relaunch → the restore offer lists the draft; Yes restores the fields and media.
4. **Monitor screenshot (US3, Windows + Flameshot)**: press `s`, choose "Monitor 2", Enter → Flameshot opens on monitor 2 only; the saved PNG matches monitor 2's resolution.
5. **Region recording (US3)**: press `r`, choose "Region…", drag about 800×600, record 5 s, press `r` → the video's frame size equals the region within 2 px (`ffprobe -show_streams`).
6. **Window recording (US3)**: press `r`, choose "Window…", pick an app, record, close the app → recording stops with "window closed" and the file plays.
7. **Unavailable options (US3)**: on Wayland, the Window option is disabled with its reason.
8. **Keyboard only (US4)**: do scenario 1 without the mouse using the keys in [contracts/shortcuts.md](contracts/shortcuts.md); F1 lists them all; typing `s` or `n` in the Notes field types the letter.
9. **High DPI (Windows)**: at 150 % scaling, repeat 4 and 5; the rectangles still match.
