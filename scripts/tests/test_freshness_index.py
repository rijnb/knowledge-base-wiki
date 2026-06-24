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
    def test_indexes_wiki_blocks_with_heading_and_provenance(self):
        self.write(
            "wiki/concepts/Concept.md",
            """---
title: Concept
---

# Concept

## Current Understanding

Current ownership sits with the map enrichment flow. ^claim-owner-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred
> blocks:
>   claim-owner-01:
>     sources: [raw:meeting-2026-06-02#b08]
>     observed: 2026-06-02
>     checked: 2026-06-20
>     status: current
>     confidence: medium
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["summary"]["wiki_pages"], 1)
        self.assertEqual(inventory["summary"]["canonical_blocks"], 1)
        self.assertEqual(inventory["summary"]["blocks_with_provenance"], 1)
        page = inventory["wiki_pages"][0]
        self.assertEqual(page["path"], "wiki/concepts/Concept.md")
        self.assertEqual(page["title"], "Concept")
        self.assertEqual(page["migration_status"], "legacy-inferred")
        block = page["blocks"][0]
        self.assertEqual(block["id"], "claim-owner-01")
        self.assertEqual(block["heading_path"], ["Concept", "Current Understanding"])
        self.assertEqual(block["status"], "current")
        self.assertEqual(block["confidence"], "medium")
        self.assertEqual(block["sources"], ["raw:meeting-2026-06-02#b08"])
        self.assertEqual(block["text"], "Current ownership sits with the map enrichment flow.")

    def test_two_blocks_in_one_paragraph_get_their_own_text(self):
        self.write(
            "wiki/concepts/Dense.md",
            """# Dense

Claim one is here. ^claim-one
Claim two is here. ^claim-two
""",
        )

        inventory = build_inventory(self.root)
        blocks = {b["id"]: b for b in inventory["wiki_pages"][0]["blocks"]}

        self.assertEqual(blocks["claim-one"]["text"], "Claim one is here.")
        self.assertEqual(blocks["claim-two"]["text"], "Claim two is here.")

    def test_counts_blocks_without_provenance(self):
        self.write(
            "wiki/concepts/Legacy.md",
            """# Legacy

This block has an ID but no provenance yet. ^claim-legacy-01
""",
        )

        inventory = build_inventory(self.root)

        self.assertEqual(inventory["summary"]["canonical_blocks"], 1)
        self.assertEqual(inventory["summary"]["blocks_with_provenance"], 0)
        self.assertEqual(inventory["summary"]["blocks_without_provenance"], 1)
        block = inventory["wiki_pages"][0]["blocks"][0]
        self.assertEqual(block["status"], "unknown")
        self.assertEqual(block["sources"], [])

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

We agreed to pilot block provenance.
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
        self.assertEqual(payload["summary"]["canonical_blocks"], 1)


if __name__ == "__main__":
    unittest.main()
