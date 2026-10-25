import pytest

from bugcap import recorder


def ffmpeg(platform, fmt="video", **kw):
    return recorder.build_capture_argv("ffmpeg", platform, fmt, kw.pop("fps", 30), kw.pop("max_seconds", 30),
                                       "/m/out.mp4", **kw)


def _has(argv, *seq):
    return any(argv[i:i + len(seq)] == list(seq) for i in range(len(argv)))


def test_linux_x11grab():
    argv = ffmpeg("linux", display=":1", fps=10)
    assert _has(argv, "-f", "x11grab", "-framerate", "10", "-i", ":1")


def test_windows_gdigrab():
    assert _has(ffmpeg("windows"), "-f", "gdigrab", "-framerate", "30", "-i", "desktop")


def test_macos_avfoundation_uses_device_index():
    argv = ffmpeg("macos", av_index=2)
    assert _has(argv, "-f", "avfoundation") and _has(argv, "-i", "2:none")


def test_video_encoding_flags_and_duration_cap():
    argv = ffmpeg("linux", max_seconds=12)
    assert _has(argv, "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p")
    assert _has(argv, "-t", "12")
    assert argv[-1] == "/m/out.mp4"


def test_webm_alternative():
    argv = ffmpeg("linux", codec="vp9")
    assert "libvpx-vp9" in argv and "libx264" not in argv


def test_wf_recorder_argv():
    argv = recorder.build_capture_argv("wf-recorder", "linux", "video", 30, 30, "/m/out.mp4")
    assert argv[:3] == ["wf-recorder", "-r", "30"] and argv[-2:] == ["-f", "/m/out.mp4"]


def test_animated_postprocess_is_palette_two_pass_960_wide():
    argv = recorder.build_postprocess_argv("animated", "in.mp4", "out.gif", 5)
    graph = argv[argv.index("-vf") + 1]
    assert "palettegen" in graph and "paletteuse" in graph and "960" in graph and "fps=5" in graph
    assert argv[-1] == "out.gif"


def test_frames_postprocess_limits_to_eight():
    argv = recorder.build_postprocess_argv("frames", "in.mp4", "f-%03d.png", 0.5, max_frames=8)
    assert _has(argv, "-frames:v", "8") and "fps=0.5000" in argv[argv.index("-vf") + 1]


def test_unknown_format():
    with pytest.raises(ValueError):
        recorder.build_capture_argv("ffmpeg", "linux", "gif", 5, 5, "o.mp4")
    with pytest.raises(ValueError):
        recorder.build_postprocess_argv("video", "a", "b", 5)


def test_detect_recorder_preferences():
    both = lambda n: f"/usr/bin/{n}"
    only_ffmpeg = lambda n: "/usr/bin/ffmpeg" if n == "ffmpeg" else None
    assert recorder.detect_recorder("linux", {"WAYLAND_DISPLAY": "w"}, both).name == "wf-recorder"
    assert recorder.detect_recorder("linux", {"DISPLAY": ":0"}, both).name == "ffmpeg"
    assert recorder.detect_recorder("linux", {"WAYLAND_DISPLAY": "w"}, only_ffmpeg).name == "ffmpeg"
    assert recorder.detect_recorder("macos", {"WAYLAND_DISPLAY": "w"}, both).name == "ffmpeg"
    assert recorder.detect_recorder("linux", {}, lambda n: None) is None


# --- capture targets ----------------------------------------------------------------

from bugcap.screens import Monitor, Window  # noqa: E402
from bugcap.targets import CaptureTarget  # noqa: E402

MON = CaptureTarget("monitor", monitor=Monitor("DP-2", -1920, 0, 1920, 1080, False, 1))
REGION = CaptureTarget("region", rect=(100, 50, 801, 601))
WIN = CaptureTarget("window", window=Window("11", "Login - Firefox", 10, 20, 640, 480))


def test_gdigrab_monitor_and_region():
    argv = ffmpeg("windows", target=MON)
    assert _has(argv, "-f", "gdigrab", "-framerate", "30", "-offset_x", "-1920", "-offset_y", "0",
                "-video_size", "1920x1080", "-i", "desktop")
    assert _has(ffmpeg("windows", target=REGION), "-offset_x", "100", "-offset_y", "50", "-video_size", "800x600")


def test_gdigrab_window_follows_the_title():
    assert _has(ffmpeg("windows", target=WIN), "-i", "title=Login - Firefox")


def test_x11grab_region_and_window():
    assert _has(ffmpeg("linux", display=":1", target=REGION), "-video_size", "800x600", "-i", ":1+100,50")
    assert _has(ffmpeg("linux", target=WIN), "-video_size", "640x480", "-i", ":0.0+10,20")


def test_avfoundation_monitor_and_region():
    second_screen = CaptureTarget("monitor", monitor=Monitor("4", 0, 0, 0, 0, False, 1))
    assert _has(ffmpeg("macos", av_index=3, target=second_screen), "-i", "4:none")
    argv = ffmpeg("macos", av_index=3)
    assert _has(argv, "-i", "3:none")
    argv = ffmpeg("macos", av_index=3, target=REGION)
    assert any(a.startswith("crop=800:600:100:50,") for a in argv)
    with pytest.raises(recorder.TargetUnsupported):
        ffmpeg("macos", target=WIN)


def test_wf_recorder_targets():
    def wf(target):
        return recorder.build_capture_argv("wf-recorder", "linux", "video", 30, 30, "/m/out.mp4", target=target)

    assert _has(wf(MON), "-o", "DP-2")
    assert _has(wf(REGION), "-g", "100,50 800x600")
    with pytest.raises(recorder.TargetUnsupported):
        wf(WIN)


def test_fragmented_mp4_only_with_a_target():
    assert _has(ffmpeg("windows", target=REGION), "-movflags", "+frag_keyframe+empty_moov")
    assert "-movflags" not in ffmpeg("windows")
    assert "-movflags" not in ffmpeg("windows", target=CaptureTarget("all"))


@pytest.mark.parametrize("platform", ["linux", "windows", "macos"])
def test_no_target_is_byte_identical(platform):
    assert ffmpeg(platform, target=None) == ffmpeg(platform)
    assert ffmpeg(platform, target=CaptureTarget("all")) == ffmpeg(platform)


def test_avfoundation_region_is_scaled_from_the_drawn_space():
    """On a Retina Mac Tk draws in points but avfoundation records pixels, so the crop is
    relative to the screen the region was drawn on."""
    drawn = CaptureTarget("region", rect=(100, 50, 800, 600), space=(1440, 900))
    argv = ffmpeg("macos", av_index=1, target=drawn)
    assert any(a.startswith("crop=w=iw*800/1440:h=ih*600/900:x=iw*100/1440:y=ih*50/900,") for a in argv)
