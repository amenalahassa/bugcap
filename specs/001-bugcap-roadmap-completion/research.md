# Research: Bugcap Roadmap Completion

## R1 — Hand-rolled JSON-RPC vs. official MCP SDK

**Decision (revised by user): use the official `mcp` Python SDK.** The earlier hand-rolled option was evaluated and rejected on maintainability grounds: the SDK tracks protocol changes, schema generation and error handling for us.

| | Hand-rolled (rejected) | Official `mcp` SDK (chosen) |
|---|---|---|
| Dependencies | none | pydantic, anyio, httpx, starlette, uvicorn, jsonschema, pyjwt, ... (heavy; `pywin32` on Windows) |
| Protocol drift | ours to track | SDK tracks the spec |
| Code | ~150 lines | ~40 lines of tool decorators |
| Blocking `request_screenshot` | trivial | async server; run the blocking capture in a worker thread (`anyio.to_thread.run_sync` / `asyncio.to_thread`) so the loop stays responsive |

**How we contain the cost of the heavy dependency:**
- Declared as an **optional extra**: `pip install 'bugcap[mcp]'` / `pipx install 'bugcap[mcp]'` / `uv tool install 'bugcap[mcp]'`. Core CLI stays stdlib-only (+`tomli` on <3.11), honoring the "avoid heavy dependencies" requirement.
- `mcp_server.py` imports the SDK lazily; `bugcap mcp-serve` without it exits 1 with: "The MCP server needs the 'mcp' extra: pipx install 'bugcap[mcp]' (or pipx inject bugcap mcp)".
- Tool implementations are plain functions in `bugcap/agent_api.py` (no SDK imports) that the SDK layer merely registers, so the logic is unit-testable without the SDK and the SDK can be swapped later.

**Version pin:** `mcp>=1.2,<2` (supports Python >=3.10; `mcp.server.fastmcp.FastMCP` with `Image` helper). `mcp` 2.x (latest 2.3.0, also Python >=3.10, depends on `mcp-types`, `httpx2`, `opentelemetry-api`) is a new major whose server API must be verified before widening the pin; this is an explicit task (T-verify-sdk) rather than an assumption.

**T-verify-sdk result (2026-10-04, Python 3.10.12):** `pip install 'bugcap[dev,mcp]'` into a clean venv resolved `mcp==1.30.0` (newest within the `<2` pin) along with `tomli==2.4.1` (the `python_version < '3.11'` marker fired correctly). `from mcp.server.fastmcp import FastMCP, Image` imports cleanly — the pin is valid. 2.x compatibility was not exercised; leaving the `<2` ceiling in place until a future task re-verifies the 2.x server API.

**Stdio hygiene:** SDK owns stdout; all our diagnostics and the user prompt for `request_screenshot` go to stderr. No `print()` to stdout inside tool code (enforced by a test that runs the server as a subprocess).

**Testing:** unit tests call `agent_api` functions directly; protocol tests use the SDK's in-memory client/server session (or a stdio subprocess client from `mcp.client.stdio`) for handshake, `tools/list`, `tools/call` (incl. image content). Tests are skipped with a clear reason if the extra isn't installed; CI installs `.[dev,mcp]`.

## R2 — Choosing where image copies are committed

**Need (from user):** the repo that receives committed image copies must be user-selectable, not forced to the issue repo.

**Decision:** resolution order, first hit wins:
1. `bugcap sync ... --images-repo owner/repo` (plus optional `--images-path`, `--images-branch`)
2. `.bugcap.toml` `[sync]` keys `images_repo`, `images_path`, `images_branch`
3. global `config.toml` `[sync]` same keys
4. the issue's target repo, path `bugcap-images/`, repo's default branch

`bugcap init` gains optional `--images-repo` to write the `[sync]` table. Rationale: teams often keep screenshots in a dedicated (private) assets repo to avoid bloating the code repo or exposing images publicly. FR-018a consent and visibility check apply to the **images repo**, not the issue repo. Issue bodies/comments link to the committed file via its permalink (`blob/<commit>/<path>`), which agents resolve through the Contents API (`repos/<images-repo>/contents/<path>?ref=<commit>`).

**Alternatives:** always same repo (rejected: user requirement); separate `bugcap images` command (rejected: more surface).

