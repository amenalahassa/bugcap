# Feature Specification: Bugcap Backlog Features (Image Association, @ References, Screen Recording, Dashboard)

**Feature Branch**: `002-bugcap-backlog-features`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Implement the four bugcap backlog items in ROADMAP.md (Backlog section) as one feature, building on the already-implemented items 1-5, 7, 8. Items 6 (S3/R2) and 9 (other trackers) stay out of scope. Do not change existing CLI behavior; extend it. Avoid heavy dependencies; the dashboard must work with the Python standard library only, with no Node build step."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Associate existing images with a bug (Priority: P1)

A developer already has a screenshot on disk, a file produced by another tool, or an image hosted at a URL (for example in a CI artifact or an issue comment). They attach it to a bug when capturing, or later, so the bug carries the evidence without re-shooting. Each image gets a stable number within its bug and an optional label so it can be referred to later.

**Why this priority**: Every other story in this feature refers to images, and this is the smallest slice that delivers value on its own. It also works on machines with no capture tool, so it is useful on every OS.

**Independent Test**: Capture a bug with one local image, attach a second image from a URL and a third from a glob, then `show` the bug and verify three images are listed with indexes 1, 2, 3 and the labels given.

**Acceptance Scenarios**:

1. **Given** a local PNG file, **When** the user runs `bugcap capture --image ./shot.png --title "Login fails"`, **Then** a new report is created whose image list contains a copy of the file with index 1, and the original file is not referenced by path afterwards.
2. **Given** an existing report, **When** the user runs `bugcap attach <id> --image ./a.png --image ./b.jpg --label after-fix`, **Then** both images are added with the next free indexes, and only the first label set is applied to the one image that asked for it (labels apply per `--image` occurrence).
3. **Given** a glob such as `./shots/*.png` that matches three files, **When** the user attaches it, **Then** the three matches are added in sorted filename order, each with the next index.
4. **Given** an `https://` URL to a real PNG, **When** the user attaches it, **Then** the image is downloaded into the store and the report refers to the stored copy; the URL is not stored as the image location.
5. **Given** a URL that responds with HTML, a file that is not an image, a file larger than the size cap, or a URL that does not respond within the timeout, **When** the user attaches it, **Then** that input is rejected with a message naming the input and the reason, nothing is stored for it, and any other valid inputs in the same command are still added (see Assumptions, partial batch import).
6. **Given** an image labelled `login-error` already exists in the report, **When** the user attaches another image with the same label, **Then** the command is refused with an error naming the duplicate label and the existing index.
7. **Given** a report created before this feature with old-style image entries, **When** bugcap opens it, **Then** the old images are still listed and shown, numbered in their original order, and no existing report data is lost.
8. **Given** an MCP client, **When** it calls the image-attach tool with a path or URL for a report, **Then** the result is the same as the CLI command (same validation, same stored copy, same index).

---

### User Story 2 - Refer to images from notes with @ (Priority: P2)

A developer writes notes such as "Error appears after step 3, see @1 and @login-error". The notes are checked when saved, so typos are caught immediately. When the bug is shown, or synced to GitHub, or viewed in the dashboard, each reference is replaced with the image it points to.

**Why this priority**: It makes the images from story 1 useful in context, and it is the reference mechanism the dashboard and GitHub sync depend on.

**Independent Test**: With a bug holding images 1 and labelled `login-error`, save notes containing `@1`, `@login-error` and `@@handle`; verify save succeeds, `show` prints the resolved image path next to each token, and the literal text `@handle` is shown for the escape. Then save notes containing `@9`; verify the command fails naming `@9` and listing the valid references.

**Acceptance Scenarios**:

