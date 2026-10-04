import shutil
import subprocess
import uuid
from pathlib import Path

from .paths import images_dir


class CaptureError(RuntimeError):
    pass


def _detect_backend() -> str:
    if shutil.which("flameshot"):
        return "flameshot"
    if shutil.which("satty"):
        return "satty"
    raise CaptureError(
        "No capture backend found. Install 'flameshot' (X11/cross-platform) "
        "or 'satty' (Wayland) and make sure it's on PATH."
    )


def capture_screenshot() -> Path:
    """Launch the detected backend's interactive capture+annotate UI and return
    the saved PNG path. Blocks until the user finishes annotating and saves/exits.
    """
    backend = _detect_backend()
    dest = images_dir() / f"{uuid.uuid4()}.png"

    if backend == "flameshot":
        # `flameshot gui` opens the interactive region-select + annotate UI and
        # saves directly to --path when the user confirms (Enter/Save).
        result = subprocess.run(
            ["flameshot", "gui", "--path", str(dest)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CaptureError(f"flameshot exited with {result.returncode}: {result.stderr}")
    elif backend == "satty":
        # satty annotates a screenshot it's given; pair it with grim on Wayland
        # for the actual grab, falling back to asking the user to pipe one in.
        if not shutil.which("grim"):
            raise CaptureError(
                "satty backend requires 'grim' to grab the screenshot first "
                "(e.g. `sudo apt install grim`)."
            )
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
    else:  # pragma: no cover - guarded by _detect_backend
        raise CaptureError(f"Unknown backend: {backend}")

    if not dest.exists():
        raise CaptureError(
            "Capture backend exited without saving a file "
            "(did you cancel the capture instead of saving it?)."
        )
    return dest
