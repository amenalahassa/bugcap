import argparse
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from . import backends, capture, config, recorder, refs, repo, service, sync
from .capture import CaptureError
from .errors import ServiceError
from .ghcli import GhError
from .store import STATUSES, Store


# --- shared helpers (T014) ----------------------------------------------------

def current_repo():
    """The RepoConfig discovered from the working directory, or None."""
    return repo.load_repo_config()


def resolve_report(store: Store, report_id: int):
    """Return the report, or print the standard not-found error and return None."""
    report = store.get(report_id)
    if report is None:
        print(f"error: no report with id {report_id}", file=sys.stderr)
    return report


from .sync import human_size  # noqa: E402,F401


def print_service_error(exc: ServiceError) -> None:
    print(f"error: {exc.message}", file=sys.stderr)
    if exc.code == "invalid_reference":
        print("valid references: " + (", ".join(exc.details.get("valid", [])) or "(none)"), file=sys.stderr)


def print_ingest(added, rejected) -> None:
    """One line per input: `added #<idx> ...` on stdout, `skipped ...` on stderr."""
    for media in added:
        name = os.path.basename(media.path or "")
        print(f"added #{media.idx} {name} ({media.kind}, {human_size(media.size_bytes)})")
    for item in rejected:
        print(f"skipped {item['source']}: {item['reason']}", file=sys.stderr)


# --- capture / list / show ----------------------------------------------------

def cmd_capture(args: argparse.Namespace) -> int:
    cfg = current_repo()
    captured: Optional[str] = None
    if not args.image:
        try:
            captured = str(capture.capture_screenshot())
        except CaptureError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    title = args.title or input("Title: ").strip()
    notes = args.note
    if notes is None:
        notes = input("Notes (optional): ").strip()

    tags = list(args.tag or [])
    repo_key: Optional[str] = None
    if cfg is not None:
        repo_key = cfg.key
        if cfg.tag not in tags:
            tags.append(cfg.tag)

    labels = list(args.label or [])
    with Store() as store:
        try:
            report, result = service.create_report(
                store,
                title=title,
                notes=notes or "",
                tags=tags,
                repo=repo_key,
                sources=list(args.image or []),
                labels=labels if args.image else None,
                require_media=bool(args.image),
                captured=captured,
                captured_label=(labels[0] if labels and not args.image else None),
            )
        except ServiceError as exc:
            print_service_error(exc)
            return 1

    if report is None:
        print_ingest([], result.rejected)
        print("error: no image could be added; no report saved", file=sys.stderr)
        return 1

    print(f"Saved report #{report.id}: {report.title}")
    for path in report.image_paths:
        print(f"  image: {path}")
    if args.image:
        print_ingest(result.added, result.rejected)
    return 1 if result.rejected else 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = current_repo()
    scope = cfg.key if (cfg is not None and not args.all) else None

    with Store() as store:
        reports = store.list(repo=scope)

    if not reports:
        print("No reports yet. Run `bugcap capture` to create one.")
        return 0

    for report in reports:
        tags = f" [{', '.join(report.tags)}]" if report.tags else ""
        print(f"#{report.id}  {report.created_at}  {report.status:8s} {report.title}{tags}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with Store() as store:
        report = resolve_report(store, args.id)
        if report is None:
            return 1

    print(f"#{report.id}  {report.title}")
    print(f"  created_at: {report.created_at}")
    print(f"  status:     {report.status}")
    if report.repo:
        print(f"  repo:       {report.repo}")
    print(f"  tags:       {', '.join(report.tags) or '(none)'}")
    print(f"  notes:      {refs.display_notes(report.notes, report.media) or '(none)'}")
    print(f"  images:")
    for path in report.image_paths:
        print(f"    - {path}")
    detailed = [m for m in report.media if not (m.kind == "image" and m.source == "legacy")]
    if detailed:
        print("  media:")
        for m in detailed:
            where = m.path or f"({len(m.frames)} frames)"
            origin = f"  (source: {m.source})" if m.source else ""
            print(f"    #{m.idx}  {m.kind:8s} {m.label or '-':12s} {where}  {human_size(m.size_bytes)}{origin}")
    print(f"  synced_refs:")
    if report.synced_refs:
        for tracker, ref in report.synced_refs.items():
            print(f"    - {tracker}: {ref}")
    else:
        print("    (not synced to any tracker yet)")
    return 0


# --- setup (T017) -------------------------------------------------------------

def _setup_capture(args: argparse.Namespace) -> int:
    backend = backends.detect()
    if backend is not None:
        print(f"Capture tool found: {backend.name} ({backend.description}).")
        return 0

    rec = backends.recommended()
    cmd = backends.install_command(rec)
    if cmd is None:
        print(
            f"No capture tool found and no supported package manager detected.\n"
            f"Install {rec.name} manually: {backends.guidance(rec)}",
            file=sys.stderr,
        )
        return 1

    joined = " ".join(cmd)
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"No capture tool found. Install {rec.name} with:\n  {joined}\n"
                f"(re-run with --yes to install automatically)",
                file=sys.stderr,
            )
            return 1
        answer = input(f"Install {rec.name}? [y/N] ").strip().lower()
        if answer != "y":
            print("Nothing installed.")
            return 1

    print(f"Installing {rec.name}: {joined}")
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"error: install command failed (exit {rc}).", file=sys.stderr)
        return 1
    print(f"{rec.name} installed.")
    return 0


