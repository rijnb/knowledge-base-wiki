#!/usr/bin/env python3
"""Merge .import/batch-log-*.jsonl into wiki/log.jsonl, validating every line.

Run from the vault root. Used by wiki-finalize-ingest as Step 1, replacing a
plain `cat "${logs[@]}" >> wiki/log.jsonl`, which could not tell a valid entry
from a half-written one, fused entries across a batch log with no trailing
newline, and deleted the batch logs whether or not the append had succeeded.

Malformed lines are quarantined in .import/batch-log-rejected.jsonl rather than
appended or dropped. The batch-log and batch-import files are removed only after
the merged log has been written successfully.

Usage:
    python3 scripts/system/wiki-merge-batch-logs.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from lib.batch_logs import merge_batch_logs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be merged without writing.")
    args = parser.parse_args()

    root = Path.cwd()
    try:
        result = merge_batch_logs(root, quiet=False, dry_run=args.dry_run)
    except OSError as e:
        print(f"Merge failed: {e}\n"
              f"wiki/log.jsonl is unchanged and the batch logs are still in "
              f".import/ — fix the cause and re-run.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Dry run: {result['merged']} entr"
              f"{'y' if result['merged'] == 1 else 'ies'} from "
              f"{len(result['files'])} batch log(s) would be merged; "
              f"{result['rejected']} line(s) would be quarantined.")
    # A non-zero exit means the merge did not happen. Quarantined lines are a
    # warning about the input, not a failed merge — finalization continues.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
