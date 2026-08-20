#!/usr/bin/env python3
"""wiki-backfill-descriptions.py — Backfill `description:` frontmatter.

For every wiki/**/*.md except index.md files: if the YAML frontmatter lacks a
`description:` key, derive a one-line summary via lib.descriptions
.extract_description() and insert `description: "<escaped>"` into the
frontmatter — after the `type:`/`tags:` lines (including block-list tag
values), before the closing ---. All other frontmatter keys (state:,
sources:, generated:, verified:, ...) are left untouched.

Idempotent: a second run changes nothing. Supports --dry-run.

Run from any directory; the wiki path is resolved relative to this script's
parent by default, or override with --wiki-dir.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.descriptions import extract_description, yaml_double_quote  # noqa: E402

ANCHOR_KEY_RE = re.compile(r"(type|tags)\s*:")
DESCRIPTION_KEY_RE = re.compile(r"description\s*:")


def backfill_file(path: Path, dry_run: bool) -> str:
    """Process one page. Returns a status key for the summary counts."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "no_frontmatter"

    end: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
        if DESCRIPTION_KEY_RE.match(lines[i]):
            return "has_description"
    if end is None:
        return "no_frontmatter"  # unclosed frontmatter block

    description = extract_description(content)
    if not description:
        return "no_summary"

    # Insert after the last top-level type:/tags: entry (skipping any
    # indented block-list continuation lines), else just before the closing ---.
    insert_at = end
    i = 1
    while i < end:
        if ANCHOR_KEY_RE.match(lines[i]):
            j = i + 1
            while j < end and lines[j][:1] in (" ", "\t"):
                j += 1
            insert_at = j
            i = j
        else:
            i += 1

    lines.insert(insert_at, f"description: {yaml_double_quote(description)}\n")
    if not dry_run:
        path.write_text("".join(lines), encoding="utf-8")
    return "inserted"


def resolve_wiki_dir(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).resolve()
    # Default: wiki/ is at the repo root (two levels above scripts/system/)
    return Path(__file__).resolve().parents[2] / "wiki"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--wiki-dir",
        metavar="PATH",
        help=(
            "Path to the wiki directory. "
            "Defaults to 'wiki/' relative to this script's parent directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without modifying any files.",
    )
    args = parser.parse_args()

    wiki_dir = resolve_wiki_dir(args.wiki_dir)
    if not wiki_dir.is_dir():
        print(f"ERROR: wiki directory not found: {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    counts = {
        "inserted": 0,
        "has_description": 0,
        "no_frontmatter": 0,
        "no_summary": 0,
    }
    scanned = 0
    for dirpath, _dirnames, filenames in os.walk(wiki_dir):
        for fname in sorted(filenames):
            if not fname.endswith(".md") or fname == "index.md":
                continue
            fpath = Path(dirpath) / fname
            scanned += 1
            try:
                status = backfill_file(fpath, args.dry_run)
            except OSError as exc:
                print(f"WARNING: cannot process {fpath}: {exc}", file=sys.stderr)
                continue
            counts[status] += 1
            if args.dry_run and status == "inserted":
                print(f"would insert: {os.path.relpath(fpath)}")

    verb = "would insert" if args.dry_run else "inserted"
    print(
        f"Scanned {scanned} pages: {counts['inserted']} {verb}, "
        f"{counts['has_description']} already had description, "
        f"{counts['no_summary']} no extractable summary, "
        f"{counts['no_frontmatter']} without (closed) frontmatter."
    )


if __name__ == "__main__":
    main()
