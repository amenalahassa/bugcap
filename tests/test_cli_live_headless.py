import sys

import pytest

from bugcap import cli


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="Linux display detection")
def test_no_desktop_session_exits_3(monkeypatch, capsys):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert cli.main(["live"]) == 3
    assert "desktop session" in capsys.readouterr().err


def test_missing_tkinter_exits_3_with_install_hint(monkeypatch, capsys):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert cli.main(["live"]) == 3
    assert "python3-tk" in capsys.readouterr().err


def test_unreachable_display_exits_3(monkeypatch, capsys):
    tk = pytest.importorskip("tkinter")
    monkeypatch.setenv("DISPLAY", ":99999")
    assert cli.main(["live"]) == 3
    assert "cannot open a window" in capsys.readouterr().err
