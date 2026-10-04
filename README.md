# bugcap

**A local-first, agent-readable bug capture tool.** Snap an annotated screenshot of whatever's
broken, jot down what you saw, and keep a plain, local record of it — images and all — that any
AI coding agent on your machine can actually read, and that you can later push to whichever issue
tracker the project uses (GitHub first).

## Why this exists

Reviewing a desktop app for bugs usually produces two disconnected things: a screenshot (saved
somewhere, annotated or not) and a mental note of what was wrong. By the time you write the issue,
context is lost, and once the screenshot is attached to the issue, most trackers make it
*actively unreadable by an API token* — GitHub's `user-attachments` CDN, for example, only
resolves for a real browser session; no personal access token, OAuth app, or GitHub App token can
fetch it. That means an AI agent helping you triage bugs (via `gh` CLI or the REST API) can see the
issue text but never the picture — exactly the thing that usually explains the bug.

`bugcap` fixes the workflow end to end:

1. **Capture + annotate** at the moment you see the bug (shells out to `flameshot`/`satty` — no
   annotation UI reinvented here).
2. **Store locally**, as plain files: a SQLite index plus PNGs on disk, independent of any
   tracker. This is the system of record. Nothing about it depends on GitHub, Jira, Linear, or
   any other service being reachable or even chosen yet.
3. **Hand to any agent**: because the store is just local files, any agent with filesystem access
   (Claude Code, Cursor, etc.) can read a report's screenshot directly — no CDN, no auth dance. A
   stdio MCP server (`bugcap mcp-serve`) exposes the same store to agents, including the image
   bytes.
4. **Sync when ready**: push a report to a real tracker on your own schedule. The GitHub adapter
   both attaches the image the normal way (so humans get the usual inline image in their browser)
   **and** commits a plain copy of the file into a repo you choose, so any agent — yours or a
   teammate's — can read the same bytes back via `gh api repos/<owner>/<repo>/contents/<path>`,
   sidestepping the CDN's browser-only restriction entirely.

The result: one capture step, a durable local record, and a sync step that's a deliberate choice
rather than a one-way trip into a format your tools can't see.

## Status

Working. Roadmap items 1–5, 7 and 8 are implemented and tested (cross-OS paths, `setup`, per-repo
`init`, scoped capture/list, triage, GitHub pull/attach, GitHub push/sync, and the MCP server).
Items 6 (S3/R2 object store) and 9 (other trackers) are deferred, but the `Destination` seam is in
place so they slot in without touching existing commands.

## Installation

Requires Python >= 3.10. The core CLI is standard-library only (plus `tomli` on Python < 3.11);
the MCP server is an optional extra.

```bash
# System-wide (recommended):
pipx install .            # core CLI
pipx install '.[mcp]'     # core CLI + MCP server
# or with uv:
uv tool install '.[mcp]'
# for local development:
pip install -e '.[dev,mcp]'
```

Then make sure a capture tool is available for your OS:

```bash
bugcap setup              # reports the detected tool, or recommends one
bugcap setup --yes        # also installs it via your package manager (no prompt)
```

