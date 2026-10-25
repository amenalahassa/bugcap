"""Open a file (or a folder of frames) in the application the OS uses for it. Live mode uses
this to preview staged attachments, videos included; nothing here raises into the UI."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .recorder import platform_key


def open_argv(path, platform: Optional[str] = None) -> Optional[list[str]]:
    """The launcher command for `path`; None on Windows, where `os.startfile` is used."""
    key = platform_key(platform)
    if key == "windows":
        return None
    return ["open" if key == "macos" else "xdg-open", str(path)]


def open_path(
    path,
    *,
    platform: Optional[str] = None,
    runner=subprocess.run,
    startfile: Optional[Callable[[str], None]] = getattr(os, "startfile", None),
    timeout: float = 3,
) -> Optional[str]:
    """Open `path`; None on success, otherwise a message for the status line."""
    path = Path(path)
    if not path.exists():
        return f"File not found: {path}"
    failed = f"No application to open {path.name}. It is at {path}."
    argv = open_argv(path, platform)
    if argv is None:
        if startfile is None:
            return failed
        try:
            startfile(str(path))
        except OSError:
            return failed
        return None
    try:
        result = runner(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None  # the launcher is still busy starting the app: it found one
    except OSError:
        return failed
    return failed if getattr(result, "returncode", 0) != 0 else None
