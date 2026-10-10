"""Per-repo setup: `bugcap init` writes .bugcap.toml so captures there get a tag + GitHub slug."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths, tomlio

CONFIG_NAME = ".bugcap.toml"
_REGISTRY_NAME = "known_repos.json"


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
    if path is None:
        return None
    cfg = _config_from_file(path)
    _remember(cfg.root)  # self-heals the registry for repos init'd before it existed
    return cfg


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
    _remember(cfg.root)


# --- known repos ----------------------------------------------------------------
# A small global registry of every repo `bugcap init` has written a .bugcap.toml for, so
# `bugcap live` can offer "which repo is this bug for?" without scanning the filesystem.

def _registry_path() -> Path:
    return paths.config_dir() / _REGISTRY_NAME


def _load_registry() -> list[str]:
    path = _registry_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [entry for entry in data if isinstance(entry, str)]


def _save_registry(roots: list[str]) -> None:
    try:
        _registry_path().write_text(json.dumps(roots, indent=2), encoding="utf-8")
    except OSError:
        pass  # best-effort: the registry is just a convenience index, never the source of truth


def _remember(root: Path) -> None:
    """Record `root` as a repo `init` has configured, for `known_repos()` to list later."""
    key = str(root.resolve())
    roots = _load_registry()
    if key not in roots:
        roots.append(key)
        _save_registry(roots)


def known_repos() -> list[RepoConfig]:
    """Every repo with a live .bugcap.toml that `init` has ever written, sorted by key.
    Entries whose config file is gone (moved or deleted) are dropped and the registry is
    pruned, so this is always in sync with what's actually on disk."""
    roots = _load_registry()
    kept: list[str] = []
    configs: list[RepoConfig] = []
    for raw in roots:
        config_path = Path(raw) / CONFIG_NAME
        if not config_path.is_file():
            continue
        try:
            configs.append(_config_from_file(config_path))
        except (OSError, ValueError):
            continue
        kept.append(raw)
    if kept != roots:
        _save_registry(kept)
    return sorted(configs, key=lambda c: c.key.lower())


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
