"""Sync policy: pull GitHub issues into reports, and push reports to a Destination.

`sync.py` depends only on the small `Destination` protocol and on `synced_refs`, so a
future object store (roadmap 6) or tracker (roadmap 9) adds a new Destination without
touching the CLI or the store. GitHub is the only Destination today."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from . import config, ghcli, refs, service
from .store import Media, Report, Store

DEFAULT_IMAGES_PATH = "bugcap-images"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# --- runtime refs (not stored directly) --------------------------------------

@dataclass
class IssueRef:
    slug: str
    number: int
    url: str


@dataclass
class FileRef:
    slug: str
    path: str
    commit: str
    permalink: str

    def as_ref(self) -> str:
        return f"{self.slug}:{self.path}@{self.commit}"


# --- Destination seam ---------------------------------------------------------

class Destination(Protocol):
    name: str

    def ensure_ready(self) -> None: ...
    def repo_visibility(self, slug: str) -> str: ...
    def supports_attach(self) -> bool: ...
    def get_file(self, slug: str, path: str, branch: Optional[str]) -> Optional[tuple[str, bytes]]:
        """Return (blob_sha, content_bytes) if the file exists, else None."""
        ...
    def put_file(self, slug: str, path: str, data: bytes, branch: Optional[str], message: str) -> FileRef: ...
    def create_issue(self, slug: str, title: str, body: str, attach: Optional[str]) -> IssueRef: ...
    def comment(self, ref: IssueRef, body: str) -> None: ...


class GitHubDestination:
    name = "github"

    def ensure_ready(self) -> None:
        ghcli.ensure_ready()

    def repo_visibility(self, slug: str) -> str:
        return ghcli.repo_visibility(slug)

    def supports_attach(self) -> bool:
        return ghcli.supports_attach()

    def get_file(self, slug: str, path: str, branch: Optional[str]) -> Optional[tuple[str, bytes]]:
        meta = ghcli.get_contents(slug, path, ref=branch)
        if not meta or "content" not in meta:
            return None
        raw = base64.b64decode("".join(meta["content"].split()))
        return meta.get("sha", ""), raw

    def put_file(self, slug, path, data, branch, message) -> FileRef:
        result = ghcli.put_contents(
            slug, path, base64.b64encode(data).decode("ascii"), message, branch=branch
        )
        commit = (result.get("commit") or {}).get("sha") or (branch or "HEAD")
        permalink = f"https://github.com/{slug}/blob/{commit}/{path}"
        return FileRef(slug=slug, path=path, commit=commit, permalink=permalink)

    def create_issue(self, slug, title, body, attach) -> IssueRef:
        url = ghcli.create_issue(slug, title, body, attach=attach)
        number = _issue_number(url)
        return IssueRef(slug=slug, number=number, url=url)

    def comment(self, ref: IssueRef, body: str) -> None:
        ghcli.comment_issue(ref.slug, ref.number, body)


def _issue_number(url: str) -> int:
    match = re.search(r"/issues/(\d+)", url or "")
    return int(match.group(1)) if match else 0


# --- pull ---------------------------------------------------------------------

def _attach_answer(store: Store, report_id: int, answer) -> None:
    """`answer` from the --ask callback: None, a path, or (path, note); the note is appended
    to the report's notes and tied to the new image."""
    if not answer:
        return
    path, note = answer if isinstance(answer, tuple) else (answer, None)
    media = service.attach_captured(store, report_id, str(path))
    if note:
        service.append_note(store, report_id, note, [media])


