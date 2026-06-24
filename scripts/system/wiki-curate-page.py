#!/usr/bin/env python3
"""Prepare a read-only packet for one-page canonical curation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.curation import build_page_packet  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a read-only one-page curation packet.",
    )
    parser.add_argument("--root", default=None, help="Vault root to scan.")
    parser.add_argument("--page", required=True, help="Wiki page path or WikiLink.")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    try:
        packet = build_page_packet(root, args.page)
    except FileNotFoundError as exc:
        if args.format == "json":
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(packet, indent=2, ensure_ascii=False))
    else:
        page = packet["page"]
        drift = packet["drift"]
        print("Curation packet")
        print(f"  page             : {page['path']}")
        print(f"  title            : {page['title']}")
        print(f"  blocks           : {len(page['blocks'])}")
        print(f"  validation issues: {len(page['validation_issues'])}")
        print(f"  drift score      : {drift['score']}")
        print(f"  drift reasons    : {', '.join(drift['reasons']) or '-'}")
        print(f"  related raw notes: {len(packet['related_raw'])}")
        print(f"  suggested actions: {', '.join(packet['suggested_actions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
