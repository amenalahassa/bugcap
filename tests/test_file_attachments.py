"""Attaching files of any type: service, CLI, references, live window session, dashboard."""
import pytest
from fixtures.make_images import png_bytes

from bugcap import cli, refs, service
from bugcap.errors import ServiceError
from bugcap.live_session import LiveSession, LiveState
from bugcap.paths import files_dir, images_dir
from bugcap.store import Store

PDF = b"%PDF-1.4 not really a pdf"


class Cfg:
    key = "owner/proj"
    tag = "proj"


@pytest.fixture
def report_id(bugcap_home):
    with Store() as store:
        return store.add("Bug").id


def _file(tmp_path, name="spec.pdf", data=PDF):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- service ----------------------------------------------------------------------

def test_add_files_accepts_any_type_and_keeps_extension(bugcap_home, report_id, tmp_path):
    odd = _file(tmp_path, "data.bin", b"\x00\x01")
    with Store() as store:
        result = service.add_files(store, report_id, [str(_file(tmp_path)), str(odd)], ["spec", None])
        media = store.list_media(report_id)
    assert result.rejected == []
    assert [(m.kind, m.idx, m.label, m.mime) for m in media] == [
        ("file", 1, "spec", "application/pdf"), ("file", 2, None, "application/octet-stream"),
    ]
    assert media[0].path.startswith("files/") and media[0].path.endswith(".pdf")
    assert media[0].source.endswith("spec.pdf")
    assert (files_dir() / media[0].path.split("/")[1]).read_bytes() == PDF


def test_identical_files_are_stored_once(bugcap_home, report_id, tmp_path):
    with Store() as store:
        service.add_files(store, report_id, [str(_file(tmp_path)), str(_file(tmp_path, "copy.pdf"))])
        a, b = store.list_media(report_id)
    assert a.path == b.path and len(list(files_dir().iterdir())) == 1


def test_removing_one_of_two_sharing_a_file_keeps_the_file(bugcap_home, report_id, tmp_path):
    with Store() as store:
        service.add_files(store, report_id, [str(_file(tmp_path)), str(_file(tmp_path, "copy.pdf"))])
        service.remove_media(store, report_id, "d1")
        assert len(list(files_dir().iterdir())) == 1
        service.remove_media(store, report_id, "d2")
    assert list(files_dir().iterdir()) == []


def test_add_files_rejects_directories_and_missing_per_item(bugcap_home, report_id, tmp_path):
    with Store() as store:
        result = service.add_files(store, report_id, [str(tmp_path), str(tmp_path / "nope.pdf"), str(_file(tmp_path))])
    assert [r["code"] for r in result.rejected] == ["invalid_file", "not_found"]
    assert len(result.added) == 1


def test_label_may_not_look_like_a_file_number(bugcap_home, report_id, tmp_path):
    with Store() as store, pytest.raises(ServiceError) as exc:
        service.add_files(store, report_id, [str(_file(tmp_path))], ["d1"])
    assert exc.value.code == "invalid_label"


# --- references -------------------------------------------------------------------

def test_notes_reference_files_by_number_and_label(bugcap_home, report_id, tmp_path):
    with Store() as store:
        service.add_files(store, report_id, [str(_file(tmp_path))], ["spec"])
        service.set_notes(store, report_id, "see @d1 and @spec")
        with pytest.raises(ServiceError):
            service.set_notes(store, report_id, "see @d2")
        with pytest.raises(ServiceError):
            service.set_notes(store, report_id, "wrong kind @i1")
        view = service.get_report_view(store, report_id)
    assert [r["token"] for r in view.references] == ["@d1", "@spec"]
    assert refs.media_token(view.media[0]) == "@d1"


# --- CLI --------------------------------------------------------------------------

def test_cli_attach_file_with_note(bugcap_home, report_id, tmp_path, capsys):
    f = _file(tmp_path)
    assert cli.main(["attach", str(report_id), "--file", str(f), "--file-label", "spec", "--note", "see @d1"]) == 0
    out = capsys.readouterr().out
    assert "added @d1 spec.pdf (file," in out
    with Store() as store:
        report = store.get(report_id)
    assert report.media[0].kind == "file" and report.media[0].label == "spec"
    assert "@d1: see @d1" in report.notes


def test_cli_attach_image_and_file_together(bugcap_home, report_id, tmp_path):
    img = tmp_path / "s.png"
    img.write_bytes(png_bytes())
    assert cli.main(["attach", str(report_id), "--image", str(img), "--file", str(_file(tmp_path))]) == 0
    with Store() as store:
        assert [(m.kind, m.idx) for m in store.get(report_id).media] == [("image", 1), ("file", 2)]


