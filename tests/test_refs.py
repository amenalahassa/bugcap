import pytest

from bugcap.refs import mask, parse_references


def _kinds(notes):
    return [(r.token, r.kind) for r in parse_references(notes)]


def test_index_label_escape():
    assert _kinds("a @1 b @login-error c @@1") == [
        ("@1", "index"), ("@login-error", "label"), ("@@", "escape"),
    ]


def test_email_is_not_a_reference():
    assert _kinds("mail dev@example.com or a.b@c.org") == []


def test_code_span_and_double_backtick_span():
    assert _kinds("`@1` and ``a ` @2 b`` ok") == []
    assert _kinds("`@1` @2") == [("@2", "index")]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_blocks(fence):
    notes = f"before\n{fence}\n@1\n{fence}\nafter @2"
    assert _kinds(notes) == [("@2", "index")]


def test_fence_closed_by_shorter_fence_continues():
    notes = "````\n@1\n```\n@2\n````\n@3"
    assert _kinds(notes) == [("@3", "index")]


def test_unclosed_fence_runs_to_end():
    assert _kinds("```\n@1\n@2") == []


@pytest.mark.parametrize("token", ["@01", "@1x", "@2label", "@-x", "@_x"])
def test_unknown_forms(token):
    assert _kinds(f"see {token} here") == [(token, "unknown")]


def test_bare_at_is_not_a_reference():
    assert _kinds("a @ b") == []
    assert _kinds("@1 at start") == [("@1", "index")]
    assert _kinds("line\n@2") == [("@2", "index")]


def test_trailing_punctuation_ends_the_token():
    assert _kinds("see @1.") == [("@1", "index")]
    assert _kinds("(@shot)") == [("@shot", "label")]


def test_mask_preserves_length_and_newlines():
    notes = "a `b`\n```\nc\n```\nd"
    masked = mask(notes)
    assert len(masked) == len(notes)
    assert masked.count("\n") == notes.count("\n")
    assert "b" not in masked and "c" not in masked and "d" in masked
