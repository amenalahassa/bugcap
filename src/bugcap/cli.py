import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import backends, capture, config, repo, sync
from .capture import CaptureError
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


# --- capture / list / show ----------------------------------------------------

def cmd_capture(args: argparse.Namespace) -> int:
    cfg = current_repo()
    try:
        if args.image:
            image_path = capture.import_image(Path(args.image))
        else:
            image_path = capture.capture_screenshot()
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

    with Store() as store:
        report = store.add(
            title=title,
            notes=notes or "",
            image_paths=[str(image_path)],
            tags=tags,
            repo=repo_key,
        )

    print(f"Saved report #{report.id}: {report.title}")
    print(f"  image: {image_path}")
    return 0


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
    print(f"  notes:      {report.notes or '(none)'}")
    print(f"  images:")
    for path in report.image_paths:
        print(f"    - {path}")
    print(f"  synced_refs:")
    if report.synced_refs:
        for tracker, ref in report.synced_refs.items():
            print(f"    - {tracker}: {ref}")
    else:
        print("    (not synced to any tracker yet)")
    return 0


# --- setup (T017) -------------------------------------------------------------

def cmd_setup(args: argparse.Namespace) -> int:
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
            report = store.update(args.id, title=args.title, notes=args.note, status=args.status)
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
        if resolve_report(store, args.id) is None:
            return 1
        try:
            if args.image:
                path = capture.import_image(Path(args.image))
            else:
                path = capture.capture_screenshot()
        except CaptureError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        store.add_image(args.id, str(path))

    print(f"Attached {path} to report #{args.id}")
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
    p.add_argument("--image", help="Import this image instead of launching a capture tool.")
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
    p.add_argument("--image", help="Import this image instead of launching a capture tool.")
    p.set_defaults(func=cmd_attach)

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
