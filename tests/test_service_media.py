import pytest

from bugcap import service
from bugcap.errors import ServiceError
from bugcap.store import Store


@pytest.fixture
def store(bugcap_home):
    with Store() as s:
        yield s


def _rid(store):
    return store.add("bug").id


def test_indexes_are_one_based_and_sequential(store, sample_images):
    rid = _rid(store)
    res = service.add_media(store, rid, [str(sample_images / "sample.png"), str(sample_images / "sample.gif")])
    assert [m.idx for m in res.added] == [1, 2]
    res = service.add_media(store, rid, [str(sample_images / "sample.jpg")])
    assert res.added[0].idx == 3


def test_original_file_is_copied_not_referenced(store, sample_images):
    rid = _rid(store)
    src = sample_images / "sample.png"
    m = service.add_media(store, rid, [str(src)]).added[0]
    assert m.path.startswith("images/") and str(src) not in m.path
    assert m.source == str(src)
    src.unlink()
    assert m.abs_path and __import__("os").path.isfile(m.abs_path)


def test_duplicate_label_case_insensitive_names_existing_index(store, sample_images):
    rid = _rid(store)
    service.add_media(store, rid, [str(sample_images / "sample.png")], ["login-error"])
    with pytest.raises(ServiceError) as exc:
        service.add_media(store, rid, [str(sample_images / "sample.gif")], ["Login-Error"])
    assert exc.value.code == "duplicate_label" and "#1" in exc.value.message
    assert len(store.get(rid).media) == 1  # nothing added, no stray file copied


def test_duplicate_label_within_one_batch(store, sample_images):
    rid = _rid(store)
    with pytest.raises(ServiceError) as exc:
        service.add_media(store, rid, [str(sample_images / "sample.png"), str(sample_images / "sample.gif")], ["a", "A"])
    assert exc.value.code == "duplicate_label"


@pytest.mark.parametrize("label", ["12", "has space", "-x", "_x", "9lives"])
def test_invalid_labels(store, sample_images, label):
    rid = _rid(store)
    with pytest.raises(ServiceError) as exc:
        service.add_media(store, rid, [str(sample_images / "sample.png")], [label])
    assert exc.value.code == "invalid_label"


def test_partial_batch_returns_added_and_rejected(store, sample_images):
    rid = _rid(store)
    res = service.add_media(store, rid, [str(sample_images / "sample.png"), str(sample_images / "not-image.txt")])
    assert len(res.added) == 1 and len(res.rejected) == 1
    assert res.rejected[0]["code"] == "invalid_image"


def test_unknown_report(store, sample_images):
    with pytest.raises(ServiceError) as exc:
        service.add_media(store, 99, [str(sample_images / "sample.png")])
    assert exc.value.code == "not_found"


def test_create_report_with_images_and_notes(store, sample_images):
    report, res = service.create_report(
        store, "t", notes="see @shot", sources=[str(sample_images / "sample.png")], labels=["shot"]
    )
    assert report.notes == "see @shot" and report.media[0].label == "shot"


def test_create_report_invalid_note_leaves_nothing(store, sample_images, bugcap_home):
    with pytest.raises(ServiceError) as exc:
        service.create_report(store, "t", notes="see @9", sources=[str(sample_images / "sample.png")])
    assert exc.value.code == "invalid_reference"
    assert store.list() == []
    assert not list((bugcap_home / "data" / "images").glob("*"))


def test_create_report_require_media_with_all_rejected(store, sample_images):
    report, res = service.create_report(
        store, "t", sources=[str(sample_images / "not-image.txt")], require_media=True
    )
    assert report is None and len(res.rejected) == 1 and store.list() == []


def test_set_status_and_tags(store):
    rid = _rid(store)
    assert service.set_status(store, rid, "resolved").status == "resolved"
    with pytest.raises(ServiceError) as exc:
        service.set_status(store, rid, "nope")
    assert exc.value.code == "invalid_status"
    assert service.set_tags(store, rid, add=["a", "b"], remove=["b"]) == ["a"]
