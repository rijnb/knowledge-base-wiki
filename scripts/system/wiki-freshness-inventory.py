#!/usr/bin/env python3
"""Build a read-only freshness inventory over raw/ and wiki/."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.freshness_index import build_inventory  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read-only inventory for query-time freshness migration.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Vault root to scan (default: parent of scripts/).",
    )
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
    inventory = build_inventory(root)
    if args.format == "json":
        print(json.dumps(inventory, indent=2, ensure_ascii=False))
    else:
        summary = inventory["summary"]
        print("Freshness inventory")
        print(f"  wiki pages               : {summary['wiki_pages']}")
        print(f"  raw notes                : {summary['raw_notes']}")
        print(f"  canonical blocks         : {summary['canonical_blocks']}")
        print(f"  blocks with provenance   : {summary['blocks_with_provenance']}")
        print(f"  blocks without provenance: {summary['blocks_without_provenance']}")
        print(f"  legacy-inferred pages    : {summary['legacy_inferred_pages']}")
        print(f"  validation issues        : {summary['validation_issues']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
