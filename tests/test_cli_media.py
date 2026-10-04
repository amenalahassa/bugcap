import pytest

from bugcap import capture, cli
from bugcap.store import Store
from fixtures.make_v1_db import build


def _boom(*a, **k):
    raise AssertionError("capture tool must not run")


def test_capture_image_creates_report_without_capture_tool(bugcap_home, sample_images, monkeypatch, capsys):
    monkeypatch.setattr(capture, "capture_screenshot", _boom)
    rc = cli.main(["capture", "--image", str(sample_images / "sample.png"), "--title", "T", "--note", ""])
    out = capsys.readouterr().out
    assert rc == 0 and out.startswith("Saved report #1: T")
    assert "added #1" in out and "(image," in out
    with Store() as store:
        assert [m.idx for m in store.get(1).media] == [1]


def test_capture_multiple_images_with_labels(bugcap_home, sample_images, capsys):
    rc = cli.main([
        "capture", "--title", "T", "--note", "see @after",
        "--image", str(sample_images / "sample.png"), "--label", "before",
        "--image", str(sample_images / "sample.gif"), "--label", "after",
    ])
    assert rc == 0
    with Store() as store:
        r = store.get(1)
        assert [(m.idx, m.label) for m in r.media] == [(1, "before"), (2, "after")]


def test_capture_unknown_reference_leaves_no_report(bugcap_home, sample_images, capsys):
    rc = cli.main(["capture", "--image", str(sample_images / "sample.png"), "--title", "T", "--note", "see @5"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error: unknown reference @5 in notes" in err and "valid references: @1" in err
    with Store() as store:
        assert store.list() == []


def test_capture_all_images_rejected_creates_nothing(bugcap_home, sample_images, capsys):
    rc = cli.main(["capture", "--image", str(sample_images / "not-image.txt"), "--title", "T", "--note", ""])
    assert rc == 1 and "skipped" in capsys.readouterr().err
    with Store() as store:
        assert store.list() == []


def test_attach_mixed_inputs_partial_exit_1(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    rc = cli.main([
        "attach", str(rid), "--image", str(sample_images / "sample.png"),
        "--image", str(sample_images / "not-image.txt"), "--image", str(sample_images / "*.gif"),
    ])
    cap = capsys.readouterr()
    assert rc == 1
    assert "added #1" in cap.out and "added #2" in cap.out
    assert "skipped" in cap.err and "not-image.txt" in cap.err
    with Store() as store:
        assert len(store.get(rid).media) == 2


def test_attach_duplicate_label_error(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--label", "a"])
    rc = cli.main(["attach", str(rid), "--image", str(sample_images / "sample.gif"), "--label", "a"])
    assert rc == 1 and "duplicate label 'a' (already #1)" in capsys.readouterr().err


def test_attach_warns_when_notes_reference_missing_label(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug", notes="see @ghost").id
    rc = cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png")])
    assert rc == 0 and "warning: unknown reference @ghost" in capsys.readouterr().err


def test_images_lists_index_label_kind_size(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--label", "shot"])
    capsys.readouterr()
    assert cli.main(["images", str(rid)]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("#1") and "shot" in line and "image" in line and "images/" in line


def test_images_unknown_report(bugcap_home, capsys):
    assert cli.main(["images", "9"]) == 1
    assert "no report with id 9" in capsys.readouterr().err


def test_legacy_report_lists_its_images(bugcap_home, tmp_path, monkeypatch, capsys):
    import shutil

    from bugcap.paths import db_path

    build(tmp_path / "v1.db")
    shutil.copy(tmp_path / "v1.db", db_path())
    assert cli.main(["images", "1"]) == 0
    out = capsys.readouterr().out
    assert "/data/images/a.png" in out and "/data/images/b.png" in out


def test_edit_note_unknown_reference(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--label", "login-error"])
    capsys.readouterr()
    assert cli.main(["edit", str(rid), "--note", "see @3"]) == 1
    err = capsys.readouterr().err
    assert err == "error: unknown reference @3 in notes\nvalid references: @1, @login-error\n"
    assert cli.main(["edit", str(rid), "--note", "see @1 and @login-error"]) == 0


def test_images_remove_and_relabel_flow(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--label", "a",
              "--image", str(sample_images / "sample.gif")])
    cli.main(["edit", str(rid), "--note", "@a and @2"])
    capsys.readouterr()

    assert cli.main(["images", str(rid), "remove", "1"]) == 1
    err = capsys.readouterr().err
    assert "--force" in err and "@a" in err

    assert cli.main(["images", str(rid), "remove", "1", "--force"]) == 0
    assert "rewrote 1 reference(s)" in capsys.readouterr().out
    with Store() as store:
        assert store.get(rid).notes == "[image removed] and @2"


def test_show_resolves_references(bugcap_home, sample_images, capsys):
    with Store() as store:
        rid = store.add("bug").id
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--label", "a"])
    cli.main(["edit", str(rid), "--note", "see @1, @@1"])
    capsys.readouterr()
    cli.main(["show", str(rid)])
    out = capsys.readouterr().out
    assert "see @1 (images/" in out and ", @1\n" in out
    assert "  media:" in out and "#1  image" in out
