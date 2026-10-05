# Security policy

## Supported versions

Only the latest release on PyPI receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately with GitHub's
[private vulnerability reporting](https://github.com/amenalahassa/bugcap/security/advisories/new).

Include what you found, the version, steps to reproduce, and the impact. You can expect an
acknowledgement within a few days and a fix or a plan as soon as it is confirmed. We'll credit you
in the release notes unless you prefer not to be named.

## Scope

Areas that matter most for bugcap:

- The local dashboard (loopback binding, Host/Origin checks, write token, static file serving)
- Fetching images from URLs and path handling (`ingest.py`)
- Running external tools (`gh`, capture and recording tools)
- The MCP server exposing local reports to agents
- Anything that could leak tokens or private screenshots during `sync`
