"""targets: what can be captured where, region rules, remembering the last choice."""
import pytest

from bugcap import targets
from bugcap.screens import Monitor
from bugcap.targets import CaptureTarget


def _tools(*present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


def test_windows_with_flameshot_and_ffmpeg_allows_everything():
    for purpose, backend in (("shot", "flameshot"), ("record", "ffmpeg")):
        av = targets.availability("windows", backend, purpose, which=_tools())
        assert all(enabled for enabled, _ in av.values()), av


def test_wayland_window_and_region_rules():
    av = targets.availability("wayland", "wf-recorder", "record", which=_tools())
    assert av["window"] == (False, "Window capture isn't supported on Wayland.")
    assert av["region"] == (False, "Install slurp to draw a region on Wayland.")
    assert av["monitor"][0] and av["all"][0]
    assert targets.availability("wayland", "satty", "shot", which=_tools("slurp"))["region"][0]


def test_x11_window_needs_a_window_lister():
    assert targets.availability("x11", "ffmpeg", "record", which=_tools())["window"] == (
        False, "Install wmctrl to pick a window on X11.")
    assert targets.availability("x11", "ffmpeg", "record", which=_tools("xwininfo"))["window"][0]


def test_macos_window_recording_is_unavailable_but_screenshots_work():
    assert not targets.availability("macos", "ffmpeg", "record", which=_tools())["window"][0]
    assert targets.availability("macos", "screencapture", "shot", which=_tools())["window"][0]


def test_normalize_rect():
    assert targets.normalize_rect((0, 0, 15, 300)) is None
    assert targets.normalize_rect((10, 20, 801, 601)) == (10, 20, 801, 601)
    assert targets.normalize_rect((10, 20, 801, 601), for_recording=True) == (10, 20, 800, 600)
    assert targets.normalize_rect((5, 5, 40, 30), for_recording=True) == (5, 5, 40, 30)


MONITORS = [Monitor("\\\\.\\DISPLAY1", 0, 0, 2560, 1440, True, 0), Monitor("\\\\.\\DISPLAY2", 2560, 0, 1920, 1080, False, 1)]


def test_remember_and_recall_a_monitor(bugcap_home):
    targets.remember(CaptureTarget("monitor", monitor=MONITORS[1]))
    target, note = targets.recall(MONITORS)
    assert target.kind == "monitor" and target.monitor == MONITORS[1] and note is None


def test_recall_matches_by_rect_when_the_name_changed(bugcap_home):
    targets.remember(CaptureTarget("monitor", monitor=MONITORS[1]))
    renamed = [MONITORS[0], Monitor("\\\\.\\DISPLAY7", 2560, 0, 1920, 1080, False, 1)]
    target, note = targets.recall(renamed)
    assert target.monitor.id == "\\\\.\\DISPLAY7" and note is None


def test_recall_falls_back_to_all_screens(bugcap_home):
    targets.remember(CaptureTarget("monitor", monitor=MONITORS[1]))
    target, note = targets.recall(MONITORS[:1])
    assert target.kind == "all" and note == "The last monitor used is not connected; using all screens."


@pytest.mark.parametrize("kind", ["region", "window", "all"])
def test_region_and_window_remember_only_the_kind(bugcap_home, kind):
    targets.remember(CaptureTarget(kind, rect=(1, 2, 300, 200)))
    target, note = targets.recall(MONITORS)
    assert target.kind == kind and target.rect is None and note is None


def test_recall_with_nothing_remembered(bugcap_home):
    assert targets.recall(MONITORS) == (CaptureTarget("all"), None)


def test_describe():
    assert CaptureTarget("all").describe() == "all screens"
    assert CaptureTarget("monitor", monitor=MONITORS[1]).describe() == "monitor 2"
    assert CaptureTarget("region", rect=(0, 0, 800, 600)).describe() == "a 800×600 region"
