from pathlib import Path

import pytest

from bugcap import drafts, live_session, recorder
from bugcap.errors import ServiceError
from bugcap.live_session import LiveSession, LiveState
from bugcap.paths import images_dir, media_dir
from bugcap.store import Store
from fixtures.make_images import png_bytes


class Cfg:
    key = "owner/proj"
    tag = "proj"


def _shot(name="shot.png"):
    """A screenshot as the capture backend leaves it: inside the store."""
    p = images_dir() / name
    p.write_bytes(png_bytes())
    return p


def _video(name="rec.mp4"):
    p = media_dir() / name
    p.write_bytes(b"not really a video")
    return p


def _recording(kind="video"):
    return recorder.RecordResult(_video(), 18, "stopped by user", 4.0, kind, "video/mp4")


def _stage_image(session, name="shot.png"):
    assert session.start()
    session.capture_done(_shot(name))


def _stage_video(session):
    assert session.start("video")
    assert session.state is LiveState.RECORDING
    session.recording_done(_recording())


@pytest.fixture
def session(bugcap_home):
    return LiveSession(Cfg())


# --- capturing ------------------------------------------------------------------

def test_start_moves_to_capturing_and_ignores_repeats(session):
    assert session.start() is True and session.state is LiveState.CAPTURING
    assert session.start() is False and session.start("video") is False


def test_capture_stages_and_returns_to_ready(session):
    _stage_image(session)
    assert session.state is LiveState.READY and len(session.staged) == 1
    assert session.start() is True  # more captures can follow


def test_empty_capture_returns_to_ready_with_message(session):
    session.start()
    session.capture_done(None)
    assert session.state is LiveState.READY and session.message and session.staged == []
    session.start()
    session.capture_done("/does/not/exist.png", "capture was cancelled")
    assert session.state is LiveState.READY and session.message == "capture was cancelled"


def test_recording_stages_a_video_and_failure_does_not(session):
    _stage_video(session)
    assert [s.kind for s in session.staged] == ["video"]
    session.start("video")
    session.recording_done(None, "ffmpeg missing")
    assert session.state is LiveState.READY and session.message == "ffmpeg missing" and len(session.staged) == 1


def test_double_start_blocked_while_recording(session):
    session.start("video")
    assert session.start() is False and session.start("video") is False


# --- new report from staged media ----------------------------------------------

def test_save_combines_images_and_a_video_in_order(session):
    first = _shot("a.png")
    session.start(); session.capture_done(first)
    _stage_video(session)
    _stage_image(session, "b.png")
    assert session.begin_details()
    report = session.save({"title": " Login broken ", "notes": "see @i1, @v2 and @i3", "tags": ["auth"],
                           "status": "in-progress"})
    assert session.state is LiveState.READY and session.saved_count == 1 and session.staged == []
    assert report.title == "Login broken" and report.repo == "owner/proj"
    assert report.tags == ["auth", "proj"] and report.status == "in-progress"
    assert [(m.idx, m.kind) for m in report.media] == [(1, "image"), (2, "video"), (3, "image")]
    assert first.exists()  # captured files live on in the store, not copied away


def test_two_reports_in_a_row(session):
    for n in (1, 2):
        _stage_image(session, f"s{n}.png")
        session.begin_details()
        session.save({"title": f"bug {n}"})
    with Store() as store:
        assert len(store.list()) == 2 and session.saved_count == 2


def test_note_only_bug_has_no_media(session):
    assert session.begin_details() is True
    report = session.save({"title": "Flaky on slow networks", "notes": "happens at night", "tags": ["perf"]})
    assert report.media == [] and report.notes == "happens at night" and report.tags == ["perf", "proj"]


def test_note_only_bug_without_tag_or_media(bugcap_home):
    s = LiveSession(None)
    s.begin_details()
    report = s.save({"title": "t"})
    assert report.tags == [] and report.media == [] and report.repo is None


def test_empty_title_rejected_and_state_and_media_kept(session):
    _stage_image(session)
    session.begin_details()
    with pytest.raises(ServiceError) as exc:
        session.save({"title": "  "})
    assert exc.value.code == "invalid_title" and session.state is LiveState.DETAILS
    assert len(session.staged) == 1 and session.saved_count == 0


def test_unknown_reference_keeps_details_open_and_creates_nothing(session):
    _stage_image(session)
    session.begin_details()
    with pytest.raises(ServiceError) as exc:
        session.save({"title": "t", "notes": "@v1"})
    assert exc.value.code == "invalid_reference" and session.state is LiveState.DETAILS
    with Store() as store:
        assert store.list() == []


def test_note_only_rejects_media_references(session):
    session.begin_details()
    with pytest.raises(ServiceError) as exc:
        session.save({"title": "t", "notes": "@i1"})
    assert exc.value.code == "invalid_reference"


def test_back_keeps_staged_media(session):
    _stage_image(session)
    session.begin_details()
    session.cancel_details()
    assert session.state is LiveState.READY and len(session.staged) == 1


