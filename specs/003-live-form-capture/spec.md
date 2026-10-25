# Feature Specification: Live-Mode Form and Capture Improvements

**Feature Branch**: `003-live-form-capture`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "Improve `bugcap live` (the control panel and the "New bug report" / "Add to existing bug" windows) in four areas, shipped together as one feature: (1) remove staged attachments and open any attachment, including videos, in the OS default app; (2) keep the in-progress form across Back/Cancel and across restarts until Discard or Save; (3) choose a monitor, a drawn region or a single window for screenshots and recordings, including Flameshot on multi-monitor Windows and recording on Windows/Ubuntu; (4) keyboard shortcuts for every live-mode action, active only while a bugcap window is focused. Python/tkinter only; existing CLI, MCP and dashboard behaviour unchanged."

## Clarifications

### Session 2026-10-25

- Q: When the user clicks Screenshot or Record, should the target chooser appear every time, or should capture start straight away on the last target? → A: The chooser opens on every Screenshot/Record click, with the last target preselected (one extra click or Enter each time).
- Q: Should a recording be able to include sound (system audio and/or microphone), or stay video-only? → A: Video only, as today; sound is out of scope for this feature.
- Q: When the user removes a staged attachment, what protects them from removing the wrong one? → A: A confirmation "Remove <item>?"; Enter/Yes confirms, Esc cancels.
- Q: What style should the control panel's shortcuts use? → A: Control panel uses single keys (S Screenshot, R Record/Stop, I Upload image, F Attach file, N New bug, E Add to existing, Del Clear); forms use Alt+letter plus Esc and Ctrl/Cmd+Enter.
- Q: Should the "Add to existing bug" selection and note also survive a restart or crash? → A: No; they are kept in memory across Cancel/reopen while bugcap runs and lost on exit. Only the New bug form and staged items are persisted.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remove and preview attachments while filling a bug (Priority: P1)

A developer has captured three screenshots and a recording in live mode and opened the "New bug report" form. One screenshot is wrong, so they remove it from the form without discarding the rest. Before writing the notes they click the recording to check that it shows the bug; it opens in their normal video player. They write the notes using the `@` tags shown and save.

**Why this priority**: Today a wrong capture can only be fixed by discarding everything, and a video cannot be checked at all before it is filed. This is the most frequent annoyance and the smallest slice that adds value on its own.

**Independent Test**: Stage two images and one video, open the form, remove the second image, click the video, then save. Verify the saved report holds exactly the first image and the video, the removed file is no longer in the staging area, and the video opened in the OS default player.

**Acceptance Scenarios**:

1. **Given** the form shows three staged items, **When** the user removes the second item and confirms, **Then** the strip shows the remaining two items, the `@` tags shown for them are updated, and the removed item is deleted from the staging area.
2. **Given** the control panel lists staged items, **When** the user removes one from the control panel, **Then** it disappears from both the control panel and any open form, and the staged count is updated.
3. **Given** the notes contain the tag of an item the user then removes, **When** the item is removed, **Then** the notes text is left as typed and the existing notes check reports the tag as no longer valid, so Save is blocked until the user fixes the notes.
4. **Given** a staged video, image or other file, **When** the user clicks its thumbnail, **Then** it opens in the application the OS uses for that file type, and the form stays open.
5. **Given** no application is registered for a staged file's type, **When** the user clicks it, **Then** a status message says the file could not be opened and names its location, and nothing else changes.
6. **Given** the user chose to remove an item, **When** the confirmation asks "Remove <item>?" and the user presses Esc or No, **Then** nothing is removed.
7. **Given** only one staged item, **When** the user removes it and confirms, **Then** the form switches to note-only mode and the user can still save a note-only bug.

---

### User Story 2 - Keep what was typed until Discard or Save (Priority: P1)

A developer is halfway through describing a bug, clicks Back to take one more screenshot, then clicks "New bug from 3 items…". The title, notes, tags, status and repo they entered are still there. Later bugcap crashes or the laptop restarts; on the next `bugcap live` they are offered the in-progress bug and get everything back, typed fields and attachments included.

**Why this priority**: Losing typed text is a data-loss bug from the user's point of view, and it discourages the capture-then-describe workflow live mode exists for.

