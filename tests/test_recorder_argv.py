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