def _setup_recorder(args: argparse.Namespace) -> None:
    """Recorder lines are appended after the capture-tool output."""
    found = recorder.detect_recorder()
    if found is not None:
        print(f"Screen recorder found: {found.name} ({found.description}).")
        return
    ffmpeg = recorder.by_name("ffmpeg")
    cmd = backends.install_command(ffmpeg)
    print("No screen recorder found (needed for `bugcap record`).")
    print(f"  Install ffmpeg: {' '.join(cmd) if cmd else backends.guidance(ffmpeg)}")
    if backends.platform_key() == "linux" and os.environ.get("WAYLAND_DISPLAY"):
        print(f"  On Wayland, also: {backends.guidance(recorder.by_name('wf-recorder'))}")
    if args.yes and cmd:
        print(f"Installing ffmpeg: {' '.join(cmd)}")
        rc = subprocess.run(cmd).returncode
        print("ffmpeg installed." if rc == 0 else f"error: install command failed (exit {rc}).")


def _setup_tkinter() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        hint = "install your distro's python3-tk package (e.g. sudo apt install python3-tk)" \
            if backends.platform_key() == "linux" else "reinstall Python with Tk support"
        print(f"Live mode (`bugcap live`) needs tkinter, which is missing: {hint}.")
    else:
        print("Live mode: tkinter is available.")


def cmd_setup(args: argparse.Namespace) -> int:
    rc = _setup_capture(args)
    _setup_recorder(args)
    _setup_tkinter()
    return rc


# --- init (T018) --------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    root = repo.git_root() or Path.cwd()
    try:
        cfg = repo.init_repo(
            root,
            tag=args.tag,
            github=args.github,
            images_repo=args.images_repo,
            force=args.force,
        )
    except repo.RepoConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Initialized {repo.CONFIG_NAME} in {cfg.root}")
    print(f"  tag:    {cfg.tag}")
    if cfg.github:
        print(f"  github: {cfg.github}")
    if cfg.images_repo:
        print(f"  images_repo: {cfg.images_repo}")
    return 0


# --- triage: edit / tag (T023) ------------------------------------------------

def cmd_edit(args: argparse.Namespace) -> int:
    if args.title is None and args.note is None and args.status is None:
        print("error: provide at least one of --title, --note, --status", file=sys.stderr)
        return 2
    with Store() as store:
        if resolve_report(store, args.id) is None:
            return 1
        try:
            with store.transaction():
                if args.note is not None:
                    service.set_notes(store, args.id, args.note)
                report = store.update(args.id, title=args.title, status=args.status)
        except ServiceError as exc:
            print_service_error(exc)
            return 1
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    changed = []
    if args.title is not None:
        changed.append("title")
    if args.note is not None:
        changed.append("notes")
    if args.status is not None:
        changed.append("status")
    print(f"Updated report #{report.id} ({', '.join(changed)}).")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    with Store() as store:
        report = resolve_report(store, args.id)
        if report is None:
            return 1
        tags = list(report.tags)
        changed = []
        if args.action == "add":
            for tag in args.tags:
                if tag not in tags:
                    tags.append(tag)
                    changed.append(f"+{tag}")
        else:  # remove
            for tag in args.tags:
                if tag in tags:
                    tags.remove(tag)
                    changed.append(f"-{tag}")
        store.set_tags(args.id, tags)

    label = ", ".join(tags) or "(none)"
    if changed:
        print(f"#{args.id} {' '.join(changed)}  ->  [{label}]")
    else:
        print(f"#{args.id} tags unchanged: [{label}]")
    return 0


# --- attach (T029) ------------------------------------------------------------

