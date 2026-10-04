# Tasks: Bugcap Backlog Features (Image Association, @ References, Live Capture, Screen Recording, Dashboard)

**Input**: Design documents from `specs/002-bugcap-backlog-features/` (spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Included. The spec's Quality section explicitly requires pytest coverage for the store migration, URL/path ingestion, `@` parsing, reference rewrite, recorder argv per OS with mocked subprocess, and dashboard API / path-traversal / CSRF tests.

**Organization**: Grouped by user story, in the spec's priority order. Story 5 (live mode) is labelled P2 in the spec, so it is placed directly after Story 2 (also P2). Story 3 (recording) is P3 and Story 4 (dashboard) is P4.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5, mapping to spec.md user stories
- Paths are relative to the repository root

## Path Conventions

- Source: `src/bugcap/`; tests: `tests/`; spec artifacts: `specs/002-bugcap-backlog-features/`
- Dashboard static assets: `src/bugcap/dashboard/static/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Fixtures and packaging needed by every later phase.

- [X] T001 Add package data for dashboard static assets in `pyproject.toml` (`[tool.setuptools.package-data] bugcap = ["dashboard/static/*"]`)
- [X] T002 [P] Create image fixtures generator `tests/fixtures/make_images.py` that writes minimal valid `sample.png`, `sample.jpg`, `sample.gif`, `sample.webp` and a `not-image.txt` into `tests/fixtures/`
- [X] T003 [P] Create v1 database fixture generator `tests/fixtures/make_v1_db.py` that builds `tests/fixtures/v1.db` using the **pre-change** schema (`user_version = 1`, `image_paths` JSON populated, at least one report with two images and one with none, a repo tag, synced_refs set)
- [X] T004 Add a local HTTP server fixture in `tests/conftest.py` (`http_server`): serves `/ok.png`, `/page.html` (text/html), `/big.png` (larger than a configurable cap), `/slow` (sleeps longer than timeout), `/redirect-loop`, `/redirect-file` (302 to a `file://` URL), and records request headers so tests can assert no `Authorization` or `Cookie` is sent

**Checkpoint**: fixtures exist and `pytest --collect-only` is clean.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema v2, media model, and the service/error scaffolding that every story uses. No user story can start until this is done.

**⚠️ CRITICAL**: Blocks all user stories.

- [X] T005 Extend `src/bugcap/paths.py` with `media_dir()` (creates `data_dir()/"media"`), `drafts_dir()` (creates `data_dir()/"drafts"`), `to_data_relative(path) -> str` and `resolve_data_path(rel) -> Path` that raises `ValueError` unless `realpath` is inside `images/` or `media/`
- [X] T006 Bump `SCHEMA_VERSION` to `2` and add DDL for `media` and `media_frames` to `src/bugcap/store.py` exactly as in data-model.md: `media.kind CHECK (kind IN ('image','video','frames','animated'))`, `UNIQUE(report_id, idx)`, `idx >= 1`, unique index on `(report_id, lower(label)) WHERE label IS NOT NULL`, `media_frames PRIMARY KEY (media_id, frame_no)`, both FKs `ON DELETE CASCADE`
- [X] T007 Implement the v1→v2 migration in `Store._migrate` in `src/bugcap/store.py`: one transaction, copy each `image_paths` entry at 0-based position *i* to `media(idx=i+1, kind='image', source='legacy', path=<data-relative if under images/ else legacy absolute>, mime from extension, size_bytes from file or 0)`, set `user_version = 2`, `ROLLBACK` on any error; leave the `image_paths` column untouched
- [X] T008 Add `Media` and `MediaFrame` dataclasses and `Report.media` to `src/bugcap/store.py`; make `Report.image_paths` a compatibility view computed from `kind='image'` media in index order (the `Report.from_row` path must keep working for old rows)
- [X] T009 Add Store methods in `src/bugcap/store.py`: `list_media(report_id)`, `get_media(media_id)`, `insert_media(report_id, **fields) -> Media` (computes `idx = MAX(idx)+1` inside the transaction), `update_media_label(media_id, label)`, `delete_media(media_id)`, `insert_frames(media_id, frames)`
- [X] T010 Make the existing `Store.add_image(report_id, path)` in `src/bugcap/store.py` delegate to `insert_media(kind='image', source=...)` so `sync.py` pull and existing callers keep their signature and behaviour
- [X] T011 [P] Create `src/bugcap/errors.py` with `ServiceError(code: str, message: str, details: dict | None = None)`; codes used later: `not_found`, `invalid_reference`, `duplicate_label`, `invalid_label`, `invalid_image`, `too_large`, `timeout`, `referenced_image`, `invalid_status`, `bad_query`, `bad_token`
- [X] T012 Create `src/bugcap/service.py` skeleton with `create_report`, `get_report_view`, `set_status`, `set_tags`, `set_notes` (notes validation hooked in later by T038), each taking a `Store` and raising `ServiceError`
- [X] T013 [P] Create `src/bugcap/refs.py` with `mask(notes) -> str` that replaces fenced blocks (``` and ~~~, closing fence must be at least as long as opening) and inline code spans (matching backtick-run length) with same-length spaces, preserving positions
- [X] T014 [P] Create `tests/test_store_migration.py`: opens `tests/fixtures/v1.db` and asserts every report survives with identical `title`, `notes`, `tags`, `status`, `repo`, `synced_refs`, and `image_paths` column; each legacy image appears once in `media` with `idx` 1..n, `source='legacy'`, `kind='image'`; re-opening is a no-op; a forced failure mid-migration (monkeypatched insert) leaves `user_version=1` and no `media` rows; a v1 DB with `image_paths` pointing outside `images/` keeps the absolute path

**Checkpoint**: `pytest tests/test_store_migration.py` passes; existing suite still green (`pytest -q`).

---

## Phase 3: User Story 1 - Associate existing images with a bug (Priority: P1) 🎯 MVP

**Goal**: `capture --image` and `attach --image` accept a path, a glob, or an http(s) URL; images are validated, copied into the store, indexed, and optionally labelled. MCP gets the same operation.

**Independent Test**: `bugcap capture --image ./a.png --title T`, then `bugcap attach <id> --image ./shots/*.png --image https://…/b.png --label after-fix`; `bugcap images <id>` lists indexes 1..n with the label; no `--image` source is referenced by its original path.

### Tests for User Story 1

- [X] T015 [P] [US1] Create `tests/test_ingest.py`: classify sources (path / glob / URL); glob matches sorted by filename; glob with no match → `ServiceError(not_found)` naming the pattern; a directory match is skipped with a reason; a `.txt` containing PNG bytes is accepted, a `.png` containing HTML is rejected (`invalid_image`); each of PNG/JPEG/GIF/WebP magic bytes accepted; a truncated file rejected
- [X] T016 [P] [US1] Create `tests/test_ingest_url.py` against `http_server`: success for `/ok.png`; `/page.html` rejected as not an image; `/big.png` aborted with `too_large` when cap is lowered in the test; `/slow` → `timeout` with timeout lowered in the test; `/redirect-file` refused (non-http scheme); more than 5 redirects → error; no `Authorization`/`Cookie` headers sent (assert on recorded headers); non-http(s) scheme (`ftp://`, `file://`) rejected before any request
- [X] T017 [P] [US1] Create `tests/test_service_media.py` for `service.add_media`: index 1-based and never reused after a removal; duplicate label (case-insensitive) → `duplicate_label` naming the existing index; purely numeric label → `invalid_label`; label with spaces → `invalid_label`; partial batch returns both `added` and `rejected`; original file is copied (its path is not stored)
- [X] T018 [P] [US1] Create `tests/test_cli_media.py`: `capture --image` creates report with image index 1 and no capture tool launched (monkeypatch `capture.capture_screenshot` to raise); `attach` with mixed inputs prints `added #…`/`skipped …` lines and exits 1 when any input is rejected; `images <id>` prints index, label, kind, size; old-style report (from v1 fixture) lists its legacy images

### Implementation for User Story 1

- [X] T019 [US1] Create `src/bugcap/ingest.py` with `classify_source(src: str) -> Literal["url","glob","path"]` (URL only for `http://` or `https://` prefixes, case-insensitive)
- [X] T020 [US1] Add `sniff_image(data: bytes) -> str` (returns mime) to `src/bugcap/ingest.py`: PNG `\x89PNG\r\n\x1a\n`, JPEG `\xff\xd8\xff`, GIF `GIF87a`/`GIF89a`, WebP `RIFF`+4 bytes+`WEBP`; raises `ServiceError(invalid_image)` otherwise
- [X] T021 [US1] Add `import_local(path: Path) -> StoredFile` to `src/bugcap/ingest.py`: read, sniff, write to `images_dir()/<uuid><ext>` via temp file + `os.replace` (atomic), return data-relative path, mime, size
- [X] T022 [US1] Add `download_url(url, *, max_bytes=25*1024*1024, timeout=20, max_redirects=5)` to `src/bugcap/ingest.py` using `urllib.request` with a custom redirect handler (http/https only, max redirects), a fixed `User-Agent: bugcap`, no `Authorization`/`Cookie`, streamed read that aborts with `too_large` once `max_bytes` is exceeded and `timeout` mapped to `timeout`; response `Content-Type` is only logged as a hint; then sniff and store as in T021
- [X] T023 [US1] Add `resolve_glob(pattern) -> list[str]` to `src/bugcap/ingest.py` (`glob.glob`, sorted, files only) and `ingest_sources(sources, labels=None) -> IngestResult(added: list, rejected: list[dict])` which expands globs and processes each input independently (partial batch)
- [X] T024 [US1] Implement `service.add_media(store, report_id, sources, labels=None) -> IngestResult` in `src/bugcap/service.py`: validate label (`^[A-Za-z][A-Za-z0-9_-]*$`, not purely numeric, unique case-insensitively within the report, checked before insert), call `ingest_sources`, insert each stored file with `insert_media(kind='image', source=<original>)`, return added/rejected; raise `not_found` when the report does not exist
- [X] T025 [US1] Wire `create_report` in `src/bugcap/service.py` to accept `sources` and `labels` and attach them after the row is created (in one transaction where possible)
- [X] T026 [US1] Extend `cmd_capture` in `src/bugcap/cli.py`: add `--image` (append, may repeat) and `--label` (append, positional with `--image`; empty string = no label). When `--image` is given, skip `capture_screenshot()` and create the report from the imported images; output one line per input (`added #<idx> <basename> (<kind>, <size>)` or `skipped <source>: <reason>`); exit 1 if any input was rejected
- [X] T027 [US1] Extend `cmd_attach` in `src/bugcap/cli.py` with repeatable `--image` and `--label` using `service.add_media`; same output and exit rules as T026
- [X] T028 [US1] Add `bugcap images <id>` subcommand in `src/bugcap/cli.py` listing index, label, kind, size, data-relative path; `not_found` → exit 1 with the standard error
- [X] T029 [US1] Extend `cmd_show` in `src/bugcap/cli.py` with a `Media:` section listing each item (index, label, kind, size, path, source) while keeping existing output lines unchanged for reports without media
- [X] T030 [US1] Add `attach_image(store, id, sources, labels=None)` to `src/bugcap/agent_api.py` delegating to `service.add_media`, returning `{report_id, added, rejected}` as in contracts/mcp.md
- [X] T031 [US1] Register `attach_image` tool in `src/bugcap/mcp_server.py` with inputs `id`, `sources` (1–20), optional `labels`; errors returned as JSON with `code`
- [X] T032 [US1] Extend `get_report` in `src/bugcap/agent_api.py` to include `media` metadata (index, label, kind, mime, size_bytes) per contracts/mcp.md, keeping image bytes behaviour unchanged
- [X] T033 [US1] Extend `tests/test_mcp.py` (skipped when the `mcp` extra is missing) to cover `attach_image` success and partial-rejection output

**Checkpoint**: US1 independently testable. `pytest tests/test_ingest.py tests/test_ingest_url.py tests/test_service_media.py tests/test_cli_media.py` passes; quickstart §2 runs.

---

## Phase 4: User Story 2 - Refer to images from notes with @ (Priority: P2)

**Goal**: Notes may contain `@n` / `@label` references, validated on save, resolved in `show`, GitHub sync, and MCP; relabel/remove refused unless `--force`, and then rewritten.

**Independent Test**: Attach two images (one labelled `login-error`); save notes `@1 @login-error @@1 dev@example.com` (valid); save `@9` (refused, naming `@9`, listing valid tokens); `images <id> remove 1` refused; `--force` rewrites `@1` to `[image removed]`.

### Tests for User Story 2

- [X] T034 [P] [US2] Create `tests/test_refs.py` covering `parse_references`: `@1`, `@label`, `@@1` (escape, not a reference), `dev@example.com` (not a reference), `` `@1` `` in code span (not a reference), double-backtick span containing a backtick, fenced ``` block and ~~~ block (not references), fence closed by a shorter fence (block continues), `@01` (unknown), `@1x` (unknown), `@2label`-style purely digit-prefixed (unknown), `@` followed by space (not a reference), `@` at start of line, `@-x` (unknown), `@_x` (unknown)
- [X] T035 [P] [US2] Create `tests/test_refs_validate_rewrite.py`: `validate_references` names the first bad token and lists all valid ones (`@1, @2, @login-error`); `rewrite_references` renumbers `@3→@2` after removing `@2`; relabel `@login→@sign-in`; code and emails untouched by rewrite; removal with `--force` replaces the token with `[image removed]`; rewrite preserves surrounding text byte-for-byte
- [X] T036 [P] [US2] Create `tests/test_service_refs.py`: `set_notes` with an unknown reference leaves old notes intact; relabel of a referenced image without `force` raises `referenced_image` with the referencing tokens listed; with `force` the notes are rewritten and the change is in one transaction (monkeypatch a failure to confirm rollback); removing the last image leaves the report intact; indexes not reused after a removal
- [X] T037 [P] [US2] Extend `tests/test_cli_media.py` for `edit --note` with unknown reference (exit 1, message format from contracts/cli.md), `images <id> remove` refusal text, `--force` output with the count of rewritten references, and `show` resolution (`@1 (images/…)`, `@@1` printed as `@1`)

### Implementation for User Story 2

- [X] T038 [US2] Implement `parse_references(notes) -> list[Ref]` in `src/bugcap/refs.py` (Ref: token, start, end, kind in `index|label|escape|unknown`) using the masked text from T013 and the regex `@@|(?<![A-Za-z0-9._%+\-])@([A-Za-z0-9_\-]+)(?![A-Za-z0-9_\-])`; classify digits without leading zero as index, labels matching `^[A-Za-z][A-Za-z0-9_\-]*$` as label, else unknown
- [X] T039 [US2] Implement `validate_references(notes, media) -> None` in `src/bugcap/refs.py` raising `ServiceError(invalid_reference, token=..., valid=[...])` with the message format `unknown reference @3 in notes` and `valid references: @1, @2, @login-error`
- [X] T040 [US2] Implement `rewrite_references(notes, mapping: dict[str,str]) -> str` in `src/bugcap/refs.py`, operating only on `parse_references` results (keeps code, fences, emails, `@@` untouched); `[image removed]` for removal mappings
- [X] T041 [US2] Implement `service.relabel_media(store, report_id, ref, new_label, force=False)` and `service.remove_media(store, report_id, ref, force=False)` in `src/bugcap/service.py`: find referencing tokens in the report's notes, refuse with `referenced_image` (listing tokens) unless `force`, otherwise rewrite notes and update media (renumber later items only on remove), all in one transaction; return the number of rewritten references
- [X] T042 [US2] Make `service.set_notes` in `src/bugcap/service.py` call `refs.validate_references` against the current media before saving (all-or-nothing)
- [X] T043 [US2] In `cmd_capture` (`src/bugcap/cli.py`), validate `--note` after images are attached (so labels added in the same command are valid) and refuse the report with exit 1 if invalid; no report is left behind on refusal
- [X] T044 [US2] In `cmd_edit` (`src/bugcap/cli.py`), route `--note` through `service.set_notes`; print the `invalid_reference` message from T039 on exit 1
- [X] T045 [US2] In `cmd_attach` (`src/bugcap/cli.py`), validate the report's existing notes against the new media after attaching; if notes now reference missing labels, report it as a warning (not a refusal)
- [X] T046 [US2] Add `images <id> relabel <ref> <new-label> [--force]` and `images <id> remove <ref> [--force]` to `src/bugcap/cli.py` with `<ref>` = index or label; refusal prints the referencing notes and tokens and says to use `--force`; success prints the number of rewritten references
- [X] T047 [US2] Extend `cmd_show` in `src/bugcap/cli.py` to print each reference's resolved path beside the token (`@1 (images/…png)`) and print `@@` as `@`, without changing non-reference text
- [X] T048 [US2] Add `update_notes(store, id, notes)` to `src/bugcap/agent_api.py` and register the `update_notes` MCP tool in `src/bugcap/mcp_server.py` returning the error shape from contracts/mcp.md (`code: invalid_reference`, `token`, `valid`)
- [X] T049 [US2] Change `_commit_images` in `src/bugcap/sync.py` to iterate `report.media` (kind `image`) instead of `report.image_paths`, keeping output identical for legacy reports (verified by the existing `tests/test_github_sync.py`)
- [X] T050 [US2] In `src/bugcap/sync.py`, replace each reference token in the issue body and comments with the image markdown (`![label](url)`) or link used for that sync; unknown tokens are not sent (validated earlier)
- [X] T051 [US2] Extend `tests/test_github_sync.py` with a case where notes contain `@1` and `@login-error` and the synced body contains the permalinks in their place

**Checkpoint**: US2 independently testable. `pytest tests/test_refs*.py tests/test_service_refs.py` passes; quickstart §3 runs.

---

## Phase 5: User Story 5 - Report many bugs in a row from a floating control window (Priority: P2)

**Goal**: `bugcap live` opens an always-on-top control window; Start runs the existing capture backend, a details window saves the report, and the control window returns to ready.

**Independent Test**: Run `bugcap live`; capture and save two bugs in a row without typing another command; the counter reads `2 saved this session`; `bugcap list` shows both. Headless: `env -u DISPLAY -u WAYLAND_DISPLAY bugcap live` exits 3.

### Tests for User Story 5

- [X] T052 [P] [US5] Create `tests/test_live_session.py` for the pure state machine in `src/bugcap/live_session.py`: `READY→CAPTURING` on start; repeat start while `CAPTURING` or `DETAILS` ignored; `CAPTURING→DETAILS` on captured path; `CAPTURING→READY` on empty capture with a message; `DETAILS→READY` on save (counter +1) and on confirmed discard (draft removed); discard without confirmation keeps state; close with unsaved input yields `needs_confirm`; decline keeps window; confirm yields `save_draft`
- [X] T053 [P] [US5] Create `tests/test_drafts.py`: `save_draft(repo, png_path, fields)` writes `drafts/<uuid>.png` and `drafts/<uuid>.json` with the shape in data-model.md; `list_drafts(repo)` returns only that repo's drafts; `delete_draft` removes both files; a corrupt JSON sidecar is skipped with a warning, not fatal
- [X] T054 [P] [US5] Create `tests/test_cli_live_headless.py`: with `DISPLAY` and `WAYLAND_DISPLAY` unset on Linux, `bugcap live` exits 3 and prints the desktop-session message; with `tkinter` import blocked (monkeypatched `sys.modules['tkinter'] = None`), it exits 3 with the install hint

### Implementation for User Story 5

- [X] T055 [US5] Create `src/bugcap/live_session.py` with `LiveState` enum (`READY, CAPTURING, DETAILS`) and a `LiveSession` class exposing `start()`, `capture_done(path | None)`, `save(fields) -> Report`, `discard(confirmed: bool)`, `request_close(has_unsaved: bool)`, plus a `saved_count` counter; no Tk imports
- [X] T056 [US5] Implement `save(fields)` in `LiveSession` to call `service.create_report` with the screenshot as the first image (through `ingest.import_local`) and the repo tag of the launch directory; reject empty title with a message
- [X] T057 [US5] Create `src/bugcap/drafts.py` with `save_draft`, `list_drafts(repo)`, `delete_draft`, `load_draft` over `paths.drafts_dir()`, JSON sidecar per data-model.md
- [X] T058 [US5] Create `src/bugcap/live.py` (Tk shell): control window with Start button, counter label `N saved this session`, a status line; `root.attributes("-topmost", True)` in a try block, showing the one-line notice in `live` when it fails (FR-050)
- [X] T059 [US5] In `src/bugcap/live.py`, run `capture.capture_screenshot()` in a worker thread, pass the result through a `queue.Queue` polled with `root.after()`; disable Start while not `READY`; all Tk calls stay on the main thread
- [X] T060 [US5] In `src/bugcap/live.py`, build the details window (`tk.Toplevel`): screenshot preview (thumbnail via `PhotoImage` subsampling), title, notes (`@` errors from `refs.validate_references` shown inline and keep the window open), tags entry (comma-separated), status combobox (`STATUSES`, default `open`), read-only repo label, Save and Discard buttons; Discard asks for confirmation (`messagebox.askyesno`)
- [X] T061 [US5] In `src/bugcap/live.py`, handle window close: if details has unsaved input, ask to confirm; on confirm call `drafts.save_draft` and exit; on decline stay open
- [X] T062 [US5] In `src/bugcap/live.py`, on start list drafts for the current repo and offer restore or discard per draft; restore reopens the details window pre-filled and deletes the draft once saved
- [X] T063 [US5] Add headless check in `src/bugcap/live.py`: on Linux without `DISPLAY`/`WAYLAND_DISPLAY`, or when `import tkinter` fails, print the explanation (desktop session needed; `python3-tk` install hint) and return exit code 3 before creating any window
- [X] T064 [US5] Add `live` subcommand in `src/bugcap/cli.py` that calls `live.run()` and maps its return code
- [X] T065 [US5] Extend `cmd_setup` in `src/bugcap/cli.py` to report whether `tkinter` is importable, with a one-line install hint when it is not (line appended; existing output unchanged)

**Checkpoint**: US5 testable without a display (state machine, drafts, headless). Manual GUI run per quickstart §6.

---

## Phase 6: User Story 3 - Record the screen for a complex bug (Priority: P3)

**Goal**: `bugcap record` captures video, keyframes, or an animated file with per-OS recorder backends, duration/size caps, safe finalization, and GitHub-aware media sync.

**Independent Test**: With ffmpeg installed, `bugcap record --id <id> --format animated --max-seconds 10`, press Enter; a media item of kind `animated` is attached and the final size is printed. Without ffmpeg: exit 3 with guidance, no report created.

### Tests for User Story 3

- [X] T066 [P] [US3] Create `tests/test_recorder_argv.py` (mocked, no subprocess run): ffmpeg argv for Linux `x11grab` (`-f x11grab -framerate F -i $DISPLAY`), Windows `gdigrab` (`-f gdigrab -framerate F -i desktop`), macOS `avfoundation` (`-i "<index>:none"`); wf-recorder argv on Wayland (`-r F -f <out>`); video encodes with `-c:v libx264 -crf 30 -pix_fmt yuv420p`; webm alternative `libvpx-vp9`; duration cap `-t S`; animated two-pass palette filter (`palettegen`, `paletteuse`, width 960); frames extraction uses `fps=` and at most 8 keyframes
- [X] T067 [P] [US3] Create `tests/test_recorder_devices.py`: `parse_avfoundation_screen_index` on a captured sample of `ffmpeg -f avfoundation -list_devices true -i ""` output returns the `Capture screen 0` index; missing screen entry → error with guidance
- [X] T068 [P] [US3] Create `tests/test_recorder_run.py` with mocked `subprocess.Popen`: Enter on stdin → graceful `q` written to ffmpeg stdin and the process waited on; Ctrl+C → same path; wf-recorder stopped with SIGINT (signal sent through the mock); duration cap triggers stop with `reason='duration cap'`; size cap (file size polled from a fake path) triggers stop with `reason='size cap'`; empty or missing output after stop → no media attached, error returned; `diagnose_failure` on macOS stderr containing `Input/output error` returns the Screen Recording permission guidance; no recorder available → exit 3 path with install guidance and no report created
- [X] T069 [P] [US3] Create `tests/test_github_media_sync.py`: video and animated files uploaded/committed byte-for-byte as-is; frames committed as one ordered set (sorted by `frame_no`) with one commit; a file above `[sync] max_upload_mb` (default 25) is skipped with the exact warning text from contracts/cli.md and the rest of sync continues; references to skipped items remain as plain text with a note

### Implementation for User Story 3

- [X] T070 [US3] Create `src/bugcap/recorder.py` with `RecordBackend` dataclass and `RECORD_BACKENDS` list (`ffmpeg` for linux/macos/windows, `wf-recorder` for linux Wayland) kept **separate** from `backends.BACKENDS` so `backends.detect()` is unchanged
- [X] T071 [US3] Implement `detect_recorder(platform, env) -> RecordBackend | None` in `src/bugcap/recorder.py` (ffmpeg present on PATH; wf-recorder preferred on Linux when `WAYLAND_DISPLAY` is set and wf-recorder is on PATH)
- [X] T072 [US3] Implement pure `build_capture_argv(backend, platform, fmt, fps, max_seconds, out_path, display) -> list[str]` in `src/bugcap/recorder.py` covering the cases in T066
- [X] T073 [US3] Implement pure `build_postprocess_argv(fmt, in_path, out_path, fps, max_frames=8) -> list[str]` in `src/bugcap/recorder.py` for animated (palette two-pass, width 960, fps default 5) and frames extraction
- [X] T074 [US3] Implement `parse_avfoundation_screen_index(output: str) -> int` in `src/bugcap/recorder.py`
- [X] T075 [US3] Implement `run_recording(backend, fmt, fps, max_seconds, max_mb, out_path, wait_for_stop) -> RecordResult(path, size_bytes, reason)` in `src/bugcap/recorder.py`: `Popen` with stdin pipe; a stop thread reads Enter from stdin; `KeyboardInterrupt` handled; watchdogs for duration and size; graceful stop (`q` to ffmpeg, SIGINT to wf-recorder); always wait for exit; verify output non-empty; post-process for animated/frames
- [X] T076 [US3] Implement `diagnose_failure(stderr: str, platform: str) -> str | None` in `src/bugcap/recorder.py` returning the macOS Screen Recording guidance (System Settings → Privacy & Security → Screen Recording) and the Wayland guidance (install wf-recorder; x11grab cannot capture Wayland)
- [X] T077 [US3] Implement `service.add_recording(store, report_id | None, file, kind, mime, size_bytes, frame_paths=None, title=None, notes=None, tags=None)` in `src/bugcap/service.py`: creates a report when `report_id` is None (title default `Recording <timestamp>`), inserts a `media` row (kind `video`/`animated`) or a `frames` item with `media_frames` rows; `frames` `path` is NULL in `media`
- [X] T078 [US3] Add `record` subcommand to `src/bugcap/cli.py` with `--id`, `--format {video,frames,animated}` (default `animated`), `--max-seconds` (30), `--fps` (5 for animated, 30 for video), `--max-mb` (25), `--backend`, `--title`, `--note`, `--tag` (repeatable); print `recorded <S> s, <size> (<kind>), stopped: <reason>`; exit 3 with guidance when no recorder or permission is missing, creating no report
- [X] T079 [US3] Extend `cmd_setup` in `src/bugcap/cli.py` to list `RECORD_BACKENDS` (detected / install suggestion / guidance) after the existing capture output, leaving existing lines unchanged
- [X] T080 [US3] Extend `src/bugcap/sync.py` media handling: iterate kinds (`video`, `animated` uploaded as-is; `frames` committed as one set ordered by `frame_no`; `image` as before); size check against `config.get_sync_defaults()`/`[sync] max_upload_mb` (default 25) producing `warning: skipped media #<idx> <name> (<size>): above the 25 MB upload limit`
- [X] T081 [US3] Extend `show` in `src/bugcap/cli.py` and `get_report` in `src/bugcap/agent_api.py` to display frames (count, total size) and recordings (kind, size) using `service.get_report_view`

**Checkpoint**: US3 testable with mocked subprocess; the real capture is verified manually (quickstart §4).

---

## Phase 7: User Story 4 - Browse and act on bugs in a local dashboard (Priority: P4)

**Goal**: `bugcap dashboard` serves a 127.0.0.1-only UI, a JSON API over the same service layer, media served by row id with Range support, a per-process token for writes, and a responsive light/dark UI with no external requests.

**Independent Test**: `bugcap dashboard --port 8765`, filter by tag, open a report, see `@1` rendered inline and an animated item playing, change its status, confirm with `bugcap show`.

### Tests for User Story 4

- [X] T082 [P] [US4] Create `tests/test_dashboard_api.py` (in-process `ThreadingHTTPServer` on port 0): `GET /api/reports` filters by `repo`, repeatable `tag` (AND), `status`, `q` (title and notes, case-insensitive), `limit`/`offset`; invalid `status` → 400 `bad_query`; `GET /api/reports/<id>` returns `notes_segments` where `@1` is a `ref` segment with `media_id`, escaped `@@1` is text; 404 for unknown id
- [X] T083 [P] [US4] Create `tests/test_dashboard_mutations.py`: `POST /status`, `POST /tags`, `PUT /notes` succeed with the token; invalid reference → 422 with `token`/`valid` and stored notes unchanged; invalid status → 400
- [X] T084 [P] [US4] Create `tests/test_dashboard_security.py`: path traversal: a media row whose `path` is `../../etc/passwd` or an absolute path → 404 and the file is never opened (monkeypatch `open` to fail); symlink inside `images/` pointing outside → 404; `/media/<id>` takes no path segment (`/media/../x` → 404); CSRF: mutating request without `X-Bugcap-Token` → 403 `bad_token`; wrong token → 403; right token but `Origin: https://evil.example` → 403; `Host: evil.example` → 400 on GET and POST; `/api/session` returns a token only to same-origin GET; static route serves only `app.js`/`app.css`/`index.html` (`/static/../server.py` → 404)
- [X] T085 [P] [US4] Create `tests/test_dashboard_media.py`: `Content-Type` from stored mime; `Range: bytes=0-99` → 206 with correct `Content-Range` and 100-byte body; `bytes=100-` and `bytes=-50` → 206; unsatisfiable range → 416 with `Content-Range: bytes */<size>`; `frames` served at `/media/<id>/frames/<n>`; unknown `frame_no` → 404
- [X] T086 [P] [US4] Create `tests/test_cli_dashboard.py`: with no `--host` the server binds `127.0.0.1`; a non-loopback host (`0.0.0.0`) is refused unless `--host` is passed explicitly (`--host` given → warning text from contracts/cli.md is printed and the server starts); `--port 0` prints the chosen URL

### Implementation for User Story 4

- [X] T087 [US4] Create `src/bugcap/dashboard/__init__.py` (package marker, exports `serve`)
- [X] T088 [US4] Implement `service.list_reports_query(store, repo, tags, status, q, limit, offset) -> (total, items)` in `src/bugcap/service.py` with SQL/LIKE filtering and tag AND semantics; validation raises `bad_query`
- [X] T089 [US4] Implement `service.report_segments(notes, media) -> list[dict]` in `src/bugcap/service.py` using `refs.parse_references` to emit `{"text": ...}` and `{"ref": {...}}` segments (no HTML)
- [X] T090 [US4] Create `src/bugcap/dashboard/api.py` with handlers `list_reports`, `get_report`, `set_status`, `set_tags`, `set_notes`, each calling `service` functions and mapping `ServiceError.code` to HTTP status (`bad_query`/`invalid_status`/400, `bad_token`/403, `not_found`/404, `invalid_reference`/422); no business logic in this module
- [X] T091 [US4] Create `src/bugcap/dashboard/media.py` with `serve_media(handler, media_row, range_header)` implementing containment via `paths.resolve_data_path`, content type from `mime`, `Accept-Ranges`, `206`/`416` handling, `Cache-Control: private, max-age=3600`, and frames routing
- [X] T092 [US4] Create `src/bugcap/dashboard/server.py` with `ThreadingHTTPServer` subclass, `BaseHTTPRequestHandler` routing for `/`, `/static/*`, `/api/*`, `/media/*`; checks Host (`127.0.0.1:<port>` or `localhost:<port>`), Origin on mutating methods, `X-Bugcap-Token` (constant-time `hmac.compare_digest`) on `POST/PUT/PATCH/DELETE`; token from `secrets.token_urlsafe(32)` held in memory; security headers (`X-Content-Type-Options: nosniff`, CSP `default-src 'self'; media-src 'self' blob:`)
- [X] T093 [US4] In `src/bugcap/dashboard/server.py`, load static files only from an allowlist (`index.html`, `app.js`, `app.css`) via `importlib.resources.files("bugcap.dashboard") / "static"`; any other name → 404
- [X] T094 [US4] Implement `serve(host="127.0.0.1", port=8765, open_browser=False)` in `src/bugcap/dashboard/server.py`: refuses non-loopback hosts unless the caller passes `explicit_host=True`; prints the URL; `--port 0` resolves the bound port
- [X] T095 [US4] Create `src/bugcap/dashboard/static/index.html`: no external URLs, `<meta name="viewport">`, CSP meta matching T092, single column at phone width, list + detail views
- [X] T096 [US4] Create `src/bugcap/dashboard/static/app.css`: colours as CSS custom properties on `:root`, dark mode under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`; explicit `body` background; 16px gutter; no horizontal scroll at 360px; images `max-width:100%`
- [X] T097 [US4] Create `src/bugcap/dashboard/static/app.js`: fetches `/api/session` once and sends the token on mutations; renders notes from `notes_segments` with `textContent` only (no `innerHTML`); inline `<img>` for image refs; `<video controls>` for video; frames as ordered `<img>` list; `<img>` for animated; filter controls (repo, tag, status, text); status select, tag add/remove, notes editor showing server 422 messages
- [X] T098 [US4] Add `dashboard` subcommand to `src/bugcap/cli.py` with `--port` (default 8765), `--open`, `--host` (default `127.0.0.1`); non-loopback `--host` prints `warning: dashboard exposed on <H>; anyone on that network can read and edit your bugs`

**Checkpoint**: US4 testable through the API tests; UI verified manually per quickstart §5.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, regression sweep, and roadmap updates.

- [X] T099 Run the full suite `pytest -q` and fix any regression in `tests/test_regression_output.py`, `tests/test_cli_*.py`, `tests/test_github_*.py`
- [X] T100 [P] Update `README.md` with usage for `--image`/`--label`, `images`, `@` references, `record`, `live`, `dashboard`, and the new MCP tools
- [X] T101 [P] Update `README.md` architecture section: `service.py` as the shared layer, `ingest.py`, `refs.py`, `recorder.py`, `live.py`/`live_session.py`, `dashboard/`, schema v2
- [X] T102 [P] Tick the four Backlog items in `ROADMAP.md` (`[x]`) only after their phase checkpoints pass, and move them from the Backlog section into the numbered list with item numbers 10–13
- [X] T103 Run the migration check from quickstart §8 against `tests/fixtures/v1.db` and confirm no data loss by diffing `bugcap list --all` before and after
- [X] T104 Run every scenario in `quickstart.md` §2–§7 and record pass/fail in `specs/002-bugcap-backlog-features/quickstart.md` under a "Last run" line

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; blocks every story.
- **US1 (Phase 3)**: depends on Foundational. MVP.
- **US2 (Phase 4)**: depends on US1 (needs media and labels).
- **US5 (Phase 5)**: depends on US1 (screenshot becomes image 1) and US2 (inline `@` validation in the details window).
- **US3 (Phase 6)**: depends on Foundational and US1 (recordings are media items); independent of US2 except for `@` display.
- **US4 (Phase 7)**: depends on US1 and US2 (refs and media rendering); can run in parallel with US3 after US2.
- **Polish (Final)**: after the stories it documents.

### Story dependency graph

```text
Setup → Foundational → US1 (MVP) → US2 → US5
                                  ↘ US3 (can run alongside US2/US5)
                                  ↘ US2 → US4
```

### Within each story

Tests first (they fail), then models/services, then CLI/MCP/UI wiring, then the checkpoint.

### Parallel opportunities

- Setup: T002 and T003 (different files) in parallel.
- Foundational: T011, T013, T014 in parallel after T006–T010.
- US1 tests T015–T018 in parallel; implementation T019–T022 are in one file and run sequentially.
- US2 tests T034–T037 in parallel.
- US3 tests T066–T069 in parallel; `recorder.py` tasks T070–T076 are sequential (one file).
- US4 tests T082–T086 in parallel; `static/` tasks T095–T097 in parallel (separate files).
- Polish T100–T102 in parallel.

### Parallel example: US4 static UI

```text
Task: "Create src/bugcap/dashboard/static/index.html" (T095)
Task: "Create src/bugcap/dashboard/static/app.css" (T096)
Task: "Create src/bugcap/dashboard/static/app.js" (T097)
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 and Phase 2 (Setup, Foundational), including the v1→v2 migration test.
2. Phase 3 (US1): images via capture/attach, incl. URL and glob inputs.
3. Stop and validate with quickstart §2 and the Phase 3 checkpoint. This already delivers the core of the backlog's item 1 on every OS.

### Incremental delivery

1. MVP (US1), then US2 (`@` references and their GitHub sync).
2. US5 (live mode), the highest-value workflow for many reports.
3. US3 (recording), platform-dependent, so verify per OS.
4. US4 (dashboard), last because it reads everything above.
5. Polish, then tick ROADMAP.

### Notes

- Every checkbox line uses the format `- [ ] T### [P?] [US#?] Description with file path`.
- Commit after each task or logical group; stop at any checkpoint to validate independently.
- Do not change existing CLI output: the regression tests in T099 are the gate.

## Phase 8: Convergence

- [X] T105 Resolve the conflict between "index never reused" and renumber-on-remove: either keep a per-report high-water mark so `Store._next_index` never reuses an index (and drop later-item renumbering in `service.remove_media`, keeping `@n` stable), or amend FR-005/FR-016 to state that removal renumbers; update `tests/test_service_media.py`/`tests/test_service_refs.py` to match per FR-005 (contradicts) [HIGH]
- [X] T106 Enforce the URL content-type check in `ingest.download_url` (reject a response whose `Content-Type` is clearly non-image such as `text/html` before reading the body; keep magic-byte sniffing as the final authority) and add a case to `tests/test_ingest_url.py` per FR-003 (partial) [MEDIUM]
- [X] T107 Remove the intermediate recording and any partial output when `run_recording` post-processing fails (`recorder._run_checked` / `run_recording`), and when `cmd_record` is refused after recording (invalid `@` reference in `--note`, store error): delete the produced file or frames directory; add tests in `tests/test_recorder_run.py` and `tests/test_cli_record.py` per FR-024 and SC-002 (partial) [MEDIUM]
- [X] T108 Pre-fill the repo tag in the live details window's Tags field (`src/bugcap/live.py` `open_details`) instead of only adding it on save, keeping `LiveSession.save` de-duplication, per FR-043 (partial) [LOW]
- [X] T109 Verify GitHub's current direct-upload / contents-API file limit, then set `config.DEFAULT_MAX_UPLOAD_MB` and the warning text in `src/bugcap/sync.py` accordingly and note the source in `research.md`, per FR-027 (partial) [MEDIUM]
- [X] T110 Add a performance test creating 500 reports and asserting `service.list_reports_query` with repo, tag and text filters returns in under 5 s (`tests/test_dashboard_api.py`), per SC-006 (missing) [LOW]
- [X] T111 Add an ffmpeg-gated test (`pytest.mark.skipif` when ffmpeg is missing) that records a short synthetic source through `recorder.build_postprocess_argv` and checks the animated output is at most 5 MB for a 10 s default-settings clip and that `ffprobe` can open the video output, per SC-004 and SC-005 (missing) [LOW]
- [X] T112 Add a test that the dashboard's `static/index.html`, `app.css` and `app.js` define light and dark palettes and a viewport meta, and that no rule sets a fixed width over 360 px on `body`, per FR-036 (partial) [LOW]

## Phase 9: Convergence

- [X] T113 Make `recorder.run_recording` and `cmd_record` safe against interruption during finalization and an unwritable output folder: check the media directory is writable before starting the recorder (exit 1 with a clear message, nothing started), catch `KeyboardInterrupt` during `_stop_process` and post-processing, delete the raw/partial output and exit without attaching anything; add tests in `tests/test_recorder_run.py` and `tests/test_cli_record.py` per Edge Cases: unwritable output folder and interrupt during finalization (partial) [MEDIUM]
- [X] T114 Render the report's GitHub issue as a clickable link in the dashboard detail view: build `https://github.com/<slug>/issues/<n>` from `synced_refs["github.issue"]` in `dashboard/api.get_report` (e.g. a `links` field) and show it as an anchor in `static/app.js` (text via `textContent`, `rel="noopener noreferrer"`); add an API test in `tests/test_dashboard_api.py` per US4/AC4 (partial) [LOW]
- [X] T115 Reword the spec text that still assumes renumbering (`spec.md` User Story 2 scenario 9 and the "Index stability" assumption) to match the T105 decision (indexes are never reused or renumbered; forced removal only replaces references to the removed image), so spec, code and `data-model.md` agree, per FR-005 and FR-016 (contradicts) [LOW]
