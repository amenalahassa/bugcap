# Data Model: Live-Mode Form and Capture Improvements

No database schema change. Entities live in memory (`LiveSession`), in the draft sidecar on disk, or in user config.

## Staged (extended) — `live_session.Staged`

| Field | Type | Notes |
|---|---|---|
| kind | `image \| video \| animated \| frames \| file` | unchanged |
| path, mime, size_bytes, frames, source, shared | — | unchanged |
| **number** | int ≥ 1 | NEW. Stable staging number shown as `@<number>`; assigned `max(existing)+1` when staged; never reused within one in-progress bug; restored from the draft |

Rules: removal is allowed in READY and DETAILS only; removal deletes the files unless `shared` (existing `delete()`). `preview_media()` uses `number` as the stand-in `idx`, so the notes check validates against stable numbers.

## In-progress bug — `LiveSession.form` + `LiveSession.staged` + `LiveSession.draft_id`

| Field | Type | Notes |
|---|---|---|
| form.title / notes / tags / status / repo | str / str / list[str] / str / str\|None | remembered across Back; prefilled on open |
| draft_id | str\|None | id of the progress draft; created at the first autosave, adopted on restore |
| last_written | dict | snapshot of (form, staged numbers) last persisted; the 5 s timer writes only when it differs |

State transitions (extends the existing `LiveState`):

```text
READY --New bug--> DETAILS --Back--> READY            (form kept, progress draft written)
DETAILS --Save ok--> READY                             (form cleared, draft deleted, saved_count+1)
DETAILS --Discard+confirm--> READY                     (form+staged cleared, draft deleted)
DETAILS --Discard+decline--> DETAILS                   (nothing changes)
any --staging change / 5 s tick with changes--> same   (progress draft written)
quit with unsaved --"Save draft?" yes--> exit           (draft kept, media moved into drafts/)
quit with unsaved --no--> exit                          (draft deleted, staged cleared)
```

At Save/Add: notes are rewritten `{str(number): str(final_idx)}` via `refs.rewrite_references`, after media are attached in staging-number order.

## In-progress addition — `LiveSession.addition` (memory only)

| Field | Type | Notes |
|---|---|---|
| report_id | int\|None | bug selected in the dialog |
| note | str | typed note |

Cleared on successful Add, confirmed Discard, or process exit. Never written to disk (clarification Q5).

## Progress draft (sidecar v2) — `drafts/<uuid>.json`

See [contracts/drafts-format.md](contracts/drafts-format.md). `Draft.launch_repo` (from the sidecar's `launch_repo`, defaulting to `repo`) is the repo live mode ran in; `LiveSession.launch_key` keeps it, since `repo_cfg` follows the form's repo picker. Adds per-media `"path"` (absolute), `"number"`, `"source"` and `"shared"`, plus top-level `"version": 2` and `"updated_at"`; `"repo"` holds the repo chosen in the form. Written atomically. Readers accept v1 (no `version`, `"file"` entries) and legacy `<uuid>.png`.

## Monitor — `screens.Monitor`

| Field | Type | Notes |
|---|---|---|
| id | str | device name (`\\.\DISPLAY2`, `HDMI-1`, avfoundation index) |
| x, y, width, height | int | physical pixels, virtual-desktop coordinates (x, y may be negative) |
| primary | bool | |
| label | str | "Monitor 2 — 1920×1080 (primary)" |

## Window — `screens.Window`

| Field | Type | Notes |
|---|---|---|
| handle | str | HWND (Windows) or X11 window id |
| title | str | non-empty |
| x, y, width, height | int | physical pixels |
| pid | int | owning process (0 = unknown); used to leave bugcap's own windows out of the picker |

## CaptureTarget — `targets.CaptureTarget`

| Field | Type | Notes |
|---|---|---|
| kind | `all \| monitor \| region \| window` | |
| monitor | Monitor\|None | for `monitor` |
| rect | (x, y, w, h)\|None | for `region`; also the window rect for X11/Flameshot fallbacks |
| window | Window\|None | for `window` |
| space | (w, h)\|None | size of the coordinate space `rect` was drawn in (Tk points); set for macOS region recordings so the crop is proportional on Retina screens |

Validation: region w, h ≥ 16 (otherwise cancelled); recording sizes rounded down to even.

`targets.availability(platform, session_type, backend, tools) -> {kind: (enabled, reason)}`, per FR-017.

Remembered in config key `live.capture_target` as JSON `{"kind": …, "monitor_id": …, "monitor_rect": [x, y, w, h]}`. Recall matches by `monitor_id`, then by rect, else returns `all` with a fallback message.

## Shortcut — `shortcuts.Shortcut`

| Field | Type | Notes |
|---|---|---|
| scope | `control \| form \| attach \| global` | |
| action | str | method name, e.g. `on_start` |
| key | str | Tk sequence template, e.g. `<{mod}-Return>` |
| label | str | e.g. "Ctrl+Enter" / "⌘+Enter", rendered per OS |
