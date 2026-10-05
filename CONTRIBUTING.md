# Contributing to bugcap

Thanks for wanting to help. bugcap is a small, local-first tool, and contributions of all sizes
are welcome: bug reports, docs fixes, tests, new capture backends, and features.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems
go through [SECURITY.md](SECURITY.md), not public issues.

## Ways to contribute

- **Report a bug.** Use the *Bug report* issue template. Include your OS, Python version,
  `bugcap --version`, the exact command, and the output. Redact anything private from logs and
  screenshots.
- **Suggest a feature.** Open an issue first and describe the problem you want solved, not just
  the solution. Check [ROADMAP.md](ROADMAP.md) to see whether it is planned or a deliberate
  non-goal.
- **Fix something.** Issues labelled `good first issue` and `help wanted` are the best place to
  start. Comment on the issue so two people don't do the same work.
- **Improve the docs.** The site lives in `docs/` and the README at the root. Typos and
  clarifications can go straight to a pull request.

## Before you write code

Open an issue and wait for a maintainer's reply for anything beyond a small fix. This covers new
commands, new MCP tools, schema changes, new sync destinations and new dependencies. It saves you
from building something that can't be merged.

## Development setup

You need Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<your-fork>/bugcap
cd bugcap
uv run --extra dev --extra mcp pytest -q     # install and run the tests
uv run bugcap --help                         # run the CLI from source
```

Set `BUGCAP_HOME` to a throwaway directory while developing, so your own reports are never
touched:

```bash
export BUGCAP_HOME=$(mktemp -d)
```

[DEVELOPMENT.md](DEVELOPMENT.md) covers installing from source, upgrades and the MCP server.

## Workflow

1. Fork the repo and create a branch from `master`: `fix-login-note`, `feat-dashboard-filter`.
2. Make a focused change. One pull request should do one thing.
3. Add or update tests, and run the whole suite.
4. Add a line under an `## Unreleased` heading in [CHANGELOG.md](CHANGELOG.md) for any change a
   user would notice. Maintainers pick the version number at release time, so don't bump it.
5. Open a pull request against `master` and fill in the template. CI must pass, and a maintainer
   will review it.

Keep commit messages short and in the imperative mood: `Fix note rewrite on relabel`. Explain
*why* in the body when it isn't obvious. Squash noisy fix-up commits before review, or expect them
to be squashed on merge.

## Project rules

These come from how bugcap is built. Pull requests that break them will be asked to change.

- **The core CLI stays standard-library only.** The only dependency is `tomli` on Python < 3.11.
  Anything heavier must be an optional extra, imported lazily, like the `mcp` SDK.
- **The store is the one shared surface.** The CLI, MCP server, dashboard and live mode go through
  `service.py` for rules and `store.py` for data. Don't add business rules to `cli.py` or a UI
  module.
- **Only `sync.py` talks to a tracker**, through `ghcli.py`, and only when the user runs it.
  Capture must work with no network and no tracker.
- **Nothing is sent anywhere by default.** No telemetry, no cloud storage, no background
  network calls.
- **Never write to stdout from the MCP server.** It speaks the protocol over stdio. Log to a file
  or stderr.
- **Validate input at the edge.** Paths, URLs and repo slugs are checked, images are validated by
  content, and the dashboard stays on loopback with its Host/Origin and token checks. Argument
  lists, never shell strings, when running external tools.
- **Database changes ship as migrations.** Bump the schema version, migrate in place and keep
  existing data. Add a test that opens an old database.
- **Don't reinvent the annotation UI.** bugcap wraps existing capture tools.
- **Cross-platform.** Linux, macOS and Windows differences belong in `backends.py`, `recorder.py`
  or `paths.py`.

## Tests

- Every bug fix gets a test that fails without the fix. Every feature gets tests for success and
  failure paths.
- **Tests must not depend on the machine.** Stub out external tools (`flameshot`, `ffmpeg`,
  `gh`, `wf-recorder`, a display) and use `tmp_path` or `BUGCAP_HOME`. A test that passes only
  because ffmpeg happens to be installed will fail in CI.
- Tests must not hit the network or the real GitHub API.
- Run `uv run --extra dev --extra mcp pytest -q` and make sure everything passes on both Python
  3.10 and 3.12 if you can: `uv run --python 3.10 ...`.

## Code style

Linting is [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml` and enforced in CI:

```bash
uv run --extra dev ruff check src tests          # add --fix for the safe fixes
```

Beyond that, match the surrounding code: type hints on public functions, small functions, naming
and comment density like the file you are editing. Comment *why*, not
*what*. Don't reformat code you aren't changing, because it hides the real diff.

## Documentation

If behaviour changes, update the usage guide (`docs/usage.html`) and the README in the same pull
request. Keep README links and image URLs absolute so they render on PyPI.

## Pull request checklist

- [ ] The change is focused and linked to an issue (for anything non-trivial)
- [ ] Tests added or updated, the full suite passes and `ruff check` is clean
- [ ] No new dependency in the core CLI
- [ ] Docs and `CHANGELOG.md` updated
- [ ] No secrets, tokens, personal paths or private screenshots in code, tests or fixtures

## Licence

bugcap is [MIT licensed](LICENSE). By submitting a contribution you agree it may be distributed
under that licence, and you confirm you have the right to submit it. There is no separate CLA.

## Releases (maintainers)

Releases are cut by maintainers: bump the version in `pyproject.toml`, `src/bugcap/__init__.py`
and `uv.lock`, move the `Unreleased` notes into a dated `CHANGELOG.md` section, then push a
`vX.Y.Z` tag. The release workflow runs the tests and publishes to PyPI.
