"""T025: github pull — create/update/unchanged, refresh rules, forwarding, --ask."""
import json

import pytest

from bugcap import sync
from bugcap.ghcli import GhError
from bugcap.store import Store


def _issues(*items):
    return json.dumps(list(items))


def _issue(n, title, body="b", state="OPEN"):
    return {"number": n, "title": title, "body": body, "url": f"https://github.com/o/r/issues/{n}", "state": state, "labels": []}


def test_first_pull_creates_then_unchanged(bugcap_home, fake_gh):
    fake_gh.on("issue", "list", stdout=_issues(_issue(1, "Bug one"), _issue(2, "Bug two", state="CLOSED")))
    with Store() as store:
        r1 = sync.pull_issues(store, "o/r")
        assert r1 == {"created": 2, "updated": 0, "unchanged": 0}
        reps = store.list()
        assert {rp.synced_refs["github.issue"] for rp in reps} == {"o/r#1", "o/r#2"}
        closed = store.find_by_ref("github.issue", "o/r#2")
        assert closed.status == "closed"  # status set from state on first import only

        r2 = sync.pull_issues(store, "o/r")
        assert r2 == {"created": 0, "updated": 0, "unchanged": 2}
        assert len(store.list()) == 2  # no duplicates


def test_refresh_title_body_only_preserves_local(bugcap_home, fake_gh):
    fake_gh.on("issue", "list", stdout=_issues(_issue(1, "Old title", body="old")))
    with Store() as store:
        sync.pull_issues(store, "o/r")
        rid = store.find_by_ref("github.issue", "o/r#1").id
        # local edits
        store.update(rid, notes="my notes", status="resolved")
        store.set_tags(rid, ["local"])

        fake_gh._handlers.clear()
        fake_gh.on("issue", "list", stdout=_issues(_issue(1, "New title", body="new")))
        res = sync.pull_issues(store, "o/r")
        assert res["updated"] == 1
        rep = store.get(rid)
        assert rep.title == "New title"
        assert rep.body == "new"
        assert rep.notes == "my notes"       # preserved
        assert rep.status == "resolved"       # preserved
        assert rep.tags == ["local"]          # preserved


def test_forwards_label_limit_repo(bugcap_home, fake_gh):
    fake_gh.on("issue", "list", stdout="[]")
    with Store() as store:
        sync.pull_issues(store, "o/r", labels=["bug", "ui"], limit=5)
    argv = fake_gh.calls[-1].argv
    assert argv[argv.index("--repo") + 1] == "o/r"
    assert argv[argv.index("--limit") + 1] == "5"
    assert argv.count("--label") == 2


def test_ask_cb_attaches_or_skips(bugcap_home, fake_gh, tmp_path):
    img = tmp_path / "s.png"
    img.write_bytes(b"png")
    fake_gh.on("issue", "list", stdout=_issues(_issue(1, "A"), _issue(2, "B")))

    def ask(report, issue):
        return str(img) if issue["number"] == 1 else None

    with Store() as store:
        sync.pull_issues(store, "o/r", ask_cb=ask)
        r1 = store.find_by_ref("github.issue", "o/r#1")
        r2 = store.find_by_ref("github.issue", "o/r#2")
        assert r1.image_paths == [str(img)]
        assert r2.image_paths == []


def test_unauthenticated_gh_raises(bugcap_home, fake_gh):
    fake_gh.on("auth", "status", returncode=1)
    with Store() as store:
        with pytest.raises(GhError, match="gh auth login"):
            sync.pull_issues(store, "o/r")
