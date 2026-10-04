# Research: Bugcap Backlog Features

No NEEDS CLARIFICATION markers existed in the spec, so this phase resolves the technical choices the spec left open. Each entry: decision, rationale, alternatives.

## 1. URL download (Story 1)

- **Decision**: `urllib.request` with a custom opener: `timeout=20`, streamed read capped at 25 MB (abort when exceeded), maximum 5 redirects, redirect targets must be http/https, a fixed User-Agent, and **no** `Authorization`, cookies or proxy credentials added by bugcap.
- **Rationale**: Stdlib only (FR-039); streaming lets the size cap stop a large download early instead of after buffering it.
- **Alternatives**: `requests`/`httpx` (new dependency, rejected); `curl` shell-out (not portable to Windows defaults).

## 2. Image validation (Story 1)

- **Decision**: Validate by magic bytes: PNG `\x89PNG\r\n\x1a\n`; JPEG `\xff\xd8\xff`; GIF `GIF87a`/`GIF89a`; WebP `RIFF????WEBP`. The content-type header is only a hint, and the file extension is ignored for acceptance.
- **Rationale**: Reliable without Pillow, which would add a native dependency. Extension and header can lie (spec edge case).
- **Alternatives**: Pillow `Image.open().verify()` (stronger, but a heavy dependency); extension-only (rejected by spec).

## 3. Glob resolution

- **Decision**: `glob.glob(pattern, recursive=False)`, sorted by name; directories and non-images are skipped with a reason; a pattern with no match is an error naming the pattern. URL inputs are not globbed.
- **Rationale**: Matches shell expectations; sorting gives the "sorted filename order" the spec requires.

## 4. Stored media layout and path safety

- **Decision**: The DB stores paths **relative to the data directory** (`images/<uuid>.png`, `media/<uuid>.mp4`). Every read resolves against the data dir and checks that `realpath` stays inside `images/` or `media/`.
- **Rationale**: Relative paths survive moving the data directory and are cross-OS (FR-002, Story 1 cross-OS requirement). Containment check is the single point of truth for path traversal (FR-033).
- **Alternatives**: Absolute paths (break on move); storing bare filenames without a directory (loses the kind mapping).

## 5. Schema migration (v1 → v2)

- **Decision**: `PRAGMA user_version` 1 → 2 in one transaction: `CREATE TABLE media (...)` with `UNIQUE(report_id, idx)` and a partial unique index on `(report_id, label) WHERE label IS NOT NULL`; then for each report, parse `image_paths` JSON and insert rows `idx = 1..n`, `kind = 'image'`, `path = <old path made data-relative when it lies under images/>`, `source = NULL`. The legacy `image_paths` column is **left in place and never written again**; `Report.image_paths` is derived from `media` for compatibility.
- **Rationale**: Idempotent and row-preserving (spec: no data loss). Leaving the column means a downgrade or a read of an old row still works (spec: keep image_paths readable).
- **Edge**: Old absolute paths that point outside `images/` are kept as-is, flagged `kind='image'` with a `legacy` marker in `source`, and served only if they still pass containment (otherwise shown as missing in `show`).
- **Alternatives**: Dropping the column (loses the fallback); rewriting JSON in place (cannot enforce indexes).

## 6. `@` reference parsing (Story 2)

