"""Detect notes whose filenames differ only by accents or diacritics.

Cross-machine sync (APFS preserves NFC, HFS+ forces NFD) combined with the
vault's ASCII-only filename convention can leave two copies of the same page
side by side — e.g. 'Adam Kepinski.md' next to 'Adam Kepiński.md'. Wikilinks
then resolve to either file depending on the machine, and content forks.

This check reports groups of .md files in the SAME directory whose names are
identical once diacritics are stripped. The ASCII-named file (if present) is
the one to keep, per the vault's filename rules.
"""

import os
import sys
import unicodedata
from pathlib import Path

from ..paths import should_skip_md

# Letters with no NFD decomposition that still have an obvious ASCII
# substitute used by the vault's naming convention.
_ASCII_SUBSTITUTES = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th",
    "ß": "ss",
    "æ": "ae", "Æ": "Ae",
    "œ": "oe", "Œ": "Oe",
})


def strip_diacritics(name: str) -> str:
    """Fold a filename stem to its accent-free ASCII-convention form."""
    decomposed = unicodedata.normalize("NFD", name.translate(_ASCII_SUBSTITUTES))
    return unicodedata.normalize(
        "NFC",
        "".join(ch for ch in decomposed if not unicodedata.combining(ch)),
    )


def check_accent_duplicates(root: Path, quiet: bool = False) -> dict:
    """Find same-directory .md files whose names differ only by diacritics."""
    if not quiet:
        print("Checking for accent-duplicate filenames...", file=sys.stderr)

    groups: dict[str, list[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        base = Path(dirpath)
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            p = base / fname
            if should_skip_md(p, root):
                continue
            rel_dir = str(p.parent.relative_to(root))
            key = f"{rel_dir}/{strip_diacritics(p.stem)}"
            groups.setdefault(key, []).append(p)

    duplicates = []
    for key in sorted(groups):
        members = groups[key]
        if len(members) < 2:
            continue
        rels = sorted(str(p.relative_to(root)) for p in members)
        keep = next((r for r in rels if strip_diacritics(Path(r).stem) == Path(r).stem), None)
        duplicates.append({
            "keep": keep,
            "duplicates": [r for r in rels if r != keep] if keep else rels,
        })

    return {
        "accent_duplicates": duplicates,
        "summary": {"accent_duplicates_found": len(duplicates)},
    }
