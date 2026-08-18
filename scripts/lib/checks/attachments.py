"""Detect linked attachments that live outside the note's own _resources dir.

Notes under raw/ and INBOX/ must keep their non-markdown attachments in
`_resources/` (or a legacy `*.resources/` dir) directly below the note's own
directory. wiki/ notes are exempt — they may legitimately reference raw/
attachments.

Pure detection — never writes.
"""

from pathlib import Path
from urllib.parse import unquote

from ..links import CURLY_TO_STRAIGHT, extract_links, is_external

# Content trees whose notes must co-locate their attachments.
ENFORCED_DIRS = ("raw", "INBOX")

# Searched for attachments: the content trees plus the legacy vault-root
# _resources/ — the historic Obsidian default attachment folder, where
# strays accumulate.
ATTACHMENT_DIRS = ("raw", "wiki", "INBOX", "_resources")


def _attachment_index(root: Path) -> dict[str, list[Path]]:
    """Map filename -> all non-markdown files in the searched trees.

    Symlinks are skipped, matching check_loose_files — resolving them could
    surface paths outside the vault.
    """
    index: dict[str, list[Path]] = {}
    for top in ATTACHMENT_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.is_file() and not f.is_symlink() and f.suffix.lower() != ".md":
                index.setdefault(f.name, []).append(f)
    return index


def _resolve_attachment(
    target: str, note: Path, root: Path, index: dict[str, list[Path]]
) -> "Path | None":
    """Resolve a link target to an existing non-markdown file, or None.

    None means: external, empty/anchor, a markdown note, unresolvable
    (broken links are the broken-link check's job), or ambiguous.
    """
    target = unquote(target).strip()
    if not target or target.startswith("#") or is_external(target):
        return None
    target = target.split("#", 1)[0].strip()
    if target.startswith("./"):
        target = target[2:]
    # Same normalization as resolve_wikilink: links often carry curly quotes
    # where the filename has straight ones.
    target = target.translate(CURLY_TO_STRAIGHT)
    p = Path(target)
    # Targets without an extension, or with .md, are notes — not attachments.
    if not p.suffix or p.suffix.lower() == ".md":
        return None

    resolved = None
    for cand in (note.parent / target, root / target):
        if cand.is_file() and not cand.is_symlink():
            if cand.resolve().suffix.lower() != ".md":
                resolved = cand.resolve()
                break
            return None
        # [[foo.png]] may actually be the companion note foo.png.md
        if Path(str(cand) + ".md").is_file():
            return None

    if resolved is None:
        matches = index.get(p.name, [])
        if p.parent != Path("."):
            suffix = p.as_posix()
            matches = [m for m in matches if m.as_posix().endswith("/" + suffix)]
        if len(matches) != 1:
            return None  # not found or ambiguous
        resolved = matches[0].resolve()

    # Never report a file outside the vault (e.g. behind a symlinked dir) —
    # downstream code treats resolved paths as vault-relative.
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _resources_ancestor(note_dir: Path, root: Path) -> "Path | None":
    """Outermost `_resources`/`*.resources` directory containing note_dir,
    or None when the note does not live inside a resources tree."""
    try:
        rel = note_dir.relative_to(root)
    except ValueError:
        return None
    for i, part in enumerate(rel.parts):
        if part == "_resources" or part.endswith(".resources"):
            return root.joinpath(*rel.parts[: i + 1])
    return None


def _is_colocated(resolved: Path, note_dir: Path, root: Path) -> bool:
    """True when resolved lives under note_dir/_resources/ (or a legacy
    `*.resources/` dir directly below note_dir) — or, for companion notes
    that themselves live inside a resources tree, anywhere in that tree."""
    anchor = _resources_ancestor(note_dir, root)
    if anchor is not None:
        try:
            resolved.relative_to(anchor)
            return True
        except ValueError:
            return False
    try:
        rel = resolved.relative_to(note_dir)
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) > 1 and (
        parts[0] == "_resources" or parts[0].endswith(".resources")
    )


def check_misplaced_attachments(root: Path, quiet: bool) -> dict:
    """Find attachments linked from raw/ and INBOX/ notes that are not stored
    in the _resources directory of ANY note that references them.

    An attachment co-located with one of its referencing notes (including a
    wiki/ note) satisfies the rule for all other referencing notes too.
    """
    index = _attachment_index(root)
    rroot = root.resolve()
    # Pass 1: gather every attachment reference from all content trees, so an
    # attachment co-located with any one referencing note is fine everywhere.
    ref_dirs: dict[Path, set[Path]] = {}   # resolved attachment -> referencing note dirs
    enforced_links = []              # (md, lineno, target, resolved) from raw/INBOX
    notes_scanned = 0
    for top in ("raw", "wiki", "INBOX"):
        base = root / top
        if not base.is_dir():
            continue
        is_enforced = top in ENFORCED_DIRS
        for md in sorted(base.rglob("*.md")):
            if not md.is_file():
                continue
            if is_enforced:
                notes_scanned += 1
            try:
                content = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, _link_type, _raw, target in extract_links(
                content, include_images=True
            ):
                resolved = _resolve_attachment(target, md, root, index)
                if resolved is None:
                    continue
                ref_dirs.setdefault(resolved, set()).add(md.parent.resolve())
                if is_enforced:
                    enforced_links.append((md, lineno, target, resolved))
    # Pass 2: flag enforced links whose attachment is co-located with none of
    # its referencing notes.
    misplaced = []
    for md, lineno, target, resolved in enforced_links:
        if any(_is_colocated(resolved, d, rroot) for d in ref_dirs[resolved]):
            continue
        try:
            resolved_rel = str(resolved.relative_to(rroot))
        except ValueError:
            resolved_rel = str(resolved)
        misplaced.append({
            "file": str(md.relative_to(root)),
            "line": lineno,
            "target": target,
            "resolved": resolved_rel,
            "expected_dir": str(md.parent.relative_to(root) / "_resources"),
        })
    return {
        "misplaced_attachments": misplaced,
        "summary": {
            "notes_scanned": notes_scanned,
            "attachments_checked": len(enforced_links),
            "misplaced_found": len(misplaced),
        },
    }
