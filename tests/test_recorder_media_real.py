"""Needs a real ffmpeg/ffprobe: output of the post-processing stage is small and playable."""
import shutil
import subprocess

import pytest

from bugcap import recorder

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


def _source(tmp_path, seconds=10):
    src = tmp_path / "src.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
         "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", str(src)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg cannot encode libx264 here: {result.stderr[-200:]}")
    return src


def _probe(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return float(out.stdout.strip())


def test_video_output_is_playable(tmp_path):
    assert _probe(_source(tmp_path)) == pytest.approx(10, abs=0.5)


def test_ten_second_animated_at_defaults_is_at_most_5_mb_and_playable(tmp_path):
    src = _source(tmp_path)
    out = tmp_path / "out.gif"
    argv = recorder.build_postprocess_argv("animated", str(src), str(out), 5)
    subprocess.run(argv, check=True, capture_output=True)
    assert 0 < out.stat().st_size <= 5 * 1024 * 1024
    assert _probe(out) > 5


def test_frames_are_at_most_eight(tmp_path):
    src = _source(tmp_path)
    argv = recorder.build_postprocess_argv("frames", str(src), str(tmp_path / "f-%03d.png"), 0.8, 8)
    subprocess.run(argv, check=True, capture_output=True)
    assert 1 <= len(list(tmp_path.glob("f-*.png"))) <= 8
