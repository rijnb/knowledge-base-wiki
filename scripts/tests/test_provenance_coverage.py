"""Tests for provenance coverage backlog generation."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.provenance_coverage import build_coverage_backlog, write_backlog  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class ProvenanceCoverageTests(VaultFixtureMixin, unittest.TestCase):
    def test_reports_covered_and_backlog_pages(self):
        self.write(
            "wiki/concepts/Covered.md",
            """---
sources:
  - id: s1
    resource: "raw/notes/source.md"
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-01
verified:
  - by: "agent:wiki-freshness"
    at: 2026-06-24
---

# Covered

Current claim. ^covered-claim
""",
        )
        self.write("wiki/concepts/Legacy.md", "# Legacy\n\nNo provenance yet.\n")
        self.write("wiki/systems/System.md", "# System\n\nKnown claim. ^system-claim\n")

        result = build_coverage_backlog(self.root)

        self.assertEqual(result["summary"]["wiki_pages"], 3)
        self.assertEqual(result["summary"]["covered_pages"], 1)
        self.assertEqual(result["summary"]["backlog_pages"], 2)
        self.assertEqual(result["summary"]["by_status"]["covered"], 1)
        self.assertEqual(result["summary"]["by_status"]["no-provenance"], 2)
        self.assertEqual(
            [page["path"] for page in result["pages"]],
            ["wiki/systems/System.md", "wiki/concepts/Legacy.md"],
        )

    def test_writes_backlog_markdown(self):
        self.write("wiki/concepts/Legacy.md", "# Legacy\n")

        result = build_coverage_backlog(self.root)
        path = write_backlog(self.root, result)

        self.assertEqual(path.relative_to(self.root).as_posix(), ".wiki-scratch/provenance-coverage-backlog.md")
        content = self.read(".wiki-scratch/provenance-coverage-backlog.md")
        self.assertIn("[[wiki/concepts/Legacy]]", content)
        self.assertIn("no-provenance", content)

    def test_invalid_provenance_ranks_first_in_backlog(self):
        self.write(
            "wiki/concepts/Broken.md",
            """---
generated:
  by: "agent:wiki-ingest"
  at: soon
sources:
  - id: s1
    resource: "raw/notes/source.md"
---

# Broken
""",
        )
        self.write("wiki/concepts/Legacy.md", "# Legacy\n")

        result = build_coverage_backlog(self.root)

        self.assertEqual(result["summary"]["by_status"]["invalid-provenance"], 1)
        self.assertEqual(result["pages"][0]["path"], "wiki/concepts/Broken.md")
        self.assertEqual(result["pages"][0]["coverage_status"], "invalid-provenance")

    def test_missing_sources_warning_does_not_mark_page_invalid(self):
        # Generated provenance without sources is a quality *warning*, not a
        # structural error; coverage must not classify it as invalid.
        self.write(
            "wiki/concepts/Warned.md",
            """---
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-24
---

# Warned

Current claim. ^warned-claim
""",
        )

        result = build_coverage_backlog(self.root)

        self.assertEqual(result["summary"]["covered_pages"], 1)
        self.assertNotIn("invalid-provenance", result["summary"]["by_status"])


class ProvenanceCoverageCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_cli_outputs_json(self):
        self.write("wiki/concepts/Legacy.md", "# Legacy\n")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-provenance-coverage.py"),
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
        self.assertEqual(payload["summary"]["backlog_pages"], 1)

    def test_rejects_negative_limit(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-provenance-coverage.py"),
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
