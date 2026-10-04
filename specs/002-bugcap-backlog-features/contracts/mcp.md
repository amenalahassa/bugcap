# MCP Contract: new tools (feature 002)

Existing tools are unchanged: `list_reports`, `get_report`, `request_screenshot`, `pull_issues`. `get_report` gains media in its output (below). Logic lives in `service.py` through `agent_api.py`; the SDK-free functions are unit tested, and `mcp_server.py` only registers them.

## `attach_image`

Attach one or more images to an existing report.

**Input**

```json
{
  "id": 7,
  "sources": ["./shot.png", "https://example.com/a.png", "./shots/*.png"],
  "labels": ["login-error", null, null]
}
```

- `sources`: same rules as CLI `--image` (path, glob, http(s) URL). Required, 1–20 entries.
- `labels`: optional, paired with `sources` by position; `null` skips a label. A label cannot be given for a glob that matches more than one file.

**Output (success or partial)**

```json
{
  "report_id": 7,
  "added": [{"index": 3, "label": "login-error", "kind": "image", "size_bytes": 48211, "source": "./shot.png"}],
  "rejected": [{"source": "https://example.com/a.png", "reason": "not an image (content is text/html)"}]
}
```

**Errors** (returned as a JSON body with `error` and `code`, not as a protocol error): `not_found`, `duplicate_label`, `invalid_label`, `invalid_image`, `too_large`, `timeout`.

## `update_notes`

Replace a report's notes, with the same `@` validation as the CLI.

**Input**: `{"id": 7, "notes": "See @1 and @login-error"}`

**Output**: `{"report_id": 7, "notes": "...", "references": [{"token": "@1", "index": 1, "path": "images/…"}]}`

**Error** (`code: invalid_reference`): `{"code": "invalid_reference", "token": "@3", "valid": ["@1", "@2", "@login-error"], "message": "unknown reference @3 in notes"}`

## `get_report` (changed output)

Adds a `media` array (order = index) and resolves references:

```json
{
  "report": {"id": 7, "title": "...", "notes": "...", "media": [{"index": 1, "label": "login-error", "kind": "image", "mime": "image/png", "size_bytes": 48211}]},
  "resolved_references": [{"token": "@1", "index": 1}]
}
```

Image bytes are still returned as image content (existing behaviour). Video, frames and animated items are listed as metadata only (no bytes) to protect the context budget; a `read_media` tool is out of scope.

## `request_screenshot` (unchanged)

No new behaviour. It remains the way an agent asks a human to capture; `bugcap live` is the human-side loop for many reports.
