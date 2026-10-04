import os

import pytest

from bugcap import service
from bugcap.errors import ServiceError
from bugcap.store import Store


@pytest.fixture
def store(bugcap_home):
    with Store() as s:
        yield s


@pytest.fixture
def report(store, sample_images):
    """Report with 3 images: #1 unlabelled, #2 'login-error', #3 unlabelled."""
    rid = store.add("bug").id
    service.add_media(store, rid, [str(sample_images / "sample.png")])
    service.add_media(store, rid, [str(sample_images / "sample.gif")], ["login-error"])
    service.add_media(store, rid, [str(sample_images / "sample.jpg")])
    return rid


def test_set_notes_with_unknown_reference_keeps_old_notes(store, report):
    service.set_notes(store, report, "see @1")
    with pytest.raises(ServiceError) as exc:
        service.set_notes(store, report, "see @9")
    assert exc.value.code == "invalid_reference"
    assert store.get(report).notes == "see @1"


def test_relabel_unreferenced_needs_no_force(store, report):
    assert service.relabel_media(store, report, "login-error", "sign-in") == 0
    assert store.get(report).media[1].label == "sign-in"


def test_relabel_referenced_refused_then_forced(store, report):
    service.set_notes(store, report, "a @login-error b @2")
    with pytest.raises(ServiceError) as exc:
        service.relabel_media(store, report, "login-error", "sign-in")
    assert exc.value.code == "referenced_image" and exc.value.details["tokens"] == ["@login-error"]
    assert store.get(report).media[1].label == "login-error"

    assert service.relabel_media(store, report, "2", "sign-in", force=True) == 1
    got = store.get(report)
    assert got.notes == "a @sign-in b @2" and got.media[1].label == "sign-in"


def test_relabel_to_taken_or_invalid_label(store, report):
    with pytest.raises(ServiceError) as exc:
        service.relabel_media(store, report, "1", "LOGIN-ERROR")
    assert exc.value.code == "duplicate_label"
    with pytest.raises(ServiceError) as exc:
        service.relabel_media(store, report, "1", "42")
    assert exc.value.code == "invalid_label"


def test_remove_referenced_refused_then_forced_keeps_other_indexes(store, report):
    service.set_notes(store, report, "x @2 y @3 z @login-error")
    with pytest.raises(ServiceError) as exc:
        service.remove_media(store, report, "2")
    assert exc.value.code == "referenced_image"
    assert len(store.get(report).media) == 3

    rewritten = service.remove_media(store, report, "login-error", force=True)
    got = store.get(report)
    assert got.notes == "x [image removed] y @3 z [image removed]"
    assert rewritten == 2
    assert [m.idx for m in got.media] == [1, 3]  # @3 still points at the same image


def test_remove_unreferenced_deletes_file_and_keeps_indexes(store, report):
    path = store.get(report).media[0].abs_path
    assert os.path.isfile(path)
    assert service.remove_media(store, report, "1") == 0
    assert not os.path.exists(path)
    assert [m.idx for m in store.get(report).media] == [2, 3]
    assert store.get(report).media[0].label == "login-error"


def test_removing_last_image_keeps_report(store, report):
    for idx in (1, 2, 3):
        service.remove_media(store, report, str(idx))
    got = store.get(report)
    assert got is not None and got.media == []


def test_forced_change_is_one_transaction(store, report, monkeypatch):
    service.set_notes(store, report, "@login-error")
    original = store.update

    def failing(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "update", failing)
    with pytest.raises(RuntimeError):
        service.relabel_media(store, report, "2", "sign-in", force=True)
    monkeypatch.setattr(store, "update", original)
    got = store.get(report)
    assert got.media[1].label == "login-error" and got.notes == "@login-error"


def test_unknown_image_ref(store, report):
    with pytest.raises(ServiceError) as exc:
        service.remove_media(store, report, "9")
    assert exc.value.code == "not_found"


def test_report_segments(store, report):
    service.set_notes(store, report, "See @1 and @@1, `@2`")
    view = service.get_report_view(store, report)
    assert view.segments[0] == {"text": "See "}
    assert view.segments[1]["ref"]["index"] == 1
    assert view.segments[2] == {"text": " and @1, `@2`"}
    assert [r["token"] for r in view.references] == ["@1"]


def test_index_not_reused_after_removing_the_last_image(store, report, sample_images):
    service.remove_media(store, report, "3")
    added = service.add_media(store, report, [str(sample_images / "sample.png")]).added[0]
    assert added.idx == 4
