"""Shared raw-source privacy helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote


SOURCE_EXTENSIONS = {".md", ".pdf", ".doc", ".docx", ".txt", ".vtt", ".eml", ".html"}
INGEST_FALSE_RE = re.compile(
    r'''^\s*ingest\s*:\s*(?:"false"|'false'|false)\s*(?:#.*)?$''',
    re.IGNORECASE,
)
WIKILINK_RE = re.compile(r"!?\[\[((?:[^\]|\n\\]|\\(?!\|)|\](?!\]))+)")
MDLINK_RE = re.compile(r"!?\[[^\]\n]*\]\(((?:[^()#\n]|\([^()\n]*\))+?)(?:#[^)]*)?\)")
SOURCE_RE = re.compile(r"^\s*source\s*:\s*(.+?)\s*(?:#.*)?$")
EXTERNAL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _frontmatter_lines(path: Path) -> list[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            if f.readline().strip() != "---":
                return []
            lines = []
            for line in f:
                if line.strip() in ("---", "..."):
                    return lines
                lines.append(line.rstrip("\n"))
    except OSError:
        pass
    return []


def has_ingest_false(path: Path) -> bool:
    """Return True when a Markdown raw note carries `ingest: false`."""
    if path.suffix.lower() != ".md":
        return False
    return any(INGEST_FALSE_RE.match(line) for line in _frontmatter_lines(path))


def _strip_target(target: str) -> str:
    target = target.strip()
    if not target:
        return ""
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if (target.startswith('"') and target.endswith('"')) or (
        target.startswith("'") and target.endswith("'")
    ):
        target = target[1:-1].strip()
    target = unquote(target).replace("\\", "/")
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith("#") or EXTERNAL_RE.match(target):
        return ""
    return target


def _link_targets(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    targets = []
    targets.extend(m.group(1) for m in WIKILINK_RE.finditer(text))
    targets.extend(m.group(1) for m in MDLINK_RE.finditer(text))
    for line in _frontmatter_lines(path):
        match = SOURCE_RE.match(line)
        if match:
            targets.append(match.group(1))
    return targets


def raw_source_paths(root: Path) -> list[Path]:
    """Return all raw source files that can participate in ingestion/privacy checks."""
    raw = root / "raw"
    if not raw.is_dir():
        return []
    return sorted(
        path
        for path in raw.rglob("*")
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS
    )


def _resolve_linked_raw_files(
    target: str,
    note_dir: Path,
    candidates: set[Path],
    root: Path,
) -> set[Path]:
    target = _strip_target(target)
    if not target:
        return set()

    raw_paths = []
    if os.path.isabs(target):
        raw_paths.append(Path(target))
    elif target.startswith("raw/"):
        raw_paths.append(root / target)
    else:
        raw_paths.append(note_dir / target)

    resolved = set()
    for raw_path in raw_paths:
        variants = [raw_path]
        if raw_path.suffix == "":
            variants.extend(raw_path.with_suffix(ext) for ext in SOURCE_EXTENSIONS)
        for variant in variants:
            try:
                candidate = variant.resolve()
            except OSError:
                continue
            if candidate in candidates:
                resolved.add(candidate)
    return resolved


def protected_raw_paths(root: Path, candidates: list[Path] | None = None) -> tuple[set[Path], list[dict]]:
    """Return raw files protected by `ingest: false` notes and their local links."""
    candidates = candidates if candidates is not None else raw_source_paths(root)
    candidate_set = {path.resolve() for path in candidates}
    protected: set[Path] = set()
    notes = []
    for path in candidates:
        if not has_ingest_false(path):
            continue
        resolved_path = path.resolve()
        linked = set()
        for target in _link_targets(path):
            linked.update(_resolve_linked_raw_files(target, path.parent, candidate_set, root))
        linked.discard(resolved_path)
        protected.add(resolved_path)
        protected.update(linked)
        notes.append({
            "file": path.relative_to(root).as_posix(),
            "linked_count": len(linked),
        })
    return protected, notes
