"""T009: repo config detection, .bugcap.toml discovery, [sync] round-trip, tomlio quoting."""
import pytest

from bugcap import repo, tomlio
from bugcap.repo import RepoConfigError

# `init_repo`/`write_config` now also record the repo in the global known-repos registry
# (paths.config_dir()); isolate every test in this module from the real one.
pytestmark = pytest.mark.usefixtures("bugcap_home")


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


def test_known_repos_lists_every_initialized_repo(git_repo):
    a = repo.init_repo(git_repo(name="repo-a"), tag="repo-a")
    b = repo.init_repo(git_repo(name="repo-b"), tag="repo-b")
    known = repo.known_repos()
    assert [c.key for c in known] == sorted([a.key, b.key])


def test_known_repos_prunes_deleted_configs(git_repo):
    kept = repo.init_repo(git_repo(name="kept"), tag="kept")
    gone_root = git_repo(name="gone")
    repo.init_repo(gone_root, tag="gone")
    (gone_root / ".bugcap.toml").unlink()

    known = repo.known_repos()

    assert [c.key for c in known] == [kept.key]


def test_known_repos_self_heals_from_load(git_repo):
    root = git_repo(name="legacy")
    repo.init_repo(root, tag="legacy")
    # Simulate a repo initialized before the registry existed: drop it from the registry
    # but keep its .bugcap.toml on disk.
    registry = repo._registry_path()
    registry.write_text("[]", encoding="utf-8")
    assert repo.known_repos() == []

    repo.load_repo_config(root)  # any bugcap command run from inside it, e.g. `bugcap list`

    assert [c.key for c in repo.known_repos()] == ["legacy"]


def test_known_repos_reflects_config_updates(git_repo):
    import dataclasses

    root = git_repo(name="proj")
    cfg = repo.init_repo(root, tag="old-tag")
    repo.write_config(dataclasses.replace(cfg, tag="new-tag"))
    known = repo.known_repos()
    assert [c.tag for c in known] == ["new-tag"]


def test_tomlio_quotes_special_characters(tmp_path):
    path = tmp_path / "c.toml"
    tomlio.save(path, {"tag": 'weird "name" with = and \\ ', "sync": {"images_path": "a/b"}})
    loaded = tomlio.load(path)
    assert loaded["tag"] == 'weird "name" with = and \\ '
    assert loaded["sync"]["images_path"] == "a/b"
