import pytest

from bugcap import service
from bugcap.store import Store


@pytest.fixture
def rid(bugcap_home, sample_images):
    with Store() as s:
        report, _ = service.create_report(s, "t", sources=[str(sample_images / "sample.png")])
    return report.id


def test_status(dashboard, rid):
    status, body = dashboard.json("POST", f"/api/reports/{rid}/status", {"status": "resolved"})
    assert status == 200 and body["status"] == "resolved"
    with Store() as s:
        assert s.get(rid).status == "resolved"


def test_invalid_status(dashboard, rid):
    status, body = dashboard.json("POST", f"/api/reports/{rid}/status", {"status": "bogus"})
    assert status == 400 and body["code"] == "invalid_status"


def test_tags_add_remove(dashboard, rid):
    assert dashboard.json("POST", f"/api/reports/{rid}/tags", {"add": ["a", "b"]})[1]["tags"] == ["a", "b"]
    assert dashboard.json("POST", f"/api/reports/{rid}/tags", {"remove": ["a"]})[1]["tags"] == ["b"]
    assert dashboard.json("POST", f"/api/reports/{rid}/tags", {"add": "x"})[0] == 400


def test_notes_ok_and_invalid_reference(dashboard, rid):
    status, body = dashboard.json("PUT", f"/api/reports/{rid}/notes", {"notes": "see @1"})
    assert status == 200 and body["notes_raw"] == "see @1"
    status, body = dashboard.json("PUT", f"/api/reports/{rid}/notes", {"notes": "see @3"})
    assert status == 422 and body["code"] == "invalid_reference"
    assert body["token"] == "@3" and body["valid"] == ["@i1"]
    with Store() as s:
        assert s.get(rid).notes == "see @1"


def test_unknown_report_and_bad_body(dashboard, rid):
    assert dashboard.json("POST", "/api/reports/99/status", {"status": "open"})[0] == 404
    assert dashboard.json("PUT", f"/api/reports/{rid}/notes", {"notes": 5})[0] == 400
    assert dashboard.json("PUT", f"/api/reports/{rid}/notes", None)[0] == 400
