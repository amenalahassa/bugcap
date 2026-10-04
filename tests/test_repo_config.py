"""T009: repo config detection, .bugcap.toml discovery, [sync] round-trip, tomlio quoting."""
import pytest

from bugcap import repo, tomlio
from bugcap.repo import RepoConfigError


def test_default_tag_is_directory_name(git_repo):
    root = git_repo(name="myrepo")
    cfg = repo.init_repo(root)
    assert cfg.tag == "myrepo"
    assert cfg.github is None  # no origin
    assert (root / ".bugcap.toml").is_file()


@pytest.mark.parametrize(
    "origin,slug",
    [
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("git@gitlab.com:owner/repo.git", None),
        ("", None),
    ],
)
def test_github_slug_detection(git_repo, origin, slug):
    root = git_repo(name="proj", origin=origin or None)
    cfg = repo.init_repo(root)
    assert cfg.github == slug


def test_tag_and_github_overrides(git_repo):
    root = git_repo(name="proj", origin="git@github.com:o/r.git")
    cfg = repo.init_repo(root, tag="custom", github="other/thing")
    assert cfg.tag == "custom"
    assert cfg.github == "other/thing"


def test_config_discovered_from_subdirectory(git_repo):
    root = git_repo(name="proj")
    repo.init_repo(root, tag="proj")
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    found = repo.find_config(sub)
    assert found == root / ".bugcap.toml"
    cfg = repo.load_repo_config(sub)
    assert cfg.tag == "proj"
    assert cfg.root == root


def test_refuses_overwrite_without_force(git_repo):
    root = git_repo(name="proj")
    repo.init_repo(root, tag="first")
    with pytest.raises(RepoConfigError):
        repo.init_repo(root, tag="second")
    assert repo.load_repo_config(root).tag == "first"
    cfg = repo.init_repo(root, tag="second", force=True)
    assert cfg.tag == "second"


def test_sync_table_round_trips(git_repo):
    root = git_repo(name="proj")
    repo.init_repo(
        root,
        tag="proj",
        images_repo="owner/assets",
        images_path="shots",
        images_branch="main",
    )
    cfg = repo.load_repo_config(root)
    assert cfg.images_repo == "owner/assets"
    assert cfg.images_path == "shots"
    assert cfg.images_branch == "main"


def test_tomlio_quotes_special_characters(tmp_path):
    path = tmp_path / "c.toml"
    tomlio.save(path, {"tag": 'weird "name" with = and \\ ', "sync": {"images_path": "a/b"}})
    loaded = tomlio.load(path)
    assert loaded["tag"] == 'weird "name" with = and \\ '
    assert loaded["sync"]["images_path"] == "a/b"
