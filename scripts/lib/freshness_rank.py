"""Deterministic freshness ranking helpers for canonical blocks."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


HISTORY_TERMS = re.compile(r"\b(original|historical|historically|history|previous|previously|past|was|were)\b", re.I)
CHANGE_TERMS = re.compile(r"\b(change|changed|evolved|transition|timeline|over time)\b", re.I)
CURRENT_TERMS = re.compile(r"\b(current|currently|now|today|latest|present)\b", re.I)


def classify_query_intent(query: str) -> str:
    """Classify freshness intent for lightweight deterministic ranking."""
    if CHANGE_TERMS.search(query):
        return "change"
    if HISTORY_TERMS.search(query):
        return "history"
    if CURRENT_TERMS.search(query):
        return "current"
    return "current"


def _date_score(value: str | None) -> int:
    if not value:
        return 0
    try:
        checked = datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return 0
    # Coarse enough to avoid false precision, useful enough for tie-breaking.
    return checked.year * 12 + checked.month


def _confidence_score(value: str | None) -> int:
    return {
        "high": 20,
        "medium": 10,
        "low": 0,
    }.get(value or "", 0)


def _status_score(status: str, intent: str) -> int:
    if intent == "history":
        return {
            "historical": 70,
            "superseded": 55,
            "current": 35,
            "stale": 25,
            "disputed": 15,
            "open": 10,
            "unknown": 0,
        }.get(status, 0)
    if intent == "change":
        return {
            "current": 65,
            "historical": 55,
            "superseded": 45,
            "stale": 35,
            "disputed": 25,
            "open": 10,
            "unknown": 0,
        }.get(status, 0)
    return {
        "current": 80,
        "open": 25,
        "unknown": 20,
        "historical": 5,
        "stale": -15,
        "disputed": -25,
        "superseded": -70,
    }.get(status, 0)


def score_block(block: dict[str, Any], intent: str) -> int:
    status = block.get("status") or "unknown"
    return (
        _status_score(status, intent)
        + _confidence_score(block.get("confidence"))
        + min(_date_score(block.get("checked")) // 100, 30)
    )


def rank_blocks(blocks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Return blocks sorted by freshness suitability for the query.

    Blocks are never removed here. Superseded/disputed evidence remains
    inspectable, but current-state queries rank it lower.
    """
    intent = classify_query_intent(query)
    ranked = []
    for block in blocks:
        item = dict(block)
        item["query_intent"] = intent
        item["freshness_score"] = score_block(block, intent)
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["freshness_score"], item.get("id", "")))
