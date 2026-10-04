# Dashboard HTTP Contract (feature 002)

Served by `bugcap dashboard` on `127.0.0.1:<port>` only. JSON under `/api`, media under `/media`, static UI at `/`. Every response has `X-Content-Type-Options: nosniff` and a `Content-Security-Policy` that allows only `'self'` for scripts, styles and images, and `media-src 'self' blob:` for players. No external origins are referenced.

## Access rules (all routes)

| Check | Rule | Failure |
|-------|------|---------|
| Host header | Must be `127.0.0.1:<port>` or `localhost:<port>` | `400` |
| Origin header (if present) | Must equal `http://127.0.0.1:<port>` or `http://localhost:<port>` | `403` |
| Token (mutating methods only) | `X-Bugcap-Token` equals the process token (constant-time compare) | `403` `{"code":"bad_token"}` |
| Unknown route | | `404` |

Mutating methods: `POST`, `PATCH`, `PUT`, `DELETE`. Reads are `GET` only.

## Session token

`GET /api/session` → `200 {"token": "<token_urlsafe(32)>"}`. Held in memory for the process lifetime; regenerated on restart. Not written to disk or logs.

## Reports

### `GET /api/reports`

Query: `repo`, `tag` (repeatable, AND semantics), `status`, `q` (case-insensitive substring over title and notes), `limit` (default 200, max 1000), `offset`.

`200`
```json
{"total": 42, "items": [{"id": 7, "title": "...", "status": "open", "tags": ["auth"], "repo": "bugcap", "created_at": "...", "media_count": 2}]}
```

`400` `{"code":"bad_query","message":"status must be one of …"}`

### `GET /api/reports/<id>`

`200`
```json
{
  "id": 7, "title": "...", "status": "open", "tags": [], "repo": "bugcap", "created_at": "...",
  "notes_raw": "See @1",
  "notes_html_segments": [{"text": "See "}, {"ref": {"token": "@1", "index": 1, "media_id": 31, "kind": "image"}}],
  "media": [{"id": 31, "index": 1, "label": "login-error", "kind": "image", "mime": "image/png", "size_bytes": 48211, "url": "/media/31"}],
  "frames": {"<media id>": [{"frame_no": 1, "url": "/media/…"}]},
  "synced_refs": {"github.issue": "https://github.com/owner/repo/issues/12"}
}
```

Notes are returned as **segments**, not HTML, so the client renders text and images without `innerHTML` (no XSS surface). `404` `{"code":"not_found"}`.

### `POST /api/reports/<id>/status` (token required)

Body: `{"status": "resolved"}` → `200` with the updated summary; `400 invalid_status`.

### `POST /api/reports/<id>/tags` (token required)

Body: `{"add": ["x"], "remove": ["y"]}` → `200` with tags; `400` on malformed input.

### `PUT /api/reports/<id>/notes` (token required)

Body: `{"notes": "..."}`. Validated by `service.set_notes`:

- `200` with the updated report.
- `422` `{"code":"invalid_reference","token":"@3","valid":["@1","@2"],"message":"unknown reference @3 in notes"}`. Stored notes unchanged.

## Media

### `GET /media/<media_id>`

- Streams the stored file (`images/…`, `media/…`) after the containment check.
- `Content-Type` from the stored `mime`.
- `Accept-Ranges: bytes`. A `Range: bytes=a-b` (or `a-`, or `-n`) request → `206` with `Content-Range`; unsatisfiable → `416` with `Content-Range: bytes */<size>`.
- `Cache-Control: private, max-age=3600`.
- Unknown id → `404`. A stored path that fails containment → `404` (the file is never opened) and logged as `media path rejected`.
- For `frames` items, use `GET /media/<media_id>/frames/<frame_no>`. The `frame_no` is an integer checked against the table; no path segment is ever used.

## Static UI

`GET /` → `index.html`; `GET /static/app.js`, `GET /static/app.css`. The static route maps only the names in an allowlist (`{"app.js","app.css"}`) to package resources; any other name is `404`. No directory listing.

## Test obligations (for the implementation tests)

- A tampered `media.path` such as `../../etc/passwd` or an absolute path → `404`, file not read.
- A symlink inside `images/` pointing outside → refused (`realpath` check).
- `POST` without token → `403`; wrong token → `403`; right token → success.
- `POST` with a foreign `Origin` → `403` even with a valid token.
- `Host: evil.example` → `400` on every route.
- `Range` variants: `bytes=0-99`, `bytes=100-`, `bytes=-50`, invalid → `416`.
