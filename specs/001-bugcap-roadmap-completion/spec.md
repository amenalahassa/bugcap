# Feature Specification: Bugcap Roadmap Completion (Cross-OS, Setup, Repo Scoping, Triage, GitHub, Agent Access)

**Feature Branch**: `001-bugcap-roadmap-completion`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Complete bugcap roadmap items 1, 2, 3, 4, 5, 7 and 8 (see ROADMAP.md) as one feature. Items 6 (S3/R2 object store) and 9 (other trackers) are out of scope, but the design must not block adding them later."

## Clarifications

### Session 2026-10-04

- Q: When `bugcap sync` is about to commit screenshots into a GitHub repo, should it ask for confirmation first if that repo is public? → A: Ask for confirmation before committing image copies: every time for a public repo, and only the first time for a private repo (consent remembered per repo).
- Q: When `bugcap github pull` re-imports an issue whose report was edited locally, which side wins? → A: Pull refreshes title and body from the issue but never touches local notes, tags, or a locally changed status.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Install once, capture on any OS, scoped to a repo (Priority: P1)

A developer installs bugcap system-wide on Linux, macOS or Windows, runs `bugcap setup` to make sure a screenshot tool is available, runs `bugcap init` inside a project repo, and from then on captures bugs that are automatically tagged with that repo. `bugcap list` shows only the current repo's reports unless `--all` is given.

**Why this priority**: This is the foundation. Every other story depends on bugcap working on the user's OS and knowing which repo a report belongs to.

**Independent Test**: On a machine with no capture tool, run `setup`, follow guidance (or confirm install), run `init` in a git repo, capture (or import an image), and verify the report carries the repo tag and appears in `list` only from inside that repo.

**Acceptance Scenarios**:

1. **Given** a supported OS with a capture tool present, **When** the user runs `bugcap setup`, **Then** the detected tool is reported and nothing is installed.
2. **Given** no capture tool and a detected package manager, **When** the user runs `bugcap setup`, **Then** a recommended tool for the OS is shown and installed only after explicit confirmation or `--yes`.
3. **Given** no capture tool and no package manager, **When** the user runs `bugcap setup`, **Then** manual installation guidance for that OS is printed and nothing is changed.
4. **Given** no capture tool, **When** the user runs `bugcap capture --image PATH`, **Then** the image is imported as a report.
5. **Given** a git repo with an `origin` remote, **When** the user runs `bugcap init`, **Then** a `.bugcap.toml` is written with tag defaulting to the repo name and the GitHub `owner/repo` auto-detected; `--tag` and `--github` override these.
6. **Given** an initialized repo, **When** the user captures inside it, **Then** the report gets the repo's tag and a `repo` field; running `bugcap list` there shows only that repo's reports, and `bugcap list --all` shows everything.
7. **Given** an existing database created before this feature, **When** bugcap runs, **Then** existing reports remain intact and are upgraded to support the repo field without data loss.
8. **Given** `BUGCAP_HOME` is set, **When** any command runs, **Then** data and config live under that location; on Linux without it, the existing data location continues to be used.

---

### User Story 2 - Triage reports after capture (Priority: P2)

A user fixes a mistake in a report (title, notes, status) or adds/removes tags without re-capturing the screenshot.

**Why this priority**: Small, high-value, and independent of any network integration.

**Independent Test**: Capture a report, edit its title/notes/status, add and remove a tag, then `show` it and verify the changes.

**Acceptance Scenarios**:

1. **Given** an existing report, **When** the user runs `bugcap edit <id>` with new title, notes and/or status, **Then** only the supplied fields change and `show` reflects them.
2. **Given** a report, **When** the user runs `bugcap tag <id> add X` then `remove X`, **Then** the tag appears then disappears; adding an existing tag or removing an absent one is harmless and reported.
3. **Given** an unknown id, **When** either command runs, **Then** a clear "not found" error is shown with a non-zero exit.

---

### User Story 3 - Pull GitHub issues and attach screenshots (Priority: P3)

A user pulls issues from a GitHub repo (via the `gh` command-line tool) into bugcap as reports, optionally being asked per issue whether to add a screenshot, and can attach a screenshot to any existing report later.

**Why this priority**: Brings existing bug backlogs into the local workflow; builds on stories 1–2.

**Independent Test**: With a mocked/real `gh`, run `github pull` twice; verify reports are created once and not duplicated; run with `--ask` and supply an image for one issue.

**Acceptance Scenarios**:

1. **Given** a repo with open issues, **When** the user runs `bugcap github pull` (optionally `--repo`, `--label`, `--limit`), **Then** each matching issue becomes a report linked to the issue.
2. **Given** issues already pulled, **When** the command runs again, **Then** existing reports are updated in place (title and body refreshed from the issue) and no duplicates are created; local notes, tags and locally changed status are preserved.
3. **Given** `--ask`, **When** each issue is processed, **Then** the user is prompted whether to add a screenshot and may skip.
4. **Given** an existing report, **When** the user runs `bugcap attach <id> [--image PATH]`, **Then** a screenshot (captured, or imported from PATH) is added to it.
5. **Given** `gh` is not installed or not authenticated, **When** any GitHub command runs, **Then** a clear message explains the problem and how to fix it, with a non-zero exit.

