---

description: "Task list for Bugcap Roadmap Completion"
---

# Tasks: Bugcap Roadmap Completion

**Input**: Design documents from `/specs/001-bugcap-roadmap-completion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/mcp.md, quickstart.md

**Tests**: Requested by FR-024. Test tasks are written first within each story and MUST fail before the implementation tasks.

**Organization**: Grouped by user story (US1 = P1 ... US5 = P5). Paths are relative to repo root. Existing WIP modules (`paths.py`, `capture.py`, `backends.py`, `repo.py`, `config.py`, `tomlio.py`) are finished and wired in, not rewritten.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1..US5; omitted in Setup, Foundational and Polish

---

## Phase 1: Setup

- [X] T001 Update `pyproject.toml`: add `dependencies = ["tomli>=2; python_version < '3.11'"]`, `[project.optional-dependencies]` `mcp = ["mcp>=1.2,<2"]` and `dev = ["pytest>=7"]`, `[tool.pytest.ini_options] testpaths = ["tests"]`
- [X] T002 [P] Create `tests/conftest.py` with fixtures: `bugcap_home` (sets `BUGCAP_HOME` to `tmp_path`, clears `XDG_*`), `git_repo` (tmp git repo with optional `origin`), `fake_gh` (monkeypatches `subprocess.run`/`shutil.which` for `gh` calls and records argv/stdin)
- [X] T003 [P] Verify the installed `mcp` SDK against the pin: in a scratch venv, `pip install 'mcp>=1.2,<2'` on Python 3.10, confirm `from mcp.server.fastmcp import FastMCP, Image` works and note whether 2.x server API is compatible; record the result in `specs/001-bugcap-roadmap-completion/research.md` under R1 (T-verify-sdk)

---

## Phase 2: Foundational (blocks all user stories)

- [X] T004 [P] Write `tests/test_paths.py`: Linux default `$XDG_DATA_HOME|~/.local/share/bugcap` is unchanged (backward compat), macOS `~/Library/Application Support/bugcap`, Windows `%LOCALAPPDATA%\bugcap` data and `%APPDATA%\bugcap` config (monkeypatch `sys.platform` and env), `BUGCAP_HOME` -> `<home>/data` and `<home>/config`
- [X] T005 [P] Write `tests/test_store_migration.py`: build a legacy DB (schema without `repo`/`body`, `user_version` 0) with rows, open via `Store`, assert rows intact, columns `repo TEXT NULL` and `body TEXT NOT NULL DEFAULT ''` exist, `PRAGMA user_version == 1`; second open is a no-op; half-migrated DB (only `repo` present) migrates without error; fresh DB gets new schema
- [X] T006 Finish `src/bugcap/paths.py` so T004 passes (no POSIX-only calls; keep directory creation)
- [X] T007 Implement migration in `src/bugcap/store.py`: `PRAGMA user_version`-based `_migrate()` in one transaction, inspecting `PRAGMA table_info(reports)` before `ALTER TABLE reports ADD COLUMN repo TEXT` and `ADD COLUMN body TEXT NOT NULL DEFAULT ''`; update `SCHEMA` and `Report` dataclass with `repo: Optional[str] = None` and `body: str = ""`
- [X] T008 Extend `src/bugcap/store.py` API: `add(..., repo=None, body="")`, `list(repo=None)` (filter when given, all when None), `update(id, *, title=None, notes=None, status=None, body=None)`, `set_tags(id, tags)`, `add_image(id, path)`, `set_ref(id, key, value)`, `find_by_ref(key, value) -> Optional[Report]`; constraints verbatim from data-model.md: "title non-empty", "tags trimmed, case-preserved, unique, order-preserving", "status in {open, in-progress, resolved, closed, wontfix} for `edit --status` (free text from legacy rows tolerated on read)"
- [X] T009 [P] Write `tests/test_repo_config.py`: `init_repo` default tag = directory name, GitHub slug detected from SSH (`git@github.com:o/r.git`) and HTTPS (`https://github.com/o/r`) origins, non-GitHub/no origin -> `github` unset, `--tag`/`--github` override, `.bugcap.toml` discovered from a subdirectory via `find_config`, `[sync]` table (`images_repo`, `images_path`, `images_branch`) round-trips, `tomlio` quoting of special characters
- [X] T010 Finish `src/bugcap/repo.py` and `src/bugcap/tomlio.py`: add `[sync]` read/write to `RepoConfig` (`images_repo`, `images_path`, `images_branch`), `init_repo(..., images_repo=None, force=False)` refusing to overwrite an existing `.bugcap.toml` unless forced; make T009 pass
- [X] T011 [P] Write `tests/test_backends.py`: with monkeypatched `sys.platform` and `shutil.which` assert `platform_key`, `detect()` order (flameshot preferred), `recommended()` per OS, `install_command()` picks the first available package manager and adds `sudo` only on non-root POSIX (no `geteuid` on Windows), returns None when no manager, `guidance()` per OS
- [X] T012 Finish `src/bugcap/backends.py` (and fix `recommended()` redundant branch) so T011 passes
- [X] T013 Add `has_display()` to `src/bugcap/capture.py` (Linux: `DISPLAY` or `WAYLAND_DISPLAY`; macOS/Windows: True) plus a `tests/test_capture.py` covering `import_image` (missing file error, suffix kept, copy lands in images dir), `capture_screenshot` per backend with mocked `subprocess.run` (flameshot, satty, screencapture, no backend -> `CaptureError` mentioning `bugcap setup`)
- [X] T014 Add shared CLI helpers in `src/bugcap/cli.py`: `current_repo()` (via `repo.load_repo_config`), `resolve_report(id)` returning an error message and exit 1 for unknown ids ("error: no report with id N")

