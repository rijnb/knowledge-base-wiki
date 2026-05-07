#!/usr/bin/env python3
"""
wiki-lint-check.py — Scan Markdown files for broken internal and external links.

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
  python3 wiki-lint-check.py [OPTIONS] [ROOT_DIR]

Options:
  --help, -h          Show this help message and exit
  --external          Also check HTTP/HTTPS links (slow; requires network)
  --timeout N         Timeout in seconds for external requests (default: 5)
  --include-images    Also check embedded images (![[...]])
  --format text|json  Output format: 'text' for human-readable (default), 'json' for AI
  --quiet             Suppress progress messages on stderr

ROOT_DIR defaults to the directory containing this script's parent.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------

# Matches [[target]], [[target|alias]], [[target#anchor|alias]] — Obsidian wikilinks.
# Captures only the target portion (before any | or # delimiter).
# A single ']' that is NOT followed by another ']' is allowed inside the target
# (e.g. [[example [1] of a note]]), while ']]' ends the link.
# '"' is excluded to prevent false positives on JSON-like nested structures (e.g. [["a","b"]]).
# '\|' (backslash-pipe) is also treated as a separator, as required inside markdown tables.
RE_WIKILINK = re.compile(r'(?<!!)\[\[((?:[^\]|#\n\\"]|\\(?!\|)|\](?!\]))+)')
# Matches ![[target]] — Obsidian image embeds (same bracket rule applies)
RE_IMAGE_EMBED = re.compile(r'!\[\[((?:[^\]|#\n\\"]|\\(?!\|)|\](?!\]))+)')
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


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

KNOWN_EXTENSIONS = {".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

# Characters that are often replaced by '_' when a title becomes a filename.
_PROBLEMATIC_CHARS = re.compile(r'[_:?*|"<>\\]')


def normalize_name(name: str) -> str:
    """Canonical form for fuzzy matching.

    Replaces '_' and chars typically substituted with '_' in filenames with a
    space, then collapses whitespace. This makes '[[foo: bar]]', '[[foo bar]]',
    and the file 'foo_ bar.md' all map to the same key.
    """
    return re.sub(r'\s+', ' ', _PROBLEMATIC_CHARS.sub(' ', name)).strip().lower()


def build_normalized_index(root: Path) -> dict[str, list[Path]]:
    """Map normalize_name(stem) -> list of .md paths, for fuzzy wikilink matching."""
    index: dict[str, list[Path]] = {}
    for p in root.rglob("*.md"):
        if should_skip_md(p, root):
            continue
        key = normalize_name(p.stem)
        index.setdefault(key, []).append(p)
    return index


def find_normalized_match(target: str, root: Path, norm_index: dict[str, list[Path]]) -> "str | None":
    """Try to match a broken wikilink target by normalizing problematic characters.

    Returns the corrected link text (stem, or relative path if the original
    target included a directory) if exactly one file matches, else None.
    """
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS
    name = candidate.stem if has_known_ext else candidate.name
    key = normalize_name(name)
    if not key:
        return None
    # If the target includes a directory prefix, restrict the search to that subdir.
    if candidate.parent != Path("."):
        subdir = root / candidate.parent
        if subdir.is_dir():
            for p in subdir.glob("*.md"):
                if normalize_name(p.stem) == key:
                    return str(candidate.parent / p.stem)
        return None
    # Vault-wide fuzzy match — only accept a unique result to avoid false fixes.
    matches = norm_index.get(key, [])
    if len(matches) == 1:
        return matches[0].stem
    return None


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


def resolve_wikilink(
    target: str,
    root: Path,
    all_md_stems: dict[str, list[Path]],
    path_suffix_set: "set[str] | None" = None,
) -> bool:
    """
    Resolve an Obsidian wikilink against the vault root.
    Wikilinks can be:
      - a bare filename stem:    people/rijn-buve  →  <root>/people/rijn-buve.md
      - a full path (no ext):    wiki/concepts/foo →  <root>/wiki/concepts/foo.md
      - a full path with ext:    wiki/concepts/foo.md
    Also checks .png/.jpg/.jpeg/.gif/.svg/.pdf for embedded files.
    If the target has no recognized extension, .md is assumed (Obsidian default).

    [[x/y]] is valid if x/y is found anywhere under raw/ or wiki/ (any depth).
    [[x]] is valid if x is found anywhere under raw/ or wiki/.

    Returns True if the target resolves to an existing file.
    """
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS

    # Try exact path first
    if (root / target).exists():
        return True

    # If no recognized extension, try appending .md and other known types.
    # This handles bare names like "my-note", paths like "wiki/concepts/foo",
    # and names with dots that aren't file extensions (e.g. "2024.05.15").
    if not has_known_ext:
        for ext in (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"):
            if (root / (target + ext)).exists():
                return True

    # If the target contains a directory component (e.g. "x/y"), also search
    # under the top-level "wiki/" and "raw/" collections — a link [[x/y]] is
    # valid when wiki/x/y.md or raw/x/y.md exists, regardless of where the
    # linking file lives.
    if candidate.parent != Path("."):
        for top in ("wiki", "raw"):
            if (root / top / target).exists():
                return True
            if not has_known_ext:
                for ext in (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"):
                    if (root / top / (target + ext)).exists():
                        return True

    # Fuzzy match: bare stem against all known markdown files.
    # Only apply when the target has no directory component — a full-path target
    # like [[_resources/foo/bar.md]] must resolve by path, not by stem alone,
    # otherwise any file named bar.md anywhere in the vault would silence the error.
    # Use the full name as the lookup key when there is no recognized extension,
    # so that "v1.2" matches "v1.2.md" rather than looking up "v1".
    if candidate.parent == Path("."):
        stem = candidate.stem if has_known_ext else candidate.name
        if stem in all_md_stems:
            return True

    # Broad suffix search: [[x/y]] is valid if any file under raw/ or wiki/
    # has a path that ends with x/y (at any depth).  Handles cases like
    # [[_resources/foo/bar.pdf]] where the file lives at raw/notes/_resources/foo/bar.pdf,
    # and bare names like [[foo.pdf]] where the file lives at raw/notes/foo.pdf.
    if path_suffix_set is not None:
        # Strip a leading "./" that Obsidian sometimes emits for relative embeds,
        # then normalize curly quotes to straight so both sides match.
        normalized = target
        if normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.translate(CURLY_TO_STRAIGHT)
        if normalized in path_suffix_set:
            return True
        if not has_known_ext:
            if (normalized + ".md") in path_suffix_set:
                return True

    return False


def resolve_wikilink_to_path(target: str, root: Path, stem_index: dict[str, list[Path]]) -> "Path | None":
    """Resolve a wikilink target to an actual Path, or None if unresolvable or ambiguous."""
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS

    exact = root / target
    if exact.exists():
        return exact

    if not has_known_ext:
        exact_md = root / (target + ".md")
        if exact_md.exists():
            return exact_md

    # If the target has a directory component, also look under wiki/ and raw/.
    if candidate.parent != Path("."):
        for top in ("wiki", "raw"):
            if (root / top / target).exists():
                return root / top / target
            if not has_known_ext:
                p = root / top / (target + ".md")
                if p.exists():
                    return p

    stem = candidate.stem if has_known_ext else candidate.name
    matches = stem_index.get(stem, [])
    if len(matches) == 1:
        return matches[0]
    return None  # not found or ambiguous


def resolve_mdlink(target: str, source_file: Path, root: Path, all_md_stems: dict[str, list[Path]]) -> bool:
    """Resolve a standard markdown relative link."""
    if is_external(target):
        return True  # handled separately

    # URL-decode basic percent-encoding (e.g. spaces as %20)
    try:
        from urllib.parse import unquote
        target = unquote(target)
    except Exception:
        pass

    p = (source_file.parent / target).resolve()
    if p.exists():
        return True

    # Also try treating as root-relative
    p2 = (root / target).resolve()
    if p2.exists():
        return True

    return False


def check_external(url: str, timeout: int) -> tuple[bool, str]:
    """Return (ok, reason). Performs a HEAD request, falls back to GET."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "wiki-lint-check/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code == 405:
            # HEAD not allowed — try GET
            try:
                req2 = urllib.request.Request(url, method="GET")
                req2.add_header("User-Agent", "wiki-lint-check/1.0")
                with urllib.request.urlopen(req2, timeout=timeout) as resp:
                    return resp.status < 400, f"HTTP {resp.status}"
            except Exception as e2:
                return False, str(e2)
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

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


def truncate_path(path: str, max_len: int = 40, prefix_len: int = 20) -> str:
    """Truncate path to max_len chars: first prefix_len chars + '...' + tail."""
    if len(path) <= max_len:
        return path
    tail_len = max_len - prefix_len - 3
    if tail_len <= 0:
        return path[:max_len]
    return path[:prefix_len] + "..." + path[-tail_len:]


