import json

from bugcap import drafts
from fixtures.make_images import png_bytes


def _png(tmp_path, name="s.png"):
    p = tmp_path / name
    p.write_bytes(png_bytes())
    return p


def test_save_writes_png_and_sidecar(bugcap_home, tmp_path):
    shot = _png(tmp_path)
    d = drafts.save_draft("o/r", shot, {"title": "T", "notes": "N", "tags": ["a"], "status": "open"})
    assert not shot.exists()
    assert d.png_path.read_bytes() == png_bytes()
    meta = json.loads(d.png_path.with_suffix(".json").read_text())
    assert set(meta) == {"created_at", "repo", "title", "notes", "tags", "status"}
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
    bad.png_path.with_suffix(".json").write_text("{not json")
    assert [d.id for d in drafts.list_drafts("o/r")] == [good.id]
    assert "unreadable draft" in capsys.readouterr().err