**Checkpoint**: store, paths, repo config, backends are tested and green.

---

## Phase 3: User Story 1 - Install, setup, init, scoped capture (Priority: P1) MVP

**Goal**: install once, ensure a capture tool exists, init a repo, capture/import tagged reports, `list` scoped to the repo.

**Independent Test**: on a machine with no capture tool run `setup`, `init` in a git repo, `capture --image`, then verify `list` scoping and `list --all`.

### Tests for US1

- [X] T015 [P] [US1] `tests/test_cli_setup.py`: `setup` with detected tool prints it and runs nothing; no tool + package manager -> prompt (answer "n" installs nothing, "y" runs the argv), `--yes` installs without prompt, non-TTY without `--yes` prints the command and exits 1, no package manager prints manual guidance
- [X] T016 [P] [US1] `tests/test_cli_init_capture_list.py`: `init` writes `.bugcap.toml` (tag defaults to repo name, slug from origin, `--tag`/`--github`/`--images-repo` overrides, existing file refused without `--force`); `capture --image` inside repo stores repo tag + `repo`; outside repo behavior identical to before; `list` in repo filters, `list --all` shows all, legacy `repo IS NULL` rows only under `--all`; `BUGCAP_HOME` respected

### Implementation for US1

- [X] T017 [US1] Implement `cmd_setup` and parser in `src/bugcap/cli.py` per contracts/cli.md (prompt `Install <tool>? [y/N]`, `--yes`, uses `backends.install_command`, exit 0 when a backend exists/installed else 1)
- [X] T018 [US1] Implement `cmd_init` in `src/bugcap/cli.py` (git root else cwd, `--tag`, `--github`, `--images-repo`, `--force`) using `repo.init_repo`
- [X] T019 [US1] Update `cmd_capture` in `src/bugcap/cli.py`: add `--image PATH` (uses `capture.import_image`, skips backend), auto-apply repo tag (deduplicated with `--tag`) and `repo` key from `RepoConfig.key`; leave output text unchanged
- [X] T020 [US1] Update `cmd_list`/`cmd_show` in `src/bugcap/cli.py`: `list --all`, filter to `repo == RepoConfig.key` inside an initialized repo, `show` prints a `repo:` line only when set
- [X] T021 [US1] Add system-wide install docs to `README.md` (`pipx install .`, `uv tool install .`, extras `'.[mcp]'`) and verify per quickstart step 1 on this machine with `pipx`/`uv` if available; note results in `specs/001-bugcap-roadmap-completion/quickstart.md`

**Checkpoint**: US1 fully usable; run T015/T016.

---

## Phase 4: User Story 2 - Triage after capture (Priority: P2)

**Goal**: edit report fields and tags without re-shooting.

**Independent Test**: capture, `edit`, `tag add/remove`, `show`.

- [X] T022 [P] [US2] `tests/test_cli_triage.py`: `edit` changes only supplied fields; no flags -> usage error exit 2; invalid status rejected with the allowed set; empty title rejected; `tag add` twice is idempotent and reported; `tag remove` of absent tag harmless; unknown id -> "not found", exit 1
- [X] T023 [US2] Implement `cmd_edit` and `cmd_tag` in `src/bugcap/cli.py` using `Store.update`/`Store.set_tags`; print what changed

**Checkpoint**: US2 independently verifiable.

---

## Phase 5: User Story 3 - GitHub pull and attach (Priority: P3)

**Goal**: import issues via `gh`, idempotently; add screenshots to existing reports.

**Independent Test**: mocked `gh`, run pull twice, then `--ask` and `attach`.

