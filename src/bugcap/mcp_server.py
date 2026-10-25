"""stdio MCP server built on the official `mcp` SDK (optional extra `bugcap[mcp]`).

The SDK is imported lazily so the core CLI works without it; `bugcap mcp-serve`
without the extra fails with a clear install hint. Tool logic lives in `agent_api`."""

import functools
import json
import logging
import os
import sys
import time
from typing import Annotated, Literal, Optional

from . import agent_api, logs
from .paths import db_path
from .store import Store

log = logging.getLogger("bugcap.mcp")

def _install_hint() -> str:
    """Computed per call (not a constant) so it always names the interpreter actually
    running `bugcap mcp-serve` right now.

    Report #9: a user installed bugcap in dev mode (no extra) first, got this hint, ran
    the suggested `pipx install 'bugcap[mcp]'` -- and still hit it. pipx had refused to
    touch the `bugcap` shim because it already pointed elsewhere ("File exists ... Not
    modifying."), so the dev-mode install kept running. Naming the interpreter here turns
    that into something diagnosable instead of a silent repeat of the same error."""
    return (
        "The MCP server needs the 'mcp' extra: pipx install 'bugcap[mcp]' "
        "(or pipx inject bugcap mcp).\n"
        f"Running from: {sys.executable}\n"
        "If you just installed the extra and still see this, the `bugcap` on PATH may be "
        "a different install than the one you just updated (a leftover shim from an "
        "earlier `pip install -e .`, `uv tool install` or `pipx install` can shadow it "
        "silently -- on Windows, pipx warns \"File exists ... Not modifying.\" instead of "
        "replacing it). Check with `where bugcap` (or `which bugcap`), then reinstall over "
        "it with `pipx install 'bugcap[mcp]' --force`."
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
        from mcp.types import ToolAnnotations
        from pydantic import Field
    except ImportError as exc:  # pragma: no cover - exercised via subprocess test
        raise MCPUnavailable(_install_hint()) from exc

    server = FastMCP(
        "bugcap",
        instructions=(
            "bugcap stores bug reports locally: a title, notes, annotated screenshots and attached "
            "files, optionally linked to a GitHub issue. Start with list_reports, read one with "
            "get_report (it returns the screenshots as images), then add evidence with attach_image, "
            "attach_file or request_screenshot and record findings with update_notes."
        ),
    )
    _log_client_initialize()

    def tool(title: str, **hints):
        def register(fn):
            return server.tool(title=title, annotations=ToolAnnotations(title=title, **hints))(_logged(fn))
        return register

    ReportId = Annotated[int, Field(description="Numeric report id, as returned by list_reports (e.g. 12).")]
    Labels = Annotated[
        Optional[list[Optional[str]]],
        Field(description=(
            "Optional short names, one per entry in `sources` and in the same order; use null to leave "
            "one unlabeled. A label lets notes refer to the item as @label."
        )),
    ]

    @tool("List bug reports", readOnlyHint=True, openWorldHint=False)
    def list_reports(
        all: Annotated[bool, Field(
            description="false (default): only reports filed for the repo the server runs in. true: every repo."
        )] = False,
        status: Annotated[
            Optional[Literal["open", "in-progress", "resolved", "closed", "wontfix"]],
            Field(description="Keep only reports with this status. Default: every status."),
        ] = None,
        limit: Annotated[Optional[int], Field(description="Return at most this many reports, newest first.")] = None,
    ) -> str:
        """List bug reports stored by bugcap, newest first. Use this to find a report id; it returns
        only summaries (id, title, status, tags, repo, created_at, linked GitHub issue) and no notes
        or images, so call get_report for the full report. Read-only and local: no network access.
        Returns a JSON array, empty when nothing matches."""
        with Store() as store:
            return json.dumps(agent_api.list_reports(store, all=all, status=status, limit=limit))

    @tool("Get a bug report", readOnlyHint=True, openWorldHint=False)
    def get_report(id: ReportId):
        """Read one bug report in full: title, body, notes, status, tags, linked GitHub issue and the
        list of attached media, followed by every screenshot as image content so you can see it.
        Use this after list_reports to understand a bug before fixing it. Notes refer to media as
        @i1, @d1 or @label; `resolved_references` maps each of those tokens to its media index.
        Read-only and local. Returns {"error": ...} when no report has this id."""
        with Store() as store:
            out = agent_api.get_report(store, id)
        if "error" in out:
            return json.dumps(out)
        content = [json.dumps(out["report"])]
        for img in out["images"]:
            content.append(Image(data=img["bytes"], format=_image_format(img["mime"])))
        return content

    @tool("Ask the user for a screenshot", readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    def request_screenshot(
        report_id: Annotated[Optional[int], Field(
            description="Report to attach the screenshot to. Give this or `issue`; this wins if both are set."
        )] = None,
        issue: Annotated[Optional[str], Field(description=(
            "GitHub issue to attach it to instead, as 'owner/repo#123' or '123' for the repo configured "
            "in .bugcap.toml. A report is created for the issue if none exists yet."
        ))] = None,
        message: Annotated[Optional[str], Field(
            description="What you want the user to capture, shown to them before the capture tool opens."
        )] = None,
        timeout_seconds: Annotated[int, Field(
            description="How long to wait for the user before giving up, in seconds (default 300)."
        )] = 300,
        note: Annotated[Optional[str], Field(
            description="Text appended to the report's notes and tied to the new screenshot, e.g. 'after the fix'."
        )] = None,
    ):
        """Ask the human at the machine to take a screenshot (for example to show a bug, or to check a
        fix) and attach it to a report. Use this when you need visual evidence you cannot produce
        yourself; to attach an image file that already exists, use attach_image. Opens the user's
        capture tool and blocks until they finish, cancel or `timeout_seconds` passes. Adds the image
        to the report (and creates a report for `issue` if needed). Returns {"status": "captured",
        "report_id"} plus the screenshot as image content, or a status of "cancelled", "error" or
        "non_interactive" (no desktop available, e.g. over SSH or in a container) with a message."""
        with Store() as store:
            out = agent_api.request_screenshot(
                store, report_id=report_id, issue=issue, message=message, timeout_seconds=timeout_seconds, note=note
            )
        image = out.pop("image", None)
        content = [json.dumps(out)]
        if image:
            content.append(Image(data=image["bytes"], format=_image_format(image["mime"])))
        return content

    @tool("Import GitHub issues", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    def pull_issues(
        repo: Annotated[Optional[str], Field(
            description="GitHub repo as 'owner/name'. Defaults to the repo configured in .bugcap.toml."
        )] = None,
        labels: Annotated[Optional[list[str]], Field(
            description="Only import issues carrying all of these labels, e.g. ['bug']."
        )] = None,
        limit: Annotated[int, Field(description="Maximum number of issues to fetch (default 30).")] = 30,
    ) -> str:
        """Import open GitHub issues into bugcap as reports, so you can read them with get_report and
        attach screenshots to them. Use this when the bug you need lives in GitHub rather than in
        bugcap yet. Calls the GitHub API through the user's `gh` login. Safe to repeat: an issue
        that is already imported only has its title and body refreshed, never its notes, tags or
        status. Returns {"created", "updated", "unchanged"} counts, or {"error": ...} when no repo
        is given or configured, or `gh` is not signed in."""
        with Store() as store:
            return json.dumps(agent_api.pull_issues(store, repo=repo, labels=labels, limit=limit))

    @tool("Attach images to a report", readOnlyHint=False, destructiveHint=False, openWorldHint=True)
    def attach_image(
        id: ReportId,
        sources: Annotated[list[str], Field(description=(
            "1 to 20 images to add: local file paths, glob patterns (e.g. 'shots/*.png') or "
            "http(s) URLs to download."
        ))],
        labels: Labels = None,
    ) -> str:
        """Add existing images (PNG, JPEG, GIF or WebP) to a bug report, for example a screenshot
        you saved or a diagram from a URL. Use attach_file instead for logs, videos or other
        non-image files, and request_screenshot when the user has to take the picture. Copies each
        image into bugcap's local store (URLs are downloaded) and appends it to the report; existing
        media is kept. Notes can then refer to it as @i<n> or @label. Returns {"added": [{index,
        label, kind, size_bytes, source}], "rejected": [{source, reason}]}: one bad source does not
        stop the others."""
        with Store() as store:
            return json.dumps(agent_api.attach_image(store, id, sources, labels))

    @tool("Attach files to a report", readOnlyHint=False, destructiveHint=False, openWorldHint=True)
    def attach_file(
        id: ReportId,
        sources: Annotated[list[str], Field(description=(
            "1 to 20 files to add: local file paths, glob patterns (e.g. 'logs/*.txt') or "
            "http(s) URLs to download."
        ))],
        labels: Labels = None,
    ) -> str:
        """Add files of any type (logs, stack traces, HAR captures, videos, configs) to a bug report as
        supporting evidence. Use attach_image for pictures so they are returned as images by
        get_report. Copies each file into bugcap's local store (URLs are downloaded) and appends it
        to the report; existing media is kept. Attached files are never uploaded to GitHub. Notes
        can then refer to a file as @d<n> or @label. Returns {"added": [...], "rejected": [{source,
        reason}]}: one bad source does not stop the others."""
        with Store() as store:
            return json.dumps(agent_api.attach_file(store, id, sources, labels))

    @tool("Replace a report's notes", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
    def update_notes(
        id: ReportId,
        notes: Annotated[str, Field(description=(
            "The complete new notes, in Markdown. Refer to attachments as @i1, @d1 or @label."
        ))],
    ) -> str:
        """Overwrite a bug report's notes with new text, for example to record a diagnosis, steps to
        reproduce or what a fix changed. The previous notes are replaced, not appended to: read
        them with get_report first and include whatever should be kept. Every @ reference must
        match media attached to the report; an unknown one is rejected with an error and nothing
        is saved. `#12` links another report; one that does not exist is kept and listed in
        `warnings`. Local only. Returns {"report_id", "notes", "references", "warnings"}."""
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
