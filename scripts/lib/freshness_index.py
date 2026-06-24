"""Read-only inventory for freshness-aware Wiki migration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .frontmatter import split_frontmatter as _frontmatter
from .paths import wiki_pages as _wiki_pages
from .provenance import (
    BLOCK_ID_RE,
    parse_provenance_callout,
    validate_provenance,
)


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _clean_heading(text: str) -> str:
    return text.strip().rstrip("#").strip()


def _title_from(path: Path, frontmatter: dict[str, str], body: str) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"]
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return _clean_heading(match.group(2))
    return path.stem


def _headings(body: str) -> list[str]:
    result: list[str] = []
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            result.append(_clean_heading(match.group(2)))
    return result


def _strip_block_ids(text: str) -> str:
    return BLOCK_ID_RE.sub("", text).strip()


def _iter_blocks(body: str):
    heading_stack: list[str] = []
    paragraph: list[str] = []
    paragraph_headings: list[str] = []

    def flush():
        nonlocal paragraph, paragraph_headings
        if paragraph:
            yield "\n".join(paragraph).strip(), list(paragraph_headings)
            paragraph = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        heading = HEADING_RE.match(line)
        if heading:
            yield from flush()
            level = len(heading.group(1))
            title = _clean_heading(heading.group(2))
            heading_stack[:] = heading_stack[:level - 1]
            heading_stack.append(title)
            paragraph_headings = list(heading_stack)
            continue
        if not line.strip():
            yield from flush()
            paragraph_headings = list(heading_stack)
            continue
        if not paragraph:
            paragraph_headings = list(heading_stack)
        paragraph.append(line)
    yield from flush()


def _blocks_in_paragraph(text: str) -> list[tuple[str, str]]:
    """Split a paragraph into (block_id, owning-segment) pairs.

    Each Obsidian `^block-id` terminates its block, so adjacent block IDs in one
    paragraph must each own only their own line(s) rather than the whole
    paragraph text.
    """
    results: list[tuple[str, str]] = []
    segment: list[str] = []
    for line in text.splitlines():
        segment.append(line)
        block_ids = BLOCK_ID_RE.findall(line)
        if block_ids:
            owned = "\n".join(segment)
            for block_id in block_ids:
                results.append((block_id, owned))
            segment = []
    return results


def _raw_notes(root: Path) -> list[Path]:
    raw = root / "raw"
    if not raw.is_dir():
        return []
    return sorted(path for path in raw.rglob("*.md") if path.name != "SKILL.md")


def _block_entry(
    block_id: str,
    text: str,
    heading_path: list[str],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    metadata = provenance.get(block_id, {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": block_id,
        "text": _strip_block_ids(text),
        "heading_path": heading_path,
        "status": metadata.get("status", "unknown"),
        "confidence": metadata.get("confidence", "unknown"),
        "sources": metadata.get("sources", []),
        "observed": metadata.get("observed"),
        "checked": metadata.get("checked"),
        "provenance": metadata,
        "has_provenance": bool(metadata),
    }


def _index_wiki_page(root: Path, path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _frontmatter(content)
    parsed_provenance = parse_provenance_callout(content) or {}
    provenance_blocks = parsed_provenance.get("blocks", {})
    if not isinstance(provenance_blocks, dict):
        provenance_blocks = {}

    blocks: list[dict[str, Any]] = []
    for text, heading_path in _iter_blocks(body):
        for block_id, segment in _blocks_in_paragraph(text):
            blocks.append(_block_entry(
                block_id,
                segment,
                heading_path,
                provenance_blocks,
            ))

    rel = str(path.relative_to(root))
    return {
        "path": rel,
        "title": _title_from(path, frontmatter, body),
        "migration_status": parsed_provenance.get("migration_status"),
        "provenance_schema": parsed_provenance.get("schema"),
        "blocks": blocks,
        "validation_issues": [
            issue.as_dict() for issue in validate_provenance(content, path=rel)
        ],
    }


def _index_raw_note(root: Path, path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _frontmatter(content)
    return {
        "path": str(path.relative_to(root)),
        "title": _title_from(path, frontmatter, body),
        "date": frontmatter.get("date") or frontmatter.get("created"),
        "source_type": frontmatter.get("source_type") or frontmatter.get("type"),
        "headings": _headings(body),
    }


def build_inventory(root: Path) -> dict[str, Any]:
    """Build a disposable, read-only inventory of `wiki/` and `raw/`."""
    root = root.resolve()
    wiki_pages = [_index_wiki_page(root, path) for path in _wiki_pages(root)]
    raw_notes = [_index_raw_note(root, path) for path in _raw_notes(root)]

    canonical_blocks = [
        block for page in wiki_pages for block in page["blocks"]
    ]
    validation_issues = [
        issue for page in wiki_pages for issue in page["validation_issues"]
    ]
    blocks_with_provenance = sum(1 for block in canonical_blocks if block["has_provenance"])
    legacy_inferred_pages = sum(
        1 for page in wiki_pages if page.get("migration_status") == "legacy-inferred"
    )
    return {
        "summary": {
            "wiki_pages": len(wiki_pages),
            "raw_notes": len(raw_notes),
            "canonical_blocks": len(canonical_blocks),
            "blocks_with_provenance": blocks_with_provenance,
            "blocks_without_provenance": len(canonical_blocks) - blocks_with_provenance,
            "legacy_inferred_pages": legacy_inferred_pages,
            "validation_issues": len(validation_issues),
        },
        "wiki_pages": wiki_pages,
        "raw_notes": raw_notes,
        "validation_issues": validation_issues,
    }
