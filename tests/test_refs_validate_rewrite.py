import pytest

from bugcap.errors import ServiceError
from bugcap.refs import (
    display_notes, rewrite_references, validate_references,
)
from bugcap.store import Media


def m(idx, label=None, path=None):
    return Media(idx, 1, idx, label, "image", path or f"images/{idx}.png", "image/png", 1, None, "")


def test_validate_names_first_bad_token_and_lists_valid():
    media = [m(1), m(2, "login-error")]
    with pytest.raises(ServiceError) as exc:
        validate_references("ok @1 bad @3 worse @4", media)
    assert exc.value.code == "invalid_reference"
    assert exc.value.message == "unknown reference @3 in notes"
    assert exc.value.details["valid"] == ["@i1", "@i2", "@login-error"]


def test_validate_accepts_escapes_code_and_emails():
    validate_references("@1 @login-error @@9 `@9` dev@example.com", [m(1), m(2, "login-error")])


def test_label_match_is_case_sensitive():
    with pytest.raises(ServiceError):
        validate_references("@Login", [m(1, "login")])


def test_rewrite_renumbers_and_relabels():
    assert rewrite_references("@3 and @login", {"3": "@2", "login": "@sign-in"}) == "@2 and @sign-in"


def test_rewrite_leaves_code_emails_escapes():
    notes = "`@3` a@3.com @@3 @3"
    assert rewrite_references(notes, {"3": "@2"}) == "`@3` a@3.com @@3 @2"


def test_rewrite_removal_text_and_exact_preservation():
    notes = "  keep\ttabs\r\n@1é @1 end  "
    assert rewrite_references(notes, {"1": "[image removed]"}) == "  keep\ttabs\r\n@1é [image removed] end  "


def test_display_resolves_and_unescapes():
    out = display_notes("@1 and @@1 and `@1`", [m(1, path="images/a.png")])
    assert out == "@1 (images/a.png) and @1 and `@1`"
