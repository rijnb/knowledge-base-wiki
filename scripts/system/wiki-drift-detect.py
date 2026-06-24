#!/usr/bin/env python3
"""Detect canonical pages that deserve one-page freshness curation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.drift import detect_drift, write_queue  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read-only freshness drift detector for wiki/ pages.",
    )
    parser.add_argument("--root", default=None, help="Vault root to scan.")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--write-queue",
        action="store_true",
        help="Write .wiki-scratch/freshness-curation-candidates.md.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Number of candidates to print in text mode (default: 25).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    result = detect_drift(root)
    queue_path = write_queue(root, result) if args.write_queue else None

    if args.format == "json":
        if queue_path:
            result["queue_path"] = str(queue_path.relative_to(root))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        summary = result["summary"]
        print("Freshness drift")
        print(f"  pages checked    : {summary['pages_checked']}")
        print(f"  raw notes checked: {summary['raw_notes_checked']}")
        print(f"  candidates       : {summary['candidates']}")
        for candidate in result["candidates"][:args.limit]:
            print(
                f"  - {candidate['page']} score {candidate['score']} "
                f"({', '.join(candidate['reasons'])})"
            )
        if queue_path:
            print(f"  queue written    : {queue_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
