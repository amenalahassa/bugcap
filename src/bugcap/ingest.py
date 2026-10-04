"""Bring existing images into the store: local paths, globs and http(s) URLs.

Every input is validated by its magic bytes (never its extension or Content-Type), copied
into the images directory under a fresh name (the original path is not kept), and written
atomically. Network access is limited to plain http(s) GETs with no credentials."""
from __future__ import annotations

import glob
import os
import socket
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from .errors import ServiceError
from .paths import images_dir, to_data_relative

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20
MAX_REDIRECTS = 5

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


@dataclass
class StoredFile:
    path: str  # data-relative (images/<uuid>.<ext>)
    abs_path: Path
    mime: str
    size_bytes: int
    source: str


@dataclass
class Item:
    """One concrete input after glob expansion."""
    source: str
    label: Optional[str] = None
    error: Optional[ServiceError] = None  # set when expansion itself failed


@dataclass
class IngestResult:
    added: list = field(default_factory=list)  # [{"stored": StoredFile, "source", "label"}]
    rejected: list = field(default_factory=list)  # [{"source", "reason", "code"}]


def classify_source(src: str) -> Literal["url", "glob", "path"]:
    lowered = src.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "url"
    if any(ch in src for ch in "*?[") and not os.path.exists(os.path.expanduser(src)):
        return "glob"
    return "path"


def sniff_image(data: bytes) -> str:
    """The image mime type for PNG/JPEG/GIF/WebP magic bytes; ServiceError(invalid_image) otherwise."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33:
        return "image/png"
    if data.startswith(b"\xff\xd8\xff") and len(data) >= 4:
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 16:
        return "image/webp"
    raise ServiceError("invalid_image", "not an image (PNG, JPEG, GIF or WebP expected)")


def _store(data: bytes, source: str) -> StoredFile:
    mime = sniff_image(data)
    dest = images_dir() / f"{uuid.uuid4()}{_EXT[mime]}"
    tmp = dest.with_name(dest.name + ".part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return StoredFile(to_data_relative(dest), dest, mime, len(data), source)


def import_local(path: Path) -> StoredFile:
    path = Path(path).expanduser()
    if path.is_dir():
        raise ServiceError("invalid_image", "is a directory")
    if not path.is_file():
        raise ServiceError("not_found", "file not found")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ServiceError("invalid_image", f"cannot read file: {exc.strerror or exc}")
    return _store(data, str(path))


class _LimitedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int):
        self.max_redirections = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith(("http://", "https://")):
            raise ServiceError("invalid_image", "redirect to a non-http(s) URL refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _clearly_not_image(content_type: str) -> bool:
    """Reject text/HTML/JSON/XML responses early. Anything else (image/*, octet-stream, a
    missing header) goes on to the magic-byte check, which is the final authority."""
    if not content_type:
        return False
    main, _, sub = content_type.partition("/")
    return main == "text" or any(k in sub for k in ("html", "json", "xml"))


def download_url(
    url: str,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = DOWNLOAD_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> StoredFile:
    if not url.lower().startswith(("http://", "https://")):
        raise ServiceError("invalid_image", "only http(s) URLs are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "bugcap"}, method="GET")
    opener = urllib.request.build_opener(_LimitedRedirects(max_redirects))
    try:
        with opener.open(request, timeout=timeout) as response:
            hint = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if _clearly_not_image(hint):
                raise ServiceError("invalid_image", f"not an image (content is {hint})")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ServiceError("too_large", f"larger than {max_bytes // (1024 * 1024)} MB")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ServiceError("too_large", f"larger than {max_bytes // (1024 * 1024)} MB")
                chunks.append(chunk)
    except ServiceError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            raise ServiceError("invalid_image", "too many redirects") from exc
        raise ServiceError("invalid_image", f"HTTP {exc.code}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ServiceError("timeout", f"timed out after {timeout:g} s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise ServiceError("timeout", f"timed out after {timeout:g} s") from exc
        raise ServiceError("invalid_image", f"download failed: {exc.reason}") from exc
    data = b"".join(chunks)
    try:
        return _store(data, url)
    except ServiceError as exc:
        suffix = f" (content is {hint})" if hint else ""
        raise ServiceError(exc.code, exc.message + suffix) from None


def resolve_glob(pattern: str) -> list[str]:
    """All matches, sorted by name (directories included; they are rejected per item)."""
    return sorted(glob.glob(os.path.expanduser(pattern)))


def expand_sources(sources: list[str], labels: Optional[list[Optional[str]]] = None) -> list[Item]:
    """Expand globs; `labels` pairs up with `sources` by position (empty/None = no label)."""
    items: list[Item] = []
    for position, source in enumerate(sources):
        label = labels[position] if labels and position < len(labels) else None
        label = label or None
        kind = classify_source(source)
        if kind == "glob":
            matches = resolve_glob(source)
            if not matches:
                items.append(Item(source, label, ServiceError("not_found", f"no files match {source}")))
            elif label and len(matches) > 1:
                items.append(Item(source, label, ServiceError(
                    "invalid_label", f"label {label!r} cannot apply to {source}, which matches {len(matches)} files")))
            else:
                items.extend(Item(m, label) for m in matches)
        else:
            items.append(Item(source, label))
    return items


def ingest_item(item: Item) -> StoredFile:
    if item.error is not None:
        raise item.error
    if classify_source(item.source) == "url":
        return download_url(item.source)
    return import_local(Path(item.source))


def ingest_sources(sources: list[str], labels: Optional[list[Optional[str]]] = None) -> IngestResult:
    """Process each input independently (a failure never blocks the others)."""
    result = IngestResult()
    for item in expand_sources(sources, labels):
        try:
            stored = ingest_item(item)
        except ServiceError as exc:
            result.rejected.append({"source": item.source, "reason": exc.message, "code": exc.code})
        else:
            result.added.append({"stored": stored, "source": item.source, "label": item.label})
    return result