1. **Given** a report with images 1 and 2 and label `login-error` on image 2, **When** the user saves notes containing `@1` and `@login-error`, **Then** the save succeeds.
2. **Given** the same report, **When** the user saves notes containing `@3`, **Then** the save is refused, the error names `@3`, and the valid references (`@1`, `@2`, `@login-error`) are listed. The previous notes are kept.
3. **Given** notes containing an email address such as `dev@example.com`, **When** saved, **Then** the `@` is not treated as a reference.
4. **Given** notes containing `` `@1` `` inside a code span or a fenced code block, **When** saved, **Then** the text is not treated as a reference and is not validated or resolved.
5. **Given** notes containing `@@1`, **When** saved and shown, **Then** the output contains the literal `@1` and no image is resolved.
6. **Given** a report, **When** the user runs `bugcap show <id>`, **Then** each reference outside code is printed with the resolved image path beside it.
7. **Given** a report that has been synced to GitHub, **When** the sync is run, **Then** each `@n` reference in the synced issue body or comment is replaced with the image markdown or link used for that sync.
8. **Given** an image that is referenced by notes, **When** the user relabels or removes it, **Then** the command is refused and lists the referencing notes, unless `--force` is given; with `--force`, the references are rewritten to match the new label or removed (the token is replaced by its plain text with the image no longer resolving, so nothing dangles silently).
9. **Given** a relabel or removal that renumbers later images, **When** the change is applied, **Then** `@n` references pointing at the later images are rewritten to their new numbers so they still point at the same image.

---

### User Story 3 - Record the screen for a complex bug (Priority: P3)

A developer reproduces a bug that is hard to describe in a still picture, such as a timing problem or a multi-step interaction. They run `bugcap record`, perform the steps, press Enter or Ctrl+C, and the recording is attached to a new or existing bug as a video, a short set of keyframes, or an animated image, whichever they chose. Size and duration are kept small by default.

**Why this priority**: Valuable, but it depends on platform recording tools that vary by OS and may need permissions, so it is delivered after the image and reference work it reuses.

**Independent Test**: On a machine with a supported recorder, run `bugcap record --id <id> --format animated --max-seconds 10`, record a few seconds, press Enter; verify a playable animated file is attached to that report as a media item of kind `animated` and the command prints its final size.

**Acceptance Scenarios**:

1. **Given** the user chooses `--format video`, **When** recording stops, **Then** an mp4 or webm file is attached as a media item of kind `video` and is playable.
2. **Given** `--format frames`, **When** recording stops, **Then** a short batch of PNG or JPEG keyframes is attached as one media item of kind `frames`, with the frames kept in order.
3. **Given** `--format animated`, **When** recording stops, **Then** a GIF or animated WebP is attached as one media item of kind `animated`.
4. **Given** no `--format`, **When** the user records, **Then** the default format is used (see Assumptions) and the size-saving defaults apply.
5. **Given** `--max-seconds 30` and the user does not stop, **When** 30 seconds pass, **Then** recording stops automatically and the file is finalized and attached; the command reports that the duration cap was reached.
6. **Given** a size cap is reached before the time cap, **When** recording is still running, **Then** recording stops and the file is finalized and attached, with a message that the size cap was reached.
7. **Given** the user presses Enter or Ctrl+C, **When** recording stops, **Then** the output is always a playable file (Ctrl+C never leaves a truncated, unplayable file), and the command reports the final size.
8. **Given** no recorder tool is installed, **When** the user runs `bugcap record`, **Then** the command explains which recorder is needed for this OS and how to install it (`bugcap setup` covers this), and exits without creating a report.
9. **Given** the OS denies screen-recording permission (for example macOS), **When** the user records, **Then** the command explains how to grant the permission and exits without creating a report.
10. **Given** an existing report id, **When** recording is attached, **Then** the media item is added to that report; with no id, a new report is created.
11. **Given** a recording whose final size is above the GitHub limit for direct upload, **When** the report is synced, **Then** the sync warns clearly that the file was not uploaded, names the file and its size, and continues with the other media; the warning is never silent.
12. **Given** frames or an animated file, **When** synced to GitHub, **Then** video and animated files are uploaded or committed as-is, and frames are linked as a set (every frame in order), each subject to the same size warning.

---

### User Story 4 - Browse and act on bugs in a local dashboard (Priority: P4)

A developer runs `bugcap dashboard` to open a web page on their own machine. They filter bugs by repo, tag, status or text, open one to read its notes with references resolved inline, look at all its images and recordings, follow its GitHub link, and make light changes such as status, tags and notes.

**Why this priority**: The most visible feature, but it reads the data and references produced by stories 1-3, so it comes last. It is read-mostly, so it adds no new data rules.

**Independent Test**: Start `bugcap dashboard --port 0 --open` (or a chosen port), filter the list by a tag, open a bug with an image and a video, verify the image is shown inline where `@1` appears in the notes, the video plays, and changing the status is reflected on the next `bugcap show`.

