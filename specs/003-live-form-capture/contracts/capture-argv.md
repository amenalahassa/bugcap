# Contract: Capture and Record Commands per Target

Pure builders. Tests assert exact lists. `target=None` MUST return exactly today's command.

Notation: `D` destination file; `(x, y, w, h)` physical-pixel rectangle in virtual-desktop coordinates; `N` zero-based monitor index in the backend's order; `W, H` rounded down to even for recording.

## `capture.build_screenshot_argv(backend, target, dest, platform) -> list[list[str]]`

Returns one or more commands, run in order (grim + satty is two).

| backend | None / all | monitor | region | window |
|---|---|---|---|---|
| flameshot | `[exe, gui, --path, D]` | `[exe, screen, -n, N, -e, --path, D]` | `[exe, gui, --region, WxH+X+Y, --path, D]` | `[exe, gui, --region, <window rect>, --path, D]` |
| satty | `[grim, RAW]`, `[satty, --filename, RAW, --output-filename, D]` | grim `-o OUTPUT` | grim `-g "X,Y WxH"` | `TargetUnsupported` |
| screencapture | `[exe, -i, D]` | `[exe, -D, N+1, D]` | `[exe, -R, X,Y,W,H, D]` | `[exe, -i, -w, D]` |

`TargetUnsupported(reason)` is raised for unsupported combinations; the chooser never offers them.

## `recorder.build_capture_argv(backend, platform, fmt, fps, max_seconds, out, display=None, codec="h264", av_index=0, target=None) -> list[str]`

Input section only (the encoder part is unchanged, except that mp4 adds `-movflags +frag_keyframe+empty_moov`; with `target=None` it is left out so output is byte-identical):

| backend/platform | monitor / region | window |
|---|---|---|
| ffmpeg windows | `-f gdigrab -framerate F -offset_x X -offset_y Y -video_size WxH -i desktop` | `-f gdigrab -framerate F -i title=<title>` |
| ffmpeg linux (X11) | `-f x11grab -framerate F -video_size WxH -i <display>+X,Y` | as region with the window rect |
| ffmpeg macos | monitor: `-i <index>:none`; region: input as monitor + `-vf crop=W:H:X:Y,pad=…`, or, when the target carries `space=(SW, SH)` (the Tk screen size in points the region was drawn in), `-vf crop=w=iw*W/SW:h=ih*H/SH:x=iw*X/SW:y=ih*Y/SH,pad=…` so Retina pixels are cropped correctly | `TargetUnsupported` |
| wf-recorder | monitor: `-o OUTPUT`; region: `-g "X,Y WxH"` | `TargetUnsupported` |

## `recorder.run_recording(..., target=None, still_valid=None)`

- `still_valid: Callable[[], str | None]` returns `None` while OK, or a reason ("window closed", "window minimised", "window moved"); polled each loop. When it returns a reason, recording stops with `RecordResult.reason = <reason>` and the file is kept.
- `None` (default) means no check, as today.

## Window listing (`screens.list_windows`)

- Windows: Win32 enumeration, each window with its owning process id.
- X11: `wmctrl -lpG` (`id desktop pid x y w h host title`; desktop `-1` skipped), falling back to `xwininfo -root -tree` (no pid).
- bugcap's own windows are dropped by process id, or by title (`New bug report`, `New bug (note only)`, `Add to existing bug`, `Capture what?`, `bugcap live…`) when no pid is known.

## `opener.open_argv(path, platform) -> list[str] | None`

`macos → ["open", path]`, `linux → ["xdg-open", path]`, `windows → None` (use `os.startfile`). A frame set opens its folder.

`opener.open_path(path) -> str | None` returns `None` on success, else a user message: "File not found: …" or "No application to open <name>. It is at <path>."
