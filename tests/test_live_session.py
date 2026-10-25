from pathlib import Path

import pytest
from fixtures.make_images import png_bytes

from bugcap import drafts, live_session, recorder
from bugcap.errors import ServiceError
from bugcap.live_session import LiveSession, LiveState
from bugcap.paths import images_dir, media_dir
from bugcap.store import Store


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
    assert all(Path(m.abs_path).is_file() for m in report.media)  # captured files stay in the store


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
    session.remove_staged(1)
    assert not a.exists() and b.exists() and len(session.staged) == 1
    session.clear_staged()
    assert not b.exists() and session.staged == []


# --- stable staging numbers -----------------------------------------------------

def test_staged_items_get_stable_numbers_never_reused(session):
    _stage_image(session, "a.png")
    _stage_video(session)
    _stage_image(session, "c.png")
    assert [s.number for s in session.staged] == [1, 2, 3]
    session.remove_staged(2)
    _stage_image(session, "d.png")
    assert [s.number for s in session.staged] == [1, 3, 4]


def test_preview_media_uses_staging_numbers(session):
    _stage_image(session, "a.png")
    _stage_video(session)
    session.remove_staged(1)
    assert [(m.idx, m.kind) for m in session.preview_media()] == [(2, "video")]


def test_save_rewrites_staging_numbers_to_final_indexes(session):
    _stage_image(session, "a.png")
    _stage_image(session, "b.png")
    _stage_video(session)
    session.remove_staged(2)
    session.begin_details()
    report = session.save({"title": "t", "notes": "see @i1 and @v3"})
    assert [(m.idx, m.kind) for m in report.media] == [(1, "image"), (2, "video")]
    assert report.notes == "see @i1 and @v2"


# --- removing and opening staged items -------------------------------------------

def test_remove_works_in_details_but_not_while_capturing(session):
    a = _shot("a.png")
    session.start(); session.capture_done(a)
    session.begin_details()
    assert session.remove_staged(1) is True and not a.exists()
    assert session.state is LiveState.DETAILS and session.staged == []  # now a note-only bug
    _shot_b = _shot("b.png")
    session.cancel_details()
    session.start(); session.capture_done(_shot_b)
    session.start()  # a second capture is running
    assert session.remove_staged(2) is False and _shot_b.exists()


def test_remove_keeps_a_shared_upload_on_disk(session, tmp_path):
    src = tmp_path / "pic.png"
    src.write_bytes(png_bytes())
    assert session.upload_images([src]) == []
    stored = session.staged[0].path
    assert session.remove_staged(1) is True and stored.exists() and session.staged == []


def test_removed_tag_is_no_longer_valid_in_notes(session):
    _stage_image(session, "a.png")
    _stage_image(session, "b.png")
    session.remove_staged(2)
    from bugcap import refs

    with pytest.raises(ServiceError) as exc:
        refs.validate_references("see @i2", session.preview_media())
    assert exc.value.code == "invalid_reference" and exc.value.details["valid"] == ["@i1"]


def test_unknown_number_is_ignored(session):
    _stage_image(session)
    assert session.remove_staged(7) is False and len(session.staged) == 1


def test_item_path_is_the_file_or_the_frames_folder(session, tmp_path):
    shot = _shot("a.png")
    session.start(); session.capture_done(shot)
    folder = media_dir() / "x-frames"
    folder.mkdir()
    frame = folder / "frame-001.png"
    frame.write_bytes(png_bytes())
    session.start("video")
    session.recording_done(recorder.RecordResult(None, 1, "stopped by user", 1.0, "frames", "image/png",
                                                 [(str(frame), 1)]))
    assert session.item_path(1) == shot and session.item_path(2) == folder
    assert session.item_path(9) is None


def test_attach_note_uses_the_final_report_numbers(session):
    """In "Add to existing" a note can point at the report's own media too, so it keeps
    using the numbers the items will have in that report (no staging numbers there)."""
    _stage_image(session, "x.png")
    _stage_image(session, "y.png")
    session.begin_details()
    report = session.save({"title": "existing"})
    _stage_image(session, "z.png")
    _stage_video(session)
    session.remove_staged(session.staged[0].number)
    updated = session.attach(report.id, "compare @i1 with @v3")
    assert [(m.idx, m.kind) for m in updated.media] == [(1, "image"), (2, "image"), (3, "video")]
    assert "compare @i1 with @v3" in updated.notes


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


