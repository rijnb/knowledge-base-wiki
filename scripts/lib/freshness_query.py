"""Query-time freshness packet generation.

Semantic search finds candidate pages. This module turns those retrieved pages
into a block-level packet so current/history/change queries can rank canonical
claims by freshness instead of treating each page as a single blob.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .freshness_index import build_inventory
from .freshness_rank import classify_query_intent, rank_blocks


QMD_URI_RE = re.compile(r"^qmd://([^/]+)/(.*)$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+")
SOURCE_EXTENSION_SUFFIX_RE = re.compile(
    r"\.(?:docx?|pptx?|xlsx?|pdf|html?|eml|vtt|txt)$",
    re.IGNORECASE,
)


def _normalize_page_arg(page: str) -> str:
    value = page.strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].split("|", 1)[0]
    value = value.split("#", 1)[0]
    if not value.endswith(".md"):
        value += ".md"
    return value.lstrip("/")


def _qmd_key(path: str) -> str:
    parts = []
    for part in Path(path).parts:
        normalized = re.sub(r"[^A-Za-z0-9]+", " ", part).strip().lower()
        if normalized:
            parts.append(normalized)
    return "/".join(parts)


def _title_key(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", value)).strip().lower()


def _title_variants(value: str) -> list[str]:
    values = []
    queue = [value.strip()]
    while queue:
        current = queue.pop(0)
        if not current or current in values:
            continue
        values.append(current)
        for variant in (
            DATE_PREFIX_RE.sub("", current).strip(),
            SOURCE_EXTENSION_SUFFIX_RE.sub("", current).strip(),
            current.split(" - ", 1)[1].strip() if " - " in current else "",
        ):
            if variant and variant not in values and variant not in queue:
                queue.append(variant)
    return values


def _qmd_result_to_rel_path(value: str, root: Path, collection: str) -> str | None:
    value = value.strip()
    uri_match = QMD_URI_RE.match(value)
    if uri_match:
        found_collection, rel_path = uri_match.groups()
        if found_collection != collection:
            return None
        return rel_path

    path = Path(value)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return None
    if value.startswith("./"):
        return value[2:]
    return value


def resolve_qmd_result_pages(
    root: Path,
    result_files: list[str],
    collection: str = "tomtom",
) -> list[str]:
    """Resolve qmd result file IDs to real `wiki/` page paths.

    QMD emits normalized identifiers such as
    `qmd://tomtom/wiki/concepts/Foo-Bar.md`; the vault keeps readable filenames
    such as `wiki/concepts/Foo Bar.md`. Only unambiguous wiki-page matches are
    returned, preserving QMD result order.
    """
    root = root.resolve()
    inventory = build_inventory(root)
    by_qmd_key: dict[str, list[str]] = {}
    exact = {page["path"] for page in inventory["wiki_pages"]}
    for page in inventory["wiki_pages"]:
        by_qmd_key.setdefault(_qmd_key(page["path"]), []).append(page["path"])

    resolved: list[str] = []
    seen: set[str] = set()
    for result_file in result_files:
        rel_path = _qmd_result_to_rel_path(result_file, root, collection)
        if not rel_path or not rel_path.startswith("wiki/"):
            continue
        if rel_path in exact:
            matches = [rel_path]
        else:
            matches = by_qmd_key.get(_qmd_key(rel_path), [])
        if len(matches) != 1:
            continue
        match = matches[0]
        if match not in seen:
            seen.add(match)
            resolved.append(match)
    return resolved


def _inventory_path_indexes(inventory: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    wiki_buckets: dict[str, list[str]] = {}
    raw_buckets: dict[str, list[str]] = {}
    for page in inventory["wiki_pages"]:
        wiki_buckets.setdefault(_qmd_key(page["path"]), []).append(page["path"])
    for note in inventory["raw_notes"]:
        raw_buckets.setdefault(_qmd_key(note["path"]), []).append(note["path"])
    wiki_by_key = {
        key: matches[0]
        for key, matches in wiki_buckets.items()
        if len(set(matches)) == 1
    }
    raw_by_key = {
        key: matches[0]
        for key, matches in raw_buckets.items()
        if len(set(matches)) == 1
    }
    return wiki_by_key, raw_by_key


def _resolve_qmd_result_paths(
    inventory: dict[str, Any],
    root: Path,
    result_files: list[str],
    collection: str,
) -> dict[str, list[str]]:
    wiki_by_key, raw_by_key = _inventory_path_indexes(inventory)
    exact_wiki = {page["path"] for page in inventory["wiki_pages"]}
    exact_raw = {note["path"] for note in inventory["raw_notes"]}

    wiki_pages: list[str] = []
    raw_notes: list[str] = []
    unresolved: list[str] = []
    seen_wiki: set[str] = set()
    seen_raw: set[str] = set()

    for result_file in result_files:
        rel_path = _qmd_result_to_rel_path(result_file, root, collection)
        if not rel_path:
            unresolved.append(result_file)
            continue
        match: str | None = None
        if rel_path.startswith("wiki/"):
            match = rel_path if rel_path in exact_wiki else wiki_by_key.get(_qmd_key(rel_path))
            if match and match not in seen_wiki:
                seen_wiki.add(match)
                wiki_pages.append(match)
            elif not match:
                unresolved.append(result_file)
        elif rel_path.startswith("raw/"):
            match = rel_path if rel_path in exact_raw else raw_by_key.get(_qmd_key(rel_path))
            if match and match not in seen_raw:
                seen_raw.add(match)
                raw_notes.append(match)
            elif not match:
                unresolved.append(result_file)
        else:
            unresolved.append(result_file)
    return {
        "wiki_pages": wiki_pages,
        "raw_notes": raw_notes,
        "unresolved": unresolved,
    }


def _unique_page_index(pages: list[dict[str, Any]]) -> dict[str, str]:
    buckets: dict[str, list[str]] = {}
    for page in pages:
        path = page["path"]
        for value in (page.get("title") or "", Path(path).stem):
            key = _title_key(value)
            if key:
                buckets.setdefault(key, []).append(path)
    return {
        key: matches[0]
        for key, matches in buckets.items()
        if len(set(matches)) == 1
    }


def _page_paths_from_wikilinks(content: str, page_by_key: dict[str, str]) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {}
    for link in WIKILINK_RE.finditer(content):
        target = link.group(1).strip()
        variants = [target]
        if target.endswith(".md"):
            variants.append(target[:-3])
        variants.append(Path(target).stem)
        for variant in variants:
            key = _title_key(variant)
            page = page_by_key.get(key)
            if page:
                matches.setdefault(page, set()).add("wikilink")
    return matches


def _page_paths_from_raw_title(raw: dict[str, Any], page_by_key: dict[str, str]) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {}
    candidates = []
    candidates.extend(_title_variants(raw.get("title") or ""))
    candidates.extend(_title_variants(Path(raw["path"]).stem))
    for candidate in candidates:
        key = _title_key(candidate)
        page = page_by_key.get(key)
        if page:
            matches.setdefault(page, set()).add("title-match")
    return matches


def _raw_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": raw["path"],
        "title": raw.get("title"),
        "date": raw.get("date"),
        "source_type": raw.get("source_type"),
    }


def _map_raw_notes_to_pages(
    root: Path,
    inventory: dict[str, Any],
    raw_paths: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    raw_by_path = {note["path"]: note for note in inventory["raw_notes"]}
    page_by_key = _unique_page_index(inventory["wiki_pages"])
    mappings: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    mapped_pages: list[str] = []
    seen_pages: set[str] = set()

    for raw_path in raw_paths:
        raw = raw_by_path.get(raw_path)
        if not raw:
            continue
        content = ""
        try:
            content = (root / raw_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        page_reasons = _page_paths_from_wikilinks(content, page_by_key)
        for page, reasons in _page_paths_from_raw_title(raw, page_by_key).items():
            page_reasons.setdefault(page, set()).update(reasons)

        if not page_reasons:
            item = _raw_summary(raw)
            item["reason"] = "no-canonical-page-match"
            unmapped.append(item)
            continue

        pages = sorted(page_reasons)
        for page in pages:
            if page not in seen_pages:
                seen_pages.add(page)
                mapped_pages.append(page)
        summary = _raw_summary(raw)
        summary["raw_path"] = raw["path"]
        summary["mapped_pages"] = pages
        summary["reasons"] = sorted({reason for reasons in page_reasons.values() for reason in reasons})
        mappings.append(summary)
    return mappings, unmapped, mapped_pages


def _selected_pages(
    inventory: dict[str, Any],
    pages: list[str] | None,
) -> list[dict[str, Any]]:
    if pages is None:
        return inventory["wiki_pages"]

    by_path = {page["path"]: page for page in inventory["wiki_pages"]}
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for requested in pages:
        rel_path = _normalize_page_arg(requested)
        page = by_path.get(rel_path)
        if page is None:
            missing.append(rel_path)
        else:
            selected.append(page)
    if missing:
        raise FileNotFoundError(f"Wiki page not found: {', '.join(missing)}")
    return selected


def _legacy_reason(page: dict[str, Any]) -> str | None:
    if page.get("validation_issues"):
        return "invalid-provenance"
    blocks = page.get("blocks", [])
    if not blocks:
        return "no-block-provenance"
    if any(not block.get("has_provenance") for block in blocks):
        return "blocks-without-provenance"
    return None


def _freshness_action(block: dict[str, Any], intent: str) -> str:
    provenance = block.get("provenance", {})
    if provenance.get("provenance_quality") == "minimal-risk-stamp":
        return "use-as-page-caution"
    status = block.get("status") or "unknown"
    if intent == "history":
        if status in {"historical", "superseded"}:
            return "prefer"
        if status == "current":
            return "current-context"
        return "rank-lower-explain"
    if intent == "change":
        if status in {"current", "historical", "superseded", "stale"}:
            return "compare"
        return "rank-lower-explain"
    if status == "current":
        return "prefer"
    if status == "superseded":
        return "do-not-use-as-current"
    if status in {"historical", "stale", "disputed"}:
        return "rank-lower-explain"
    return "verify-before-using"


def _date_fragment(block: dict[str, Any]) -> str:
    observed = block.get("observed")
    checked = block.get("checked")
    parts = []
    if observed:
        parts.append(f"observed {observed}")
    if checked:
        parts.append(f"checked {checked}")
    return ", ".join(parts) if parts else "no dates recorded"


def _freshness_note(block: dict[str, Any], intent: str) -> str:
    status = block.get("status") or "unknown"
    confidence = block.get("confidence") or "unknown"
    dates = _date_fragment(block)
    provenance = block.get("provenance", {})
    if provenance.get("provenance_quality") == "minimal-risk-stamp":
        evidence_latest = provenance.get("evidence_latest")
        latest = f" latest related evidence {evidence_latest};" if evidence_latest else ""
        review_mode = provenance.get("review_mode")
        mode = f" review mode {review_mode};" if review_mode else ""
        return (
            "Minimal page-level freshness stamp only;"
            f"{latest}{mode} detailed page claims are not yet block-mapped; "
            f"{confidence} confidence; {dates}."
        )
    if intent == "history":
        if status == "historical":
            return f"historical block; {confidence} confidence; {dates}."
        if status == "superseded":
            target = block.get("provenance", {}).get("superseded_by")
            suffix = f" Superseded by {target}." if target else ""
            return f"Superseded block remains useful for history; {confidence} confidence; {dates}.{suffix}"
        return f"{status} block used as supporting context for a history query; {confidence} confidence; {dates}."
    if intent == "change":
        return f"{status} block can be compared in a change-over-time answer; {confidence} confidence; {dates}."
    if status == "current":
        return f"current block; {confidence} confidence; {dates}."
    if status == "historical":
        return f"historical block; rank lower for current-state answers; {confidence} confidence; {dates}."
    if status == "stale":
        return f"Stale block; rank lower and explain freshness uncertainty; {confidence} confidence; {dates}."
    if status == "disputed":
        return f"Disputed block; do not present without explaining the dispute; {confidence} confidence; {dates}."
    if status == "superseded":
        target = block.get("provenance", {}).get("superseded_by")
        suffix = f" Superseded by {target}." if target else ""
        return f"Superseded block; do not use as the current answer; {confidence} confidence; {dates}.{suffix}"
    return f"Freshness is {status}; verify before using for a current-state answer; {confidence} confidence; {dates}."


def _block_candidates(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        for block in page.get("blocks", []):
            item = dict(block)
            item["page_path"] = page["path"]
            item["page_title"] = page["title"]
            candidates.append(item)
    return candidates


def _legacy_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in pages:
        reason = _legacy_reason(page)
        if reason:
            result.append({
                "path": page["path"],
                "title": page["title"],
                "reason": reason,
                "validation_issues": page.get("validation_issues", []),
            })
    return result


def build_query_packet(
    root: Path,
    query: str,
    pages: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Build a block-level freshness packet for retrieved candidate pages."""
    root = root.resolve()
    inventory = build_inventory(root)
    return _build_query_packet_from_inventory(inventory, query=query, pages=pages, limit=limit)


