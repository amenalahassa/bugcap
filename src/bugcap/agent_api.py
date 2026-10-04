"""SDK-free implementations of the four agent tools. `mcp_server.py` merely registers
these, so the logic is unit-testable without the MCP SDK installed."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from . import capture, repo, sync
from .store import Report, Store

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _mime(path) -> str:
    return _MIME.get(Path(path).suffix.lower(), "application/octet-stream")


def _summary(report: Report) -> dict:
    return {
        "id": report.id,
        "title": report.title,
        "status": report.status,
        "tags": report.tags,
        "repo": report.repo,
        "created_at": report.created_at,
        "synced_refs": report.synced_refs,
    }


def _current_repo_key() -> Optional[str]:
    cfg = repo.load_repo_config()
    return cfg.key if cfg else None


def list_reports(
    store: Store,
    all: bool = False,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    scope = None if all else _current_repo_key()
    reports = store.list(repo=scope)
    if status is not None:
        reports = [r for r in reports if r.status == status]
    if limit is not None:
        reports = reports[: max(0, int(limit))]
    return [_summary(r) for r in reports]


def get_report(store: Store, id: int) -> dict:
    report = store.get(id)
    if report is None:
        return {"error": f"no report with id {id}"}
    data = _summary(report)
    data.update({"body": report.body, "notes": report.notes, "image_paths": report.image_paths})
    images = []
    for path in report.image_paths:
        p = Path(path)
        if p.is_file():
            images.append({"path": path, "mime": _mime(p), "bytes": p.read_bytes()})
    return {"report": data, "images": images}


def _resolve_slug(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    cfg = repo.load_repo_config()
    return cfg.github if cfg else None


def _resolve_target(store: Store, report_id: Optional[int], issue: Optional[str]) -> Optional[Report]:
    """Find (or create from an issue) the report a screenshot is being requested for."""
    if report_id is not None:
        return store.get(report_id)
    if not issue:
        return None
    if "#" in issue:
        slug, _, number = issue.partition("#")
        slug = slug or (_resolve_slug(None) or "")
    else:
        slug = _resolve_slug(None) or ""
        number = issue
    ref = f"{slug}#{number}"
    existing = store.find_by_ref("github.issue", ref)
    if existing is not None:
        return existing
    return store.add(
        title=f"Issue {ref}", repo=slug or None, synced_refs={"github.issue": ref}
    )


def _capture_with_timeout(timeout_seconds: int) -> Path:
    result: dict = {}

    def worker():
        try:
            result["path"] = capture.capture_screenshot()
        except BaseException as exc:  # re-raised on the calling thread
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise TimeoutError("screenshot request timed out")
    if "error" in result:
        raise result["error"]
    return result["path"]


def request_screenshot(
    store: Store,
    report_id: Optional[int] = None,
    issue: Optional[str] = None,
    message: Optional[str] = None,
    timeout_seconds: int = 300,
) -> dict:
    if not capture.has_display():
        return {"status": "non_interactive", "message": "no interactive desktop UI available"}
    report = _resolve_target(store, report_id, issue)
    if report is None:
        return {"status": "error", "message": "no target report or issue given"}
    if message:
        print(message, file=sys.stderr, flush=True)
    print(f"bugcap: capture a screenshot for report #{report.id}...", file=sys.stderr, flush=True)
    try:
        path = _capture_with_timeout(timeout_seconds)
    except capture.CaptureError as exc:
        return {"status": "cancelled", "message": str(exc)}
    except TimeoutError as exc:
        return {"status": "cancelled", "message": str(exc)}
    store.add_image(report.id, str(path))
    p = Path(path)
    return {
        "status": "captured",
        "report_id": report.id,
        "image": {"path": str(path), "mime": _mime(p), "bytes": p.read_bytes()},
    }


def pull_issues(
    store: Store,
    repo: Optional[str] = None,
    labels: Optional[list[str]] = None,
    limit: int = 30,
    ask_cb: Optional[Callable] = None,
) -> dict:
    slug = _resolve_slug(repo)
    if not slug:
        return {"error": "no GitHub repo given and none configured in .bugcap.toml"}
    return sync.pull_issues(store, slug, labels, limit, ask_cb)
