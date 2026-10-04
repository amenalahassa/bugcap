import pytest

from bugcap.paths import media_dir
from bugcap.store import Store

DATA = bytes(range(256)) * 2  # 512 bytes


@pytest.fixture
def media(bugcap_home):
    path = media_dir() / "clip.mp4"
    path.write_bytes(DATA)
    frames = []
    for n in (1, 2):
        f = media_dir() / f"fr{n}.png"
        f.write_bytes(bytes([n]) * 5)
        frames.append((str(f), 5))
    with Store() as s:
        rid = s.add("t").id
        video = s.insert_media(rid, kind="video", path=str(path), mime="video/mp4", source="recorded")
        fr = s.insert_media(rid, kind="frames", path=None, mime="image/png", size_bytes=10, frames=frames)
    return video.id, fr.id


def test_full_response(dashboard, media):
    status, headers, body = dashboard.call("GET", f"/media/{media[0]}")
    assert status == 200 and body == DATA
    assert headers["content-type"] == "video/mp4" and headers["accept-ranges"] == "bytes"
    assert headers["cache-control"] == "private, max-age=3600"


@pytest.mark.parametrize("rng,expected,crange", [
    ("bytes=0-99", DATA[0:100], "bytes 0-99/512"),
    ("bytes=100-", DATA[100:], "bytes 100-511/512"),
    ("bytes=-50", DATA[-50:], "bytes 462-511/512"),
    ("bytes=500-9999", DATA[500:], "bytes 500-511/512"),
])
def test_ranges(dashboard, media, rng, expected, crange):
    status, headers, body = dashboard.call("GET", f"/media/{media[0]}", headers={"Range": rng})
    assert status == 206 and body == expected and headers["content-range"] == crange


@pytest.mark.parametrize("rng", ["bytes=512-", "bytes=600-700", "bytes=-0"])
def test_unsatisfiable_range(dashboard, media, rng):
    status, headers, _ = dashboard.call("GET", f"/media/{media[0]}", headers={"Range": rng})
    assert status == 416 and headers["content-range"] == "bytes */512"


def test_garbage_range_serves_full(dashboard, media):
    status, _, body = dashboard.call("GET", f"/media/{media[0]}", headers={"Range": "nonsense"})
    assert status == 200 and body == DATA


def test_frames(dashboard, media):
    fid = media[1]
    status, headers, body = dashboard.call("GET", f"/media/{fid}/frames/2")
    assert status == 200 and body == bytes([2]) * 5 and headers["content-type"] == "image/png"
    assert dashboard.call("GET", f"/media/{fid}/frames/9")[0] == 404
    assert dashboard.call("GET", f"/media/{fid}")[0] == 404  # a frames item has no single file


def test_unknown_media(dashboard):
    assert dashboard.call("GET", "/media/999")[0] == 404
