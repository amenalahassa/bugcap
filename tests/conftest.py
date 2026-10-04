"""Shared pytest fixtures: BUGCAP_HOME isolation, throwaway git repos, a fake `gh`."""
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pytest


@pytest.fixture
def bugcap_home(tmp_path, monkeypatch):
    """Point bugcap's data/config at a temp dir and clear XDG/platform env leakage."""
    home = tmp_path / "bugcap_home"
    monkeypatch.setenv("BUGCAP_HOME", str(home))
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_SESSION_TYPE", "LOCALAPPDATA", "APPDATA"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def git_repo(tmp_path):
    """Factory for a temp git repo, optionally with an `origin` remote."""
    def _make(name: str = "proj", origin: Optional[str] = None) -> Path:
        root = tmp_path / name
        root.mkdir()
        env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, env={**_base_env(), **env})
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True, env=_base_env())
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True, env=_base_env())
        if origin:
            subprocess.run(["git", "remote", "add", "origin", origin], cwd=root, check=True, env=_base_env())
        return root
    return _make


def _base_env() -> dict:
    import os
    return dict(os.environ)


@dataclass
class _Call:
    argv: list
    stdin: Optional[str]


@dataclass
class FakeGh:
    """Records `gh` invocations and returns scripted results.

    `responses` maps a predicate over argv to a CompletedProcess-like result.
    `which` controls whether `gh` (and other binaries) appear on PATH.
    """
    calls: list = field(default_factory=list)
    _handlers: list = field(default_factory=list)
    present: set = field(default_factory=lambda: {"gh"})

    def add(self, match: Callable[[list], bool], returncode: int = 0, stdout: str = "", stderr: str = ""):
        self._handlers.append((match, returncode, stdout, stderr))
        return self

    def on(self, *tokens: str, returncode: int = 0, stdout: str = "", stderr: str = ""):
        """Match when every token appears as (a substring of) some argv element.

        This matches both standalone flags (e.g. "--repo") and tokens embedded in a
        single element (e.g. "contents" inside the `gh api repos/o/r/contents/...` path).
        """
        toks = list(tokens)
        return self.add(
            lambda argv: all(any(t in elem for elem in argv) for t in toks),
            returncode,
            stdout,
            stderr,
        )

    def run(self, argv, *args, **kwargs):
        stdin = kwargs.get("input")
        self.calls.append(_Call(list(argv), stdin))
        for match, rc, out, err in self._handlers:
            if match(argv):
                return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def argvs(self) -> list:
        return [c.argv for c in self.calls]


@pytest.fixture
def fake_gh(monkeypatch):
    """Install a FakeGh over subprocess.run and shutil.which for the ghcli module."""
    fake = FakeGh()

    def fake_which(name):
        return f"/usr/bin/{name}" if name in fake.present else None

    # Patch where ghcli looks them up.
    import bugcap.ghcli as ghcli  # noqa: F401  (import may create the module lazily)
    monkeypatch.setattr("bugcap.ghcli.subprocess.run", fake.run)
    monkeypatch.setattr("bugcap.ghcli.shutil.which", fake_which)
    return fake


# Make `src/` importable without an install when tests run from a checkout.
_src = Path(__file__).resolve().parent.parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
