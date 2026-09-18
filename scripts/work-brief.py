#!/usr/bin/env python3
"""
work-brief.py — Gather the data packet for a pre-1:1 stakeholder brief.

Deterministic: no LLM, no network. It reads `work/Stakeholders.md`, the topic
pages and the raw folders, and prints one document with six sections:

  Person                       the stakeholder row — needs from me, cadence,
                               channel, last contact with its evidence, next
  Their topics                 the row's `Topics` column plus every topic whose
                               own `stakeholders:` names them; per topic its
                               progress, my first open action, what is
                               delegated to them, and the log since the window
                               opened
  Since last contact           raw notes in `(since, today]` that name them,
                               and separately the ones that land on their
                               topics without naming them — by topic name or
                               `related` page as a file list, by shared goal
                               or stakeholder as one count per topic
  Open asks                    everything delegated to them, and my own open
                               actions that name them
  Other stakeholders …         who else shares at least one of these topics
  Suggested brief skeleton     the five labelled lines — since last time / what
                               I need from you / risk I see / decision needed /
                               FYI — each with 0-3 mechanically picked
                               candidates from the sections above

`PERSON` is matched case-insensitively against the `Person` column: the cell as
written, its wikilink targets, or any unique substring of them (a first name is
usually enough). An ambiguous or unknown name lists the candidates and exits 2.

The judgement — which candidate belongs on which line, and in what words —
belongs to the `work-brief` skill, which writes `work/briefs/YYYY-MM-DD <Person>.md`
from this packet.

Usage:
  python3 scripts/work-brief.py "Someone" [--today YYYY-MM-DD]
  python3 scripts/work-brief.py Someone --since 2026-03-01 --format json
  python3 scripts/work-brief.py Someone --vault DIR --out packet.md
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.work_backlog import TOPICS_DIR, load_topics, parse_date  # noqa: E402
from lib.work_brief import (  # noqa: E402
    PersonError,
    build_brief,
    render_json,
    render_markdown,
    resolve_person,
)
from lib.work_weekly import STAKEHOLDERS_PATH, parse_stakeholders  # noqa: E402

COMMAND = "scripts/work-brief.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("person", metavar="PERSON",
                        help="a row of the Person column, or a unique substring of one")
    parser.add_argument("--vault", type=Path, default=Path(__file__).resolve().parents[1],
                        help="vault root (default: parent of this script's directory)")
    parser.add_argument("--today", help="pretend today is this date (YYYY-MM-DD)")
    parser.add_argument("--since", help="start of the window (default: the resolved "
                                        "last contact, else one cadence back, else "
                                        "14 days)")
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

    since = None
    if args.since:
        since = parse_date(args.since)
        if since is None:
            print(f"error: --since wants YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            return 2
        if since >= today:
            print(f"error: --since {since.isoformat()} is not before "
                  f"--today {today.isoformat()}", file=sys.stderr)
            return 2

    stakeholders = parse_stakeholders(root)
    if not stakeholders:
        print(f"error: no stakeholder table in {root / STAKEHOLDERS_PATH}",
              file=sys.stderr)
        return 2
    try:
        person = resolve_person(stakeholders, args.person)
    except PersonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    topics = load_topics(root)
    if not topics:
        print(f"error: no topic pages under {root / TOPICS_DIR}", file=sys.stderr)
        return 2

    brief = build_brief(root, topics, stakeholders, person, today, since)
    text = render_json(brief) if args.format == "json" else render_markdown(brief, COMMAND)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