def _build_query_packet_from_inventory(
    inventory: dict[str, Any],
    query: str,
    pages: list[str] | None,
    limit: int,
) -> dict[str, Any]:
    selected = _selected_pages(inventory, pages)
    intent = classify_query_intent(query)

    ranked = rank_blocks(_block_candidates(selected), query=query)
    annotated: list[dict[str, Any]] = []
    for index, block in enumerate(ranked, start=1):
        item = dict(block)
        item["rank"] = index
        item["freshness_action"] = _freshness_action(block, intent)
        item["freshness_note"] = _freshness_note(block, intent)
        annotated.append(item)

    return {
        "query": query,
        "query_intent": intent,
        "candidate_pages": [page["path"] for page in selected],
        "ranked_blocks": annotated[:limit],
        "total_ranked_blocks": len(annotated),
        "legacy_pages": _legacy_pages(selected),
        "raw_mappings": [],
        "raw_evidence": [],
    }


def build_query_packet_from_qmd_results(
    root: Path,
    query: str,
    result_files: list[str],
    pages: list[str] | None = None,
    collection: str = "tomtom",
    limit: int = 10,
) -> dict[str, Any]:
    """Build a query packet from QMD result IDs, preserving raw-note hits."""
    root = root.resolve()
    inventory = build_inventory(root)
    resolved = _resolve_qmd_result_paths(inventory, root, result_files, collection)
    raw_mappings, raw_evidence, raw_pages = _map_raw_notes_to_pages(
        root,
        inventory,
        resolved["raw_notes"],
    )

    candidate_pages = list(pages or [])
    candidate_pages.extend(resolved["wiki_pages"])
    candidate_pages.extend(raw_pages)
    candidate_pages = list(dict.fromkeys(candidate_pages))

    packet = _build_query_packet_from_inventory(
        inventory,
        query=query,
        pages=candidate_pages,
        limit=limit,
    )
    packet["raw_mappings"] = raw_mappings
    packet["raw_evidence"] = raw_evidence
    packet["unresolved_qmd_results"] = resolved["unresolved"]
    return packet
