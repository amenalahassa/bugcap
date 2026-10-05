"""`capture --no-image` saves a text-only report; `delete` removes a report and its files."""

from fixtures.make_images import png_bytes

from bugcap import cli, service
from bugcap.paths import resolve_data_path
from bugcap.store import Store


def test_capture_no_image_skips_capture_tool(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def boom():
        raise AssertionError("no capture tool should run with --no-image")

    monkeypatch.setattr(cli.capture, "capture_screenshot", boom)
    assert cli.main(["capture", "--no-image", "--title", "Simple bug", "--note", "it breaks"]) == 0
    assert capsys.readouterr().out.startswith("Saved report #1: Simple bug")
    with Store() as store:
        r = store.get(1)
        assert r.media == [] and r.notes == "it breaks"


def test_capture_no_image_rejects_image_and_label(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    img = tmp_path / "s.png"
    img.write_bytes(png_bytes())
    assert cli.main(["capture", "--no-image", "--image", str(img), "--title", "T"]) == 2
    assert cli.main(["capture", "--no-image", "--label", "x", "--title", "T"]) == 2
    assert "cannot be combined" in capsys.readouterr().err
    with Store() as store:
        assert store.list() == []


def test_delete_with_yes_removes_report_and_files(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    img = tmp_path / "s.png"
    img.write_bytes(png_bytes())
    assert cli.main(["capture", "--image", str(img), "--title", "Gone", "--note", ""]) == 0
    capsys.readouterr()
    with Store() as store:
        report = store.get(1)
        file_path = resolve_data_path(report.media[0].path)
    assert file_path.exists()

    assert cli.main(["delete", "1", "--yes"]) == 0
    assert "Deleted report #1: Gone" in capsys.readouterr().out
    assert not file_path.exists()
    with Store() as store:
        assert store.get(1) is None
        assert store.list() == []


def test_delete_without_yes_refuses_when_not_interactive(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with Store() as store:
        store.add(title="Keep me")
    monkeypatch.setattr("sys.stdin", type("NoTTY", (), {"isatty": lambda self: False})())
    assert cli.main(["delete", "1"]) == 2
    assert "re-run with --yes" in capsys.readouterr().err
    with Store() as store:
        assert store.get(1) is not None


def test_delete_missing_report(bugcap_home, capsys):
    assert cli.main(["delete", "99", "--yes"]) == 1
    assert "no report with id 99" in capsys.readouterr().err


def test_delete_report_keeps_other_reports_and_numbering(bugcap_home):
    with Store() as store:
        a = store.add(title="A")
        b = store.add(title="B")
        service.delete_report(store, a.id)
        assert [r.id for r in store.list()] == [b.id]
        c = store.add(title="C")
        assert c.id == b.id + 1


def test_capture_warns_on_unknown_report_ref_but_saves(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["capture", "--no-image", "--title", "Dup", "--note", "duplicate of #99"]) == 0
    captured = capsys.readouterr()
    assert "warning: #99 in notes is not a report (kept as text)" in captured.err
    assert captured.out.startswith("Saved report #1: Dup")
    with Store() as store:
        assert store.get(1).notes == "duplicate of #99"


def test_capture_does_not_warn_for_existing_report_ref(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with Store() as store:
        store.add(title="First")
    assert cli.main(["capture", "--no-image", "--title", "Second", "--note", "dup of #1"]) == 0
    assert "warning" not in capsys.readouterr().err