def test_cli_attach_file_failure_exits_1(bugcap_home, report_id, tmp_path, capsys):
    assert cli.main(["attach", str(report_id), "--file", str(tmp_path / "missing.pdf")]) == 1
    assert "skipped" in capsys.readouterr().err


# --- live window session ----------------------------------------------------------

def test_live_upload_image_and_file_then_save_with_references(bugcap_home, tmp_path):
    session = LiveSession(Cfg())
    img = tmp_path / "shot.png"
    img.write_bytes(png_bytes())
    assert session.upload_images([str(img)]) == []
    assert session.upload_files([str(_file(tmp_path)), str(_file(tmp_path, "log.txt", b"hi"))]) == []
    assert [s.kind for s in session.staged] == ["image", "file", "file"]
    assert session.begin_details()
    report = session.save({"title": "From uploads", "notes": "@i1 broke while reading @d2"})
    assert [(m.kind, m.idx) for m in report.media] == [("image", 1), ("file", 2), ("file", 3)]
    assert report.media[1].mime == "application/pdf"
    assert session.state is LiveState.READY and session.staged == []


def test_live_upload_refuses_non_images_but_keeps_the_good_ones(bugcap_home, tmp_path):
    session = LiveSession(Cfg())
    good = tmp_path / "ok.png"
    good.write_bytes(png_bytes())
    errors = session.upload_images([str(_file(tmp_path, "notes.txt", b"text")), str(good)])
    assert len(errors) == 1 and errors[0].startswith("notes.txt")
    assert [s.kind for s in session.staged] == ["image"]


def test_live_upload_ignored_while_busy(bugcap_home, tmp_path):
    session = LiveSession(Cfg())
    assert session.start()
    assert session.upload_files([str(_file(tmp_path))]) != [] and session.staged == []


def test_live_upload_to_existing_report(bugcap_home, report_id, tmp_path):
    session = LiveSession(Cfg())
    session.upload_files([str(_file(tmp_path))])
    report = session.attach(report_id, "attached @d1")
    assert report.media[0].kind == "file" and "@d1" in report.notes


def test_discarding_an_upload_never_deletes_a_file_another_report_uses(bugcap_home, report_id, tmp_path):
    f = _file(tmp_path)
    with Store() as store:
        service.add_files(store, report_id, [str(f)])
    session = LiveSession(Cfg())
    session.upload_files([str(f)])
    assert session.begin_details()
    assert session.discard(True)
    with Store() as store:
        stored = store.get(report_id).media[0]
    assert (files_dir() / stored.path.split("/")[1]).read_bytes() == PDF


def test_uploaded_image_goes_to_images_dir(bugcap_home, tmp_path):
    session = LiveSession(Cfg())
    img = tmp_path / "shot.png"
    img.write_bytes(png_bytes())
    session.upload_images([str(img)])
    assert session.staged[0].path.parent == images_dir()


# --- dashboard --------------------------------------------------------------------

def test_dashboard_serves_files_as_opaque_downloads(dashboard, bugcap_home, report_id, tmp_path):
    html = _file(tmp_path, "evil name.html", b"<script>alert(1)</script>")
    with Store() as store:
        service.add_files(store, report_id, [str(html)])
        media_id = store.list_media(report_id)[0].id
    status, headers, body = dashboard.call("GET", f"/media/{media_id}")
    assert status == 200 and body == b"<script>alert(1)</script>"
    assert headers["content-type"] == "application/octet-stream"
    assert headers["content-disposition"] == 'attachment; filename="evil_name.html"'
    status, _, _ = dashboard.call("GET", f"/api/reports/{report_id}")
    assert status == 200


# --- agent API and tracker sync ---------------------------------------------------

def test_agent_api_attach_file(bugcap_home, report_id, tmp_path):
    from bugcap import agent_api

    with Store() as store:
        out = agent_api.attach_file(store, report_id, [str(_file(tmp_path)), str(tmp_path / "gone.pdf")], ["spec", None])
        assert agent_api.attach_file(store, report_id, [])["code"] == "bad_query"
    assert [(a["index"], a["label"], a["kind"]) for a in out["added"]] == [(1, "spec", "file")]
    assert [r["source"] for r in out["rejected"]] == [str(tmp_path / "gone.pdf")]


def test_sync_never_uploads_attached_files(bugcap_home, report_id, tmp_path):
    from types import SimpleNamespace

    from bugcap import sync

    with Store() as store:
        service.add_files(store, report_id, [str(_file(tmp_path))])
        service.set_notes(store, report_id, "see @d1")
        report = store.get(report_id)
        opts = SimpleNamespace(images=SimpleNamespace(repo="o/r", path="p"), max_upload_mb=25)
        result = sync.SyncResult()
        links = sync._commit_media(store, report, None, opts, result)
    assert [link.urls for link in links] == [[]]
    body = sync._issue_body(report, links)
    assert "kept local" in body and "files/" not in body