- [X] T024 [P] [US3] `tests/test_ghcli.py`: `ensure_ready` errors when `gh` missing (per-OS install hint) and when `gh auth status` fails ("Run `gh auth login`"); argv lists only (no shell strings); `list_issues` parses `--json` output; `repo_visibility` failure -> treated as "public"
- [X] T025 [P] [US3] `tests/test_github_pull.py`: first pull creates reports with `github.issue = owner/repo#N`, `body`, status from issue state; second pull -> `unchanged`/`updated`, no duplicates; refresh updates `title` and `body` only and never `notes`, `tags`, or `status` (clarification Q2); `--label`, `--limit`, `--repo` forwarded to `gh`; `--ask` prompts per issue and attaches given path or skips; missing/unauthenticated gh exits 1 with the message
- [X] T026 [P] [US3] `tests/test_cli_attach.py`: `attach ID --image PATH` appends image; without `--image` calls capture backend; unknown id error; no backend + no `--image` -> guidance error
- [X] T027 [US3] Create `src/bugcap/ghcli.py`: `GhError`, `ensure_ready()`, `run_gh(args, stdin=None)` (argv list, text mode), `list_issues(slug, labels, limit)`, `repo_visibility(slug)` (`gh repo view SLUG --json visibility`; failure -> "public"), `supports_attach()` (feature-detect `--attach` in `gh issue create --help`), `create_issue`, `comment_issue`, `get_contents`, `put_contents` (JSON via `gh api --input -` on stdin, never argv)
- [X] T028 [US3] Implement `pull_issues(slug, labels, limit, ask_cb)` in `src/bugcap/sync.py` returning `{created, updated, unchanged}`; match via `Store.find_by_ref("github.issue", ...)`; set `status` only on creation; refresh `title`/`body` only
- [X] T029 [US3] Implement `cmd_github_pull` (nested subparser `github pull`) and `cmd_attach` in `src/bugcap/cli.py`; slug from `--repo` else `.bugcap.toml`; `--ask` prompt `Add a screenshot? [y/N/path]`; friendly `GhError` -> stderr, exit 1

**Checkpoint**: US3 independent of US4/US5.

---

## Phase 6: User Story 4 - Push reports to GitHub (Priority: P4)

**Goal**: create/comment issues and commit plain image copies to a user-chosen repo, idempotently, with consent rules.

**Independent Test**: mocked `gh`, sync twice, check one issue, one image commit, refs recorded.

- [X] T030 [P] [US4] `tests/test_github_sync.py`: new report -> issue created (with `--attach` when supported, else body links to committed file), image committed via contents PUT (base64 over stdin), `github.issue`, `github.image.<basename>` (`owner/repo:path@commit`), `github.comment_hash` recorded; linked report -> comment not new issue; rerun -> zero gh write calls; changed notes -> exactly one new comment; partial failure (put_contents fails) then rerun resumes without duplicate issue; `--attach` partial failure still records issue URL printed by `gh`; existing identical path -> skip, different content -> unique `<id>-<n>-<8-char hash>` name
- [X] T031 [P] [US4] `tests/test_sync_consent.py`: public images repo -> prompt every run, decline skips image commit but issue/comment proceed; private repo -> prompt first time only, consent saved to global config `[consent] images_repos`; visibility unknown -> treated as public; non-interactive without `--yes`/consent -> skip image commit with message; `--yes` accepts; images repo resolution order flag > `.bugcap.toml [sync]` > global `[sync]` > issue repo with default path `bugcap-images`
- [X] T032 [US4] Extend `src/bugcap/config.py` with `get_sync_defaults()` and `consent_has(slug)`/`consent_add(slug)` using comma-separated `consent.images_repos` (tomlio is flat); leave S3 `KNOWN_KEYS` untouched
- [X] T033 [US4] In `src/bugcap/sync.py` define `Destination` protocol (`name`, `ensure_ready`, `repo_visibility`, `create_issue`, `comment`, `put_file`), `IssueRef`/`FileRef` dataclasses, `GitHubDestination` wrapping `ghcli`, and `resolve_images_target(flag, repo_cfg, global_cfg, issue_slug)`
- [X] T034 [US4] Implement `sync_report(store, report, destination, opts)` in `src/bugcap/sync.py`: consent gate (FR-018a), commit images first (record each ref immediately), create-or-comment with permalink/`--attach`, content-hash comment idempotency per data-model.md synced_refs keys; each step persisted immediately for resume
- [X] T035 [US4] Implement `cmd_sync` in `src/bugcap/cli.py`: `sync ID --to github [--repo] [--images-repo] [--images-path] [--images-branch] [--yes]`; prints issue URL and image permalinks; `--to` choices registry-driven so new destinations plug in

**Checkpoint**: US4 independent of US5.

---

