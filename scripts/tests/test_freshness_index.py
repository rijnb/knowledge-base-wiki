"""Tests for the read-only freshness inventory."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.freshness_index import build_inventory  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class FreshnessInventoryTests(VaultFixtureMixin, unittest.TestCase):
    def test_indexes_wiki_page_with_frontmatter_provenance(self):
        self.write(
            "wiki/concepts/Concept.md",
            """---
title: Concept
state: active
sources:
  - id: s1
    resource: "raw/notes/2026-06-02 Meeting.md"
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-02
verified:
  - by: "agent:wiki-freshness"
    at: 2026-06-20
---

# Concept

## Current Understanding

Current ownership sits with the map enrichment flow. ^claim-owner-01
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["summary"]["wiki_pages"], 1)
        self.assertEqual(inventory["summary"]["pages_with_provenance"], 1)
        self.assertEqual(inventory["summary"]["pages_without_provenance"], 0)
        page = inventory["wiki_pages"][0]
        self.assertEqual(page["path"], "wiki/concepts/Concept.md")
        self.assertEqual(page["title"], "Concept")
        self.assertEqual(page["state"], "active")
        self.assertTrue(page["has_provenance"])
        self.assertEqual(page["generated_at"], "2026-06-02")
        self.assertEqual(page["verified_at"], "2026-06-20")
        self.assertEqual(page["checked"], "2026-06-20")
        self.assertEqual(page["status"], "current")
        self.assertEqual(page["confidence"], "medium")
        self.assertEqual(page["sources"], ["raw/notes/2026-06-02 Meeting.md"])
        self.assertEqual(page["validation_issues"], [])

    def test_counts_pages_without_provenance(self):
        self.write(
            "wiki/concepts/Legacy.md",
            """# Legacy

This page has no provenance yet. ^claim-legacy-01
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["summary"]["pages_with_provenance"], 0)
        self.assertEqual(inventory["summary"]["pages_without_provenance"], 1)
        page = inventory["wiki_pages"][0]
        self.assertFalse(page["has_provenance"])
        self.assertEqual(page["status"], "unknown")
        self.assertEqual(page["confidence"], "unknown")
        self.assertEqual(page["sources"], [])

    def test_human_verification_raises_confidence(self):
        self.write(
            "wiki/concepts/Reviewed.md",
            """---
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-02
verified:
  - by: "human:ribu"
    at: 2026-06-20
sources:
  - id: s1
    resource: "raw/notes/source.md"
---

# Reviewed
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["wiki_pages"][0]["confidence"], "high")

    def test_passed_stale_after_marks_page_stale(self):
        self.write(
            "wiki/concepts/Stale.md",
            """---
generated:
  by: "agent:wiki-ingest"
  at: 2020-01-01
sources:
  - id: s1
    resource: "raw/notes/source.md"
stale_after: 2020-06-01
---

# Stale
""",
        )

        inventory = build_inventory(self.root)

        page = inventory["wiki_pages"][0]
        self.assertEqual(page["status"], "stale")
        self.assertEqual(page["stale_after"], "2020-06-01")

    def test_indexes_raw_notes_with_frontmatter_date_and_headings(self):
        self.write(
            "raw/notes/Meeting.md",
            """---
title: Weekly Meeting
date: 2026-06-20
source_type: meeting
---

# Weekly Meeting

## Decisions

We agreed to pilot page provenance.
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["summary"]["raw_notes"], 1)
        note = inventory["raw_notes"][0]
        self.assertEqual(note["path"], "raw/notes/Meeting.md")
        self.assertEqual(note["title"], "Weekly Meeting")
        self.assertEqual(note["date"], "2026-06-20")
        self.assertEqual(note["source_type"], "meeting")
        self.assertEqual(note["headings"], ["Weekly Meeting", "Decisions"])

    def test_skips_ingest_false_raw_notes_and_linked_raw_notes(self):
        self.write(
            "raw/notes/Sensitive.md",
            """---
ingest: false
date: 2026-06-22
---

# Sensitive

Private note with [[linked/Linked Secret]].
""",
        )
        self.write(
            "raw/notes/linked/Linked Secret.md",
            """---
date: 2026-06-22
---

# Linked Secret

Private linked context.
""",
        )
        self.write("raw/notes/Public.md", "# Public\n\nOrdinary evidence.\n")

        inventory = build_inventory(self.root)

        self.assertEqual(
            [note["path"] for note in inventory["raw_notes"]],
            ["raw/notes/Public.md"],
        )


class FreshnessInventoryCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_cli_outputs_inventory_json(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nClaim. ^claim-01\n")
        self.write("raw/notes/Note.md", "# Note\n\nEvidence.\n")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-freshness-inventory.py"),
                "--root",
                str(self.root),
                "--format",
                "json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["wiki_pages"], 1)
        self.assertEqual(payload["summary"]["raw_notes"], 1)
        self.assertEqual(payload["summary"]["pages_without_provenance"], 1)


if __name__ == "__main__":
    unittest.main()
