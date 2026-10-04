import os
import sys
from pathlib import Path


def _home_override() -> Path | None:
    value = os.environ.get("BUGCAP_HOME")
    return Path(value) if value else None


def data_dir() -> Path:
    override = _home_override()
    if override:
        path = override / "data"
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "bugcap"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "bugcap"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "bugcap"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    override = _home_override()
    if override:
        path = override / "config"
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "bugcap"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "bugcap"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / "bugcap"
    path.mkdir(parents=True, exist_ok=True)
    return path


def images_dir() -> Path:
    path = data_dir() / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "bugcap.db"


def config_path() -> Path:
    return config_dir() / "config.toml"
