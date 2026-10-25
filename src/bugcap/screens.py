"""Monitors and windows of the running desktop, for live mode's "Capture what?" chooser.

Windows uses the Win32 API through `ctypes` (no dependency); Linux reads `xrandr`,
`wmctrl`/`xwininfo` (X11) or `wlr-randr`/`swaymsg` (Wayland); macOS lists the screens
ffmpeg's avfoundation sees. Parsers are pure and every OS call is injectable, so all of it
is testable anywhere. Coordinates are physical pixels on the virtual desktop (x/y may be
negative for a monitor left of or above the primary one)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from .recorder import platform_key


@dataclass(frozen=True)
class Monitor:
    id: str  # device name: \\.\DISPLAY2, HDMI-1, or the avfoundation screen index
    x: int
    y: int
    width: int
    height: int
    primary: bool = False
    number: int = 0  # 0-based position in the order capture tools count screens

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    @property
    def label(self) -> str:
        size = f"{self.width}\u00d7{self.height}" if self.width else "size unknown"
        return f"Monitor {self.number + 1} \u2014 {size}" + (" (primary)" if self.primary else "")


@dataclass(frozen=True)
class Window:
    handle: str  # HWND (Windows) or X11 window id
    title: str
    x: int
    y: int
    width: int
    height: int
    pid: int = 0  # owning process, when the OS says (0: unknown)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


# bugcap's own windows, for when the owning process is unknown (xwininfo)
OWN_TITLES = ("New bug report", "New bug (note only)", "Add to existing bug", "Capture what?")


def drop_own(windows: list[Window], own_pid: Optional[int] = None) -> list[Window]:
    """Leave out live mode's own windows: by process id where known, else by title."""
    own_pid = os.getpid() if own_pid is None else own_pid
    return [w for w in windows
            if w.pid != own_pid and w.title not in OWN_TITLES and not w.title.startswith("bugcap live")]


def session_type(platform: Optional[str] = None, env: Optional[dict] = None) -> str:
    """'windows', 'macos', 'wayland' or 'x11'."""
    key = platform_key(platform)
    if key != "linux":
        return key
    env = os.environ if env is None else env
    return "wayland" if env.get("WAYLAND_DISPLAY") else "x11"


def order_monitors(monitors: list[Monitor]) -> list[Monitor]:
    """Primary first, the rest in the order the OS listed them (how Qt, and so Flameshot,
    numbers screens), each given its `number`."""
    ordered = [m for m in monitors if m.primary] + [m for m in monitors if not m.primary]
    return [Monitor(m.id, m.x, m.y, m.width, m.height, m.primary, n) for n, m in enumerate(ordered)]


# --- parsers (pure) ----------------------------------------------------------------

_XRANDR = re.compile(r"^\s*\d+:\s+\+?(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)", re.M)


def parse_xrandr(text: str) -> list[Monitor]:
    """`xrandr --listactivemonitors`."""
    return [Monitor(name, int(x), int(y), int(w), int(h), primary=bool(star))
            for star, name, w, h, x, y in _XRANDR.findall(text or "")]


def parse_wlr_randr(text: str) -> list[Monitor]:
    """`wlr-randr --json`: enabled outputs, current mode divided by the output scale
    (Wayland tools such as slurp and grim work in these logical pixels)."""
    found = []
    for out in json.loads(text or "[]"):
        if not out.get("enabled"):
            continue
        mode = next((m for m in out.get("modes", []) if m.get("current")), None)
        if mode is None:
            continue
        scale = float(out.get("scale") or 1) or 1
        pos = out.get("position") or {}
        found.append(Monitor(str(out["name"]), int(pos.get("x", 0)), int(pos.get("y", 0)),
                             round(mode["width"] / scale), round(mode["height"] / scale)))
    return found


def parse_swaymsg(text: str) -> list[Monitor]:
    """`swaymsg -t get_outputs` (sway and other wlroots compositors speaking its IPC)."""
    found = []
    for out in json.loads(text or "[]"):
        if not out.get("active"):
            continue
        r = out.get("rect") or {}
        found.append(Monitor(str(out["name"]), int(r.get("x", 0)), int(r.get("y", 0)),
                             int(r.get("width", 0)), int(r.get("height", 0)), bool(out.get("primary"))))
    return found


_WMCTRL = re.compile(
    r"^(0x[0-9a-fA-F]+)\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+\S+\s+(.+)$", re.M)


def parse_wmctrl(text: str) -> list[Window]:
    """`wmctrl -lpG`; sticky windows (desktop -1: panels, docks) are left out."""
    return [Window(wid, title.strip(), int(x), int(y), int(w), int(h), int(pid))
            for wid, desk, pid, x, y, w, h, title in _WMCTRL.findall(text or "") if desk != "-1"]


_XWININFO = re.compile(r'^     (0x[0-9a-fA-F]+) "(.+)": \(.*\)\s+(\d+)x(\d+)\+-?\d+\+-?\d+\s+\+(-?\d+)\+(-?\d+)\s*$', re.M)
MIN_WINDOW = 50  # smaller named windows are tooltips and helpers, not something to record


def parse_xwininfo(text: str) -> list[Window]:
    """`xwininfo -root -tree`: named direct children of the root window."""
    return [Window(wid, title, int(x), int(y), int(w), int(h))
            for wid, title, w, h, x, y in _XWININFO.findall(text or "")
            if int(w) >= MIN_WINDOW and int(h) >= MIN_WINDOW]


_AV_SCREENS = re.compile(r"\[(\d+)\]\s+Capture screen (\d+)")


def parse_avfoundation_screens(text: str) -> list[Monitor]:
    """ffmpeg's avfoundation device list: one entry per screen; the id is the device index."""
    return [Monitor(index, 0, 0, 0, 0, primary=(screen == "0"))
            for index, screen in _AV_SCREENS.findall(text or "")]


