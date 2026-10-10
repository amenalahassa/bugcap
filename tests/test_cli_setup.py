"""T015: `bugcap setup` detection, prompting, --yes, non-TTY, and manual guidance."""
import subprocess
import types

import pytest
from bugcap import backends, cli, recorder


@pytest.fixture
def tty(monkeypatch):
    def _set(value: bool):
        monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: value))
    return _set


@pytest.fixture
def record_run(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    return calls


def test_detected_tool_runs_nothing(monkeypatch, record_run, capsys):
    monkeypatch.setattr(backends, "detect", lambda: backends.by_name("flameshot"))
    assert cli.main(["setup"]) == 0
    assert "flameshot" in capsys.readouterr().out
    assert record_run == []


def test_prompt_decline_installs_nothing(monkeypatch, record_run, tty):
    monkeypatch.setattr(backends, "detect", lambda: None)
    monkeypatch.setattr(backends, "install_command", lambda b: ["sudo", "apt-get", "install", "-y", "flameshot"])
    tty(True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert cli.main(["setup"]) == 1
    assert record_run == []


def test_prompt_accept_runs_argv(monkeypatch, record_run, tty):
    monkeypatch.setattr(backends, "detect", lambda: None)
    cmd = ["sudo", "apt-get", "install", "-y", "flameshot"]
    monkeypatch.setattr(backends, "install_command", lambda b: cmd)
    tty(True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert cli.main(["setup"]) == 0
    assert record_run == [cmd]


def test_yes_installs_without_prompt(monkeypatch, record_run, tty):
    monkeypatch.setattr(backends, "detect", lambda: None)
    # Pretend a recorder is present so setup only installs the capture tool
    # (otherwise it also tries to install ffmpeg, which depends on the machine).
    monkeypatch.setattr(recorder, "detect_recorder", lambda: types.SimpleNamespace(name="ffmpeg", description="stub"))
    cmd = ["winget", "install", "Flameshot.Flameshot"]
    monkeypatch.setattr(backends, "install_command", lambda b: cmd)
    tty(False)  # even non-interactive, --yes proceeds

    def boom(*a):
        raise AssertionError("should not prompt with --yes")

    monkeypatch.setattr("builtins.input", boom)
    assert cli.main(["setup", "--yes"]) == 0
    assert record_run == [cmd]


def test_non_tty_without_yes_prints_command_exits_1(monkeypatch, record_run, tty, capsys):
    monkeypatch.setattr(backends, "detect", lambda: None)
    monkeypatch.setattr(backends, "install_command", lambda b: ["apt-get", "install", "flameshot"])
    tty(False)
    assert cli.main(["setup"]) == 1
    assert "apt-get install flameshot" in capsys.readouterr().err
    assert record_run == []


def test_no_package_manager_prints_guidance(monkeypatch, record_run, capsys):
    monkeypatch.setattr(backends, "detect", lambda: None)
    monkeypatch.setattr(backends, "install_command", lambda b: None)
    assert cli.main(["setup"]) == 1
    assert "manually" in capsys.readouterr().err.lower()
    assert record_run == []


def test_yes_install_verified_prints_installed(monkeypatch, record_run, tty, capsys):
    """After a successful install, setup re-checks detection instead of trusting the exit
    code: found now -> plain "installed" (the install also made it detectable)."""
    calls = iter([None, backends.by_name("flameshot")])  # not found, then found
    monkeypatch.setattr(backends, "detect", lambda: next(calls))
    monkeypatch.setattr(recorder, "detect_recorder", lambda: types.SimpleNamespace(name="ffmpeg", description="stub"))
    monkeypatch.setattr(backends, "install_command", lambda b: ["winget", "install", "Flameshot.Flameshot"])
    tty(False)
    assert cli.main(["setup", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "flameshot installed." in out
    assert "PATH" not in out


def test_yes_install_not_yet_on_path_warns(monkeypatch, record_run, tty, capsys):
    """Windows installers (winget) often don't update an already-running terminal's PATH,
    so a bare "installed." would be misleading right before `bugcap live` fails to find it.
    Detection still failing after a successful install should say so instead."""
    monkeypatch.setattr(backends, "detect", lambda: None)  # still not found, even post-install
    monkeypatch.setattr(recorder, "detect_recorder", lambda: types.SimpleNamespace(name="ffmpeg", description="stub"))
    monkeypatch.setattr(backends, "install_command", lambda b: ["winget", "install", "Flameshot.Flameshot"])
    tty(False)
    assert cli.main(["setup", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "installed" in out
    assert "PATH" in out
    assert "reopen your terminal" in out


def test_version_flag(capsys):
    from bugcap import __version__

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"bugcap {__version__}"
