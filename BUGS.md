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
