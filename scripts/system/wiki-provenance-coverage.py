#!/usr/bin/env python3
"""Build a full block-provenance coverage backlog for wiki/ pages."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.provenance_coverage import build_coverage_backlog, write_backlog  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Report block-provenance coverage for all wiki/ pages.",
    )
    parser.add_argument("--root", default=None, help="Vault root to scan.")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--write-backlog",
        action="store_true",
        help="Write .wiki-scratch/provenance-coverage-backlog.md.",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=25,
        help="Number of backlog entries to print in text mode (default: 25).",
    )
    return parser.parse_args()


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit must be a non-negative integer")
    return parsed


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    result = build_coverage_backlog(root)
    backlog_path = write_backlog(root, result) if args.write_backlog else None

    if args.format == "json":
        if backlog_path:
            result["backlog_path"] = str(backlog_path.relative_to(root))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        summary = result["summary"]
        print("Provenance coverage")
        print(f"  wiki pages   : {summary['wiki_pages']}")
        print(f"  covered      : {summary['covered_pages']}")
        print(f"  backlog      : {summary['backlog_pages']}")
        print("  by status:")
        for status, count in sorted(summary["by_status"].items()):
            print(f"    - {status}: {count}")
        for page in result["pages"][:args.limit]:
            print(
                f"  - {page['path']} "
                f"({page['coverage_status']}, priority {page['priority']})"
            )
        if backlog_path:
            print(f"  backlog written: {backlog_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
