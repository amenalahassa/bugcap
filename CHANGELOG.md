# Changelog

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
