"""T030: github sync — create/commit/comment idempotency, resume, existing-path handling."""
import base64
import json

import pytest

from bugcap import config, sync
from bugcap.store import Store
from bugcap.sync import GitHubDestination, ImagesTarget, SyncOptions


def _img(tmp_path, name="shot.png", data=b"PNGDATA"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _base_handlers(fake_gh, *, attach=True, visibility="private", missing_file=True):
    fake_gh.on("issue", "create", "--help", stdout=("x --attach y" if attach else "x"))
    fake_gh.on("repo", "view", stdout=json.dumps({"visibility": visibility}))
    if missing_file:
        # GET contents 404 — but must not swallow the PUT (which also hits .../contents/...)
        fake_gh.add(
            lambda argv: any("contents" in e for e in argv) and "--method" not in argv,
            returncode=1,
            stderr="not found",
        )


def _get_contents(fake_gh, payload):
    """Register a GET contents response that does not match the PUT call."""
    fake_gh.add(
        lambda argv: any("contents" in e for e in argv) and "--method" not in argv,
        returncode=0,
        stdout=json.dumps(payload),
    )


def _opts(assume_yes=True, path="bugcap-images"):
    return SyncOptions(
        issue_slug="o/r",
        images=ImagesTarget(repo="o/r", path=path, branch=None),
        assume_yes=assume_yes,
    )


def test_new_report_creates_issue_commits_image(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path)
    _base_handlers(fake_gh)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")

    with Store() as store:
        rep = store.add("Broken button", notes="n", image_paths=[str(img)], repo="o/r")
        res = sync.sync_report(store, rep, GitHubDestination(), _opts())
        assert res.created_issue is True
        assert res.issue_url == "https://github.com/o/r/issues/5"

        saved = store.get(rep.id)
        assert saved.synced_refs["github.issue"] == "o/r#5"
        assert saved.synced_refs["github.image.shot.png"] == "o/r:bugcap-images/shot.png@abc123"
        assert "github.comment_hash" in saved.synced_refs

    # image went up via a PUT with base64 content on stdin
    put = next(c for c in fake_gh.calls if "PUT" in c.argv)
    assert base64.b64decode(json.loads(put.stdin)["content"]) == b"PNGDATA"
    # --attach used on creation
    create = next(c for c in fake_gh.calls if c.argv[:2] == ["gh", "issue"] and "create" in c.argv and "--help" not in c.argv)
    assert "--attach" in create.argv


def test_rerun_is_zero_writes(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path)
    _base_handlers(fake_gh)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")

    with Store() as store:
        rep = store.add("Bug", notes="n", image_paths=[str(img)], repo="o/r")
        sync.sync_report(store, rep, GitHubDestination(), _opts())
        rep = store.get(rep.id)
        fake_gh.calls.clear()
        sync.sync_report(store, rep, GitHubDestination(), _opts())

    writes = [c for c in fake_gh.calls if ("PUT" in c.argv) or ("comment" in c.argv) or ("create" in c.argv and "--help" not in c.argv)]
    assert writes == []


def test_changed_notes_one_comment(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path)
    _base_handlers(fake_gh)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")
    fake_gh.on("issue", "comment", stdout="https://github.com/o/r/issues/5#comment-1")

    with Store() as store:
        rep = store.add("Bug", notes="n", image_paths=[str(img)], repo="o/r")
        sync.sync_report(store, rep, GitHubDestination(), _opts())
        store.update(rep.id, notes="changed notes")
        rep = store.get(rep.id)
        fake_gh.calls.clear()
        res = sync.sync_report(store, rep, GitHubDestination(), _opts())
        assert res.commented is True
        assert res.created_issue is False

    comments = [c for c in fake_gh.calls if "comment" in c.argv]
    creates = [c for c in fake_gh.calls if "create" in c.argv and "--help" not in c.argv]
    assert len(comments) == 1
    assert creates == []


def test_resume_after_issue_create_failure(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path)
    _base_handlers(fake_gh)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    # issue create fails with no URL the first time
    fake_gh.on("issue", "create", returncode=1, stderr="server error")

    with Store() as store:
        rep = store.add("Bug", notes="n", image_paths=[str(img)], repo="o/r")
        with pytest.raises(Exception):
            sync.sync_report(store, rep, GitHubDestination(), _opts())
        rep = store.get(rep.id)
        assert rep.synced_refs.get("github.image.shot.png")  # image ref persisted
        assert "github.issue" not in rep.synced_refs

        # second run: image already committed (skip PUT), issue now succeeds
        fake_gh._handlers.clear()
        _base_handlers(fake_gh, missing_file=False)
        fake_gh.on("--method", "PUT", returncode=1, stderr="should not be called")
        fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/9\n")
        fake_gh.calls.clear()
        res = sync.sync_report(store, rep, GitHubDestination(), _opts())
        assert res.issue_url.endswith("/issues/9")

    assert not any("PUT" in c.argv for c in fake_gh.calls)  # no duplicate upload


def test_attach_partial_failure_still_records_issue(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path)
    _base_handlers(fake_gh)
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    # create exits non-zero but still prints the URL (attach upload failed)
    fake_gh.on("issue", "create", returncode=1, stdout="https://github.com/o/r/issues/11\n", stderr="attach failed")

    with Store() as store:
        rep = store.add("Bug", notes="n", image_paths=[str(img)], repo="o/r")
        res = sync.sync_report(store, rep, GitHubDestination(), _opts())
        assert res.issue_url.endswith("/issues/11")
        assert store.get(rep.id).synced_refs["github.issue"] == "o/r#11"


def test_existing_identical_path_skips_upload(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path, data=b"SAME")
    _base_handlers(fake_gh, missing_file=False)
    # GET returns identical content
    _get_contents(fake_gh, {"sha": "blob1", "content": base64.b64encode(b"SAME").decode()})
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")

    with Store() as store:
        rep = store.add("Bug", image_paths=[str(img)], repo="o/r")
        sync.sync_report(store, rep, GitHubDestination(), _opts())
        assert store.get(rep.id).synced_refs["github.image.shot.png"] == "o/r:bugcap-images/shot.png@blob1"

    assert not any("PUT" in c.argv for c in fake_gh.calls)  # identical -> no upload


def test_existing_different_content_unique_name(bugcap_home, fake_gh, tmp_path):
    img = _img(tmp_path, data=b"NEWBYTES")
    _base_handlers(fake_gh, missing_file=False)
    _get_contents(fake_gh, {"sha": "blob1", "content": base64.b64encode(b"OLDBYTES").decode()})
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "def456"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")

    with Store() as store:
        rep = store.add("Bug", image_paths=[str(img)], repo="o/r")
        sync.sync_report(store, rep, GitHubDestination(), _opts())
        ref = store.get(rep.id).synced_refs["github.image.shot.png"]

    # path has the unique <id>-<n>-<8hash>.png form
    assert ref.startswith("o/r:bugcap-images/")
    name = ref.split("/")[-1].split("@")[0]
    assert name.startswith(f"{rep.id}-0-") and name.endswith(".png")
    assert len(name.split("-")[-1].split(".")[0]) == 8
