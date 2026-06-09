"""Path filters, indexes, and string-shortening helpers."""

import os
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


class VaultIndex:
    """Single-pass walk of raw/ and wiki/ that produces every lookup a vault
    scan needs:

      md_files        — sorted list of .md files that pass should_skip_md;
                        what check_vault iterates.
      stem_index      — filename stem → matching paths (fuzzy wikilink match).
      norm_index      — normalize_name(stem) → matching paths (fuzzy match
                        across filename-substituted characters).
      path_suffix_set — every "/"-joined trailing path component of every
                        file under raw/ and wiki/, curly-quote normalized;
                        lets [[x/y]] resolve to any file ending in x/y.

    Replaces what used to be three separate rglob traversals plus a fourth
    walk inside check_vault — substantial perf win on iCloud-backed vaults.
    """

    def __init__(self, root: Path):
        self.root = root
        self.md_files: list[Path] = []
        self.stem_index: dict[str, list[Path]] = {}
        self.norm_index: dict[str, list[Path]] = {}
        self.path_suffix_set: set[str] = set()
        self._build()

    def _build(self):
        # Local import — resolve imports should_skip_md from this module,
        # so importing normalize_name at module load creates a cycle.
        from .resolve import normalize_name

        root = self.root
        for top in ("raw", "wiki"):
            top_dir = root / top
            if not top_dir.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(top_dir):
                base = Path(dirpath)
                for fname in filenames:
                    p = base / fname
                    rel_parts = p.relative_to(root).parts
                    for i in range(len(rel_parts)):
                        self.path_suffix_set.add(
                            "/".join(rel_parts[i:]).translate(CURLY_TO_STRAIGHT)
                        )
                    if fname.endswith(".md") and not should_skip_md(p, root):
                        self.md_files.append(p)
                        stem = p.stem
                        self.stem_index.setdefault(stem, []).append(p)
                        self.norm_index.setdefault(normalize_name(stem), []).append(p)
        self.md_files.sort()