def pull_issues(
    store: Store,
    slug: str,
    labels: Optional[list[str]] = None,
    limit: int = 30,
    ask_cb: Optional[Callable[[Report, dict], Optional[str]]] = None,
) -> dict:
    """Import open issues as reports. Refreshes title/body only; never notes/tags/status.
    Returns {created, updated, unchanged}."""
    ghcli.ensure_ready()
    issues = ghcli.list_issues(slug, labels, limit)
    created = updated = unchanged = 0
    for issue in issues:
        ref = f"{slug}#{issue['number']}"
        body = issue.get("body") or ""
        existing = store.find_by_ref("github.issue", ref)
        if existing is None:
            status = "closed" if str(issue.get("state", "")).upper() == "CLOSED" else "open"
            report = store.add(
                title=issue["title"],
                body=body,
                repo=slug,
                status=status,
                synced_refs={"github.issue": ref},
            )
            created += 1
            if ask_cb is not None:
                _attach_answer(store, report.id, ask_cb(report, issue))
        else:
            if existing.title != issue["title"] or existing.body != body:
                store.update(existing.id, title=issue["title"], body=body)
                updated += 1
            else:
                unchanged += 1
            if ask_cb is not None:
                _attach_answer(store, existing.id, ask_cb(existing, issue))
    return {"created": created, "updated": updated, "unchanged": unchanged}


# --- push (sync) --------------------------------------------------------------

@dataclass
class ImagesTarget:
    repo: str
    path: str
    branch: Optional[str] = None


def resolve_images_target(
    flag_repo: Optional[str],
    flag_path: Optional[str],
    flag_branch: Optional[str],
    repo_cfg,
    global_cfg: dict,
    issue_slug: str,
) -> ImagesTarget:
    """Resolve where image copies are committed: flag > .bugcap.toml [sync] > global [sync]
    > the issue repo, with default path 'bugcap-images'."""
    cfg_repo = getattr(repo_cfg, "images_repo", None) if repo_cfg else None
    cfg_path = getattr(repo_cfg, "images_path", None) if repo_cfg else None
    cfg_branch = getattr(repo_cfg, "images_branch", None) if repo_cfg else None
    repo = flag_repo or cfg_repo or global_cfg.get("images_repo") or issue_slug
    path = flag_path or cfg_path or global_cfg.get("images_path") or DEFAULT_IMAGES_PATH
    branch = flag_branch or cfg_branch or global_cfg.get("images_branch")
    return ImagesTarget(repo=repo, path=path.strip("/"), branch=branch)


@dataclass
class SyncOptions:
    issue_slug: str
    images: ImagesTarget
    assume_yes: bool = False
    interactive: bool = True
    confirm: Optional[Callable[[str, str], bool]] = None  # (slug, visibility) -> bool
    max_upload_mb: float = 25


@dataclass
class SyncResult:
    issue_url: Optional[str] = None
    created_issue: bool = False
    commented: bool = False
    image_permalinks: list = field(default_factory=list)
    media_links: list = field(default_factory=list)  # [MediaLink], in media order
    messages: list = field(default_factory=list)


def _consent_ok(destination: Destination, images_repo: str, opts: SyncOptions) -> tuple[bool, str]:
    visibility = destination.repo_visibility(images_repo)
    private = visibility == "private"
    if private and config.consent_has(images_repo):
        return True, ""
    if opts.assume_yes:
        if private:
            config.consent_add(images_repo)
        return True, ""
    if opts.interactive and opts.confirm and opts.confirm(images_repo, visibility):
        if private:
            config.consent_add(images_repo)
        return True, ""
    kind = "private" if private else "public"
    return False, f"skipped image commit to {kind} repo {images_repo} (not confirmed)"


def _unique_name(report_id: int, index: int, basename: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:8]
    stem, dot, ext = basename.rpartition(".")
    suffix = f".{ext}" if dot else ""
    return f"{report_id}-{index}-{digest}{suffix}"


@dataclass
class MediaLink:
    media: Media
    name: str
    urls: list  # permalinks (several for a frames set); empty when nothing was uploaded
    note: str = ""  # why nothing was uploaded


def _permalink(images: ImagesTarget, path: str) -> str:
    return f"https://github.com/{images.repo}/blob/{images.branch or 'HEAD'}/{path}"


