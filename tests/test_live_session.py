import pytest

from bugcap import drafts, live_session
from bugcap.errors import ServiceError
from bugcap.live_session import LiveSession, LiveState
from bugcap.store import Store
from fixtures.make_images import png_bytes


class Cfg:
    key = "owner/proj"
    tag = "proj"


def _shot(tmp_path, name="shot.png"):
    p = tmp_path / name
    p.write_bytes(png_bytes())
    return p


@pytest.fixture
def session(bugcap_home):
    return LiveSession(Cfg())


def test_start_moves_to_capturing_and_ignores_repeats(session):
    assert session.start() is True and session.state is LiveState.CAPTURING
    assert session.start() is False and session.state is LiveState.CAPTURING


def test_repeat_start_ignored_in_details(session, tmp_path):
    session.start()
    session.capture_done(_shot(tmp_path))
    assert session.state is LiveState.DETAILS
    assert session.start() is False and session.state is LiveState.DETAILS


def test_empty_capture_returns_to_ready_with_message(session):
    session.start()
    session.capture_done(None)
    assert session.state is LiveState.READY and session.message
    session.start()
    session.capture_done("/does/not/exist.png", "capture was cancelled")
    assert session.state is LiveState.READY and session.message == "capture was cancelled"


def test_save_creates_report_with_screenshot_and_repo(session, tmp_path):
    shot = _shot(tmp_path)
    session.start()
    session.capture_done(shot)
    report = session.save({"title": " Login broken ", "notes": "see @1", "tags": ["auth"], "status": "in-progress"})
    assert session.state is LiveState.READY and session.saved_count == 1
    assert report.title == "Login broken" and report.repo == "owner/proj"
    assert report.tags == ["auth", "proj"] and report.status == "in-progress"
    assert report.notes == "see @1" and len(report.media) == 1
    assert not shot.exists()  # the capture temp file is gone once copied into the store


def test_two_saves_in_a_row(session, tmp_path):
    for n in (1, 2):
        session.start()
        session.capture_done(_shot(tmp_path, f"s{n}.png"))
        session.save({"title": f"bug {n}"})
    assert session.saved_count == 2
    with Store() as store:
        assert len(store.list()) == 2


def test_empty_title_rejected_and_state_kept(session, tmp_path):
    session.start()
    session.capture_done(_shot(tmp_path))
    with pytest.raises(ServiceError) as exc:
        session.save({"title": "  "})
    assert exc.value.code == "invalid_title" and session.state is LiveState.DETAILS
    assert session.saved_count == 0


def test_unknown_reference_keeps_details_open(session, tmp_path):
    session.start()
    session.capture_done(_shot(tmp_path))
    with pytest.raises(ServiceError) as exc:
        session.save({"title": "t", "notes": "@4"})
    assert exc.value.code == "invalid_reference" and session.state is LiveState.DETAILS
    with Store() as store:
        assert store.list() == []


def test_discard_needs_confirmation(session, tmp_path):
    shot = _shot(tmp_path)
    session.start()
    session.capture_done(shot)
    assert session.discard(False) is False and session.state is LiveState.DETAILS and shot.exists()
    assert session.discard(True) is True and session.state is LiveState.READY and not shot.exists()


def test_close_flow(session, tmp_path):
    assert session.request_close(False) == "close"
    session.start()
    session.capture_done(_shot(tmp_path))
    assert session.request_close(True) == "needs_confirm"
    assert session.confirm_close(False) == "stay"
    assert session.confirm_close(True) == "save_draft"


def test_restored_draft_is_deleted_once_saved(session, bugcap_home, tmp_path):
    draft = drafts.save_draft("owner/proj", _shot(tmp_path), {"title": "half", "notes": "", "tags": [], "status": "open"})
    session.restore(draft.png_path, draft.id)
    assert session.state is LiveState.DETAILS
    session.save({"title": "finished"})
    assert drafts.list_drafts("owner/proj") == []
    assert not draft.png_path.exists()


def test_initial_tags_prefill_repo_tag_but_keep_draft_tags():
    assert live_session.initial_tags(Cfg()) == ["proj"]
    assert live_session.initial_tags(None) == []
    assert live_session.initial_tags(Cfg(), {"tags": ["a"]}) == ["a"]
    assert live_session.initial_tags(Cfg(), {"tags": []}) == []


def test_save_does_not_duplicate_the_prefilled_repo_tag(session, tmp_path):
    session.start()
    session.capture_done(_shot(tmp_path))
    report = session.save({"title": "t", "tags": ["proj", "x"]})
    assert report.tags == ["proj", "x"]