def cmd_attach(args: argparse.Namespace) -> int:
    with Store() as store:
        report = resolve_report(store, args.id)
        if report is None:
            return 1
        labels = list(args.label or [])
        if args.image:
            try:
                result = service.add_media(store, args.id, list(args.image), labels)
            except ServiceError as exc:
                print_service_error(exc)
                return 1
            print_ingest(result.added, result.rejected)
            try:
                refs.validate_references(store.get(args.id).notes, store.get(args.id).media)
            except ServiceError as exc:
                print(f"warning: {exc.message}", file=sys.stderr)
            return 1 if result.rejected else 0
        try:
            path = capture.capture_screenshot()
        except CaptureError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            service.attach_captured(store, args.id, str(path), labels[0] if labels else None)
        except ServiceError as exc:
            print_service_error(exc)
            return 1

    print(f"Attached {path} to report #{args.id}")
    return 0


# --- images (list / relabel / remove) -----------------------------------------

def cmd_images(args: argparse.Namespace) -> int:
    with Store() as store:
        report = resolve_report(store, args.id)
        if report is None:
            return 1
        if args.action is None:
            for m in report.media:
                where = m.path or f"({len(m.frames)} frames)"
                print(f"#{m.idx}  {m.label or '-':12s} {m.kind:8s} {human_size(m.size_bytes):>9s}  {where}")
            return 0
        try:
            if args.action == "relabel":
                if len(args.args) != 2:
                    print("error: usage: bugcap images <id> relabel <idx|label> <new-label>", file=sys.stderr)
                    return 2
                count = service.relabel_media(store, args.id, args.args[0], args.args[1], force=args.force)
                print(f"relabelled {args.args[0]} -> {args.args[1]}; rewrote {count} reference(s)")
            else:
                if len(args.args) != 1:
                    print("error: usage: bugcap images <id> remove <idx|label>", file=sys.stderr)
                    return 2
                count = service.remove_media(store, args.id, args.args[0], force=args.force)
                print(f"removed {args.args[0]}; rewrote {count} reference(s)")
        except ServiceError as exc:
            print_service_error(exc)
            if exc.code == "referenced_image":
                print(f"notes: {report.notes}", file=sys.stderr)
            return 1
    return 0


# --- record -------------------------------------------------------------------

def cmd_record(args: argparse.Namespace) -> int:
    if args.backend:
        chosen = recorder.by_name(args.backend)
        if not all(shutil.which(b) for b in chosen.binaries):
            print(f"error: {chosen.name} is not installed. {backends.guidance(chosen)}", file=sys.stderr)
            return 3
    else:
        chosen = recorder.detect_recorder()
        if chosen is None:
            ffmpeg = recorder.by_name("ffmpeg")
            print("error: no screen recorder found. " + backends.guidance(ffmpeg), file=sys.stderr)
            print("Run `bugcap setup` to see install options.", file=sys.stderr)
            return 3

    cfg = current_repo()
    with Store() as store:
        if args.id is not None and resolve_report(store, args.id) is None:
            return 1

    fps = args.fps or (30 if args.format == "video" else 5)
    stop = threading.Event()
    if sys.stdin is not None and sys.stdin.isatty():
        def _wait_enter():
            try:
                sys.stdin.readline()
            finally:
                stop.set()

        threading.Thread(target=_wait_enter, daemon=True).start()
    print(f"Recording with {chosen.name} (max {args.max_seconds} s). Press Enter or Ctrl+C to stop.", file=sys.stderr)
    try:
        result = recorder.run_recording(
            chosen.name, args.format, fps, args.max_seconds, args.max_mb, wait_for_stop=stop.is_set,
        )
    except recorder.RecorderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.guidance:
            print(exc.guidance, file=sys.stderr)
        return 3 if exc.guidance else 1

    tags = list(args.tag or [])
    repo_key = None
    if cfg is not None and args.id is None:
        repo_key = cfg.key
        if cfg.tag not in tags:
            tags.append(cfg.tag)
    with Store() as store:
        try:
            report, media = service.add_recording(
                store, args.id, str(result.path) if result.path else None, result.kind, result.mime,
                result.size_bytes, frame_paths=result.frames or None, title=args.title,
                notes=args.note, tags=tags, repo=repo_key,
            )
        except ServiceError as exc:
            recorder.discard(result)
            print_service_error(exc)
            return 1
    print(f"recorded {result.duration:.1f} s, {human_size(result.size_bytes)} ({result.kind}), stopped: {result.reason}")
    print(f"added #{media.idx} to report #{report.id}")
    return 0


