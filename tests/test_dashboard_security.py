import builtins
import os

import pytest

from bugcap import service
from bugcap.store import Store


@pytest.fixture
def rid(bugcap_home, sample_images):
    with Store() as s:
        report, _ = service.create_report(s, "t", sources=[str(sample_images / "sample.png")])
    return report.id


def _media_id(rid):
    with Store() as s:
        return s.get(rid).media[0].id


@pytest.mark.parametrize("evil", ["../../etc/passwd", "/etc/passwd", "images/../../outside"])
def test_tampered_media_path_is_404_and_never_opened(dashboard, rid, monkeypatch, evil):
    mid = _media_id(rid)
    with Store() as s:
        s._conn.execute("UPDATE media SET path = ? WHERE id = ?", (evil, mid))
        s._conn.commit()
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
    status, _, _ = dashboard.call("GET", f"/media/{mid}")
    monkeypatch.setattr(builtins, "open", real_open)
    assert status == 404


def test_symlink_escaping_images_dir_refused(dashboard, rid, tmp_path, bugcap_home):
    from bugcap.paths import images_dir

    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    link = images_dir() / "link.png"
    os.symlink(outside, link)
    mid = _media_id(rid)
    with Store() as s:
        s._conn.execute("UPDATE media SET path = 'images/link.png' WHERE id = ?", (mid,))
        s._conn.commit()
    assert dashboard.call("GET", f"/media/{mid}")[0] == 404


def test_media_takes_no_path_segment(dashboard, rid):
    assert dashboard.call("GET", "/media/../x")[0] == 404
    assert dashboard.call("GET", "/media/1/../../etc/passwd")[0] == 404
    assert dashboard.call("GET", "/media/abc")[0] == 404


def test_write_requires_token(dashboard, rid):
    path = f"/api/reports/{rid}/status"
    status, _, body = dashboard.call("POST", path, {"status": "closed"}, token=False)
    assert status == 403 and b"bad_token" in body
    status, _, _ = dashboard.call("POST", path, {"status": "closed"}, token=False, headers={"X-Bugcap-Token": "wrong"})
    assert status == 403
    assert dashboard.call("POST", path, {"status": "closed"})[0] == 200


def test_foreign_origin_refused_even_with_token(dashboard, rid):
    path = f"/api/reports/{rid}/status"
    status, _, _ = dashboard.call("POST", path, {"status": "closed"}, headers={"Origin": "https://evil.example"})
    assert status == 403
    ok = dashboard.call("POST", path, {"status": "closed"}, headers={"Origin": f"http://127.0.0.1:{dashboard.port}"})
    assert ok[0] == 200
    assert dashboard.call("GET", "/api/session", headers={"Origin": "https://evil.example"})[0] == 403


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_foreign_host_refused(dashboard, rid, method):
    path = "/api/reports" if method == "GET" else f"/api/reports/{rid}/status"
    status, _, _ = dashboard.call(method, path, {"status": "open"} if method == "POST" else None, host="evil.example")
    assert status == 400


def test_static_allowlist(dashboard):
    assert dashboard.call("GET", "/static/../server.py")[0] == 404
    assert dashboard.call("GET", "/static/server.py")[0] == 404
    assert dashboard.call("GET", "/static/")[0] == 404
    assert dashboard.call("GET", "/static/index.html")[0] == 404


def test_non_loopback_bind_refused_without_explicit_host():
    from bugcap.dashboard.server import make_server

    with pytest.raises(ValueError):
        make_server("0.0.0.0", 0)
    server = make_server("0.0.0.0", 0, explicit_host=True)
    assert server.exposed
    server.server_close()