# --- remembered form and progress drafts -------------------------------------------

FIELDS = {"title": "Login broken", "notes": "after step 3", "tags": ["auth"], "status": "in-progress",
          "repo": "owner/proj"}


def _progress(session):
    return drafts.load_draft(session.draft_id) if session.draft_id else None


def test_back_remembers_the_form(session):
    session.begin_details()
    session.remember_form(FIELDS)
    session.cancel_details()
    assert session.state is LiveState.READY and session.form == FIELDS
    assert session.begin_details() and session.form == FIELDS


def test_autosave_writes_only_when_something_changed(session):
    session.begin_details()
    assert session.autosave(FIELDS) is True
    first = _progress(session)
    assert first.title == "Login broken" and first.repo == "owner/proj" and first.tags == ["auth"]
    assert session.autosave(FIELDS) is False
    assert session.autosave({**FIELDS, "notes": "after step 4"}) is True
    assert _progress(session).notes == "after step 4" and session.draft_id == first.id


def test_autosave_skips_an_empty_bug(session):
    assert session.autosave({"title": "", "notes": ""}) is False and session.draft_id is None


def test_staging_and_removal_update_the_progress_draft(session):
    _stage_image(session, "a.png")
    assert [i["number"] for i in _progress(session).items] == [1]
    _stage_video(session)
    session.remove_staged(1)
    assert [(i["number"], i["kind"]) for i in _progress(session).items] == [(2, "video")]


def test_save_and_discard_clear_the_form_and_the_draft(session):
    _stage_image(session)
    session.begin_details()
    session.autosave(FIELDS)
    draft_id = session.draft_id
    session.save(FIELDS)
    assert session.form == {} and session.draft_id is None and drafts.load_draft(draft_id) is None

    _stage_image(session, "b.png")
    session.begin_details()
    session.autosave(FIELDS)
    assert session.discard(False) is False and session.form == FIELDS
    draft_id = session.draft_id
    assert session.discard(True) is True and session.form == {} and drafts.load_draft(draft_id) is None


def test_restore_adopts_the_draft_and_keeps_writing_to_it(session):
    _stage_image(session)
    session.begin_details()
    session.autosave(FIELDS)
    draft = _progress(session)
    fresh = LiveSession(Cfg())  # as after a crash and a relaunch
    fresh.restore(draft)
    assert fresh.draft_id == draft.id and fresh.form["title"] == "Login broken"
    assert [s.number for s in fresh.staged] == [1] and fresh.staged[0].path.exists()
    fresh.autosave({**FIELDS, "title": "Login broken on Safari"})
    assert [d.title for d in drafts.list_drafts("owner/proj")] == ["Login broken on Safari"]


def test_addition_is_remembered_in_memory_only(session):
    report = _existing(session)
    session.remember_addition(report.id, "half a note")
    assert session.addition == {"report_id": report.id, "note": "half a note"}
    assert session.draft_id is None
    session.remember_form({"title": "another bug", "notes": ""})
    session.attach(report.id, "the full note")
    assert session.addition == {}
    assert session.form["title"] == "another bug" and _progress(session).title == "another bug"


def test_discard_clears_the_addition(session):
    session.remember_addition(3, "x")
    _stage_image(session)
    session.begin_details()
    session.discard(True)
    assert session.addition == {}


def test_emptying_the_bug_drops_its_progress_draft(session):
    _stage_image(session)
    draft_id = session.draft_id
    session.clear_staged()
    assert session.draft_id is None and drafts.load_draft(draft_id) is None


def test_abandon_throws_everything_away(session):
    shot = _shot()
    session.start(); session.capture_done(shot)
    session.autosave(FIELDS)
    draft_id = session.draft_id
    session.abandon()
    assert not shot.exists() and session.form == {} and drafts.load_draft(draft_id) is None


def test_keep_as_draft_leaves_a_single_draft(session):
    _stage_image(session)
    session.begin_details()
    session.autosave(FIELDS)
    assert session.keep_as_draft(FIELDS) is True
    kept = drafts.list_drafts("owner/proj")
    assert len(kept) == 1 and kept[0].title == "Login broken"
    assert kept[0].png_path.parent == drafts.drafts_dir()


def test_autosave_records_the_launch_repo(session):
    session.begin_details()
    session.autosave({**FIELDS, "repo": "someone/else"})
    assert [d.title for d in drafts.list_drafts("owner/proj")] == ["Login broken"]