# --- the running system --------------------------------------------------------------

def _output(runner, argv: list[str]) -> Optional[str]:
    try:
        result = runner(argv, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 0) != 0:
        return None
    return (result.stdout or "") + (result.stderr or "" if argv[0] == "ffmpeg" else "")


def list_monitors(platform: Optional[str] = None, env: Optional[dict] = None, *,
                  runner=subprocess.run, win=None) -> list[Monitor]:
    """The connected monitors, primary first; empty when they cannot be listed."""
    kind = session_type(platform, env)
    found: list[Monitor] = []
    if kind == "windows":
        win = win or _Win32()
        found = [Monitor(name, x, y, w, h, primary) for name, x, y, w, h, primary in win.monitors()]
    elif kind == "x11":
        found = parse_xrandr(_output(runner, ["xrandr", "--listactivemonitors"]) or "")
    elif kind == "wayland":
        for argv, parse in ((["wlr-randr", "--json"], parse_wlr_randr), (["swaymsg", "-t", "get_outputs"], parse_swaymsg)):
            text = _output(runner, argv)
            if text:
                try:
                    found = parse(text)
                except (ValueError, KeyError, TypeError):
                    found = []
                if found:
                    break
    else:
        argv = ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        try:
            probe = runner(argv, capture_output=True, text=True, timeout=10)
            found = parse_avfoundation_screens((probe.stderr or "") + (probe.stdout or ""))
        except (OSError, subprocess.SubprocessError):
            found = []
    return order_monitors(found)


def list_windows(platform: Optional[str] = None, env: Optional[dict] = None, *,
                 runner=subprocess.run, win=None, own_pid: Optional[int] = None) -> list[Window]:
    """Visible top-level windows with a title (bugcap's own excluded); empty where windows
    cannot be listed (Wayland, macOS)."""
    kind = session_type(platform, env)
    if kind == "windows":
        win = win or _Win32()
        found = [Window(str(h), title, x, y, w, ht, pid) for h, title, x, y, w, ht, cloaked, pid in win.windows()
                 if title and not cloaked and w > 0 and ht > 0]
    elif kind == "x11":
        text = _output(runner, ["wmctrl", "-lpG"])
        if text is not None:
            found = parse_wmctrl(text)
        else:
            found = parse_xwininfo(_output(runner, ["xwininfo", "-root", "-tree"]) or "")
    else:
        return []
    return drop_own(found, own_pid)


def window_state(window: Window, platform: Optional[str] = None, env: Optional[dict] = None, *,
                 runner=subprocess.run, win=None) -> Optional[str]:
    """None while the window can still be recorded as chosen, otherwise why not."""
    kind = session_type(platform, env)
    if kind == "windows":
        info = (win or _Win32()).window_info(int(window.handle))
        if info is None:
            return "window closed"
        return "window minimised" if info[4] else None
    if kind == "x11":
        now = next((w for w in list_windows(platform, env, runner=runner, own_pid=-1)
                    if w.handle == window.handle), None)
        if now is None:
            return "window closed"
        return "window moved" if now.rect != window.rect else None
    return None


def enable_dpi_awareness(platform: Optional[str] = None) -> bool:
    """Make this process DPI-aware on Windows so Tk, the Win32 API and ffmpeg's gdigrab all
    speak physical pixels (otherwise rectangles are scaled on high-DPI monitors). Call before
    the first Tk window. True when it took effect."""
    if platform_key(platform) != "windows" or sys.platform != "win32":
        return False
    import ctypes

    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0  # per-monitor aware
    except (AttributeError, OSError):
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except (AttributeError, OSError):
            return False


class _Win32:  # pragma: no cover - exercised on Windows by hand (see quickstart.md)
    """The few Win32 calls the chooser needs, returning plain tuples."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32
        try:
            self.dwmapi = ctypes.windll.dwmapi
        except OSError:
            self.dwmapi = None

    def monitors(self) -> list[tuple]:
        ctypes, wintypes = self.ctypes, self.wintypes

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

        found = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                  ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def each(hmon, _hdc, _rect, _data):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if self.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                found.append((info.szDevice, r.left, r.top, r.right - r.left, r.bottom - r.top,
                              bool(info.dwFlags & 1)))
            return True

        self.user32.EnumDisplayMonitors(None, None, proc(each), 0)
        return found

    def _rect(self, hwnd) -> Optional[tuple[int, int, int, int]]:
        ctypes, wintypes = self.ctypes, self.wintypes
        rect = wintypes.RECT()
        ok = False
        if self.dwmapi is not None:  # the visible frame, without the invisible resize border
            ok = self.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0
        if not ok and not self.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def _cloaked(self, hwnd) -> bool:
        if self.dwmapi is None:
            return False
        ctypes, wintypes = self.ctypes, self.wintypes
        value = wintypes.DWORD()
        self.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(value), ctypes.sizeof(value))
        return bool(value.value)

    def windows(self) -> list[tuple]:
        ctypes, wintypes = self.ctypes, self.wintypes
        found = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd, _data):
            if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buffer, length + 1)
            rect = self._rect(hwnd)
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if rect is not None:
                found.append((int(hwnd), buffer.value, *rect, self._cloaked(hwnd), pid.value))
            return True

        self.user32.EnumWindows(proc(each), 0)
        return found

    def window_info(self, hwnd: int) -> Optional[tuple]:
        if not self.user32.IsWindow(self.wintypes.HWND(hwnd)):
            return None
        rect = self._rect(hwnd) or (0, 0, 0, 0)
        return (*rect, bool(self.user32.IsIconic(self.wintypes.HWND(hwnd))))
