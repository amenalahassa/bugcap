# Known bugs / issues

All five entries below are fixed (see the commit history); they are kept here with their resolution.

## `bugcap init --force` silently orphans existing data when the repo changes

When `.bugcap.toml` is overwritten with `--force` and the tag or GitHub slug changes, reports
already stored under the old repo key keep pointing at it. They disappear from `bugcap list` in
that repo, with no warning.

**Expected:** if the repo identity (tag / GitHub slug) changes, `init --force` asks whether the
existing reports and their images/data should be moved to the new repo, with the old and new
values and the number of affected reports shown. Non-interactive runs need an explicit flag
(e.g. `--migrate` / `--no-migrate`) instead of guessing.

**Resolution:** Fixed: `init --force` (and `config repo set/unset`) shows the old/new identity and the number of affected reports, then moves them (and swaps the repo tag) on `--migrate` or an interactive yes; non-interactive runs must pass `--migrate` or `--no-migrate`.

## `bugcap mcp-serve` does not log anything

The MCP server produces no log output, so failed tool calls, client connection problems and
crashes are invisible to the user.

**Expected:** log to a file (and/or stderr, never stdout, which carries the MCP protocol) with a
configurable level: startup, client initialize, each tool call with its outcome and duration, and
errors with tracebacks. Default log location in the per-user data dir; document it in the README.

**Resolution:** Fixed: `mcp-serve` logs to `logs/mcp-server.log` in the data dir and to stderr (never stdout), with `--log-level`/`--log-file`; documented in the README.

## Capturing a new image for an already-reported bug can't carry a note

`bugcap attach <id>` already captures (or imports with `--image`) a screenshot onto an existing
report, but it takes no text: there is no way to say what the new image shows. The only workaround
is a separate `bugcap edit` afterwards, which loses the link between the note and the image.

**Expected:** `bugcap attach <id> [--note TEXT]` appends the note to the report's existing notes
(never replaces them), tied to the image it was added with (timestamped, and referenceable once
`@` image references exist). Without `--note` on an interactive terminal, prompt for an optional
note after the capture, as `capture` does. The same applies to the MCP `request_screenshot` tool
(optional note argument) and to the `--ask` flow of `github pull`.

**Resolution:** Fixed: `attach --note` (and an interactive prompt, MCP `request_screenshot` `note`, and the `github pull --ask` flow) appends a timestamped note that references the image.

## `--images-repo` value is not validated

`bugcap init --images-repo X` and `bugcap sync --images-repo X` accept any string. Nothing checks
that it is a well-formed `owner/repo` slug, or that the repo exists and is writable with the
current `gh` login, so a typo only surfaces later as a failed commit during `sync` (or, worse, a
partial sync).

**Expected:** validate the slug format immediately (also for `--github`, `--images-path` and
`--images-branch`), and verify via `gh` that the repo exists, is writable and that the branch
exists, with a clear error naming the bad value. Offline or unauthenticated, warn and continue
rather than refuse.

**Resolution:** Fixed: slug, images path and branch formats are validated in `init`, `sync` and `config repo set`, and checked with `gh` (exists, writable, branch exists); offline only warns.

## No way to change the values set at `init` without `--force`

The tag, GitHub slug and `[sync]` values (`images_repo`, `images_path`, `images_branch`) can only
be changed by re-running `bugcap init --force`, which rewrites `.bugcap.toml` wholesale (and
currently orphans existing data, see above).

**Expected:** a dedicated command, e.g. `bugcap config repo set <key> <value>` /
`bugcap config repo show` (or `bugcap init --update`), that changes individual keys of the current
repo's `.bugcap.toml`, validates the new value (see above) and, for tag/slug changes, offers to
migrate existing reports as described in the `init --force` entry.

**Resolution:** Fixed: `bugcap config repo show|set|unset` changes single keys, validates them and follows the same migration rules.
