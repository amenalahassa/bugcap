"""T031: image-commit consent rules (FR-018a) and images-target resolution (FR-018b/R2)."""
import json

from bugcap import config, repo, sync
from bugcap.store import Store
from bugcap.sync import GitHubDestination, ImagesTarget, SyncOptions, resolve_images_target


def _img(tmp_path, name="s.png", data=b"X"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _handlers(fake_gh, visibility="public", view_fails=False):
    fake_gh.on("issue", "create", "--help", stdout="--attach")
    if view_fails:
        fake_gh.on("repo", "view", returncode=1, stderr="boom")
    else:
        fake_gh.on("repo", "view", stdout=json.dumps({"visibility": visibility}))
    fake_gh.add(lambda a: any("contents" in e for e in a) and "--method" not in a, returncode=1)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "c1"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/1\n")


class Recorder:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, slug, visibility):
        self.calls.append((slug, visibility))
        return self.answer


def _opts(confirm=None, assume_yes=False, interactive=True, repo_="o/r"):
    return SyncOptions(
        issue_slug="o/r",
        images=ImagesTarget(repo=repo_, path="bugcap-images", branch=None),
        assume_yes=assume_yes,
        interactive=interactive,
        confirm=confirm,
    )


def test_public_prompts_every_run_decline_skips_commit(bugcap_home, fake_gh, tmp_path):
    _handlers(fake_gh, visibility="public")
    confirm = Recorder(False)
    with Store() as store:
        rep = store.add("Bug", image_paths=[str(_img(tmp_path))], repo="o/r")
        res1 = sync.sync_report(store, rep, GitHubDestination(), _opts(confirm))
        assert res1.created_issue is True           # issue still proceeds
        assert res1.image_permalinks == []           # nothing committed
        assert any("skipped image commit" in m for m in res1.messages)
        rep = store.get(rep.id)
        sync.sync_report(store, rep, GitHubDestination(), _opts(confirm))
    assert len(confirm.calls) == 2                    # asked every run
    assert not any("PUT" in c.argv for c in fake_gh.calls)


def test_private_prompts_first_time_only_and_saves_consent(bugcap_home, fake_gh, tmp_path):
    _handlers(fake_gh, visibility="private")
    confirm = Recorder(True)
    with Store() as store:
        a = store.add("A", image_paths=[str(_img(tmp_path, "a.png", b"A"))], repo="o/r")
        sync.sync_report(store, a, GitHubDestination(), _opts(confirm))
        assert config.consent_has("o/r") is True       # consent saved
        # a second report to the same private repo must not prompt again
        b = store.add("B", image_paths=[str(_img(tmp_path, "b.png", b"B"))], repo="o/r")
        sync.sync_report(store, b, GitHubDestination(), _opts(confirm))
    assert len(confirm.calls) == 1
    # consent persisted to global config under [consent] images_repos
    assert "o/r" in config.load().get("consent", {}).get("images_repos", "")


def test_visibility_unknown_treated_as_public(bugcap_home, fake_gh, tmp_path):
    _handlers(fake_gh, view_fails=True)
    confirm = Recorder(False)
    with Store() as store:
        rep = store.add("Bug", image_paths=[str(_img(tmp_path))], repo="o/r")
        res = sync.sync_report(store, rep, GitHubDestination(), _opts(confirm))
    assert confirm.calls and confirm.calls[0][1] == "public"
    assert res.image_permalinks == []
    assert config.consent_has("o/r") is False          # public never remembered


def test_non_interactive_without_yes_skips_with_message(bugcap_home, fake_gh, tmp_path):
    _handlers(fake_gh, visibility="private")
    with Store() as store:
        rep = store.add("Bug", image_paths=[str(_img(tmp_path))], repo="o/r")
        res = sync.sync_report(store, rep, GitHubDestination(), _opts(confirm=None, interactive=False))
        assert res.created_issue is True
        assert any("skipped image commit" in m for m in res.messages)
    assert not any("PUT" in c.argv for c in fake_gh.calls)


def test_yes_accepts(bugcap_home, fake_gh, tmp_path):
    _handlers(fake_gh, visibility="public")
    with Store() as store:
        rep = store.add("Bug", image_paths=[str(_img(tmp_path))], repo="o/r")
        res = sync.sync_report(store, rep, GitHubDestination(), _opts(assume_yes=True))
        assert res.image_permalinks  # committed
    assert any("PUT" in c.argv for c in fake_gh.calls)


def test_resolution_order(tmp_path):
    cfg = repo.RepoConfig(
        root=tmp_path, tag="t",
        images_repo="cfg/repo", images_path="cfgpath", images_branch="cfgbr",
    )
    glob = {"images_repo": "glob/repo", "images_path": "globpath", "images_branch": "globbr"}

    # flag wins
    t = resolve_images_target("flag/repo", "fpath", "fbr", cfg, glob, "issue/repo")
    assert (t.repo, t.path, t.branch) == ("flag/repo", "fpath", "fbr")

    # repo cfg next
    t = resolve_images_target(None, None, None, cfg, glob, "issue/repo")
    assert (t.repo, t.path, t.branch) == ("cfg/repo", "cfgpath", "cfgbr")

    # global next
    t = resolve_images_target(None, None, None, None, glob, "issue/repo")
    assert (t.repo, t.path, t.branch) == ("glob/repo", "globpath", "globbr")

    # issue repo with default path last
    t = resolve_images_target(None, None, None, None, {}, "issue/repo")
    assert (t.repo, t.path, t.branch) == ("issue/repo", "bugcap-images", None)


def test_max_upload_mb_default_and_clamp(bugcap_home):
    from bugcap import config

    assert config.get_max_upload_mb() == 25
    config.set_value("sync.max_upload_mb", "40")
    assert config.get_max_upload_mb() == 40
    config.set_value("sync.max_upload_mb", "5000")
    assert config.get_max_upload_mb() == 100  # GitHub blocks files over 100 MB
    config.set_value("sync.max_upload_mb", "-3")
    assert config.get_max_upload_mb() == 25
