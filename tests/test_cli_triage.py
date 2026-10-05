"""T022: `bugcap edit` and `bugcap tag`."""

from bugcap import cli
from bugcap.store import Store


def _one(bugcap_home):
    with Store() as store:
        return store.add("Title", notes="n", tags=["a"]).id


def test_edit_changes_only_supplied_fields(bugcap_home, capsys):
    rid = _one(bugcap_home)
    assert cli.main(["edit", str(rid), "--status", "resolved"]) == 0
    with Store() as store:
        r = store.get(rid)
        assert r.status == "resolved"
        assert r.title == "Title"  # untouched
        assert r.notes == "n"      # untouched


def test_edit_no_flags_is_usage_error(bugcap_home):
    rid = _one(bugcap_home)
    assert cli.main(["edit", str(rid)]) == 2


def test_edit_invalid_status_rejected_with_allowed_set(bugcap_home, capsys):
    rid = _one(bugcap_home)
    assert cli.main(["edit", str(rid), "--status", "bogus"]) == 2
    err = capsys.readouterr().err
    assert "open" in err and "resolved" in err  # allowed set listed


def test_edit_empty_title_rejected(bugcap_home):
    rid = _one(bugcap_home)
    assert cli.main(["edit", str(rid), "--title", "   "]) == 2


def test_edit_unknown_id(bugcap_home, capsys):
    assert cli.main(["edit", "999", "--status", "open"]) == 1
    assert "no report with id 999" in capsys.readouterr().err


def test_tag_add_idempotent_and_remove(bugcap_home, capsys):
    rid = _one(bugcap_home)
    assert cli.main(["tag", str(rid), "add", "ui"]) == 0
    assert cli.main(["tag", str(rid), "add", "ui"]) == 0  # idempotent
    with Store() as store:
        assert store.get(rid).tags == ["a", "ui"]
    out = capsys.readouterr().out
    assert "unchanged" in out  # second add reported as no change

    assert cli.main(["tag", str(rid), "remove", "ui"]) == 0
    assert cli.main(["tag", str(rid), "remove", "ui"]) == 0  # harmless
    with Store() as store:
        assert store.get(rid).tags == ["a"]


def test_tag_unknown_id(bugcap_home, capsys):
    assert cli.main(["tag", "999", "add", "x"]) == 1
    assert "no report with id 999" in capsys.readouterr().err
