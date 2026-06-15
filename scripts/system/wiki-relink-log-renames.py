#!/usr/bin/env python3
"""Repoint wiki/log.jsonl entries whose source note was renamed (idempotent).

Run from the vault root. Used by wiki-finalize-ingest right after stamping, and
by wiki-doctor before pruning. Keeps the log's 'file' fields pointing at current
filenames so a renamed note is not orphan-dropped and re-ingested.

Usage:
    python3 scripts/system/wiki-relink-log-renames.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from lib.fixers import relink_renamed_log_entries  # noqa: E402


def main() -> int:
    relinked, ambiguous = relink_renamed_log_entries(Path.cwd(), quiet=False)
    print(f"Relinked {relinked} renamed log "
          f"entr{'y' if relinked == 1 else 'ies'} in wiki/log.jsonl "
          f"({ambiguous} ambiguous skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
