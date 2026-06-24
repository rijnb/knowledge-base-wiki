"""Evaluation tests for freshness-aware block ranking."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.freshness_rank import classify_query_intent, rank_blocks  # noqa: E402


def block(block_id: str, status: str, confidence: str = "medium", checked: str | None = None):
    return {
        "id": block_id,
        "status": status,
        "confidence": confidence,
        "checked": checked,
        "text": f"{block_id} text",
    }


class QueryIntentTests(unittest.TestCase):
    def test_classifies_current_query(self):
        self.assertEqual(classify_query_intent("What is the current owner?"), "current")

    def test_classifies_history_query(self):
        self.assertEqual(classify_query_intent("What was the original decision?"), "history")

    def test_classifies_historically_as_history_query(self):
        self.assertEqual(classify_query_intent("What did this argue historically?"), "history")

    def test_classifies_change_query(self):
        self.assertEqual(classify_query_intent("How did this change over time?"), "change")


class FreshnessRankingTests(unittest.TestCase):
    def test_current_query_prefers_current_over_superseded(self):
        ranked = rank_blocks([
            block("old", "superseded", "high", "2026-06-20"),
            block("now", "current", "medium", "2026-01-10"),
        ], query="What is current?")

        self.assertEqual([item["id"] for item in ranked], ["now", "old"])
        self.assertLess(ranked[1]["freshness_score"], ranked[0]["freshness_score"])

    def test_history_query_keeps_historical_context_high(self):
        ranked = rank_blocks([
            block("now", "current", "high", "2026-06-20"),
            block("history", "historical", "medium", "2024-01-10"),
        ], query="What was the original approach?")

        self.assertEqual(ranked[0]["id"], "history")

    def test_disputed_blocks_are_demoted_but_not_removed(self):
        ranked = rank_blocks([
            block("disputed", "disputed", "high", "2026-06-20"),
            block("current", "current", "medium", "2026-06-01"),
        ], query="What is current?")

        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["id"], "current")
        self.assertEqual(ranked[1]["id"], "disputed")


if __name__ == "__main__":
    unittest.main()
