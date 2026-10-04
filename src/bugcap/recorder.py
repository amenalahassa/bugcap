"""Screen recording: ffmpeg (all OSes) or wf-recorder (Wayland), producing a video, an animated
GIF, or a few keyframes. Argument construction is pure (testable per OS without running
anything); `run_recording` owns the process, the stop/cap watchdogs and safe finalization."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .backends import Backend
from .paths import media_dir

FORMATS = ("video", "frames", "animated")

RECORD_BACKENDS = [
    Backend(
        name="ffmpeg",
        binaries=["ffmpeg"],
        description="Cross-platform screen recording (X11, Windows, macOS)",
        platforms=("linux", "macos", "windows"),
        annotates=False,
        installs={
            "linux": [
                ("apt-get", ["apt-get", "install", "-y", "ffmpeg"]),
                ("dnf", ["dnf", "install", "-y", "ffmpeg"]),
                ("pacman", ["pacman", "-S", "--noconfirm", "ffmpeg"]),
                ("zypper", ["zypper", "install", "-y", "ffmpeg"]),
                ("brew", ["brew", "install", "ffmpeg"]),
            ],
            "macos": [("brew", ["brew", "install", "ffmpeg"])],
            "windows": [
                ("winget", ["winget", "install", "--id", "Gyan.FFmpeg", "-e"]),
                ("scoop", ["scoop", "install", "ffmpeg"]),
                ("choco", ["choco", "install", "-y", "ffmpeg"]),
            ],
        },
        manual={
            "linux": "Install ffmpeg from your distro (e.g. sudo apt install ffmpeg).",
            "macos": "brew install ffmpeg",
            "windows": "winget install Gyan.FFmpeg, or https://ffmpeg.org/download.html",
        },
    ),
    Backend(
        name="wf-recorder",
        binaries=["wf-recorder"],
        description="Wayland screen recording (ffmpeg's x11grab cannot capture Wayland)",
        platforms=("linux",),
        annotates=False,
        installs={
            "linux": [
                ("apt-get", ["apt-get", "install", "-y", "wf-recorder"]),
                ("dnf", ["dnf", "install", "-y", "wf-recorder"]),
                ("pacman", ["pacman", "-S", "--noconfirm", "wf-recorder"]),
                ("zypper", ["zypper", "install", "-y", "wf-recorder"]),
            ]
        },
        manual={"linux": "Install wf-recorder from your distro, or https://github.com/ammen99/wf-recorder"},
    ),
]

MACOS_PERMISSION_HELP = (
    "macOS blocked screen recording. Open System Settings > Privacy & Security > Screen Recording, "
    "allow your terminal app, then run the command again."
)
WAYLAND_HELP = (
    "Recording a Wayland session needs wf-recorder (ffmpeg's x11grab cannot capture Wayland). "
    "Install it, e.g. sudo apt install wf-recorder."
)


class RecorderError(RuntimeError):
    def __init__(self, message: str, guidance: Optional[str] = None):
        super().__init__(message)
        self.guidance = guidance


def platform_key(platform: Optional[str] = None) -> str:
    platform = platform or sys.platform
    if platform in ("windows", "win32"):
        return "windows"
    if platform in ("macos", "darwin"):
        return "macos"
    return "linux"


def by_name(name: str) -> Backend:
    for backend in RECORD_BACKENDS:
        if backend.name == name:
            return backend
    raise KeyError(name)


def detect_recorder(platform: Optional[str] = None, env: Optional[dict] = None, which=shutil.which) -> Optional[Backend]:
    """wf-recorder on Wayland when installed, otherwise ffmpeg, otherwise None."""
    platform = platform_key(platform)
    env = os.environ if env is None else env
    if platform == "linux" and env.get("WAYLAND_DISPLAY") and which("wf-recorder"):
        return by_name("wf-recorder")
    if which("ffmpeg"):
        return by_name("ffmpeg")
    return None


# --- argument construction (pure) ----------------------------------------------

def _scale_filter(width: int = 960) -> str:
    return f"scale='min({width},iw)':-2:flags=lanczos"


def build_capture_argv(
    backend: str,
    platform: str,
    fmt: str,
    fps: int,
    max_seconds: int,
    out_path: str,
    display: Optional[str] = None,
    codec: str = "h264",
    av_index: int = 0,
) -> list[str]:
    """The command that records the screen to `out_path` (always a real video; animated and
    frames are derived from it afterwards)."""
    platform = platform_key(platform)
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    vp9 = codec == "vp9" and fmt == "video"
    if backend == "wf-recorder":
        argv = ["wf-recorder", "-r", str(fps)]
        argv += ["-c", "libvpx-vp9"] if vp9 else ["-c", "libx264", "-x", "yuv420p"]
        return argv + ["-f", out_path]

    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"]
    if platform == "linux":
        argv += ["-f", "x11grab", "-framerate", str(fps), "-i", display or ":0.0"]
    elif platform == "windows":
        argv += ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop"]
    else:
        argv += ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1", "-i", f"{av_index}:none"]
    argv += ["-t", str(max_seconds)]
    argv += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
    if vp9:
        argv += ["-c:v", "libvpx-vp9", "-crf", "35", "-b:v", "0"]
    else:
        argv += ["-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
    return argv + [out_path]


def build_postprocess_argv(fmt: str, in_path: str, out_path: str, fps: float, max_frames: int = 8) -> list[str]:
    """Derive an animated GIF (palette two-pass in one filter graph) or keyframes (`out_path`
    is a printf pattern such as `frame-%03d.png`) from a recorded video."""
    if fmt == "animated":
        graph = f"fps={fps:g},{_scale_filter()},split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse"
        return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", in_path,
                "-vf", graph, "-loop", "0", out_path]
    if fmt == "frames":
        return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", in_path,
                "-vf", f"fps={fps:.4f},{_scale_filter(1280)}", "-frames:v", str(max_frames), out_path]
    raise ValueError(f"no post-processing for format {fmt!r}")


_AV_SCREEN = re.compile(r"\[(\d+)\]\s+Capture screen \d+")


def parse_avfoundation_screen_index(output: str) -> int:
    match = _AV_SCREEN.search(output)
    if not match:
        raise RecorderError("no screen capture device found by ffmpeg/avfoundation", MACOS_PERMISSION_HELP)
    return int(match.group(1))


def diagnose_failure(stderr: str, platform: str) -> Optional[str]:
    text = stderr or ""
    platform = platform_key(platform)
    if platform == "macos" and re.search(r"Input/output error|not permitted|permission|denied", text, re.I):
        return MACOS_PERMISSION_HELP
    if platform == "linux" and re.search(r"Cannot open display|x11grab|Could not open", text, re.I):
        return WAYLAND_HELP
    return None


# --- running -------------------------------------------------------------------

@dataclass
class RecordResult:
    path: Optional[Path]
    size_bytes: int
    reason: str
    duration: float
    kind: str
    mime: str
    frames: list = field(default_factory=list)  # [(path, size)]


def _size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _stop_process(proc, backend: str, platform: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if backend == "ffmpeg":
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
            except (OSError, ValueError, AttributeError):
                proc.terminate()
        elif platform_key(platform) == "windows":  # pragma: no cover
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_recording(
    backend: str,
    fmt: str,
    fps: int,
    max_seconds: int,
    max_mb: float,
    out_dir: Optional[Path] = None,
    wait_for_stop: Callable[[], bool] = lambda: False,
    *,
    platform: Optional[str] = None,
    env: Optional[dict] = None,
    codec: str = "h264",
    popen=subprocess.Popen,
    runner=subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    size_of: Callable[[object], int] = _size,
    poll_interval: float = 0.2,
) -> RecordResult:
    """Record until `wait_for_stop()` is true, Ctrl+C, or a cap is hit; always wait for the
    recorder to exit so the file is complete; then derive animated/frames if requested."""
    platform = platform_key(platform)
    env = os.environ if env is None else env
    try:
        out_dir = Path(out_dir) if out_dir else media_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RecorderError(f"cannot use the output folder: {exc.strerror or exc}") from exc
    if not os.access(out_dir, os.W_OK):
        raise RecorderError(f"the output folder is not writable: {out_dir}")
    stem = uuid.uuid4().hex
    ext = ".webm" if (codec == "vp9" and fmt == "video") else ".mp4"
    raw = out_dir / f"{stem}{ext}"

    av_index = 0
    if backend == "ffmpeg" and platform == "macos":
        probe = runner(["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                       capture_output=True, text=True)
        av_index = parse_avfoundation_screen_index((probe.stderr or "") + (probe.stdout or ""))

    argv = build_capture_argv(backend, platform, fmt, fps, max_seconds, str(raw),
                              display=env.get("DISPLAY"), codec=codec, av_index=av_index)
    log = tempfile.TemporaryFile()
    try:
        proc = popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
    except OSError as exc:
        log.close()
        raise RecorderError(f"could not start {backend}: {exc}", guidance_for(backend, platform)) from exc

    started = clock()
    reason = "stopped by user"
    max_bytes = int(max_mb * 1024 * 1024)
    try:
        while True:
            if proc.poll() is not None:
                reason = "recorder exited"
                break
            if wait_for_stop():
                reason = "stopped by user"
                break
            if clock() - started >= max_seconds:
                reason = "duration cap"
                break
            if size_of(raw) >= max_bytes:
                reason = "size cap"
                break
            sleep(poll_interval)
    except KeyboardInterrupt:
        reason = "interrupted"
    def _finish() -> RecordResult:
        duration = clock() - started
        _stop_process(proc, backend, platform)

        log.seek(0)
        stderr_text = log.read().decode("utf-8", "replace")
        log.close()
        if size_of(raw) == 0:
            raw_exists = Path(raw).exists()
            if raw_exists:
                Path(raw).unlink(missing_ok=True)
            raise RecorderError(
                "the recording is empty" + (f": {stderr_text.strip().splitlines()[-1]}" if stderr_text.strip() else ""),
                diagnose_failure(stderr_text, platform),
            )

        if fmt == "video":
            mime = "video/webm" if raw.suffix == ".webm" else "video/mp4"
            return RecordResult(raw, size_of(raw), reason, duration, "video", mime)

        if fmt == "animated":
            out = out_dir / f"{stem}.gif"
            try:
                _run_checked(runner, build_postprocess_argv("animated", str(raw), str(out), min(fps, 8)))
            except RecorderError:
                raw.unlink(missing_ok=True)
                out.unlink(missing_ok=True)
                raise
            raw.unlink(missing_ok=True)
            return RecordResult(out, size_of(out), reason, duration, "animated", "image/gif")

        frames_dir = out_dir / f"{stem}-frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(frames_dir / "frame-%03d.png")
        per_second = 8 / max(duration, 1.0)
        try:
            _run_checked(runner, build_postprocess_argv("frames", str(raw), pattern, min(float(fps), per_second), 8))
            frames = [(str(p), size_of(p)) for p in sorted(frames_dir.glob("frame-*.png"))]
            if not frames:
                raise RecorderError("no frames could be extracted from the recording")
        except RecorderError:
            shutil.rmtree(frames_dir, ignore_errors=True)
            raise
        finally:
            raw.unlink(missing_ok=True)
        return RecordResult(None, sum(s for _, s in frames), reason, duration, "frames", "image/png", frames)

    try:
        return _finish()
    except KeyboardInterrupt:
        # Ctrl+C while finalizing: never attach (or leave behind) a partial file.
        if proc.poll() is None:
            proc.kill()
        for leftover in (raw, out_dir / f"{stem}.gif"):
            Path(leftover).unlink(missing_ok=True)
        shutil.rmtree(out_dir / f"{stem}-frames", ignore_errors=True)
        raise RecorderError("interrupted while finishing the recording; nothing was attached") from None


def discard(result: "RecordResult") -> None:
    """Delete the files of a recording that will not be attached."""
    if result.path:
        Path(result.path).unlink(missing_ok=True)
    for frame_path, _ in result.frames:
        Path(frame_path).unlink(missing_ok=True)
    if result.frames:
        try:
            Path(result.frames[0][0]).parent.rmdir()
        except OSError:
            pass


def _run_checked(runner, argv: list[str]) -> None:
    try:
        result = runner(argv, capture_output=True, text=True)
    except OSError as exc:
        raise RecorderError(
            "ffmpeg is needed to make animated/frames output", guidance_for("ffmpeg")
        ) from exc
    if getattr(result, "returncode", 0) != 0:
        raise RecorderError(f"ffmpeg post-processing failed: {(getattr(result, 'stderr', '') or '').strip()[-300:]}")


def guidance_for(backend: str, platform: Optional[str] = None) -> str:
    b = by_name(backend)
    key = platform_key(platform)
    return b.manual.get(key, "See the project's website for install steps.")
