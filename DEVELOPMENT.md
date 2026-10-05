# Development

## Installing bugcap as a tool

From the project directory:

```bash
uv tool install '.[mcp]'            # regular install
uv tool install --editable '.[mcp]' # editable: source changes take effect without reinstalling
```

Optional extras are installed with `'.[extra]'`. Defined in `pyproject.toml`:

- `mcp`: the official MCP SDK, needed for `bugcap mcp-serve` (`uv tool install '.[mcp]'`)
- `dev`: pytest and ruff, for running the tests and the linter

An extra that isn't defined in `pyproject.toml` is ignored with a warning.

## Running tests

```bash
uv run --extra dev --with pytest pytest -q
```

Use `uv run` rather than bare `python3`: dependencies such as `tomli` (Python < 3.11) are only
installed in uv's environment.

## Linting

```bash
uv run --extra dev ruff check src tests
```

Rules are in `pyproject.toml` (`[tool.ruff]`); CI runs the same check.

## Upgrading to a new version

`uv tool install` on an already-installed tool does nothing, and `uv tool upgrade bugcap` does not
pick up local source changes. After pulling or editing the code, force a rebuild:

```bash
uv tool install --reinstall '.[mcp]'
# or
uv tool install --force '.[mcp]'
```

- Bump `version` in `pyproject.toml` for each release, so uv doesn't reuse a cached build of the
  same version and `uv tool list` stays meaningful.
- With an editable install you only need to reinstall when dependencies or entry points change.

### Installing from git

```bash
uv tool install 'bugcap[mcp] @ git+https://github.com/<you>/bugcap'
uv tool upgrade bugcap
```

### Uninstalling

```bash
uv tool uninstall bugcap
```

## Data survives reinstalls

The store (SQLite database and images) and config live in per-user data/config directories, not
in the tool environment (`BUGCAP_HOME` overrides both). Reinstalling never touches them; schema
changes ship as in-place migrations.

## MCP server

If `bugcap mcp-serve` is registered with Claude Code (or another MCP client), it points at the
`bugcap` executable on your PATH. After a reinstall, restart the client or reconnect (`/mcp` in
Claude Code) so it launches the new version.
