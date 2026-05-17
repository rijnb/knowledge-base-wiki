"""In-place file rewriters for wikilinks and markdown links."""

import re
from pathlib import Path


# A line that is "bare" after a link is removed — optional indent + optional list
# marker + optional empty quote pair + whitespace. Used by delete_* helpers to
# decide whether to drop the whole line.
# Quote pairs: "" '' and their curly variants (via \u escapes).
_BARE_LINE_RE = re.compile(
    r'^\s*(?:[-*+]|\d+\.)?\s*(?:""|\'\'|“”|‘’)?\s*$'
)


def fix_wikilinks_in_file(file_path: Path, fixes: list) -> int:
    """Replace wikilink targets in-place; returns the number of substitutions made."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    count = 0
    for old_target, new_target in fixes:
        pattern = re.compile(r'(?<!!)\[\[' + re.escape(old_target) + r'(?=[\]|#\n]| #)')
        content, n = pattern.subn(f'[[{new_target}', content)
        count += n
    if count:
        file_path.write_text(content, encoding="utf-8")
    return count


def replace_mdlink_target_in_file(file_path: Path, old_target: str, new_target: str) -> int:
    """Replace a markdown link target in-place; returns substitution count."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(' + re.escape(old_target) + r'(?: ?#[^)]*)?\)')
    new_content, n = pattern.subn(lambda m: f'[{m.group(1)}]({new_target})', content)
    if n:
        file_path.write_text(new_content, encoding="utf-8")
    return n


def mark_broken_wikilinks_in_file(file_path: Path, targets: list) -> int:
    """
    For each target in `targets`, rewrite every matching wikilink in file_path:
      [[target]]           -> [[target|(broken link) target]]
      [[target|text]]      -> [[target|(broken link) text]]
      [[target#heading]]   -> [[target#heading|(broken link) target]]
      [[target#heading|text]] -> [[target#heading|(broken link) text]]
    Returns the total number of substitutions made.
    """
    content = file_path.read_text(encoding="utf-8", errors="replace")
    count = 0
    for target in targets:
        pattern = re.compile(
            r'(?<!!)\[\[(' + re.escape(target) + r')( ?#[^|\\\]]*)?(?:\\?(\|[^\]\n]*))?\]\]'
        )
        def _replacer(m, _t=target):
            heading = m.group(2) or ""
            alias_part = m.group(3)          # includes leading '|', or None
            display = alias_part[1:] if alias_part else _t
            return f'[[{_t}{heading}|(broken link) {display}]]'
        content, n = pattern.subn(_replacer, content)
        count += n
    if count:
        file_path.write_text(content, encoding="utf-8")
    return count


def delete_wikilink_in_file(file_path: Path, target: str):
    """Remove [[target...]] from file, collapsing surrounding whitespace.
    If the resulting line is empty or just a bare list marker, the whole line is dropped.
    Returns (changed, removed_linenos) where removed_linenos are 1-indexed lines that
    were fully deleted (so callers can adjust line numbers in sibling entries)."""
    content = file_path.read_text(encoding='utf-8', errors='replace')
    link_pat = re.compile(
        r'( ?)(?<!!)\[\[' + re.escape(target) + r'(?: ?#[^|\\\]]*)?(?:\\?\|[^\]]*)?\]\]( ?)'
    )

    lines = content.splitlines(keepends=True)
    new_lines = []
    changed = False
    removed_linenos: list[int] = []

    for lineno, line in enumerate(lines, 1):
        if not link_pat.search(line):
            new_lines.append(line)
            continue
        def _repl(m):
            return ' ' if (m.group(1) and m.group(2)) else ''
        new_line = link_pat.sub(_repl, line)
        if _BARE_LINE_RE.match(new_line.rstrip('\r\n')):
            changed = True
            removed_linenos.append(lineno)
        else:
            if new_line != line:
                changed = True
            new_lines.append(new_line)

    if changed:
        file_path.write_text(''.join(new_lines), encoding='utf-8')
    return changed, removed_linenos


def delink_wikilink_in_file(file_path: Path, target: str) -> int:
    """Strip [[ ]] brackets from wikilinks, leaving plain text.
    Path prefix and extension are also removed when no alias is present.
    [[x/y/z]] → z,  [[x/y/z|alias]] → alias
    [[target#heading]] → target,  [[target#heading|alias]] → alias
    Returns substitution count."""
    content = file_path.read_text(encoding='utf-8', errors='replace')
    pattern = re.compile(
        r'(?<!!)\[\[' + re.escape(target) + r'(?: ?#[^|\\\]]*)?(?:\\?\|([^\]]*))?\]\]'
    )
    stem = Path(target).stem  # strips any path prefix and extension: x/y/z.md → z
    def _repl(m, _stem=stem):
        alias = m.group(1)
        return alias if alias is not None else _stem
    new_content, n = pattern.subn(_repl, content)
    if n:
        file_path.write_text(new_content, encoding='utf-8')
    return n


def delete_mdlink_in_file(file_path: Path, target: str):
    """Remove [text](target) standard markdown links from file.
    If the resulting line is bare, the whole line is dropped.
    Returns (changed, removed_linenos)."""
    content = file_path.read_text(encoding='utf-8', errors='replace')
    link_pat = re.compile(
        r'( ?)(?<!!)\[[^\]]*\]\(' + re.escape(target) + r'(?: ?#[^)]*)?\)( ?)'
    )

    lines = content.splitlines(keepends=True)
    new_lines = []
    changed = False
    removed_linenos: list[int] = []

    for lineno, line in enumerate(lines, 1):
        if not link_pat.search(line):
            new_lines.append(line)
            continue
        def _repl(m):
            return ' ' if (m.group(1) and m.group(2)) else ''
        new_line = link_pat.sub(_repl, line)
        if _BARE_LINE_RE.match(new_line.rstrip('\r\n')):
            changed = True
            removed_linenos.append(lineno)
        else:
            if new_line != line:
                changed = True
            new_lines.append(new_line)

    if changed:
        file_path.write_text(''.join(new_lines), encoding='utf-8')
    return changed, removed_linenos


def mark_as_broken_link_in_file(file_path: Path, target: str) -> bool:
    """Rewrite [[target]] → [[broken-link|target]] in file. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r'(?<!!)\[\[(' + re.escape(target) + r')( ?#[^|\\\]]*)?(?:\\?(\|[^\]\n]*))?\]\]'
    )
    def _replacer(m, _t=target):
        alias_part = m.group(3)
        display = alias_part[1:] if alias_part else _t
        return f'[[broken-link|{display}]]'
    new_content, n = pattern.subn(_replacer, content)
    if n:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False
