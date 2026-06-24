"""Unit tests for the pure freshness ranking primitives."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.freshness_rank import rank_blocks, score_block  # noqa: E402


def block(block_id, status="current", confidence="medium", checked=None):
    return {
        "id": block_id,
        "status": status,
        "confidence": confidence,
        "checked": checked,
    }


class ScoreBlockTests(unittest.TestCase):
    def test_score_does_not_depend_on_check_date(self):
        # Recency is a tie-breaker, not part of the primary score; two blocks
        # that differ only by checked date must score identically.
        old = score_block(block("a", checked="2001-01-01"), "current")
        new = score_block(block("a", checked="2026-06-24"), "current")
        self.assertEqual(old, new)

    def test_status_outranks_confidence(self):
        current_low = score_block(block("a", "current", "low"), "current")
        superseded_high = score_block(block("b", "superseded", "high"), "current")
        self.assertGreater(current_low, superseded_high)


class RankBlocksRecencyTests(unittest.TestCase):
    def test_newer_checked_outranks_older_when_status_and_confidence_equal(self):
        # Ids are chosen so an alphabetical id tie-break would give the WRONG
        # order; only genuine recency ranking produces ["z-newer", "a-older"].
        ranked = rank_blocks(
            [
                block("a-older", "current", "medium", "2024-01-10"),
                block("z-newer", "current", "medium", "2026-06-20"),
            ],
            query="What is the current state?",
        )
        self.assertEqual([item["id"] for item in ranked], ["z-newer", "a-older"])

    def test_missing_check_date_ranks_after_dated_block_on_a_tie(self):
        # "a-dated" would already win on id; use ids where recency must override.
        ranked = rank_blocks(
            [
                block("a-undated", "current", "medium", None),
                block("z-dated", "current", "medium", "2020-01-01"),
            ],
            query="current state",
        )
        self.assertEqual([item["id"] for item in ranked], ["z-dated", "a-undated"])

    def test_status_still_wins_over_recency(self):
        ranked = rank_blocks(
            [
                block("fresh-but-superseded", "superseded", "medium", "2026-06-20"),
                block("stale-but-current", "current", "medium", "2020-01-01"),
            ],
            query="What is current?",
        )
        self.assertEqual(ranked[0]["id"], "stale-but-current")


if __name__ == "__main__":
    unittest.main()
