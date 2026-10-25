"""Smoke-test the MCP server image the way Glama checks it.

Starts the image with its default command (mcp-proxy in front of `bugcap mcp-serve`),
connects over streamable HTTP, and checks that the server initializes and lists the
expected tools. Run after `docker build -t bugcap-mcp .`:

    uv run --extra mcp python scripts/docker_smoke.py bugcap-mcp
"""
import asyncio
import subprocess
import sys
import time
import urllib.error
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

EXPECTED_TOOLS = {
    "list_reports", "get_report", "request_screenshot", "pull_issues", "attach_image", "attach_file", "update_notes",
}
PORT = 8080
URL = f"http://127.0.0.1:{PORT}/mcp"


def _wait_for_proxy(container: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=2)
            return
        except urllib.error.HTTPError:
            return  # the proxy answered, whatever the route says
        except OSError:
            time.sleep(1)
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    sys.exit(f"mcp-proxy did not come up within {timeout:.0f}s\n{logs.stdout}{logs.stderr}")


async def _check() -> None:
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
    missing = EXPECTED_TOOLS - tools
    if missing:
        sys.exit(f"server {init.serverInfo.name} is missing tools: {sorted(missing)}")
    print(f"ok: {init.serverInfo.name} {init.serverInfo.version}, {len(tools)} tools")


def main() -> None:
    image = sys.argv[1] if len(sys.argv) > 1 else "bugcap-mcp"
    container = subprocess.run(
        ["docker", "run", "-d", "--rm", "-p", f"{PORT}:{PORT}", image],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    try:
        _wait_for_proxy(container)
        asyncio.run(_check())
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True)


if __name__ == "__main__":
    main()
