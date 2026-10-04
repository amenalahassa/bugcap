"""BUGS.md: validate repo values, init --force / config repo set re-homing reports."""
import pytest

from bugcap import cli, ghcli, repo, validation
from bugcap.store import Store


# --- validation -------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["owner/repo", "my-org/my.repo_1", "a/b"])
def test_good_slugs(slug):
    assert validation.validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["", "owner", "owner/", "/repo", "a/b/c", "bad owner/repo", "o/r r", "-o/r", "o/..", "o/r\n"])
def test_bad_slugs(slug):
    with pytest.raises(ValueError) as exc:
        validation.validate_slug(slug, "images repo")
    assert repr(slug) in str(exc.value) and "images repo" in str(exc.value)


@pytest.mark.parametrize("path", ["bugcap-images", "a/b", "docs/bug-images/x", "x/"])
def test_good_paths(path):
    validation.validate_images_path(path)


@pytest.mark.parametrize("path", ["", "/", "/lead", "..", "a/../b", "a//b", "a\\b", "has space", "./x"])
def test_bad_paths(path):
    with pytest.raises(ValueError):
        validation.validate_images_path(path)


@pytest.mark.parametrize("branch", ["main", "feature/x-1", "release_2.0"])
def test_good_branches(branch):
    validation.validate_branch(branch)


@pytest.mark.parametrize("branch", ["", "a b", "-x", "x/", "a..b", "x.lock", "a~1", "a:b", "a@{1}", "end.", "/x", "a//b"])
def test_bad_branches(branch):
    with pytest.raises(ValueError):
        validation.validate_branch(branch)


# --- online verification ------------------------------------------------------------

def _fake_verify(monkeypatch, behaviour):
    calls = []

    def verify(slug, branch=None, need_write=False):
        calls.append((slug, branch, need_write))
        if behaviour == "unavailable":
            raise ghcli.GhUnavailable("offline")
        if behaviour:
            raise ghcli.GhError(behaviour)

    monkeypatch.setattr(ghcli, "verify_repo", verify)
    return calls


def test_init_rejects_malformed_slug_before_writing(bugcap_home, git_repo, monkeypatch, capsys):
    root = git_repo()
    monkeypatch.chdir(root)
    assert cli.main(["init", "--images-repo", "not a slug"]) == 1
    assert "invalid images repo 'not a slug'" in capsys.readouterr().err
    assert not (root / repo.CONFIG_NAME).exists()
    assert cli.main(["init", "--github", "x"]) == 1
    assert "invalid GitHub repo 'x'" in capsys.readouterr().err


def test_init_definite_gh_failure_names_the_value(bugcap_home, git_repo, monkeypatch, capsys):
    root = git_repo()
    monkeypatch.chdir(root)
    _fake_verify(monkeypatch, "repo 'o/assets' does not exist, or your `gh` login cannot see it")
    assert cli.main(["init", "--images-repo", "o/assets"]) == 1
    assert "'o/assets' does not exist" in capsys.readouterr().err
    assert not (root / repo.CONFIG_NAME).exists()


def test_init_offline_warns_and_continues(bugcap_home, git_repo, monkeypatch, capsys):
    root = git_repo()
    monkeypatch.chdir(root)
    calls = _fake_verify(monkeypatch, "unavailable")
    assert cli.main(["init", "--images-repo", "o/assets"]) == 0
    assert "warning: could not verify o/assets" in capsys.readouterr().err
    assert calls == [("o/assets", None, True)]
    assert repo.load_repo_config(root).images_repo == "o/assets"


def test_sync_rejects_bad_images_values(bugcap_home, monkeypatch, capsys, fake_gh):
    with Store() as store:
        rid = store.add("Bug", repo="o/r").id
    fake_gh.on("auth", "status")
    assert cli.main(["sync", str(rid), "--repo", "o/r", "--images-repo", "oops"]) == 1
    assert "invalid images repo 'oops'" in capsys.readouterr().err
    assert cli.main(["sync", str(rid), "--repo", "o/r", "--images-path", "../x"]) == 1
    assert "invalid images path" in capsys.readouterr().err
    assert cli.main(["sync", str(rid), "--repo", "o/r", "--images-branch", "a b"]) == 1
    assert "invalid branch 'a b'" in capsys.readouterr().err


