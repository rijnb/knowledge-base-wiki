"""Detect orphan wiki pages and optionally relink plain-text references."""

import re
import sys
from pathlib import Path

from ..frontmatter import (
    add_orphan_false_to_frontmatter,
    has_orphan_false_in_frontmatter,
    remove_orphan_false_from_frontmatter,
)
from ..links import extract_links, is_external
from ..paths import should_skip_md
from ..resolve import resolve_wikilink_to_path


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
        # Apply the same skip filter the VaultIndex uses, so links inside
        # skipped files (e.g. wiki/log.md, START_HERE.md) never count as backlinks.
        if should_skip_md(md_file, root):
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
        files_touched: list = []

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
