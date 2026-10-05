"""Sync of video/animated/frames media, size limits and @ reference substitution."""
import base64
import json

from fixtures.make_images import png_bytes

from bugcap import service, sync
from bugcap.store import Store
from bugcap.sync import GitHubDestination, ImagesTarget, SyncOptions


def _setup(fake_gh):
    fake_gh.on("issue", "create", "--help", stdout="x --attach y")
    fake_gh.on("repo", "view", stdout=json.dumps({"visibility": "private"}))
    fake_gh.add(
        lambda argv: any("contents" in e for e in argv) and "--method" not in argv,
        returncode=1, stderr="not found",
    )
    fake_gh.on("--method", "PUT", stdout=json.dumps({"commit": {"sha": "abc123"}}))
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/5\n")


def _opts(max_upload_mb=25):
    return SyncOptions(
        issue_slug="o/r", images=ImagesTarget(repo="o/r", path="bugcap-images", branch=None),
        assume_yes=True, max_upload_mb=max_upload_mb,
    )


def _body(fake_gh) -> str:
    create = next(c for c in fake_gh.calls if "create" in c.argv and "--help" not in c.argv)
    return create.stdin


def _puts(fake_gh):
    return [c for c in fake_gh.calls if "PUT" in c.argv]


def _add_file(store, rid, kind, data, ext, label=None):
    from bugcap.paths import media_dir

    path = media_dir() / f"{kind}-{len(data)}{ext}"
    path.write_bytes(data)
    return store.insert_media(rid, kind=kind, path=str(path), label=label, mime="video/mp4", source="recorded")


def test_video_and_animated_uploaded_as_is(bugcap_home, fake_gh):
    _setup(fake_gh)
    with Store() as store:
        rid = store.add("Bug", repo="o/r").id
        _add_file(store, rid, "video", b"VIDEO-BYTES", ".mp4")
        _add_file(store, rid, "animated", b"GIF89a-animated", ".gif")
        sync.sync_report(store, store.get(rid), GitHubDestination(), _opts())
    sent = [base64.b64decode(json.loads(c.stdin)["content"]) for c in _puts(fake_gh)]
    assert sent == [b"VIDEO-BYTES", b"GIF89a-animated"]
    body = _body(fake_gh)
    assert "[video-11.mp4](https://github.com/o/r/blob/abc123/bugcap-images/video-11.mp4)" in body


def test_frames_committed_in_order_as_numbered_list(bugcap_home, fake_gh):
    _setup(fake_gh)
    from bugcap.paths import media_dir

    frames = []
    for n in (1, 2, 3):
        p = media_dir() / f"f{n}.png"
        p.write_bytes(png_bytes() + bytes([n]))
        frames.append((str(p), p.stat().st_size))
    with Store() as store:
        rid = store.add("Bug", repo="o/r").id
        store.insert_media(rid, kind="frames", path=None, mime="image/png", size_bytes=sum(s for _, s in frames),
                           source="recorded", frames=frames)
        sync.sync_report(store, store.get(rid), GitHubDestination(), _opts())
    paths = [next(e for e in c.argv if "contents" in e) for c in _puts(fake_gh)]
    assert [p.rsplit("/", 1)[1] for p in paths] == ["001.png", "002.png", "003.png"]
    body = _body(fake_gh)
    assert body.index("1. [") < body.index("2. [") < body.index("3. [")


def test_oversize_media_skipped_with_warning_and_sync_continues(bugcap_home, fake_gh):
    _setup(fake_gh)
    with Store() as store:
        rid = store.add("Bug", notes="see @1 and @2", repo="o/r").id
        _add_file(store, rid, "video", b"x" * (2 * 1024 * 1024), ".mp4")
        _add_file(store, rid, "animated", b"small", ".gif")
        res = sync.sync_report(store, store.get(rid), GitHubDestination(), _opts(max_upload_mb=1))
    assert res.created_issue
    assert any(
        m.startswith("warning: skipped media @v1 video-2097152.mp4 (2.0 MB): above the 1 MB upload limit")
        for m in res.messages
    )
    assert len(_puts(fake_gh)) == 1  # the small one still went up
    body = _body(fake_gh)
    assert "@v1 (not uploaded: above the 1 MB limit)" in body
    assert "[animated-5.gif](https://github.com/o/r/blob/abc123/bugcap-images/animated-5.gif)" in body


def test_references_replaced_in_issue_body(bugcap_home, fake_gh, sample_images):
    _setup(fake_gh)
    with Store() as store:
        report, _ = service.create_report(
            store, "Bug", notes="see @1 and @login-error, mail a@b.com, literal @@1", repo="o/r",
            sources=[str(sample_images / "sample.png"), str(sample_images / "sample.gif")], labels=[None, "login-error"],
        )
        sync.sync_report(store, report, GitHubDestination(), _opts())
    body = _body(fake_gh)
    first = body.split("\n\n")[0]
    assert first.startswith("see ![")
    assert "![login-error](https://github.com/o/r/blob/abc123/bugcap-images/" in first
    assert "mail a@b.com, literal @1" in first
    assert "@login-error" not in first
    assert body.count("![") == 2  # referenced images are not appended a second time


def test_report_refs_become_issue_numbers_or_plain_text(bugcap_home, fake_gh):
    _setup(fake_gh)
    with Store() as store:
        same = store.add("Same repo", repo="o/r")
        store.set_ref(same.id, "github.issue", "o/r#42")
        elsewhere = store.add("Elsewhere", repo="o/r")
        store.set_ref(elsewhere.id, "github.issue", "other/x#7")
        unsynced = store.add("Unsynced", repo="o/r")
        rid = store.add(
            "Bug", notes=f"dup of #{same.id}, see #{elsewhere.id}, also #{unsynced.id} and #999", repo="o/r",
        ).id
        sync.sync_report(store, store.get(rid), GitHubDestination(), _opts())
    body = _body(fake_gh)
    assert f"dup of #42, see other/x#7, also report {unsynced.id} and #999" in body