# --- live ---------------------------------------------------------------------

def cmd_live(args: argparse.Namespace) -> int:
    from . import live

    return live.run(args.repo_dir)


# --- dashboard ----------------------------------------------------------------

def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import server

    host = args.host or "127.0.0.1"
    explicit = args.host is not None
    if explicit and host not in server.LOOPBACK:
        print(f"warning: dashboard exposed on {host}; anyone on that network can read and edit your bugs",
              file=sys.stderr)
    try:
        server.serve(host=host, port=args.port, open_browser=args.open, explicit_host=explicit)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


# --- github pull (T029) -------------------------------------------------------

def _ask_screenshot_cb():
    def cb(report, issue) -> Optional[str]:
        prompt = f"Add a screenshot for issue #{issue['number']} {issue['title']!r}? [y/N/path] "
        answer = input(prompt).strip()
        if not answer or answer.lower() == "n":
            return None
        try:
            if answer.lower() == "y":
                return str(capture.capture_screenshot())
            return str(capture.import_image(Path(answer)))
        except CaptureError as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            return None
    return cb


def cmd_github_pull(args: argparse.Namespace) -> int:
    cfg = current_repo()
    slug = args.repo or (cfg.github if cfg else None)
    if not slug:
        print(
            "error: no GitHub repo; pass --repo owner/repo or run `bugcap init` "
            "in a repo with a GitHub origin.",
            file=sys.stderr,
        )
        return 1
    ask_cb = _ask_screenshot_cb() if args.ask else None
    try:
        with Store() as store:
            summary = sync.pull_issues(store, slug, labels=args.label, limit=args.limit, ask_cb=ask_cb)
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"pulled from {slug}: created {summary['created']}, "
        f"updated {summary['updated']}, unchanged {summary['unchanged']}"
    )
    return 0


# --- sync (T035) --------------------------------------------------------------

_DESTINATIONS = {"github": sync.GitHubDestination}


def _consent_prompt(slug: str, visibility: str) -> bool:
    answer = input(f"Commit image copies to {visibility} repo {slug}? [y/N] ").strip().lower()
    return answer == "y"


def cmd_sync(args: argparse.Namespace) -> int:
    with Store() as store:
        report = resolve_report(store, args.id)
        if report is None:
            return 1

        cfg = current_repo()
        linked = report.synced_refs.get("github.issue", "")
        issue_slug = (
            args.repo
            or (report.repo if report.repo and "/" in report.repo else None)
            or (cfg.github if cfg else None)
            or (linked.split("#")[0] if "#" in linked else None)
        )
        if not issue_slug:
            print(
                "error: no target repo; pass --repo owner/repo or sync from an initialized repo.",
                file=sys.stderr,
            )
            return 1

        destination = _DESTINATIONS[args.to]()
        try:
            destination.ensure_ready()
        except GhError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        images = sync.resolve_images_target(
            args.images_repo, args.images_path, args.images_branch,
            cfg, config.get_sync_defaults(), issue_slug,
        )
        opts = sync.SyncOptions(
            issue_slug=issue_slug,
            images=images,
            assume_yes=args.yes,
            interactive=sys.stdin.isatty(),
            confirm=_consent_prompt,
            max_upload_mb=config.get_max_upload_mb(),
        )
        try:
            result = sync.sync_report(store, report, destination, opts)
        except GhError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if result.issue_url:
        print(f"issue: {result.issue_url}")
    for link in result.image_permalinks:
        print(f"image: {link}")
    for message in result.messages:
        print(message)
    return 0


# --- mcp-serve (T040) ---------------------------------------------------------

def cmd_mcp_serve(args: argparse.Namespace) -> int:
    from . import mcp_server
    try:
        mcp_server.run()
    except mcp_server.MCPUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


