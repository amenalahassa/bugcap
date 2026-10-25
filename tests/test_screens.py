"""screens: monitors and windows per OS, from tool output or (Windows) a Win32 shim."""
import json
import subprocess

from bugcap import screens
from bugcap.screens import Monitor, Window

XRANDR = """Monitors: 3
 0: +*eDP-1 1920/344x1080/194+0+0  eDP-1
 1: +HDMI-1 2560/597x1440/336+1920+0  HDMI-1
 2: +DP-2 1280/300x1024/240+-1280+0  DP-2
"""

WMCTRL = """0x01e00003 -1 900  0    0    1920 32   host Top panel
0x03a00003  0 1234 100  52   1200 800  host Login - Mozilla Firefox
0x04200007  0 777  1920 0    2560 1440 host Terminal
0x05000001  0 4242 300  200  500  400  host New bug report
"""

XWININFO = """
xwininfo: Window id: 0x1e6 (the root window) (has no name)

  Root window id: 0x1e6 (the root window) (has no name)
  Parent window id: 0x0 (none)
     3 children:
     0x3a00003 "Login - Mozilla Firefox": ("Navigator" "firefox")  1200x800+100+52  +100+52
        1 child:
        0x3a00004 (has no name): ()  1x1+-1+-1  +99+51
     0x4200007 "Terminal": ("gnome-terminal" "Gnome-terminal")  2560x1440+0+0  +1920+0
     0x4400001 "tiny": ()  10x10+0+0  +0+0
"""


def _run(outputs):
    def runner(argv, **k):
        out = outputs.get(argv[0])
        if out is None:
            raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv, 0, out, "")
    return runner


def test_parse_xrandr_with_primary_and_negative_offset():
    mons = screens.parse_xrandr(XRANDR)
    assert [(m.id, m.x, m.y, m.width, m.height, m.primary) for m in mons] == [
        ("eDP-1", 0, 0, 1920, 1080, True),
        ("HDMI-1", 1920, 0, 2560, 1440, False),
        ("DP-2", -1280, 0, 1280, 1024, False),
    ]


def test_order_puts_primary_first_and_numbers_and_labels():
    raw = [Monitor("B", 1920, 0, 2560, 1440), Monitor("A", 0, 0, 1920, 1080, primary=True)]
    mons = screens.order_monitors(raw)
    assert [m.id for m in mons] == ["A", "B"] and [m.number for m in mons] == [0, 1]
    assert mons[0].label == "Monitor 1 — 1920×1080 (primary)"
    assert mons[1].label == "Monitor 2 — 2560×1440"
    assert mons[1].rect == (1920, 0, 2560, 1440)


def test_parse_wlr_randr_json_uses_current_mode_and_scale():
    data = [{"name": "eDP-1", "enabled": True, "position": {"x": 0, "y": 0}, "scale": 2.0,
             "modes": [{"width": 2880, "height": 1800, "current": True}, {"width": 1920, "height": 1200}]},
            {"name": "HDMI-A-1", "enabled": False, "position": {"x": 0, "y": 0}, "modes": []}]
    mons = screens.parse_wlr_randr(json.dumps(data))
    assert [(m.id, m.x, m.y, m.width, m.height) for m in mons] == [("eDP-1", 0, 0, 1440, 900)]


def test_parse_swaymsg_outputs():
    data = [{"name": "DP-1", "active": True, "primary": False, "focused": True,
             "rect": {"x": 0, "y": 0, "width": 2560, "height": 1440}},
            {"name": "DP-2", "active": False, "rect": {"x": 0, "y": 0, "width": 0, "height": 0}}]
    assert [(m.id, m.width) for m in screens.parse_swaymsg(json.dumps(data))] == [("DP-1", 2560)]


def test_parse_wmctrl_skips_sticky_panels():
    wins = screens.parse_wmctrl(WMCTRL)
    assert [(w.handle, w.title, w.x, w.y, w.width, w.height, w.pid) for w in wins] == [
        ("0x03a00003", "Login - Mozilla Firefox", 100, 52, 1200, 800, 1234),
        ("0x04200007", "Terminal", 1920, 0, 2560, 1440, 777),
        ("0x05000001", "New bug report", 300, 200, 500, 400, 4242),
    ]


def test_parse_xwininfo_keeps_named_top_level_windows():
    wins = screens.parse_xwininfo(XWININFO)
    assert [(w.title, w.x, w.y, w.width) for w in wins] == [
        ("Login - Mozilla Firefox", 100, 52, 1200), ("Terminal", 1920, 0, 2560)]


