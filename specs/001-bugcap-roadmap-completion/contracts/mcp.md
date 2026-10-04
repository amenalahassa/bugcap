# MCP Contract (stdio, official `mcp` SDK)

Transport, handshake and error codes are provided by the SDK (`FastMCP`, stdio). Contract-relevant behavior (SDK-defined, verified by tests): `initialize` returns `serverInfo.name = "bugcap"` and a `tools` capability; `tools/list` lists the four tools below with JSON schemas derived from type hints. Reference of methods: `initialize` (returns `protocolVersion`, `capabilities: {tools: {}}`, `serverInfo: {name: "bugcap", version}`), `notifications/initialized` (no reply), `ping`, `tools/list`, `tools/call`. Unknown method → error -32601; invalid params → -32602; parse error → -32700. Tool failures are results with `isError: true`.

## Tools

| Tool | Arguments | Result |
|---|---|---|
| `list_reports` | `all?: bool` (default: current repo of server cwd), `status?: str`, `limit?: int` | text: JSON array of `{id,title,status,tags,repo,created_at,synced_refs}` |
| `get_report` | `id: int` | text JSON of the report + one `image` content block (`data` base64, `mimeType`) per image |
| `request_screenshot` | `report_id?: int`, `issue?: str`, `message?: str`, `timeout_seconds?: int=300` | UI available: blocks, then image content + `{status:"captured", report_id}`; else `{status:"non_interactive"}`; cancel `{status:"cancelled"}` |
| `pull_issues` | `repo?: str`, `labels?: [str]`, `limit?: int` | text JSON `{created,updated,unchanged}` |

## Claude Code config (documented in README)

Requires the extra: `pipx install 'bugcap[mcp]'` (or `uv tool install 'bugcap[mcp]'`).

```bash
claude mcp add bugcap -- bugcap mcp-serve
```
or `.mcp.json`:
```json
{ "mcpServers": { "bugcap": { "command": "bugcap", "args": ["mcp-serve"] } } }
```