# --- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugcap",
        description="Local-first, agent-readable bug capture: annotated screenshots + notes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="Detect a capture tool, or recommend/install one.")
    p.add_argument("--yes", action="store_true", help="Install the recommended tool without prompting.")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("init", help="Write .bugcap.toml so captures here are tagged/scoped.")
    p.add_argument("--tag", help="Repo tag (defaults to the directory name).")
    p.add_argument("--github", help="GitHub owner/repo (defaults to the origin remote).")
    p.add_argument("--images-repo", dest="images_repo", help="Repo for committed image copies ([sync]).")
    p.add_argument("--force", action="store_true", help="Overwrite an existing .bugcap.toml.")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("capture", help="Capture (or import) a screenshot and save a report.")
    p.add_argument("--title", help="Short title for the report.")
    p.add_argument("--note", help="Free-form notes/observations.")
    p.add_argument("--tag", action="append", help="Tag to attach (repeatable).")
    p.add_argument("--image", action="append", metavar="SRC",
                   help="Import an image (path, glob or http(s) URL) instead of launching a capture tool; repeatable.")
    p.add_argument("--label", action="append", help="Label for the --image at the same position (repeatable).")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("list", help="List reports (current repo only, unless --all).")
    p.add_argument("--all", action="store_true", help="List reports from every repo.")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="Show a single report in detail.")
    p.add_argument("id", type=int, help="Report id (see `bugcap list`).")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("edit", help="Edit a report's title, notes and/or status.")
    p.add_argument("id", type=int)
    p.add_argument("--title")
    p.add_argument("--note")
    p.add_argument("--status", help=f"One of: {', '.join(STATUSES)}")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("tag", help="Add or remove tags on a report.")
    p.add_argument("id", type=int)
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("tags", nargs="+")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("attach", help="Attach a screenshot (captured or imported) to a report.")
    p.add_argument("id", type=int)
    p.add_argument("--image", action="append", metavar="SRC",
                   help="Import an image (path, glob or http(s) URL) instead of launching a capture tool; repeatable.")
    p.add_argument("--label", action="append", help="Label for the --image at the same position (repeatable).")
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("images", help="List a report's images, or relabel/remove one.")
    p.add_argument("id", type=int)
    p.add_argument("action", nargs="?", choices=["relabel", "remove"])
    p.add_argument("args", nargs="*", help="relabel: <idx|label> <new-label>; remove: <idx|label>")
    p.add_argument("--force", action="store_true", help="Rewrite @ references in the notes instead of refusing.")
    p.set_defaults(func=cmd_images)

    p = sub.add_parser("record", help="Record the screen (video, keyframes or animated GIF) into a report.")
    p.add_argument("--id", type=int, help="Attach to this report (default: create a new one).")
    p.add_argument("--format", choices=list(recorder.FORMATS), default="animated")
    p.add_argument("--max-seconds", dest="max_seconds", type=int, default=30)
    p.add_argument("--fps", type=int, help="Frames per second (default 5, or 30 for video).")
    p.add_argument("--max-mb", dest="max_mb", type=float, default=25)
    p.add_argument("--backend", choices=[b.name for b in recorder.RECORD_BACKENDS])
    p.add_argument("--title")
    p.add_argument("--note")
    p.add_argument("--tag", action="append")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("live", help="Floating control window to capture and report many bugs in a row.")
    p.add_argument("--repo-dir", dest="repo_dir", help="Directory whose .bugcap.toml scopes the reports.")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("dashboard", help="Browse and triage reports in a local web page (127.0.0.1 only).")
    p.add_argument("--port", type=int, default=8765, help="Port (0 picks a free one).")
    p.add_argument("--host", help="Bind address (default 127.0.0.1; anything else exposes your bugs).")
    p.add_argument("--open", action="store_true", help="Open the page in your browser.")
    p.set_defaults(func=cmd_dashboard)

    gh = sub.add_parser("github", help="GitHub integration (via the `gh` CLI).")
    gh_sub = gh.add_subparsers(dest="github_command", required=True)
    pull = gh_sub.add_parser("pull", help="Import issues as reports.")
    pull.add_argument("--repo", help="owner/repo (defaults to .bugcap.toml).")
    pull.add_argument("--label", action="append", help="Filter by label (repeatable).")
    pull.add_argument("--limit", type=int, default=30, help="Max issues (default 30).")
    pull.add_argument("--ask", action="store_true", help="Ask to add a screenshot per issue.")
    pull.set_defaults(func=cmd_github_pull)

    p = sub.add_parser("sync", help="Push a report to a destination (GitHub).")
    p.add_argument("id", type=int)
    p.add_argument("--to", choices=list(_DESTINATIONS), default="github")
    p.add_argument("--repo", help="Issue repo owner/repo.")
    p.add_argument("--images-repo", dest="images_repo", help="Repo to commit image copies to.")
    p.add_argument("--images-path", dest="images_path", help="Directory within the images repo.")
    p.add_argument("--images-branch", dest="images_branch", help="Branch within the images repo.")
    p.add_argument("--yes", action="store_true", help="Accept image-commit consent prompts.")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("mcp-serve", help="Run the stdio MCP server (needs the 'mcp' extra).")
    p.set_defaults(func=cmd_mcp_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
