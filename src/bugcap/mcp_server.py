"""stdio MCP server built on the official `mcp` SDK (optional extra `bugcap[mcp]`).

The SDK is imported lazily so the core CLI works without it; `bugcap mcp-serve`
without the extra fails with a clear install hint. Tool logic lives in `agent_api`."""
from __future__ import annotations

import functools
import json
import logging
import os
import sys
import time
from typing import Optional

from . import agent_api, logs
from .paths import db_path
from .store import Store

log = logging.getLogger("bugcap.mcp")

INSTALL_HINT = (
    "The MCP server needs the 'mcp' extra: pipx install 'bugcap[mcp]' "
    "(or pipx inject bugcap mcp)."
)


class MCPUnavailable(RuntimeError):
    pass


def _image_format(mime: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }.get(mime, "png")


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("bugcap")
    except Exception:  # not installed (running from a checkout)
        return "unknown"


def _problem(result) -> Optional[str]:
    """The error text of a tool result, if it reports one (tools return JSON strings or content lists)."""
    first = result[0] if isinstance(result, list) and result else result
    if not isinstance(first, str):
        return None
    try:
        data = json.loads(first)
    except ValueError:
        return None
    if isinstance(data, dict):
        if data.get("error"):
            return f"{data.get('code', 'error')}: {data['error']}"
        if data.get("status") in ("error", "cancelled", "non_interactive"):
            return f"{data['status']}: {data.get('message', '')}"
    return None


def _logged(fn):
    """Log each tool call: name and argument names (values only at DEBUG, since notes can be
    private), outcome and duration, and any exception with its traceback."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        name = fn.__name__
        started = time.monotonic()
        log.info("tool %s called (arguments: %s)", name, ", ".join(sorted(kwargs)) or "none")
        if log.isEnabledFor(logging.DEBUG):
            log.debug("tool %s arguments: %.500r", name, kwargs)
        try:
            result = fn(*args, **kwargs)
        except Exception:
            log.exception("tool %s failed after %d ms", name, (time.monotonic() - started) * 1000)
            raise
        millis = (time.monotonic() - started) * 1000
        problem = _problem(result)
        if problem:
            log.warning("tool %s returned an error after %d ms: %s", name, millis, problem)
        else:
            log.info("tool %s ok in %d ms", name, millis)
        return result

    return wrapper


def _log_client_initialize() -> None:
    """Log the client's initialize request (name, version, protocol). Best effort: it relies on
    an SDK internal, so a changed SDK only costs this one log line."""
    try:
        from mcp import types
        from mcp.server.session import ServerSession
    except ImportError:  # pragma: no cover
        return
    original = getattr(ServerSession, "_received_request", None)
    if original is None or getattr(original, "_bugcap_wrapped", False):
        return

    async def received(self, responder):
        try:
            request = responder.request.root
            if isinstance(request, types.InitializeRequest):
                params = request.params
                log.info(
                    "client initialize: %s %s (protocol %s)",
                    params.clientInfo.name, params.clientInfo.version, params.protocolVersion,
                )
        except Exception:  # never let logging break the protocol
            log.debug("could not log the initialize request", exc_info=True)
        return await original(self, responder)

    received._bugcap_wrapped = True  # type: ignore[attr-defined]
    ServerSession._received_request = received  # type: ignore[method-assign]


def build_server():
    """Construct the FastMCP server with the tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:  # pragma: no cover - exercised via subprocess test
        raise MCPUnavailable(INSTALL_HINT) from exc

    server = FastMCP("bugcap")
    _log_client_initialize()

    def tool():
        def register(fn):
            return server.tool()(_logged(fn))
        return register

    @tool()
    def list_reports(all: bool = False, status: Optional[str] = None, limit: Optional[int] = None) -> str:
        """List bug reports (current repo by default; `all` for every repo)."""
        with Store() as store:
            return json.dumps(agent_api.list_reports(store, all=all, status=status, limit=limit))

    @tool()
    def get_report(id: int):
        """Fetch a report's metadata plus each attached image as image content."""
        with Store() as store:
            out = agent_api.get_report(store, id)
        if "error" in out:
            return json.dumps(out)
        content = [json.dumps(out["report"])]
        for img in out["images"]:
            content.append(Image(data=img["bytes"], format=_image_format(img["mime"])))
        return content

    @tool()
    def request_screenshot(
        report_id: Optional[int] = None,
        issue: Optional[str] = None,
        message: Optional[str] = None,
        timeout_seconds: int = 300,
        note: Optional[str] = None,
    ):
        """Ask the user to capture a screenshot for a report or issue (blocks when a UI exists).
        `note` is appended to the report's notes, tied to the new image."""
        with Store() as store:
            out = agent_api.request_screenshot(
                store, report_id=report_id, issue=issue, message=message, timeout_seconds=timeout_seconds, note=note
            )
        image = out.pop("image", None)
        content = [json.dumps(out)]
        if image:
            content.append(Image(data=image["bytes"], format=_image_format(image["mime"])))
        return content

    @tool()
    def pull_issues(repo: Optional[str] = None, labels: Optional[list[str]] = None, limit: int = 30) -> str:
        """Import GitHub issues as reports (same as `bugcap github pull`)."""
        with Store() as store:
            return json.dumps(agent_api.pull_issues(store, repo=repo, labels=labels, limit=limit))

    @tool()
    def attach_image(id: int, sources: list[str], labels: Optional[list[Optional[str]]] = None) -> str:
        """Attach images (file paths, globs or http(s) URLs) to a report, with optional labels
        (one per source, null for none). Notes can then refer to them as @i1 or @label."""
        with Store() as store:
            return json.dumps(agent_api.attach_image(store, id, sources, labels))

    @tool()
    def update_notes(id: int, notes: str) -> str:
        """Replace a report's notes. @i1 / @label references must point at the report's images."""
        with Store() as store:
            return json.dumps(agent_api.update_notes(store, id, notes))

    return server


def run(log_level: Optional[str] = None, log_file: Optional[str] = None) -> None:
    """Run the stdio server (blocking). Raises MCPUnavailable if the SDK is missing.
    Logs startup, client initialize, every tool call and any crash (see `logs.py`)."""
    _, target = logs.setup_logging(log_level, log_file)
    if target is not None:
        print(f"bugcap mcp-serve: logging to {target}", file=sys.stderr, flush=True)
    log.info(
        "starting bugcap %s MCP server (python %s, database %s, pid %s)",
        _version(), sys.version.split()[0], db_path(), os.getpid(),
    )
    try:
        server = build_server()
    except MCPUnavailable as exc:
        log.error("cannot start: %s", exc)
        raise
    try:
        server.run()
    except KeyboardInterrupt:
        log.info("interrupted; shutting down")
    except Exception:
        log.exception("server crashed")
        raise
    finally:
        log.info("server stopped")
