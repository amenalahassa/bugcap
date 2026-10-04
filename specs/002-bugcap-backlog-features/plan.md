# Implementation Plan: Bugcap Backlog Features

**Branch**: `002-bugcap-backlog-features` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-bugcap-backlog-features/spec.md`

## Summary

Extend bugcap (Python 3.10+, stdlib-first, SQLite store) with five capabilities:

1. **Image association**: `--image` on `capture`/`attach` accepts path, glob, or http(s) URL; inputs are validated by magic bytes, copied into the store, and indexed per report with optional labels. Backed by a new `media` table migrated from `image_paths`.
2. **`@` references**: parsed from notes (outside code and emails), validated on save, resolved in `show`, GitHub sync, and the dashboard. Relabel/remove rewrites references under `--force`.
3. **Screen recording**: `bugcap record` drives ffmpeg (portable baseline) or wf-recorder (Wayland), producing video, keyframe frames, or animated GIF, capped by duration and size.
4. **Dashboard**: `bugcap dashboard` serves a 127.0.0.1-only UI built on `http.server` plus static HTML/JS, with a JSON API over the same service layer, media served by id, Range support, and a per-process token for writes.
5. **Live mode** (spec Story 5): `bugcap live` opens a Tk always-on-top control window; each Start runs the existing capture backend, then a details window saves the report and returns to ready.

Central design choice: a new `service.py` layer owns all new rules (validation, indexing, reference rewrite, media lifecycle). The CLI, MCP tools, dashboard API, and live mode call it; none re-implements them. Existing commands keep their behaviour.

## Technical Context

**Language/Version**: Python 3.10+ (matches `requires-python`)

**Primary Dependencies**: None new at runtime. Standard library only: `sqlite3`, `urllib.request`, `http.server`, `tkinter` (live mode), `subprocess`, `secrets`, `glob`. Optional existing extras stay optional (`mcp`). External binaries used when present: `ffmpeg`, `wf-recorder`, `flameshot`, `satty`/`grim`, `screencapture`, `gh`.

**Storage**: SQLite (`bugcap.db`) with `PRAGMA user_version` migrations (current version 1 → 2). Files under the data directory: `images/` (existing), `media/` (new, recordings and frames), `drafts/` (new, live-mode drafts).

**Testing**: pytest (existing suite in `tests/`). Recorder argv construction and dashboard tests use mocked subprocess / in-process `ThreadingHTTPServer` on port 0.

**Target Platform**: Linux (X11, Wayland), macOS, Windows. The dashboard is a local browser page; live mode needs a desktop session.

**Project Type**: CLI tool with an embedded local web UI and a small desktop control window.

**Performance Goals**: Dashboard list of 500 reports filters in under 5 s (SC-006); live-mode details window appears within 1 s of capture (SC-011). Recording overhead is delegated to ffmpeg/wf-recorder.

**Constraints**: No new required third-party dependency (FR-039). No Node build step. Dashboard makes no external requests (FR-037). Media served only from store dirs (FR-033). Existing CLI output unchanged (FR-038). Default URL download cap 25 MB; default recording cap 30 s / 25 MB; GitHub warning threshold 25 MB per file.

**Scale/Scope**: Single user, local store, hundreds to low thousands of reports, a handful of images or recordings per report.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template: no ratified principles, so there are no gates to enforce. Recorded as **not applicable**, not as a pass. The design keeps to the principles the existing code already follows (local-first, stdlib-first, one service layer, no data loss on migration). Recommend ratifying a constitution with these principles before `/speckit-tasks`, so future features have explicit gates.

## Project Structure

### Documentation (this feature)

```text
specs/002-bugcap-backlog-features/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── cli.md           # new/extended commands and flags
│   ├── mcp.md           # new MCP tools
│   └── dashboard-api.md # /api and media routes, token rules
├── checklists/requirements.md
└── tasks.md             # NOT created here (/speckit-tasks)
```

### Source Code (repository root)

```text
src/bugcap/
├── store.py            # MODIFIED: schema v2 (media table), migration, Report.media / image_paths view
├── paths.py            # MODIFIED: media_dir(), drafts_dir(); data-relative path helpers
├── ingest.py           # NEW: resolve SRC (path/glob/URL), size/timeout/content-type checks, magic-byte validation, atomic copy into store
├── refs.py             # NEW: @-token parser (code/fence/email/@@ aware), resolver, rewrite on relabel/remove
├── service.py          # NEW: shared operations: add_media, relabel_media, remove_media, set_notes (validated), set_status, set_tags, create_report
├── recorder.py         # NEW: RECORD_BACKENDS, per-OS argv builders (pure), run/stop/finalize, guidance
├── live.py             # NEW: Tk shell for `bugcap live` (thin)
├── live_session.py     # NEW: pure state machine for live mode (testable without Tk)
├── dashboard/
│   ├── __init__.py
│   ├── server.py       # NEW: ThreadingHTTPServer, loopback guard, Host/Origin checks, routing, Range
│   ├── api.py          # NEW: JSON handlers calling service.py / store (no logic of their own)
│   └── static/         # NEW: index.html, app.js, app.css (no external URLs; light/dark via prefers-color-scheme)
├── backends.py         # UNCHANGED behaviour; `setup` also lists RECORD_BACKENDS
├── capture.py          # UNCHANGED behaviour; import_image/capture_screenshot reused by ingest/live
├── sync.py             # MODIFIED: iterate media (kinds), upload video/animated as-is, frames as a set, size warnings, reference substitution
├── agent_api.py        # MODIFIED: new functions delegate to service.py
├── mcp_server.py       # MODIFIED: register attach_image, update_notes tools
└── cli.py              # MODIFIED: --image (repeatable) on capture/attach; --label; images subcommand; record; live; dashboard; reference validation on edit

