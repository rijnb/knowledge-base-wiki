"""Check frontmatter tags against the approved vocabulary in config/tags.md.

Two failure modes, both of which the tag pipeline is meant to prevent and
neither of which shows up anywhere else:

* **`unapproved`** — a note carries a tag that is not in `config/tags.md`. The
  vocabulary is closed, so an unapproved tag is either a hand-typed mistake or
  an ingest that bypassed `wiki-tags.py`. Either way nothing will ever match it
  in a `wiki-find` tags pass but that one note.
* **`malformed`** — a tag that breaks the curated shape (one segment, four
  segments, uppercase, a space, a `:` that makes it illegal in Obsidian). These
  are worse than unapproved: Obsidian silently refuses to index several of
  them, so the tag is invisible in the tag pane however many notes declare it.

Pure detection — never writes. The remedy is a human adding the tag to
`config/tags.md`, or a remap run.
"""

from collections import Counter
from pathlib import Path

from ..wiki_assign import load_vocabulary
from ..wiki_tags import iter_notes, parse_tags, split_document, valid_tag


# Reported but not counted as an error: the note is untagged, which is a
# coverage gap for the assign phase to close rather than a fault in the note.
def check_tags(root: Path, quiet: bool = False) -> dict:
    """Find frontmatter tags that are unapproved or malformed."""
    approved = set(load_vocabulary(root / "config" / "tags.md", assignable=False))
    issues: list[dict] = []
    unapproved: Counter = Counter()
    notes_scanned = untagged = 0

    for path in iter_notes(root):
        notes_scanned += 1
        content = path.read_text(encoding="utf-8", errors="replace")
        fm, _ = split_document(content)
        tags = parse_tags(fm)
        if not tags:
            untagged += 1
            continue
        rel = str(path.relative_to(root))
        for tag in tags:
            if not valid_tag(tag):
                issues.append({"file": rel, "tag": tag, "problem": "malformed"})
            elif approved and tag not in approved:
                issues.append({"file": rel, "tag": tag, "problem": "unapproved"})
                unapproved[tag] += 1

    # No vocabulary file means the pipeline has not been set up; say so rather
    # than reporting every tag in the vault as unapproved.
    return {
        "tag_issues": sorted(issues, key=lambda i: (i["file"], i["tag"])),
        "summary": {
            "notes_scanned": notes_scanned,
            "untagged_notes": untagged,
            "vocabulary_size": len(approved),
            "tag_errors": len(issues),
            "malformed": sum(1 for i in issues if i["problem"] == "malformed"),
            "unapproved": sum(1 for i in issues if i["problem"] == "unapproved"),
            "unapproved_tags": [t for t, _ in unapproved.most_common(20)],
        },
    }
