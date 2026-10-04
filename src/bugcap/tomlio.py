"""Tiny TOML read/write for bugcap's flat config (strings, bools, ints, one table level)."""
import json
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def dumps(data: dict[str, Any]) -> str:
    lines = [f"{k} = {_scalar(v)}" for k, v in data.items() if not isinstance(v, dict)]
    for key, table in data.items():
        if isinstance(table, dict):
            lines += ["", f"[{key}]"] + [f"{k} = {_scalar(v)}" for k, v in table.items()]
    return "\n".join(lines).strip() + "\n"


def save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(dumps(data), encoding="utf-8")
