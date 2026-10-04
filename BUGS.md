# Known bugs / issues

## `bugcap init --force` silently orphans existing data when the repo changes

When `.bugcap.toml` is overwritten with `--force` and the tag or GitHub slug changes, reports
already stored under the old repo key keep pointing at it. They disappear from `bugcap list` in
that repo, with no warning.

**Expected:** if the repo identity (tag / GitHub slug) changes, `init --force` asks whether the
existing reports and their images/data should be moved to the new repo, with the old and new
values and the number of affected reports shown. Non-interactive runs need an explicit flag
(e.g. `--migrate` / `--no-migrate`) instead of guessing.

## `bugcap mcp-serve` does not log anything

The MCP server produces no log output, so failed tool calls, client connection problems and
crashes are invisible to the user.

**Expected:** log to a file (and/or stderr, never stdout, which carries the MCP protocol) with a
configurable level: startup, client initialize, each tool call with its outcome and duration, and
errors with tracebacks. Default log location in the per-user data dir; document it in the README.

## Capturing a new image for an already-reported bug can't carry a note

`bugcap attach <id>` already captures (or imports with `--image`) a screenshot onto an existing
report, but it takes no text: there is no way to say what the new image shows. The only workaround
is a separate `bugcap edit` afterwards, which loses the link between the note and the image.

**Expected:** `bugcap attach <id> [--note TEXT]` appends the note to the report's existing notes
(never replaces them), tied to the image it was added with (timestamped, and referenceable once
`@` image references exist). Without `--note` on an interactive terminal, prompt for an optional
note after the capture, as `capture` does. The same applies to the MCP `request_screenshot` tool
(optional note argument) and to the `--ask` flow of `github pull`.
