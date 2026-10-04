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
