"""SDK-free implementations of the agent tools. `mcp_server.py` merely registers
these, so the logic is unit-testable without the MCP SDK installed."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from . import capture, refs, repo, service, sync
from .errors import ServiceError
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


def _media_meta(media) -> list[dict]:
    return [
        {
            "index": m.idx,
            "label": m.label,
            "kind": m.kind,
            "mime": m.mime,
            "size_bytes": m.size_bytes,
            **({"frames": len(m.frames)} if m.kind == "frames" else {}),
        }
        for m in media
    ]


def get_report(store: Store, id: int) -> dict:
    report = store.get(id)
    if report is None:
        return {"error": f"no report with id {id}"}
    data = _summary(report)
    data.update({
        "body": report.body,
        "notes": report.notes,
        "image_paths": report.image_paths,
        "media": _media_meta(report.media),
    })
    images = []
    for path in report.image_paths:
        p = Path(path)
        if p.is_file():
            images.append({"path": path, "mime": _mime(p), "bytes": p.read_bytes()})
    resolved = [
        {"token": r.token, "index": found.idx}
        for r in refs.parse_references(report.notes)
        if r.kind in ("index", "label") and (found := refs.resolve(r, report.media)) is not None
    ]
    return {"report": data, "images": images, "resolved_references": resolved}


def attach_image(store: Store, id: int, sources: list[str], labels: Optional[list] = None) -> dict:
    """Attach images (paths, globs, http(s) URLs) to a report; partial batches are reported."""
    return _attach(store, id, sources, labels, service.add_media)


def attach_file(store: Store, id: int, sources: list[str], labels: Optional[list] = None) -> dict:
    """Attach files of any type (paths, globs, http(s) URLs) to a report."""
    return _attach(store, id, sources, labels, service.add_files)


def _attach(store: Store, id: int, sources: list[str], labels, add) -> dict:
    if not sources or len(sources) > 20:
        return {"code": "bad_query", "error": "sources must contain 1 to 20 entries"}
    try:
        result = add(store, id, list(sources), labels)
    except ServiceError as exc:
        return {"error": exc.message, **exc.as_dict()}
    return {
        "report_id": id,
        "added": [
            {"index": m.idx, "label": m.label, "kind": m.kind, "size_bytes": m.size_bytes, "source": m.source}
            for m in result.added
        ],
        "rejected": [{"source": r["source"], "reason": r["reason"]} for r in result.rejected],
    }


def update_notes(store: Store, id: int, notes: str) -> dict:
    """Replace a report's notes, validating `@` references against its images."""
    try:
        report = service.set_notes(store, id, notes)
    except ServiceError as exc:
        return {"error": exc.message, **exc.as_dict()}
    view = service.get_report_view(store, id)
    warnings = service.report_ref_warnings(store, report.notes)
    return {"report_id": report.id, "notes": report.notes, "references": view.references, "warnings": warnings}


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
    note: Optional[str] = None,
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
    media = service.attach_captured(store, report.id, str(path))
    note_error = None
    if note:
        try:
            service.append_note(store, report.id, note, [media])
        except ServiceError as exc:
            note_error = exc.message
    p = Path(path)
    return {
        **({"note_error": note_error} if note_error else {}),
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
