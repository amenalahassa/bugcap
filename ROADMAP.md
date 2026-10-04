# Roadmap

Items are in priority order. Status: `[x]` done, `[~]` started (partial code, not wired in), `[ ]` not started.

- [x] Capture (flameshot/satty shell-out) + local SQLite store + CLI (`capture`, `list`, `show`)
- [x] 1. **Cross-OS support**: per-OS data/config dirs, macOS/Windows capture backends
      (`paths.py`, `capture.py`; `BUGCAP_HOME` override; tested)
- [x] 2. **Detect capture tool, suggest or install it** (`bugcap setup`): per-OS detection,
      install commands, manual guidance
- [x] 3. **System-wide install + per-repo `bugcap init`** with a tag (`.bugcap.toml`, GitHub slug
      auto-detected); store migrated to add a `repo` column with no data loss
- [x] 4. `bugcap edit <id>` / `bugcap tag <id>` for post-capture triage without re-shooting
- [x] 5. **GitHub pull**: `bugcap github pull` imports issues via `gh` (refreshing title/body only,
      preserving local notes/tags/status), then `--ask` offers a screenshot per issue;
      `bugcap attach <id>` adds images to an existing report
- [ ] 6. **Object store sync (S3/R2)**: *optional*, user-configured; uploads images/media and
      records remote keys. Presigned URLs expire (max 7 days), so permanent embeds need a public
      bucket or CDN base URL. Needs the optional `boto3` extra. *(deferred; the `Destination`
      seam in `sync.py` is in place for it)*
- [x] 7. **Agent prompting via MCP** (`bugcap mcp-serve`): built on the official `mcp` SDK
      (optional `bugcap[mcp]` extra, lazy-imported). Tools: `list_reports`, `get_report` (incl.
      image bytes), `request_screenshot` (asks the user to capture for a report/issue),
      `pull_issues`
- [x] 8. **GitHub push** (`bugcap sync <id> --to github`): `gh issue create --attach` for the
      human-facing inline image (feature-detected), comment on existing issues, **plus** a plain
      (non-LFS) commit of the same file into a **user-chosen** repo (`--images-repo`, `.bugcap.toml`
      `[sync]`, or global default) so any token-authenticated agent can read it back via the
      Contents API. Consent is asked per the images repo's visibility (every run if public, once if
      private). The repo-committed copy is kept; an S3/R2 store (6) is an optional extra, not a
      replacement.
- [ ] 9. Additional trackers (Linear, Jira, Trello) behind the same `Destination` interface *(deferred)*
- [x] 10. **Associate existing images to a bug**: `--image` (path, glob or URL) on `capture` and
      `attach`, plus `bugcap images`; validated by magic bytes and copied into the store; MCP
      `attach_image`
- [x] 11. **`@` references in notes** (`@1`, `@login-error`): validated on save, resolved in
      `show`, GitHub sync, MCP and the dashboard; relabel/remove rewrite them with `--force`
- [x] 12. **Screen recording** (`bugcap record`): ffmpeg / wf-recorder, video, keyframes or
      animated GIF, duration and size caps; `bugcap live` for rapid multi-report capture
- [x] 13. **Dashboard** (`bugcap dashboard`): local web UI over the same service layer,
      127.0.0.1 only by default