---

### User Story 4 - Push reports to GitHub (Priority: P4)

A user runs `bugcap sync <id> --to github` to create a GitHub issue (with the screenshot visible to humans), or comment on the already-linked issue, and have a plain copy of each image committed into the target repo so automated agents can read it back through the repository contents interface.

**Why this priority**: Closes the loop with GitHub; depends on repo config and attach.

**Independent Test**: Sync a report with an image twice with a mocked `gh`; verify one issue, one committed image per screenshot, recorded references, and no duplicates on re-run.

**Acceptance Scenarios**:

1. **Given** an unlinked report with images, **When** synced to GitHub, **Then** an issue is created with the image attached where the platform allows, a plain (non-LFS) copy of each image is committed to the repo, and the issue URL and image locations are recorded on the report.
2. **Given** a report already linked to an issue, **When** synced, **Then** a comment is added to that issue instead of creating a new one.
3. **Given** a target repo that is public, **When** sync is about to commit image copies, **Then** the user is asked to confirm on every run; declining skips the image commit (issue/comment still proceeds) and nothing is committed.
4. **Given** a target repo that is private, **When** sync first commits image copies to it, **Then** the user is asked once; the consent is remembered for that repo and later syncs do not ask again.
5. **Given** a report already fully synced, **When** synced again, **Then** nothing is duplicated (no new issue, no repeated comment, no repeated commit).
6. **Given** sync is built against a small tracker/storage interface, **When** a future destination (object store, other tracker) is added, **Then** existing commands need no redesign.

---

### User Story 5 - Let coding agents read and request bug reports (Priority: P5)

A user registers `bugcap mcp-serve` as an MCP server in their coding agent. The agent can list reports, fetch a report including its image, pull GitHub issues, and ask the user to capture a screenshot for a given report or issue.

**Why this priority**: High leverage but depends on all earlier capabilities.

**Independent Test**: Drive the server over stdio with a scripted client: handshake, list tools, call each tool, and verify results (including image content).

**Acceptance Scenarios**:

1. **Given** the server is started, **When** a client performs the MCP initialize handshake, **Then** the server advertises its tools.
2. **Given** reports exist, **When** the agent calls `list_reports` and `get_report`, **Then** it receives report data and the image as image content.
3. **Given** the agent calls `request_screenshot` for a report or issue, **When** a desktop UI is available, **Then** the call blocks until the user captures (or cancels) and returns the result; **When** no UI is available, **Then** it returns immediately with a clear non-interactive message.
4. **Given** the agent calls `pull_issues`, **Then** behavior matches `github pull` and returns a summary.
5. **Given** the README, **When** a user follows the documented Claude Code config snippet, **Then** the server is usable from Claude Code.

---

### Edge Cases