tests/
├── test_store_migration.py      # NEW: v1 DB -> v2, no data loss, image_paths fallback
├── test_ingest.py               # NEW: path, glob, URL (local http server), oversize, non-image, timeout, redirects, no credentials
├── test_refs.py                 # NEW: @ parsing edge cases, validation messages, rewrite on relabel/remove
├── test_service.py              # NEW: index stability, label uniqueness, forced rewrite
├── test_recorder.py             # NEW: argv per OS with mocked subprocess, caps, finalize, guidance
├── test_live_session.py         # NEW: state machine transitions, draft recovery
├── test_dashboard_api.py        # NEW: endpoints, filters, validation errors
├── test_dashboard_security.py   # NEW: path traversal, CSRF token, Origin/Host, non-loopback refusal
├── test_github_media_sync.py    # NEW: video/animated as-is, frames as set, size warning
└── test_cli_media.py            # NEW: capture/attach --image, show resolution, record/dashboard arg parsing
```

**Structure Decision**: Keep the existing flat `src/bugcap/` layout and add a single subpackage only for the dashboard (it has static assets). New logic lives in `service.py`, `refs.py` and `ingest.py` so the CLI, MCP, dashboard and live mode share one implementation. `live.py` is a thin Tk shell over the pure `live_session.py`, so the logic is testable without a display.

## Delivery Order (for `/speckit-tasks`)

1. Store v2 migration + `media` table (blocks everything else).
2. `ingest.py` + `service.add_media` + CLI `--image` on `capture`/`attach` + MCP `attach_image`.
3. `refs.py` + validation in `capture`/`edit`/`attach`/MCP + `show` resolution + relabel/remove with `--force`.
4. GitHub sync adaptation (kinds, size warnings, reference substitution).
5. `recorder.py` + `bugcap record` + `setup` extension.
6. `service`-backed dashboard API, then static UI, then security tests.
7. `live_session.py` then `live.py`.
8. README, ROADMAP ticks.

## Complexity Tracking

No constitution exists to violate. Two deliberate complexity points, both justified by the spec:

| Item | Why needed | Simpler alternative rejected because |
|------|-----------|--------------------------------------|
| Separate `media` table alongside legacy `image_paths` | Kinds, labels, stable indexes and per-item source need columns; spec requires old rows to stay readable | Adding columns to the `reports` JSON blob would make index stability and per-item labels hard to enforce with uniqueness |
| Separate `service.py` layer | Spec FR-032 requires the dashboard, CLI and MCP to share logic | Per-interface logic would duplicate validation and rewrite rules in three places |