**Independent Test**: Type a title, notes and tags, click Back, reopen New bug and verify every field is restored. Then close bugcap from the control panel without saving, relaunch it, accept the draft offer and verify fields and staged media are restored.

**Acceptance Scenarios**:

1. **Given** the user typed a title, notes, tags, status and repo, **When** they click Back and then New bug, **Then** every field shows what they typed.
2. **Given** the user clicked Back, **When** they open "Add to existing bug" instead, **Then** the new-bug fields remain remembered and come back the next time New bug is opened.
3. **Given** the user selected a bug and typed a note in "Add to existing bug", **When** they click Cancel and reopen that dialog, **Then** the same bug is selected and the note is restored.
4. **Given** remembered fields, **When** the user clicks Discard and confirms, **Then** fields and staged media are cleared and the next New bug starts empty.
5. **Given** remembered fields, **When** the user clicks Discard and declines the confirmation, **Then** nothing is cleared.
6. **Given** the user saves the bug, **When** they next open New bug, **Then** the form starts empty.
7. **Given** remembered fields or staged media, **When** bugcap exits unexpectedly or is closed without saving, **Then** on the next launch in the same repo the user is offered that in-progress bug, and accepting it restores fields and media.
8. **Given** the user successfully adds a note to an existing bug, **When** they reopen "Add to existing bug", **Then** the dialog starts empty.

---

### User Story 3 - Choose what to capture or record (Priority: P2)

A developer works on Windows with two monitors and Flameshot. They click Screenshot and pick "Monitor 2"; only that monitor is captured. For a recording they pick "Region", drag a rectangle around the dialog that misbehaves, and only that rectangle is recorded. On Ubuntu they pick a single application window to record. The next time, bugcap preselects their last choice.

**Why this priority**: On multi-monitor setups the current behaviour captures the wrong or the whole desktop, and recordings are unnecessarily large and expose unrelated screen content. It depends on platform tools, so it comes after the form fixes.

**Independent Test**: On a two-monitor machine, take a screenshot of monitor 2 only, then record a drawn region for five seconds. Verify the image matches monitor 2's resolution and the video's frame size matches the drawn region.

**Acceptance Scenarios**:

1. **Given** two or more monitors, **When** the user starts a screenshot or recording, **Then** they can choose one monitor or all screens, and the result covers only the choice.
2. **Given** the user chooses Region, **When** they drag a rectangle on screen, **Then** only that rectangle is captured or recorded; pressing Esc cancels without capturing.
3. **Given** the user chooses Window, **When** they pick a window from the list of open windows, **Then** only that window is captured or recorded.
4. **Given** a target was chosen once, **When** the user starts the next screenshot or recording, **Then** the same target type (and same monitor, if it still exists) is preselected.
5. **Given** the platform or installed tool cannot honour a target (for example window-only recording on a Wayland session), **When** the chooser is shown, **Then** that option is disabled with a short reason, and it is never silently replaced by a different target.
6. **Given** a remembered monitor that is no longer connected, **When** the chooser opens, **Then** it falls back to all screens and says so.
7. **Given** a single monitor, **When** the user starts a capture, **Then** the chooser still opens, offering the screen (preselected), Region and Window, and pressing Enter or clicking once starts the preselected capture.

---

### User Story 4 - Drive live mode from the keyboard (Priority: P3)

A developer reporting several bugs in a row presses a key to take a screenshot, another to open New bug, types the title and notes, and saves with Ctrl+Enter, without touching the mouse. They press F1 to see every shortcut.

**Why this priority**: It speeds up frequent users but does not unblock anything; every action is already reachable with the mouse.

**Independent Test**: With the control panel focused, take a screenshot, open New bug, fill the fields, remove an attachment, open an attachment and save, using only the keyboard. Verify F1 lists every shortcut used.

**Acceptance Scenarios**:

1. **Given** a focused bugcap window, **When** the user presses an action's shortcut, **Then** the action runs exactly as if its button were clicked, including being ignored when the button is disabled.
2. **Given** focus is in the Title or Notes field, **When** the user types ordinary text, uses standard editing keys (copy, paste, undo, select all, arrows, Enter for a new line in Notes), **Then** the text behaves normally and no live-mode action runs.
3. **Given** the New bug form, **When** the user presses Ctrl+Enter (Cmd+Enter on macOS), **Then** the bug is saved; Esc acts as Back.
4. **Given** the "Add to existing bug" dialog, **When** the user presses Esc, **Then** it acts as Cancel; Ctrl+Enter acts as Add.
5. **Given** any live-mode window, **When** the user presses F1, **Then** a help overlay lists every shortcut for the current OS, and it closes with Esc or F1.
6. **Given** a button with a shortcut, **When** the user looks at or hovers over it, **Then** the shortcut is shown.
7. **Given** bugcap is not the focused application, **When** the user presses a bugcap shortcut, **Then** nothing happens in bugcap.

