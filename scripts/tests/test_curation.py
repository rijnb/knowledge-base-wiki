"""Tests for one-page curation packet generation."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.curation import build_page_packet  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class CurationPacketTests(VaultFixtureMixin, unittest.TestCase):
    def test_packet_contains_page_blocks_and_related_raw_notes(self):
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
            "raw/notes/Note.md",
            """---
date: 2026-06-21
---

This update links to [[Concept]].
""",
        )

        packet = build_page_packet(self.root, "wiki/concepts/Concept.md")

        self.assertEqual(packet["page"]["path"], "wiki/concepts/Concept.md")
        self.assertEqual(packet["page"]["blocks"][0]["id"], "claim-01")
        self.assertEqual(packet["related_raw"][0]["path"], "raw/notes/Note.md")
        self.assertIn("newer-related-raw", packet["drift"]["reasons"])
        self.assertIn("revise", packet["suggested_actions"])
        self.assertIn("supersede", packet["suggested_actions"])

    def test_accepts_wikilink_target(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nCurrent claim.\n")

        packet = build_page_packet(self.root, "[[wiki/concepts/Concept]]")

        self.assertEqual(packet["page"]["path"], "wiki/concepts/Concept.md")


class CurationCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_cli_outputs_packet_json(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nCurrent claim.\n")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-curate-page.py"),
                "--root",
                str(self.root),
                "--page",
                "wiki/concepts/Concept.md",
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
        self.assertEqual(payload["page"]["path"], "wiki/concepts/Concept.md")


if __name__ == "__main__":
    unittest.main()
