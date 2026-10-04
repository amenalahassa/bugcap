# Quickstart: validating feature 002

Use an isolated data directory so the real store is untouched.

```bash
export BUGCAP_HOME="$(mktemp -d)"
cd /path/to/an/initialized/repo        # has .bugcap.toml (bugcap init)
```

## Prerequisites

- Python 3.10+, `pip install -e '.[dev]'`
- For recording: `ffmpeg` (and `wf-recorder` on Wayland), see `bugcap setup`
- For live mode: a desktop session with Tk (`python3 -c "import tkinter"` succeeds)
- For the dashboard: any browser

## 1. Test suite

```bash
pytest -q
```

Expected: all new test modules listed in plan.md pass; existing tests unchanged.

## 2. Images (Story 1)

```bash
bugcap capture --image ./sample.png --title "Login fails" --note "See @1"
bugcap attach 1 --image https://example.com/some.png --label after-fix
bugcap attach 1 --image ./not-an-image.txt        # expect: rejected, exit 1
bugcap images 1
```

Expected: `images 1` lists indexes 1 and 2; index 2 has label `after-fix`; the rejected file is not in the store; `bugcap show 1` lists the copies under `images/` (not the original paths).

## 3. `@` references (Story 2)

```bash
bugcap edit 1 --note "Error after step 3, see @1 and @after-fix. Mail dev@example.com, code \`@9\`, escape @@1"
bugcap edit 1 --note "See @9"                     # expect: error naming @9, lists @1, @2, @after-fix
bugcap images 1 remove 1                          # expect: refused (referenced)
bugcap images 1 remove 1 --force                  # expect: references rewritten, notes show [image removed]
bugcap show 1
```

## 4. Recording (Story 3)

```bash
bugcap record --id 1 --format animated --max-seconds 10
# perform a few actions, press Enter
bugcap show 1
```

Expected: a media item of kind `animated` appears with its final size; the command reports the stop reason. Without ffmpeg installed, expect exit 3 with install guidance and no new report.

## 5. Dashboard (Story 4)

```bash
bugcap dashboard --port 8765 --open
```

Checks:

- Filter by tag and text; open report 1; `@1` renders inline; the animated item plays.
- Change the status; then `bugcap show 1` shows the new status.
- Non-loopback refusal: `bugcap dashboard --host 0.0.0.0` → refused without the explicit flag; with it, a warning is printed.
- Security (curl):
  ```bash
  curl -si -H 'Host: evil.example' http://127.0.0.1:8765/api/reports        # 400
  curl -si -X POST http://127.0.0.1:8765/api/reports/1/status -d '{"status":"closed"}'   # 403 (no token)
  curl -si 'http://127.0.0.1:8765/media/..%2F..%2Fetc%2Fpasswd'                # 404
  ```

## 6. Live mode (Story 5)

```bash
bugcap live
```

Run through two bugs: click Start, capture a region, fill title, Save; the counter reads `1 saved this session`; repeat. Close with a details window open and unsaved text, decline (window stays), then confirm (draft kept). Run `bugcap live` again in the same repo: the draft is offered.

Headless check: `env -u DISPLAY -u WAYLAND_DISPLAY bugcap live` → exit 3 with the desktop-session message.

## 7. GitHub sync (Story 3, sync)

```bash
bugcap sync 1 --to github --repo owner/repo --yes
```

Expected: `@` references in the issue body are replaced with image markdown or links; any media over 25 MB prints a skip warning and sync continues.

## 8. Migration (no data loss)

```bash
# Using a database created by the previous version (fixture in tests/fixtures/v1.db)
cp tests/fixtures/v1.db "$BUGCAP_HOME/data/bugcap.db"
bugcap list --all
bugcap images 1
```

Expected: every v1 report is present with its notes, tags, status and repo; each old image appears as index 1…n with `source: legacy`.

## Last run

2026-10-04, Linux (X11, Python 3.10), isolated `BUGCAP_HOME`:

- §1 `pytest -q`: 298 passed.
- §2, §3 (CLI, local HTTP server for the URL case), §4 (real ffmpeg x11grab, animated GIF, duration cap), §8 (migration of a v1 database): pass.
- §5: API and security checks by curl pass (400 bad Host, 403 no token, 404 traversal, non-loopback warning). The browser UI itself was not opened by hand.
- §6: Tk shell driven programmatically against the real display (two reports saved in a row, counter `2 saved this session`); not clicked through by hand. Headless exit 3 is covered by tests.
- §7: covered by `tests/test_github_media_sync.py` with a fake `gh`; not run against real GitHub.
- Not exercised: macOS and Windows recorders (argv construction only, via tests), Wayland (wf-recorder).
