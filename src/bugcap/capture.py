import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import backends
from .paths import images_dir
from .recorder import TargetUnsupported, _target_parts, platform_key

__all__ = ["CaptureError", "TargetUnsupported", "build_screenshot_argv", "capture_screenshot", "has_display",
           "import_image"]


class CaptureError(RuntimeError):
    pass


def has_display() -> bool:
    """Whether an interactive graphical session is available for a capture UI.

    Linux: a running X11/Wayland session (``DISPLAY`` or ``WAYLAND_DISPLAY``).
    macOS/Windows: assumed present (the window server runs for logged-in users).
    """
    if sys.platform == "win32" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _no_backend_error() -> CaptureError:
    rec = backends.recommended()
    return CaptureError(
        "No capture tool found. Run `bugcap setup` to detect/install one "
        f"(recommended: {rec.name} - {backends.guidance(rec)}), "
        "or pass an existing screenshot with --image."
    )


def import_image(source: Path) -> Path:
    """Copy an existing image into the store (no capture tool needed)."""
    if not source.is_file():
        raise CaptureError(f"Image not found: {source}")
    dest = images_dir() / f"{uuid.uuid4()}{source.suffix.lower() or '.png'}"
    shutil.copyfile(source, dest)
    return dest


def _geometry(rect) -> str:
    x, y, w, h = rect
    return f"{w}x{h}+{x}+{y}"


def build_screenshot_argv(backend: str, target, dest, platform=None, raw=None,
                          resolve=lambda name: name) -> list[list[str]]:
    """The command(s) that capture `target` (a `targets.CaptureTarget`, or None for the
    backend's usual interactive capture) into `dest`, run in order. satty needs a grim grab
    into `raw` first. Raises TargetUnsupported for a combination the backend cannot do."""
    kind, rect = _target_parts(target, for_recording=False)
    dest = str(dest)
    if backend == "flameshot":
        exe = resolve("flameshot")
        if kind == "monitor":  # annotate on that screen only (bugcap report: multi-monitor Windows)
            return [[exe, "screen", "-n", str(target.monitor.number), "-e", "--path", dest]]
        if kind in ("region", "window"):
            return [[exe, "gui", "--region", _geometry(rect), "--path", dest]]
        return [[exe, "gui", "--path", dest]]
    if backend == "satty":
        grim = [resolve("grim")]
        if kind == "monitor":
            grim += ["-o", target.monitor.id]
        elif kind == "region":
            x, y, w, h = rect
            grim += ["-g", f"{x},{y} {w}x{h}"]
        elif kind == "window":
            raise TargetUnsupported("grim cannot capture a single window")
        return [grim + [str(raw)], [resolve("satty"), "--filename", str(raw), "--output-filename", dest]]
    if backend == "screencapture":
        exe = resolve("screencapture")
        if kind == "monitor":
            return [[exe, "-D", str(target.monitor.number + 1), dest]]
        if kind == "region":
            return [[exe, "-R", ",".join(str(v) for v in rect), dest]]
        if kind == "window":
            return [[exe, "-i", "-w", dest]]
        # -i interactive region/window selection (space toggles window mode)
        return [[exe, "-i", dest]]
    raise CaptureError(f"Unknown backend: {backend}")


def capture_screenshot(target=None) -> Path:
    """Launch the detected backend's capture and return the saved PNG path. Without a
    `target` it is the backend's interactive capture UI; with one (live mode) it covers just
    that monitor, region or window. Blocks until the user finishes (saves or cancels).
    """
    backend = backends.detect()
    if backend is None:
        raise _no_backend_error()
    dest = images_dir() / f"{uuid.uuid4()}.png"
    raw = images_dir() / f"{uuid.uuid4()}-raw.png" if backend.name == "satty" else None
    commands = build_screenshot_argv(backend.name, target, dest, platform_key(), raw,
                                     resolve=lambda name: backends.resolve(name) or name)
    try:
        for argv in commands:
            result = subprocess.run(argv, capture_output=True, text=True)
            if result.returncode != 0 and backend.name == "flameshot" and argv[1] == "screen":
                # flameshot numbers screens its own way; the monitor's rectangle always works
                fallback = [argv[0], "gui", "--region", _geometry(target.monitor.rect), "--path", str(dest)]
                result = subprocess.run(fallback, capture_output=True, text=True)
            if result.returncode != 0:
                name = Path(argv[0]).stem
                raise CaptureError(f"{name} exited with {result.returncode}: {result.stderr}")
    finally:
        if raw is not None:
            raw.unlink(missing_ok=True)

    if not dest.exists():
        raise CaptureError(
            "Capture backend exited without saving a file "
            "(did you cancel the capture instead of saving it?)."
        )
    return dest