## Phase 7: User Story 5 - Agent access via MCP (Priority: P5)

**Goal**: official-SDK stdio MCP server exposing four tools.

**Independent Test**: SDK stdio client performs handshake, lists tools, calls each (incl. image content).

- [X] T036 [P] [US5] `tests/test_agent_api.py` (no SDK needed): `list_reports` repo scoping/`all`/`status`/`limit`; `get_report` returns metadata plus image bytes+mime per image and error for unknown id; `request_screenshot` returns `non_interactive` when `has_display()` False, `captured` (attaches image, creates report from issue when `issue` given), `cancelled` on `CaptureError`; `pull_issues` summary
- [X] T037 [P] [US5] `tests/test_mcp.py` (`pytest.importorskip("mcp")`): via SDK client over stdio subprocess `bugcap mcp-serve` with `BUGCAP_HOME` temp: `initialize` returns `serverInfo.name == "bugcap"` with tools capability, `tools/list` has exactly the four tools with schemas, `get_report` result contains an `image` content block, nothing but protocol on stdout, running without the extra prints the install hint and exits 1 (simulate via blocked import)
- [X] T038 [US5] Create `src/bugcap/agent_api.py` with SDK-free functions `list_reports`, `get_report`, `request_screenshot` (prompt/message to stderr; `timeout_seconds` default 300 enforced around the blocking capture), `pull_issues`
- [X] T039 [US5] Create `src/bugcap/mcp_server.py`: lazy `from mcp.server.fastmcp import FastMCP, Image`; on `ImportError` raise a friendly error ("The MCP server needs the 'mcp' extra: pipx install 'bugcap[mcp]' (or pipx inject bugcap mcp)"); register the four tools from `agent_api`, run blocking `request_screenshot` in a worker thread; `get_report` returns `Image(...)` content per image; `run()` uses stdio
- [X] T040 [US5] Add `mcp-serve` subcommand in `src/bugcap/cli.py` (exit 1 with hint when SDK missing); document the Claude Code snippets from contracts/mcp.md in `README.md`

---

## Phase 8: Polish & Cross-Cutting

- [X] T041 [P] Update `README.md`: status, usage for every new command, architecture section (module map, `Destination` seam for roadmap items 6/9, `synced_refs` keys), cross-OS notes, extras
- [X] T042 [P] Update `ROADMAP.md`: mark items 1-5, 7, 8 `[x]`; keep 6 and 9 deferred; adjust item 7/8 notes (SDK, `--images-repo`)
- [X] T043 Run the full `pytest` suite on Python 3.10 (and 3.11+ if available) with `.[dev,mcp]`; fix failures
- [X] T044 Walk through every step in `specs/001-bugcap-roadmap-completion/quickstart.md` (real `gh` only where authenticated; else rely on mocked tests) and note any deviations
- [X] T045 Regression check: confirm `capture`/`list`/`show` output outside an initialized repo is byte-identical to the previous commit's behavior (compare against `git stash`-free run of the previous revision with a scratch `BUGCAP_HOME`)
- [X] T046 [P] Grep for POSIX-only calls (`geteuid`, `fcntl`, hard-coded `/`-paths, `shell=True`) in `src/` and confirm each is guarded or absent

---

## Dependencies & Execution Order

- Phase 1 -> Phase 2 (blocks everything) -> stories.
- **US1** (P1) needs Phase 2 only. **US2** needs US1's CLI scaffolding for repo scoping but its logic (T008) is foundational, so it can start after Phase 2. **US3** needs T027 (ghcli) and T008; **US4** needs US3's `ghcli.py` (T027) and `sync.py` scaffold (T028 creates the file; coordinate); **US5** needs `pull_issues` (T028) and capture flow (T013, T019).
- Within a story: tests first (must fail) -> implementation.
- `src/bugcap/cli.py` is touched by US1-US5; those tasks are sequential across stories (no [P] between them). `src/bugcap/sync.py` is shared by T028, T033, T034: do in that order.

## Parallel Examples

- Phase 2: T004, T005, T009, T011 (separate test files) in parallel; then T006, T010, T012 in parallel (different modules).
- US3: T024, T025, T026 in parallel.
- US4: T030, T031 in parallel.
- US5: T036, T037 in parallel; T038 before T039.
- Polish: T041, T042, T046 in parallel.

## Implementation Strategy

- **MVP = Phase 1 + 2 + US1** (cross-OS install, setup, init, scoped capture/list). Stop and validate via quickstart steps 1-6.
- Then add US2 (small), US3, US4, US5 incrementally; each is independently demonstrable and the suite stays green at every checkpoint.
- Out of scope (do not build): S3/R2 object store (roadmap 6) and other trackers (roadmap 9); only the `Destination` seam is delivered.
