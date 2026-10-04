"""JSON handlers for the dashboard. Each is a thin wrapper over `service`/`store`; the only
logic here is shaping responses and mapping ServiceError codes to HTTP statuses."""
from __future__ import annotations

from .. import service
from ..errors import ServiceError
from ..store import Report

STATUS_FOR_CODE = {
    "bad_query": 400, "invalid_status": 400, "invalid_label": 400, "invalid_title": 400,
    "bad_token": 403, "not_found": 404, "invalid_reference": 422,
    "duplicate_label": 409, "referenced_image": 409,
}


def http_status(exc: ServiceError) -> int:
    return STATUS_FOR_CODE.get(exc.code, 400)


def _summary(report: Report) -> dict:
    return {
        "id": report.id, "title": report.title, "status": report.status, "tags": report.tags,
        "repo": report.repo, "created_at": report.created_at, "media_count": len(report.media),
    }


def list_reports(store, query: dict) -> dict:
    def one(name):
        values = query.get(name)
        return values[-1] if values else None

    def number(name, default):
        raw = one(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            raise ServiceError("bad_query", f"{name} must be a number")

    total, items = service.list_reports_query(
        store, repo=one("repo"), tags=query.get("tag") or [], status=one("status"), q=one("q"),
        limit=number("limit", 200), offset=number("offset", 0),
    )
    return {"total": total, "items": items}


def _links(synced_refs: dict) -> list:
    """Clickable targets derived from sync refs (currently the GitHub issue)."""
    links = []
    issue = (synced_refs or {}).get("github.issue", "")
    slug, sep, number = issue.rpartition("#")
    if sep and number.isdigit() and slug.count("/") == 1:
        links.append({"label": f"GitHub issue {issue}", "url": f"https://github.com/{slug}/issues/{number}"})
    return links


def get_report(store, report_id: int) -> dict:
    view = service.get_report_view(store, report_id)
    report = view.report
    media = [
        {
            "id": m.id, "index": m.idx, "label": m.label, "kind": m.kind, "mime": m.mime,
            "size_bytes": m.size_bytes, "url": f"/media/{m.id}",
        }
        for m in view.media
    ]
    frames = {
        str(m.id): [{"frame_no": f.frame_no, "url": f"/media/{m.id}/frames/{f.frame_no}"} for f in m.frames]
        for m in view.media if m.kind == "frames"
    }
    data = _summary(report)
    data.update({
        "notes_raw": report.notes,
        "notes_segments": view.segments,
        "notes_html_segments": view.segments,
        "media": media,
        "frames": frames,
        "synced_refs": report.synced_refs,
        "links": _links(report.synced_refs),
    })
    return data


def set_status(store, report_id: int, body: dict) -> dict:
    status = body.get("status")
    if not isinstance(status, str):
        raise ServiceError("bad_query", "body must be {\"status\": \"...\"}")
    return _summary(service.set_status(store, report_id, status))


def set_tags(store, report_id: int, body: dict) -> dict:
    add, remove = body.get("add", []), body.get("remove", [])
    for value in (add, remove):
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise ServiceError("bad_query", "add and remove must be lists of strings")
    return {"tags": service.set_tags(store, report_id, add=add, remove=remove)}


def set_notes(store, report_id: int, body: dict) -> dict:
    notes = body.get("notes")
    if not isinstance(notes, str):
        raise ServiceError("bad_query", "body must be {\"notes\": \"...\"}")
    service.set_notes(store, report_id, notes)
    return get_report(store, report_id)
