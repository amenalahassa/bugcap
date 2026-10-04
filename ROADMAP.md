# Roadmap

Items are in priority order. Status: `[x]` done, `[~]` started (partial code, not wired in), `[ ]` not started.

- [x] Capture (flameshot/satty shell-out) + local SQLite store + CLI (`capture`, `list`, `show`)
- [~] 1. **Cross-OS support**: per-OS data/config dirs, macOS/Windows capture backends
      (`paths.py`, `capture.py` rewritten; untested)
- [~] 2. **Detect capture tool, suggest or install it** (`bugcap setup`): per-OS detection,
      install commands, manual guidance (`backends.py` written; no CLI command yet)
- [~] 3. **System-wide install + per-repo `bugcap init`** with a tag (`.bugcap.toml`, GitHub slug
      auto-detected) (`repo.py`, `config.py`, `tomlio.py` written; store has no `repo` column yet)
- [ ] 4. `bugcap edit <id>` / `bugcap tag <id>` for post-capture triage without re-shooting
- [ ] 5. **GitHub pull**: `bugcap github pull` imports issues via `gh`, then asks whether to add
      a screenshot to each; `bugcap attach <id>` adds images to an existing report
- [ ] 6. **Object store sync (S3/R2)**: *optional*, user-configured; uploads images/media and
      records remote keys. Presigned URLs expire (max 7 days), so permanent embeds need a public
      bucket or CDN base URL. Needs the optional `boto3` extra. *(deferred)*
- [ ] 7. **Agent prompting via MCP** (`bugcap mcp-serve`): `list`/`get` (incl. image bytes),
      `request_screenshot` (agent asks the user to capture for a report/issue), `pull_issues`
- [ ] 8. **GitHub push** (`bugcap sync <id> --to github`): `gh issue create --attach` for the
      human-facing inline image, comment on existing issues, **plus** a plain (non-LFS) commit of
      the same file into the repo so any token-authenticated agent can read it back via the
      Contents API. The repo-committed copy is kept; an S3/R2 store (6) is an optional extra,
      not a replacement.
- [ ] 9. Additional trackers (Linear, Jira, Trello) behind the same adapter interface *(deferred)*

## Backlog (unprioritized)

- [ ] **Associate existing images to a bug**: from a local file, a path, or a URL (downloaded into
      the store), on `capture`, `attach`, or later via `bugcap attach <id> --image <path|url>`
- [ ] **Reference specific images from the notes with `@`**: e.g. `@1` or `@login-error` in notes
      resolves to that report's image (images get a stable index and optional label); validated on
      save, rendered inline in `show`, the dashboard and synced issues
- [ ] **Screen recording for complex bugs**: record the screen and store the result, by user
      choice, as either a video (mp4/webm) or a short burst of frames / animated image
      (GIF/APNG/WebP) for more efficient storage. Needs a per-OS recorder backend (detect/install
      like capture backends) and a size/duration cap
- [ ] **Dashboard (web app)**: `bugcap dashboard` starts a local web UI to browse, filter (repo,
      tag, status) and open bugs with their images/recordings and `@` references; local-only by
      default (binds to 127.0.0.1)
