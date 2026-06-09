#!/usr/bin/env python3
"""
wiki-doctor.py — Scan Markdown files for broken internal and external links.

This is a thin shim. The real implementation lives in the `lib/` package
next to this file. Behaviour and CLI surface are unchanged.

Output is structured JSON designed for AI consumption:
  {
    "broken_links": [
      {
        "file": "relative/path/to/file.md",
        "line": 12,
        "type": "wikilink|markdown|image",
        "raw": "[[target]]",
        "target": "target",
        "reason": "file not found"
      },
      ...
    ],
    "summary": { "files_checked": N, "links_checked": N, "broken": N, "skipped_external": N },
    "errors": [ "...", ... ]
  }

Usage:
  python3 wiki-doctor.py [OPTIONS] [ROOT_DIR]

See `--help` for the full option list.
"""

import sys
from pathlib import Path

# Make `lib` importable when the script is invoked directly from the
# scripts/ directory or from anywhere via its absolute path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
