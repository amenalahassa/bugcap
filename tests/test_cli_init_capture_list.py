"""T016: init writes config; capture scopes inside a repo; list filters; --all; legacy rows."""
import pytest

from fixtures.make_images import png_bytes
from bugcap import cli, repo
from bugcap.store import Store


def test_init_writes_config(bugcap_home, git_repo, monkeypatch, capsys):
    root = git_repo(name="myproj", origin="git@github.com:owner/myproj.git")
    monkeypatch.chdir(root)
    assert cli.main(["init"]) == 0
    cfg = repo.load_repo_config(root)
    assert cfg.tag == "myproj"
    assert cfg.github == "owner/myproj"
    out = capsys.readouterr().out
    assert "myproj" in out

    # refuses to overwrite without --force
    assert cli.main(["init", "--tag", "x"]) == 1
    assert "already exists" in capsys.readouterr().err
    # overrides + force
    assert cli.main(["init", "--tag", "renamed", "--github", "o/r", "--images-repo", "o/assets", "--force"]) == 0
    cfg = repo.load_repo_config(root)
    assert cfg.tag == "renamed" and cfg.github == "o/r" and cfg.images_repo == "o/assets"


def test_capture_image_scoped_inside_repo(bugcap_home, git_repo, monkeypatch, tmp_path, capsys):
    root = git_repo(name="proj", origin="https://github.com/owner/proj")
    monkeypatch.chdir(root)
    cli.main(["init"])
    capsys.readouterr()

    img = tmp_path / "shot.png"
    img.write_bytes(png_bytes())
    assert cli.main(["capture", "--image", str(img), "--title", "Broken", "--note", "x"]) == 0

    with Store() as store:
        reps = store.list()
        assert len(reps) == 1
        r = reps[0]
        assert r.repo == "owner/proj"
        assert "proj" in r.tags  # repo tag auto-applied


def test_capture_outside_repo_unchanged(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # not a repo
    img = tmp_path / "s.png"
    img.write_bytes(png_bytes())
    assert cli.main(["capture", "--image", str(img), "--title", "T", "--note", "n"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Saved report #1: T")
    with Store() as store:
        r = store.list()[0]
        assert r.repo is None
        assert r.tags == []


def test_list_scoping_and_all(bugcap_home, git_repo, monkeypatch, capsys):
    root = git_repo(name="proj", origin="https://github.com/owner/proj")
    with Store() as store:
        store.add("in repo", repo="owner/proj", tags=["proj"])
        store.add("other repo", repo="x/y")
        store.add("legacy", repo=None)

    monkeypatch.chdir(root)
    cli.main(["init"])
    capsys.readouterr()

    cli.main(["list"])
    scoped = capsys.readouterr().out
    assert "in repo" in scoped
    assert "other repo" not in scoped
    assert "legacy" not in scoped

    cli.main(["list", "--all"])
    everything = capsys.readouterr().out
    assert "in repo" in everything and "other repo" in everything and "legacy" in everything


def test_list_outside_repo_shows_all(bugcap_home, tmp_path, monkeypatch, capsys):
    with Store() as store:
        store.add("a", repo="x/y")
        store.add("b", repo=None)
    monkeypatch.chdir(tmp_path)
    cli.main(["list"])
    out = capsys.readouterr().out
    assert "a" in out and "b" in out
