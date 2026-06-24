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
            """# Covered

Current claim. ^covered-claim

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   covered-claim:
>     sources: [raw/notes/source.md]
>     checked: 2026-06-24
>     status: current
>     confidence: high
""",
        )
        self.write("wiki/concepts/Legacy.md", "# Legacy\n\nNo block IDs yet.\n")
        self.write("wiki/systems/Partial.md", "# Partial\n\nKnown claim. ^partial-claim\n")

        result = build_coverage_backlog(self.root)

        self.assertEqual(result["summary"]["wiki_pages"], 3)
        self.assertEqual(result["summary"]["covered_pages"], 1)
        self.assertEqual(result["summary"]["backlog_pages"], 2)
        self.assertEqual(result["summary"]["by_status"]["covered"], 1)
        self.assertEqual(result["summary"]["by_status"]["legacy-no-block-ids"], 1)
        self.assertEqual(result["summary"]["by_status"]["block-ids-without-provenance"], 1)
        self.assertEqual(
            [page["path"] for page in result["pages"]],
            ["wiki/systems/Partial.md", "wiki/concepts/Legacy.md"],
        )

    def test_writes_backlog_markdown(self):
        self.write("wiki/concepts/Legacy.md", "# Legacy\n")

        result = build_coverage_backlog(self.root)
        path = write_backlog(self.root, result)

        self.assertEqual(path.relative_to(self.root).as_posix(), ".wiki-scratch/provenance-coverage-backlog.md")
        content = self.read(".wiki-scratch/provenance-coverage-backlog.md")
        self.assertIn("[[wiki/concepts/Legacy]]", content)
        self.assertIn("legacy-no-block-ids", content)

    def test_minimal_stamp_remains_in_coverage_backlog(self):
        self.write(
            "wiki/concepts/Minimal.md",
            """# Minimal

## Freshness Status

This page has a minimal provenance stamp only. ^freshness-status

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred-minimal
> blocks:
>   freshness-status:
>     checked: 2026-06-24
>     status: current
>     confidence: medium
""",
        )

        result = build_coverage_backlog(self.root)

        self.assertEqual(result["summary"]["covered_pages"], 0)
        self.assertEqual(result["summary"]["by_status"]["minimal-stamp"], 1)
        self.assertEqual(result["pages"][0]["coverage_status"], "minimal-stamp")


    def test_missing_sources_warning_does_not_mark_page_invalid(self):
        # A claim block with provenance but no sources is a quality *warning*,
        # not a structural error; coverage must not classify it as invalid.
        self.write(
            "wiki/concepts/Warned.md",
            """# Warned

Current claim. ^warned-claim

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   warned-claim:
>     checked: 2026-06-24
>     status: current
>     confidence: high
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


if __name__ == "__main__":
    unittest.main()
