import pytest

from bugcap import cli, recorder
from bugcap.store import Store


def _fake_result(tmp_path, kind="animated"):
    f = tmp_path / "rec.gif"
    f.write_bytes(b"GIF89a-data")
    return recorder.RecordResult(f, 11, "duration cap", 9.2, kind, "image/gif")


@pytest.fixture
def have_ffmpeg(monkeypatch):
    monkeypatch.setattr(recorder, "detect_recorder", lambda *a, **k: recorder.by_name("ffmpeg"))


def test_record_new_report(bugcap_home, tmp_path, have_ffmpeg, monkeypatch, capsys):
    seen = {}

    def fake_run(name, fmt, fps, max_seconds, max_mb, **kw):
        seen.update(name=name, fmt=fmt, fps=fps, max_seconds=max_seconds, max_mb=max_mb)
        return _fake_result(tmp_path)

    monkeypatch.setattr(recorder, "run_recording", fake_run)
    assert cli.main(["record", "--max-seconds", "10", "--title", "Flow", "--tag", "ui"]) == 0
    out = capsys.readouterr().out
    assert "recorded 9.2 s, 11 B (animated), stopped: duration cap" in out
    assert seen == dict(name="ffmpeg", fmt="animated", fps=5, max_seconds=10, max_mb=25.0)
    with Store() as store:
        r = store.get(1)
        assert r.title == "Flow" and r.tags == ["ui"]
        assert [(m.kind, m.source, m.mime) for m in r.media] == [("animated", "recorded", "image/gif")]


def test_record_into_existing_report_video_fps(bugcap_home, tmp_path, have_ffmpeg, monkeypatch):
    seen = {}
    monkeypatch.setattr(recorder, "run_recording", lambda name, fmt, fps, *a, **k: seen.update(fps=fps) or _fake_result(tmp_path))
    with Store() as store:
        rid = store.add("bug").id
    assert cli.main(["record", "--id", str(rid), "--format", "video"]) == 0
    assert seen["fps"] == 30
    with Store() as store:
        assert len(store.list()) == 1 and len(store.get(rid).media) == 1


def test_record_frames(bugcap_home, tmp_path, have_ffmpeg, monkeypatch):
    frames = []
    for n in (1, 2):
        p = tmp_path / f"f{n}.png"
        p.write_bytes(b"x" * n)
        frames.append((str(p), n))
    res = recorder.RecordResult(None, 3, "stopped by user", 3.0, "frames", "image/png", frames)
    monkeypatch.setattr(recorder, "run_recording", lambda *a, **k: res)
    assert cli.main(["record", "--format", "frames"]) == 0
    with Store() as store:
        media = store.get(1).media[0]
        assert media.kind == "frames" and media.path is None
        assert [f.frame_no for f in media.frames] == [1, 2]


def test_record_without_recorder_exit_3_no_report(bugcap_home, monkeypatch, capsys):
    monkeypatch.setattr(recorder, "detect_recorder", lambda *a, **k: None)
    assert cli.main(["record"]) == 3
    assert "no screen recorder found" in capsys.readouterr().err
    with Store() as store:
        assert store.list() == []


def test_record_permission_error_exit_3_no_report(bugcap_home, have_ffmpeg, monkeypatch, capsys):
    def boom(*a, **k):
        raise recorder.RecorderError("the recording is empty", recorder.MACOS_PERMISSION_HELP)

    monkeypatch.setattr(recorder, "run_recording", boom)
    assert cli.main(["record"]) == 3
    assert "Screen Recording" in capsys.readouterr().err
    with Store() as store:
        assert store.list() == []


def test_record_unknown_report(bugcap_home, have_ffmpeg, capsys):
    assert cli.main(["record", "--id", "42"]) == 1
    assert "no report with id 42" in capsys.readouterr().err


def test_record_note_validates_references(bugcap_home, tmp_path, have_ffmpeg, monkeypatch, capsys):
    monkeypatch.setattr(recorder, "run_recording", lambda *a, **k: _fake_result(tmp_path))
    assert cli.main(["record", "--note", "see @1"]) == 0
    capsys.readouterr()
    assert cli.main(["record", "--note", "see @4"]) == 1
    assert "unknown reference @4" in capsys.readouterr().err
    with Store() as store:
        assert len(store.list()) == 1  # the refused recording left no report behind


def test_setup_lists_recorder_and_tkinter(bugcap_home, monkeypatch, capsys):
    from bugcap import backends

    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("flameshot"))
    monkeypatch.setattr(recorder, "detect_recorder", lambda *a, **k: None)
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Capture tool found: flameshot")
    assert "No screen recorder found" in out and "Install ffmpeg" in out
    assert "tkinter" in out


def test_refused_note_deletes_the_recorded_file(bugcap_home, tmp_path, have_ffmpeg, monkeypatch):
    result = _fake_result(tmp_path)
    monkeypatch.setattr(recorder, "run_recording", lambda *a, **k: result)
    assert cli.main(["record", "--note", "see @9"]) == 1
    assert not result.path.exists()


def test_record_unwritable_folder_exit_1_no_report(bugcap_home, have_ffmpeg, monkeypatch, capsys):
    def boom(*a, **k):
        raise recorder.RecorderError("the output folder is not writable: /x")

    monkeypatch.setattr(recorder, "run_recording", boom)
    assert cli.main(["record"]) == 1
    assert "not writable" in capsys.readouterr().err
    with Store() as store:
        assert store.list() == []
