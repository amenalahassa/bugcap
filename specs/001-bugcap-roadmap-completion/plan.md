# Implementation Plan: Bugcap Roadmap Completion

**Branch**: `001-bugcap-roadmap-completion` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-bugcap-roadmap-completion/spec.md`, plus planning direction: explain hand-rolled JSON-RPC vs official MCP SDK, and let the user choose which repo receives committed image copies.

## Summary

Finish and wire in the existing WIP modules (`paths`, `capture`, `backends`, `repo`, `config`, `tomlio`) and add: a store migration (`repo`, `body` columns), triage commands (`edit`, `tag`), `attach`, a `gh`-based GitHub layer (pull + sync) behind a small `Destination` interface, and a stdio MCP server. Core stays standard library only (plus `tomli` on Python <3.11). MCP uses the **official `mcp` SDK** as an optional extra (decision and trade-offs in [research.md](research.md) R1). Image copies are committed to a **user-chosen repo** (flag > `.bugcap.toml` > global config > the issue's own repo; R2).

## Technical Context

**Language/Version**: Python >=3.10 (dev machine 3.10.12)

**Primary Dependencies**: core is stdlib only + `tomli` for <3.11 (marker in `pyproject.toml`); `gh` CLI at runtime for GitHub features; official `mcp` SDK (`mcp>=1.2,<2`) as optional extra `bugcap[mcp]`

**Storage**: SQLite (`bugcap.db`, versioned via `PRAGMA user_version`) + image files on disk; per-OS dirs via `paths.py`; global `config.toml`; per-repo `.bugcap.toml`

**Testing**: pytest (new dev extra); `BUGCAP_HOME` + `tmp_path` isolation; `gh`/`shutil.which`/`sys.platform` monkeypatched; tool logic tested directly; MCP protocol tested via the SDK client (in-memory or stdio subprocess), skipped if extra missing

**Target Platform**: Linux, macOS, Windows

**Project Type**: single-package CLI (`src/bugcap`)

**Performance Goals**: CLI commands feel instant (<200 ms excluding network/UI); MCP `get_report` returns in one request

**Constraints**: no POSIX-only calls (e.g. `os.geteuid` already guarded); no shell string execution (argv lists only); large payloads to `gh api` via stdin, not argv (Windows ~32k limit); existing `capture`/`list`/`show` output unchanged outside initialized repos

**Scale/Scope**: single user, thousands of reports at most

## Constitution Check

`.specify/memory/constitution.md` is still the unfilled template, so there are no ratified gates. Self-imposed principles applied: minimal dependencies, test-first for new modules, CLI text in/out with errors on stderr and non-zero exit. **Result: pass (no violations).** Re-check after design: still pass.

## Project Structure

### Documentation (this feature)

```text
specs/001-bugcap-roadmap-completion/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   └── mcp.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
src/bugcap/
├── paths.py        # existing: finish, test
├── capture.py      # existing: add has_display(), attach flow helper
├── backends.py     # existing: finish, test
├── repo.py         # existing: add [sync] keys, load/save of images_repo/path/branch
├── config.py       # existing: repurposed for [consent]/[sync] defaults (S3 keys stay, unused until roadmap 6)
├── tomlio.py       # existing: tomli marker dep
├── store.py        # migrate(): user_version, repo/body columns; update/tags/find_by_ref/upsert APIs
├── ghcli.py        # NEW: gh wrapper (ensure_ready, issues, create/comment, repo visibility, contents PUT/GET)
├── sync.py         # NEW: Destination protocol, GitHubDestination, sync_report() orchestrator, pull_issues()
├── agent_api.py    # NEW: SDK-free tool implementations (list/get/request_screenshot/pull)
├── mcp_server.py   # NEW: lazy-imports `mcp` SDK (FastMCP), registers agent_api tools, stdio run
└── cli.py          # new subcommands: setup, init, edit, tag, attach, github pull, sync, mcp-serve; list --all

tests/
├── conftest.py     # BUGCAP_HOME isolation, fake gh
├── test_store_migration.py
├── test_paths.py
├── test_repo_config.py
├── test_backends.py
├── test_cli_triage.py
├── test_github_pull.py
├── test_github_sync.py
└── test_mcp.py
```

**Structure Decision**: single-package layout kept. Network/remote concerns are isolated in `ghcli.py` (transport) and `sync.py` (policy + `Destination` interface) so roadmap items 6 and 9 add a new `Destination` implementation (and, for an object store, a `BlobStore` implementation) without touching commands or the store.

## Key Design Decisions

1. **MCP**: official `mcp` SDK over stdio, optional extra, lazy import with a clear install hint (R1). Tool logic lives in SDK-free `agent_api.py`; blocking capture runs in a worker thread.
2. **Image-copy repo is selectable** (R2): `bugcap sync --images-repo owner/repo [--images-path DIR] [--images-branch B]`, persisted optionally in `.bugcap.toml` `[sync]`. Consent (FR-018a) is keyed by the *images* repo.
3. **Destination interface** (R3): `ensure_ready()`, `visibility(repo)`, `create_issue`, `comment`, `put_file`; GitHub is the only implementation now.
4. **Pull ownership rule** (from clarification): pull writes `title` and `body` (remote-owned); `notes`, `tags`, `status` are local-owned, `status` set only on first import.
5. **Idempotency via `synced_refs`** flat string keys (R4) — no schema change needed for sync state.
6. **gh `--attach`** is used when the installed `gh` supports it (feature-detected); otherwise the issue body embeds the committed image link (R5).

## Complexity Tracking

No constitution violations; table not needed.
