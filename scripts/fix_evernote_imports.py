#!/usr/bin/env python3
"""
For each note in raw/notes/ containing an "Imported from Evernote" callout:
  1. Extract the "Updated:" date from the callout
  2. Add/update "created_date" in frontmatter
  3. Remove the callout block
"""

import re
import sys
from pathlib import Path

VAULT = Path("/Users/ribu/Obsidian/TomTom")
NOTES_DIR = VAULT / "raw" / "notes"

CALLOUT_PATTERN = re.compile(
    r'>\[!info\]- Imported from Evernote\n'
    r'>Notebook:.*\n'
    r'>Imported:.*\n'
    r'>Created:.*\n'
    r'>Updated: (\d{4}-\d{2}-\d{2})\n'
    r'\n?',  # optional trailing blank line
)

def process_file(path: Path, dry_run: bool = False) -> str | None:
    content = path.read_text(encoding="utf-8")

    m = CALLOUT_PATTERN.search(content)
    if not m:
        return None

    updated_date = m.group(1)

    # Remove all callout blocks (use re.sub to catch duplicates too)
    new_content = CALLOUT_PATTERN.sub("", content)

    # Update/add frontmatter
    if new_content.startswith("---\n"):
        # Frontmatter exists — insert created_date after opening ---
        if "created_date:" in new_content:
            # Replace existing value
            new_content = re.sub(
                r'^created_date:.*$',
                f'created_date: {updated_date}',
                new_content,
                flags=re.MULTILINE,
            )
        else:
            # Insert after opening ---
            new_content = new_content.replace(
                "---\n", f"---\ncreated_date: {updated_date}\n", 1
            )
    else:
        # No frontmatter — prepend one
        new_content = f"---\ncreated_date: {updated_date}\n---\n" + new_content

    if new_content == content:
        return None  # Nothing changed

    if not dry_run:
        path.write_text(new_content, encoding="utf-8")

    return updated_date


def main():
    dry_run = "--dry-run" in sys.argv
    files = list(NOTES_DIR.rglob("*.md"))
    matched = [f for f in files if "Imported from Evernote" in f.read_text(encoding="utf-8", errors="ignore")]

    print(f"Found {len(matched)} notes to process (dry_run={dry_run})")

    processed = 0
    skipped = 0
    for path in matched:
        result = process_file(path, dry_run=dry_run)
        if result:
            processed += 1
        else:
            skipped += 1
            print(f"  SKIP (no change): {path.name}")

    print(f"\nDone. Processed: {processed}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
