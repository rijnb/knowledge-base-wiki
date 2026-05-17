"""Path filters, indexes, and string-shortening helpers."""

from pathlib import Path

from .links import CURLY_TO_STRAIGHT


def truncate_path(path: str, max_len: int = 40, prefix_len: int = 20) -> str:
    """Truncate path to max_len chars: first prefix_len chars + '...' + tail."""
    if len(path) <= max_len:
        return path
    tail_len = max_len - prefix_len - 3
    if tail_len <= 0:
        return path[:max_len]
    return path[:prefix_len] + "..." + path[-tail_len:]


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
