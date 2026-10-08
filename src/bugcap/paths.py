import os
import sys
from pathlib import Path


def _home_override() -> Path | None:
    value = os.environ.get("BUGCAP_HOME")
    return Path(value) if value else None


def _data_dir_path() -> Path:
    """The data directory location, without creating it."""
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
    return path


def data_dir() -> Path:
    path = _data_dir_path()
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


def media_dir() -> Path:
    path = data_dir() / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def files_dir() -> Path:
    path = data_dir() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def drafts_dir() -> Path:
    path = data_dir() / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


_STORE_DIRS = ("images", "media", "files")


def to_data_relative(path) -> str:
    """Path relative to the data dir (posix style) if it lies under images/ or media/;
    otherwise the path unchanged (legacy absolute paths)."""
    raw = str(path)
    root = _data_dir_path()
    try:
        real = Path(os.path.realpath(raw))
        for name in _STORE_DIRS:
            base = Path(os.path.realpath(root / name))
            if real == base or base in real.parents:
                return real.relative_to(Path(os.path.realpath(root))).as_posix()
    except (OSError, ValueError):
        pass
    return raw


def resolve_data_path(rel) -> Path:
    """Absolute path for a stored data-relative path; ValueError unless its realpath lies
    inside images/ or media/ (blocks traversal, absolute paths and escaping symlinks)."""
    raw = str(rel)
    if not raw or os.path.isabs(raw) or "\x00" in raw:
        raise ValueError(f"path outside the media store: {raw!r}")
    root = _data_dir_path()
    candidate = Path(os.path.realpath(root / raw))
    for name in _STORE_DIRS:
        base = Path(os.path.realpath(root / name))
        if candidate != base and base in candidate.parents:
            return candidate
    raise ValueError(f"path outside the media store: {raw!r}")


def absolute_stored_path(stored: str) -> str:
    """Absolute filesystem path for a stored media path (relative ones live in the data dir)."""
    if os.path.isabs(stored):
        return stored
    first = stored.replace("\\", "/").split("/", 1)[0]
    if first in _STORE_DIRS:
        return str(_data_dir_path() / stored)
    return stored


def db_path() -> Path:
    return data_dir() / "bugcap.db"


def config_path() -> Path:
    return config_dir() / "config.toml"
