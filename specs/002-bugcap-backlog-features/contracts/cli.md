# CLI Contract: bugcap (feature 002)

All existing commands, flags and outputs are unchanged. The additions below are backward compatible. Exit codes: `0` success, `1` user error (validation, not found, refused), `2` usage error (argparse), `3` environment problem (no recorder, no display, missing tool).

## Images: `capture` and `attach`

```text
bugcap capture [--title T] [--note N] [--tag X ...] [--image SRC ...] [--label L ...]
bugcap attach <id> --image SRC [--image SRC ...] [--label L ...]
```

- `--image SRC` (repeatable): local file path, glob pattern, or `http(s)://` URL. Each input is validated and copied into the store.
- `--label L` (repeatable): applies to the `--image` at the same position. Use `--label ""` or omit to skip a label for that image.
- `capture --image` skips the capture tool and creates the report with the imported images as indexes 1…n.
- Output per input: `added #<idx> <basename> (<kind>, <size>)` or `skipped <source>: <reason>`. Partial batch: valid inputs are added; invalid ones are reported and the exit code is `1` if any input was rejected (valid ones remain added).

Examples:

```text
bugcap capture --image ./shot.png --title "Login fails" --note "See @1"
bugcap attach 7 --image ./shots/*.png --image https://ci.example.com/run/42.png --label after-fix
```

Error cases (exit 1): file missing; glob matches nothing; URL not http(s); HTML or other non-image body; size > 25 MB; timeout; duplicate label (`duplicate label 'login-error' (already #2)`).

## Images: new subcommand `images`

```text
bugcap images <id>                      # list: idx, label, kind, size, path
bugcap images <id> relabel <idx|label> <new-label> [--force]
bugcap images <id> remove <idx|label> [--force]
```

- `relabel` / `remove` on a referenced item without `--force` → exit `1`, message lists the referencing notes and tokens, and says to use `--force`.
- With `--force`: references are rewritten (relabel: `@old` → `@new`; remove: token → `[image removed]`. Other indexes never change, so remaining `@n` tokens stay valid.

## Notes: `capture`, `edit`

- `--note` and `edit --note` validate `@` references on save. Unknown references refuse the save with exit `1`:

  ```text
  error: unknown reference @3 in notes
  valid references: @1, @2, @login-error
  ```

- `edit` without `--note` does not re-validate notes.

## Show

`bugcap show <id>` gains a media section and inline resolution:

```text
Notes: Error appears after step 3, see @1 (images/3f2a….png) and @login-error (images/9b1c….png)
Media:
  #1  image  login-error  images/3f2a….png  48.2 KB  (source: ./shot.png)
  #2  video  -            media/77e1….mp4   3.1 MB   (recorded)
  #3  frames -            media/… (8 frames) 1.4 MB
```

Escaped `@@1` prints as `@1`. Code and email `@` are printed unchanged.

## Record

```text
bugcap record [--id N] [--format video|frames|animated] [--max-seconds S] [--fps F]
              [--max-mb M] [--backend ffmpeg|wf-recorder] [--title T] [--note N] [--tag X ...]
```

- Defaults: `--format animated`, `--max-seconds 30`, `--fps 5` (animated) / `30` (video), `--max-mb 25`.
- Without `--id`, a new report is created and its title defaults to `Recording <timestamp>`.
- Stops on Enter, Ctrl+C, or a cap. Prints the stop reason and the final size: `recorded 9.2 s, 1.1 MB (animated), stopped: duration cap`.
- Exit `3` when no recorder is available (prints the install guidance for the OS) or permission is missing (prints how to grant it). No report is created in these cases.

## Setup (extended)

`bugcap setup` also reports recorder backends (`ffmpeg`, `wf-recorder`) with the same detection, install suggestion, and `--yes` behaviour. Existing capture output is unchanged; recorder lines are appended.

## Live

```text
bugcap live [--repo-dir DIR]
```

- Opens the control window (always on top where supported). No stdout interaction is required.
- Exit `3` without a desktop session (`DISPLAY`/`WAYLAND_DISPLAY` missing on Linux, or Tk cannot open a display).
- On start, offers restore for drafts saved in the same repo (GUI prompt; in headless tests the prompt is injected).

## Dashboard

```text
bugcap dashboard [--port P] [--open] [--host H]
```

- Default `--port 8765`; `--port 0` picks a free port and prints the URL.
- Default host `127.0.0.1`. A non-loopback `--host` is refused unless passed explicitly, and then prints: `warning: dashboard exposed on <H>; anyone on that network can read and edit your bugs`.
- `--open` opens the URL in the default browser.
- Runs in the foreground until Ctrl+C.

## Sync (extended)

`bugcap sync <id> --to github` behaviour additions:

- Each `@n`/`@label` in the notes is replaced in the issue body or comment with `![label](url)` for images or a plain link for video and animated files.
- Video and animated files are uploaded or committed as-is.
- Frames are committed as a set, in order, one commit, linked in the body as a numbered list.
- Items above the size threshold are skipped with `warning: skipped media #<idx> <name> (<size>): above the 25 MB upload limit` and sync continues.
