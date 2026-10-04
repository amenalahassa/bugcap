"""Logging for `bugcap mcp-serve`.

stdout carries the MCP protocol, so nothing here ever writes to it: records go to a rotating
file in the per-user data dir and to stderr."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from . import config
from .paths import data_dir

LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOGGER_NAMES = ("bugcap.mcp", "mcp")  # ours, and the MCP SDK's own (protocol-level) messages
_MARK = "_bugcap_handler"


def default_log_path() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / "mcp-server.log"


def resolve_level(explicit: Optional[str] = None) -> int:
    """Flag, then BUGCAP_LOG_LEVEL, then `[log] level` in config.toml, then INFO."""
    for candidate in (explicit, os.environ.get("BUGCAP_LOG_LEVEL"), config.get("log.level")):
        if candidate and str(candidate).strip().lower() in LEVELS:
            return LEVELS[str(candidate).strip().lower()]
    return logging.INFO


def resolve_path(explicit: Optional[str] = None) -> Path:
    for candidate in (explicit, os.environ.get("BUGCAP_LOG_FILE"), config.get("log.file")):
        if candidate:
            return Path(str(candidate)).expanduser()
    return default_log_path()


def setup_logging(level: Optional[str] = None, path: Optional[str] = None) -> tuple[logging.Logger, Optional[Path]]:
    """Configure file + stderr logging (idempotent). Returns the logger and the log file
    actually in use (None if the file could not be opened and only stderr is used)."""
    numeric = resolve_level(level)
    target: Optional[Path] = resolve_path(path)
    formatter = logging.Formatter(FORMAT)
    handlers: list[logging.Handler] = []
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError as exc:
        print(f"bugcap mcp-serve: cannot write the log file {target}: {exc}; logging to stderr only", file=sys.stderr)
        target = None
    stream = logging.StreamHandler(sys.stderr)  # never stdout: it carries the protocol
    stream.setFormatter(formatter)
    handlers.append(stream)
    for handler in handlers:
        setattr(handler, _MARK, True)

    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if getattr(h, _MARK, False)]:
            logger.removeHandler(old)
            old.close()
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(numeric)
        logger.propagate = False  # the SDK installs its own root handler; avoid duplicates
    return logging.getLogger("bugcap.mcp"), target