def _upload(store, report, destination, images, ref_key, target_path, data, basename, index, result, message):
    """Commit one file (skipping identical content already there); returns its permalink."""
    existing = destination.get_file(images.repo, target_path, images.branch)
    if existing is not None:
        blob_sha, remote_bytes = existing
        if remote_bytes == data:
            ref = FileRef(images.repo, target_path, blob_sha, _permalink(images, target_path))
            store.set_ref(report.id, ref_key, ref.as_ref())
            report.synced_refs[ref_key] = ref.as_ref()
            return ref.permalink
        # different content at that path: pick a unique name
        directory = target_path.rsplit("/", 1)[0]
        target_path = f"{directory}/{_unique_name(report.id, index, basename, data)}"
    ref = destination.put_file(images.repo, target_path, data, images.branch, message)
    store.set_ref(report.id, ref_key, ref.as_ref())
    report.synced_refs[ref_key] = ref.as_ref()
    result.image_permalinks.append(ref.permalink)
    return ref.permalink


def _media_files(m: Media) -> list:
    """[(absolute path, size)] of the files a media item consists of."""
    if m.kind == "frames":
        from .paths import absolute_stored_path
        return [(absolute_stored_path(f.path), f.size_bytes) for f in m.frames]
    return [(m.abs_path, m.size_bytes)] if m.abs_path else []


def _commit_media(store: Store, report: Report, destination: Destination, opts: SyncOptions, result: SyncResult) -> list:
    """Commit each not-yet-committed media file, recording its ref immediately.
    Returns a MediaLink per media item. Files above `max_upload_mb` are skipped with a warning."""
    images = opts.images
    limit = int(opts.max_upload_mb * 1024 * 1024)
    links: dict = {}
    pending = []  # (media, link) needing at least one upload

    for m in report.media:
        files = _media_files(m)
        if not files:
            continue
        name = os.path.basename(files[0][0]) if m.kind != "frames" else f"frames-{m.idx}"
        link = MediaLink(m, name, [])
        links[m.id] = link
        too_big = [(p, sz) for p, sz in files if sz > limit]
        if too_big:
            size = sum(sz for _, sz in files)
            result.messages.append(
                f"warning: skipped media #{m.idx} {name} ({human_size(size)}): "
                f"above the {opts.max_upload_mb:g} MB upload limit"
            )
            link.note = f"not uploaded: above the {opts.max_upload_mb:g} MB limit"
            continue
        if m.kind == "frames":
            done = report.synced_refs.get(f"github.frames.{m.idx}")
            if done:
                link.urls = [
                    _permalink(images, f"{images.path}/{report.id}-{m.idx}-frames/{n:03d}{os.path.splitext(p)[1]}")
                    for n, (p, _) in enumerate(files, start=1)
                ]
                continue
        else:
            ref_key = _ref_key(m, name)
            if ref_key in report.synced_refs:
                link.urls = [_permalink(images, f"{images.path}/{name}")]
                continue
        pending.append((m, link, files, name))

    if pending:
        ok, reason = _consent_ok(destination, images.repo, opts)
        if not ok:
            result.messages.append(reason)
            return [links[m.id] for m in report.media if m.id in links]
        for m, link, files, name in pending:
            if m.kind == "frames":
                for n, (path, _) in enumerate(files, start=1):
                    with open(path, "rb") as fh:
                        data = fh.read()
                    fname = f"{n:03d}{os.path.splitext(path)[1]}"
                    target = f"{images.path}/{report.id}-{m.idx}-frames/{fname}"
                    link.urls.append(_upload(
                        store, report, destination, images, f"github.frame.{m.idx}.{n}", target, data, fname,
                        m.idx * 1000 + n, result, f"bugcap: add frame {n} of media #{m.idx} for report #{report.id}",
                    ))
                store.set_ref(report.id, f"github.frames.{m.idx}", f"{images.repo}:{images.path}/{report.id}-{m.idx}-frames")
                report.synced_refs[f"github.frames.{m.idx}"] = "set"
            else:
                path = files[0][0]
                with open(path, "rb") as fh:
                    data = fh.read()
                index = report.media.index(m)
                link.urls.append(_upload(
                    store, report, destination, images, _ref_key(m, name), f"{images.path}/{name}", data, name,
                    index, result, f"bugcap: add {name} for report #{report.id}",
                ))
    return [links[m.id] for m in report.media if m.id in links]


