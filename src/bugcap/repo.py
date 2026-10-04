"""Per-repo setup: `bugcap init` writes .bugcap.toml so captures there get a tag + GitHub slug."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import tomlio

CONFIG_NAME = ".bugcap.toml"


class RepoConfigError(RuntimeError):
    pass


@dataclass
class RepoConfig:
    root: Path
    tag: str
    github: Optional[str] = None  # "owner/repo"
    images_repo: Optional[str] = None  # [sync] owner/repo for committed image copies
    images_path: Optional[str] = None  # [sync] directory within images_repo
    images_branch: Optional[str] = None  # [sync] branch within images_repo

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


def _config_from_file(path: Path) -> RepoConfig:
    data = tomlio.load(path)
    sync = data.get("sync") or {}
    return RepoConfig(
        root=path.parent,
        tag=data.get("tag") or path.parent.name,
        github=data.get("github"),
        images_repo=sync.get("images_repo"),
        images_path=sync.get("images_path"),
        images_branch=sync.get("images_branch"),
    )


def load_repo_config(start: Optional[Path] = None) -> Optional[RepoConfig]:
    path = find_config(start)
    return _config_from_file(path) if path else None


def write_config(cfg: RepoConfig) -> None:
    data: dict = {"tag": cfg.tag}
    if cfg.github:
        data["github"] = cfg.github
    sync = {
        k: v
        for k, v in (
            ("images_repo", cfg.images_repo),
            ("images_path", cfg.images_path),
            ("images_branch", cfg.images_branch),
        )
        if v
    }
    if sync:
        data["sync"] = sync
    tomlio.save(cfg.root / CONFIG_NAME, data)


def build_config(
    root: Path,
    tag: Optional[str] = None,
    github: Optional[str] = None,
    images_repo: Optional[str] = None,
    images_path: Optional[str] = None,
    images_branch: Optional[str] = None,
) -> RepoConfig:
    """The config `init` would write (nothing is written)."""
    return RepoConfig(
        root=root,
        tag=tag or root.name,
        github=github or detect_github_slug(root),
        images_repo=images_repo,
        images_path=images_path,
        images_branch=images_branch,
    )


def init_repo(
    root: Path,
    tag: Optional[str] = None,
    github: Optional[str] = None,
    images_repo: Optional[str] = None,
    images_path: Optional[str] = None,
    images_branch: Optional[str] = None,
    force: bool = False,
) -> RepoConfig:
    if (root / CONFIG_NAME).exists() and not force:
        raise RepoConfigError(
            f"{CONFIG_NAME} already exists in {root}. Use --force to overwrite."
        )
    cfg = build_config(root, tag, github, images_repo, images_path, images_branch)
    write_config(cfg)
    return cfg


SETTABLE_KEYS = ("tag", "github", "images_repo", "images_path", "images_branch")
