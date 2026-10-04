# Data Model

## Report (table `reports`, schema version 1)

| Field | Type | Notes |
|---|---|---|
| id | integer PK | |
| created_at | ISO-8601 UTC text | |
| title | text | remote-owned when linked to an issue (pull refreshes it) |
| body | text, default '' | NEW: issue body from pull; remote-owned |
| notes | text | local-owned; pull never changes it |
| image_paths | JSON list of str | absolute paths in images dir |
| tags | JSON list of str | local-owned; auto includes repo tag on capture |
| status | text, default 'open' | local-owned; set from issue state only on first import |
| repo | text NULL | NEW: repo key (GitHub slug, else tag) from `.bugcap.toml`; NULL for legacy/unscoped |
| synced_refs | JSON dict str→str | see keys below |

Validation: title non-empty; status in {open, in-progress, resolved, closed, wontfix} for `edit --status` (free text from legacy rows tolerated on read); tags trimmed, case-preserved, unique, order-preserving.

### synced_refs keys
- `github.issue`: `owner/repo#N`
- `github.comment_hash`: sha256 hex of last synced content
- `github.image.<basename>`: `owner/repo:path@commit`

## Migration (0 → 1)
Add `repo` and `body` if absent; set `PRAGMA user_version = 1`; idempotent; no row rewrites.

## RepoConfig (`.bugcap.toml`)
```toml
tag = "myrepo"
github = "owner/repo"        # optional
[sync]                       # optional
images_repo = "owner/assets"
images_path = "bugcap-images"
images_branch = "main"
```

## Global config (`config.toml`)
`[sync]` same three keys as defaults; `[consent] images_repos = "owner/a,owner/b"` (private repos where the user already approved image commits; public repos are never remembered).

## Destination / refs (runtime, not stored)
`IssueRef(slug, number, url)`, `FileRef(slug, path, commit, permalink)`.

## State transitions
Report status: user-driven via `edit --status`. Sync state: unsynced → issue linked (`github.issue`) → images recorded (`github.image.*`) → content hash recorded; each step persisted immediately.
