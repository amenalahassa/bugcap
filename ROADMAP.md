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
