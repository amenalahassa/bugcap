# Contract: Live-Mode Keyboard Shortcuts

Source of truth: `shortcuts.SHORTCUTS`. Labels and bindings are rendered from it; `{mod}` is `Control` (label "Ctrl") on Windows/Linux and `Command` (label "⌘") on macOS; `Alt` is labelled "Option" on macOS.

| Scope | Action | Key | Label (Win/Linux) | Label (macOS) |
|---|---|---|---|---|
| control | Screenshot | `s` / `S` | S | S |
| control | Record / Stop | `r` / `R` | R | R |
| control | Upload image | `i` / `I` | I | I |
| control | Attach file | `f` / `F` | F | F |
| control | New bug | `n` / `N` | N | N |
| control | Add to existing | `e` / `E` | E | E |
| control | Clear | `Delete` | Del | ⌦ |
| form | Save | `<{mod}-Return>` | Ctrl+Enter | ⌘+Enter |
| form | Back | `<Escape>` | Esc | Esc |
| form | Discard | `<Alt-d>` | Alt+D | Option+D |
| form | Remove selected attachment | `<Alt-x>` | Alt+X | Option+X |
| form | Open selected attachment | `<Alt-o>` | Alt+O | Option+O |
| form | Select previous/next attachment (focus on strip) | `<Left>` / `<Right>` | ← / → | ← / → |
| attach | Add | `<{mod}-Return>` | Ctrl+Enter | ⌘+Enter |
| attach | Cancel | `<Escape>` | Esc | Esc |
| attach | Focus bug picker | `<Alt-b>` | Alt+B | Option+B |
| chooser | Confirm / Cancel | `<Return>` / `<Escape>` | Enter / Esc | Enter / Esc |
| global | Shortcut help | `<F1>` | F1 | F1 |

Invariants (tested):

- Every action in FR-020 appears exactly once in its scope; no key is bound twice within a scope.
- No `form`/`attach` shortcut is an unmodified printable key, so text entry is never intercepted (FR-022).
- A shortcut whose button is disabled is a no-op (FR-025).
- Only bugcap windows are bound; there are no global hotkeys (FR-021).