def delete_wikilink_in_file(file_path: Path, target: str):
    # Remove [[target...]] from file, collapsing surrounding whitespace.
    # If the resulting line is empty or just a bare list marker, the whole line is dropped.
    # Returns (changed, removed_linenos) where removed_linenos are 1-indexed lines that
    # were fully deleted (so callers can adjust line numbers in sibling entries).
    content = file_path.read_text(encoding='utf-8', errors='replace')
    link_pat = re.compile(
        r'( ?)(?<!!)\[\[' + re.escape(target) + r'(?: ?#[^|\\\]]*)?(?:\\?\|[^\]]*)?\]\]( ?)'
    )
    # Bare: optional indent + optional list marker + optional empty quote pair + whitespace.
    # Quote pairs: "" '' and their curly variants (via \u escapes)
    bare_pat = re.compile(
        r'^\s*(?:[-*+]|\d+\.)?\s*(?:""|\'\'|\u201c\u201d|\u2018\u2019)?\s*$'
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
        if bare_pat.match(new_line.rstrip('\r\n')):
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
    bare_pat = re.compile(
        r'^\s*(?:[-*+]|\d+\.)?\s*(?:""|\'\'|\u201c\u201d|\u2018\u2019)?\s*$'
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
        if bare_pat.match(new_line.rstrip('\r\n')):
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


def fix_curly_quotes(root: Path, quiet: bool) -> tuple[int, int, int]:
    """Rename .md files whose stems contain curly quotes and fix curly quotes in all link targets.
    Returns (renamed_files, link_files_changed, links_changed)."""
    # Pass 1: rename files whose stems contain curly quotes
    renamed = 0
    for p in sorted(root.rglob("*.md")):
        if should_skip_md(p, root):
            continue
        if not _CURLY_RE.search(p.stem):
            continue
        new_stem = p.stem.translate(CURLY_TO_STRAIGHT)
        new_path = p.parent / (new_stem + ".md")
        if new_path.exists():
            if not quiet:
                print(f"  Cannot rename {p.name}: {new_path.name} already exists", file=sys.stderr)
            continue
        p.rename(new_path)
        renamed += 1
        if not quiet:
            print(f"  Renamed: {p.name} → {new_path.name}", file=sys.stderr)

    # Pass 2: fix curly quotes inside link targets across all .md files
    link_files = 0
    link_count = 0
    for md_file in sorted(root.rglob("*.md")):
        if should_skip_md(md_file, root):
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _CURLY_RE.search(content):
            continue  # fast-path: no curly quotes anywhere in this file

        counter = [0]

        def _fix_wiki(m, _c=counter):
            inner = m.group(1)
            fixed = inner.translate(CURLY_TO_STRAIGHT)
            if fixed != inner:
                _c[0] += 1
                return f'[[{fixed}'
            return m.group(0)

        def _fix_img(m, _c=counter):
            inner = m.group(1)
            fixed = inner.translate(CURLY_TO_STRAIGHT)
            if fixed != inner:
                _c[0] += 1
                return f'![[{fixed}'
            return m.group(0)

        def _fix_md(m, _c=counter):
            target = m.group(1)
            if is_external(target) or not _CURLY_RE.search(target):
                return m.group(0)
            fixed = target.translate(CURLY_TO_STRAIGHT)
            _c[0] += 1
            offset = m.start(1) - m.start(0)
            full = m.group(0)
            return full[:offset] + fixed + full[offset + len(target):]

        new_content = RE_WIKILINK.sub(_fix_wiki, content)
        new_content = RE_IMAGE_EMBED.sub(_fix_img, new_content)
        new_content = RE_MDLINK.sub(_fix_md, new_content)
        new_content = RE_MDIMAGE.sub(_fix_md, new_content)

        if counter[0]:
            md_file.write_text(new_content, encoding="utf-8")
            link_files += 1
            link_count += counter[0]

    return renamed, link_files, link_count


def should_skip_md(path: Path, root: Path) -> bool:
    """Return True if this .md file should be excluded from scanning."""
    rel = path.relative_to(root)
    # Only scan wiki/ and raw/ — ignore everything else (postponed/, scripts/, etc.)
    if not rel.parts or rel.parts[0] not in ("wiki", "raw"):
        return True
    # Skip files inside hidden directories (any parent component starting with '.')
    if any(part.startswith(".") for part in rel.parts[:-1]):
        return True
    # Skip SKILL.md files (superpowers skill definitions)
    if path.name == "SKILL.md":
        return True
    # Skip index and navigation files
    if path.name in ("index.md", "_index.md", "START_HERE.md"):
        return True
    # Skip the log file — it contains ingest headers with individual page links
    if rel == Path("wiki/log.md"):
        return True
    return False


def build_stem_index(root: Path) -> dict[str, list[Path]]:
    """Build a map from filename stem → list of matching paths (for fuzzy wikilink resolution)."""
    index: dict[str, list[Path]] = {}
    for p in root.rglob("*.md"):
        if should_skip_md(p, root):
            continue
        s = p.stem
        index.setdefault(s, []).append(p)
    return index


def build_path_suffix_set(root: Path) -> set[str]:
    """Build a set of all path suffixes for every file under raw/ and wiki/.

    For a file at raw/notes/_resources/foo/bar.pdf this adds:
      raw/notes/_resources/foo/bar.pdf
      notes/_resources/foo/bar.pdf
      _resources/foo/bar.pdf
      foo/bar.pdf
      bar.pdf

    All entries are normalized (curly quotes → straight) so that a link
    containing a straight apostrophe matches a filename with a curly quote.

    This lets [[x/y]] resolve to a file at wiki/a/b/x/y.md (or any depth).
    """
    suffix_set: set[str] = set()
    for top in ("raw", "wiki"):
        top_dir = root / top
        if not top_dir.is_dir():
            continue
        for p in top_dir.rglob("*"):
            if not p.is_file():
                continue
            parts = p.relative_to(root).parts
            for i in range(len(parts)):
                suffix = "/".join(parts[i:])
                suffix_set.add(suffix.translate(CURLY_TO_STRAIGHT))
    return suffix_set


def has_orphan_false_in_frontmatter(content: str) -> bool:
    """Return True if YAML frontmatter contains 'orphan: false'."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        if re.match(r'\s*orphan\s*:\s*false\s*$', line):
            return True
    return False


def add_orphan_false_to_frontmatter(file_path: Path) -> bool:
    """Add 'orphan: false' to the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if has_orphan_false_in_frontmatter(content):
        return False
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() in ("---", "..."):
                lines.insert(i, "orphan: false\n")
                file_path.write_text(''.join(lines), encoding="utf-8")
                return True
        return False  # unclosed frontmatter
    else:
        file_path.write_text("---\norphan: false\n---\n" + content, encoding="utf-8")
        return True


def remove_orphan_false_from_frontmatter(file_path: Path) -> bool:
    """Remove 'orphan: false' from the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return False
    fm_end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() in ("---", "..."):
            fm_end = i
            break
    if fm_end is None:
        return False
    new_lines = [
        line for i, line in enumerate(lines)
        if not (0 < i < fm_end and re.match(r'\s*orphan\s*:\s*false\s*$', line.rstrip('\r\n')))
    ]
    if len(new_lines) < len(lines):
        file_path.write_text(''.join(new_lines), encoding="utf-8")
        return True
    return False


def has_stub_in_frontmatter(content: str) -> bool:
    """Return True if YAML frontmatter contains 'stub: true'."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        if re.match(r'\s*stub\s*:\s*true\s*$', line):
            return True
    return False


def remove_stub_from_frontmatter(file_path: Path) -> bool:
    """Remove 'stub: true' from the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return False
    fm_end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() in ("---", "..."):
            fm_end = i
            break
    if fm_end is None:
        return False
    new_lines = [
        line for i, line in enumerate(lines)
        if not (0 < i < fm_end and re.match(r'\s*stub\s*:\s*true\s*$', line.rstrip('\r\n')))
    ]
    if len(new_lines) < len(lines):
        file_path.write_text(''.join(new_lines), encoding="utf-8")
        return True
    return False


def add_stub_to_frontmatter(file_path: Path) -> bool:
    """Add 'stub: true' to the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if has_stub_in_frontmatter(content):
        return False
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() in ("---", "..."):
                lines.insert(i, "stub: true\n")
                file_path.write_text(''.join(lines), encoding="utf-8")
                return True
        return False  # unclosed frontmatter
    else:
        file_path.write_text("---\nstub: true\n---\n" + content, encoding="utf-8")
        return True


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


_RAW_TEXT_EXTENSIONS = {".md", ".txt", ".vtt", ".eml"}


def has_raw_reference(stem: str, raw_dir: Path) -> bool:
    """Return True if any text file in raw/ contains a plain-text reference to stem."""
    if not raw_dir.is_dir():
        return False
    target_re = re.compile(r'(?<!\w)' + re.escape(stem) + r'(?:\.md)?(?!\w)')
    for raw_file in raw_dir.rglob("*"):
        if not raw_file.is_file() or raw_file.suffix.lower() not in _RAW_TEXT_EXTENSIONS:
            continue
        try:
            content = raw_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if target_re.search(content):
            return True
    return False


def check_orphans(root: Path, quiet: bool) -> dict:
    """Find wiki pages (wiki/*/*.md) with no backlinks except from index files."""
    wiki_dir = root / "wiki"
    if not wiki_dir.is_dir():
        return {"orphans": [], "summary": {"wiki_pages_checked": 0, "orphans_found": 0}}

    # Collect candidate pages: exactly wiki/<subdir>/<file>.md
    # Exclude index files and pages that explicitly declare orphan: false
    wiki_pages: list[Path] = []
    for md_file in sorted(wiki_dir.glob("*/*.md")):
        if md_file.name in ("index.md", "_index.md"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        if has_orphan_false_in_frontmatter(content):
            continue
        wiki_pages.append(md_file)

    if not quiet:
        print(f"Checking orphans across {len(wiki_pages)} wiki pages ...", file=sys.stderr)

    # Build stem index scoped to wiki pages only (for unambiguous resolution)
    stem_index: dict[str, list[Path]] = {}
    for p in wiki_pages:
        stem_index.setdefault(p.stem, []).append(p)

    # Build backlink map: resolved_path -> set of source_rel (non-index sources only)
    # Also track which wiki pages have outgoing wikilinks.
    backlinks: dict[str, set[str]] = {}
    has_outgoing: set[str] = set()  # wiki page paths that contain at least one outgoing wikilink
    wiki_page_strs = {str(p) for p in wiki_pages}
    scanned = 0
    for md_file in sorted(root.rglob("*.md")):
        rel = md_file.relative_to(root)
        if not rel.parts or rel.parts[0] not in ("wiki", "raw"):
            continue
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        if md_file.name == "SKILL.md":
            continue
        if md_file.name in ("index.md", "_index.md"):
            continue  # index pages don't count as backlink sources

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        scanned += 1
        if not quiet and scanned % 50 == 0:
            print(f"\r  {scanned} files scanned for backlinks ...", end="", flush=True, file=sys.stderr)

        for _, link_type, _, target in extract_links(content, include_images=False):
            if link_type != "wikilink":
                continue
            if not target or target.startswith("#") or is_external(target):
                continue
            resolved = resolve_wikilink_to_path(target, root, stem_index)
            if resolved is not None:
                backlinks.setdefault(str(resolved), set()).add(str(rel))
            # Record that this wiki page has at least one outgoing link
            if str(md_file) in wiki_page_strs:
                has_outgoing.add(str(md_file))

    if not quiet:
        print(f"\r  {scanned} files scanned for backlinks — done.        ", file=sys.stderr)

    # A true orphan has no incoming links AND no outgoing links.
    orphans = [
        str(p.relative_to(root))
        for p in wiki_pages
        if not backlinks.get(str(p)) and str(p) not in has_outgoing
    ]

    return {
        "orphans": sorted(orphans),
        "summary": {
            "wiki_pages_checked": len(wiki_pages),
            "orphans_found": len(orphans),
        },
    }


def replace_plain_references_in_content(content: str, stem: str) -> tuple[str, int]:
    """
    Replace plain-text occurrences of `stem` (and `stem.md`) with `[[stem]]`.
    Skips YAML frontmatter, existing wikilinks, markdown links, and inline code.
    """
    target_re = re.compile(r'(?<!\w)' + re.escape(stem) + r'(?:\.md)?(?!\w)')
    # Regions to skip: [[wikilinks]], [text](url) markdown links, `inline code`
    skip_re = re.compile(r'\[\[[^\]\n]+\]\]|\[(?:[^\]\n]*)\]\([^)\n]*\)|`[^`\n]*`')

    lines = content.splitlines(keepends=True)

    # Find frontmatter end (lines to skip at top)
    fm_end = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() in ("---", "..."):
                fm_end = i + 1
                break

    result = []
    count = 0
    for i, line in enumerate(lines):
        if i < fm_end:
            result.append(line)
            continue
        parts = []
        last = 0
        for m in skip_re.finditer(line):
            safe = line[last:m.start()]
            replaced, n = target_re.subn(f'[[{stem}]]', safe)
            parts.append(replaced)
            count += n
            parts.append(m.group(0))
            last = m.end()
        safe = line[last:]
        replaced, n = target_re.subn(f'[[{stem}]]', safe)
        parts.append(replaced)
        count += n
        result.append(''.join(parts))

    return ''.join(result), count


def fix_orphans(orphans: list[str], root: Path, quiet: bool) -> dict:
    """
    For each orphaned wiki page:
    - Find plain-text references in wiki/ and replace with wikilinks (only wiki/ modified).
    - If wiki/ references were linked: remove 'orphan: false' from the page's frontmatter.
    - If no wiki/ references found but raw/ mentions the stem: add 'orphan: false' to the
      page's frontmatter to acknowledge it is known from raw context.
    Raw files are never modified.
    """
    wiki_dir = root / "wiki"
    raw_dir = root / "raw"
    if not wiki_dir.is_dir():
        return {"fixed_references": 0, "files_changed": 0, "orphans_resolved": 0, "details": []}

    wiki_files = sorted(wiki_dir.rglob("*.md"))

    total_refs = 0
    total_files = 0
    details = []

    for orphan_rel in orphans:
        orphan_path = root / orphan_rel
        stem = orphan_path.stem

        if len(stem) < 3:
            continue  # too short — would cause too many false positives

        refs_linked = 0
        files_touched: list[str] = []

        for wiki_file in wiki_files:
            if wiki_file == orphan_path:
                continue  # don't add self-references

            try:
                content = wiki_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if stem not in content:
                continue  # fast path

            new_content, n = replace_plain_references_in_content(content, stem)
            if n:
                wiki_file.write_text(new_content, encoding="utf-8")
                refs_linked += n
                total_files += 1
                files_touched.append((str(wiki_file.relative_to(root)), n))

        # Update frontmatter on the orphan page itself
        fm_action: "str | None" = None
        if refs_linked > 0:
            # Page now has real wiki backlinks — remove orphan: false if present
            if remove_orphan_false_from_frontmatter(orphan_path):
                fm_action = "removed_orphan_false"
        else:
            # No wiki links found — check raw/ for any mention
            if has_raw_reference(stem, raw_dir):
                if add_orphan_false_to_frontmatter(orphan_path):
                    fm_action = "added_orphan_false"

        if not quiet:
            if refs_linked > 0:
                file_list = ", ".join(f"{f} ({n})" for f, n in files_touched)
                print(f"  {orphan_rel}: [[{stem}]] linked in {file_list}", file=sys.stderr)
            if fm_action == "added_orphan_false":
                print(f"  {orphan_rel}: raw reference found → orphan: false added", file=sys.stderr)
            elif fm_action == "removed_orphan_false":
                print(f"  {orphan_rel}: orphan: false removed (now has wiki links)", file=sys.stderr)

        if refs_linked or fm_action:
            total_refs += refs_linked
            details.append({
                "orphan": orphan_rel,
                "stem": stem,
                "references_linked": refs_linked,
                "files_changed": [f for f, _ in files_touched],
                "frontmatter": fm_action,
            })

    return {
        "fixed_references": total_refs,
        "files_changed": total_files,
        "orphans_resolved": len([d for d in details if d["references_linked"] > 0]),
        "orphans_acknowledged": len([d for d in details if d["frontmatter"] == "added_orphan_false"]),
        "details": details,
    }


def check_vault(root: Path, args) -> dict:
    errors = []
    broken = []
    total_files = 0
    total_links = 0
    skipped_external = 0

    if not root.is_dir():
        return {
            "broken_links": [],
            "summary": {"files_checked": 0, "links_checked": 0, "broken": 0, "skipped_external": 0},
            "errors": [f"Root directory not found: {root}"]
        }

    if not args.quiet:
        print(f"Scanning {root} ...", file=sys.stderr)

    stem_index = build_stem_index(root)
    norm_index = build_normalized_index(root)
    path_suffix_set = build_path_suffix_set(root)
    md_files = sorted(p for p in root.rglob("*.md") if not should_skip_md(p, root))

    for md_file in md_files:
        total_files += 1
        rel = md_file.relative_to(root)

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"Cannot read {rel}: {e}")
            continue

        _, fm_end_line = strip_frontmatter(content)

        for lineno, link_type, raw, target in extract_links(content, args.include_images, args.skip_frontmatter):
            total_links += 1

            # External links
            if is_external(target):
                if args.external:
                    ok, reason = check_external(target, args.timeout)
                    if not ok:
                        broken.append({
                            "file": str(rel),
                            "line": lineno,
                            "type": link_type,
                            "raw": raw,
                            "target": target,
                            "reason": reason,
                        })
                else:
                    skipped_external += 1
                continue

            # Skip empty or anchor-only targets
            if not target or target.startswith("#"):
                total_links -= 1
                continue

            # Resolve
            if link_type == "wikilink" or (link_type == "image" and "[[" in raw):
                ok = resolve_wikilink(target, root, stem_index, path_suffix_set)
            else:
                ok = resolve_mdlink(target, md_file, root, stem_index)

            if not ok:
                entry = {
                    "file": str(rel),
                    "line": lineno,
                    "type": link_type,
                    "raw": raw,
                    "target": target,
                    "reason": "file not found",
                }
                if fm_end_line and lineno <= fm_end_line:
                    entry["in_frontmatter"] = True
                if link_type == "wikilink" or (link_type == "image" and "[[" in raw):
                    fix = find_normalized_match(target, root, norm_index)
                    if fix:
                        entry["suggested_fix"] = fix
                broken.append(entry)

        if not args.quiet and total_files % 50 == 0:
            print(f"\r  {total_files} files scanned ...", end="", flush=True, file=sys.stderr)

    if not args.quiet:
        print(f"\r  {total_files} files scanned — done.        ", file=sys.stderr)

    fixed_links = 0
    fixed_files = 0
    if getattr(args, "fix_simple_errors", False):
        fixes_by_file: dict = {}
        for entry in broken:
            if "suggested_fix" in entry:
                fp = root / entry["file"]
                fixes_by_file.setdefault(fp, []).append(
                    (entry["target"], entry["suggested_fix"])
                )
        for fp, fixes in fixes_by_file.items():
            seen: set = set()
            deduped = [f for f in fixes if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]
            n = fix_wikilinks_in_file(fp, deduped)
            if n:
                fixed_files += 1
                fixed_links += n
                if not args.quiet:
                    rel = fp.relative_to(root)
                    for old_t, new_t in deduped:
                        print(f"  fix: {rel}: [[{old_t}]] → [[{new_t}]]", file=sys.stderr)
        for entry in broken:
            if "suggested_fix" in entry:
                entry["fixed"] = True

        # Delete bullet lines in YAML frontmatter that contain unfixable broken wikilinks
        fm_targets_by_file: dict = {}
        for entry in broken:
            if entry.get("fixed") or not entry.get("in_frontmatter"):
                continue
            if entry["raw"].startswith("[["):
                fp = root / entry["file"]
                fm_targets_by_file.setdefault(fp, []).append(entry["target"])
        fm_deleted_links = 0
        fm_deleted_files = 0
        for fp, targets in fm_targets_by_file.items():
            seen: set = set()
            deduped = [t for t in targets if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            file_changed = False
            for target in deduped:
                changed, _ = delete_wikilink_in_file(fp, target)
                if changed:
                    fm_deleted_links += 1
                    file_changed = True
                    if not args.quiet:
                        rel = fp.relative_to(root)
                        print(f"  fix (fm delete): {rel}: [[{target}]]", file=sys.stderr)
            if file_changed:
                fm_deleted_files += 1
        for entry in broken:
            if not entry.get("fixed") and entry.get("in_frontmatter"):
                if entry["raw"].startswith("[["):
                    entry["fm_deleted"] = True

        q_renamed, q_link_files, q_links = fix_curly_quotes(root, args.quiet)
        if not args.quiet and (q_renamed or q_links):
            print(f"  Curly quotes: {q_renamed} file(s) renamed, "
                  f"{q_links} link(s) updated in {q_link_files} file(s).", file=sys.stderr)

    removed_links = 0
    removed_files = 0
    if getattr(args, "remove_broken_links", False):
        targets_by_file: dict = {}
        for entry in broken:
            if entry.get("fixed"):
                continue
            if entry["raw"].startswith("[["):
                fp = root / entry["file"]
                targets_by_file.setdefault(fp, []).append(entry["target"])
        for fp, targets in targets_by_file.items():
            seen: set = set()
            deduped = [t for t in targets if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            n = mark_broken_wikilinks_in_file(fp, deduped)
            if n:
                removed_files += 1
                removed_links += n
        for entry in broken:
            if not entry.get("fixed") and entry["raw"].startswith("[["):
                entry["removed"] = True
        if not args.quiet and removed_links:
            print(f"  Marked {removed_links} broken link(s) in {removed_files} file(s).", file=sys.stderr)

    summary: dict = {
        "files_checked": total_files,
        "links_checked": total_links,
        "broken": len(broken),
        "skipped_external": skipped_external,
    }
    if getattr(args, "fix_simple_errors", False):
        summary["fixed_links"] = fixed_links
        summary["fixed_files"] = fixed_files
        if fm_deleted_links:
            summary["fm_deleted_links"] = fm_deleted_links
            summary["fm_deleted_files"] = fm_deleted_files
        if q_renamed or q_links:
            summary["quote_renamed_files"] = q_renamed
            summary["quote_updated_links"] = q_links
            summary["quote_updated_link_files"] = q_link_files
    if getattr(args, "remove_broken_links", False):
        summary["removed_links"] = removed_links
        summary["removed_files"] = removed_files

    return {
        "broken_links": broken,
        "summary": summary,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_text(result: dict) -> str:
    lines = []
    s = result["summary"]
    lines.append(f"Checked {s['files_checked']} files, {s['links_checked']} links — "
                 f"{s['broken']} broken, {s['skipped_external']} external skipped.")
    if s.get("fixed_links"):
        lines.append(f"Fixed {s['fixed_links']} link(s) in {s['fixed_files']} file(s).")
    if s.get("fm_deleted_links"):
        lines.append(f"Removed {s['fm_deleted_links']} frontmatter broken link(s) in {s['fm_deleted_files']} file(s).")
    if s.get("removed_links"):
        lines.append(f"Marked {s['removed_links']} broken link(s) in {s['removed_files']} file(s).")
    lines.append("")

    if result["errors"]:
        lines.append("ERRORS:")
        for e in result["errors"]:
            lines.append(f"  ! {e}")
        lines.append("")

    if not result["broken_links"]:
        lines.append("No broken links found.")
    else:
        lines.append("BROKEN LINKS:")
        for b in result["broken_links"]:
            lines.append(f"{b['line']}: {b['file']}")
            lines.append(f"    type  : {b['type']}")
            lines.append(f"    reason: {b['reason']}")
            raw_display = b['raw'][2:] if b['raw'].startswith('[[') else b['raw']
            lines.append(f"    raw   : {raw_display}")
            lines.append(f"    target: {b['target']}")
            if "suggested_fix" in b:
                suffix = " (fixed)" if b.get("fixed") else " (use --fix-simple-errors to apply)"
                lines.append(f"    suggested_fix: {b['suggested_fix']}{suffix}")
            if b.get("removed"):
                lines.append("    action: marked as broken in file")
        lines.append("")

    if "orphans" in result:
        lines.append("")
        os_ = result["orphans"]
        os_s = result.get("orphan_summary", {})
        fix = result.get("orphan_fix")
        if fix:
            parts = [f"{fix['orphans_resolved']} orphan(s) resolved via wiki links"]
            if fix.get("orphans_acknowledged"):
                parts.append(f"{fix['orphans_acknowledged']} acknowledged via raw reference (orphan: false added)")
            lines.append(f"ORPHAN FIX: {', '.join(parts)}; "
                         f"{fix['fixed_references']} reference(s) linked in {fix['files_changed']} file(s).")
        lines.append(f"ORPHAN CHECK: {os_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{os_s.get('orphans_found', len(os_))} orphan(s) remaining.")
        if os_:
            lines.append("ORPHANS (no incoming links except from index pages):")
            for o in os_:
                lines.append(f"  {o}")
        else:
            lines.append("No orphan pages found.")

    if "stubs" in result:
        lines.append("")
        st_ = result["stubs"]
        st_s = result.get("stub_summary", {})
        lines.append(f"STUB CHECK: {st_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{st_s.get('stubs_found', len(st_))} stub(s) found.")
        if st_:
            lines.append("STUBS (thin pages not yet acknowledged with stub: true):")
            for s in st_:
                lines.append(f"  {s}")
        else:
            lines.append("No stub pages found.")

    # Issues summary — shown at the end
    has_issues = result["broken_links"] or result.get("orphans") or result.get("stubs")
    if has_issues:
        lines.append("")
        lines.append("ISSUES SUMMARY:")
        if result["broken_links"]:
            by_type: dict = {}
            for b in result["broken_links"]:
                t = b["type"]
                if t not in by_type:
                    by_type[t] = {"found": 0, "fixed": 0, "remaining": 0}
                by_type[t]["found"] += 1
                if b.get("fixed") or b.get("fm_deleted"):
                    by_type[t]["fixed"] += 1
                else:
                    by_type[t]["remaining"] += 1
            total_fixed = sum(v["fixed"] for v in by_type.values())
            total_remaining = sum(v["remaining"] for v in by_type.values())
            lines.append(f"  broken links : {len(result['broken_links'])} found, {total_fixed} fixed, {total_remaining} remaining")
            for t in sorted(by_type):
                v = by_type[t]
                lines.append(f"     {t:<10}: {v['found']} found, {v['fixed']} fixed, {v['remaining']} remaining")
        if "orphans" in result:
            os_s = result.get("orphan_summary", {})
            fix = result.get("orphan_fix")
            n_found = os_s.get("orphans_found", len(result["orphans"]))
            if fix:
                resolved = fix.get("orphans_resolved", 0)
                ack = fix.get("orphans_acknowledged", 0)
                remaining = n_found - resolved
                detail = f"{resolved} resolved"
                if ack:
                    detail += f", {ack} acknowledged"
                detail += f", {remaining} remaining"
                lines.append(f"  orphans      : {n_found} found, {detail}")
            else:
                lines.append(f"  orphans      : {n_found} found")
        if "stubs" in result:
            st_s = result.get("stub_summary", {})
            n_found = st_s.get("stubs_found", len(result["stubs"]))
            lines.append(f"  stubs        : {n_found} found")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def run_interactive(broken_links: list, orphans: list, stubs: list, root: Path) -> None:
    """Curses-based TUI for reviewing broken links, orphan pages, and stub pages."""
    try:
        import curses as _curses
    except ImportError:
        print("Error: curses module not available on this platform.", file=sys.stderr)
        sys.exit(1)

    if not broken_links and not orphans and not stubs:
        print("No broken links, orphan pages, or stub pages found.")
        return

    all_items = [{"_kind": "link", **b} for b in broken_links] + \
                [{"_kind": "orphan", "file": o} for o in orphans] + \
                [{"_kind": "stub", "file": s} for s in stubs]
    n = len(all_items)
    states: list = [None] * n
    messages: list = [""] * n

    def fmt_line(i: int) -> str:
        item = all_items[i]
        if item["_kind"] in ("orphan", "stub"):
            return f"{i + 1:3d}  {item['file']}"
        return f"{i + 1:3d}  {truncate_path(item['file'])}  {item['target']}"

    def do_delete(i: int) -> str:
        entry = broken_links[i]
        try:
            is_wiki = entry["type"] == "wikilink" or (entry["type"] == "image" and "[[" in entry["raw"])
            if is_wiki:
                ok, removed = delete_wikilink_in_file(root / entry["file"], entry["target"])
            else:
                ok, removed = delete_mdlink_in_file(root / entry["file"], entry["target"])
            if ok and removed:
                # Adjust line numbers for all entries in the same file that came
                # after any deleted line, so the popup context stays accurate.
                for other in broken_links:
                    if other["file"] != entry["file"]:
                        continue
                    shift = sum(1 for dl in removed if dl < other["line"])
                    if shift:
                        other["line"] -= shift
            return "deleted" if ok else "no match — may already be handled"
        except Exception as e:
            return f"error: {e}"

    def do_broken(i: int) -> str:
        entry = broken_links[i]
        try:
            ok = mark_as_broken_link_in_file(root / entry["file"], entry["target"])
            return "broken" if ok else "no match — may already be handled"
        except Exception as e:
            return f"error: {e}"

    def do_delink(i: int) -> str:
        entry = broken_links[i]
        try:
            n = delink_wikilink_in_file(root / entry["file"], entry["target"])
            return "delinked" if n else "no match — may already be handled"
        except Exception as e:
            return f"error: {e}"

    def do_delete_orphan(i: int) -> str:
        try:
            (root / all_items[i]["file"]).unlink()
            return "deleted"
        except Exception as e:
            return f"error: {e}"

    def do_keep_orphan(i: int) -> str:
        try:
            changed = add_orphan_false_to_frontmatter(root / all_items[i]["file"])
            return "kept" if changed else "already kept"
        except Exception as e:
            return f"error: {e}"

    def do_mark_stub_acknowledged(i: int) -> str:
        try:
            changed = add_stub_to_frontmatter(root / all_items[i]["file"])
            return "marked as stub" if changed else "already marked as stub"
        except Exception as e:
            return f"error: {e}"

    def do_edit(i: int) -> str:
        try:
            subprocess.Popen(["open", str(root / all_items[i]["file"])])
            return "opened in editor"
        except Exception as e:
            return f"error: {e}"

    def show_orphan_preview(stdscr, entry: dict, idx: int) -> "str | None":
        """Show scrollable file contents for an orphan. Returns 'd', 'k', or None."""
        try:
            file_lines = (root / entry["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            file_lines = [f"(error reading file: {e})"]

        height, width = stdscr.getmaxyx()
        pop_w = min(max(40, width - 4), width - 2)
        pop_h = min(max(10, height - 4), height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)
        inner_w = pop_w - 4
        list_h = pop_h - 5

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)
        scroll = 0
        sep = "─" * (pop_w - 2)
        hint = "[ d=delete   k=keep as orphan   e=edit   ↑↓=prev/next   PgUp/PgDn=scroll   h=help   Enter/q=close ]"

        while True:
            win.erase()
            win.box()
            title = f" Orphan preview {idx + 1}/{n} "
            try:
                win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
                win.addstr(1, 2, entry["file"][:pop_w - 3])
                win.addstr(2, 1, sep[:pop_w - 2])
            except _curses.error:
                pass
            for row in range(list_h):
                li = scroll + row
                if li >= len(file_lines):
                    break
                try:
                    win.addstr(3 + row, 2, file_lines[li][:inner_w])
                except _curses.error:
                    pass
            try:
                win.addstr(pop_h - 2, max(1, (pop_w - len(hint)) // 2), hint[:pop_w - 2])
            except _curses.error:
                pass
            win.refresh()

            key = win.getch()
            if key in (10, 13, ord("q"), ord("Q"), 27):
                break
            elif key == _curses.KEY_UP:
                del win; stdscr.touchwin(); stdscr.refresh()
                return "prev"
            elif key == _curses.KEY_DOWN:
                del win; stdscr.touchwin(); stdscr.refresh()
                return "next"
            elif key == _curses.KEY_PPAGE:
                scroll = max(0, scroll - list_h)
            elif key == _curses.KEY_NPAGE:
                scroll = min(max(0, len(file_lines) - list_h), scroll + list_h)
            elif key in (ord("d"), ord("D")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "d"
            elif key in (ord("k"), ord("K")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "k"
            elif key in (ord("e"), ord("E")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "e"
            elif key in (ord("h"), ord("H")):
                show_help(stdscr)

        del win
        stdscr.touchwin()
        stdscr.refresh()
        return None

    def show_stub_preview(stdscr, entry: dict, idx: int) -> "str | None":
        """Show scrollable file contents for a stub. Returns 'd', 'k', or None."""
        try:
            file_lines = (root / entry["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            file_lines = [f"(error reading file: {e})"]

        height, width = stdscr.getmaxyx()
        pop_w = min(max(40, width - 4), width - 2)
        pop_h = min(max(10, height - 4), height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)
        inner_w = pop_w - 4
        list_h = pop_h - 5

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)
        scroll = 0
        sep = "─" * (pop_w - 2)
        hint = "[ d=delete   k=acknowledge as stub (add stub: true)   e=edit   ↑↓=prev/next   PgUp/PgDn=scroll   h=help   Enter/q=close ]"

        while True:
            win.erase()
            win.box()
            title = f" Stub preview {idx + 1}/{n} "
            try:
                win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
                win.addstr(1, 2, entry["file"][:pop_w - 3])
                win.addstr(2, 1, sep[:pop_w - 2])
            except _curses.error:
                pass
            for row in range(list_h):
                li = scroll + row
                if li >= len(file_lines):
                    break
                try:
                    win.addstr(3 + row, 2, file_lines[li][:inner_w])
                except _curses.error:
                    pass
            try:
                win.addstr(pop_h - 2, max(1, (pop_w - len(hint)) // 2), hint[:pop_w - 2])
            except _curses.error:
                pass
            win.refresh()

            key = win.getch()
            if key in (10, 13, ord("q"), ord("Q"), 27):
                break
            elif key == _curses.KEY_UP:
                del win; stdscr.touchwin(); stdscr.refresh()
                return "prev"
            elif key == _curses.KEY_DOWN:
                del win; stdscr.touchwin(); stdscr.refresh()
                return "next"
            elif key == _curses.KEY_PPAGE:
                scroll = max(0, scroll - list_h)
            elif key == _curses.KEY_NPAGE:
                scroll = min(max(0, len(file_lines) - list_h), scroll + list_h)
            elif key in (ord("d"), ord("D")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "d"
            elif key in (ord("k"), ord("K")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "k"
            elif key in (ord("e"), ord("E")):
                del win; stdscr.touchwin(); stdscr.refresh()
                return "e"
            elif key in (ord("h"), ord("H")):
                show_help(stdscr)

        del win
        stdscr.touchwin()
        stdscr.refresh()
        return None

    def read_source_context(entry: dict, context: int = 2) -> list:
        """Return list of (lineno, text, is_current) for the line and `context` lines around it."""
        try:
            fp = root / entry["file"]
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            current = entry["line"] - 1  # 0-indexed
            start = max(0, current - context)
            end = min(len(lines), current + context + 1)
            return [(i + 1, lines[i], i == current) for i in range(start, end)]
        except Exception as e:
            return [(entry["line"], f"(error reading file: {e})", True)]

    def show_file_browser(stdscr, broken_target: str = "") -> "Path | None":
        """Browse the vault tree and pick a replacement .md file.
        Returns path relative to root, or None if cancelled."""
        top_names = ("wiki", "raw")
        top_dirs = [root / name for name in top_names if (root / name).is_dir()]
        if not top_dirs:
            top_dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))

        class _Node:
            __slots__ = ("path", "depth", "expanded", "_children")

            def __init__(self, path: Path, depth: int):
                self.path = path
                self.depth = depth
                self.expanded = False
                self._children: "list | None" = None

            @property
            def is_dir(self) -> bool:
                return self.path.is_dir()

            def load_children(self) -> list:
                if self._children is None:
                    kids: list = []
                    try:
                        for p in sorted(self.path.iterdir(),
                                        key=lambda x: (not x.is_dir(), x.name.lower())):
                            if p.name.startswith("."):
                                continue
                            if p.is_dir() or p.suffix.lower() == ".md":
                                kids.append(_Node(p, self.depth + 1))
                    except PermissionError:
                        pass
                    self._children = kids
                return self._children

        root_nodes = [_Node(d, 0) for d in top_dirs]

        def build_visible() -> list:
            out: list = []

            def _walk(nodes: list) -> None:
                for nd in nodes:
                    out.append(nd)
                    if nd.is_dir and nd.expanded:
                        _walk(nd.load_children())

            _walk(root_nodes)
            return out

        height, width = stdscr.getmaxyx()
        pop_w = min(max(50, width - 6), width - 2)
        pop_h = min(max(10, height - 4), height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)

        selected = 0
        scroll_offset = 0

        while True:
            visible = build_visible()
            if not visible:
                del win
                stdscr.touchwin()
                stdscr.refresh()
                return None
            if selected >= len(visible):
                selected = len(visible) - 1

            win.erase()
            win.box()
            title = " Find replacement link "
            try:
                win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
            except _curses.error:
                pass

            if broken_target:
                try:
                    label = "replacing: "
                    win.addstr(1, 2, label, _curses.A_DIM)
                    win.addstr(1, 2 + len(label),
                               broken_target[:max(1, pop_w - 2 - len(label))],
                               _curses.color_pair(5) | _curses.A_BOLD)
                except _curses.error:
                    pass

            nav = "↑↓ navigate   → expand   ← collapse   a-z=jump to name   Enter=select   Esc=cancel"
            try:
                win.addstr(2, max(1, (pop_w - len(nav)) // 2), nav[:pop_w - 2])
            except _curses.error:
                pass
            sep = "─" * (pop_w - 2)
            try:
                win.addstr(3, 1, sep[:pop_w - 2])
            except _curses.error:
                pass

            list_h = pop_h - 5  # rows 4 .. pop_h-2
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + list_h:
                scroll_offset = selected - list_h + 1

            inner_w = pop_w - 4
            for row in range(list_h):
                idx = scroll_offset + row
                if idx >= len(visible):
                    break
                nd = visible[idx]
                indent = "  " * nd.depth
                if nd.is_dir:
                    icon = "▼ " if nd.expanded else "▶ "
                    label = indent + icon + nd.path.name + "/"
                else:
                    label = indent + "  " + nd.path.name
                attr = _curses.A_REVERSE if idx == selected else _curses.A_NORMAL
                try:
                    win.addstr(4 + row, 2, label[:inner_w], attr)
                except _curses.error:
                    pass

            win.refresh()
            key = win.getch()

            if key == 27:  # Escape
                del win
                stdscr.touchwin()
                stdscr.refresh()
                return None
            elif key == _curses.KEY_UP:
                if selected > 0:
                    selected -= 1
            elif key == _curses.KEY_DOWN:
                if selected < len(visible) - 1:
                    selected += 1
            elif key == _curses.KEY_PPAGE:
                page = max(1, list_h - 1)
                selected = max(0, selected - page)
            elif key == _curses.KEY_NPAGE:
                page = max(1, list_h - 1)
                selected = min(len(visible) - 1, selected + page)
            elif key == _curses.KEY_RIGHT:
                nd = visible[selected]
                if nd.is_dir and not nd.expanded:
                    nd.expanded = True
                    nd.load_children()
            elif key == _curses.KEY_LEFT:
                nd = visible[selected]
                if nd.is_dir and nd.expanded:
                    nd.expanded = False
                else:
                    # Jump to and collapse parent
                    for i in range(selected - 1, -1, -1):
                        if visible[i].depth == nd.depth - 1 and visible[i].is_dir:
                            visible[i].expanded = False
                            selected = i
                            break
            elif key in (10, 13):  # Enter
                nd = visible[selected]
                if nd.is_dir:
                    nd.expanded = not nd.expanded
                    if nd.expanded:
                        nd.load_children()
                else:
                    del win
                    stdscr.touchwin()
                    stdscr.refresh()
                    return nd.path.relative_to(root)
            elif 32 <= key <= 126:  # printable ASCII — jump to next matching name
                ch = chr(key).lower()
                n_vis = len(visible)
                for offset in range(1, n_vis + 1):
                    candidate = (selected + offset) % n_vis
                    if visible[candidate].path.name.lower().startswith(ch):
                        selected = candidate
                        break

    def show_search_dialog(stdscr, broken_target: str = "") -> "Path | None":
        """Search for a replacement link by regex across filenames in raw/ and wiki/.
        Default search text is the stem of broken_target (filename only, no directories).
        Returns path relative to root, or None if cancelled."""
        search_text = Path(broken_target).name if broken_target else ""

        top_dirs = [root / name for name in ("wiki", "raw") if (root / name).is_dir()]
        all_files: list[Path] = []
        for td in top_dirs:
            for p in sorted(td.rglob("*")):
                if p.is_file() and not p.name.startswith("."):
                    all_files.append(p.relative_to(root))

        def do_search(pattern: str) -> list[Path]:
            if not pattern:
                return []
            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except re.error:
                return []
            return [p for p in all_files if rx.search(p.name)]

        results: list[Path] = do_search(search_text)
        result_sel = 0

        height, width = stdscr.getmaxyx()
        pop_w = min(max(60, width - 6), width - 2)
        pop_h = min(max(13, height - 4), height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)
        _curses.curs_set(1)

        while True:
            if result_sel < 0:
                result_sel = 0
            if results and result_sel >= len(results):
                result_sel = len(results) - 1

            win.erase()
            win.box()
            title = " Search for link "
            try:
                win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
            except _curses.error:
                pass

            # Row 1: original broken link
            if broken_target:
                label = "broken: "
                try:
                    win.addstr(1, 2, label, _curses.A_DIM)
                    win.addstr(1, 2 + len(label), broken_target[:pop_w - 4 - len(label)],
                               _curses.color_pair(5) | _curses.A_BOLD)
                except _curses.error:
                    pass

            # Row 2: search input
            field_w = max(10, pop_w - 6)
            display_text = search_text[-field_w:] if len(search_text) > field_w else search_text
            try:
                win.addstr(2, 2, "> ")
                win.addstr(2, 4, display_text.ljust(field_w)[:field_w])
            except _curses.error:
                pass

            # Row 3: nav hint
            nav = "type to filter   ↑↓ navigate results   Enter=select   Esc=cancel"
            try:
                win.addstr(3, max(1, (pop_w - len(nav)) // 2), nav[:pop_w - 2], _curses.A_DIM)
            except _curses.error:
                pass

            # Row 4: separator with match count
            n_res = len(results)
            if search_text:
                count_label = f" {n_res} match{'es' if n_res != 1 else ''} "
            else:
                count_label = " type to search "
            sep_fill = "─" * (pop_w - 2)
            mid = max(0, (pop_w - 2 - len(count_label)) // 2)
            sep_line = (sep_fill[:mid] + count_label + sep_fill)[:pop_w - 2]
            try:
                win.addstr(4, 1, sep_line)
            except _curses.error:
                pass

            # Rows 5..pop_h-2: results
            list_h = pop_h - 6
            inner_w = pop_w - 4

            if not results:
                try:
                    if not search_text:
                        msg = "Type to search..."
                    else:
                        try:
                            re.compile(search_text)
                            msg = "No matches."
                        except re.error:
                            msg = "Invalid regex."
                    win.addstr(5, 2, msg[:inner_w], _curses.A_DIM)
                except _curses.error:
                    pass
            else:
                scroll = max(0, result_sel - list_h + 1) if result_sel >= list_h else 0
                for row in range(list_h):
                    idx = scroll + row
                    if idx >= len(results):
                        break
                    rel = str(results[idx])
                    attr = _curses.A_REVERSE if idx == result_sel else _curses.A_NORMAL
                    try:
                        win.addstr(5 + row, 2, rel[:inner_w], attr)
                    except _curses.error:
                        pass

            # Position cursor at end of search input (row 2)
            cursor_x = min(4 + len(display_text), pop_w - 2)
            try:
                win.move(2, cursor_x)
            except _curses.error:
                pass

            win.refresh()
            key = win.getch()

            if key == 27:  # Escape
                break
            elif key in (10, 13):  # Enter — select highlighted result
                if results and 0 <= result_sel < len(results):
                    _curses.curs_set(0)
                    del win
                    stdscr.touchwin()
                    stdscr.refresh()
                    return results[result_sel]
            elif key == _curses.KEY_UP:
                if result_sel > 0:
                    result_sel -= 1
            elif key == _curses.KEY_DOWN:
                if results and result_sel < len(results) - 1:
                    result_sel += 1
            elif key in (8, 127, _curses.KEY_BACKSPACE):
                if search_text:
                    search_text = search_text[:-1]
                    results = do_search(search_text)
                    result_sel = 0
            elif 32 <= key <= 126:  # printable ASCII — append to search
                search_text += chr(key)
                results = do_search(search_text)
                result_sel = 0

        _curses.curs_set(0)
        del win
        stdscr.touchwin()
        stdscr.refresh()
        return None

    def do_find_replace(i: int, new_rel: Path) -> str:
        """Replace the broken link at index i with a link to new_rel (relative to root)."""
        entry = broken_links[i]
        old_target = entry["target"]
        old_file = entry["file"]
        is_wiki = entry["type"] == "wikilink" or (entry["type"] == "image" and "[[" in entry["raw"])
        try:
            if is_wiki:
                new_target = str(new_rel.with_suffix(""))
                count = fix_wikilinks_in_file(root / entry["file"], [(old_target, new_target)])
            else:
                source_dir = (root / entry["file"]).parent
                new_target = os.path.relpath(root / new_rel, source_dir)
                count = replace_mdlink_target_in_file(root / entry["file"], old_target, new_target)
            if count:
                entry["target"] = new_target
                # fix_wikilinks_in_file replaces all occurrences in the file at once.
                # Mark any other unresolved entries with the same file+target as resolved
                # so they don't show up as failed "no match" when the cursor reaches them.
                for j, other in enumerate(broken_links):
                    if j != i and states[j] is None and other["file"] == old_file and other["target"] == old_target:
                        other["target"] = new_target
                        states[j] = "replaced"
                        messages[j] = f"→ {new_rel.stem}"
                return "replaced"
            return "no match — may already be changed"
        except Exception as e:
            return f"error: {e}"

    def show_popup(stdscr, entry: dict, idx: int) -> "str | None":
        """Draw a wide popup with source context and missing link; close on Enter."""
        context_lines = read_source_context(entry)
        missing = entry["target"]

        height, width = stdscr.getmaxyx()
        pop_w = min(max(40, width - 4), width - 2)
        inner_w = pop_w - 4

        def _wrap(lineno, text):
            """Yield (display_str, char_start, char_end, text_offset) per wrapped row."""
            prefix = f"{lineno:4d}  "
            prefix_len = len(prefix)
            text_w = max(1, inner_w - prefix_len)
            indent = " " * prefix_len
            if not text:
                yield (prefix, 0, 0, prefix_len)
                return
            for i in range(0, len(text), text_w):
                chunk = text[i:i + text_w]
                yield ((prefix if i == 0 else indent) + chunk, i, i + len(chunk), prefix_len)

        # Find the link's char span in the source line before wrapping.
        # Use raw_link to locate the link, then narrow to just tgt within it
        # so that surrounding syntax (e.g. [[ ]]) is not highlighted.
        raw_link = entry.get("raw", "")
        tgt = entry.get("target", "")
        link_start = link_end = -1
        for _, src_text, is_cur in context_lines:
            if is_cur:
                if raw_link:
                    raw_pos = src_text.find(raw_link)
                    if raw_pos != -1:
                        tgt_off = raw_link.find(tgt) if tgt else -1
                        if tgt_off != -1:
                            link_start = raw_pos + tgt_off
                            link_end = link_start + len(tgt)
                        else:
                            link_start = raw_pos
                            link_end = raw_pos + len(raw_link)
                if link_start == -1 and tgt:
                    pos = src_text.find(tgt)
                    if pos != -1:
                        link_start = pos
                        link_end = pos + len(tgt)
                break

        # Pre-wrap all context lines so pop_h reflects actual row count
        display_rows: list[tuple[str, bool, int, int, int]] = []
        for lineno, text, is_current in context_lines:
            for disp, cstart, cend, toff in _wrap(lineno, text):
                display_rows.append((disp, is_current, cstart, cend, toff))

        # Layout: 4 header rows + content rows + sep + missing + hint + border = +4 fixed footer
        pop_h = min(4 + len(display_rows) + 4, height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)

        sep = "─" * (pop_w - 2)
        hint = "[ ↑/↓ prev/next   d=delete   b=mark broken   p=plain text   n=navigate   s=search   e=edit   h=help   Enter/q=close ]"

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)
        win.box()
        title = f" Broken link detail {idx + 1}/{n} "
        win.addstr(0, (pop_w - len(title)) // 2, title)
        win.addstr(1, 2, f"file: {entry['file']}"[:pop_w - 3])
        win.addstr(2, 2, f"line: {entry['line']}"[:pop_w - 3])
        win.addstr(3, 1, sep[:pop_w - 2])
        max_content_rows = max(0, pop_h - 8)
        hl_attr = _curses.color_pair(5) | _curses.A_BOLD
        for i, (display, is_current, cstart, cend, toff) in enumerate(display_rows[:max_content_rows]):
            base_attr = _curses.A_NORMAL if is_current else _curses.A_DIM
            text = display[:pop_w - 3]
            try:
                if is_current and link_start != -1 and cstart < link_end and cend > link_start:
                    # Map source-text char offsets to display positions for this row
                    row_hl_s = max(0, link_start - cstart)
                    row_hl_e = min(cend - cstart, link_end - cstart)
                    d_s = min(toff + row_hl_s, len(text))
                    d_e = min(toff + row_hl_e, len(text))
                    if d_s > 0:
                        win.addstr(4 + i, 2, text[:d_s], base_attr)
                    if d_s < d_e:
                        win.addstr(4 + i, 2 + d_s, text[d_s:d_e], hl_attr)
                    if d_e < len(text):
                        win.addstr(4 + i, 2 + d_e, text[d_e:], base_attr)
                else:
                    win.addstr(4 + i, 2, text, base_attr)
            except _curses.error:
                pass
        sep_row = 4 + min(len(display_rows), max_content_rows)
        try:
            win.addstr(sep_row, 1, sep[:pop_w - 2])
            win.addstr(sep_row + 1, 2, f"Missing link: {missing}"[:pop_w - 3])
        except _curses.error:
            pass
        try:
            win.addstr(pop_h - 2, max(1, (pop_w - len(hint)) // 2), hint[:pop_w - 2])
        except _curses.error:
            pass
        win.refresh()

        action = None
        while True:
            key = win.getch()
            if key in (10, 13, ord("q"), ord("Q"), 27):
                break
            elif key == _curses.KEY_UP:
                action = "prev"
                break
            elif key == _curses.KEY_DOWN:
                action = "next"
                break
            elif key in (ord("d"), ord("D")):
                action = "d"
                break
            elif key in (ord("b"), ord("B")):
                action = "b"
                break
            elif key in (ord("p"), ord("P")):
                action = "r"
                break
            elif key in (ord("n"), ord("N")):
                action = "n"
                break
            elif key in (ord("s"), ord("S")):
                action = "s"
                break
            elif key in (ord("e"), ord("E")):
                action = "e"
                break
            elif key in (ord("h"), ord("H")):
                show_help(stdscr)
                win.touchwin()
                win.refresh()

        del win
        stdscr.touchwin()
        stdscr.refresh()
        return action

    def show_help(stdscr) -> None:
        """Show a full-command help dialog. Close with Enter, Esc, or h."""
        help_lines = [
            "NAVIGATION",
            "  ↑ / ↓          Navigate list items",
            "  PgUp / PgDn    Jump a full page",
            "  Enter          Open detail / preview popup",
            "  h              Show this help",
            "  q / Esc        Quit",
            "",
            "BROKEN LINK ACTIONS  (when a broken link is selected)",
            "  d              Delete the broken link from the file",
            "  b              Rewrite as [[broken-link|…]]",
            "  p              Strip [[ ]] brackets — leave plain text",
            "  n              Open file browser to navigate and pick a replacement",
            "  s              Search files in raw/ and wiki/ by regex for a replacement",
            "  e              Open source file in default editor",
            "",
            "ORPHAN PAGE ACTIONS  (when an orphan page is selected)",
            "  d              Delete the orphan page file from disk",
            "  k              Keep orphan, add 'orphan: false' to frontmatter",
            "  e              Open source file in default editor",
            "",
            "STUB PAGE ACTIONS  (when a stub page is selected)",
            "  d              Delete the stub page file from disk",
            "  k              Acknowledge as stub (add 'stub: true' to frontmatter)",
            "  e              Open source file in default editor",
            "",
            "DETAIL / PREVIEW POPUP  (opened with Enter)",
            "  ↑ / ↓          Prev / next item (links); scroll (orphans)",
            "  PgUp / PgDn    Scroll content (orphans)",
            "  d  b  p  n  s  k  e  Same actions as in the main list",
            "  h              Show this help",
            "  Enter / q      Close popup",
        ]

        height, width = stdscr.getmaxyx()
        pop_w = min(max(54, width - 8), width - 2)
        inner_w = pop_w - 4
        content_h = min(len(help_lines), height - 6)
        pop_h = min(content_h + 4, height - 2)
        pop_y = max(0, (height - pop_h) // 2)
        pop_x = max(0, (width - pop_w) // 2)
        sep = "─" * (pop_w - 2)
        close_hint = "[ ↑↓/PgUp/PgDn scroll   Esc / Enter / h to close ]"

        win = _curses.newwin(pop_h, pop_w, pop_y, pop_x)
        win.keypad(True)
        scroll = 0

        while True:
            win.erase()
            win.box()
            title = " Help "
            try:
                win.addstr(0, max(1, (pop_w - len(title)) // 2), title, _curses.A_BOLD)
                win.addstr(1, 1, sep[:pop_w - 2])
            except _curses.error:
                pass

            rows_avail = pop_h - 4
            for row in range(rows_avail):
                li = scroll + row
                if li >= len(help_lines):
                    break
                line = help_lines[li]
                try:
                    attr = _curses.A_BOLD if (line and not line.startswith(" ")) else _curses.A_NORMAL
                    win.addstr(2 + row, 2, line[:inner_w], attr)
                except _curses.error:
                    pass

            try:
                win.addstr(pop_h - 2, max(1, (pop_w - len(close_hint)) // 2), close_hint[:pop_w - 2])
            except _curses.error:
                pass
            if len(help_lines) > rows_avail:
                pct = int(100 * scroll / max(1, len(help_lines) - rows_avail))
                try:
                    win.addstr(pop_h - 2, pop_w - 5, f"{pct:3d}%")
                except _curses.error:
                    pass

            win.refresh()
            key = win.getch()
            if key in (10, 13, 27, ord("q"), ord("Q"), ord("h"), ord("H")):
                break
            elif key == _curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == _curses.KEY_DOWN:
                scroll = min(max(0, len(help_lines) - rows_avail), scroll + 1)
            elif key == _curses.KEY_PPAGE:
                scroll = max(0, scroll - rows_avail)
            elif key == _curses.KEY_NPAGE:
                scroll = min(max(0, len(help_lines) - rows_avail), scroll + rows_avail)

        del win
        stdscr.touchwin()
        stdscr.refresh()

    def curses_main(stdscr):
        _curses.curs_set(0)
        _curses.start_color()
        _curses.use_default_colors()
        _curses.init_pair(1, _curses.COLOR_BLACK, _curses.COLOR_CYAN)  # selected
        _curses.init_pair(2, _curses.COLOR_GREEN, -1)                  # deleted
        _curses.init_pair(3, _curses.COLOR_YELLOW, -1)                 # marked broken
        _curses.init_pair(4, _curses.COLOR_MAGENTA, -1)               # replaced
        _curses.init_pair(5, _curses.COLOR_YELLOW, -1)                 # broken link in popup
        _curses.init_pair(6, _curses.COLOR_WHITE, -1)                  # filename in list
        _curses.init_pair(7, _curses.COLOR_CYAN, -1)                   # file line number in list
        _curses.init_pair(8, _curses.COLOR_BLUE, -1)                   # delinked (plain text)
        _curses.init_pair(9, _curses.COLOR_GREEN, -1)                  # kept orphan
        _curses.init_pair(10, _curses.COLOR_RED, -1)                   # unhandled orphan
        _curses.init_pair(11, _curses.COLOR_CYAN, -1)                  # unhandled stub

        selected = 0
        offset = 0
        n_links = sum(1 for it in all_items if it["_kind"] == "link")
        n_orps = sum(1 for it in all_items if it["_kind"] == "orphan")
        n_stubs = sum(1 for it in all_items if it["_kind"] == "stub")

        def redraw():
            nonlocal offset
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            list_height = height - 4

            header = f"Broken links: {n_links}   Orphans: {n_orps}   Stubs: {n_stubs}"
            stdscr.addstr(0, 0, header[:width - 1])

            sel_kind = all_items[selected]["_kind"] if n > 0 else "link"
            if sel_kind == "orphan":
                hint = "ENTER=preview   d=delete   k=keep as orphan   e=edit   h=help   q=quit"
            elif sel_kind == "stub":
                hint = "ENTER=preview   d=delete   k=acknowledge stub   e=edit   h=help   q=quit"
            else:
                hint = "ENTER=preview   d=delete   b=mark broken   p=plain text   n=navigate   s=search   e=edit   h=help   q=quit"
            stdscr.addstr(1, 0, hint[:width - 1])
            stdscr.addstr(2, 0, ("─" * (width - 1))[:width - 1])

            if selected < offset:
                offset = selected
            elif selected >= offset + list_height:
                offset = selected - list_height + 1

            # Fixed column layout: [prefix=7][num=3][gap=2][file_col][gap=2][link_col]
            avail = width - 1
            _fixed = 12   # prefix(7) + num(3) + gap(2)
            _remaining = max(20, avail - _fixed)
            _col_file_w = max(15, _remaining * 55 // 100)
            _col_link_w = max(10, _remaining - _col_file_w - 2)

            for row in range(list_height):
                idx = offset + row
                if idx >= n:
                    break
                item = all_items[idx]
                state = states[idx]
                is_orphan = item["_kind"] == "orphan"
                is_stub = item["_kind"] == "stub"
                if state == "deleted":
                    prefix = "[DELD] "; state_attr = _curses.color_pair(2)
                elif state == "broken":
                    prefix = "[BRKN] "; state_attr = _curses.color_pair(3)
                elif state == "replaced":
                    prefix = "[FIXD] "; state_attr = _curses.color_pair(4)
                elif state == "delinked":
                    prefix = "[TEXT] "; state_attr = _curses.color_pair(8)
                elif state == "kept":
                    prefix = "[KEEP] "; state_attr = _curses.color_pair(9)
                elif is_orphan:
                    prefix = "[ORPH] "; state_attr = _curses.color_pair(10)
                elif is_stub:
                    prefix = "[STUB] "; state_attr = _curses.color_pair(11)
                else:
                    prefix = "[LINK] "; state_attr = _curses.color_pair(5)
                y = 3 + row
                if idx == selected:
                    try:
                        if is_orphan or is_stub:
                            line = (prefix + f"{idx + 1:3d}  {item['file']}")[:avail]
                        else:
                            fp = truncate_path(item['file'], max_len=_col_file_w, prefix_len=_col_file_w // 2).ljust(_col_file_w)
                            line = (prefix + f"{idx + 1:3d}  {fp}  {item['target']}")[:avail]
                        stdscr.addstr(y, 0, line, _curses.color_pair(1) | _curses.A_BOLD)
                    except _curses.error:
                        pass
                    continue
                x = 0
                resolved = state is not None
                dim = _curses.A_DIM
                if is_orphan or is_stub:
                    file_w = max(1, avail - _fixed)
                    segments = [
                        (prefix,                        state_attr),
                        (f"{idx + 1:3d}",               dim if resolved else _curses.color_pair(2)),
                        ("  ",                          _curses.A_NORMAL),
                        (item['file'][:file_w],         dim if resolved else _curses.color_pair(6) | _curses.A_BOLD),
                    ]
                else:
                    fp = truncate_path(item['file'], max_len=_col_file_w, prefix_len=_col_file_w // 2).ljust(_col_file_w)
                    segments = [
                        (prefix,                                   state_attr),
                        (f"{idx + 1:3d}",                         dim if resolved else _curses.color_pair(2)),
                        ("  ",                                     _curses.A_NORMAL),
                        (fp,                                       dim if resolved else _curses.color_pair(6) | _curses.A_BOLD),
                        ("  ",                                     _curses.A_NORMAL),
                        (item['target'][:_col_link_w],            dim if resolved else _curses.color_pair(5) | _curses.A_BOLD),
                    ]
                for text, attr in segments:
                    if x >= avail or not text:
                        continue
                    try:
                        stdscr.addstr(y, x, text[:avail - x], attr)
                    except _curses.error:
                        pass
                    x += len(text)

            done = sum(1 for s in states if s is not None)
            status = messages[selected] if messages[selected] else ""
            footer = f"  {done}/{n} handled" + (f"  — {status}" if status else "")
            try:
                stdscr.addstr(height - 1, 0, footer[:width - 1])
            except _curses.error:
                pass
            stdscr.refresh()

        while True:
            redraw()
            key = stdscr.getch()

            if key in (ord("q"), ord("Q"), 27):
                break
            elif key in (ord("h"), ord("H")):
                show_help(stdscr)
            elif key == _curses.KEY_UP:
                if selected > 0:
                    selected -= 1
            elif key == _curses.KEY_DOWN:
                if selected < n - 1:
                    selected += 1
            elif key == _curses.KEY_PPAGE:
                height, _ = stdscr.getmaxyx()
                page = max(1, height - 4 - 1)
                selected = max(0, selected - page)
            elif key == _curses.KEY_NPAGE:
                height, _ = stdscr.getmaxyx()
                page = max(1, height - 4 - 1)
                selected = min(n - 1, selected + page)
            elif key in (10, 13):  # Enter — open popup for the selected item
                idx = selected
                while True:
                    redraw()
                    item = all_items[idx]
                    if item["_kind"] == "orphan":
                        action = show_orphan_preview(stdscr, item, idx)
                        if action == "d":
                            res = do_delete_orphan(idx)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "File deleted." if res == "deleted" else res
                        elif action == "k":
                            res = do_keep_orphan(idx)
                            states[idx] = "kept" if res in ("kept", "already kept") else None
                            messages[idx] = res
                        elif action == "e":
                            messages[idx] = do_edit(idx)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    elif item["_kind"] == "stub":
                        action = show_stub_preview(stdscr, item, idx)
                        if action == "d":
                            res = do_delete_orphan(idx)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "File deleted." if res == "deleted" else res
                        elif action == "k":
                            res = do_mark_stub_acknowledged(idx)
                            states[idx] = "kept" if res == "marked as stub" else None
                            messages[idx] = "stub: true added." if res == "marked as stub" else res
                        elif action == "e":
                            messages[idx] = do_edit(idx)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    else:
                        action = show_popup(stdscr, item, idx)
                        if action == "d":
                            res = do_delete(idx)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "Link removed." if res == "deleted" else res
                        elif action == "b":
                            res = do_broken(idx)
                            states[idx] = "broken" if res == "broken" else None
                            messages[idx] = "Marked [[broken-link|…]]." if res == "broken" else res
                        elif action == "r":
                            res = do_delink(idx)
                            states[idx] = "delinked" if res == "delinked" else None
                            messages[idx] = "Brackets removed (plain text)." if res == "delinked" else res
                        elif action == "n":
                            new_rel = show_file_browser(stdscr, item.get("target", ""))
                            if new_rel is not None:
                                res = do_find_replace(idx, new_rel)
                                states[idx] = "replaced" if res == "replaced" else None
                                messages[idx] = f"→ {new_rel.stem}" if res == "replaced" else res
                        elif action == "s":
                            new_rel = show_search_dialog(stdscr, item.get("target", ""))
                            if new_rel is not None:
                                res = do_find_replace(idx, new_rel)
                                states[idx] = "replaced" if res == "replaced" else None
                                messages[idx] = f"→ {new_rel.stem}" if res == "replaced" else res
                        elif action == "e":
                            messages[idx] = do_edit(idx)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    if action in ("d", "b", "r", "k") or (action in ("n", "s") and states[idx] is not None):
                        next_idx = next((i for i in range(idx + 1, n) if states[i] is None), None)
                        if next_idx is not None:
                            idx = next_idx; selected = idx
                            continue
                    selected = idx
                    break
            elif key in (ord("d"), ord("D")):
                if states[selected] is None:
                    item = all_items[selected]
                    if item["_kind"] in ("orphan", "stub"):
                        res = do_delete_orphan(selected)
                        states[selected] = "deleted" if res == "deleted" else None
                        messages[selected] = "File deleted." if res == "deleted" else res
                    else:
                        res = do_delete(selected)
                        states[selected] = "deleted" if res == "deleted" else None
                        messages[selected] = "Link removed." if res == "deleted" else res
            elif key in (ord("k"), ord("K")):
                if states[selected] is None:
                    if all_items[selected]["_kind"] == "orphan":
                        res = do_keep_orphan(selected)
                        states[selected] = "kept" if res in ("kept", "already kept") else None
                        messages[selected] = res
                    elif all_items[selected]["_kind"] == "stub":
                        res = do_mark_stub_acknowledged(selected)
                        states[selected] = "kept" if res == "marked as stub" else None
                        messages[selected] = "stub: true added." if res == "marked as stub" else res
            elif key in (ord("b"), ord("B")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    res = do_broken(selected)
                    states[selected] = "broken" if res == "broken" else None
                    messages[selected] = "Marked [[broken-link|…]]." if res == "broken" else res
                    if states[selected] is not None:
                        next_idx = next((i for i in range(selected + 1, n) if states[i] is None), None)
                        if next_idx is not None:
                            selected = next_idx
            elif key in (ord("p"), ord("P")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    res = do_delink(selected)
                    states[selected] = "delinked" if res == "delinked" else None
                    messages[selected] = "Brackets removed (plain text)." if res == "delinked" else res
                    if states[selected] is not None:
                        next_idx = next((i for i in range(selected + 1, n) if states[i] is None), None)
                        if next_idx is not None:
                            selected = next_idx
            elif key in (ord("n"), ord("N")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    new_rel = show_file_browser(stdscr, all_items[selected].get("target", ""))
                    if new_rel is not None:
                        res = do_find_replace(selected, new_rel)
                        states[selected] = "replaced" if res == "replaced" else None
                        messages[selected] = f"→ {new_rel.stem}" if res == "replaced" else res
                        if states[selected] is not None:
                            next_idx = next((i for i in range(selected + 1, n) if states[i] is None), None)
                            if next_idx is not None:
                                selected = next_idx
            elif key in (ord("s"), ord("S")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    new_rel = show_search_dialog(stdscr, all_items[selected].get("target", ""))
                    if new_rel is not None:
                        res = do_find_replace(selected, new_rel)
                        states[selected] = "replaced" if res == "replaced" else None
                        messages[selected] = f"→ {new_rel.stem}" if res == "replaced" else res
                        if states[selected] is not None:
                            next_idx = next((i for i in range(selected + 1, n) if states[i] is None), None)
                            if next_idx is not None:
                                selected = next_idx
            elif key in (ord("e"), ord("E")):
                messages[selected] = do_edit(selected)

    _curses.wrapper(curses_main)

    deleted_links   = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "link")
    deleted_orphans = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "orphan")
    deleted_stubs   = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "stub")
    broken_count    = sum(1 for s in states if s == "broken")
    replaced_count  = sum(1 for s in states if s == "replaced")
    delinked_count  = sum(1 for s in states if s == "delinked")
    kept_orphans    = sum(1 for i, s in enumerate(states) if s == "kept" and all_items[i]["_kind"] == "orphan")
    kept_stubs      = sum(1 for i, s in enumerate(states) if s == "kept" and all_items[i]["_kind"] == "stub")
    skipped = n - sum(1 for s in states if s is not None)
    print(f"\nSession complete: {deleted_links} links deleted, {broken_count} marked broken, "
          f"{delinked_count} plain text, {replaced_count} replaced, "
          f"{deleted_orphans} orphan pages deleted, {kept_orphans} orphans kept, "
          f"{deleted_stubs} stub pages deleted, {kept_stubs} stubs resolved, {skipped} skipped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def ask_run_auto_fixes() -> bool:
    """Show a centered curses dialog asking whether to run automatic fixes first.
    Enter/Y = yes (default), N/Esc = no."""
    try:
        import curses as _c
    except ImportError:
        _c = None

    result = [True]

    def _dialog(stdscr):
        _c.curs_set(0)
        _c.start_color()
        _c.use_default_colors()
        _c.init_pair(1, _c.COLOR_BLACK, _c.COLOR_CYAN)  # selected button
        _c.init_pair(2, _c.COLOR_YELLOW, -1)             # title

        content = [
            "Apply automatic fixes before interactive review?",
            "",
            "  fix-simple-errors  — repair normalizable broken links",
            "  fix-orphans        — link plain-text references in wiki/",
            "",
            "Only remaining issues will appear in the interactive TUI.",
        ]

        height, width = stdscr.getmaxyx()
        box_w = min(max(len(l) for l in content) + 6, width - 4)
        # rows: top border + sep + content + sep + buttons + bottom border
        box_h = min(len(content) + 5, height - 4)
        by = max(0, (height - box_h) // 2)
        bx = max(0, (width - box_w) // 2)

        selected = 0  # 0 = Yes, 1 = No

        win = _c.newwin(box_h, box_w, by, bx)
        win.keypad(True)

        while True:
            win.erase()
            win.box()

            title = " Wiki Lint — Auto-fix "
            try:
                win.addstr(0, max(1, (box_w - len(title)) // 2), title,
                           _c.color_pair(2) | _c.A_BOLD)
            except _c.error:
                pass

            sep = "─" * (box_w - 2)
            try:
                win.addstr(1, 1, sep[:box_w - 2])
            except _c.error:
                pass

            for i, line in enumerate(content):
                try:
                    win.addstr(2 + i, 2, line[:box_w - 3])
                except _c.error:
                    pass

            content_end = 2 + len(content)
            try:
                win.addstr(content_end, 1, sep[:box_w - 2])
            except _c.error:
                pass

            btn_yes = " [ Yes ] "
            btn_no  = " [ No  ] "
            btn_row = content_end + 1
            gap = 2
            total_btn_w = len(btn_yes) + gap + len(btn_no)
            btn_x = max(1, (box_w - total_btn_w) // 2)
            try:
                attr_yes = (_c.color_pair(1) | _c.A_BOLD) if selected == 0 else _c.A_NORMAL
                attr_no  = (_c.color_pair(1) | _c.A_BOLD) if selected == 1 else _c.A_NORMAL
                win.addstr(btn_row, btn_x, btn_yes, attr_yes)
                win.addstr(btn_row, btn_x + len(btn_yes) + gap, btn_no, attr_no)
            except _c.error:
                pass

            hint = "Y/Enter=yes   N/Esc=no   ←→=switch"
            try:
                win.addstr(box_h - 1, max(1, (box_w - len(hint)) // 2), hint[:box_w - 2])
            except _c.error:
                pass

            win.refresh()

            key = win.getch()
            if key in (ord('y'), ord('Y')):
                result[0] = True
                break
            elif key in (10, 13):        # Enter — confirm highlighted button
                result[0] = (selected == 0)
                break
            elif key in (ord('n'), ord('N'), 27):  # N or Esc = No
                result[0] = False
                break
            elif key in (_c.KEY_LEFT, _c.KEY_RIGHT, 9):  # arrow / Tab
                selected = 1 - selected

    if _c is not None:
        try:
            _c.wrapper(_dialog)
            return result[0]
        except Exception:
            pass

    # Fallback: plain terminal prompt
    sys.stdout.write("\nRun automatic checks and fixes before interactive mode? [Y/n] ")
    sys.stdout.flush()
    try:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return ch not in ('\x1b', 'n', 'N')
    except Exception:
        return sys.stdin.readline().strip().lower() not in ('n', 'no')


def run_scan_with_dialog(root: Path, args) -> dict:
    """Run full scan (links, orphans, stubs, optional auto-fixes) inside a
    centered curses progress dialog. Only called in --interactive mode."""
    try:
        import curses as _c
    except ImportError:
        _c = None

    def _do_scan() -> dict:
        if getattr(args, "fix_simple_errors", False):
            print("Fixing broken links...", file=sys.stderr)
        result = check_vault(root, args)
        orphan_result = check_orphans(root, args.quiet)
        result["orphans"] = orphan_result["orphans"]
        result["orphan_summary"] = orphan_result["summary"]
        stub_result = check_stubs(root, args.quiet)
        result["stubs"] = stub_result["stubs"]
        result["stub_summary"] = stub_result["summary"]
        if getattr(args, "fix_orphans", False) and orphan_result["orphans"]:
            print(f"Fixing {len(orphan_result['orphans'])} orphan(s)...", file=sys.stderr)
            fix_result = fix_orphans(orphan_result["orphans"], root, args.quiet)
            result["orphan_fix"] = fix_result
            if fix_result["orphans_resolved"] > 0:
                updated = check_orphans(root, quiet=True)
                result["orphans"] = updated["orphans"]
                result["orphan_summary"] = updated["summary"]
        return result

    if _c is None:
        return _do_scan()

    outcome: list = []

    def _curses_scan(stdscr):
        _c.curs_set(0)
        _c.start_color()
        _c.use_default_colors()
        _c.init_pair(2, _c.COLOR_YELLOW, -1)

        height, width = stdscr.getmaxyx()
        box_w = max(40, width - 4)
        box_h = min(20, height - 4)
        by = max(0, (height - box_h) // 2)
        bx = max(0, (width - box_w) // 2)
        inner_w = box_w - 4
        max_log = box_h - 3  # rows 2 … box_h-2

        win = _c.newwin(box_h, box_w, by, bx)
        log_buf: list[str] = []
        cur: list[str] = [""]

        def _wrap(line: str) -> list[str]:
            """Wrap a single line to inner_w, indenting continuation rows."""
            if len(line) <= inner_w:
                return [line]
            rows = []
            while len(line) > inner_w:
                rows.append(line[:inner_w])
                line = "  " + line[inner_w:]
            if line:
                rows.append(line)
            return rows

        def redraw():
            win.erase()
            win.box()
            title = " Scanning vault "
            try:
                win.addstr(0, max(1, (box_w - len(title)) // 2), title,
                           _c.color_pair(2) | _c.A_BOLD)
                win.addstr(1, 1, "─" * (box_w - 2))
            except _c.error:
                pass
            raw = log_buf + ([cur[0]] if cur[0] else [])
            wrapped: list[str] = []
            for ln in raw:
                wrapped.extend(_wrap(ln))
            visible = wrapped[-max_log:]
            for i, line in enumerate(visible):
                try:
                    win.addstr(2 + i, 2, line[:inner_w])
                except _c.error:
                    pass
            win.refresh()

        class _Stderr:
            def write(self, text: str):
                i = 0
                while i < len(text):
                    if text[i] == '\r':
                        cur[0] = ""
                        i += 1
                    elif text[i] == '\n':
                        log_buf.append(cur[0])
                        cur[0] = ""
                        i += 1
                    else:
                        j = i
                        while j < len(text) and text[j] not in ('\r', '\n'):
                            j += 1
                        cur[0] += text[i:j]
                        i = j
                redraw()

            def flush(self):
                pass

        old_err = sys.stderr
        sys.stderr = _Stderr()
        try:
            outcome.append(_do_scan())
        except Exception as e:
            outcome.extend([None, e])
        finally:
            sys.stderr = old_err

        if cur[0]:
            log_buf.append(cur[0])
            cur[0] = ""
        log_buf.append("")
        log_buf.append("  Done — starting interactive review…")
        redraw()
        _c.napms(1000)

    try:
        _c.wrapper(_curses_scan)
    except Exception:
        pass

    if outcome and outcome[0] is not None:
        return outcome[0]
    if len(outcome) > 1 and outcome[1] is not None:
        raise outcome[1]
    return _do_scan()


def parse_args():
    parser = argparse.ArgumentParser(
        prog="wiki-lint-check.py",
        description=(
            "Scan Markdown files for broken internal and external links.\n"
            "Output is structured JSON (default) or human-readable text, "
            "designed for AI consumption."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan vault rooted at the script's parent directory:
  python3 wiki-lint-check.py

  # Scan a specific vault directory:
  python3 wiki-lint-check.py /path/to/vault

  # Human-readable output:
  python3 wiki-lint-check.py --format text

  # Include external HTTP link checks:
  python3 wiki-lint-check.py --external --timeout 10

  # Include image embeds in checks:
  python3 wiki-lint-check.py --include-images

  # Skip frontmatter links (e.g. author: [[Name]] in raw/clips):
  python3 wiki-lint-check.py --skip-frontmatter

  # Show suggested fixes for broken wikilinks, then apply them:
  python3 wiki-lint-check.py --format text
  python3 wiki-lint-check.py --fix-simple-errors

  # Batch mode (no TUI, output only):
  python3 wiki-lint-check.py --batch-mode --format text

  # Combine options:
  python3 wiki-lint-check.py --external --include-images --skip-frontmatter --format text /path/to/vault
        """,
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="Root directory of the vault (default: parent of this script's directory)",
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="Also check HTTP/HTTPS links (requires network access; slow)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        metavar="N",
        help="Timeout in seconds for external HTTP requests (default: 5)",
    )
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Also check embedded image links (![[...]] and ![alt](...))",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format: 'text' for humans (default), 'json' for AI",
    )
    parser.add_argument(
        "--skip-frontmatter",
        action="store_true",
        help="Do not check links inside YAML frontmatter (useful to ignore author/tag references)",
    )
    parser.add_argument(
        "--remove-broken-links", 
        action="store_true",
        dest="remove_broken_links",
        help=(
            "Rewrite broken WikiLinks in-place to mark them visually. "
            "[[broken]] becomes [[broken|(broken link) broken]] and "
            "[[broken|text]] becomes [[broken|(broken link) text]], "
            "preserving the original target while flagging it in the display text."
        ),
    )
    parser.add_argument(
        "--fix-simple-errors", 
        action="store_true",
        dest="fix_simple_errors",
        help=(
            "Rewrite broken WikiLinks where a unique normalized match is found. "
            "Characters like ':' are often replaced by '_' in filenames or omitted "
            "in link text; this flag repairs such mismatches in-place."
        ),
    )
    parser.add_argument(
        "--fix-orphans",
        action="store_true",
        dest="fix_orphans",
        help=(
            "For each orphaned Wiki page, find plain-text references to its name in wiki/ "
            "files and replace them with WikiLinks. Only modifies files inside wiki/."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages written to stderr",
    )
    parser.add_argument(
        "--batch-mode",
        action="store_true",
        dest="batch_mode",
        help=(
            "Disable the interactive TUI and output results in text/JSON format only. "
            "By default, an interactive TUI opens after scanning to fix broken links one by one."
        ),
    )
    return parser, parser.parse_args()


def main():
    parser, args = parse_args()

    # Determine root directory
    if args.root:
        root = Path(args.root).resolve()
    else:
        # Default: parent of the 'scripts' directory (i.e., the vault root)
        script_dir = Path(__file__).resolve().parent
        if script_dir.name == "scripts":
            root = script_dir.parent
        else:
            root = script_dir

    if not root.exists():
        msg = f"Error: directory does not exist: {root}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    if not root.is_dir():
        msg = f"Error: not a directory: {root}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    auto_fix_applied = False
    if not args.batch_mode:
        auto_fix_applied = ask_run_auto_fixes()
        if auto_fix_applied:
            args.fix_simple_errors = True
            args.fix_orphans = True

    try:
        if not args.batch_mode:
            result = run_scan_with_dialog(root, args)
        else:
            result = check_vault(root, args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        msg = f"Unexpected error: {e}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    if args.batch_mode:
        if getattr(args, "fix_simple_errors", False):
            result["broken_links"] = [b for b in result["broken_links"] if "suggested_fix" in b or b.get("fm_deleted")]
            result["summary"]["broken"] = len(result["broken_links"])

        orphan_result = check_orphans(root, args.quiet)
        result["orphans"] = orphan_result["orphans"]
        result["orphan_summary"] = orphan_result["summary"]

        stub_result = check_stubs(root, args.quiet)
        result["stubs"] = stub_result["stubs"]
        result["stub_summary"] = stub_result["summary"]

        if getattr(args, "fix_orphans", False) and orphan_result["orphans"]:
            fix_result = fix_orphans(orphan_result["orphans"], root, args.quiet)
            result["orphan_fix"] = fix_result
            if fix_result["orphans_resolved"] > 0:
                updated = check_orphans(root, quiet=True)
                result["orphans"] = updated["orphans"]
                result["orphan_summary"] = updated["summary"]

    has_issues = (
        result["summary"]["broken"] > 0
        or result.get("orphan_summary", {}).get("orphans_found", 0) > 0
        or result.get("stub_summary", {}).get("stubs_found", 0) > 0
    )

    if not args.batch_mode:
        broken_for_review = result["broken_links"]
        if auto_fix_applied:
            broken_for_review = [b for b in broken_for_review if not b.get("fixed") and not b.get("fm_deleted")]
        run_interactive(broken_for_review, result.get("orphans", []), result.get("stubs", []), root)
    elif args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_text(result))

    if args.batch_mode and has_issues:
        print("\nTip: run without --batch-mode to review and fix issues interactively.", file=sys.stderr)

    # Exit code: 0 = clean, 1 = issues found, 2 = errors
    if result.get("errors"):
        sys.exit(2)
    if has_issues:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
