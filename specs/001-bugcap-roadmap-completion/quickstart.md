# Quickstart / Validation Guide

Prereqs: Python >=3.10, `pipx` or `uv`, `git`; `gh` authenticated for GitHub steps (or run the mocked pytest suite).

1. **Install system-wide**: `pipx install '.[mcp]'` (or `uv tool install '.[mcp]'`; omit `[mcp]` for the core CLI only), then `bugcap --help` from another directory. Expect all subcommands listed. Upgrade check: install on Python 3.10 resolves `tomli`.
2. **Setup**: `bugcap setup` → detected tool or recommendation; `bugcap setup --yes` only installs when missing. With `PATH` stripped, expect manual guidance.
3. **Init**: in a git repo with a GitHub origin, `bugcap init` → `.bugcap.toml` with tag=repo name and `github=owner/repo`.
4. **Capture/import**: `bugcap capture --image ./shot.png --title "Broken" --note "x"` → report carries repo tag; `bugcap list` shows it; from another directory `bugcap list` omits it, `bugcap list --all` shows it.
5. **Triage**: `bugcap edit 1 --status resolved`; `bugcap tag 1 add ui`; `bugcap show 1`.
6. **Migration**: copy a pre-feature `bugcap.db` into `BUGCAP_HOME/data/`, run `bugcap list --all` → old rows intact.
7. **Pull**: `bugcap github pull --limit 5` twice → counts `created` then `unchanged`. `bugcap attach 2 --image shot.png`.
8. **Sync**: `bugcap sync 1 --to github --images-repo owner/assets` → prompt (private: first time; public: always), issue created, image committed, refs in `bugcap show 1`; rerun → no changes.
9. **MCP** (needs the `mcp` extra; without it `bugcap mcp-serve` prints the install hint and exits 1): `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' | bugcap mcp-serve` → result with `serverInfo`. Add to Claude Code per [contracts/mcp.md](contracts/mcp.md).
10. **Tests**: `pip install -e '.[dev,mcp]' && pytest`.

---

## Validation status (2026-10-04, Linux aarch64, Python 3.10.12)

- **Step 1 (install)** — verified with `uv tool install --python 3.10 .`: the wheel builds, `tomli`
  resolves via the `python_version < '3.11'` marker, and `bugcap --help` / `bugcap list` run from
  an unrelated directory. `uv tool install '.[mcp]'` also succeeds (pulls `mcp 1.30.0`). `pipx` is
  not installed on this machine, so the pipx line was not exercised here; the packaging is standard
  (PEP 621 + console script) so pipx uses the same metadata.
- **Step 10 (tests)** — `pip install -e '.[dev,mcp]' && pytest` → **104 passed** on Python 3.10.12.
  3.11+ was not available on this machine, so the suite ran on 3.10 only.
- **Steps 2–9** — exercised through the mocked pytest suite (`gh`, `shutil.which`, `sys.platform`
  are monkeypatched; the MCP handshake runs a real `bugcap mcp-serve` subprocess via the SDK stdio
  client). `gh` is not authenticated in this environment, so the live GitHub pull/sync walk-throughs
  were not run against a real repo; no deviations were found in the mocked paths.
