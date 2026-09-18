#!/usr/bin/env python3
"""
work-backlog.py — Compile the personal topic pages in `work/topics/` into one
backlog. Deterministic: no LLM, no network, and the output is always derivable
from the pages, so it can be regenerated or thrown away at will.

Three modes, one at a time:

  (default)          Compile `work/Backlog.md`: the active portfolio, my open
                     actions grouped by horizon, delegated work grouped by
                     person, overdue reviews, deadlines inside six weeks,
                     structural smells, and the watching/parked list.

  --archive-done D   Move every checked box out of `## Next actions (me)` and
                     `## Delegated` on every topic page and append it to
                     `## Log` as `- D — done: <text>`, carrying the lines
                     indented under it along. Line surgery only — every other
                     byte of the page is preserved — and idempotent, so a
                     second run moves nothing. A checkbox nested under another
                     list item is a subtask and stays where it is; one inside
                     a code block is not a task at all. A page that is not
                     valid UTF-8 is reported on stderr and left untouched.

  --recap PERIOD     Write `work/recaps/<PERIOD>.md`: per topic, the current
                     progress line and the log entries dated inside the
                     period, with closed topics last. PERIOD is `YYYY-MM`,
                     `YYYY-Www`, `YYYY-Www..Www`, `last-month` or `last-week`.
                     Start-of-period progress comes from `work/weekly/YYYY-Www.md`
                     snapshots when they exist (see `load_snapshots`).

Usage:
  python3 scripts/work-backlog.py [--vault DIR] [--today YYYY-MM-DD] [--out FILE] [--dry-run]
  python3 scripts/work-backlog.py --archive-done 2026-09-17 [--dry-run]
  python3 scripts/work-backlog.py --recap 2026-09 [--dry-run]
  python3 scripts/work-backlog.py --recap last-week --today 2026-09-17
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.work_backlog import (  # noqa: E402
    BACKLOG_PATH,
    RECAPS_DIR,
    TOPICS_DIR,
    PeriodError,
    archive_done,
    compile_backlog,
    compile_recap,
    load_snapshots,
    load_topics,
    parse_date,
    parse_period,
    snapshot_at,
)

COMMAND = "scripts/work-backlog.py"


def _write(target: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        sys.stdout.write(text)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"written to {target}")


def mode_compile(root: Path, today: date, out: Path | None, dry_run: bool) -> int:
    topics = load_topics(root)
    if not topics:
        print(f"error: no topic pages under {root / TOPICS_DIR}", file=sys.stderr)
        return 2
    text = compile_backlog(topics, today, COMMAND)
    _write(out or (root / BACKLOG_PATH), text, dry_run)
    if not dry_run:
        active = sum(1 for t in topics if t.status == "active")
        actions = sum(len(t.open_tasks()) for t in topics if not t.is_done)
        print(f"{len(topics)} topics ({active} active), {actions} open actions of mine")
    return 0


def mode_archive(root: Path, day: str, dry_run: bool) -> int:
    if parse_date(day) is None:
        print(f"error: --archive-done wants YYYY-MM-DD, got {day!r}", file=sys.stderr)
        return 2
    topics = load_topics(root)
    if not topics:
        print(f"error: no topic pages under {root / TOPICS_DIR}", file=sys.stderr)
        return 2
    total = 0
    skipped = 0
    for topic in topics:
        # Strict decoding: this is the one mode that writes a topic page back,
        # and `errors="replace"` would turn every byte it could not decode
        # into a U+FFFD that the write would then make permanent. A page that
        # is not valid UTF-8 is reported and left untouched.
        try:
            content = topic.path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            skipped += 1
            print(f"warning: {topic.path.relative_to(root)}: not valid UTF-8 "
                  f"({exc.reason} at byte {exc.start}) — skipped, nothing rewritten",
                  file=sys.stderr)
            continue
        new_content, moved = archive_done(content, day)
        if not moved:
            continue
        total += len(moved)
        print(f"{topic.path.relative_to(root)}: {len(moved)} moved to ## Log")
        for text in moved:
            print(f"  - {text}")
        if not dry_run:
            topic.path.write_bytes(new_content.encode("utf-8"))
    if not total:
        print("no checked boxes to archive")
    elif dry_run:
        print(f"\ndry run — {total} items would move; re-run without --dry-run to write")
    else:
        print(f"\n{total} items archived under {day}")
    if skipped:
        print(f"{skipped} page(s) skipped: not valid UTF-8")
    return 0


def mode_recap(root: Path, period: str, today: date, out: Path | None,
               dry_run: bool) -> int:
    try:
        label, start, end = parse_period(period, today)
    except PeriodError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    topics = load_topics(root)
    if not topics:
        print(f"error: no topic pages under {root / TOPICS_DIR}", file=sys.stderr)
        return 2
    snapshot = snapshot_at(load_snapshots(root), start)
    text = compile_recap(topics, label, start, end, COMMAND, snapshot)
    _write(out or (root / RECAPS_DIR / f"{label}.md"), text, dry_run)
    if not dry_run:
        print(f"{label}: {start.isoformat()} .. {end.isoformat()}"
              + (f", {len(snapshot)} start-of-period progress lines" if snapshot else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vault", type=Path, default=Path(__file__).resolve().parents[1],
                        help="vault root (default: parent of this script's directory)")
    parser.add_argument("--today", help="pretend today is this date (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, help="write here instead of the default path")
    parser.add_argument("--dry-run", action="store_true",
                        help="print instead of writing (topic pages are never rewritten)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--archive-done", metavar="DATE",
                      help="move checked boxes on every topic page into its ## Log")
    mode.add_argument("--recap", metavar="PERIOD",
                      help="YYYY-MM | YYYY-Www | YYYY-Www..Www | last-month | last-week")
    args = parser.parse_args(argv)

    root = args.vault.resolve()
    if not (root / TOPICS_DIR).is_dir():
        print(f"error: no {TOPICS_DIR}/ under {root}", file=sys.stderr)
        return 2

    today = date.today()
    if args.today:
        parsed = parse_date(args.today)
        if parsed is None:
            print(f"error: --today wants YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
            return 2
        today = parsed

    if args.archive_done:
        return mode_archive(root, args.archive_done, args.dry_run)
    if args.recap:
        return mode_recap(root, args.recap, today, args.out, args.dry_run)
    return mode_compile(root, today, args.out, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