## R3 — Destination interface for future S3/R2 and trackers

`Destination` protocol (in `sync.py`): `name`, `ensure_ready()`, `repo_visibility(slug)`, `create_issue(title, body, attachments) -> IssueRef`, `comment(ref, body, attachments)`, `put_file(slug, path, bytes, branch, message) -> FileRef`. A future object store implements only a `BlobStore` slice (`put_file`/`public_url`); a Linear/Jira destination implements the issue slice. `sync_report()` depends only on this protocol and `synced_refs`; refs are namespaced `<destination>.<kind>` so destinations don't collide.

## R4 — Idempotency model

`synced_refs` (existing JSON dict of str→str) keys:
- `github.issue` = `owner/repo#N` (set by sync create **or** by pull)
- `github.comment_hash` = sha256 of the last synced (title, notes, image basenames); comment only when it differs
- `github.image.<basename>` = `owner/repo:path@commit`

Re-run logic: issue ref present → comment (only if hash changed); image ref present → skip upload. Partial failure leaves already-recorded refs, so re-run resumes. Existing-path-in-repo: GET contents first; identical content → record and skip; different content → new unique name (`<id>-<n>-<8-char hash>.png`). Pulled-issue lookup uses `github.issue` via a store query (`find_by_ref`).

## R5 — Issue creation with attached image

Installed `gh` (2.100) supports `gh issue create --attach FILE#alt` and `gh issue comment --attach`. Older `gh` does not. **Decision:** feature-detect via `gh issue create --help` containing `--attach`; use it when present (humans get native inline image), always also commit the plain copy (FR-018); when absent, embed the committed-file link in the body. If `--attach` partially fails, `gh` still prints the issue URL — parse it and record the issue so re-run comments instead of recreating.

## R6 — Calling `gh`

Always argv lists, `capture_output=True, text=True`; large JSON (base64 file contents) via `gh api --input -` on stdin. `ensure_ready()`: `shutil.which("gh")` → else error with per-OS install hint; `gh auth status` non-zero → error "run `gh auth login`". Repo visibility: `gh repo view SLUG --json visibility`; any failure → treated as public (ask every time). Pull: `gh issue list --repo SLUG --state open --label L --limit N --json number,title,body,url,state,labels`; PRs are excluded by `issue list` already.

## R7 — Store migration

`PRAGMA user_version`: 0 → existing DB (no `repo`, `body`); migration 1 runs `ALTER TABLE reports ADD COLUMN repo TEXT` and `ADD COLUMN body TEXT NOT NULL DEFAULT ''` if absent (inspect `PRAGMA table_info` so a half-migrated DB is safe), then sets `user_version=1`. Wrapped in a transaction; fresh DBs create the new schema directly. Legacy rows keep `repo=NULL`; they appear only under `list --all` when inside a repo (documented).

## R8 — Cross-OS specifics to verify

- `paths.py`: Linux data path stays `$XDG_DATA_HOME|~/.local/share/bugcap`; macOS `~/Library/Application Support/bugcap`; Windows `%LOCALAPPDATA%\bugcap` / config `%APPDATA%\bugcap`; `BUGCAP_HOME` → `<home>/data`, `<home>/config`.
- Windows capture: flameshot via winget/scoop/choco; **add a Snipping Tool/PowerShell fallback is out of scope**; `--image` import is the no-tool path.
- Desktop-UI detection (`has_display()`): Linux = `DISPLAY` or `WAYLAND_DISPLAY`; macOS/Windows = true unless `SSH_CONNECTION` set without a session (assume interactive). Used by `request_screenshot`.
- System-wide install: `pipx install .` / `uv tool install .` verified in quickstart (entry point `bugcap`, `tomli` marker resolves on 3.10).

## R9 — `request_screenshot` semantics

Params: `report_id` | `issue` (`owner/repo#N` or number using repo config) and optional `message` shown to the user. If a desktop UI exists, print the message to stderr, then call the capture flow (blocking, default timeout 300 s configurable), attach the image to the report (creating one from the issue if needed), return image content + text. If no UI: return `isError: false` with text `status: "non_interactive"` and no capture, so the agent can fall back. User cancel → `status: "cancelled"`.