---

### Edge Cases

- Removing an item while a recording is still being finalized: the in-flight item cannot be removed until it is staged.
- Removing every staged item from the control panel while the form is open: the form switches to note-only mode and keeps the typed fields.
- Opening an attachment whose file was deleted or moved outside bugcap: a status message says the file is missing; the item stays listed so the user can remove it.
- Two bugcap live windows in the same repo: each keeps its own in-progress bug; restart offers each saved in-progress draft separately, like existing drafts.
- Remembered repo no longer configured: the form falls back to the default repo and says so.
- Region drawn with zero or tiny size (smaller than 16×16 px): treated as cancelled, with a status message.
- Region spanning two monitors with different scaling: the captured area matches what the user drew on screen.
- The chosen window is closed, minimised or moved during recording: the recording stops and keeps what was captured, with a status message naming the reason.
- A shortcut pressed while a modal confirmation (Discard, Close) is open: only that dialog's own keys apply.
- Shortcuts with non-US keyboard layouts: shortcuts that need a key not present on the layout still have a working equivalent listed in the F1 overlay.

## Requirements *(mandatory)*

### Functional Requirements

**Attachments**

- **FR-001**: Users MUST be able to remove any single staged item from the New bug form and from the control panel's staged list, after confirming a "Remove <item>?" prompt (Enter/Yes confirms, Esc/No cancels).
- **FR-002**: Removing an item MUST delete its staged files, update the displayed `@` tags and staged count in every open live window, and leave the notes text unchanged.
- **FR-003**: The notes check MUST flag any `@` tag that no longer matches a staged item, and Save MUST be blocked while such a tag exists, as it is for other invalid tags today.
- **FR-004**: Clicking (or activating by keyboard) any staged item MUST open it in the OS default application for its type, for images, videos, animated images and other files alike.
- **FR-005**: If an item cannot be opened (missing file, no registered application), the system MUST show a status message with the reason and the file location, and MUST NOT close or reset the form.

**Remembered form**

- **FR-006**: Back MUST keep the New bug fields (title, notes, tags, status, repo) and the staged items; reopening New bug MUST restore them.
- **FR-007**: The "Add to existing bug" dialog MUST keep its selected bug and note across Cancel and reopen, separately from the New bug fields, for as long as live mode runs; this state is not persisted and is lost when bugcap exits.
- **FR-008**: Remembered state MUST be cleared only by a confirmed Discard, a successful Save (New bug fields), or a successful Add (Add-to-existing fields).
- **FR-009**: The remembered New bug fields and staged items MUST be persisted so that they survive closing bugcap and unexpected exits, and MUST be offered for restore on the next live-mode launch in the same repo through the existing draft offer.
- **FR-010**: Persisting the New bug form MUST happen whenever it is left (Back, window close, bugcap close) and at least every 5 seconds while its fields change, so that no more than 5 seconds of typing can be lost on a crash.

**Capture and recording target**

- **FR-011**: Every Screenshot and Record click MUST open a target chooser before anything is captured, offering one monitor, all screens, a drawn region, or a single window; the last target is preselected, Enter or one click confirms it, and Esc cancels without capturing.
- **FR-012**: Screenshots and recordings MUST contain only the chosen target.
- **FR-013**: On Windows with Flameshot and multiple monitors, choosing a monitor MUST capture that monitor only.
- **FR-014**: Recording on Windows and on Linux (X11 and Wayland) MUST honour monitor and region targets; window targets MUST be honoured where the platform allows it.
- **FR-015**: Region selection MUST use an on-screen overlay where the user drags a rectangle; Esc MUST cancel.
- **FR-016**: The list of monitors and open windows MUST come from the running system at the time the chooser opens.
- **FR-017**: Options the current platform or installed tool cannot honour MUST be shown disabled with a reason, never silently replaced by another target.
- **FR-018**: The last chosen target MUST be remembered and preselected next time; if it is no longer available the system MUST fall back to all screens and say so.
- **FR-019**: The command each target produces for each OS and tool MUST be derivable without running it, so it can be tested on any OS.

