"""Link regex patterns, extraction, and a few shared text utilities."""

import re


# Matches [[target]], [[target|alias]] — Obsidian wikilinks.
# Captures only the target portion (before any | delimiter).
# A single ']' that is NOT followed by another ']' is allowed inside the target
# (e.g. [[example [1] of a note]]), while ']]' ends the link.
# Double quotes and '#' are permitted inside targets (e.g. [[raw/some/link/This is "A Valid" Note.md]],
# [[notes/Issue #42 follow-up]]); '#' is no longer treated as an anchor separator at the regex level.
# '\|' (backslash-pipe) is also treated as a separator, as required inside markdown tables.
RE_WIKILINK = re.compile(r'(?<!!)\[\[((?:[^\]|\n\\]|\\(?!\|)|\](?!\]))+)')
# Matches ![[target]] — Obsidian image embeds (same bracket rule applies)
RE_IMAGE_EMBED = re.compile(r'!\[\[((?:[^\]|\n\\]|\\(?!\|)|\](?!\]))+)')
# Matches [text](target) — standard markdown links; skips http/https separately
RE_MDLINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)#\n]+?)(?:#[^)]*)?\)')
# Matches ![alt](target) — standard markdown images
RE_MDIMAGE = re.compile(r'!\[[^\]]*\]\(([^)#\n]+?)(?:#[^)]*)?\)')


CURLY_TO_STRAIGHT = str.maketrans({
    '‘': "'",  # '  LEFT SINGLE QUOTATION MARK
    '’': "'",  # '  RIGHT SINGLE QUOTATION MARK
    '“': '"',  # "  LEFT DOUBLE QUOTATION MARK
    '”': '"',  # "  RIGHT DOUBLE QUOTATION MARK
})
_CURLY_RE = re.compile(r'[‘’“”]')


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "ftp://", "mailto:"))


def strip_frontmatter(content: str) -> tuple[str, int]:
    """
    If content starts with a YAML frontmatter block (--- ... ---), replace it
    with blank lines so line numbers are preserved. Returns (modified_content, fm_end_line).
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content, 0
    for i, line in enumerate(lines[1:], 1):
        if line.strip() in ("---", "..."):
            blanked = [""] * (i + 1)
            return "\n".join(blanked) + "\n" + "".join(lines[i + 1:]), i + 1
    return content, 0  # unclosed frontmatter — don't strip


def extract_links(content: str, include_images: bool, skip_frontmatter: bool = False):
    """Yield (line_number, type, raw_match, target) for every link in content."""
    if skip_frontmatter:
        content, _ = strip_frontmatter(content)
    lines = content.splitlines()
    for lineno, line in enumerate(lines, 1):
        # Obsidian wikilinks
        for m in RE_WIKILINK.finditer(line):
            target = m.group(1).strip()
            if line[m.end():].startswith('|(broken link)') or line[m.end():].startswith('\\|(broken link)'):
                continue  # already marked by --remove-broken-links; skip
            yield lineno, "wikilink", m.group(0), target
        # Obsidian image embeds
        if include_images:
            for m in RE_IMAGE_EMBED.finditer(line):
                target = m.group(1).strip()
                yield lineno, "image", m.group(0), target
        # Standard markdown links
        for m in RE_MDLINK.finditer(line):
            target = m.group(1).strip()
            yield lineno, "markdown", m.group(0), target
        # Standard markdown images
        if include_images:
            for m in RE_MDIMAGE.finditer(line):
                target = m.group(1).strip()
                yield lineno, "image", m.group(0), target