**Acceptance Scenarios**:

1. **Given** reports from several repos, **When** the user selects a repo, a tag, a status, or types text, **Then** the list shows only matching bugs and the filters can be combined.
2. **Given** a bug with notes containing `@1`, **When** the user opens it, **Then** the image appears inline at that point in the notes.
3. **Given** a bug with a video, frames and an animated image, **When** opened, **Then** the video has playback controls, the frames are previewed in order, and the animated image plays.
4. **Given** a bug synced to GitHub, **When** opened, **Then** its GitHub issue link is shown.
5. **Given** the user changes the status, adds or removes a tag, or edits the notes, **When** the change is saved, **Then** it appears on the bug and in `bugcap show`; notes are checked against the same rules as the CLI, and an invalid reference is shown as an error in the page.
6. **Given** the dashboard is started without `--host`, **When** it starts, **Then** it listens on 127.0.0.1 only.
7. **Given** a `--host` value that is not a loopback address, **When** the user starts the dashboard with it, **Then** a warning is printed, and the dashboard starts only because `--host` was given explicitly.
8. **Given** a web page on another origin, **When** it tries to change data through the dashboard, **Then** the change is refused because the request does not carry the session token.
9. **Given** a request for a media file, **When** the path is outside the store's image and media directories (for example `../../etc/passwd` or an absolute path), **Then** the request is refused and nothing outside those directories is served.
10. **Given** a request for a video with a byte range, **When** served, **Then** the correct partial content is returned so the video can seek.
11. **Given** a phone-sized screen or a dark-mode system setting, **When** the dashboard is opened, **Then** the layout remains usable and the colours follow the system theme.
12. **Given** the dashboard page, **When** it loads, **Then** it makes no requests to external hosts; all scripts and styles are served locally.

### Edge Cases

- A glob that matches nothing is an error naming the pattern, not a silent no-op.
- A glob that matches a directory or a non-image file skips that entry with a reported reason; a glob matching only invalid files is an error.
- A URL that redirects to a non-http(s) address is refused.
- An image whose content is valid but whose extension is misleading (for example `.txt` holding a PNG) is accepted only if its content is a real PNG, JPEG, GIF or WebP.
- A reference such as `@01` or `@1x` is not a valid index and is treated as an unknown token, not as `@1`.
- A label that looks like a number (for example `2`) is refused, because it would be ambiguous with an index.
- A label containing spaces or characters outside letters, digits, `-` and `_` is refused.
- Notes with an `@` at the end of a sentence followed by a space are not references.
- Removing the last image of a report leaves the report intact with no images; references to it are refused unless `--force`.
- Recording while the chosen output folder is not writable fails before recording starts.
- Recording when the user interrupts during finalization does not leave a partial file attached.
- An existing database written by the previous version is upgraded automatically the first time the new version opens it; downgrading to the previous version afterwards is not supported.
- A dashboard request for a bug id that does not exist returns a clear not-found response.
- A dashboard edit that would make notes invalid is refused and the stored notes are unchanged.

## Requirements *(mandatory)*

### Functional Requirements

**Images (Story 1)**

- **FR-001**: `bugcap capture --image SRC` and `bugcap attach <id> --image SRC` MUST accept a local file path, a glob pattern, or an http(s) URL, and the `--image` option MUST be repeatable.
- **FR-002**: Every accepted image MUST be copied into the store's image directory; the report MUST NOT reference the original file location.
- **FR-003**: URL downloads MUST enforce a size cap (default 25 MB), a timeout (default 20 seconds), a content-type check, and MUST NOT send credentials, cookies or the user's tokens.
- **FR-004**: Every input MUST be validated as a real PNG, JPEG, GIF or WebP by its content, not by its name or content-type header alone.
- **FR-005**: Each image in a report MUST have a stable 1-based index that is never reused within that report, even after another image is removed.
- **FR-006**: An image MAY have a label; labels MUST be unique within a report, MUST match letters, digits, `-` and `_`, and MUST NOT be purely numeric.
- **FR-007**: Image data MUST be stored in a structure that records index, label, kind, stored location and original source; existing reports' image lists MUST be migrated into it without loss, and their old list MUST remain readable.
- **FR-008**: The same image attachment operation MUST be available to the MCP server as a tool, with the same validation and results as the CLI.
- **FR-009**: Image attachment MUST report, per input, whether it was added, skipped, or rejected, and why.

