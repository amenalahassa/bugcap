"""shortcuts: the one table that drives live mode's key bindings, button labels and F1 help."""
import pytest

from bugcap import shortcuts

FR_020 = {
    "control": {"screenshot", "record", "upload_image", "attach_file", "clear", "new_bug", "add_existing"},
    "form": {"save", "back", "discard", "remove_item", "open_item", "prev_item", "next_item"},
    "attach": {"add", "cancel", "focus_bug"},
    "chooser": {"confirm", "cancel"},
    "global": {"help"},
}


def test_every_required_action_once_per_scope():
    for scope, actions in FR_020.items():
        found = [s.action for s in shortcuts.SHORTCUTS if s.scope == scope]
        assert sorted(found) == sorted(actions), scope


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_no_key_bound_twice_in_a_scope(platform):
    for scope in FR_020:
        seqs = [seq for s in shortcuts.SHORTCUTS if s.scope == scope for seq in shortcuts.sequences(s, platform)]
        assert len(seqs) == len(set(seqs)), scope


def test_text_windows_never_take_a_plain_printable_key():
    for s in shortcuts.SHORTCUTS:
        if s.scope in ("form", "attach"):
            for seq in shortcuts.sequences(s, "win32"):
                inner = seq.strip("<>")
                assert "-" in inner or inner in ("Escape", "Left", "Right"), seq


def test_control_letters_bind_both_cases():
    shot = next(s for s in shortcuts.SHORTCUTS if s.action == "screenshot")
    assert shortcuts.sequences(shot, "win32") == ["<Key-s>", "<Key-S>"]


def test_modifier_rendering_per_os():
    save = next(s for s in shortcuts.SHORTCUTS if s.action == "save")
    assert shortcuts.sequences(save, "win32") == ["<Control-Return>"]
    assert shortcuts.sequences(save, "darwin") == ["<Command-Return>"]
    assert shortcuts.label(save, "linux") == "Ctrl+Enter"
    assert shortcuts.label(save, "darwin") == "⌘+Enter"
    discard = next(s for s in shortcuts.SHORTCUTS if s.action == "discard")
    assert shortcuts.sequences(discard, "win32") == ["<Alt-d>", "<Alt-D>"]
    assert shortcuts.sequences(discard, "darwin") == [
        "<Option-d>", "<Option-D>", "<Command-Option-d>", "<Command-Option-D>"]
    assert shortcuts.label(discard, "win32") == "Alt+D" and shortcuts.label(discard, "darwin") == "Option+D"


def test_help_lists_everything_grouped():
    lines = shortcuts.help_lines("win32")
    assert lines[0] == "Control window"
    text = "\n".join(lines)
    for s in shortcuts.SHORTCUTS:
        assert shortcuts.label(s, "win32") in text and s.description in text


def test_key_for_lookup():
    assert shortcuts.label_for("form", "save", "win32") == "Ctrl+Enter"
    assert shortcuts.label_for("control", "nope", "win32") == ""


def test_macos_option_letters_also_bind_with_command():
    discard = next(s for s in shortcuts.SHORTCUTS if s.action == "discard")
    seqs = shortcuts.sequences(discard, "darwin")
    assert "<Command-Option-d>" in seqs and "<Option-d>" in seqs


def test_letters_by_key_position_on_windows():
    """On a non-Latin layout the letter keys send other characters; Windows still reports the
    virtual key code, which is the Latin capital letter's code."""
    assert shortcuts.action_for_keycode("control", ord("S"), "win32") == "screenshot"
    assert shortcuts.action_for_keycode("control", ord("Q"), "win32") is None
    assert shortcuts.action_for_keycode("control", ord("S"), "linux") is None
    assert any("position" in line for line in shortcuts.help_lines("win32"))
