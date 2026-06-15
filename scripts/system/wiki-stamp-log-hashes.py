#!/usr/bin/env python3
"""Stamp a content hash + mtime onto every wiki/log.jsonl entry (idempotent).

Run from the vault root. Used by wiki-finalize-ingest right after merging the
batch logs, and as the one-time backfill for pre-existing log entries. Recording
the hash lets the ingester recognize a renamed raw note as already-ingested
(same bytes), while still re-ingesting genuinely modified notes.

Usage:
    python3 scripts/system/wiki-stamp-log-hashes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from lib.fixers import stamp_log_hashes  # noqa: E402


def main() -> int:
    root = Path.cwd()
    stamped, total = stamp_log_hashes(root, quiet=False)
    print(f"Stamped {stamped} of {total} "
          f"log entr{'y' if total == 1 else 'ies'} in wiki/log.jsonl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