def test_discard_needs_confirmation_and_removes_files(session):
    shot = _shot()
    session.start(); session.capture_done(shot)
    session.begin_details()
    assert session.discard(False) is False and session.state is LiveState.DETAILS and shot.exists()
    assert session.discard(True) is True and session.state is LiveState.READY and not shot.exists()
    assert session.staged == []


def test_remove_and_clear_staged(session):
    a, b = _shot("a.png"), _shot("b.png")
    session.start(); session.capture_done(a)
    session.start(); session.capture_done(b)
    session.remove_staged(0)
    assert not a.exists() and b.exists() and len(session.staged) == 1
    session.clear_staged()
    assert not b.exists() and session.staged == []


# --- adding to an existing report ----------------------------------------------

def _existing(session):
    session.begin_details()
    return session.save({"title": "existing", "notes": "first"})


def test_attach_staged_media_to_existing_report_with_note(session):
    report = _existing(session)
    _stage_image(session, "x.png")
    _stage_video(session)
    updated = session.attach(report.id, "now with sound @v2")
    assert [(m.idx, m.kind) for m in updated.media] == [(1, "image"), (2, "video")]
    assert updated.notes.startswith("first\n\n[") and "now with sound @v2" in updated.notes
    assert session.staged == [] and session.state is LiveState.READY


def test_attach_note_only_to_existing_report(session):
    report = _existing(session)
    updated = session.attach(report.id, "still happening")
    assert updated.media == [] and "still happening" in updated.notes


def test_attach_needs_something_and_a_real_report(session):
    report = _existing(session)
    with pytest.raises(ServiceError) as exc:
        session.attach(report.id, "  ")
    assert exc.value.code == "invalid_note"
    _stage_image(session)
    with pytest.raises(ServiceError) as exc:
        session.attach(999, "")
    assert exc.value.code == "not_found" and len(session.staged) == 1


def test_attach_bad_reference_changes_nothing(session):
    report = _existing(session)
    _stage_image(session)
    with pytest.raises(ServiceError) as exc:
        session.attach(report.id, "see @i9")
    assert exc.value.code == "invalid_reference"
    with Store() as store:
        assert store.get(report.id).media == []
    assert len(session.staged) == 1


# --- closing and drafts ---------------------------------------------------------

def test_close_flow(session):
    assert session.request_close(False) == "close"
    _stage_image(session)
    assert session.request_close(False) == "needs_confirm"  # staged media would be lost
    assert session.confirm_close(False) == "stay"
    assert session.confirm_close(True) == "save_draft"


def test_close_details_only_asks_when_something_would_be_lost(session):
    session.begin_details()
    assert session.request_close(False) == "close"
    assert session.request_close(True) == "needs_confirm"


def test_keep_as_draft_then_restore_and_save(session):
    shot = _shot()
    session.start(); session.capture_done(shot)
    _stage_video(session)
    session.begin_details()
    assert session.keep_as_draft({"title": "half", "notes": "", "tags": [], "status": "open"}) is True
    assert session.staged == [] and session.state is LiveState.READY
    (draft,) = drafts.list_drafts("owner/proj")
    assert [i["kind"] for i in draft.items] == ["image", "video"]

    session.restore(draft)
    assert session.state is LiveState.DETAILS and len(session.staged) == 2
    report = session.save({"title": "finished", "notes": "@i1 @v2"})
    assert drafts.list_drafts("owner/proj") == []
    assert list(drafts.drafts_dir().iterdir()) == []
    assert [m.kind for m in report.media] == ["image", "video"]
    assert all(Path(m.abs_path).is_file() for m in report.media)  # not lost with the draft


def test_note_only_draft_round_trip(session):
    session.begin_details()
    assert session.keep_as_draft({"title": "later", "notes": "n"}) is True
    (draft,) = drafts.list_drafts("owner/proj")
    assert draft.items == []
    session.restore(draft)
    assert session.save({"title": "later"}).media == []


def test_empty_keep_as_draft_makes_nothing(session):
    session.begin_details()
    assert session.keep_as_draft({"title": "", "notes": ""}) is False
    assert drafts.list_drafts("owner/proj") == [] and session.state is LiveState.READY


def test_describe():
    S = live_session.Staged
    staged = [S("image", None), S("image", None), S("video", None)]
    assert live_session.describe(staged) == "2 images, 1 video"
    assert live_session.describe([]) == ""


def test_initial_tags_prefill_repo_tag_but_keep_draft_tags():
    assert live_session.initial_tags(Cfg()) == ["proj"]
    assert live_session.initial_tags(None) == []
    assert live_session.initial_tags(Cfg(), {"tags": ["a"]}) == ["a"]
    assert live_session.initial_tags(Cfg(), {"tags": []}) == []


def test_save_does_not_duplicate_the_prefilled_repo_tag(session):
    session.begin_details()
    report = session.save({"title": "t", "tags": ["proj", "x"]})
    assert report.tags == ["proj", "x"]
