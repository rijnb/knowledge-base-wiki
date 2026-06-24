"""Read-only freshness drift detection for canonical Wiki pages."""

from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import Any

from .freshness_index import build_inventory
from .paths import wikilink_target


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def _date_value(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _latest_date(values: list[str | None]) -> str | None:
    parsed = sorted(
        (date for date in (_date_value(value) for value in values) if date),
        reverse=True,
    )
    return parsed[0].strftime("%Y-%m-%d") if parsed else None


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _link_targets(content: str) -> set[str]:
    targets = set()
    for match in WIKILINK_RE.finditer(content):
        target = match.group(1).strip()
        targets.add(_normalize_title(Path(target).stem))
    return targets


def _relation_index(root: Path, raw_notes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map normalized page titles to raw notes that explicitly reference them.

    The first version deliberately avoids an O(wiki pages * raw notes) scan.
    Explicit wikilinks are the strongest signal and cheap to invert. Raw-note
    titles are also indexed as a weak signal for notes named after a page.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for note in raw_notes:
        content = _read(root, note["path"])
        targets = _link_targets(content)
        title = _normalize_title(note.get("title") or "")
        if title:
            targets.add(title)
        for target in targets:
            index.setdefault(target, []).append(note)
    return index


def _page_checked(page: dict[str, Any]) -> str | None:
    return _latest_date([
        block.get("checked")
        for block in page.get("blocks", [])
        if isinstance(block.get("checked"), str)
    ])


def _status_reasons(page: dict[str, Any]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    statuses = {block.get("status") for block in page.get("blocks", [])}
    if "disputed" in statuses:
        score += 30
        reasons.append("disputed-block")
    if "stale" in statuses:
        score += 25
        reasons.append("stale-block")
    if "superseded" in statuses:
        score += 15
        reasons.append("superseded-block")
    return score, reasons


def _candidate(
    page: dict[str, Any],
    related_index: dict[str, list[dict[str, Any]]],
    ambiguous_titles: set[str],
) -> dict[str, Any] | None:
    normalized_title = _normalize_title(page["title"])
    related = related_index.get(normalized_title, [])
    if not related:
        return None

    # When several wiki pages share a title, a raw wikilink cannot be
    # attributed to one of them, so the raw-recency signal is unreliable.
    title_is_ambiguous = normalized_title in ambiguous_titles

    checked = _page_checked(page)
    latest_raw = _latest_date([note.get("date") for note in related])
    checked_dt = _date_value(checked)
    latest_raw_dt = _date_value(latest_raw)

    score = 0
    reasons: list[str] = []

    if page.get("blocks"):
        without_provenance = [
            block for block in page["blocks"] if not block.get("has_provenance")
        ]
        if without_provenance:
            score += 20
            reasons.append("blocks-without-provenance")
    else:
        score += 35
        reasons.append("legacy-page-no-block-provenance")

    if title_is_ambiguous:
        reasons.append("ambiguous-title")
    elif checked_dt and latest_raw_dt and latest_raw_dt > checked_dt:
        score += 60
        reasons.append("newer-related-raw")
    elif not checked and latest_raw:
        score += 40
        reasons.append("unreviewed-related-raw")

    status_score, status_reasons = _status_reasons(page)
    score += status_score
    reasons.extend(status_reasons)

    if not reasons:
        return None

    return {
        "page": page["path"],
        "title": page["title"],
        "score": score,
        "reasons": reasons,
        "checked": checked,
        "latest_related_raw_date": latest_raw,
        "related_raw_count": len(related),
        "related_raw": [note["path"] for note in related[:10]],
    }


def detect_drift(root: Path) -> dict[str, Any]:
    """Return ranked one-page curation candidates without modifying files."""
    root = root.resolve()
    inventory = build_inventory(root)
    related_index = _relation_index(root, inventory["raw_notes"])

    title_counts: dict[str, int] = {}
    for page in inventory["wiki_pages"]:
        title_counts[_normalize_title(page["title"])] = (
            title_counts.get(_normalize_title(page["title"]), 0) + 1
        )
    ambiguous_titles = {title for title, count in title_counts.items() if count > 1}

    candidates = [
        candidate
        for page in inventory["wiki_pages"]
        for candidate in [_candidate(page, related_index, ambiguous_titles)]
        if candidate
    ]
    candidates.sort(key=lambda item: (-item["score"], item["page"]))
    return {
        "summary": {
            "pages_checked": inventory["summary"]["wiki_pages"],
            "raw_notes_checked": inventory["summary"]["raw_notes"],
            "candidates": len(candidates),
        },
        "candidates": candidates,
    }


def write_queue(root: Path, result: dict[str, Any]) -> Path:
    outdir = root / ".wiki-scratch"
    outdir.mkdir(exist_ok=True)
    path = outdir / "freshness-curation-candidates.md"
    lines = [
        "# Freshness curation candidates",
        "",
        "Generated by `wiki-drift-detect.py`. Review one page at a time; no page changes were applied automatically.",
        "",
    ]
    for candidate in result["candidates"]:
        page_link = wikilink_target(candidate["page"])
        lines.append(
            f"- [ ] **[[{page_link}]]** score {candidate['score']} — "
            f"{', '.join(candidate['reasons'])}"
        )
        lines.append(
            f"      <sub>latest related raw: {candidate.get('latest_related_raw_date') or '?'}; "
            f"checked: {candidate.get('checked') or '?'}; "
            f"related raw notes: {candidate['related_raw_count']}</sub>"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
