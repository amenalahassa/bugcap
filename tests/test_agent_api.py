"""T036: agent_api tool logic (no MCP SDK needed)."""
import json

import pytest

from bugcap import agent_api, capture
from bugcap.capture import CaptureError
from bugcap.store import Store


@pytest.fixture
def no_repo(monkeypatch):
    monkeypatch.setattr("bugcap.repo.load_repo_config", lambda *a, **k: None)


def _scope_to(monkeypatch, key, github=None):
    class Cfg:
        pass

    cfg = Cfg()
    cfg.key = key
    cfg.github = github or key
    monkeypatch.setattr("bugcap.repo.load_repo_config", lambda *a, **k: cfg)


def test_list_reports_scoping_all_status_limit(bugcap_home, monkeypatch):
    with Store() as store:
        store.add("in repo A", repo="o/r", status="open")
        store.add("in repo A2", repo="o/r", status="resolved")
        store.add("other repo", repo="x/y", status="open")

        _scope_to(monkeypatch, "o/r")
        scoped = agent_api.list_reports(store)
        assert {r["title"] for r in scoped} == {"in repo A", "in repo A2"}

        all_reports = agent_api.list_reports(store, all=True)
        assert len(all_reports) == 3

        open_only = agent_api.list_reports(store, all=True, status="open")
        assert {r["title"] for r in open_only} == {"in repo A", "other repo"}

        limited = agent_api.list_reports(store, all=True, limit=1)
        assert len(limited) == 1


def test_get_report_includes_image_bytes_and_errors(bugcap_home, tmp_path, no_repo):
    img = tmp_path / "s.png"
    img.write_bytes(b"IMGBYTES")
    with Store() as store:
        rep = store.add("Bug", notes="n", image_paths=[str(img)], repo="o/r")
        out = agent_api.get_report(store, rep.id)
        assert out["report"]["id"] == rep.id
        assert out["report"]["notes"] == "n"
        assert out["images"][0]["bytes"] == b"IMGBYTES"
        assert out["images"][0]["mime"] == "image/png"

        assert "error" in agent_api.get_report(store, 999)


def test_request_screenshot_non_interactive(bugcap_home, monkeypatch, no_repo):
    monkeypatch.setattr(capture, "has_display", lambda: False)
    with Store() as store:
        rep = store.add("Bug")
        out = agent_api.request_screenshot(store, report_id=rep.id)
    assert out["status"] == "non_interactive"


def test_request_screenshot_captured(bugcap_home, monkeypatch, tmp_path, no_repo):
    shot = tmp_path / "cap.png"
    shot.write_bytes(b"CAP")
    monkeypatch.setattr(capture, "has_display", lambda: True)
    monkeypatch.setattr(capture, "capture_screenshot", lambda: shot)
    with Store() as store:
        rep = store.add("Bug")
        out = agent_api.request_screenshot(store, report_id=rep.id, message="please snap")
        assert out["status"] == "captured"
        assert out["report_id"] == rep.id
        assert out["image"]["bytes"] == b"CAP"
        assert store.get(rep.id).image_paths == [str(shot)]


def test_request_screenshot_creates_report_from_issue(bugcap_home, monkeypatch, tmp_path):
    _scope_to(monkeypatch, "o/r", github="o/r")
    shot = tmp_path / "cap.png"
    shot.write_bytes(b"CAP")
    monkeypatch.setattr(capture, "has_display", lambda: True)
    monkeypatch.setattr(capture, "capture_screenshot", lambda: shot)
    with Store() as store:
        out = agent_api.request_screenshot(store, issue="o/r#3")
        assert out["status"] == "captured"
        rep = store.find_by_ref("github.issue", "o/r#3")
        assert rep is not None
        assert rep.image_paths == [str(shot)]


def test_request_screenshot_cancelled(bugcap_home, monkeypatch, no_repo):
    monkeypatch.setattr(capture, "has_display", lambda: True)

    def boom():
        raise CaptureError("user cancelled")

    monkeypatch.setattr(capture, "capture_screenshot", boom)
    with Store() as store:
        rep = store.add("Bug")
        out = agent_api.request_screenshot(store, report_id=rep.id)
    assert out["status"] == "cancelled"
    assert "cancelled" in out["message"]


def test_pull_issues_summary(bugcap_home, fake_gh, no_repo):
    issues = [{"number": 1, "title": "A", "body": "b", "url": "u", "state": "OPEN", "labels": []}]
    fake_gh.on("issue", "list", stdout=json.dumps(issues))
    with Store() as store:
        out = agent_api.pull_issues(store, repo="o/r")
    assert out == {"created": 1, "updated": 0, "unchanged": 0}


def test_pull_issues_without_repo_errors(bugcap_home, no_repo):
    with Store() as store:
        out = agent_api.pull_issues(store)
    assert "error" in out
