"""Detect loose non-markdown files that belong in a _resources directory."""

from pathlib import Path

# Content trees the doctor governs. Other top-level dirs (scripts/, config/,
# templates/, docs/, dot-dirs) legitimately contain non-markdown files.
CONTENT_DIRS = ("raw", "wiki", "INBOX")


def _in_resources(rel: Path) -> bool:
    return any(p == "_resources" or p.endswith(".resources") for p in rel.parts)


def _is_infrastructure(name: str) -> bool:
    return name.startswith(".") or name.startswith("log.jsonl")


def check_loose_files(root: Path, quiet: bool) -> dict:
    """Find non-markdown files in content trees that are not inside _resources/.

    Pure detection — never writes. fix_loose_files() in fixers.py remediates.
    """
    loose = []
    files_scanned = 0
    for top in CONTENT_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            if f.is_symlink():
                continue
            files_scanned += 1
            if f.suffix.lower() == ".md":
                continue
            rel = f.relative_to(root)
            if _in_resources(rel) or _is_infrastructure(f.name):
                continue
            loose.append(str(rel))
    return {
        "loose_files": sorted(loose),
        "summary": {"files_scanned": files_scanned, "loose_found": len(loose)},
    }
