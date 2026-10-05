"""References in notes.

`@` points at media, by kind letter and its number in the report: `@i3` image, `@v2` video,
`@g4` animated GIF, `@f5` keyframes. `@login-error` is a media label and `@@` a literal `@`.
The older `@3` form still reads as media 3, so existing notes keep working.

`#N` points at report N (soft: an unknown number is kept as text and reported as a warning).

References are ignored inside fenced code blocks, inline code spans and email-like text.
Everything here is pure text processing; the rules for what a reference may point at
live in `validate_references`."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from .errors import ServiceError

REMOVED_TEXT = "[image removed]"
LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
MEDIA_LETTERS = {"image": "i", "video": "v", "animated": "g", "frames": "f"}
# `v2`, `G4`, ...: a kind letter and a number. Labels may not look like this (see service.validate_label).
INDEX_RE = re.compile(r"^([ivgfIVGF])([1-9][0-9]*)$")
RESERVED_LABEL_RE = re.compile(r"^[ivgfIVGF][0-9]+$")  # any kind letter + digits, even i0
_LEGACY_INDEX_RE = re.compile(r"^([1-9][0-9]*)$")
_REPORT_RE = re.compile(r"(?:^|(?<=[\s(\[]))#([1-9][0-9]*)(?![\w\-])", re.M)
_REF_RE = re.compile(r"@@|(?<![\w.%+\-])@([A-Za-z0-9_\-]+)(?![\w\-])")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass
class Ref:
    token: str  # text as written, e.g. "@i1", "@login-error", "@@"
    start: int
    end: int
    kind: Literal["index", "label", "escape", "unknown"]

    @property
    def name(self) -> str:
        return self.token[1:]

    @property
    def key(self) -> str:
        """What the reference points at: the image number for an index (`@i1` and `@1` both
        give "1"), otherwise the name as written. Used to match rewrite mappings."""
        if self.kind == "index":
            return index_number(self.name) or self.name
        return self.name


def _blank(text: str) -> str:
    return "".join(ch if ch == "\n" else " " for ch in text)


def mask(notes: str) -> str:
    """Replace fenced blocks and inline code spans with spaces (same length, same newlines)."""
    out: list[str] = []
    fence: Optional[tuple[str, int]] = None  # (char, length) of the open fence
    prose: list[str] = []  # consecutive non-fence lines, so code spans may cross lines

    def flush():
        if prose:
            out.append(_mask_spans("".join(prose)))
            prose.clear()

    for line in notes.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if fence is None:
            match = _FENCE_RE.match(stripped)
            if match:
                flush()
                run = match.group(1)
                fence = (run[0], len(run))
                out.append(_blank(line))
            else:
                prose.append(line)
        else:
            out.append(_blank(line))
            match = _FENCE_RE.match(stripped)
            if (
                match
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= fence[1]
                and not stripped.strip().strip(fence[0])
            ):
                fence = None
    flush()
    return "".join(out)


def _mask_spans(text: str) -> str:
    chars = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k = j
        closed = -1
        while k < n:
            if text[k] == "`":
                m = k
                while m < n and text[m] == "`":
                    m += 1
                if m - k == run:
                    closed = m
                    break
                k = m
            else:
                k += 1
        if closed == -1:
            i = j  # unmatched backticks are literal
        else:
            for p in range(i, closed):
                if chars[p] != "\n":
                    chars[p] = " "
            i = closed
    return "".join(chars)


def index_number(name: str) -> Optional[str]:
    """`v3`, `I3` or the older `3` -> "3"; anything else -> None."""
    match = INDEX_RE.match(name)
    if match:
        return match.group(2)
    match = _LEGACY_INDEX_RE.match(name)
    return match.group(1) if match else None


def index_letter(name: str) -> Optional[str]:
    """The lower-case kind letter of `v3` ("v"); None for the older `3` form."""
    match = INDEX_RE.match(name)
    return match.group(1).lower() if match else None


def media_token(item) -> str:
    """The reference that points at a media item as written in notes: `@i1`, `@v2`, `@g3`, `@f4`."""
    return f"@{MEDIA_LETTERS.get(item.kind, 'i')}{item.idx}"


def report_refs(notes: str) -> list[int]:
    """Report numbers referenced by `#N` in the notes (code and emails excluded)."""
    return [int(m.group(1)) for m in _REPORT_RE.finditer(mask(notes or ""))]


def substitute_reports(notes: str, mapping: dict) -> str:
    """Replace `#N` by `mapping[N]` where present (other `#N` are left as written)."""
    out = notes or ""
    for m in reversed(list(_REPORT_RE.finditer(mask(out)))):
        number = int(m.group(1))
        if number in mapping:
            out = out[: m.start()] + mapping[number] + out[m.end():]
    return out


def _classify(name: str) -> str:
    if index_number(name) is not None:
        return "index"
    if LABEL_RE.match(name):
        return "label"
    return "unknown"


def parse_references(notes: str) -> list[Ref]:
    masked = mask(notes or "")
    refs: list[Ref] = []
    for match in _REF_RE.finditer(masked):
        if match.group(0) == "@@":
            refs.append(Ref("@@", match.start(), match.end(), "escape"))
        else:
            refs.append(Ref(match.group(0), match.start(), match.end(), _classify(match.group(1))))  # type: ignore[arg-type]
    return refs


def resolve(ref: Ref, media: list):
    """The media item a reference points at (label match is case-sensitive), or None.
    `@v2` only matches a video; the older `@2` matches whatever item is number 2."""
    if ref.kind == "index":
        letter = index_letter(ref.name)
        for item in media:
            if item.idx == int(ref.key) and (letter is None or MEDIA_LETTERS.get(item.kind) == letter):
                return item
    elif ref.kind == "label":
        for item in media:
            if item.label == ref.name:
                return item
    return None


def valid_tokens(media: list) -> list[str]:
    indexes = [media_token(m) for m in sorted(media, key=lambda m: m.idx)]
    labels = [f"@{m.label}" for m in sorted(media, key=lambda m: m.idx) if m.label]
    return indexes + labels


def validate_references(notes: str, media: list) -> None:
    for ref in parse_references(notes):
        if ref.kind == "escape":
            continue
        if resolve(ref, media) is None:
            valid = valid_tokens(media)
            raise ServiceError(
                "invalid_reference",
                f"unknown reference {ref.token} in notes",
                {"token": ref.token, "valid": valid},
            )


def _rewrite(notes: str, mapping: dict[str, str]) -> tuple[str, int]:
    out = notes
    count = 0
    for ref in reversed(parse_references(notes)):
        if ref.kind in ("index", "label") and ref.key in mapping:
            replacement = mapping[ref.key]
            if replacement != ref.token:
                out = out[: ref.start] + replacement + out[ref.end :]
                count += 1
    return out, count


def rewrite_references(notes: str, mapping: dict[str, str]) -> str:
    """Replace references by key (`{"2": "@i1", "old": "@new", "3": "[image removed]"}`).
    Code, emails and `@@` are never touched; other text is preserved exactly."""
    return _rewrite(notes, mapping)[0]


def rewrite_references_counted(notes: str, mapping: dict[str, str]) -> tuple[str, int]:
    return _rewrite(notes, mapping)


def references_to(notes: str, item, media_all: list) -> list[Ref]:
    """References in `notes` that resolve to `item`."""
    return [
        r
        for r in parse_references(notes)
        if (found := resolve(r, media_all)) is not None and found.id == item.id
    ]


def display_notes(notes: str, media: list) -> str:
    """Notes for terminal display: `@i1` becomes `@i1 (images/…)` and `@@` prints as `@`."""
    out = notes or ""
    for ref in reversed(parse_references(out)):
        if ref.kind == "escape":
            out = out[: ref.start] + "@" + out[ref.end :]
        elif ref.kind in ("index", "label"):
            item = resolve(ref, media)
            if item is not None:
                where = item.path or f"{len(item.frames)} frames"
                out = out[: ref.start] + f"{ref.token} ({where})" + out[ref.end :]
    return out


def substitute(notes: str, media: list, replacements: dict) -> str:
    """Notes for an outside destination: each resolvable reference becomes
    `replacements[media.id]` (left as written when absent) and `@@` becomes `@`."""
    out = notes or ""
    for ref in reversed(parse_references(out)):
        if ref.kind == "escape":
            out = out[: ref.start] + "@" + out[ref.end :]
        elif ref.kind in ("index", "label"):
            item = resolve(ref, media)
            if item is not None and item.id in replacements:
                out = out[: ref.start] + replacements[item.id] + out[ref.end :]
    return out