- Running `init` outside a git repo, or in a repo with no `origin` remote (tag falls back to directory name; GitHub slug left unset unless `--github` given).
- Running `init` where `.bugcap.toml` already exists (must not silently overwrite without notice).
- Origin remotes in SSH, HTTPS and non-GitHub forms.
- Captures taken outside any initialized repo (no tag/repo applied; list behaves as before).
- Paths with spaces or non-ASCII characters on Windows; image files that are missing, unreadable, or not images.
- Install command fails or user declines confirmation during `setup`.
- GitHub rate limits, network failure, private repos, issues with no body, pull requests mixed with issues.
- Sync interrupted midway (issue created but image commit failed) — re-run must resume without duplication.
- Image already exists at the target path in the repo.
- Repo visibility cannot be determined (treated as public, i.e. ask every time).
- User declines the image-commit prompt (issue/comment still synced; re-run asks again).
- MCP client closes stdin mid-request; malformed requests; `request_screenshot` timeout or user cancel.
- Existing commands (`capture`, `list`, `show`) must keep their current behavior outside initialized repos.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run on Linux, macOS and Windows without relying on OS-specific facilities unavailable on the others.
- **FR-002**: System MUST store data and config in per-OS standard locations, overridable via `BUGCAP_HOME`; the existing Linux data location MUST remain valid and existing data MUST remain accessible.
- **FR-003**: System MUST capture screenshots using a tool available on the current OS and MUST allow importing an existing image when no tool is available.
- **FR-004**: `bugcap setup` MUST detect an installed capture tool, and if none, recommend one for the OS.
- **FR-005**: `setup` MUST install the recommended tool only after explicit user confirmation or `--yes`, using the detected package manager; otherwise it MUST print manual guidance.
- **FR-006**: System MUST be installable system-wide via pipx and uv tool, and this MUST be documented and verified.
- **FR-007**: `bugcap init [--tag T] [--github owner/repo]` MUST write a `.bugcap.toml` in the repo, defaulting the tag to the repo name and auto-detecting the GitHub slug from `origin`.
- **FR-008**: Captures made inside an initialized repo MUST automatically receive the repo's tag and a `repo` field.
- **FR-009**: Existing databases MUST be migrated to include the repo field with no loss of existing reports.
- **FR-010**: `bugcap list` MUST show only the current repo's reports when inside an initialized repo, unless `--all` is given.
- **FR-011**: `bugcap edit <id>` MUST allow changing title, notes and status of a report.
- **FR-012**: `bugcap tag <id> add|remove` MUST add or remove tags on a report idempotently.
- **FR-013**: `bugcap github pull [--repo] [--label] [--limit] [--ask]` MUST import issues as reports linked via recorded external references, updating rather than duplicating on re-run; re-import MUST refresh title and body only and MUST NOT overwrite local notes, tags or a locally changed status.
- **FR-014**: With `--ask`, system MUST prompt per issue about adding a screenshot, allowing skip.
- **FR-015**: `bugcap attach <id> [--image PATH]` MUST add a screenshot to an existing report.
- **FR-016**: System MUST emit clear, actionable errors when the `gh` tool is missing or unauthenticated.
- **FR-017**: `bugcap sync <id> --to github` MUST create an issue with the image attached where possible, or comment on an already-linked issue.
- **FR-018**: Sync MUST also commit a plain (non-LFS) copy of each image into the target repo and record all resulting references.
- **FR-018a**: Before committing image copies, sync MUST ask for confirmation every time when the target repo is public, and only on first use (remembered per repo) when it is private; `--yes` accepts the prompt, and a non-interactive run without `--yes` or prior consent MUST skip the image commit and say so.
- **FR-018b**: The repo that receives committed image copies MUST be user-selectable (per-command option, per-repo setting, or global default), defaulting to the issue's own repo; the visibility/consent rules in FR-018a apply to that chosen repo.
- **FR-019**: Sync MUST be idempotent on re-run and able to resume after partial failure.
- **FR-020**: Sync MUST be structured behind a small destination/storage interface so an object store or other trackers can be added later without changing existing commands.
- **FR-021**: `bugcap mcp-serve` MUST provide a stdio MCP server exposing `list_reports`, `get_report` (returning image content), `request_screenshot` and `pull_issues`.
- **FR-022**: `request_screenshot` MUST block awaiting the user when a desktop UI is available and MUST return a clear non-interactive result otherwise.
- **FR-023**: Documentation MUST include a Claude Code configuration snippet for the MCP server.
- **FR-024**: Automated tests MUST cover store migration, repo config, backend detection (simulated OS/PATH), GitHub pull and sync (simulated `gh`), and the MCP handshake and tools.
- **FR-025**: README usage/architecture and ROADMAP status MUST be updated as items complete.
- **FR-026**: Existing `capture`, `list`, `show` behavior MUST be unchanged outside initialized repos.
- **FR-027**: System MUST NOT add heavy dependencies and MUST support Python 3.10 and later.

### Key Entities

- **Report**: A captured bug — id, title, notes, status, tags, repo, creation time, one or more images.
- **Image**: A screenshot belonging to a report; may be captured or imported.
- **Repo Config**: Per-repo settings (tag, GitHub slug) stored in the repo and discovered from the working directory.
- **External Reference**: A link from a report to a remote artifact (GitHub issue, comment, committed image path) used for idempotent pull and sync.
- **Capture Backend**: A screenshot tool known for an OS, with detection, install command and manual guidance.
- **Destination**: A target that reports can be synced to (GitHub now; others later).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from install to first tagged capture in a repo in under 5 minutes on each of the three OSes.
- **SC-002**: `setup` never modifies the system without explicit confirmation or `--yes` (0 unconfirmed installs).
- **SC-003**: Re-running `github pull` or `sync` any number of times yields zero duplicate reports, issues, comments or committed images.
- **SC-004**: 100% of existing reports remain accessible and unchanged after upgrading an existing database.
- **SC-005**: An agent can retrieve a report's image through the agent interface in a single request.
- **SC-006**: Every failure involving missing/unauthenticated GitHub tooling produces a message stating the cause and the fix.
- **SC-007**: The automated test suite covers every area listed in FR-024 and passes on all three target OSes' simulated environments.
- **SC-008**: Existing `capture`/`list`/`show` workflows behave identically before and after, outside initialized repos.

## Assumptions

- Users have git; the GitHub features require the `gh` CLI to be installed and authenticated, which bugcap diagnoses but does not set up.
- Object store sync (roadmap 6) and other trackers (roadmap 9) are out of scope; only the extension seam is required.
- The existing work-in-progress modules are finished and wired in rather than rewritten.
- Choice between a hand-written protocol layer and the official MCP SDK is a planning decision.
- "Desktop UI available" means an interactive graphical session is detected; otherwise the environment is treated as non-interactive.
- By default, committed image copies go to a conventional folder on the default branch of the issue's repo; the user can choose a different repo, folder and branch.
- Issues only (not pull requests) are imported by `github pull`.
