"""Live mode's keyboard shortcuts: one table that drives the Tk bindings, the hints on the
buttons and the F1 help, so they cannot drift apart. Keys work only while a bugcap window
has focus (no global hotkeys). The control window has no text fields, so it uses single
keys; the forms use modifiers so typing is never taken over."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .recorder import platform_key

SCOPES = {"control": "Control window", "form": "New bug form", "attach": "Add to existing bug",
          "chooser": "Capture what?", "global": "Everywhere"}


@dataclass(frozen=True)
class Shortcut:
    scope: str
    action: str
    key: str  # "s" (single key), "Delete", "Escape", "{mod}-Return", "Alt-d"
    description: str


SHORTCUTS = [
    Shortcut("control", "screenshot", "s", "Screenshot"),
    Shortcut("control", "record", "r", "Record / Stop"),
    Shortcut("control", "upload_image", "i", "Upload image"),
    Shortcut("control", "attach_file", "f", "Attach file"),
    Shortcut("control", "new_bug", "n", "New bug"),
    Shortcut("control", "add_existing", "e", "Add to existing bug"),
    Shortcut("control", "clear", "Delete", "Clear everything staged"),
    Shortcut("form", "save", "{mod}-Return", "Save"),
    Shortcut("form", "back", "Escape", "Back (keeps what you typed)"),
    Shortcut("form", "discard", "Alt-d", "Discard"),
    Shortcut("form", "remove_item", "Alt-x", "Remove the selected item"),
    Shortcut("form", "open_item", "Alt-o", "Open the selected item"),
    Shortcut("form", "prev_item", "Left", "Select the previous item (on the item strip)"),
    Shortcut("form", "next_item", "Right", "Select the next item (on the item strip)"),
    Shortcut("attach", "add", "{mod}-Return", "Add"),
    Shortcut("attach", "cancel", "Escape", "Cancel"),
    Shortcut("attach", "focus_bug", "Alt-b", "Choose the bug"),
    Shortcut("chooser", "confirm", "Return", "Capture the selected target"),
    Shortcut("chooser", "cancel", "Escape", "Cancel"),
    Shortcut("global", "help", "F1", "Show or hide this list"),
]

_NAMES = {"Return": "Enter", "Escape": "Esc", "Delete": "Del", "Left": "←", "Right": "→"}


def _mac(platform: Optional[str]) -> bool:
    return platform_key(platform) == "macos"


def sequences(shortcut: Shortcut, platform: Optional[str] = None) -> list[str]:
    """Tk event sequences for this OS. A letter binds both cases (Caps Lock, Shift)."""
    key = shortcut.key.replace("{mod}", "Command" if _mac(platform) else "Control")
    if _mac(platform):
        key = key.replace("Alt-", "Option-")
    if len(key) == 1:
        return [f"<Key-{key.lower()}>", f"<Key-{key.upper()}>"]
    if "-" in key and len(key.rsplit("-", 1)[1]) == 1:
        mod, letter = key.rsplit("-", 1)
        mods = [mod, f"Command-{mod}"] if mod == "Option" else [mod]  # Option+letter alone types a character
        return [f"<{m}-{c}>" for m in mods for c in (letter.lower(), letter.upper())]
    return [f"<{key}>"]


def action_for_keycode(scope: str, keycode: int, platform: Optional[str] = None) -> Optional[str]:
    """Windows only: the single-letter shortcut of `scope` on this physical key. On a
    non-Latin layout (Cyrillic, Greek, ...) the key sends another character, but Windows
    still reports the virtual key code, which is the Latin capital letter's code."""
    if platform_key(platform) != "windows":
        return None
    for s in SHORTCUTS:
        if s.scope == scope and len(s.key) == 1 and ord(s.key.upper()) == keycode:
            return s.action
    return None


def label(shortcut: Shortcut, platform: Optional[str] = None) -> str:
    """How the key is written on a button and in the help: "S", "Ctrl+Enter", "⌘+Enter"."""
    parts = shortcut.key.split("-")
    out = []
    for part in parts:
        if part == "{mod}":
            out.append("⌘" if _mac(platform) else "Ctrl")
        elif part == "Alt":
            out.append("Option" if _mac(platform) else "Alt")
        else:
            out.append(_NAMES.get(part, part.upper() if len(part) == 1 else part))
    return "+".join(out)


def label_for(scope: str, action: str, platform: Optional[str] = None) -> str:
    found = next((s for s in SHORTCUTS if s.scope == scope and s.action == action), None)
    return label(found, platform) if found else ""


def help_lines(platform: Optional[str] = None) -> list[str]:
    """The F1 overlay: a heading per scope, then "key  description" lines."""
    lines: list[str] = []
    for scope, title in SCOPES.items():
        if lines:
            lines.append("")
        lines.append(title)
        lines += [f"  {label(s, platform):<12} {s.description}" for s in SHORTCUTS if s.scope == scope]
    if platform_key(platform) == "windows":
        lines += ["", "On a non-Latin keyboard layout the letter keys work by position (as on a US layout)."]
    return lines
