import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import backends
from .paths import images_dir


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


def capture_screenshot() -> Path:
    """Launch the detected backend's interactive capture UI and return the saved PNG path.
    Blocks until the user finishes (saves or cancels).
    """
    backend = backends.detect()
    if backend is None:
        raise _no_backend_error()
    dest = images_dir() / f"{uuid.uuid4()}.png"

    if backend.name == "flameshot":
        result = subprocess.run(
            ["flameshot", "gui", "--path", str(dest)], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise CaptureError(f"flameshot exited with {result.returncode}: {result.stderr}")
    elif backend.name == "satty":
        raw = images_dir() / f"{uuid.uuid4()}-raw.png"
        subprocess.run(["grim", str(raw)], check=True)
        result = subprocess.run(
            ["satty", "--filename", str(raw), "--output-filename", str(dest)],
            capture_output=True,
            text=True,
        )
        raw.unlink(missing_ok=True)
        if result.returncode != 0:
            raise CaptureError(f"satty exited with {result.returncode}: {result.stderr}")
    elif backend.name == "screencapture":
        # -i interactive region/window selection (space toggles window mode)
        result = subprocess.run(["screencapture", "-i", str(dest)], capture_output=True, text=True)
        if result.returncode != 0:
            raise CaptureError(f"screencapture exited with {result.returncode}: {result.stderr}")
    else:  # pragma: no cover
        raise CaptureError(f"Unknown backend: {backend.name}")

    if not dest.exists():
        raise CaptureError(
            "Capture backend exited without saving a file "
            "(did you cancel the capture instead of saving it?)."
        )
    return dest
