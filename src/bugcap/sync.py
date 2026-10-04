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

from . import config, ghcli
from .store import Report, Store

DEFAULT_IMAGES_PATH = "bugcap-images"


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
                path = ask_cb(report, issue)
                if path:
                    store.add_image(report.id, path)
        else:
            if existing.title != issue["title"] or existing.body != body:
                store.update(existing.id, title=issue["title"], body=body)
                updated += 1
            else:
                unchanged += 1
            if ask_cb is not None:
                path = ask_cb(existing, issue)
                if path:
                    store.add_image(existing.id, path)
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


@dataclass
class SyncResult:
    issue_url: Optional[str] = None
    created_issue: bool = False
    commented: bool = False
    image_permalinks: list = field(default_factory=list)
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


def _commit_images(store: Store, report: Report, destination: Destination, opts: SyncOptions, result: SyncResult) -> list:
    """Commit each not-yet-committed image; record its ref immediately. Returns [(basename, permalink)]."""
    images = opts.images
    links: list = []
    pending = []
    for index, img in enumerate(report.image_paths):
        basename = os.path.basename(img)
        ref_key = f"github.image.{basename}"
        if ref_key in report.synced_refs:
            links.append((basename, f"https://github.com/{images.repo}/blob/{images.branch or 'HEAD'}/{images.path}/{basename}"))
            continue
        pending.append((index, img, basename, ref_key))

    if not pending:
        return links

    ok, reason = _consent_ok(destination, images.repo, opts)
    if not ok:
        result.messages.append(reason)
        return links

    for index, img, basename, ref_key in pending:
        with open(img, "rb") as fh:
            data = fh.read()
        target_path = f"{images.path}/{basename}"
        existing = destination.get_file(images.repo, target_path, images.branch)
        if existing is not None:
            blob_sha, remote_bytes = existing
            if remote_bytes == data:
                # identical content already present: record and skip the upload
                ref = FileRef(images.repo, target_path, blob_sha, f"https://github.com/{images.repo}/blob/{images.branch or 'HEAD'}/{target_path}")
                store.set_ref(report.id, ref_key, ref.as_ref())
                report.synced_refs[ref_key] = ref.as_ref()
                links.append((basename, ref.permalink))
                continue
            # different content at that path: pick a unique name
            target_path = f"{images.path}/{_unique_name(report.id, index, basename, data)}"
        ref = destination.put_file(images.repo, target_path, data, images.branch, f"bugcap: add {basename} for report #{report.id}")
        store.set_ref(report.id, ref_key, ref.as_ref())
        report.synced_refs[ref_key] = ref.as_ref()
        links.append((basename, ref.permalink))
        result.image_permalinks.append(ref.permalink)
    return links


def _content_hash(report: Report) -> str:
    basenames = sorted(os.path.basename(p) for p in report.image_paths)
    payload = "\n".join([report.title, report.notes or "", *basenames])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue_body(report: Report, image_links: list) -> str:
    parts = [report.notes or report.body or "_(captured with bugcap)_"]
    for basename, permalink in image_links:
        parts.append(f"![{basename}]({permalink})")
    return "\n\n".join(parts)


def sync_report(store: Store, report: Report, destination: Destination, opts: SyncOptions) -> SyncResult:
    """Create/comment an issue and commit image copies, idempotently and resumably."""
    result = SyncResult()
    image_links = _commit_images(store, report, destination, opts, result)

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
