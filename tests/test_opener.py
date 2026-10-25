"""opener: open a staged attachment in the OS default application."""
from types import SimpleNamespace

from bugcap import opener


def test_open_argv_per_platform(tmp_path):
    f = str(tmp_path / "a.mp4")
    assert opener.open_argv(f, "macos") == ["open", f]
    assert opener.open_argv(f, "darwin") == ["open", f]
    assert opener.open_argv(f, "linux") == ["xdg-open", f]
    assert opener.open_argv(f, "windows") is None
    assert opener.open_argv(f, "win32") is None


def test_missing_file_is_reported(tmp_path):
    missing = tmp_path / "gone.png"
    assert opener.open_path(missing, platform="linux") == f"File not found: {missing}"


def test_success_returns_none(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    seen = []
    runner = lambda argv, **k: seen.append(argv) or SimpleNamespace(returncode=0)  # noqa: E731
    assert opener.open_path(f, platform="linux", runner=runner) is None
    assert seen == [["xdg-open", str(f)]]


def test_no_handler_exit_code(tmp_path):
    f = tmp_path / "a.weird"
    f.write_bytes(b"x")
    runner = lambda argv, **k: SimpleNamespace(returncode=3)  # noqa: E731
    message = opener.open_path(f, platform="linux", runner=runner)
    assert message == f"No application to open a.weird. It is at {f}."


def test_launcher_missing(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"x")

    def runner(argv, **k):
        raise FileNotFoundError("xdg-open")

    assert opener.open_path(f, platform="linux", runner=runner) == f"No application to open a.png. It is at {f}."


def test_windows_uses_startfile_and_maps_oserror(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    opened = []
    assert opener.open_path(f, platform="windows", startfile=opened.append) is None
    assert opened == [str(f)]

    def no_association(path):
        raise OSError("No application is associated")

    assert opener.open_path(f, platform="windows", startfile=no_association) == (
        f"No application to open a.mp4. It is at {f}.")


def test_slow_launcher_counts_as_opened(tmp_path):
    import subprocess

    f = tmp_path / "a.png"
    f.write_bytes(b"x")

    def runner(argv, **k):
        raise subprocess.TimeoutExpired(argv, k.get("timeout"))

    assert opener.open_path(f, platform="macos", runner=runner) is None


def test_a_folder_can_be_opened(tmp_path):
    runner = lambda argv, **k: SimpleNamespace(returncode=0)  # noqa: E731
    assert opener.open_path(tmp_path, platform="linux", runner=runner) is None