**Keyboard shortcuts**

- **FR-020**: Every control panel action (Screenshot, Record/Stop, Upload image, Attach file, Clear, New bug, Add to existing) and every form action (Save, Back, Discard, remove selected attachment, open selected attachment, Cancel, Add) MUST have a keyboard shortcut.
- **FR-021**: Shortcuts MUST work only while a bugcap window is focused; there MUST be no system-wide hotkeys.
- **FR-022**: Shortcuts MUST NOT override text entry or standard editing keys in text fields. The control panel (which has no text fields) MUST use single keys: S Screenshot, R Record/Stop, I Upload image, F Attach file, N New bug, E Add to existing, Del Clear. The forms MUST use Alt+letter for their other actions, Esc for Back/Cancel, and Ctrl+Enter (Cmd+Enter on macOS) for Save/Add.
- **FR-023**: Shortcuts MUST use the platform's primary modifier (Cmd on macOS, Ctrl elsewhere).
- **FR-024**: Each button MUST show its shortcut, and F1 MUST open an overlay listing every shortcut for the current OS.
- **FR-025**: A shortcut for a disabled action MUST do nothing.

**Compatibility and documentation**

- **FR-026**: Existing CLI commands, MCP tools, dashboard behaviour and stored report/draft data MUST keep working unchanged; drafts written before this feature MUST still load.
- **FR-027**: README/usage docs and the CHANGELOG MUST describe the new live-mode behaviour and the shortcut list.

### Key Entities

- **Staged item**: an attachment waiting to be filed (screenshot, uploaded image, recording, other file), with its kind, file(s) and the `@` tag shown in the form. Can now be removed individually and opened.
- **In-progress bug**: the remembered New bug fields (title, notes, tags, status, repo) plus its staged items; persisted as a draft until Save or Discard.
- **In-progress addition**: the remembered "Add to existing bug" selection and note; held in memory only, until Add succeeds, the in-progress bug is discarded, or bugcap exits.
- **Capture target**: what to capture or record — a monitor (by identity and position), all screens, a region (position and size), or a window (identity and title) — plus whether the current platform/tool supports it.
- **Shortcut map**: the action-to-key list per OS, used for bindings, button labels and the F1 overlay.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can remove a wrong attachment and keep the others in at most 2 actions (remove, confirm), with no need to discard or recapture.
- **SC-002**: 100% of staged item types (image, video, animated image, other file) can be opened from the form on Windows, macOS and Linux when the OS has an application for the type.
- **SC-003**: In 100% of Back → reopen and Cancel → reopen cycles, every typed field is restored exactly.
- **SC-004**: After an unexpected exit, the user recovers the in-progress bug with at most the last 5 seconds of typing lost.
- **SC-005**: On a two-monitor Windows machine with Flameshot, a monitor-targeted screenshot contains only that monitor in 100% of attempts.
- **SC-006**: A region recording's frame size matches the drawn region (within 2 px per side) on Windows and Ubuntu.
- **SC-007**: A user can capture, describe and save a bug using only the keyboard.
- **SC-008**: No existing automated test of the CLI, MCP or dashboard needs to change for this feature.

## Assumptions

- Attachments open in the OS default application; there is no in-app video player.
- Recordings stay video-only; recording microphone or system audio is out of scope.
- Shortcuts apply only inside bugcap windows; global hotkeys are out of scope.
- The in-progress bug reuses the existing drafts store and draft-offer flow instead of adding a new persistence mechanism.
- Removing an attachment never rewrites the notes; the existing notes check is enough to point out stale tags.
- Window-only recording may be unavailable on some Linux setups (notably Wayland); the chooser disables it there with a reason, as FR-017 requires.
- Listing monitors and windows uses facilities already on the OS or already-supported tools; no heavy new dependency is added.
- The default shortcut set is fixed; user-configurable shortcuts are out of scope.
- Control-panel single keys and Esc, Ctrl/Cmd+Enter, F1 are fixed by FR-022/FR-024; the exact Alt+letter for each form action is chosen in planning, avoiding letters the OS or text fields already use.
