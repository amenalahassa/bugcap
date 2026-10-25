import json

from fixtures.make_images import png_bytes

from bugcap import drafts


def _png(tmp_path, name="s.png"):
    p = tmp_path / name
    p.write_bytes(png_bytes())
    return p


def test_save_writes_png_and_sidecar(bugcap_home, tmp_path):
    shot = _png(tmp_path)
    d = drafts.save_draft("o/r", shot, {"title": "T", "notes": "N", "tags": ["a"], "status": "open"})
    assert not shot.exists()
    assert d.png_path.read_bytes() == png_bytes()
    meta = json.loads((d.png_path.parent / f"{d.id}.json").read_text())
    assert set(meta) == {"created_at", "repo", "title", "notes", "tags", "status", "media"}
    assert meta["repo"] == "o/r" and meta["tags"] == ["a"]


def test_list_only_this_repo(bugcap_home, tmp_path):
    a = drafts.save_draft("o/r", _png(tmp_path, "a.png"), {"title": "a"})
    drafts.save_draft("x/y", _png(tmp_path, "b.png"), {"title": "b"})
    drafts.save_draft(None, _png(tmp_path, "c.png"), {"title": "c"})
    assert [d.id for d in drafts.list_drafts("o/r")] == [a.id]
    assert [d.title for d in drafts.list_drafts(None)] == ["c"]


def test_delete_removes_both_files(bugcap_home, tmp_path):
    d = drafts.save_draft("o/r", _png(tmp_path), {"title": "a"})
    drafts.delete_draft(d.id)
    assert not d.png_path.exists() and not d.png_path.with_suffix(".json").exists()
    drafts.delete_draft(d.id)  # idempotent


def test_corrupt_sidecar_skipped_with_warning(bugcap_home, tmp_path, capsys):
    good = drafts.save_draft("o/r", _png(tmp_path, "a.png"), {"title": "good"})
    bad = drafts.save_draft("o/r", _png(tmp_path, "b.png"), {"title": "bad"})
    (bad.png_path.parent / f"{bad.id}.json").write_text("{not json")
    assert [d.id for d in drafts.list_drafts("o/r")] == [good.id]
    assert "unreadable draft" in capsys.readouterr().err


def test_multi_media_and_note_only_drafts_round_trip(bugcap_home, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"vid")
    frames = [tmp_path / f"f{n}.png" for n in (1, 2)]
    for f in frames:
        f.write_bytes(png_bytes())
    items = [
        {"kind": "image", "path": str(_png(tmp_path)), "mime": "image/png", "size_bytes": 5, "frames": []},
        {"kind": "video", "path": str(video), "mime": "video/mp4", "size_bytes": 3, "frames": []},
        {"kind": "frames", "path": None, "mime": "image/png", "size_bytes": 10,
         "frames": [(str(f), 5) for f in frames]},
    ]
    d = drafts.save_draft("o/r", None, {"title": "multi"}, items=items)
    loaded = drafts.load_draft(d.id)
    assert [i["kind"] for i in loaded.items] == ["image", "video", "frames"]
    assert all(__import__("pathlib").Path(p).is_file() for i in loaded.items for p in ([i["path"]] if i["path"] else []) + [f for f, _ in i["frames"]])
    drafts.delete_draft(d.id)
    assert drafts.load_draft(d.id) is None
    assert list(drafts.drafts_dir().iterdir()) == []

    note_only = drafts.save_draft("o/r", None, {"title": "just a note"})
    assert drafts.load_draft(note_only.id).items == []


def test_legacy_png_draft_still_loads(bugcap_home):
    directory = drafts.drafts_dir()
    (directory / "old.png").write_bytes(png_bytes())
    (directory / "old.json").write_text(json.dumps({"created_at": "2026", "repo": "o/r", "title": "old"}))
    d = drafts.load_draft("old")
    assert d.title == "old" and d.items[0]["kind"] == "image" and d.png_path.name == "old.png"
    drafts.delete_draft("old")
    assert list(directory.iterdir()) == []


# --- progress drafts (format v2: media left in place) -----------------------------

def _progress_items(tmp_path):
    shot = _png(tmp_path, "keep.png")
    return shot, [{"number": 2, "kind": "image", "path": str(shot), "mime": "image/png", "size_bytes": 9,
                   "frames": [], "source": "keep.png", "shared": True}]


def test_write_progress_leaves_media_in_place_and_round_trips(bugcap_home, tmp_path):
    shot, items = _progress_items(tmp_path)
    draft_id = drafts.write_progress(None, "o/r", {"title": "T", "notes": "see @i2", "tags": ["a"]}, items)
    assert shot.exists()
    meta = json.loads((drafts.drafts_dir() / f"{draft_id}.json").read_text())
    assert meta["version"] == 2 and meta["updated_at"] and meta["media"][0]["path"] == str(shot)
    d = drafts.load_draft(draft_id)
    assert (d.title, d.notes, d.tags, d.repo) == ("T", "see @i2", ["a"], "o/r")
    assert d.items[0]["path"] == str(shot) and d.items[0]["number"] == 2
    assert d.items[0]["source"] == "keep.png" and d.items[0]["shared"] is True


def test_write_progress_rewrites_the_same_draft(bugcap_home, tmp_path):
    shot, items = _progress_items(tmp_path)
    draft_id = drafts.write_progress(None, "o/r", {"title": "one"}, items)
    created = drafts.load_draft(draft_id).created_at
    assert drafts.write_progress(draft_id, "o/r", {"title": "two"}, items) == draft_id
    assert [d.title for d in drafts.list_drafts("o/r")] == ["two"]
    assert drafts.load_draft(draft_id).created_at == created
    assert not list(drafts.drafts_dir().glob("*.tmp"))


def test_write_progress_is_atomic(bugcap_home, tmp_path, monkeypatch):
    shot, items = _progress_items(tmp_path)
    draft_id = drafts.write_progress(None, "o/r", {"title": "safe"}, items)

    def crash(*a, **k):
        raise OSError("power cut")

    monkeypatch.setattr(drafts.os, "replace", crash)
    try:
        drafts.write_progress(draft_id, "o/r", {"title": "lost"}, items)
    except OSError:
        pass
    assert drafts.load_draft(draft_id).title == "safe"


def test_progress_draft_without_media(bugcap_home):
    draft_id = drafts.write_progress(None, None, {"title": "just a note"}, [])
    d = drafts.load_draft(draft_id)
    assert d.title == "just a note" and d.items == []


def test_delete_never_removes_media_kept_in_place(bugcap_home, tmp_path):
    shot, items = _progress_items(tmp_path)
    draft_id = drafts.write_progress(None, "o/r", {"title": "T"}, items)
    drafts.delete_draft(draft_id)
    assert shot.exists() and drafts.load_draft(draft_id) is None


def test_progress_draft_is_listed_for_its_launch_repo_too(bugcap_home, tmp_path):
    shot, items = _progress_items(tmp_path)
    draft_id = drafts.write_progress(None, "other/repo", {"title": "filed elsewhere"}, items, launch_repo="o/r")
    assert [d.id for d in drafts.list_drafts("o/r")] == [draft_id]
    assert [d.id for d in drafts.list_drafts("other/repo")] == [draft_id]
    assert drafts.list_drafts("x/y") == []