def _ref_key(m: Media, name: str) -> str:
    return f"github.image.{name}" if m.kind == "image" else f"github.media.{name}"


def _content_hash(report: Report) -> str:
    basenames = sorted(os.path.basename(p) for p in report.image_paths)
    others = sorted(
        f"{m.kind}:{os.path.basename(m.path or '')}:{len(m.frames)}"
        for m in report.media
        if m.kind != "image"
    )
    payload = "\n".join([report.title, report.notes or "", *basenames, *others])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _link_markdown(link: MediaLink) -> str:
    """The markdown that stands in for a media reference."""
    if not link.urls:
        return ""
    label = link.media.label or link.name
    if link.media.kind == "image":
        return f"![{label}]({link.urls[0]})"
    if link.media.kind == "frames":
        return ", ".join(f"[{label} {n}]({u})" for n, u in enumerate(link.urls, start=1))
    return f"[{label}]({link.urls[0]})"


def _issue_body(report: Report, links: list) -> str:
    replacements: dict = {}
    for link in links:
        if link.urls:
            replacements[link.media.id] = _link_markdown(link)
        elif link.note:
            replacements[link.media.id] = f"@{link.media.idx} ({link.note})"
    notes = refs.substitute(report.notes, report.media, replacements) if report.notes else ""
    referenced = {
        found.id
        for r in refs.parse_references(report.notes or "")
        if r.kind in ("index", "label") and (found := refs.resolve(r, report.media)) is not None
    }
    parts = [notes or report.body or "_(captured with bugcap)_"]
    for link in links:
        if not link.urls or link.media.id in referenced:
            continue
        if link.media.kind == "frames":
            parts.append("\n".join(f"{n}. [{link.name} frame {n}]({u})" for n, u in enumerate(link.urls, start=1)))
        elif link.media.kind == "image":
            parts.append(f"![{link.name}]({link.urls[0]})")
        else:
            parts.append(f"[{link.name}]({link.urls[0]})")
    return "\n\n".join(parts)


def sync_report(store: Store, report: Report, destination: Destination, opts: SyncOptions) -> SyncResult:
    """Create/comment an issue and commit image copies, idempotently and resumably."""
    result = SyncResult()
    image_links = _commit_media(store, report, destination, opts, result)

    issue_ref_str = report.synced_refs.get("github.issue")
    content_hash = _content_hash(report)

    if issue_ref_str:
        number = int(issue_ref_str.split("#")[-1])
        slug = issue_ref_str.rsplit("#", 1)[0]
        ref = IssueRef(slug=slug, number=number, url=f"https://github.com/{slug}/issues/{number}")
        result.issue_url = ref.url
        if report.synced_refs.get("github.comment_hash") != content_hash:
            destination.comment(ref, _issue_body(report, image_links))
            store.set_ref(report.id, "github.comment_hash", content_hash)
            report.synced_refs["github.comment_hash"] = content_hash
            result.commented = True
    else:
        attach = None
        if destination.supports_attach() and report.image_paths:
            attach = report.image_paths[0]
        ref = destination.create_issue(
            opts.issue_slug, report.title, _issue_body(report, image_links), attach
        )
        store.set_ref(report.id, "github.issue", f"{ref.slug}#{ref.number}")
        report.synced_refs["github.issue"] = f"{ref.slug}#{ref.number}"
        store.set_ref(report.id, "github.comment_hash", content_hash)
        report.synced_refs["github.comment_hash"] = content_hash
        result.issue_url = ref.url
        result.created_issue = True

    return result
