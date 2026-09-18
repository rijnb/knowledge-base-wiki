#!/usr/bin/env python3
"""
work-weekly.py — Gather the data packet for the Monday weekly review.

Deterministic: no LLM, no network. It reads the topic pages, the stakeholder
table, the raw folders and the wiki ingest log, and prints one document with
eight sections:

  Snapshot                     one `- [[Topic]] — <progress>` line per live
                               topic, in the shape `work-backlog.py --recap`
                               reads back from `work/weekly/YYYY-Www.md`
  Backlog                      the compiled backlog, headings demoted one level
  Stakeholder cadence          who is past their cadence, which raw file is the
                               evidence for the last contact and why it counts
                               (a diary title, a sender, a small recipient
                               list, an attendee list), plus the files that
                               merely name them and were *not* counted
  New on my topics since D     raw notes that name a topic or one of its
                               `related` pages, grouped by topic; notes that
                               only share a goal or a stakeholder are one
                               count per topic. Watched and parked topics come
                               after the active ones
  Unmapped new material        raw notes in the window that map to no topic,
                               plus links shared by two or more of them
  New or changed wiki pages    from `wiki/log.jsonl`, ordered by how many
                               topics they touch
  Deadlines and horizon flags  deadlines inside six weeks; `horizon: next`
                               topics that should probably be `now`
  Interaction check            active pairs sharing a stakeholder or goal but
                               not each other's `related`, and next actions
                               that name another topic

The judgement — what a new page means, what to do about it — belongs to the
`work-weekly` skill, which writes `work/weekly/YYYY-Www.md` from this packet.

Usage:
  python3 scripts/work-weekly.py [--today YYYY-MM-DD] [--since YYYY-MM-DD]
  python3 scripts/work-weekly.py --format json --out packet.json
  python3 scripts/work-weekly.py --vault DIR --out work/weekly/packet.md
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.work_backlog import TOPICS_DIR, load_topics, parse_date  # noqa: E402
from lib.work_weekly import (  # noqa: E402
    build_packet,
    default_since,
    render_json,
    render_markdown,
)

COMMAND = "scripts/work-weekly.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vault", type=Path, default=Path(__file__).resolve().parents[1],
                        help="vault root (default: parent of this script's directory)")
    parser.add_argument("--today", help="pretend today is this date (YYYY-MM-DD)")
    parser.add_argument("--since", help="start of the window (default: a week back, "
                                        "or the last weekly review if that is newer)")
    parser.add_argument("--format", choices=("md", "json"), default="md",
                        help="output format (default: md)")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
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

    since = default_since(root, today)
    if args.since:
        parsed = parse_date(args.since)
        if parsed is None:
            print(f"error: --since wants YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            return 2
        since = parsed
    if since >= today:
        print(f"error: --since {since.isoformat()} is not before "
              f"--today {today.isoformat()}", file=sys.stderr)
        return 2

    topics = load_topics(root)
    if not topics:
        print(f"error: no topic pages under {root / TOPICS_DIR}", file=sys.stderr)
        return 2

    packet = build_packet(root, topics, today, since, COMMAND)
    text = render_json(packet) if args.format == "json" else render_markdown(packet, COMMAND)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
