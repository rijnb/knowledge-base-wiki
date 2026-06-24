#!/usr/bin/env python3
"""Apply minimal query-time provenance status blocks to reviewed pages."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.provenance_stamp import DEFAULT_CHECKED, load_stamp_specs, stamp_pages  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stamp reviewed legacy pages with a minimal freshness status block.",
    )
    parser.add_argument(
        "manifest",
        help="JSON manifest containing an auto_ok list of pages to stamp.",
    )
    parser.add_argument("--root", default=None, help="Vault root to update.")
    parser.add_argument(
        "--checked",
        default=DEFAULT_CHECKED,
        help=f"Checked date to record in YYYY-MM-DD form (default: {DEFAULT_CHECKED}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing pages.",
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
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = root / manifest
    result = stamp_pages(
        root,
        load_stamp_specs(manifest),
        checked=args.checked,
        dry_run=args.dry_run,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Minimal provenance stamp")
        for action, count in sorted(result["summary"].items()):
            print(f"  {action}: {count}")
        for item in result["results"]:
            detail = f" ({item['reason']})" if item.get("reason") else ""
            print(f"  - {item['page']}: {item['action']}{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
