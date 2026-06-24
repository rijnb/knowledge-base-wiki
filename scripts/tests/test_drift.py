"""Tests for read-only freshness drift detection."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.drift import detect_drift  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class DriftDetectionTests(VaultFixtureMixin, unittest.TestCase):
    def test_detects_newer_related_raw_note_than_checked_block(self):
        self.write(
            "wiki/concepts/Concept.md",
            """# Concept

Current claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: [raw:old-note#b1]
>     observed: 2026-01-01
>     checked: 2026-01-10
>     status: current
>     confidence: medium
""",
        )
        self.write(
            "raw/notes/New meeting.md",
            """---
date: 2026-06-20
---

# New meeting

We discussed [[Concept]] and changed its current claim.
""",
        )

        result = detect_drift(self.root)

        self.assertEqual(result["summary"]["candidates"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["page"], "wiki/concepts/Concept.md")
        self.assertGreater(candidate["score"], 0)
        self.assertIn("newer-related-raw", candidate["reasons"])
        self.assertEqual(candidate["latest_related_raw_date"], "2026-06-20")
        self.assertEqual(candidate["checked"], "2026-01-10")

    def test_legacy_page_related_to_raw_note_is_candidate(self):
        self.write("wiki/concepts/Legacy Concept.md", "# Legacy Concept\n\nKnown idea.\n")
        self.write(
            "raw/notes/Legacy followup.md",
            """---
date: 2026-06-21
---

This follow-up is about [[Legacy Concept]].
""",
        )

        candidate = detect_drift(self.root)["candidates"][0]

        self.assertEqual(candidate["page"], "wiki/concepts/Legacy Concept.md")
        self.assertIn("legacy-page-no-block-provenance", candidate["reasons"])
        self.assertEqual(candidate["related_raw_count"], 1)

    def test_ambiguous_page_title_suppresses_raw_signal(self):
        # Two wiki pages share a filename/title in different folders, so a raw
        # wikilink cannot be attributed to one of them. The newer-raw signal
        # must be suppressed and the ambiguity flagged instead.
        self.write("wiki/people/John.md", "# John\n\nA person.\n")
        self.write("wiki/projects/John.md", "# John\n\nA project.\n")
        self.write(
            "raw/notes/Update.md",
            "---\ndate: 2026-06-21\n---\n\nNotes about [[John]].\n",
        )

        result = detect_drift(self.root)
        for candidate in result["candidates"]:
            if candidate["title"].lower() == "john":
                self.assertIn("ambiguous-title", candidate["reasons"])
                self.assertNotIn("newer-related-raw", candidate["reasons"])
                self.assertNotIn("unreviewed-related-raw", candidate["reasons"])

    def test_unrelated_raw_note_does_not_create_candidate(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nKnown idea.\n")
        self.write("raw/notes/Other.md", "---\ndate: 2026-06-21\n---\n\nNothing related.\n")

        self.assertEqual(detect_drift(self.root)["candidates"], [])

    def test_ingest_false_raw_note_does_not_create_candidate(self):
        self.write("wiki/concepts/Secret Topic.md", "# Secret Topic\n\nKnown idea.\n")
        self.write(
            "raw/notes/Sensitive.md",
            """---
ingest: false
date: 2026-06-21
---

# Secret Topic

Private notes about [[Secret Topic]].
""",
        )

        result = detect_drift(self.root)

        self.assertEqual(result["summary"]["raw_notes_checked"], 0)
        self.assertEqual(result["candidates"], [])


class DriftCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_cli_outputs_candidates_json(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nKnown idea.\n")
        self.write("raw/notes/Note.md", "---\ndate: 2026-06-21\n---\n\n[[Concept]] update.\n")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-drift-detect.py"),
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
        self.assertEqual(payload["summary"]["candidates"], 1)

    def test_cli_writes_queue_when_requested(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nKnown idea.\n")
        self.write("raw/notes/Note.md", "---\ndate: 2026-06-21\n---\n\n[[Concept]] update.\n")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-drift-detect.py"),
                "--root",
                str(self.root),
                "--write-queue",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        queue = self.root / ".wiki-scratch/freshness-curation-candidates.md"
        self.assertTrue(queue.is_file())
        self.assertIn("[[wiki/concepts/Concept]]", queue.read_text(encoding="utf-8"))

    def test_rejects_negative_limit(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-drift-detect.py"),
                "--root",
                str(self.root),
                "--limit",
                "-1",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("limit", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
