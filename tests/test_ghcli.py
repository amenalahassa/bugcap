"""T024: gh wrapper readiness, argv hygiene, issue list parsing, visibility fallback."""
import json

import pytest

from bugcap import ghcli
from bugcap.ghcli import GhError


def test_ensure_ready_missing_gh(fake_gh):
    fake_gh.present = set()  # gh not on PATH
    with pytest.raises(GhError, match="not found"):
        ghcli.ensure_ready()


def test_ensure_ready_unauthenticated(fake_gh):
    fake_gh.on("auth", "status", returncode=1, stderr="not logged in")
    with pytest.raises(GhError, match="gh auth login"):
        ghcli.ensure_ready()


def test_ensure_ready_ok(fake_gh):
    fake_gh.on("auth", "status", returncode=0)
    ghcli.ensure_ready()  # no raise


def test_calls_are_argv_lists(fake_gh):
    fake_gh.on("issue", "list", stdout="[]")
    ghcli.list_issues("o/r", limit=5)
    assert fake_gh.calls, "gh should have been invoked"
    argv = fake_gh.calls[0].argv
    assert isinstance(argv, list)
    assert argv[0] == "gh"
    assert "--repo" in argv and "o/r" in argv


def test_list_issues_parses_json(fake_gh):
    issues = [
        {"number": 1, "title": "A", "body": "b", "url": "u", "state": "OPEN", "labels": []},
        {"number": 2, "title": "B", "body": "", "url": "u2", "state": "OPEN", "labels": []},
    ]
    fake_gh.on("issue", "list", stdout=json.dumps(issues))
    out = ghcli.list_issues("o/r", labels=["bug"], limit=10)
    assert [i["number"] for i in out] == [1, 2]
    argv = fake_gh.calls[0].argv
    assert "--label" in argv and "bug" in argv
    assert argv[argv.index("--limit") + 1] == "10"


def test_repo_visibility_failure_is_public(fake_gh):
    fake_gh.on("repo", "view", returncode=1, stderr="boom")
    assert ghcli.repo_visibility("o/r") == "public"


def test_repo_visibility_private(fake_gh):
    fake_gh.on("repo", "view", stdout=json.dumps({"visibility": "PRIVATE"}))
    assert ghcli.repo_visibility("o/r") == "private"


def test_create_issue_parses_url(fake_gh):
    fake_gh.on("issue", "create", stdout="https://github.com/o/r/issues/7\n")
    url = ghcli.create_issue("o/r", "title", "body")
    assert url == "https://github.com/o/r/issues/7"
    # body goes via stdin, not argv
    call = fake_gh.calls[0]
    assert call.stdin == "body"
    assert "--body-file" in call.argv and "-" in call.argv


def test_put_contents_sends_payload_on_stdin(fake_gh):
    fake_gh.on("api", stdout=json.dumps({"commit": {"sha": "abc"}}))
    ghcli.put_contents("o/r", "dir/x.png", "QkFTRTY0", "msg", branch="main")
    call = fake_gh.calls[0]
    assert "--input" in call.argv and "-" in call.argv
    payload = json.loads(call.stdin)
    assert payload["content"] == "QkFTRTY0"
    assert payload["branch"] == "main"
