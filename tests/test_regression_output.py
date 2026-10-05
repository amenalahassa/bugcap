"""T045: `capture`/`list`/`show` output outside an initialized repo is unchanged (FR-026).

The expected strings below are the exact pre-feature formats; the test fails if any
scoping/repo change leaks into output when there is no .bugcap.toml in scope."""

from fixtures.make_images import png_bytes

from bugcap import cli
from bugcap.store import Store


def test_capture_output_unchanged(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # not a git repo / no .bugcap.toml
    img = tmp_path / "s.png"
    img.write_bytes(png_bytes())
    cli.main(["capture", "--image", str(img), "--title", "Broken thing", "--note", "n"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Saved report #1: Broken thing"
    assert out[1].startswith("  image: ")


def test_list_output_unchanged(bugcap_home, tmp_path, monkeypatch, capsys):
    with Store() as store:
        r = store.add("A title", tags=["x", "y"])
    monkeypatch.chdir(tmp_path)
    cli.main(["list"])
    line = capsys.readouterr().out.strip()
    created = Store(bugcap_home / "data" / "bugcap.db").get(r.id).created_at
    assert line == f"#{r.id}  {created}  {'open':8s} A title [x, y]"


def test_show_output_unchanged(bugcap_home, tmp_path, monkeypatch, capsys):
    with Store() as store:
        r = store.add("A title", notes="hello", image_paths=["/a/b.png"])  # repo is None
    monkeypatch.chdir(tmp_path)
    cli.main(["show", str(r.id)])
    out = capsys.readouterr().out
    created = Store(bugcap_home / "data" / "bugcap.db").get(r.id).created_at
    expected = (
        f"#{r.id}  A title\n"
        f"  created_at: {created}\n"
        f"  status:     open\n"
        f"  tags:       (none)\n"
        f"  notes:      hello\n"
        f"  images:\n"
        f"    - /a/b.png\n"
        f"  synced_refs:\n"
        f"    (not synced to any tracker yet)\n"
    )
    assert out == expected  # no `repo:` line when repo is unset