**References (Story 2)**

- **FR-010**: Notes MAY contain `@n` (index) or `@label` tokens that refer to images of the same report.
- **FR-011**: References MUST be validated on `capture`, `edit`, `attach` and MCP note updates; an unknown reference MUST refuse the save, name the bad token, and list the valid references.
- **FR-012**: `@` inside an email-like token, inside a code span, or inside a fenced code block MUST NOT be treated as a reference.
- **FR-013**: `@@` MUST render as a literal `@` and MUST NOT be treated as a reference.
- **FR-014**: `show` MUST print each reference's resolved image location next to the token.
- **FR-015**: When a report is synced to GitHub, each reference MUST be replaced with the image markdown or link used for that sync; the dashboard MUST display each reference's image inline.
- **FR-016**: Removing or relabeling a referenced image MUST be refused unless `--force` is given; with `--force`, references MUST be rewritten so they keep pointing at the same image (for relabel and renumbering) or are replaced by their plain text (for removal).

**Recording (Story 3)**

- **FR-017**: `bugcap record` MUST accept `--id`, `--format` (`video`, `frames`, `animated`), `--max-seconds`, and `--fps`; without `--id` it MUST create a new report.
- **FR-018**: `video` MUST produce mp4 or webm; `frames` MUST produce an ordered set of PNG or JPEG keyframes; `animated` MUST produce GIF or animated WebP.
- **FR-019**: Defaults MUST favour small size (see Assumptions for values); the user MUST be able to override duration, frame rate and format.
- **FR-020**: Recording MUST stop on Enter or Ctrl+C, on the duration cap, or on the size cap, and in every case MUST finalize a playable file before attaching it.
- **FR-021**: The command MUST report the final size of the attached file, and MUST state when a cap was the reason recording stopped.
- **FR-022**: The recorder MUST be chosen per OS: ffmpeg is the portable baseline (with x11grab on Linux/X11, gdigrab on Windows, avfoundation on macOS); wf-recorder is used on Linux Wayland sessions where it is available.
- **FR-023**: Recorder availability MUST be detected and installation guidance offered through the same mechanism as capture backends and `bugcap setup`.
- **FR-024**: When no recorder exists, or screen-recording permission is missing, the command MUST explain the cause and the fix, and MUST NOT create a report or leave a partial file.
- **FR-025**: Media items MUST carry a kind of `image`, `video`, `frames` or `animated`; the `@` reference rules, `show`, the MCP server, the dashboard and sync MUST all handle every kind.
- **FR-026**: GitHub sync MUST upload or commit video and animated files as-is and MUST link frames as an ordered set.
- **FR-027**: Any media file above GitHub's direct-upload limit for the chosen destination MUST be skipped with a visible warning naming the file and its size; sync MUST NOT fail silently and MUST continue with the remaining media.

**Dashboard (Story 4)**

- **FR-028**: `bugcap dashboard` MUST accept `--port` and `--open`, and MUST bind to 127.0.0.1 by default.
- **FR-029**: A non-loopback `--host` MUST be refused unless it is explicitly passed, and MUST print a warning when it is used.
- **FR-030**: The dashboard MUST let the user browse and filter reports by repo, tag, status and text, and open a report to see its notes with references resolved inline, all its media, and its sync references.
- **FR-031**: The dashboard MUST allow changing status, adding and removing tags, and editing notes, with the same validation as the CLI.
- **FR-032**: The dashboard MUST expose a JSON API under `/api` that uses the same store and service logic as the CLI and MCP server; no rule may be duplicated in the dashboard.
- **FR-033**: Media MUST be served only from the store's image and media directories; any path resolving outside them MUST be refused.
- **FR-034**: Media responses MUST carry the correct content type and MUST support byte-range requests for video.
- **FR-035**: Every state-changing API request MUST carry a per-session token that is issued by the dashboard page and checked by the server; requests without it, or with a wrong one, MUST be refused.
- **FR-036**: The dashboard MUST be responsive (usable at phone width) and follow the system light or dark theme.
- **FR-037**: The dashboard MUST NOT make requests to any external network host.

**Cross-cutting**

