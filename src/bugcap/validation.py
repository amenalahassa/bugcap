"""Format checks for the GitHub-related values users type (slug, images path, branch).
Pure functions that raise ValueError naming the bad value; the online existence checks
live in `ghcli.verify_repo`."""
from __future__ import annotations

import re
from typing import Optional

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_BAD_BRANCH_CHARS = re.compile(r"[\s~^:?*\[\\\x00-\x1f\x7f]")


def validate_slug(value: str, what: str = "repo") -> str:
    """`owner/repo`, GitHub's character rules."""
    owner, sep, name = (value or "").partition("/")
    if (
        not sep
        or "/" in name
        or not _OWNER.fullmatch(owner)
        or not _REPO.fullmatch(name)
        or name in (".", "..")
    ):
        raise ValueError(f"invalid {what} {value!r}: expected owner/repo (letters, digits, '-', '_', '.')")
    return value


def validate_images_path(value: str) -> str:
    """A relative directory inside the images repo (no '..', no absolute or backslash paths)."""
    path = (value or "").strip("/")
    parts = path.split("/")
    if (
        not path
        or value.startswith("/")
        or "\\" in value
        or any(p in ("", ".", "..") for p in parts)
        or _BAD_BRANCH_CHARS.search(path)
    ):
        raise ValueError(f"invalid images path {value!r}: expected a relative directory such as bugcap-images")
    return value


def validate_branch(value: str) -> str:
    """Git ref-name rules (the common ones): no spaces, '..', '@{', leading '-' or '/', trailing '/' '.' or '.lock'."""
    bad = (
        not value
        or _BAD_BRANCH_CHARS.search(value)
        or ".." in value
        or "@{" in value
        or value.startswith(("-", "/"))
        or value.endswith(("/", ".", ".lock"))
        or "//" in value
        or value == "@"
    )
    if bad:
        raise ValueError(f"invalid branch {value!r}: not a valid git branch name")
    return value


def validate_repo_values(
    github: Optional[str] = None,
    images_repo: Optional[str] = None,
    images_path: Optional[str] = None,
    images_branch: Optional[str] = None,
) -> None:
    """Validate whichever values are given; ValueError names the first bad one."""
    if github:
        validate_slug(github, "GitHub repo")
    if images_repo:
        validate_slug(images_repo, "images repo")
    if images_path:
        validate_images_path(images_path)
    if images_branch:
        validate_branch(images_branch)
