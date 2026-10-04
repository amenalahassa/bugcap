"""Serve stored media by row id, never by a client-supplied path."""
from __future__ import annotations

import logging
import re

from ..paths import resolve_data_path

log = logging.getLogger("bugcap.dashboard")
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024


def parse_range(header: str | None, size: int):
    """None = no (usable) range, 'invalid' = unsatisfiable, else (start, end) inclusive."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if not match or (match.group(1) == "" and match.group(2) == ""):
        return None
    first, last = match.groups()
    if first == "":  # suffix: last N bytes
        n = int(last)
        if n == 0 or size == 0:
            return "invalid"
        return max(0, size - n), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or (last and int(last) < start):
        return "invalid"
    return start, min(end, size - 1)


def serve_media(handler, rel_path, mime: str, range_header: str | None) -> None:
    """`rel_path` is the stored data-relative path; it must resolve inside images/ or media/."""
    try:
        path = resolve_data_path(rel_path)
        if not path.is_file():
            raise ValueError("missing file")
    except (ValueError, OSError, TypeError):
        log.warning("media path rejected: %r", rel_path)
        handler.send_json(404, {"code": "not_found", "message": "media not found"})
        return
    size = path.stat().st_size
    rng = parse_range(range_header, size)
    if rng == "invalid":
        handler.send_response(416)
        handler.send_security_headers()
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    start, end = rng if rng else (0, size - 1)
    handler.send_response(206 if rng else 200)
    handler.send_security_headers()
    handler.send_header("Content-Type", mime)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, max-age=3600")
    handler.send_header("Content-Length", str(end - start + 1) if size else "0")
    if rng:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    if not size:
        return
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(CHUNK, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)
