"""Read-only inventory for freshness-aware Wiki queries."""

from __future__ import annotations

from datetime import date
import re
from pathlib import Path
from typing import Any

from .frontmatter import split_frontmatter as _frontmatter
from .paths import wiki_pages as _wiki_pages
from .provenance import (
    parse_provenance,
    provenance_dates,
    validate_provenance,
)
from .raw_privacy import protected_raw_paths


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


def _raw_notes(root: Path) -> list[Path]:
    raw = root / "raw"
    if not raw.is_dir():
        return []
    protected, _ = protected_raw_paths(root)
    return sorted(
        path
        for path in raw.rglob("*.md")
        if path.name != "SKILL.md" and path.resolve() not in protected
    )


def _has_provenance(provenance: dict[str, Any] | None) -> bool:
    if not provenance:
        return False
    return provenance.get("generated") is not None or bool(provenance.get("sources"))


def _actors(provenance: dict[str, Any]) -> list[str]:
    actors: list[str] = []
    generated = provenance.get("generated")
    if isinstance(generated, dict) and generated.get("by"):
        actors.append(str(generated["by"]))
    for entry in provenance.get("verified") or []:
        if isinstance(entry, dict) and entry.get("by"):
            actors.append(str(entry["by"]))
    return actors


def _page_status(provenance: dict[str, Any] | None, today: str) -> str:
    if not _has_provenance(provenance):
        return "unknown"
    stale_after = provenance.get("stale_after")
    if isinstance(stale_after, str) and stale_after <= today:
        return "stale"
    return "current"


def _page_confidence(provenance: dict[str, Any] | None) -> str:
    if not _has_provenance(provenance):
        return "unknown"
    if any(actor.startswith("human:") for actor in _actors(provenance)):
        return "high"
    return "medium"


def _page_sources(provenance: dict[str, Any] | None) -> list[str]:
    if not provenance or not isinstance(provenance.get("sources"), list):
        return []
    return [
        entry["resource"]
        for entry in provenance["sources"]
        if isinstance(entry, dict) and entry.get("resource")
    ]


def _index_wiki_page(root: Path, path: Path, today: str) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _frontmatter(content)
    provenance = parse_provenance(content)
    generated_at, verified_at = provenance_dates(provenance)
    checked = max(
        (value for value in (generated_at, verified_at) if value),
        default=None,
    )

    rel = str(path.relative_to(root))
    return {
        "path": rel,
        "title": _title_from(path, frontmatter, body),
        "state": frontmatter.get("state"),
        "provenance": provenance,
        "has_provenance": _has_provenance(provenance),
        "generated_at": generated_at,
        "verified_at": verified_at,
        "observed": generated_at,
        "checked": checked,
        "stale_after": provenance.get("stale_after") if provenance else None,
        "status": _page_status(provenance, today),
        "confidence": _page_confidence(provenance),
        "sources": _page_sources(provenance),
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
    today = date.today().isoformat()
    wiki_pages = [_index_wiki_page(root, path, today) for path in _wiki_pages(root)]
    raw_notes = [_index_raw_note(root, path) for path in _raw_notes(root)]

    validation_issues = [
        issue for page in wiki_pages for issue in page["validation_issues"]
    ]
    pages_with_provenance = sum(1 for page in wiki_pages if page["has_provenance"])
    return {
        "summary": {
            "wiki_pages": len(wiki_pages),
            "raw_notes": len(raw_notes),
            "pages_with_provenance": pages_with_provenance,
            "pages_without_provenance": len(wiki_pages) - pages_with_provenance,
            "validation_issues": len(validation_issues),
        },
        "wiki_pages": wiki_pages,
        "raw_notes": raw_notes,
        "validation_issues": validation_issues,
    }
