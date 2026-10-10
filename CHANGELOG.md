# Changelog

## Unreleased

### Added
- Attach files of any type to a report: `bugcap attach <id> --file SRC [--file-label L]` (paths, globs or URLs, repeatable) and the `attach_file` MCP tool. Notes refer to them as `@d1`, `@d2` or by label.
- Live mode: **Upload image...** and **Attach file...** buttons stage files picked from disk, for a new bug or an existing one.
- Live mode: the new-bug form's **Repo** field is now a picker listing every repo you've run `bugcap init` in, so a report can be filed against a different project than the one `live` was launched from.
- Docs: a "Windows notes" section in the usage guide covering the `pipx`/`winget` install path, where data and config live, the `ffmpeg` recorder requirement, and the PATH-refresh quirk below.

### Changed
- The store schema moves to version 3 (the `media` table accepts the new `file` kind); existing databases migrate on first open.
- Attached files are served by the dashboard as downloads and are never uploaded by `sync`.

### Fixed
- Missing report ID errors now suggest `bugcap list --all` to find report IDs.
- Windows: `bugcap setup` and `bugcap live` re-sync `PATH` from the registry before detecting a capture tool, so a tool installed via `winget`/`scoop`/`choco` is picked up without restarting the terminal. `bugcap setup` also double-checks detection after installing instead of assuming a zero exit code means the tool is now usable, and says so if a restart is still needed.
- `bugcap show`/`list`/etc. no longer crash with `UnicodeEncodeError` on a narrow console codepage (e.g. Windows cp1252) when a report's title or notes contain a character the codepage can't render.

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
