"""Thin wrapper over the GitHub CLI (`gh`). Always argv lists (never shell strings);
large JSON payloads go to `gh api` via stdin, never argv (Windows ~32k limit)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Optional


class GhError(RuntimeError):
    pass


def _install_hint() -> str:
    if sys.platform == "win32":
        return "winget install GitHub.cli (or https://cli.github.com)"
    if sys.platform == "darwin":
        return "brew install gh (or https://cli.github.com)"
    return "see https://github.com/cli/cli#installation (apt install gh, dnf install gh, ...)"


def ensure_ready() -> None:
    """Raise GhError unless `gh` is installed and authenticated."""
    if not shutil.which("gh"):
        raise GhError(f"GitHub CLI (`gh`) not found. Install: {_install_hint()}")
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise GhError("`gh` is not logged in. Run `gh auth login`.")


def run_gh(args: list[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run `gh <args>` capturing text output; `stdin` is fed to the process if given."""
    return subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True
    )


def _checked(args: list[str], stdin: Optional[str] = None) -> str:
    result = run_gh(args, stdin=stdin)
    if result.returncode != 0:
        raise GhError((result.stderr or result.stdout or "gh failed").strip())
    return result.stdout


def list_issues(slug: str, labels: Optional[list[str]] = None, limit: int = 30) -> list[dict]:
    args = [
        "issue", "list", "--repo", slug, "--state", "open",
        "--limit", str(limit),
        "--json", "number,title,body,url,state,labels",
    ]
    for label in labels or []:
        args += ["--label", label]
    out = _checked(args)
    return json.loads(out or "[]")


def repo_visibility(slug: str) -> str:
    """Repo visibility ('public'/'private'/'internal'); any failure is treated as 'public'."""
    result = run_gh(["repo", "view", slug, "--json", "visibility"])
    if result.returncode != 0:
        return "public"
    try:
        return str(json.loads(result.stdout).get("visibility", "public")).lower()
    except (ValueError, AttributeError):
        return "public"


def supports_attach() -> bool:
    """Feature-detect `gh issue create --attach` (present in recent gh releases)."""
    result = run_gh(["issue", "create", "--help"])
    return "--attach" in (result.stdout or "")


def create_issue(
    slug: str, title: str, body: str, attach: Optional[str] = None
) -> str:
    """Create an issue; return the issue URL printed by gh (parsed from stdout)."""
    args = ["issue", "create", "--repo", slug, "--title", title, "--body-file", "-"]
    if attach:
        args += ["--attach", attach]
    result = run_gh(args, stdin=body)
    url = _first_url(result.stdout) or _first_url(result.stderr)
    if result.returncode != 0 and not url:
        raise GhError((result.stderr or result.stdout or "gh issue create failed").strip())
    if not url:
        raise GhError("could not determine the created issue URL from gh output")
    return url


def comment_issue(slug: str, number: int, body: str) -> str:
    args = ["issue", "comment", str(number), "--repo", slug, "--body-file", "-"]
    out = _checked(args, stdin=body)
    return _first_url(out) or ""


def get_contents(slug: str, path: str, ref: Optional[str] = None) -> Optional[dict]:
    """GET repo contents; None on 404 (missing file)."""
    endpoint = f"repos/{slug}/contents/{path}"
    if ref:
        endpoint += f"?ref={ref}"
    result = run_gh(["api", endpoint])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def put_contents(
    slug: str,
    path: str,
    content_b64: str,
    message: str,
    branch: Optional[str] = None,
    sha: Optional[str] = None,
) -> dict:
    """PUT repo contents (create/update a file). Payload (incl. base64) goes via stdin."""
    payload: dict = {"message": message, "content": content_b64}
    if branch:
        payload["branch"] = branch
    if sha:
        payload["sha"] = sha
    endpoint = f"repos/{slug}/contents/{path}"
    out = _checked(
        ["api", "--method", "PUT", endpoint, "--input", "-"],
        stdin=json.dumps(payload),
    )
    return json.loads(out or "{}")


def _first_url(text: Optional[str]) -> Optional[str]:
    for token in (text or "").split():
        if token.startswith("http://") or token.startswith("https://"):
            return token.strip()
    return None


class GhUnavailable(RuntimeError):
    """Cannot verify (no `gh`, not logged in, offline): callers warn and carry on."""


def verify_repo(slug: str, branch: Optional[str] = None, need_write: bool = False) -> None:
    """Check that `slug` exists (and, with `need_write`, that the current login can push) and
    that `branch` exists. Raises GhError for a definite problem naming the bad value and
    GhUnavailable when the check itself cannot be done."""
    try:
        ensure_ready()
    except GhError as exc:
        raise GhUnavailable(str(exc)) from exc

    def fetch(endpoint: str):
        result = run_gh(["api", endpoint])
        if result.returncode == 0:
            try:
                return json.loads(result.stdout or "{}")
            except ValueError:
                return {}
        text = f"{result.stderr} {result.stdout}"
        if "404" in text or "Not Found" in text:
            return None
        raise GhUnavailable(text.strip() or "gh api failed")

    info = fetch(f"repos/{slug}")
    if info is None:
        raise GhError(f"repo {slug!r} does not exist, or your `gh` login cannot see it")
    permissions = info.get("permissions") if isinstance(info, dict) else None
    if need_write and isinstance(permissions, dict) and permissions.get("push") is False:
        raise GhError(f"repo {slug!r} is not writable with the current `gh` login")
    if branch and fetch(f"repos/{slug}/branches/{branch}") is None:
        raise GhError(f"branch {branch!r} does not exist in {slug}")
