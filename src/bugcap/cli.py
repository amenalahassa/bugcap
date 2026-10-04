import argparse
import sys

from .capture import CaptureError, capture_screenshot
from .store import Store


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        image_path = capture_screenshot()
    except CaptureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    title = args.title or input("Title: ").strip()
    notes = args.note
    if notes is None:
        notes = input("Notes (optional): ").strip()

    with Store() as store:
        report = store.add(
            title=title,
            notes=notes or "",
            image_paths=[str(image_path)],
            tags=args.tag or [],
        )

    print(f"Saved report #{report.id}: {report.title}")
    print(f"  image: {image_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with Store() as store:
        reports = store.list()

    if not reports:
        print("No reports yet. Run `bugcap capture` to create one.")
        return 0

    for report in reports:
        tags = f" [{', '.join(report.tags)}]" if report.tags else ""
        print(f"#{report.id}  {report.created_at}  {report.status:8s} {report.title}{tags}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with Store() as store:
        report = store.get(args.id)

    if report is None:
        print(f"error: no report with id {args.id}", file=sys.stderr)
        return 1

    print(f"#{report.id}  {report.title}")
    print(f"  created_at: {report.created_at}")
    print(f"  status:     {report.status}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugcap",
        description="Local-first, agent-readable bug capture: annotated screenshots + notes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser(
        "capture", help="Capture and annotate a screenshot, then save a report."
    )
    capture_parser.add_argument("--title", help="Short title for the report.")
    capture_parser.add_argument("--note", help="Free-form notes/observations.")
    capture_parser.add_argument(
        "--tag", action="append", help="Tag to attach (repeatable)."
    )
    capture_parser.set_defaults(func=cmd_capture)

    list_parser = subparsers.add_parser("list", help="List all local reports.")
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show", help="Show a single report in detail.")
    show_parser.add_argument("id", type=int, help="Report id (see `bugcap list`).")
    show_parser.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
