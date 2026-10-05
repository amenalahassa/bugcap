"""Note references: `@i1` image, `@v2` video, `@g3` GIF, `@f4` frames, `@label`, the older `@1`
(media 1, any kind), `@@`, and `#N` for reports. Reserved labels keep the forms unambiguous."""
import pytest

from bugcap import refs, service
from bugcap.errors import ServiceError
from bugcap.store import Media

KINDS = ["image", "video", "animated", "frames"]


def m(idx, kind="image", label=None):
    return Media(idx, 1, idx, label, kind, "p", "x", 1, None, "")


MEDIA = [m(1, "image"), m(2, "video"), m(3, "animated"), m(4, "frames", "login")]


def test_media_token_uses_kind_letter():
    assert [refs.media_token(x) for x in MEDIA] == ["@i1", "@v2", "@g3", "@f4"]
    assert refs.valid_tokens(MEDIA) == ["@i1", "@v2", "@g3", "@f4", "@login"]


@pytest.mark.parametrize("token, idx", [("@i1", 1), ("@v2", 2), ("@g3", 3), ("@f4", 4), ("@I1", 1), ("@V2", 2)])
def test_kind_letter_resolves_to_matching_media(token, idx):
    ref = refs.parse_references(f"see {token}")[0]
    assert ref.kind == "index"
    assert refs.resolve(ref, MEDIA).idx == idx


@pytest.mark.parametrize("token, idx", [("@1", 1), ("@2", 2), ("@3", 3)])
def test_legacy_number_still_resolves_any_kind(token, idx):
    ref = refs.parse_references(token)[0]
    assert refs.resolve(ref, MEDIA).idx == idx


@pytest.mark.parametrize("token", ["@i2", "@v1", "@g4", "@f2"])
def test_wrong_kind_letter_does_not_resolve(token):
    ref = refs.parse_references(token)[0]
    assert refs.resolve(ref, MEDIA) is None


def test_validate_error_lists_canonical_tokens():
    with pytest.raises(ServiceError) as exc:
        refs.validate_references("bad @i9", MEDIA)
    assert exc.value.details["valid"] == ["@i1", "@v2", "@g3", "@f4", "@login"]


def test_rewrite_by_number_covers_every_form():
    # item numbers are unique per report, so the number alone identifies the item being removed
    out = refs.rewrite_references("@v2 and @2 and @i2, not @@2", {"2": "[image removed]"})
    assert out == "[image removed] and [image removed] and [image removed], not @@2"


@pytest.mark.parametrize("label", ["i1", "v2", "g3", "f4", "I7", "i0", "V0", "1"])
def test_labels_that_look_like_media_numbers_are_reserved(label):
    with pytest.raises(ServiceError) as exc:
        service.validate_label(label)
    assert exc.value.code == "invalid_label"


def test_ordinary_labels_still_allowed():
    assert service.validate_label("login-error") == "login-error"
    assert service.validate_label("video-bug") == "video-bug"


def test_find_media_by_letter_and_legacy_number():
    assert service.find_media(MEDIA, "v2").idx == 2
    assert service.find_media(MEDIA, "@G3").idx == 3
    assert service.find_media(MEDIA, "2").idx == 2
    assert service.find_media(MEDIA, "login").idx == 4
    with pytest.raises(ServiceError):
        service.find_media(MEDIA, "i2")  # media 2 is a video, not an image


def test_report_refs_found_only_in_prose():
    notes = "dup of #3, see (#12). a#4 and `#5` are not refs; #1x is not either.\n# Heading\n#7"
    assert refs.report_refs(notes) == [3, 12, 7]


def test_substitute_reports_keeps_unknown_refs():
    assert refs.substitute_reports("see #3 and a#4", {3: "#42"}) == "see #42 and a#4"
