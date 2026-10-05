"""T026: `bugcap attach`."""
import pytest
from fixtures.make_images import png_bytes

from bugcap import backends, capture, cli
from bugcap.store import Store


def test_attach_image_appends(bugcap_home, tmp_path):
    with Store() as store:
        rid = store.add("Bug", image_paths=["existing.png"]).id
    img = tmp_path / "new.png"
    img.write_bytes(png_bytes())
    assert cli.main(["attach", str(rid), "--image", str(img)]) == 0
    with Store() as store:
        paths = store.get(rid).image_paths
        assert len(paths) == 2
        assert paths[-1].endswith(".png")


def test_attach_without_image_captures(bugcap_home, monkeypatch, tmp_path):
    with Store() as store:
        rid = store.add("Bug").id
    shot = tmp_path / "cap.png"
    shot.write_bytes(png_bytes())
    monkeypatch.setattr(capture, "capture_screenshot", lambda: shot)
    assert cli.main(["attach", str(rid)]) == 0
    with Store() as store:
        assert store.get(rid).image_paths == [str(shot)]


def test_attach_unknown_id(bugcap_home, capsys):
    assert cli.main(["attach", "999", "--image", "x.png"]) == 1
    assert "no report with id 999" in capsys.readouterr().err


def test_attach_no_backend_no_image_is_guidance_error(bugcap_home, monkeypatch, capsys):
    with Store() as store:
        rid = store.add("Bug").id
    monkeypatch.setattr(backends, "detect", lambda: None)
    assert cli.main(["attach", str(rid)]) == 1
    assert "bugcap setup" in capsys.readouterr().err


# --- BUGS.md: attach --note --------------------------------------------------------

import re  # noqa: E402

from bugcap import agent_api, sync  # noqa: E402


def _seed(notes=""):
    with Store() as store:
        return store.add("Bug", notes=notes).id


def test_attach_note_appends_and_is_tied_to_the_image(bugcap_home, tmp_path, capsys):
    rid = _seed("original note")
    img = tmp_path / "new.png"
    img.write_bytes(png_bytes())
    assert cli.main(["attach", str(rid), "--image", str(img), "--note", "after the fix"]) == 0
    with Store() as store:
        report = store.get(rid)
    first, _, entry = report.notes.partition("\n\n")
    assert first == "original note"  # never replaced
    assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] @i1: after the fix", entry)
    assert "Added note" in capsys.readouterr().out


def test_attach_note_on_empty_notes_and_second_note_stacks(bugcap_home, tmp_path):
    rid = _seed()
    for name, text in (("a.png", "first"), ("b.png", "second")):
        img = tmp_path / name
        img.write_bytes(png_bytes())
        cli.main(["attach", str(rid), "--image", str(img), "--note", text])
    with Store() as store:
        lines = store.get(rid).notes.split("\n\n")
    assert len(lines) == 2 and lines[0].endswith("@i1: first") and lines[1].endswith("@i2: second")


def test_attach_note_references_every_added_image(bugcap_home, sample_images):
    rid = _seed()
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"),
              "--image", str(sample_images / "sample.gif"), "--note", "both views"])
    with Store() as store:
        assert store.get(rid).notes.endswith("@i1 @i2: both views")


def test_attach_note_resolves_in_show(bugcap_home, sample_images, capsys):
    rid = _seed()
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--note", "shows it"])
    capsys.readouterr()
    cli.main(["show", str(rid)])
    assert "@i1 (images/" in capsys.readouterr().out


def test_attach_captured_screenshot_with_note(bugcap_home, monkeypatch, tmp_path):
    rid = _seed()
    shot = tmp_path / "cap.png"
    shot.write_bytes(png_bytes())
    monkeypatch.setattr(capture, "capture_screenshot", lambda: shot)
    assert cli.main(["attach", str(rid), "--note", "from capture"]) == 0
    with Store() as store:
        assert store.get(rid).notes.endswith("@i1: from capture")


def test_attach_prompts_for_a_note_on_a_terminal(bugcap_home, sample_images, monkeypatch):
    rid = _seed()
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "typed note")
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png")])
    with Store() as store:
        assert store.get(rid).notes.endswith("@i1: typed note")


def test_attach_empty_prompt_answer_adds_no_note(bugcap_home, sample_images, monkeypatch):
    rid = _seed("keep")
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png")])
    with Store() as store:
        assert store.get(rid).notes == "keep"


def test_attach_no_prompt_when_not_a_terminal(bugcap_home, sample_images, monkeypatch):
    rid = _seed("keep")
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("prompted")))
    assert cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png")]) == 0


def test_attach_note_not_saved_when_no_image_was_added(bugcap_home, sample_images, capsys):
    rid = _seed("keep")
    rc = cli.main(["attach", str(rid), "--image", str(sample_images / "not-image.txt"), "--note", "lost?"])
    assert rc == 1 and "note was not saved" in capsys.readouterr().err
    with Store() as store:
        assert store.get(rid).notes == "keep"


