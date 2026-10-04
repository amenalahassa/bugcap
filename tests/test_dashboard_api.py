import pytest

from bugcap import service
from bugcap.store import Store


@pytest.fixture
def seeded(bugcap_home, sample_images):
    with Store() as s:
        a, _ = service.create_report(s, "Login crash", notes="Stack in Auth module", tags=["auth", "p1"],
                                     repo="proj", sources=[str(sample_images / "sample.png")], labels=["shot"])
        s.add("Slow search", notes="timeout on LOGIN page", tags=["auth"], repo="proj", status="resolved")
        s.add("Typo", tags=["ui"], repo="other")
    return a.id


def test_session_token(dashboard):
    status, body = dashboard.json("GET", "/api/session")
    assert status == 200 and body["token"] == dashboard.token


def test_list_filters(dashboard, seeded):
    j = lambda path: dashboard.json("GET", path)[1]
    assert j("/api/reports")["total"] == 3
    assert [i["title"] for i in j("/api/reports?repo=other")["items"]] == ["Typo"]
    assert j("/api/reports?tag=auth&tag=p1")["total"] == 1  # AND semantics
    assert j("/api/reports?tag=auth")["total"] == 2
    assert j("/api/reports?status=resolved")["items"][0]["title"] == "Slow search"
    assert j("/api/reports?q=login")["total"] == 2  # title and notes, case-insensitive
    page = j("/api/reports?limit=1&offset=1")
    assert page["total"] == 3 and len(page["items"]) == 1
    assert j("/api/reports")["items"][2]["media_count"] == 1


@pytest.mark.parametrize("query", ["status=nope", "limit=0", "limit=5000", "offset=-1", "limit=abc"])
def test_bad_queries(dashboard, query):
    status, body = dashboard.json("GET", "/api/reports?" + query)
    assert status == 400 and body["code"] == "bad_query"


def test_report_detail_segments_and_media(dashboard, seeded):
    with Store() as s:
        service.set_notes(s, seeded, "See @1 and @@1 or @shot")
    status, body = dashboard.json("GET", f"/api/reports/{seeded}")
    assert status == 200
    media = body["media"][0]
    assert media["url"] == f"/media/{media['id']}" and media["label"] == "shot"
    seg = body["notes_segments"]
    assert seg[0] == {"text": "See "}
    assert seg[1]["ref"] == {"token": "@1", "index": 1, "media_id": media["id"], "kind": "image"}
    assert seg[2] == {"text": " and @1 or "}
    assert seg[3]["ref"]["token"] == "@shot"
    assert body["notes_raw"] == "See @1 and @@1 or @shot"


def test_unknown_report_and_route(dashboard):
    assert dashboard.json("GET", "/api/reports/99")[0] == 404
    assert dashboard.json("GET", "/api/nothing")[0] == 404


def test_static_ui_served(dashboard):
    status, headers, body = dashboard.call("GET", "/")
    assert status == 200 and b"/static/app.js" in body and "text/html" in headers["content-type"]
    assert dashboard.call("GET", "/static/app.js")[0] == 200
    assert dashboard.call("GET", "/static/app.css")[0] == 200
    assert "'self'" in headers["content-security-policy"] and headers["x-content-type-options"] == "nosniff"


def test_ui_has_no_external_urls_or_innerhtml():
    from importlib import resources

    base = resources.files("bugcap.dashboard") / "static"
    for name in ("index.html", "app.js", "app.css"):
        text = (base / name).read_text()
        assert "http://" not in text.replace("http://www.w3.org", "") and "https://" not in text
        assert "innerHTML" not in text


def test_filtering_500_reports_is_fast(bugcap_home):
    import time

    with Store() as s:
        for n in range(500):
            s.add(f"bug {n}", notes="needle" if n % 50 == 0 else "hay", tags=["auth"] if n % 2 else ["ui"],
                  repo="proj" if n % 3 else "other")
        start = time.monotonic()
        total, items = service.list_reports_query(s, repo="proj", tags=["auth"], q="needle")
        elapsed = time.monotonic() - start
    assert total == len([n for n in range(500) if n % 50 == 0 and n % 2 and n % 3])
    assert elapsed < 5


def test_github_issue_exposed_as_link(dashboard, bugcap_home):
    with Store() as s:
        rid = s.add("t", synced_refs={"github.issue": "owner/repo#12"}).id
        plain = s.add("u", synced_refs={"github.issue": "weird"}).id
    body = dashboard.json("GET", f"/api/reports/{rid}")[1]
    assert body["links"] == [{"label": "GitHub issue owner/repo#12", "url": "https://github.com/owner/repo/issues/12"}]
    assert dashboard.json("GET", f"/api/reports/{plain}")[1]["links"] == []
