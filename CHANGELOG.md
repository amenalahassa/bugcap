# Changelog

## Unreleased

### Fixed
- Missing report ID errors now suggest `bugcap list --all` to find report IDs.

## 0.5.1 - 2026-10-05

### Added
- `bugcap --version`.
- Contributing guide, code of conduct, security policy, and issue and pull request templates.
- ruff linting (`[tool.ruff]` in `pyproject.toml`), run in CI; `ruff` joins the `dev` extra.

### Changed
- CI tests Python 3.10 to 3.13 on Linux, plus macOS and Windows, with ruff linting and a job timeout.

### Fixed
- The README uses absolute image and file links so the logo and demo render on PyPI.
- Tests no longer depend on the working directory, on `/` path separators, or on a display (one test hung on Windows and macOS).

## 0.5.0 - 2026-10-05

### Added
- `bugcap attach` prints the bug's details (as `bugcap show` does) after its usual output.

### Changed
- Identical images are stored once: files are named by their content, so the same image on several bugs shares one file. Images already in the store keep their old names and are not merged.
- Removing an image or deleting a report keeps a file that another bug still uses.

## 0.4.0 - 2026-10-04

### Added
- `bugcap live` can record the screen (Record / Stop) as well as take screenshots. Captures are staged: take any mix of images and videos, then make one report from them.
- `bugcap live` can add the staged captures, with an optional note, to an existing bug.
- `bugcap live` can file a note-only bug (title, note, optional tags) with no media.
- Live drafts keep every staged capture, or none.

### Changed
- The live window now opens in the top-right corner of the screen; its dialogs open beside it.

## 0.3.0 - 2026-10-04

### Added
- `bugcap capture --no-image` saves a text-only report without launching a capture tool.
- `bugcap delete <id>` permanently deletes a report and its images (asks first; `--yes` skips the prompt). Synced GitHub issues are not touched.

### Changed
- Media are referenced by kind: `@i1` image, `@v2` video, `@g3` animated GIF, `@f4` frame set. Reports keep `#N`, so a media ref is never mistaken for a report. `@1` still works in existing notes.
- Notes can reference reports with `#N`. An unknown number is kept as text with a warning, and `sync` turns it into the linked GitHub issue (or plain `report N`).
- Labels that look like media numbers (`i1`, `v2`, `g3`, `f4`, `1`) are now reserved and rejected.
- `bugcap live` uses a flatter, consistent light theme with an accent Save/Start button.

## 0.2.2 - 2026-10-04

### Fixed
- The `setup --yes` test no longer depends on whether a screen recorder is installed on the machine running it. (0.2.1 was tagged before this fix; its CI run failed, so it was not published.)

## 0.2.1 - 2026-10-04

### Added
- **Documentation site:** GitHub Pages with a landing page and a usage guide (`docs/`), linked from the README.
- **Release workflow:** tests on push and pull requests; on a `v*` tag, the package is built and published to PyPI with trusted publishing.

### Fixed
- `uv.lock` records the current package version.

## 0.2.0 - 2026-10-04

### Added
- **Images:** `capture`/`attach --image` accept paths, globs and http(s) URLs (validated by content, copied into the store), with `--label`; `bugcap images` lists, relabels and removes.
- **`@` references** in notes (`@1`, `@label`, `@@`): validated on save, resolved in `show`, GitHub sync, MCP and the dashboard; relabel/remove need `--force` when referenced.
- **`bugcap record`:** ffmpeg / wf-recorder; video, keyframes or animated GIF; duration and size caps.
- **`bugcap live`:** always-on-top window for reporting many bugs in a row, with drafts.
- **`bugcap dashboard`:** local web UI (127.0.0.1 only by default) to browse, filter and triage.
- **`bugcap config repo show|set|unset`;** `init --force` and `config repo` offer to move reports when the repo identity changes (`--migrate` / `--no-migrate`).
- **`attach --note`**, MCP `request_screenshot` `note`, and the `github pull --ask` note.
- MCP tools `attach_image` and `update_notes`; `mcp-serve` logging (`--log-level`, `--log-file`).
- Validation of `--github`, `--images-repo`, `--images-path`, `--images-branch`, checked with `gh` when available.
- GitHub sync of video/animated/frames media with a size limit (`[sync] max_upload_mb`, default 25, max 100).

### Changed
- Database schema v2 (`media` table); existing databases are migrated in place with no data loss. Downgrading is not supported.
- Image inputs must be real PNG, JPEG, GIF or WebP files.
