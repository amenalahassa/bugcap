"""stdio MCP server built on the official `mcp` SDK (optional extra `bugcap[mcp]`).

The SDK is imported lazily so the core CLI works without it; `bugcap mcp-serve`
without the extra fails with a clear install hint. Tool logic lives in `agent_api`."""
from __future__ import annotations

import json
from typing import Optional

from . import agent_api
from .store import Store

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


def build_server():
    """Construct the FastMCP server with the tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:  # pragma: no cover - exercised via subprocess test
        raise MCPUnavailable(INSTALL_HINT) from exc

    server = FastMCP("bugcap")

    @server.tool()
    def list_reports(all: bool = False, status: Optional[str] = None, limit: Optional[int] = None) -> str:
        """List bug reports (current repo by default; `all` for every repo)."""
        with Store() as store:
            return json.dumps(agent_api.list_reports(store, all=all, status=status, limit=limit))

    @server.tool()
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

    @server.tool()
    def request_screenshot(
        report_id: Optional[int] = None,
        issue: Optional[str] = None,
        message: Optional[str] = None,
        timeout_seconds: int = 300,
    ):
        """Ask the user to capture a screenshot for a report or issue (blocks when a UI exists)."""
        with Store() as store:
            out = agent_api.request_screenshot(
                store, report_id=report_id, issue=issue, message=message, timeout_seconds=timeout_seconds
            )
        image = out.pop("image", None)
        content = [json.dumps(out)]
        if image:
            content.append(Image(data=image["bytes"], format=_image_format(image["mime"])))
        return content

    @server.tool()
    def pull_issues(repo: Optional[str] = None, labels: Optional[list[str]] = None, limit: int = 30) -> str:
        """Import GitHub issues as reports (same as `bugcap github pull`)."""
        with Store() as store:
            return json.dumps(agent_api.pull_issues(store, repo=repo, labels=labels, limit=limit))

    @server.tool()
    def attach_image(id: int, sources: list[str], labels: Optional[list[Optional[str]]] = None) -> str:
        """Attach images (file paths, globs or http(s) URLs) to a report, with optional labels
        (one per source, null for none). Notes can then refer to them as @1 or @label."""
        with Store() as store:
            return json.dumps(agent_api.attach_image(store, id, sources, labels))

    @server.tool()
    def update_notes(id: int, notes: str) -> str:
        """Replace a report's notes. @1 / @label references must point at the report's images."""
        with Store() as store:
            return json.dumps(agent_api.update_notes(store, id, notes))

    return server


def run() -> None:
    """Run the stdio server (blocking). Raises MCPUnavailable if the SDK is missing."""
    build_server().run()