- **Decision**:
  1. Remove fenced blocks (```` ``` ```` or `~~~`, matched by fence length) and inline code spans (matched by backtick run length), replacing them with same-length spaces so positions stay valid.
  2. Scan with one regex: `@@` (escape, yields literal `@`) **or** `(?<![A-Za-z0-9._%+\-])@([A-Za-z0-9_\-]+)(?![A-Za-z0-9_\-])`. The lookbehind excludes emails (`dev@example.com`).
  3. Classify the captured token: all digits and no leading zero → index; otherwise must match `[A-Za-z][A-Za-z0-9_\-]*` → label; anything else (`@01`, `@1x`, `@2`-style labels that are purely numeric) → unknown token.
  4. Validation error lists the bad token and the valid choices (`@1`, `@2`, `@login-error`).
- **Rationale**: Single pass, deterministic, positions preserved for rewrite. Covers every edge case listed in the spec.
- **Alternatives**: Markdown parser library (dependency); naive regex without code masking (wrongly validates code).

## 7. Reference rewrite on relabel/remove (Story 2)

- **Decision**: Build a map `old_token → new_token` (renumber: `@3 → @2` after removing `@2`; relabel: `@login → @sign-in`). Apply only to reference tokens found by the same scanner (code and emails untouched). Removal with `--force` replaces the token with `[image removed]`.
- **Rationale**: The spec says "replaced by their plain text" for removal; `[image removed]` keeps the sentence readable and visibly marks the loss. This is a choice to confirm (noted in Assumptions of the plan, not a clarification marker).
- **Alternatives**: Plain `2` (ambiguous); deleting the whole sentence (destructive).

## 8. Recording backends and command construction (Story 3)

- **Decision**: A separate `RECORD_BACKENDS` list in `recorder.py` (not mixed into capture `BACKENDS`, so `detect()` never picks ffmpeg for screenshots). Argv builders are pure functions of (backend, platform, format, fps, max_seconds, output path, display info):
  - **ffmpeg, Linux X11**: `-f x11grab -framerate F -i $DISPLAY`
  - **ffmpeg, Windows**: `-f gdigrab -framerate F -i desktop`
  - **ffmpeg, macOS**: `-f avfoundation -framerate F -i "<screen index>:none"`; the screen index is discovered from `ffmpeg -f avfoundation -list_devices true -i ""` ("Capture screen N").
  - **wf-recorder (Wayland)**: `wf-recorder -r F -f out.mp4`, stopped with SIGINT, which finalizes the file.
  - Duration cap: `-t S` (ffmpeg) or a timer that sends the stop signal.
  - Video: `-c:v libx264 -preset veryfast -crf 30 -pix_fmt yuv420p` (mp4); webm alternative `-c:v libvpx-vp9 -crf 40 -b:v 0`.
  - Frames: record to a temporary mp4, then extract at most N keyframes (default 8, ~1 per second) with `-vf fps=…,scale=960:-2` to `frame_%02d.png`.
  - Animated: two-pass palette GIF (`palettegen`, `paletteuse`), scale 960 px wide, fps default 5, or animated WebP when `-c:v libwebp` is available.
- **Rationale**: Pure argv builders are testable with a mocked `subprocess` (spec quality requirement). Keeping recorders separate avoids changing capture detection (existing behaviour, FR-038).
- **Stop handling**: On Enter (stdin readline) or Ctrl+C, send `q` to ffmpeg's stdin (graceful finalize) on all OSes, and SIGINT to wf-recorder. Always wait for the process, then verify the file with `ffprobe` (if present) or a non-zero size; a failed finalize is reported and not attached.
- **Permissions**: macOS — if ffmpeg exits with an avfoundation "Input/output error" or produces no frames, print how to grant Screen Recording to the terminal (System Settings → Privacy & Security → Screen Recording). Linux Wayland without wf-recorder — guidance to install it and to note that ffmpeg x11grab cannot capture Wayland.
- **Alternatives**: Bundling a recorder (rejected, large); OBS (manual, not scriptable); Python screen-grab libraries (dependency).

## 9. GitHub size limits (Story 3)

- **Decision**: Warning threshold 25 MB per file (configurable in `[sync] max_upload_mb`); absolute ceiling 100 MB (GitHub's per-file limit for committed content). Files over the threshold are skipped with a warning naming the file and size; sync continues. Frames are uploaded as an ordered set (one commit, sorted names).
- **Rationale**: Matches the spec assumption; never silent (FR-027).
- **Note**: Verify the exact issue-attachment limit when implementing; the threshold is configurable so it can be corrected without code changes.

## 10. Dashboard server (Story 4)

- **Decision**: `http.server.ThreadingHTTPServer` with a handler class; static files read from the package (`importlib.resources`), with a fixed allowlist of names. Loopback: default host `127.0.0.1`; any other `--host` refused unless passed explicitly, then a warning is printed.
- **Rationale**: Stdlib, no Node build (spec). Threading handles the page plus media Range requests concurrently.
- **Alternatives**: `asyncio` framework (more code); Flask (dependency).

## 11. Dashboard CSRF and DNS-rebinding defense (Story 4)

- **Decision**:
  - Per-process token `secrets.token_urlsafe(32)`, held in memory only.
  - `GET /api/session` returns `{token}`; it is a read, so other pages can't use it, because a cross-origin response is unreadable without CORS (none is granted).
  - Every `POST/PATCH/PUT/DELETE` requires header `X-Bugcap-Token` matching the token (constant-time compare); requests without it get 403.
  - Every request checks `Host` is `127.0.0.1:<port>` or `localhost:<port>`; any mutating request with an `Origin` header must equal that origin. This blocks DNS rebinding and forms posted from other sites.
- **Rationale**: Token alone stops CSRF; Host/Origin checks also stop rebinding, which a token fetched from the same origin would otherwise defeat.
- **Alternatives**: Cookies with SameSite (more state, still needs Origin checks); no token (rejected by spec).

## 12. Media serving (Story 4)

- **Decision**: Media routes take the **media row id**, not a path: `GET /media/<id>`. The server resolves the stored relative path, checks containment in `images/` or `media/`, and streams it. Content type from the stored `mime` (set at ingest/record time). `Range: bytes=a-b` honoured with `206` and `Accept-Ranges: bytes`; invalid ranges get `416`.
- **Rationale**: Clients never supply a filesystem path, which removes the traversal surface; containment check remains as defense in depth and is tested with tampered rows.
- **Alternatives**: `/media/<path>` (larger attack surface).

## 13. Live mode GUI (Story 5)

- **Decision**: `tkinter` (stdlib). Control window: `attributes("-topmost", True)`; if setting topmost fails or the platform is Wayland without support, show a one-line notice. Capture runs in a worker thread (`capture.capture_screenshot()` blocks), and the result is passed to the Tk thread through a `queue.Queue` polled with `after()`. All Tk calls stay on the main thread.
- **State machine** (`live_session.py`, pure): `READY → CAPTURING → DETAILS → READY`, with `CAPTURING → READY` on empty capture, `DETAILS → READY` on save or discard, and a `closing` guard that asks before dropping drafts. The GUI only renders the state and forwards events, so the transitions are unit-tested without a display.
- **Drafts**: Unsaved captures are copied to `drafts/<uuid>.png` plus a JSON sidecar (fields, repo). On the next `bugcap live` in the same repo, drafts are offered for restore or discard.
- **Headless**: If `DISPLAY`/`WAYLAND_DISPLAY` is missing on Linux, or Tk cannot open a display, exit with an explanation (FR-051).
- **Alternatives**: Qt/PySide (heavy dependency); web-based floating page (cannot be always-on-top); terminal UI (not a floating window).
- **Risk**: `python3-tk` is not always installed on Linux. `bugcap setup` should detect and suggest it; `live` prints the install hint when `import tkinter` fails.

## 14. Shared service layer (FR-032)

- **Decision**: `service.py` exposes plain functions taking a `Store` and returning dataclasses or raising `ServiceError(code, message, details)`. The CLI maps errors to exit codes and stderr text; MCP maps them to JSON error results; the dashboard maps `code` to HTTP status (400 validation, 403 token, 404 not found, 409 conflict such as a referenced-image refusal). Validation codes: `invalid_reference`, `duplicate_label`, `referenced_image`, `invalid_image`, `too_large`, `not_found`.
- **Rationale**: One place for every rule; the error codes make the refusal (for example, "referenced; use --force") consistent across interfaces.

## 15. Notes save semantics (Story 2)

- **Decision**: All-or-nothing: `service.set_notes` parses references against the report's current media before writing; any invalid token refuses the save. The same call is used by `capture`, `edit`, `attach` (when attaching adds labels that new notes may reference, validation runs after the media change, in one transaction), MCP, and the dashboard.
- **Rationale**: Matches the spec assumption and keeps every interface identical.

## GitHub file-size limits (checked 2026-10-04)

Sources: GitHub Docs "Attaching files" and "Repository limits"; REST "Repository contents".

- Issue/PR attachments: 10 MB for images and GIFs, 10 MB for videos (free plan) or 100 MB (paid), 25 MB for other files. This applies only to the single `gh issue create --attach` image.
- Files bugcap commits through the Contents API (all media): GitHub recommends 1 MB per file and blocks pushes of files over 100 MB; the Contents API returns content inline only up to 1 MB.

Decision: `[sync] max_upload_mb` defaults to **25** (a conservative warning threshold, below the 100 MB hard block, matching the URL download cap) and is clamped to at most **100**. Items above it are skipped with a warning and sync continues.

## Decision update: no renumbering (T105)

FR-005 (never reused) and FR-016 (references keep pointing at the same image) are both satisfied by never renumbering: a per-report high-water mark (`reports.media_seq`) feeds the next index. `remove --force` replaces references to the removed image with `[image removed]`; all other tokens stay valid.
