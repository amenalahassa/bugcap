from pathlib import Path

import pytest
from fixtures.make_images import gif_bytes, jpeg_bytes, png_bytes, webp_bytes

from bugcap import ingest
from bugcap.errors import ServiceError


def test_classify_sources(tmp_path):
    assert ingest.classify_source("https://x.test/a.png") == "url"
    assert ingest.classify_source("HTTP://x.test/a.png") == "url"
    assert ingest.classify_source("./shots/*.png") == "glob"
    assert ingest.classify_source("shot.png") == "path"
    assert ingest.classify_source("ftp://x/a.png") == "path"  # not a URL we fetch; fails as a path
    existing = tmp_path / "we[ird].png"
    existing.write_bytes(png_bytes())
    assert ingest.classify_source(str(existing)) == "path"  # literal file wins over glob chars


@pytest.mark.parametrize("data,mime", [
    (png_bytes(), "image/png"), (jpeg_bytes(), "image/jpeg"),
    (gif_bytes(), "image/gif"), (webp_bytes(), "image/webp"),
])
def test_sniff_accepts_each_format(data, mime):
    assert ingest.sniff_image(data) == mime


def test_sniff_rejects_truncated_and_html():
    for data in (png_bytes()[:8], b"<html>hi</html>", b"", b"GIF8"):
        with pytest.raises(ServiceError) as exc:
            ingest.sniff_image(data)
        assert exc.value.code == "invalid_image"


def test_extension_is_irrelevant(bugcap_home, tmp_path):
    txt = tmp_path / "shot.txt"
    txt.write_bytes(png_bytes())
    stored = ingest.import_local(txt)
    assert stored.mime == "image/png" and stored.abs_path.suffix == ".png"

    fake = tmp_path / "fake.png"
    fake.write_text("<html></html>")
    with pytest.raises(ServiceError) as exc:
        ingest.import_local(fake)
    assert exc.value.code == "invalid_image"


def test_import_copies_into_store(bugcap_home, sample_images):
    stored = ingest.import_local(sample_images / "sample.png")
    assert stored.path.startswith("images/")
    assert stored.abs_path.read_bytes() == png_bytes()
    assert stored.source.endswith("sample.png")
    assert not list(stored.abs_path.parent.glob("*.part"))


def test_glob_sorted_and_no_match(sample_images):
    matches = ingest.resolve_glob(str(sample_images / "sample.*"))
    assert [Path(m).name for m in matches] == ["sample.gif", "sample.jpg", "sample.png", "sample.webp"]
    items = ingest.expand_sources([str(sample_images / "nope-*.png")])
    assert items[0].error.code == "not_found" and "nope-*.png" in items[0].error.message


def test_directory_match_is_skipped_with_reason(bugcap_home, sample_images):
    (sample_images / "sub.png").mkdir()
    result = ingest.ingest_sources([str(sample_images / "*.png")])
    assert len(result.added) == 1
    assert [r["reason"] for r in result.rejected] == ["is a directory"]


def test_partial_batch(bugcap_home, sample_images):
    result = ingest.ingest_sources([str(sample_images / "sample.png"), str(sample_images / "not-image.txt"), "/missing.png"])
    assert len(result.added) == 1
    assert {r["code"] for r in result.rejected} == {"invalid_image", "not_found"}


def test_label_on_multi_match_glob_rejected(sample_images):
    items = ingest.expand_sources([str(sample_images / "sample.*")], ["x"])
    assert len(items) == 1 and items[0].error.code == "invalid_label"
