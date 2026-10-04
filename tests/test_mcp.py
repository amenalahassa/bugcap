"""T037: MCP protocol over a stdio subprocess (needs the `mcp` extra)."""
import asyncio
import os
import subprocess
import sys

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

EXPECTED_TOOLS = {"list_reports", "get_report", "request_screenshot", "pull_issues"}


def _seed_report(home) -> int:
    env = dict(os.environ, BUGCAP_HOME=str(home))
    os.environ["BUGCAP_HOME"] = str(home)
    from bugcap.store import Store

    img = home / "shot.png"
    (home).mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n seed")
    with Store() as store:
        return store.add("Seeded", image_paths=[str(img)]).id


async def _drive(home):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bugcap.cli", "mcp-serve"],
        env=dict(os.environ, BUGCAP_HOME=str(home)),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            report = await session.call_tool("get_report", {"id": 1})
            return init, tools, report


def test_mcp_handshake_tools_and_image(bugcap_home):
    home = bugcap_home / "data"
    _seed_report(home.parent)  # seed under BUGCAP_HOME (store uses <home>/data)

    init, tools, report = asyncio.run(asyncio.wait_for(_drive(bugcap_home), timeout=30))

    # initialize: name + tools capability
    assert init.serverInfo.name == "bugcap"
    assert init.capabilities.tools is not None

    # tools/list: exactly the four tools, each with an input schema
    names = {t.name for t in tools.tools}
    assert names == EXPECTED_TOOLS
    for tool in tools.tools:
        assert tool.inputSchema  # schema derived from type hints

    # get_report: an image content block is present (handshake success also proves
    # nothing but protocol was written to stdout)
    kinds = [getattr(c, "type", None) for c in report.content]
    assert "image" in kinds
    image = next(c for c in report.content if getattr(c, "type", None) == "image")
    assert image.data and image.mimeType == "image/png"


def test_mcp_serve_without_extra_prints_hint(bugcap_home):
    # Simulate the `mcp` extra being absent by poisoning the import in a subprocess.
    code = (
        "import sys; "
        "sys.modules['mcp']=None; sys.modules['mcp.server']=None; "
        "sys.modules['mcp.server.fastmcp']=None; "
        "from bugcap import cli; raise SystemExit(cli.main(['mcp-serve']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env=dict(os.environ, BUGCAP_HOME=str(bugcap_home)),
    )
    assert proc.returncode == 1
    assert "mcp" in proc.stderr.lower() and "extra" in proc.stderr.lower()
