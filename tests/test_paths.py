"""T004: per-OS data/config locations and BUGCAP_HOME override."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def paths(monkeypatch):
    import bugcap.paths as paths_mod
    importlib.reload(paths_mod)
    return paths_mod


def _clear(monkeypatch):
    for var in ("BUGCAP_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "LOCALAPPDATA", "APPDATA"):
        monkeypatch.delenv(var, raising=False)


def test_linux_default_unchanged(paths, monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.data_dir() == tmp_path / ".local" / "share" / "bugcap"
    assert paths.config_dir() == tmp_path / ".config" / "bugcap"


def test_linux_respects_xdg(paths, monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    assert paths.data_dir() == tmp_path / "xdgdata" / "bugcap"


def test_macos(paths, monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    expected = tmp_path / "Library" / "Application Support" / "bugcap"
    assert paths.data_dir() == expected
    assert paths.config_dir() == expected


def test_windows(paths, monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert paths.data_dir() == tmp_path / "Local" / "bugcap"
    assert paths.config_dir() == tmp_path / "Roaming" / "bugcap"


def test_bugcap_home_override(paths, monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("BUGCAP_HOME", str(tmp_path / "home"))
    assert paths.data_dir() == tmp_path / "home" / "data"
    assert paths.config_dir() == tmp_path / "home" / "config"
    assert paths.db_path() == tmp_path / "home" / "data" / "bugcap.db"
    assert paths.images_dir() == tmp_path / "home" / "data" / "images"