def test_attach_note_with_bad_reference_keeps_the_image(bugcap_home, sample_images, capsys):
    rid = _seed()
    rc = cli.main(["attach", str(rid), "--image", str(sample_images / "sample.png"), "--note", "see @9"])
    err = capsys.readouterr().err
    assert rc == 1 and "unknown reference @9" in err and "image was attached" in err
    with Store() as store:
        report = store.get(rid)
    assert len(report.media) == 1 and report.notes == ""


def test_mcp_request_screenshot_note(bugcap_home, monkeypatch, tmp_path):
    shot = tmp_path / "cap.png"
    shot.write_bytes(png_bytes())
    monkeypatch.setattr(capture, "has_display", lambda: True)
    monkeypatch.setattr(capture, "capture_screenshot", lambda: shot)
    with Store() as store:
        rid = store.add("Bug", notes="before").id
        out = agent_api.request_screenshot(store, report_id=rid, note="what it shows")
        assert out["status"] == "captured" and "note_error" not in out
        assert store.get(rid).notes.startswith("before\n\n[") and store.get(rid).notes.endswith("@i1: what it shows")


def test_pull_ask_flow_appends_note(bugcap_home, monkeypatch, tmp_path):
    shot = tmp_path / "cap.png"
    shot.write_bytes(png_bytes())
    with Store() as store:
        rid = store.add("Issue").id
        sync._attach_answer(store, rid, (str(shot), "seen on pull"))
        sync._attach_answer(store, rid, str(shot))
        sync._attach_answer(store, rid, None)
        report = store.get(rid)
    assert len(report.media) == 2 and report.notes.endswith("@i1: seen on pull")


# --- details after attach / shared storage -----------------------------------------------

def test_attach_prints_the_bug_details_after_the_usual_output(bugcap_home, tmp_path, capsys):
    with Store() as store:
        rid = store.add("Login fails", tags=["auth"]).id
    img = tmp_path / "new.png"
    img.write_bytes(png_bytes())
    assert cli.main(["attach", str(rid), "--image", str(img), "--note", "see this"]) == 0
    out = capsys.readouterr().out
    assert out.index("added @i1") < out.index(f"#{rid}  Login fails")
    assert "tags:       auth" in out and "see this" in out and "media:" in out and "i1" in out


def test_attach_with_a_rejected_image_still_shows_the_unchanged_bug(bugcap_home, tmp_path, capsys):
    with Store() as store:
        rid = store.add("Bug").id
    assert cli.main(["attach", str(rid), "--image", str(tmp_path / "missing.png")]) == 1
    captured = capsys.readouterr()
    assert "skipped" in captured.err and f"#{rid}  Bug" in captured.out and "media:" not in captured.out


def test_attach_unknown_id_prints_no_details(bugcap_home, capsys):
    assert cli.main(["attach", "999", "--image", "x.png"]) == 1
    assert capsys.readouterr().out == ""


def test_same_image_on_two_bugs_is_stored_once(bugcap_home, tmp_path):
    from bugcap.paths import images_dir

    with Store() as store:
        a, b = store.add("A").id, store.add("B").id
    img = tmp_path / "same.png"
    img.write_bytes(png_bytes())
    assert cli.main(["attach", str(a), "--image", str(img)]) == 0
    assert cli.main(["attach", str(b), "--image", str(img)]) == 0
    with Store() as store:
        pa, pb = store.get(a).media[0].path, store.get(b).media[0].path
    assert pa == pb and len(list(images_dir().iterdir())) == 1


def test_shared_file_survives_until_its_last_user_is_gone(bugcap_home, tmp_path):
    from bugcap import service

    with Store() as store:
        a, b = store.add("A").id, store.add("B").id
    img = tmp_path / "same.png"
    img.write_bytes(png_bytes())
    for rid in (a, b):
        assert cli.main(["attach", str(rid), "--image", str(img)]) == 0
    with Store() as store:
        path = store.get(a).media[0].abs_path
        service.remove_media(store, a, "i1")
        assert __import__("os").path.isfile(path)  # B still uses it
        service.delete_report(store, b)
    assert not __import__("os").path.exists(path)


def test_same_image_twice_in_one_attach_and_failed_attach_keep_shared_file(bugcap_home, tmp_path):
    from bugcap import service

    with Store() as store:
        a, b = store.add("A").id, store.add("B").id
        img = tmp_path / "same.png"
        img.write_bytes(png_bytes())
        service.add_media(store, a, [str(img)])
        # B asks for the same image with a label that cannot be used: nothing may be deleted
        with pytest.raises(Exception):
            service.add_media(store, b, [str(img)], labels=["i1"])
        path = store.get(a).media[0].abs_path
        assert __import__("os").path.isfile(path)
        res = service.add_media(store, b, [str(img), str(img)])
        assert len(res.added) == 2 and len({m.path for m in res.added}) == 1
