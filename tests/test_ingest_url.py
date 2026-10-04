import pytest

from bugcap import ingest
from bugcap.errors import ServiceError


def test_download_ok(bugcap_home, http_server):
    stored = ingest.download_url(http_server.url("/ok.png"))
    assert stored.mime == "image/png" and stored.abs_path.is_file()
    assert stored.source.endswith("/ok.png")


def test_follows_redirect(bugcap_home, http_server):
    assert ingest.download_url(http_server.url("/redirect-ok")).mime == "image/png"


def test_html_rejected_with_content_type_hint(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/page.html"))
    assert exc.value.code == "invalid_image" and "text/html" in exc.value.message


def test_too_large(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/big.png"), max_bytes=1024 * 1024)
    assert exc.value.code == "too_large"
    assert not list((bugcap_home / "data" / "images").glob("*"))  # nothing stored


def test_timeout(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/slow"), timeout=0.3)
    assert exc.value.code == "timeout"


def test_redirect_to_file_refused(bugcap_home, http_server):
    with pytest.raises(ServiceError):
        ingest.download_url(http_server.url("/redirect-file"))


def test_redirect_loop_stops(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/redirect-loop"))
    assert "redirect" in exc.value.message
    assert len(http_server.requests) <= 6


@pytest.mark.parametrize("url", ["ftp://x.test/a.png", "file:///etc/passwd"])
def test_non_http_scheme_rejected_before_any_request(bugcap_home, http_server, url):
    with pytest.raises(ServiceError):
        ingest.download_url(url)
    assert http_server.requests == []


def test_no_credentials_sent(bugcap_home, http_server):
    ingest.download_url(http_server.url("/ok.png"))
    _, headers = http_server.requests[0]
    assert "authorization" not in headers and "cookie" not in headers
    assert headers["user-agent"] == "bugcap"


def test_404_is_a_rejection(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/nothing"))
    assert "404" in exc.value.message


def test_text_content_type_rejected_before_body_is_read(bugcap_home, http_server):
    with pytest.raises(ServiceError) as exc:
        ingest.download_url(http_server.url("/page.html"), max_bytes=1)  # would be too_large if read
    assert exc.value.code == "invalid_image" and "text/html" in exc.value.message


def test_clearly_not_image_rule():
    for ct in ("text/plain", "text/html", "application/json", "application/xhtml+xml"):
        assert ingest._clearly_not_image(ct)
    for ct in ("", "image/png", "application/octet-stream", "binary/octet-stream"):
        assert not ingest._clearly_not_image(ct)