Supported capture backends: [`flameshot`](https://flameshot.org/) (cross-platform, recommended),
[`satty`](https://github.com/Satty-org/Satty) + `grim` (Linux/Wayland), and `screencapture`
(macOS built-in). If no tool is available you can always import an existing image with
`bugcap capture --image PATH`.

## Usage

```bash
# One-time, inside a project repo: scope captures to this repo (tag + GitHub slug auto-detected).
bugcap init                         # or: bugcap init --tag myproj --github owner/repo
bugcap init --images-repo owner/assets   # optionally pin where synced image copies are committed

# Capture (or import) a screenshot, annotate it, then describe the bug.
bugcap capture --title "Dashboard empty after module creation" \
                --note "Created Activity Tracking module, dashboard shows no widgets" \
                --tag ui
bugcap capture --image ./shot.png --title "Broken" --note "no capture tool needed"

# Images: attach existing files, globs or URLs (validated, copied into the store), with labels.
bugcap capture --image ./a.png --label login-error --title "Login fails" --note "See @1 and @login-error"
bugcap attach <id> --image './shots/*.png' --image https://ci.example.com/run/42.png --label after-fix
bugcap images <id>                              # index, label, kind, size
bugcap images <id> relabel login-error sign-in  # refused while notes reference it, unless --force
bugcap images <id> remove 2 --force             # rewrites @ references (removed ones: [image removed])

# Record the screen (needs ffmpeg, or wf-recorder on Wayland): animated GIF (default), video, or keyframes.
bugcap record --id <id> --format animated --max-seconds 10   # Enter or Ctrl+C stops early

# Report many bugs in a row from a small always-on-top window (needs tkinter and a desktop session).
bugcap live

# Browse, filter and triage in a local web page (127.0.0.1 only; --host exposes it on purpose).
bugcap dashboard --port 8765 --open

# List reports (current repo only inside an initialized repo; everything with --all) and show one.
bugcap list
bugcap list --all
bugcap show <id>

# Triage after capture, without re-shooting.
bugcap edit <id> --status resolved --note "fixed in #42"
bugcap tag <id> add ui
bugcap tag <id> remove ui

# GitHub: pull issues in as reports (idempotent), optionally asking to add a screenshot per issue.
bugcap github pull --repo owner/repo --label bug --limit 20 --ask
bugcap attach <id> --image ./shot.png      # add an image to any report

# GitHub: push a report — create/comment an issue AND commit a plain image copy agents can read.
bugcap sync <id> --to github --images-repo owner/assets --yes

# Run the MCP server (needs the 'mcp' extra) so coding agents can read/request reports.
bugcap mcp-serve
```

**`@` references.** In notes, `@1` (image index) or `@login-error` (label) points at that report's
image or recording. They are checked when notes are saved (`capture --note`, `edit --note`, MCP
`update_notes`, the dashboard): an unknown one is refused and the valid ones are listed. `@@`
writes a literal `@`; code spans, fenced blocks and email addresses are never references. `show`
resolves them, and `sync` replaces them with image/links in the GitHub issue. Relabelling or
removing a referenced image needs `--force`, which rewrites the notes in the same transaction.

Media over `[sync] max_upload_mb` (default 25) is skipped on `sync` with a warning.

Statuses accepted by `edit --status`: `open`, `in-progress`, `resolved`, `closed`, `wontfix`
(free-text values from older databases are tolerated on read).

### Where data lives (per-OS)

| Platform | Data (`bugcap.db`, `images/`) | Config (`config.toml`) |
|---|---|---|
| Linux | `$XDG_DATA_HOME/bugcap` (default `~/.local/share/bugcap`) | `$XDG_CONFIG_HOME/bugcap` (default `~/.config/bugcap`) |
| macOS | `~/Library/Application Support/bugcap` | same as data |
| Windows | `%LOCALAPPDATA%\bugcap` | `%APPDATA%\bugcap` |

Set `BUGCAP_HOME` to override both (`$BUGCAP_HOME/data` and `$BUGCAP_HOME/config`). The historic
Linux location is unchanged, so existing databases keep working; they are migrated in place
(a `repo` and `body` column are added) with no data loss.

### Using it from Claude Code (MCP)

Requires the extra (`pipx install 'bugcap[mcp]'` or `uv tool install 'bugcap[mcp]'`):

```bash
claude mcp add bugcap -- bugcap mcp-serve
```

or in `.mcp.json`:

```json
{ "mcpServers": { "bugcap": { "command": "bugcap", "args": ["mcp-serve"] } } }
```

The server exposes six tools: `list_reports`, `get_report` (returns the image bytes as image
content, plus media metadata and resolved `@` references), `request_screenshot` (asks you to
capture for a report or issue; returns immediately when there is no desktop UI), `pull_issues`,
`attach_image` (paths, globs or URLs, with optional labels) and `update_notes` (validated `@`
references; errors come back as JSON with a `code`).

## Architecture

Module map (`src/bugcap/`):

| Module | Responsibility |
|---|---|
| `paths.py` | Per-OS data/config dirs; `BUGCAP_HOME` override. |
| `capture.py` | Import or capture images (`flameshot`/`satty`+`grim`/`screencapture`); `has_display()`. |
| `backends.py` | Capture-tool detection, per-OS install commands, manual guidance. |
| `store.py` | SQLite store (`reports`, `media`, `media_frames`; schema v2), `PRAGMA user_version` migrations, report API, `transaction()`. |
| `service.py` | **Shared rules** used by the CLI, MCP, dashboard and live mode: media add/relabel/remove, notes validation, reference rewrite, queries. Raises `ServiceError`. |
| `ingest.py` | Path/glob/URL inputs: magic-byte validation, size/timeout/redirect limits, atomic copy into `images/`. |
| `refs.py` | `@` reference parsing (code/email aware), validation, rewrite, display. |
| `recorder.py` | `ffmpeg`/`wf-recorder` argv per OS, stop/caps watchdogs, animated/frames post-processing. |
| `live.py` + `live_session.py` + `drafts.py` | Tk control window (thin) over a pure state machine; drafts on disk. |
| `dashboard/` | `http.server` UI + JSON API (loopback, Host/Origin checks, write token, Range media, static allowlist). |
| `repo.py` + `tomlio.py` | `.bugcap.toml` discovery/read/write (tag, github slug, `[sync]`). |
| `config.py` | Global `config.toml`: `[sync]` defaults and `[consent]` for image commits. |
| `ghcli.py` | Thin `gh` wrapper (argv lists; large payloads via stdin). **Transport.** |
| `sync.py` | `Destination` protocol, `GitHubDestination`, `pull_issues`, `sync_report`. **Policy.** |
| `agent_api.py` | SDK-free tool logic for the six MCP tools. |
| `mcp_server.py` | Lazy-imports the `mcp` SDK; registers the `agent_api` tools over stdio. |
| `cli.py` | All subcommands. |

The **store is the one shared surface**. Capture writes to it; the CLI, the MCP server, and the
sync layer only read/update it — nothing talks to a tracker except `sync.py` (via `ghcli.py`), and
nothing requires a tracker to exist for capture to be useful.

**Extension seam (roadmap 6 & 9):** `sync.py` depends only on the small `Destination` protocol
(`ensure_ready`, `repo_visibility`, `get_file`, `put_file`, `create_issue`, `comment`,
`supports_attach`) and on the report's `synced_refs`. A future object store or tracker implements
that protocol — the CLI and store don't change. Refs are namespaced per destination:

- `github.issue` → `owner/repo#N`
- `github.comment_hash` → sha256 of the last synced content (so re-sync comments only on change)
- `github.image.<basename>` / `github.media.<basename>` → `owner/repo:path@commit` (so each file is committed at most once)
- `github.frame.<idx>.<n>` and `github.frames.<idx>` → keyframes of a recording (one commit per frame; GitHub's contents API commits one file at a time)

These refs also make pull and sync **idempotent and resumable**: each step is persisted as it
succeeds, so a re-run skips what is already recorded.

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Design notes / deliberate non-goals

- **No cloud storage by default, no vendor account.** The store is plain files on your disk. Sync
  (GitHub, and optionally an S3/R2 object store) is opt-in and explicit, per report.
- **Not a GitHub attachment replacement.** The CDN-attached image stays for humans browsing the
  issue normally; the repo-committed copy exists purely so agents can read it. Both are written
  on sync, deliberately redundant.
- **Not using Git LFS for synced copies.** GitHub's Contents API returns LFS pointer files, not
  the real bytes, for LFS-tracked paths — which would silently defeat the entire point of
  committing the copy. Plain commits are used instead; if screenshot volume ever outgrows that,
  the right next step is an external object store with its own token-authable download URLs, not
  LFS.
- **Annotation UI is not reinvented.** `bugcap` is glue around an existing capture/annotate tool,
  not a new one.

## License

MIT — see [LICENSE](LICENSE).
