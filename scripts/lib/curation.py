"""One-page curation packet generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .drift import detect_drift
from .freshness_index import build_inventory


def _normalize_page_arg(page: str) -> str:
    value = page.strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].split("|", 1)[0]
    if not value.endswith(".md"):
        value += ".md"
    return value


def _find_page(inventory: dict[str, Any], rel_path: str) -> dict[str, Any]:
    for page in inventory["wiki_pages"]:
        if page["path"] == rel_path:
            return page
    raise FileNotFoundError(f"Wiki page not found: {rel_path}")


def _raw_lookup(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {note["path"]: note for note in inventory["raw_notes"]}


def _suggested_actions(page: dict[str, Any], drift: dict[str, Any] | None) -> list[str]:
    actions = ["confirm", "revise", "split", "move-to-history"]
    statuses = {block.get("status") for block in page.get("blocks", [])}
    reasons = set(drift.get("reasons", []) if drift else [])
    if "superseded" in statuses or "newer-related-raw" in reasons:
        actions.append("supersede")
    if "disputed" in statuses:
        actions.append("resolve-dispute")
    if not page.get("blocks"):
        actions.append("add-block-provenance")
    return actions


def build_page_packet(root: Path, page: str) -> dict[str, Any]:
    """Return a read-only packet for curating one canonical page."""
    root = root.resolve()
    rel_path = _normalize_page_arg(page)
    inventory = build_inventory(root)
    page_entry = _find_page(inventory, rel_path)
    drift_result = detect_drift(root)
    drift = next(
        (candidate for candidate in drift_result["candidates"] if candidate["page"] == rel_path),
        None,
    )
    raw_by_path = _raw_lookup(inventory)
    related_raw = [
        raw_by_path[path]
        for path in (drift.get("related_raw", []) if drift else [])
        if path in raw_by_path
    ]
    return {
        "page": page_entry,
        "drift": drift or {
            "page": rel_path,
            "score": 0,
            "reasons": [],
            "related_raw_count": 0,
            "related_raw": [],
        },
        "related_raw": related_raw,
        "suggested_actions": _suggested_actions(page_entry, drift),
    }
