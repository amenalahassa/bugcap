"""Shared operations used by the CLI, the MCP tools, the dashboard and live mode.

All rules that go beyond plain storage (label and reference validation, reference rewrite on
relabel/remove, media lifecycle) live here so no interface re-implements them. Functions
take a `Store`, raise `ServiceError`, and never print."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from . import ingest, refs
from .errors import ServiceError
from .paths import resolve_data_path
from .store import STATUSES, Media, Report, Store

_LABEL_HELP = "start with a letter; then letters, digits, '-' or '_'"


# --- lookups ------------------------------------------------------------------

def _require(store: Store, report_id: int) -> Report:
    report = store.get(report_id)
    if report is None:
        raise ServiceError("not_found", f"no report with id {report_id}")
    return report


def find_media(media: list[Media], ref: str) -> Media:
    """Locate a media item by number (`v2`, `i2`, or the older `2`) or label (`login-error`,
    case-insensitive). The leading `@` is optional."""
    text = str(ref).lstrip("@")
    number = refs.index_number(text)
    if number is not None:
        letter = refs.index_letter(text)
        for item in media:
            if item.idx == int(number) and (letter is None or refs.MEDIA_LETTERS.get(item.kind) == letter):
                return item
    else:
        for item in media:
            if item.label and item.label.lower() == text.lower():
                return item
    raise ServiceError("not_found", f"no image {ref!r} on this report")


# --- labels -------------------------------------------------------------------

def validate_label(label: str) -> str:
    if not refs.LABEL_RE.match(label):
        raise ServiceError("invalid_label", f"invalid label {label!r}: {_LABEL_HELP}")
    if refs.RESERVED_LABEL_RE.match(label) or label.isdigit():
        raise ServiceError(
            "invalid_label",
            f"label {label!r} is reserved: names like i1, v2, g3, f4 or 5 are media numbers",
        )
    return label


def _check_new_labels(existing: list[Media], labels: list[Optional[str]]) -> None:
    taken = {m.label.lower(): m for m in existing if m.label}
    for label in labels:
        if not label:
            continue
        validate_label(label)
        clash = taken.get(label.lower())
        if clash is not None:
            raise ServiceError(
                "duplicate_label", f"duplicate label {label!r} (already {refs.media_token(clash)})",
                {"label": label, "index": clash.idx},
            )
        taken[label.lower()] = Media(0, 0, 0, label, "image", None, "", 0, None, "")


# --- media: add ---------------------------------------------------------------

@dataclass
class AddResult:
    added: list = field(default_factory=list)  # [Media]
    rejected: list = field(default_factory=list)  # [{"source","reason","code"}]


def _discard(stored_files) -> None:
    for stored in stored_files:
        try:
            stored.abs_path.unlink()
        except OSError:
            pass


def _prepare(existing: list[Media], sources: list[str], labels):
    """Expand globs and validate labels before any file is copied."""
    items = ingest.expand_sources(list(sources), labels)
    _check_new_labels(existing, [i.label for i in items if i.error is None])
    return items


def _ingest_all(items):
    ok, rejected = [], []
    for item in items:
        try:
            ok.append((item, ingest.ingest_item(item)))
        except ServiceError as exc:
            rejected.append({"source": item.source, "reason": exc.message, "code": exc.code})
    return ok, rejected


def add_media(store: Store, report_id: int, sources: list[str], labels=None) -> AddResult:
    report = _require(store, report_id)
    items = _prepare(report.media, sources, labels)
    ok, rejected = _ingest_all(items)
    result = AddResult(rejected=rejected)
    try:
        with store.transaction():
            for item, stored in ok:
                result.added.append(
                    store.insert_media(
                        report_id, kind="image", path=str(stored.abs_path), label=item.label,
                        mime=stored.mime, size_bytes=stored.size_bytes, source=item.source,
                    )
                )
    except BaseException:
        _discard(s for _, s in ok)
        raise
    return result


# --- reports ------------------------------------------------------------------

def create_report(
    store: Store,
    title: str,
    notes: str = "",
    tags=None,
    repo: Optional[str] = None,
    status: str = "open",
    body: str = "",
    sources: Optional[list[str]] = None,
    labels=None,
    require_media: bool = False,
    captured: Optional[str] = None,
    captured_label: Optional[str] = None,
) -> tuple[Report, AddResult]:
    """Create a report, attaching `sources` as images. Notes are validated against the final
    media; on any failure no report and no copied file is left behind. With `require_media`,
    a report whose inputs were all rejected is not created (the report is returned as None).
    `captured` is a screenshot the capture tool already saved in the store: it becomes image 1
    without being copied."""
    if not (title or "").strip():
        raise ServiceError("invalid_title", "title must not be empty")
    items = _prepare([], sources or [], list(labels or []))
    if captured_label:
        _check_new_labels([], [captured_label] + [i.label for i in items if i.error is None])
    ok, rejected = _ingest_all(items)
    result = AddResult(rejected=rejected)
    if require_media and not ok and captured is None:
        return None, result  # type: ignore[return-value]
    try:
        with store.transaction():
            report = store.add(title=title, notes="", tags=tags, repo=repo, body=body, status=status)
            if captured is not None:
                result.added.append(
                    store.insert_media(report.id, kind="image", path=captured,
                                       label=captured_label or None, source="captured")
                )
            for item, stored in ok:
                result.added.append(
                    store.insert_media(
                        report.id, kind="image", path=str(stored.abs_path), label=item.label,
                        mime=stored.mime, size_bytes=stored.size_bytes, source=item.source,
                    )
                )
            if notes:
                refs.validate_references(notes, result.added)
                store.update(report.id, notes=notes)
    except BaseException:
        _discard(s for _, s in ok)
        raise
    return store.get(report.id), result


def report_ref_warnings(store: Store, notes: str) -> list[str]:
    """Warnings for `#N` references to reports that do not exist. They are not errors: the
    text is kept, and the report may be created later or may have been deleted."""
    return [
        f"warning: #{number} in notes is not a report (kept as text)"
        for number in sorted(set(refs.report_refs(notes)))
        if store.get(number) is None
    ]


def delete_report(store: Store, report_id: int) -> Report:
    """Delete a report, its media rows and their image/frame files. The rows go first, so a
    failed delete leaves the files in place; synced GitHub issues are not touched."""
    report = _require(store, report_id)
    store.delete(report_id)
    for item in report.media:
        _delete_files(item)
    return report


def attach_captured(store: Store, report_id: int, path: str, label: Optional[str] = None) -> Media:
    """Attach a screenshot the capture tool already saved in the store (no copy)."""
    report = _require(store, report_id)
    _check_new_labels(report.media, [label])
    return store.insert_media(report_id, kind="image", path=str(path), label=label or None, source="captured")


def add_recording(
    store: Store,
    report_id: Optional[int],
    file: Optional[str],
    kind: str,
    mime: str,
    size_bytes: int,
    frame_paths: Optional[list] = None,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    tags=None,
    repo: Optional[str] = None,
) -> tuple[Report, Media]:
    """Attach a finished recording (video / animated file, or a set of keyframes) to an
    existing report, or to a new one when `report_id` is None. `frame_paths` is
    [(path, size)] for kind `frames`."""
    from datetime import datetime

    if kind not in ("video", "animated", "frames"):
        raise ServiceError("invalid_image", f"unsupported recording kind {kind!r}")
    if kind == "frames" and not frame_paths:
        raise ServiceError("invalid_image", "a frames recording needs at least one keyframe")
    with store.transaction():
        if report_id is None:
            report = store.add(
                title=title or f"Recording {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                tags=tags, repo=repo,
            )
        else:
            report = _require(store, report_id)
        media = store.insert_media(
            report.id, kind=kind, path=None if kind == "frames" else file, mime=mime,
            size_bytes=size_bytes, source="recorded", frames=frame_paths if kind == "frames" else None,
        )
        if notes:
            refs.validate_references(notes, store.list_media(report.id))
            store.update(report.id, notes=notes)
    return store.get(report.id), media


def format_note_entry(text: str, media: list, when=None) -> str:
    """`[2026-10-04 10:15] @i3: text`: timestamped and tied to the image(s) it was added with."""
    from datetime import datetime

    stamp = (when or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M")
    tokens = " ".join(refs.media_token(m) for m in media)
    return f"[{stamp}] {tokens}: {text.strip()}" if tokens else f"[{stamp}] {text.strip()}"


def append_note(store: Store, report_id: int, text: str, media: Optional[list] = None, when=None) -> Report:
    """Append a note to the report's notes (never replacing them), tied to the media it was
    added with so it can be referenced with `@n`. The new entry is validated like any note."""
    report = _require(store, report_id)
    if not (text or "").strip():
        return report
    entry = format_note_entry(text, media or [], when)
    refs.validate_references(entry, report.media)
    notes = f"{report.notes.rstrip()}\n\n{entry}" if (report.notes or "").strip() else entry
    return store.update(report_id, notes=notes)


def set_status(store: Store, report_id: int, status: str) -> Report:
    _require(store, report_id)
    if status not in STATUSES:
        raise ServiceError(
            "invalid_status", f"invalid status {status!r}; choose one of: {', '.join(STATUSES)}"
        )
    return store.update(report_id, status=status)


def set_tags(store: Store, report_id: int, add=None, remove=None) -> list[str]:
    report = _require(store, report_id)
    tags = list(report.tags)
    for tag in add or []:
        if tag not in tags:
            tags.append(tag)
    tags = [t for t in tags if t not in set(remove or [])]
    return store.set_tags(report_id, tags).tags


def set_notes(store: Store, report_id: int, notes: str) -> Report:
    report = _require(store, report_id)
    refs.validate_references(notes, report.media)
    return store.update(report_id, notes=notes)


# --- media: relabel / remove --------------------------------------------------

def _referencing(report: Report, item: Media, only_label: bool = False) -> list[refs.Ref]:
    found = refs.references_to(report.notes, item, report.media)
    return [r for r in found if r.kind == "label"] if only_label else found


def _refuse(item: Media, found: list[refs.Ref]) -> ServiceError:
    tokens = [r.token for r in found]
    return ServiceError(
        "referenced_image",
        f"{refs.media_token(item)} is referenced in notes by {', '.join(tokens)}; use --force to rewrite them",
        {"tokens": tokens},
    )


def relabel_media(store: Store, report_id: int, ref: str, new_label: str, force: bool = False) -> int:
    """Returns the number of rewritten references."""
    report = _require(store, report_id)
    item = find_media(report.media, ref)
    new_label = new_label or ""
    if new_label:
        others = [m for m in report.media if m.id != item.id]
        _check_new_labels(others, [new_label])
    found = _referencing(report, item, only_label=True) if item.label else []
    if found and not force:
        raise _refuse(item, found)
    mapping = {item.label: f"@{new_label}" if new_label else refs.media_token(item)} if item.label else {}
    with store.transaction():
        store.update_media_label(item.id, new_label or None)
        notes, count = refs.rewrite_references_counted(report.notes, mapping)
        if count:
            store.update(report_id, notes=notes)
    return count


def remove_media(store: Store, report_id: int, ref: str, force: bool = False) -> int:
    """Delete an item and replace references to it with plain text; other indexes stay as
    they are (an index is never reused). Returns the number of rewritten references."""
    report = _require(store, report_id)
    item = find_media(report.media, ref)
    found = _referencing(report, item)
    if found and not force:
        raise _refuse(item, found)
    mapping = {str(item.idx): refs.REMOVED_TEXT}
    if item.label:
        mapping[item.label] = refs.REMOVED_TEXT
    with store.transaction():
        store.delete_media(item.id)
        notes, count = refs.rewrite_references_counted(report.notes, mapping)
        if count:
            store.update(report_id, notes=notes)
    _delete_files(item)
    return count


def _delete_files(item: Media) -> None:
    paths = [item.path] if item.path else []
    paths += [f.path for f in item.frames]
    for rel in paths:
        try:
            os.unlink(resolve_data_path(rel))
        except (ValueError, OSError):
            pass  # legacy absolute paths and missing files are left alone


# --- views --------------------------------------------------------------------

def report_segments(notes: str, media: list[Media]) -> list[dict]:
    """Notes as `{"text": ...}` / `{"ref": {...}}` segments (no HTML), for the dashboard."""
    segments: list[dict] = []
    pos = 0
    text = notes or ""

    def add_text(chunk: str) -> None:
        if chunk:
            if segments and "text" in segments[-1]:
                segments[-1]["text"] += chunk
            else:
                segments.append({"text": chunk})

    for ref in refs.parse_references(text):
        if ref.kind == "escape":
            add_text(text[pos : ref.start] + "@")
        else:
            item = refs.resolve(ref, media) if ref.kind in ("index", "label") else None
            if item is None:
                continue
            add_text(text[pos : ref.start])
            segments.append(
                {"ref": {"token": ref.token, "index": item.idx, "media_id": item.id, "kind": item.kind}}
            )
        pos = ref.end
    add_text(text[pos:])
    return segments


@dataclass
class ReportView:
    report: Report
    media: list
    references: list  # [{"token", "index", "path"}]
    segments: list


def get_report_view(store: Store, report_id: int) -> ReportView:
    report = _require(store, report_id)
    resolved = []
    for ref in refs.parse_references(report.notes):
        item = refs.resolve(ref, report.media) if ref.kind in ("index", "label") else None
        if item is not None:
            resolved.append({"token": ref.token, "index": item.idx, "path": item.path})
    return ReportView(report, report.media, resolved, report_segments(report.notes, report.media))


def list_reports_query(
    store: Store,
    repo: Optional[str] = None,
    tags: Optional[list] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """Filtered, paged report summaries (newest first). Tags use AND semantics; `q` is a
    case-insensitive substring match over title and notes."""
    if status and status not in STATUSES:
        raise ServiceError("bad_query", f"status must be one of {', '.join(STATUSES)}")
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ServiceError("bad_query", "limit must be between 1 and 1000")
    if not isinstance(offset, int) or offset < 0:
        raise ServiceError("bad_query", "offset must be 0 or more")
    needle = (q or "").lower()
    wanted = set(tags or [])
    matched = []
    for report in store.list(repo=repo):
        if status and report.status != status:
            continue
        if wanted and not wanted <= set(report.tags):
            continue
        if needle and needle not in report.title.lower() and needle not in (report.notes or "").lower():
            continue
        matched.append(report)
    items = [
        {
            "id": r.id, "title": r.title, "status": r.status, "tags": r.tags, "repo": r.repo,
            "created_at": r.created_at, "media_count": len(r.media),
        }
        for r in matched[offset : offset + limit]
    ]
    return len(matched), items