def test_sync_refuses_unwritable_images_repo_before_anything_is_committed(bugcap_home, monkeypatch, capsys, fake_gh):
    with Store() as store:
        rid = store.add("Bug", repo="o/r").id
    _fake_verify(monkeypatch, "repo 'o/assets' is not writable with the current `gh` login")
    assert cli.main(["sync", str(rid), "--repo", "o/r", "--images-repo", "o/assets", "--yes"]) == 1
    assert "not writable" in capsys.readouterr().err
    assert not [c for c in fake_gh.argvs if "PUT" in c or "create" in c and "--help" not in c]


def test_verify_repo_against_gh_outputs(fake_gh):
    import json

    verify = ghcli.verify_repo_real
    fake_gh.on("auth", "status")
    fake_gh.add(lambda argv: "repos/o/found/branches/nope" in " ".join(argv), returncode=1, stderr="Not Found (HTTP 404)")
    fake_gh.on("repos/o/found", stdout=json.dumps({"permissions": {"push": True}}))
    fake_gh.on("repos/o/readonly", stdout=json.dumps({"permissions": {"push": False}}))
    fake_gh.add(lambda argv: "repos/o/missing" in " ".join(argv), returncode=1, stderr="gh: Not Found (HTTP 404)")
    fake_gh.add(lambda argv: "repos/o/neterr" in " ".join(argv), returncode=1, stderr="could not resolve host")
    verify("o/found", need_write=True)
    with pytest.raises(ghcli.GhError, match="not writable"):
        verify("o/readonly", need_write=True)
    verify("o/readonly")  # read access is enough when write is not needed
    with pytest.raises(ghcli.GhError, match="does not exist"):
        verify("o/missing")
    with pytest.raises(ghcli.GhError, match="branch 'nope'"):
        verify("o/found", "nope")
    with pytest.raises(ghcli.GhUnavailable):
        verify("o/neterr")


def test_verify_repo_unavailable_without_gh(fake_gh):
    fake_gh.present.clear()
    with pytest.raises(ghcli.GhUnavailable):
        ghcli.verify_repo_real("o/r")


# --- init --force / config repo: re-homing reports ------------------------------------

@pytest.fixture
def repo_with_reports(bugcap_home, git_repo, monkeypatch):
    root = git_repo(name="proj", origin="https://github.com/owner/proj")
    monkeypatch.chdir(root)
    assert cli.main(["init"]) == 0
    with Store() as store:
        store.add("one", repo="owner/proj", tags=["proj", "ui"])
        store.add("two", repo="owner/proj", tags=["proj"])
        store.add("elsewhere", repo="x/y", tags=["y"])
    return root


def _titles(repo_key):
    with Store() as store:
        return sorted(r.title for r in store.list(repo=repo_key))


