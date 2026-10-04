"""Per-repo setup: `bugcap init` writes .bugcap.toml so captures there get a tag + GitHub slug."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import tomlio

CONFIG_NAME = ".bugcap.toml"


@dataclass
class RepoConfig:
    root: Path
    tag: str
    github: Optional[str] = None  # "owner/repo"

    @property
    def key(self) -> str:
        return self.github or self.tag


def _git(args: list[str], cwd: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def git_root(start: Optional[Path] = None) -> Optional[Path]:
    root = _git(["rev-parse", "--show-toplevel"], start or Path.cwd())
    return Path(root) if root else None


def detect_github_slug(root: Path) -> Optional[str]:
    url = _git(["remote", "get-url", "origin"], root)
    if not url:
        return None
    match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    here = (start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_repo_config(start: Optional[Path] = None) -> Optional[RepoConfig]:
    path = find_config(start)
    if not path:
        return None
    data = tomlio.load(path)
    return RepoConfig(
        root=path.parent, tag=data.get("tag") or path.parent.name, github=data.get("github")
    )


def init_repo(
    root: Path, tag: Optional[str] = None, github: Optional[str] = None
) -> RepoConfig:
    cfg = RepoConfig(
        root=root, tag=tag or root.name, github=github or detect_github_slug(root)
    )
    data = {"tag": cfg.tag}
    if cfg.github:
        data["github"] = cfg.github
    tomlio.save(root / CONFIG_NAME, data)
    return cfg
