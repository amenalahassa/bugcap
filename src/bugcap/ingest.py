"""Bring existing images into the store: local paths, globs and http(s) URLs.

Every input is validated by its magic bytes (never its extension or Content-Type), copied
into the images directory under a name derived from its content (the original path is not
kept) and written atomically. The same image is therefore stored once, however many reports
use it. Network access is limited to plain http(s) GETs with no credentials."""
from __future__ import annotations

import glob
import hashlib
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from .errors import ServiceError
from .paths import files_dir, images_dir, to_data_relative
from .store import guess_mime

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20
MAX_REDIRECTS = 5

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,16}$")


@dataclass
class StoredFile:
    path: str  # data-relative (images/<uuid>.<ext>)
    abs_path: Path
    mime: str
    size_bytes: int
    source: str
    reused: bool = False  # the content was already in the store; no new file was written


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


def content_name(data: bytes, mime: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()}{_EXT[mime]}"


def _store(data: bytes, source: str) -> StoredFile:
    mime = sniff_image(data)
    dest = images_dir() / content_name(data, mime)
    if dest.is_file() and dest.stat().st_size == len(data):
        return StoredFile(to_data_relative(dest), dest, mime, len(data), source, reused=True)
    tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return StoredFile(to_data_relative(dest), dest, mime, len(data), source)


def adopt(path) -> Path:
    """Give a screenshot the capture tool already saved in the store its content-derived
    name. If the same image is stored already, the new copy is dropped and the existing
    path returned. Anything that is not a recognisable image, or sits outside the store, is
    left where it is."""
    path = Path(path)
    if path.parent != images_dir():
        return path
    try:
        data = path.read_bytes()
        mime = sniff_image(data)
    except (OSError, ServiceError):
        return path
    dest = images_dir() / content_name(data, mime)
    if dest == path:
        return path
    if dest.is_file() and dest.stat().st_size == len(data):
        path.unlink(missing_ok=True)
        return dest
    os.replace(path, dest)
    return dest


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


def _fetch(url: str, *, max_bytes: int, timeout: float, max_redirects: int, images_only: bool) -> tuple[bytes, str]:
    """GET `url`; returns (body, content-type hint). With `images_only`, text/HTML/JSON/XML
    responses are refused early."""
    if not url.lower().startswith(("http://", "https://")):
        raise ServiceError("invalid_image", "only http(s) URLs are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "bugcap"}, method="GET")
    opener = urllib.request.build_opener(_LimitedRedirects(max_redirects))
    try:
        with opener.open(request, timeout=timeout) as response:
            hint = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if images_only and _clearly_not_image(hint):
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
    return b"".join(chunks), hint


def download_url(
    url: str,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = DOWNLOAD_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> StoredFile:
    data, hint = _fetch(url, max_bytes=max_bytes, timeout=timeout, max_redirects=max_redirects, images_only=True)
    try:
        return _store(data, url)
    except ServiceError as exc:
        suffix = f" (content is {hint})" if hint else ""
        raise ServiceError(exc.code, exc.message + suffix) from None


# --- any file (attachments) ---------------------------------------------------

def _store_file(data: bytes, source: str, name: str) -> StoredFile:
    """Store any bytes under their content hash, keeping a sane extension so the file still
    opens with the right program. Identical content is stored once."""
    suffix = Path(name).suffix.lower()
    if not _SUFFIX_RE.match(suffix):
        suffix = ""
    dest = files_dir() / f"{hashlib.sha256(data).hexdigest()}{suffix}"
    if dest.is_file() and dest.stat().st_size == len(data):
        return StoredFile(to_data_relative(dest), dest, guess_mime(name), len(data), source, reused=True)
    tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return StoredFile(to_data_relative(dest), dest, guess_mime(name), len(data), source)


def import_local_file(path: Path) -> StoredFile:
    path = Path(path).expanduser()
    if path.is_dir():
        raise ServiceError("invalid_file", "is a directory")
    if not path.is_file():
        raise ServiceError("not_found", "file not found")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ServiceError("invalid_file", f"cannot read file: {exc.strerror or exc}")
    return _store_file(data, str(path), path.name)


def download_file(
    url: str,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = DOWNLOAD_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> StoredFile:
    data, _ = _fetch(url, max_bytes=max_bytes, timeout=timeout, max_redirects=max_redirects, images_only=False)
    return _store_file(data, url, urllib.parse.urlparse(url).path)


def adopt_file(path) -> Path:
    """Give a file already copied into the files directory its content-derived name (same
    rules as `adopt`): an identical file already stored wins and the new copy is dropped."""
    path = Path(path)
    if path.parent != files_dir():
        return path
    try:
        data = path.read_bytes()
    except OSError:
        return path
    suffix = path.suffix.lower() if _SUFFIX_RE.match(path.suffix.lower()) else ""
    dest = files_dir() / f"{hashlib.sha256(data).hexdigest()}{suffix}"
    if dest == path:
        return path
    if dest.is_file() and dest.stat().st_size == len(data):
        path.unlink(missing_ok=True)
        return dest
    os.replace(path, dest)
    return dest


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


def ingest_file_item(item: Item) -> StoredFile:
    if item.error is not None:
        raise item.error
    if classify_source(item.source) == "url":
        return download_file(item.source)
    return import_local_file(Path(item.source))


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
