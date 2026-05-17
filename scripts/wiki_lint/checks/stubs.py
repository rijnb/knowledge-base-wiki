"""Detect wiki pages whose body is thinner than a small word threshold."""

import re
from pathlib import Path

from ..frontmatter import has_stub_in_frontmatter


_STUB_WORD_THRESHOLD = 5


def _body_word_count(content: str) -> int:
    """Count prose words in body text, excluding frontmatter, headers, and link-only lines."""
    lines = content.splitlines()
    in_fm = False
    fm_done = False
    count = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if i == 0 and s == "---":
            in_fm = True
            continue
        if in_fm:
            if s in ("---", "..."):
                in_fm = False
                fm_done = True
            continue
        if not fm_done:
            continue
        if s.startswith("#"):
            continue
        if re.match(r'^[-*+]\s*\[\[', s) or s.startswith("[["):
            continue
        if not s:
            continue
        count += len(s.split())
    return count


def check_stubs(root: Path, quiet: bool) -> dict:
    """Find wiki pages (wiki/*/*.md) that look like stubs but lack 'stub: true'.

    Pages already marked 'stub: true' are suppressed (acknowledged stubs).
    Flags pages whose body prose word count falls below _STUB_WORD_THRESHOLD.
    """
    wiki_dir = root / "wiki"
    if not wiki_dir.is_dir():
        return {"stubs": [], "summary": {"wiki_pages_checked": 0, "stubs_found": 0}}

    stubs = []
    wiki_pages_checked = 0
    for md_file in sorted(wiki_dir.glob("*/*.md")):
        if md_file.name in ("index.md", "_index.md"):
            continue
        wiki_pages_checked += 1
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if has_stub_in_frontmatter(content):
            continue  # already acknowledged as a stub
        if _body_word_count(content) < _STUB_WORD_THRESHOLD:
            stubs.append(str(md_file.relative_to(root)))

    return {
        "stubs": sorted(stubs),
        "summary": {"wiki_pages_checked": wiki_pages_checked, "stubs_found": len(stubs)},
    }