def test_force_same_identity_asks_nothing(repo_with_reports, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    assert cli.main(["init", "--force", "--images-repo", "owner/assets"]) == 0
    assert _titles("owner/proj") == ["one", "two"]


def test_force_new_identity_non_interactive_requires_a_flag(repo_with_reports, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    assert cli.main(["init", "--force", "--github", "owner/renamed", "--tag", "renamed"]) == 1
    err = capsys.readouterr().err
    assert "2 existing report(s)" in err and "owner/proj" in err and "owner/renamed" in err
    assert "--migrate" in err and "--no-migrate" in err
    assert repo.load_repo_config(repo_with_reports).key == "owner/proj"  # config untouched
    assert _titles("owner/proj") == ["one", "two"]


def test_force_with_migrate_moves_reports_and_tag(repo_with_reports, capsys):
    assert cli.main(["init", "--force", "--github", "owner/renamed", "--tag", "renamed", "--migrate"]) == 0
    assert "Moved 2 report(s)" in capsys.readouterr().out
    assert _titles("owner/proj") == [] and _titles("owner/renamed") == ["one", "two"]
    assert _titles("x/y") == ["elsewhere"]  # other repos untouched
    with Store() as store:
        assert [r.tags for r in store.list(repo="owner/renamed") if r.title == "one"] == [["renamed", "ui"]]
    assert cli.main(["list"]) == 0
    assert "one" in capsys.readouterr().out


def test_force_with_no_migrate_leaves_reports_and_says_so(repo_with_reports, capsys):
    assert cli.main(["init", "--force", "--github", "owner/renamed", "--no-migrate"]) == 0
    assert "Left 2 report(s) under owner/proj" in capsys.readouterr().err
    assert _titles("owner/proj") == ["one", "two"]


def test_force_interactive_prompt(repo_with_reports, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": print(prompt) or "y")
    assert cli.main(["init", "--force", "--github", "owner/renamed"]) == 0
    out = capsys.readouterr().out
    assert "2 existing report(s)" in out and "owner/renamed" in out
    assert _titles("owner/renamed") == ["one", "two"]


def test_force_interactive_decline(repo_with_reports, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["init", "--force", "--github", "owner/renamed"]) == 0
    assert _titles("owner/proj") == ["one", "two"]


def test_force_with_no_reports_needs_no_flag(bugcap_home, git_repo, monkeypatch):
    root = git_repo(name="p2", origin="https://github.com/o/p2")
    monkeypatch.chdir(root)
    cli.main(["init"])
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    assert cli.main(["init", "--force", "--github", "o/other"]) == 0


# --- config repo ------------------------------------------------------------------------

def test_config_repo_show(repo_with_reports, capsys):
    assert cli.main(["config", "repo", "show"]) == 0
    out = capsys.readouterr().out
    assert "tag:" in out and "proj" in out and "owner/proj" in out and "images_repo:" in out and "(not set)" in out


def test_config_repo_outside_a_repo(bugcap_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "repo", "show"]) == 1
    assert "bugcap init" in capsys.readouterr().err


def test_config_set_sync_values_without_force(repo_with_reports, capsys):
    assert cli.main(["config", "repo", "set", "images_repo", "owner/assets"]) == 0
    assert cli.main(["config", "repo", "set", "images_path", "/shots/"]) == 0
    assert cli.main(["config", "repo", "set", "images_branch", "main"]) == 0
    cfg = repo.load_repo_config(repo_with_reports)
    assert (cfg.images_repo, cfg.images_path, cfg.images_branch) == ("owner/assets", "shots", "main")
    assert cfg.tag == "proj" and cfg.github == "owner/proj"  # other keys kept
    assert _titles("owner/proj") == ["one", "two"]


def test_config_set_validates(repo_with_reports, capsys):
    assert cli.main(["config", "repo", "set", "images_repo", "nope"]) == 1
    assert "invalid images repo 'nope'" in capsys.readouterr().err
    assert cli.main(["config", "repo", "set", "images_path", "../x"]) == 1
    assert cli.main(["config", "repo", "set", "bogus", "x"]) == 2
    assert repo.load_repo_config(repo_with_reports).images_repo is None


def test_config_set_checks_with_gh(repo_with_reports, monkeypatch, capsys):
    calls = _fake_verify(monkeypatch, None)
    assert cli.main(["config", "repo", "set", "images_repo", "owner/assets"]) == 0
    assert calls == [("owner/assets", None, True)]
    calls.clear()
    assert cli.main(["config", "repo", "set", "images_branch", "docs"]) == 0
    assert calls == [("owner/assets", "docs", True)]  # the branch is checked against the current images repo
    _fake_verify(monkeypatch, "repo 'owner/ghost' does not exist, or your `gh` login cannot see it")
    assert cli.main(["config", "repo", "set", "images_repo", "owner/ghost"]) == 1
    assert repo.load_repo_config(repo_with_reports).images_repo == "owner/assets"


def test_config_set_identity_change_follows_migrate_rules(repo_with_reports, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    assert cli.main(["config", "repo", "set", "github", "owner/new"]) == 1
    assert "--migrate" in capsys.readouterr().err
    assert repo.load_repo_config(repo_with_reports).github == "owner/proj"
    assert cli.main(["config", "repo", "set", "github", "owner/new", "--migrate"]) == 0
    assert _titles("owner/new") == ["one", "two"] and _titles("owner/proj") == []


def test_config_set_tag_only_swaps_the_tag(repo_with_reports, capsys):
    assert cli.main(["config", "repo", "set", "tag", "fresh", "--migrate"]) == 0
    with Store() as store:
        tags = {r.title: r.tags for r in store.list(repo="owner/proj")}
    assert tags == {"one": ["fresh", "ui"], "two": ["fresh"]}


def test_config_unset(repo_with_reports, capsys):
    cli.main(["config", "repo", "set", "images_repo", "owner/assets"])
    assert cli.main(["config", "repo", "unset", "images_repo"]) == 0
    assert repo.load_repo_config(repo_with_reports).images_repo is None
    assert cli.main(["config", "repo", "unset", "tag"]) == 2
    # removing the github slug changes the repo key to the tag, so it follows the same rules
    assert cli.main(["config", "repo", "unset", "github", "--migrate"]) == 0
    assert _titles("proj") == ["one", "two"]
