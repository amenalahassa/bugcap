import signal
import subprocess
from pathlib import Path

import pytest

from bugcap import recorder


class FakeStdin:
    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, exit_on_stop=True):
        self.stdin = FakeStdin()
        self.exited = False
        self.signals = []
        self.waited = False
        self.exit_on_stop = exit_on_stop

    def poll(self):
        return 0 if self.exited else None

    def wait(self, timeout=None):
        self.waited = True
        self.exited = True

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.exited = True

    def kill(self):
        self.exited = True


class Env:
    """Fake clock + popen/runner/size hooks."""

    def __init__(self, tmp_path, size=1000):
        self.now = 0.0
        self.proc = FakeProc()
        self.argvs = []
        self.size = size
        self.tmp = tmp_path
        self.runs = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def popen(self, argv, **kw):
        self.argvs.append(argv)
        return self.proc

    def size_of(self, path):
        return self.size

    def runner(self, argv, **kw):
        self.runs.append(argv)
        out = argv[-1]
        if "%03d" in out:
            for n in (1, 2):
                (self.tmp / f"frame-00{n}.png").write_bytes(b"x" * 10)
        else:
            open(out, "wb").write(b"gif")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def kwargs(self, **extra):
        base = dict(platform="linux", env={"DISPLAY": ":0"}, popen=self.popen, runner=self.runner,
                    clock=self.clock, sleep=self.sleep, size_of=self.size_of)
        base.update(extra)
        return base


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def run(env, tmp_path, backend="ffmpeg", fmt="video", max_seconds=30, max_mb=25, wait=lambda: False, **extra):
    return recorder.run_recording(backend, fmt, 5, max_seconds, max_mb, tmp_path, wait, **env.kwargs(**extra))


def test_enter_sends_q_to_ffmpeg_and_waits(env, tmp_path):
    ticks = iter([False, False, True])
    result = run(env, tmp_path, wait=lambda: next(ticks))
    assert env.proc.stdin.written == [b"q"] and env.proc.stdin.closed
    assert env.proc.waited
    assert result.reason == "stopped by user" and result.kind == "video" and result.mime == "video/mp4"


def test_ctrl_c_takes_the_same_path(env, tmp_path):
    def interrupt():
        raise KeyboardInterrupt

    result = run(env, tmp_path, wait=interrupt)
    assert result.reason == "interrupted" and env.proc.stdin.written == [b"q"] and env.proc.waited


def test_wf_recorder_stopped_with_sigint(env, tmp_path):
    result = run(env, tmp_path, backend="wf-recorder", wait=lambda: True)
    assert env.proc.signals == [signal.SIGINT] and env.proc.stdin.written == []
    assert env.argvs[0][0] == "wf-recorder" and result.size_bytes == 1000


def test_duration_cap(env, tmp_path):
    result = run(env, tmp_path, max_seconds=2)
    assert result.reason == "duration cap" and result.duration >= 2


def test_size_cap(env, tmp_path):
    env.size = 3 * 1024 * 1024
    result = run(env, tmp_path, max_mb=2)
    assert result.reason == "size cap"


def test_recorder_exiting_by_itself(env, tmp_path):
    env.proc.exited = True
    assert run(env, tmp_path).reason == "recorder exited"


def test_empty_output_is_an_error(env, tmp_path):
    env.size = 0
    with pytest.raises(recorder.RecorderError) as exc:
        run(env, tmp_path, wait=lambda: True)
    assert "empty" in str(exc.value)


def test_macos_permission_guidance_from_stderr():
    text = "[avfoundation @ 0x1] Error: Input/output error"
    assert "Screen Recording" in recorder.diagnose_failure(text, "macos")
    assert recorder.diagnose_failure(text, "linux") is None
    assert "wf-recorder" in recorder.diagnose_failure("Cannot open display :0", "linux")
    assert recorder.diagnose_failure("fine", "macos") is None


def test_animated_runs_postprocess_and_removes_raw(env, tmp_path):
    result = run(env, tmp_path, fmt="animated", wait=lambda: True)
    assert result.kind == "animated" and result.mime == "image/gif" and result.path.suffix == ".gif"
    assert "palettegen" in env.runs[0][env.runs[0].index("-vf") + 1]


def test_frames_result(env, tmp_path):

    def runner(argv, **kw):
        pattern = argv[-1]
        folder = Path(pattern).parent
        for n in (1, 2, 3):
            (folder / f"frame-00{n}.png").write_bytes(b"x")
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = recorder.run_recording("ffmpeg", "frames", 5, 30, 25, tmp_path, lambda: True,
                                    **env.kwargs(runner=runner))
    assert result.kind == "frames" and len(result.frames) == 3 and result.path is None
    assert [Path(p).name for p, _ in result.frames] == ["frame-001.png", "frame-002.png", "frame-003.png"]


def test_macos_probes_screen_device(env, tmp_path):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "[AVFoundation indev @ 0x1] [3] Capture screen 0\n")

    run(env, tmp_path, platform="macos", wait=lambda: True, runner=runner)
    assert "3:none" in env.argvs[0]


def test_missing_binary_is_a_recorder_error(env, tmp_path):
    def popen(argv, **kw):
        raise FileNotFoundError("ffmpeg")

    with pytest.raises(recorder.RecorderError) as exc:
        run(env, tmp_path, popen=popen)
    assert exc.value.guidance


def test_failed_animated_postprocess_leaves_no_files(env, tmp_path):
    def runner(argv, **kw):
        open(argv[-1], "wb").write(b"partial")
        return subprocess.CompletedProcess(argv, 1, "", "filter error")

    with pytest.raises(recorder.RecorderError):
        run(env, tmp_path, fmt="animated", wait=lambda: True, runner=runner)
    assert list(tmp_path.iterdir()) == []


def test_failed_frames_extraction_leaves_no_files(env, tmp_path):
    def runner(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "", "")  # succeeds but produces nothing

    with pytest.raises(recorder.RecorderError):
        run(env, tmp_path, fmt="frames", wait=lambda: True, runner=runner)
    assert list(tmp_path.iterdir()) == []


def test_discard_removes_gif_and_frames(tmp_path):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"x")
    d = tmp_path / "frames"
    d.mkdir()
    (d / "f1.png").write_bytes(b"x")
    recorder.discard(recorder.RecordResult(gif, 1, "r", 1, "animated", "image/gif"))
    recorder.discard(recorder.RecordResult(None, 1, "r", 1, "frames", "image/png", [(str(d / "f1.png"), 1)]))
    assert list(tmp_path.iterdir()) == []


def test_interrupt_during_finalization_leaves_nothing(env, tmp_path):
    class Stubborn(FakeProc):
        def wait(self, timeout=None):
            raise KeyboardInterrupt

    env.proc = Stubborn()

    def popen(argv, **kw):
        open(argv[-1], "wb").write(b"partial")  # the recorder had started writing
        return env.proc

    with pytest.raises(recorder.RecorderError) as exc:
        run(env, tmp_path, wait=lambda: True, popen=popen)
    assert "nothing was attached" in str(exc.value)
    assert env.proc.exited and list(tmp_path.iterdir()) == []


def test_unwritable_output_folder_fails_before_recording(env, tmp_path):
    import os

    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("running with privileges that ignore permissions")
        with pytest.raises(recorder.RecorderError) as exc:
            run(env, locked)
        assert "not writable" in str(exc.value) and env.argvs == []
    finally:
        locked.chmod(0o700)