- **FR-038**: Existing CLI commands, flags and output MUST keep working as they do today; new behaviour is additive.
- **FR-039**: The feature MUST NOT add a required third-party runtime dependency; the dashboard MUST run on the Python standard library alone.
- **FR-040**: Existing databases MUST be upgraded in place with no data loss.

### Key Entities *(include if feature involves data)*

- **Report**: an existing bug record; gains the ability to hold ordered media items and to be referred to from its own notes.
- **Media item**: one attached piece of evidence belonging to a report. Attributes: index within the report, optional label, kind (image, video, frames, animated), stored location(s), original source (path, glob match, or URL), size, and creation time. A frames item groups an ordered set of keyframes.
- **Reference**: a token in a report's notes (`@n`, `@label`) that resolves to a media item of that report. Not stored separately; derived from notes.
- **Sync reference**: an existing link from a report to its GitHub issue or the committed image copy, shown in the dashboard and used by sync.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can attach three images from mixed sources (a file, a glob, and a URL) to one bug in a single command, and see them numbered 1 to 3 in under 10 seconds on a typical connection.
- **SC-002**: 100% of invalid inputs (non-image content, oversized downloads, unreachable URLs, duplicate labels) are refused with a message that names the input and the reason, and no partial or invalid file is left in the store.
- **SC-003**: Every unknown `@` reference is caught on save, with 100% of errors naming the bad token and listing the valid choices.
- **SC-004**: A user can record a 10-second bug reproduction in animated format, at default settings, and the attached file is at most 5 MB.
- **SC-005**: Every recording stopped by Enter, Ctrl+C, or a cap opens as a playable file in a standard player.
- **SC-006**: A user can find a bug among 500 reports by repo, tag and text in under 5 seconds from the dashboard.
- **SC-007**: Every existing report survives the upgrade with its notes, tags, status, repo and sync references unchanged.
- **SC-008**: No request from another web page, and no request for a path outside the media folders, succeeds in the dashboard.
- **SC-009**: Existing commands and their output remain unchanged for users who do not use the new options.

## Assumptions

- **Limits (defaults, configurable)**: URL downloads capped at 25 MB, 20-second timeout, following at most 5 redirects, http and https only. A recording defaults to 30 seconds maximum, 5 frames per second, and a total cap of 25 MB; `--max-seconds` may raise or lower the duration cap.
- **Recording default format**: `animated` (GIF), chosen because it plays in every browser and in GitHub comments without a player; GIF is larger than WebP, so WebP may be preferred if the recorder supports it at the same quality. Video is recommended for longer recordings; frames for keeping individual steps.
- **GitHub direct-upload limit**: the warning threshold is 25 MB per file by default for issue attachments and committed copies, with GitHub's hard per-file limit (100 MB) as the absolute ceiling; the threshold is adjustable in configuration.
- **Partial batch import**: when several inputs are given in one command, valid inputs are added and invalid ones are reported and skipped, so one bad URL does not discard the rest. This is stated in the command help.
- **Notes save is all-or-nothing**: a bad reference refuses the whole save, and the old notes are kept. (Image batches are not all-or-nothing; see partial batch import above.)
- **Label format**: letters, digits, hyphen and underscore; labels are case-sensitive for matching but compared case-insensitively for uniqueness.
- **Index stability**: indexes are never reused; renumbering only happens when an image is removed with `--force` and the rewrite then keeps existing references pointing at the same image.
- **Media storage**: stored copies live under the store's existing image directory for images and a sibling media directory for recordings and frames; original files are never referenced in place.
- **Recorder tools**: the feature uses already-installed command-line recorders (ffmpeg, wf-recorder) and does not bundle its own. `bugcap setup` extends its detection and install guidance to cover them.
- **Dashboard session token**: generated per dashboard process and embedded in the page served by that process; it is not stored on disk and is not sent to any external host.
- **Dashboard scope**: read-mostly; it does not create reports, upload images, or start recordings in this version, and changes are limited to status, tags and notes.
- **Out of scope**: S3/R2 object storage (item 6), other trackers such as Linear, Jira, Trello (item 9), multi-user or remote access to the dashboard, and authentication beyond the local session token.
- **Existing behaviour**: the MCP server, GitHub pull/sync and `bugcap setup` keep their current behaviour; the new options and tools are additions.
- **Zero clarification markers**: all open choices above have reasonable defaults recorded here, so no questions are blocking planning. Any of them can be changed during `/speckit-clarify`.
