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
   read-only MCP server (planned, see Roadmap) exposes the same store to agents that aren't
   running on the same filesystem context.
4. **Sync when ready**: push a report to a real tracker on your own schedule. The GitHub adapter
   (planned, see Roadmap) both attaches the image the normal way (so humans get the usual inline
   image in their browser) **and** commits a plain copy of the file into the repo, so any agent —
   yours or a teammate's — can read the same bytes back via `gh api repos/<owner>/<repo>/contents/
   <path>`, sidestepping the CDN's browser-only restriction entirely.

The result: one capture step, a durable local record, and a sync step that's a deliberate choice
rather than a one-way trip into a format your tools can't see.

## Status

Early scaffold. Implemented so far: capture, local SQLite-backed store, and a CLI
(`capture` / `list` / `show`). Sync adapters and the MCP server are designed but not yet built —
see [Roadmap](#roadmap).

## Installation

Requires Python >= 3.10 and a capture backend installed on your system:

- Linux (Wayland): [`satty`](https://github.com/Satty-org/Satty)
- Linux (X11) / cross-platform: [`flameshot`](https://flameshot.org/)

```bash
pipx install .
# or, for local development:
pip install -e .
```

`bugcap` auto-detects whichever backend (`satty` or `flameshot`) is on your `PATH`; if both are
present, `flameshot` is preferred for its built-in save-to-path behavior.

## Usage

```bash
# Capture a screenshot, annotate it in the backend's UI, then describe the bug.
bugcap capture --title "Dashboard empty after module creation" \
                --note "Created Activity Tracking module, dashboard shows no widgets" \
                --tag ui --tag dashboard

# List all local reports.
bugcap list

# Show one report's full detail (metadata + resolved image paths).
bugcap show <id>
```

Reports are stored under `$XDG_DATA_HOME/bugcap` (default `~/.local/share/bugcap`):

```
~/.local/share/bugcap/
├── bugcap.db          # SQLite index: metadata, tags, status, sync refs
└── images/
    └── <uuid>.png      # one file per captured screenshot
```

Nothing here talks to a tracker yet — this is intentionally just the local capture + store layer.

## Architecture

```
┌──────────────┐     ┌───────────────────┐     ┌────────────────────────┐
│  capture.py   │ --> │   store.py (SQLite) │ --> │  cli.py (capture/list/  │
│ (flameshot/   │     │  reports table:      │     │  show)                   │
│  satty shell) │     │  id, created_at,     │     └────────────────────────┘
└──────────────┘     │  image_paths, title,  │
                       │  notes, tags, status, │     ┌────────────────────────┐
                       │  synced_refs (JSON)   │ <-- │  (planned) mcp_server.py │
                       └───────────────────┘     │  read-only MCP over the  │
                                                     │  same store              │
                                                     └────────────────────────┘
                                                     ┌────────────────────────┐
                                                     │  (planned) sync/github.py│
                                                     │  gh issue create --attach │
                                                     │  + commit raw copy        │
                                                     └────────────────────────┘
```

The store is the one shared surface. Capture writes to it; the CLI reads/writes it; the (planned)
MCP server and sync adapters only ever read/update it too — nothing talks directly to a tracker
except the sync layer, and nothing requires a tracker to exist at all for capture to be useful.

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
