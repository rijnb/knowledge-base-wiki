#!/usr/bin/env python3
"""List or delete the batch-import / batch-log files under .import/.

Run from the vault root. Used by the wiki-clear-ingest-batches skill: call with
--list first to show the user exactly what will go (and how many ingest records
would be lost with it), then with --apply once they confirm.

Replaces an inline `rm -f` over two overlapping globs, which double-counted every
claimed batch, reported its count before deleting anything, and resolved
`.import/` against whatever the current directory happened to be.

Usage:
    python3 scripts/system/wiki-clear-ingest-batches.py --list
    python3 scripts/system/wiki-clear-ingest-batches.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from lib.batch_logs import clear_ingest_batches  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="Show what would be deleted; change nothing.")
    group.add_argument("--apply", action="store_true",
                       help="Delete the listed files.")
    args = parser.parse_args()

    root = Path.cwd()
    if not (root / ".import").is_dir():
        print("No .import/ directory here — run from the vault root.",
              file=sys.stderr)
        return 1

    result = clear_ingest_batches(root, dry_run=args.list)

    if not result["files"]:
        print("No ingestion batch files in .import/ — nothing to clear.")
        return 0

    if args.list:
        print(f"{len(result['files'])} file(s) would be deleted:")
        for name in result["files"]:
            print(f"  {name}")
        if result["unmerged_log_entries"]:
            sys.stdout.flush()  # keep the warning below the file list when piped
            print(f"\nWARNING: {result['unmerged_log_entries']} ingest record(s) "
                  f"in these batch logs have not been merged into wiki/log.jsonl. "
                  f"Clearing discards them, and those notes will be re-ingested "
                  f"on the next import. Run wiki-finalize-ingest instead to keep "
                  f"them.", file=sys.stderr)
        return 0

    print(f"Cleared {result['deleted']} file(s).")
    for failure in result["failed"]:
        print(f"  FAILED: {failure}", file=sys.stderr)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
