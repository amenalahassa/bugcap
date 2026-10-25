"""T013: has_display(), import_image(), capture_screenshot() per backend (mocked)."""
import subprocess

import pytest

from bugcap import backends, capture
from bugcap.capture import CaptureError


def test_has_display_linux(monkeypatch):
    monkeypatch.setattr(capture.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert capture.has_display() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert capture.has_display() is True
    monkeypatch.delenv("DISPLAY")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert capture.has_display() is True


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_has_display_mac_windows(monkeypatch, platform):
    monkeypatch.setattr(capture.sys, "platform", platform)
    assert capture.has_display() is True


def test_import_image_missing(bugcap_home, tmp_path):
    with pytest.raises(CaptureError, match="not found"):
        capture.import_image(tmp_path / "nope.png")


def test_import_image_copies_and_keeps_suffix(bugcap_home, tmp_path):
    src = tmp_path / "shot.JPG"
    src.write_bytes(b"\xff\xd8\xff data")
    dest = capture.import_image(src)
    assert dest.suffix == ".jpg"
    assert dest.parent == capture.images_dir()
    assert dest.read_bytes() == b"\xff\xd8\xff data"


def _fake_run_writing(dest_index: int):
    """Return a fake subprocess.run that creates the file named at argv[dest_index]."""
    calls = []

    def run(argv, *a, **k):
        calls.append(argv)
        from pathlib import Path

        Path(argv[dest_index]).write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    run.calls = calls
    return run


def test_capture_flameshot(bugcap_home, monkeypatch):
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("flameshot"))
    # Isolate from whatever is actually resolvable (PATH or Windows fallback dirs) on the
    # machine running this test -- that's `backends.resolve`'s own job, covered separately.
    monkeypatch.setattr(backends, "resolve", lambda name: None)
    run = _fake_run_writing(-1)  # flameshot gui --path <dest>
    monkeypatch.setattr(capture.subprocess, "run", run)
    dest = capture.capture_screenshot()
    assert dest.exists()
    assert run.calls[0][0] == "flameshot"


def test_capture_flameshot_uses_resolved_path(bugcap_home, monkeypatch, tmp_path):
    """When flameshot is only reachable via the Windows fallback (bugcap report #1), capture
    must launch it by that resolved path, not the bare name which would just fail to spawn."""
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("flameshot"))
    exe = tmp_path / "flameshot.exe"
    exe.write_text("")
    monkeypatch.setattr(backends, "resolve", lambda name: str(exe) if name == "flameshot" else None)
    run = _fake_run_writing(-1)
    monkeypatch.setattr(capture.subprocess, "run", run)
    dest = capture.capture_screenshot()
    assert dest.exists()
    assert run.calls[0][0] == str(exe)


def test_capture_screencapture(bugcap_home, monkeypatch):
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("screencapture"))
    monkeypatch.setattr(backends, "resolve", lambda name: None)
    run = _fake_run_writing(-1)  # screencapture -i <dest>
    monkeypatch.setattr(capture.subprocess, "run", run)
    dest = capture.capture_screenshot()
    assert dest.exists()
    assert run.calls[0][0] == "screencapture"


def test_capture_satty(bugcap_home, monkeypatch):
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("satty"))
    monkeypatch.setattr(backends, "resolve", lambda name: None)

    def run(argv, *a, **k):
        from pathlib import Path

        if argv[0] == "grim":
            Path(argv[1]).write_bytes(b"raw")
        elif argv[0] == "satty":
            Path(argv[argv.index("--output-filename") + 1]).write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(capture.subprocess, "run", run)
    dest = capture.capture_screenshot()
    assert dest.exists()


def test_capture_no_backend_mentions_setup(bugcap_home, monkeypatch):
    monkeypatch.setattr(backends, "detect", lambda: None)
    with pytest.raises(CaptureError, match="bugcap setup"):
        capture.capture_screenshot()


# --- capture targets (live mode) ---------------------------------------------------

from bugcap.screens import Monitor, Window  # noqa: E402
from bugcap.targets import CaptureTarget  # noqa: E402

MON2 = Monitor("DP-2", -1920, 0, 1920, 1080, False, 1)
REGION = CaptureTarget("region", rect=(100, 50, 800, 600))
WIN = CaptureTarget("window", window=Window("11", "Editor", 10, 20, 640, 480))


def build(backend, target, platform="windows"):
    return capture.build_screenshot_argv(backend, target, "D.png", platform=platform, raw="RAW.png")


def test_screenshot_argv_without_a_target_is_unchanged():
    assert build("flameshot", None) == [["flameshot", "gui", "--path", "D.png"]]
    assert build("flameshot", CaptureTarget("all")) == [["flameshot", "gui", "--path", "D.png"]]
    assert build("screencapture", None, "macos") == [["screencapture", "-i", "D.png"]]
    assert build("satty", None, "linux") == [
        ["grim", "RAW.png"], ["satty", "--filename", "RAW.png", "--output-filename", "D.png"]]


def test_flameshot_targets():
    assert build("flameshot", CaptureTarget("monitor", monitor=MON2)) == [
        ["flameshot", "screen", "-n", "1", "-e", "--path", "D.png"]]
    assert build("flameshot", REGION) == [["flameshot", "gui", "--region", "800x600+100+50", "--path", "D.png"]]
    assert build("flameshot", WIN) == [["flameshot", "gui", "--region", "640x480+10+20", "--path", "D.png"]]


def test_grim_targets():
    shot = build("satty", CaptureTarget("monitor", monitor=MON2), "linux")
    assert shot[0] == ["grim", "-o", "DP-2", "RAW.png"]
    assert build("satty", REGION, "linux")[0] == ["grim", "-g", "100,50 800x600", "RAW.png"]
    with pytest.raises(capture.TargetUnsupported):
        build("satty", WIN, "linux")


def test_screencapture_targets():
    assert build("screencapture", CaptureTarget("monitor", monitor=MON2), "macos") == [
        ["screencapture", "-D", "2", "D.png"]]
    assert build("screencapture", REGION, "macos") == [["screencapture", "-R", "100,50,800,600", "D.png"]]
    assert build("screencapture", WIN, "macos") == [["screencapture", "-i", "-w", "D.png"]]


def test_capture_screenshot_runs_the_target_command(bugcap_home, monkeypatch):
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("flameshot"))
    monkeypatch.setattr(backends, "resolve", lambda name: None)
    run = _fake_run_writing(-1)
    monkeypatch.setattr(capture.subprocess, "run", run)
    assert capture.capture_screenshot(REGION).exists()
    assert run.calls[0][:4] == ["flameshot", "gui", "--region", "800x600+100+50"]