def test_list_monitors_x11_and_wayland():
    x11 = screens.list_monitors("linux", {"DISPLAY": ":0"}, runner=_run({"xrandr": XRANDR}))
    assert [m.id for m in x11] == ["eDP-1", "HDMI-1", "DP-2"]
    sway = json.dumps([{"name": "DP-1", "active": True, "rect": {"x": 0, "y": 0, "width": 800, "height": 600}}])
    wl = screens.list_monitors("linux", {"WAYLAND_DISPLAY": "wayland-0"}, runner=_run({"swaymsg": sway}))
    assert [m.id for m in wl] == ["DP-1"]


def test_list_monitors_missing_tool_gives_empty_list():
    assert screens.list_monitors("linux", {"DISPLAY": ":0"}, runner=_run({})) == []


def test_list_windows_x11_prefers_wmctrl_then_xwininfo():
    assert [w.title for w in screens.list_windows("linux", {"DISPLAY": ":0"}, runner=_run({"wmctrl": WMCTRL}),
                                                 own_pid=4242)] == ["Login - Mozilla Firefox", "Terminal"]
    via_xwininfo = screens.list_windows("linux", {"DISPLAY": ":0"}, runner=_run({"xwininfo": XWININFO}))
    assert [w.title for w in via_xwininfo] == ["Login - Mozilla Firefox", "Terminal"]
    assert screens.list_windows("linux", {"WAYLAND_DISPLAY": "w"}, runner=_run({"wmctrl": WMCTRL})) == []


class FakeWin:
    def __init__(self, windows=None):
        self._windows = windows if windows is not None else [
            (11, "Editor", 0, 0, 800, 600, False, 500), (12, "", 0, 0, 10, 10, False, 500),
            (13, "Capture what?", 5, 5, 200, 200, False, 4242), (14, "Hidden", 0, 0, 100, 100, True, 500)]
        self.alive = {11: (0, 0, 800, 600, False)}

    def monitors(self):
        return [("\\\\.\\DISPLAY2", -1920, 0, 1920, 1080, False), ("\\\\.\\DISPLAY1", 0, 0, 2560, 1440, True)]

    def windows(self):
        return self._windows  # (handle, title, x, y, w, h, cloaked, pid)

    def window_info(self, handle):
        return self.alive.get(handle)  # (x, y, w, h, minimised) or None when gone


def test_windows_monitors_and_windows_through_the_shim():
    win = FakeWin()
    mons = screens.list_monitors("windows", {}, win=win)
    assert [(m.id, m.primary, m.number, m.x) for m in mons] == [
        ("\\\\.\\DISPLAY1", True, 0, 0), ("\\\\.\\DISPLAY2", False, 1, -1920)]
    wins = screens.list_windows("windows", {}, win=win, own_pid=4242)
    assert [(w.handle, w.title) for w in wins] == [("11", "Editor")]


def test_window_state_on_windows():
    win = FakeWin()
    editor = Window("11", "Editor", 0, 0, 800, 600)
    assert screens.window_state(editor, "windows", win=win) is None
    win.alive[11] = (0, 0, 800, 600, True)
    assert screens.window_state(editor, "windows", win=win) == "window minimised"
    win.alive.pop(11)
    assert screens.window_state(editor, "windows", win=win) == "window closed"


def test_window_state_on_x11_detects_a_move():
    term = Window("0x04200007", "Terminal", 1920, 0, 2560, 1440)
    assert screens.window_state(term, "linux", {"DISPLAY": ":0"}, runner=_run({"wmctrl": WMCTRL})) is None
    moved = WMCTRL.replace("777  1920 0", "777  1900 0")
    assert screens.window_state(term, "linux", {"DISPLAY": ":0"}, runner=_run({"wmctrl": moved})) == "window moved"
    gone = "\n".join(line for line in WMCTRL.splitlines() if "Terminal" not in line)
    assert screens.window_state(term, "linux", {"DISPLAY": ":0"}, runner=_run({"wmctrl": gone})) == "window closed"


def test_session_type():
    assert screens.session_type("win32", {}) == "windows"
    assert screens.session_type("darwin", {}) == "macos"
    assert screens.session_type("linux", {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}) == "wayland"
    assert screens.session_type("linux", {"DISPLAY": ":0"}) == "x11"


def test_enable_dpi_awareness_is_a_no_op_off_windows():
    assert screens.enable_dpi_awareness("linux") is False


def test_own_windows_are_left_out_on_x11():
    wins = screens.list_windows("linux", {"DISPLAY": ":0"}, runner=_run({"wmctrl": WMCTRL}), own_pid=4242)
    assert "New bug report" not in [w.title for w in wins]


def test_own_windows_are_left_out_by_title_without_pids():
    wins = screens.parse_xwininfo(XWININFO.replace('"Terminal"', '"Add to existing bug"'))
    assert [w.title for w in screens.drop_own(wins, own_pid=1)] == ["Login - Mozilla Firefox"]
