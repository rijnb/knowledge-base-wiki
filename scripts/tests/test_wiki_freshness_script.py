"""Tests for the one-command freshness wrapper."""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class WikiFreshnessScriptTests(VaultFixtureMixin, unittest.TestCase):
    def test_runs_checks_and_writes_queues(self):
        self.write("wiki/concepts/Concept.md", "# Concept\n\nKnown idea.\n")
        self.write(
            "raw/notes/Concept update.md",
            "---\ndate: 2026-06-21\n---\n\n[[Concept]] update.\n",
        )

        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/wiki-freshness.sh"),
                "--root",
                str(self.root),
                "--limit",
                "5",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wiki Freshness Check", result.stdout)
        self.assertIn("Freshness drift", result.stdout)
        self.assertTrue((self.root / ".wiki-scratch/freshness-curation-candidates.md").is_file())
        self.assertTrue((self.root / ".wiki-scratch/provenance-coverage-backlog.md").is_file())

    def test_lint_errors_do_not_skip_queue_generation(self):
        self.write(
            "wiki/concepts/Bad.md",
            """# Bad

Claim. ^actual

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   missing:
>     status: current
>     confidence: high
>     sources: [raw/notes/source.md]
""",
        )
        self.write(
            "raw/notes/source.md",
            "---\ndate: 2026-06-21\n---\n\n[[Bad]] update.\n",
        )

        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/wiki-freshness.sh"),
                "--root",
                str(self.root),
                "--limit",
                "5",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Provenance lint", result.stdout)
        self.assertIn("Freshness drift", result.stdout)
        self.assertIn("Provenance coverage", result.stdout)
        self.assertTrue((self.root / ".wiki-scratch/freshness-curation-candidates.md").is_file())
        self.assertTrue((self.root / ".wiki-scratch/provenance-coverage-backlog.md").is_file())

    def test_root_without_value_fails_cleanly(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/wiki-freshness.sh"), "--root"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--root requires", result.stderr)

    def test_limit_without_value_fails_cleanly(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/wiki-freshness.sh"), "--limit"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--limit requires", result.stderr)


if __name__ == "__main__":
    unittest.main()
