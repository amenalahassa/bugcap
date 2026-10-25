"""What a live-mode screenshot or recording covers: all screens, one monitor, a drawn region
or one window. Which of these the current platform and tool can honour (and why not), the
size rules for regions, and the last choice, remembered in the user config."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import Callable, Optional

from . import config
from .screens import Monitor, Window

KINDS = ("all", "monitor", "region", "window")
MIN_REGION = 16  # a smaller drag is treated as a cancelled selection
CONFIG_KEY = "live.capture_target"


@dataclass(frozen=True)
class CaptureTarget:
    kind: str = "all"
    monitor: Optional[Monitor] = None
    rect: Optional[tuple[int, int, int, int]] = None  # (x, y, width, height) for a region
    window: Optional[Window] = None
    # size of the coordinate space `rect` was drawn in (Tk points), when it may differ from the
    # recorded pixels (a Retina Mac): the recorder then crops proportionally
    space: Optional[tuple[int, int]] = None

    def describe(self) -> str:
        if self.kind == "monitor" and self.monitor is not None:
            return f"monitor {self.monitor.number + 1}"
        if self.kind == "region" and self.rect is not None:
            return f"a {self.rect[2]}×{self.rect[3]} region"
        if self.kind == "window" and self.window is not None:
            return f"the window “{self.window.title}”"
        return "all screens"


def availability(session: str, backend: str, purpose: str,
                 which: Callable[[str], Optional[str]] = shutil.which) -> dict[str, tuple[bool, str]]:
    """{kind: (enabled, reason)} for a screenshot (`purpose="shot"`) or a recording
    (`"record"`) with `backend` in a `session` from `screens.session_type`. A disabled
    kind always carries the reason shown beside it in the chooser."""
    ok = (True, "")
    result = {"all": ok, "monitor": ok, "region": ok, "window": ok}
    if session == "wayland":
        result["window"] = (False, "Window capture isn't supported on Wayland.")
        if not which("slurp"):
            result["region"] = (False, "Install slurp to draw a region on Wayland.")
    elif session == "x11":
        if not (which("wmctrl") or which("xwininfo")):
            result["window"] = (False, "Install wmctrl to pick a window on X11.")
    elif session == "macos" and purpose == "record":
        result["window"] = (False, "Window recording needs macOS screen-capture APIs bugcap doesn't use.")
    return result


def normalize_rect(rect, for_recording: bool = False) -> Optional[tuple[int, int, int, int]]:
    """None for a selection under 16x16 px; for a recording, the size rounded down to even
    numbers (the H.264 encoder needs them)."""
    x, y, w, h = (int(v) for v in rect)
    if w < MIN_REGION or h < MIN_REGION:
        return None
    if for_recording:
        w, h = w - w % 2, h - h % 2
    return (x, y, w, h)


def remember(target: CaptureTarget) -> None:
    """Keep the chosen kind (and monitor) as the next default. Regions and windows keep only
    their kind: the next capture asks for a new one."""
    saved = {"kind": target.kind}
    if target.kind == "monitor" and target.monitor is not None:
        saved["monitor_id"] = target.monitor.id
        saved["monitor_rect"] = list(target.monitor.rect)
    try:
        config.set_value(CONFIG_KEY, json.dumps(saved))
    except OSError:
        pass  # a default that is not remembered is not worth an error


def recall(monitors: list[Monitor]) -> tuple[CaptureTarget, Optional[str]]:
    """The remembered target, matched against the monitors connected now, plus a note when
    it had to fall back to all screens."""
    try:
        saved = json.loads(config.get(CONFIG_KEY) or "{}")
    except (ValueError, OSError):
        saved = {}
    kind = saved.get("kind") if isinstance(saved, dict) else None
    if kind not in KINDS:
        return CaptureTarget("all"), None
    if kind != "monitor":
        return CaptureTarget(kind), None
    match = next((m for m in monitors if m.id == saved.get("monitor_id")), None)
    if match is None:
        rect = tuple(saved.get("monitor_rect") or ())
        match = next((m for m in monitors if m.rect == rect), None)
    if match is None:
        return CaptureTarget("all"), "The last monitor used is not connected; using all screens."
    return CaptureTarget("monitor", monitor=match), None
