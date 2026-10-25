# Contract: Draft Sidecar Format v2

File: `<data>/drafts/<uuid>.json`. Written by `drafts.write_progress()` atomically: write `<uuid>.json.tmp`, then `os.replace`.

```json
{
  "version": 2,
  "created_at": "2026-10-25T10:00:00+00:00",
  "updated_at": "2026-10-25T10:03:12+00:00",
  "repo": "owner/proj",
  "launch_repo": "owner/proj",
  "title": "Login fails",
  "notes": "See @1 and @3",
  "tags": ["proj"],
  "status": "open",
  "media": [
    {"number": 1, "kind": "image", "path": "C:/…/images/ab.png", "file": null, "mime": "image/png", "size_bytes": 123, "frames": [], "source": null, "shared": false},
    {"number": 3, "kind": "video", "path": null, "file": "<uuid>-3.mp4", "mime": "video/mp4", "size_bytes": 456, "frames": [], "source": null, "shared": false}
  ]
}
```

Rules:

- `path` (absolute, media left in place) is used for autosaved progress drafts; `file` (relative to `drafts/`) is used once the media is moved into `drafts/` (the "keep as draft" on quit, and all v1 drafts). Exactly one of them is set when the item has a main file; frame sets use `frames` as today (`[name_or_abs_path, size]`).
- `repo` is the repo picked in the form; `launch_repo` is the repo live mode ran in (defaults to `repo`). `list_drafts(r)` lists a draft when `r` matches either, so a bug filed against another repo is still offered where it was being written.
- `number` is optional. If it is missing (v1), items are numbered 1…n in order.
- A draft whose referenced files are missing is skipped with the existing warning (unchanged behaviour); a draft with `media: []` and typed fields is valid.
- Readers MUST accept v1 sidecars (no `version`) and legacy `<uuid>.png` + `<uuid>.json` drafts unchanged.
- `delete_draft(id)` removes the sidecar and `drafts/<id>-*` files only. Media referenced by absolute `path` is store-owned and is removed by Discard through `Staged.delete()`, never by `delete_draft`.
