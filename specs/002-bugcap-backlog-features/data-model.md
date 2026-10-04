# Data Model: Bugcap Backlog Features

Storage: SQLite file `bugcap.db` in the data directory. Schema version moves from **1 to 2** (`PRAGMA user_version`). Migration steps are in §Migration below; the reasoning is in [research.md](research.md) §5.

## Entity: Report (table `reports`, existing columns unchanged)

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| created_at | TEXT | ISO 8601 UTC |
| title | TEXT NOT NULL | |
| body | TEXT | GitHub issue body (pull) |
| notes | TEXT | May contain `@` references, validated on save |
| image_paths | TEXT (JSON) | **Legacy.** Migration source only; never written after v2 |
| tags | TEXT (JSON array) | |
| status | TEXT | One of `STATUSES`; legacy values tolerated on read |
| repo | TEXT NULL | |
| synced_refs | TEXT (JSON object) | |
| media_seq | INTEGER NOT NULL DEFAULT 0 | Added in v2: highest media index ever issued for this report |

On the Python `Report` object: `media` (ordered list of media items) and `image_paths` (compatibility view: the stored path of each `kind = 'image'` item, in index order).

## Entity: Media item (table `media`)

One row per item. An item is one image, one video, one animated file, or one frames set.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER PK AUTOINCREMENT | | Stable id; used by `/media/<id>` |
| report_id | INTEGER NOT NULL | FK → reports.id ON DELETE CASCADE | |
| idx | INTEGER NOT NULL | `UNIQUE(report_id, idx)`, `idx >= 1` | Per-report 1-based index; never reused |
| label | TEXT NULL | Unique per report, case-insensitive: unique index on `(report_id, lower(label)) WHERE label IS NOT NULL` | Pattern `^[A-Za-z][A-Za-z0-9_-]*$` (validated in service) |
| kind | TEXT NOT NULL | `CHECK (kind IN ('image','video','frames','animated'))` | |
| path | TEXT NULL | Relative to data dir (`images/…` or `media/…`); **NULL for `frames`** | Containment checked on every read |
| mime | TEXT NOT NULL | `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `video/mp4`, `video/webm` | For `frames`: the keyframe mime |
| size_bytes | INTEGER NOT NULL | Exact final size; for `frames`, the sum of keyframes | Reported by `record` and `show` |
| source | TEXT NULL | Original path, glob match, URL, `recorded`, or `legacy` | Informational only; never re-read |
| created_at | TEXT NOT NULL | ISO 8601 UTC | |

### Entity: Frame (table `media_frames`)

Keyframes of a `frames` item, in order.

| Column | Type | Notes |
|--------|------|-------|
| media_id | INTEGER NOT NULL | FK → media.id ON DELETE CASCADE |
| frame_no | INTEGER NOT NULL | 1-based; `PRIMARY KEY (media_id, frame_no)` |
| path | TEXT NOT NULL | Relative, under `media/` |
| size_bytes | INTEGER NOT NULL | |

**Index rule**: `idx` = max(current maximum, `reports.media_seq`) + 1, computed inside the write transaction; `media_seq` is a per-report high-water mark updated on every insert. Removing an item leaves its index unused and later items keep theirs: indexes are never reused and never renumbered. `remove --force` only replaces references to the removed item.

## Entity: Reference (derived, not stored)

A token in `Report.notes`, resolved against the report's media at read time.

| Form | Meaning | Validation |
|------|---------|-----------|
| `@<digits>` (no leading zero) | Media with that `idx` | Must exist in the report |
| `@<label>` | Media with that label (case-sensitive match) | Must exist in the report |
| `@@` | Literal `@` | Always valid |
| any other `@…` outside code and emails | Unknown token | Refuses the save, names the token |

Never a reference: inside fenced code blocks, inside code spans, email-like text (`x@y`).

## Entity: Sync reference (existing `synced_refs`)

Existing keys are unchanged. Per-image keys keep `github.image.<basename>`. A frames set adds `github.frames.<idx>` → commit path. The dashboard reads these to show GitHub links.

## Entity: Live draft (filesystem, not in DB)

`drafts/<uuid>.png` plus `drafts/<uuid>.json`:

```json
{ "created_at": "2026-10-04T10:00:00Z", "repo": "bugcap", "title": "", "notes": "", "tags": [], "status": "open" }
```

A draft lives until it is saved (converted into a report, then deleted) or discarded.

## Validation rules

- Label: `^[A-Za-z][A-Za-z0-9_-]*$`, unique per report case-insensitively; a purely numeric label is refused.
- Index: integer ≥ 1, unique per report, never reused.
- Kind: one of four. `frames` needs at least one keyframe. `image` passes the magic-byte check.
- Size: URL download ≤ 25 MB; recording ≤ `--max-mb` (default 25).
- Status: `STATUSES`.
- Path: relative, under `images/` or `media/`, `realpath` containment on every read.

## State transitions

- **Media item**: `attached` (insert) → `relabeled` (update label, rewrite references) → `removed` (delete; referenced items refused unless `--force`, then references rewritten to `[image removed]`).
- **Live session**: `READY → CAPTURING → DETAILS → READY`; `CAPTURING → READY` on empty capture; `DETAILS → READY` on save or discard; closing with unsaved details saves a draft first.

## Migration (v1 → v2)

1. `BEGIN`.
2. Create `media` and `media_frames`, plus the indexes above.
3. For each row in `reports`, parse `image_paths` JSON. For each entry at 0-based position *i*, insert `media(report_id, idx = i+1, kind = 'image', path = <data-relative if under images/, else the legacy absolute path>, mime = <from extension>, size_bytes = <file size, or 0 if missing>, source = 'legacy', created_at = reports.created_at)`.
4. `PRAGMA user_version = 2`.
5. `COMMIT`. Any error → `ROLLBACK`; the database is unchanged.

Guarantees: the `reports` row count is unchanged; every legacy path appears exactly once in `media`; `image_paths` is untouched; re-running is a no-op (version check).
