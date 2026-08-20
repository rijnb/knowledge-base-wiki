"""Tests for restoring per-claim source footnotes from legacy provenance callouts."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.legacy_callout import parse_provenance_callout  # noqa: E402
from lib.provenance import parse_provenance  # noqa: E402
from lib.source_footnotes import apply_footnotes, callout_block_sources  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]

BACKUP_PAGE = """# Topic

First claim. ^b1

Second claim. ^b2

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred
> blocks:
>   b1:
>     sources: ["raw/notes/a.md"]
>     observed: 2024-01-01
>     checked: 2026-07-09
>   b2:
>     sources: ["raw/notes/a.md", "raw/emails/b.md"]
>     observed: 2024-02-02
>     checked: 2026-07-09
"""

CURRENT_PAGE = """---
type: concept
sources:
  - id: s1
    resource: "raw/notes/a.md"
generated:
  by: "agent:wiki-ingest"
  at: 2026-07-24
---

# Topic

First claim. ^b1

Second claim. ^b2
"""


class LegacyCalloutTests(unittest.TestCase):
    def test_parses_block_sources_from_legacy_callout(self):
        parsed = parse_provenance_callout(BACKUP_PAGE)
        self.assertEqual(parsed["schema"], "kb-prov-v1")
        self.assertEqual(parsed["blocks"]["b1"]["sources"], ["raw/notes/a.md"])
        self.assertEqual(
            parsed["blocks"]["b2"]["sources"],
            ["raw/notes/a.md", "raw/emails/b.md"],
        )

    def test_callout_block_sources_maps_anchor_to_resources(self):
        self.assertEqual(
            callout_block_sources(BACKUP_PAGE),
            {
                "b1": ["raw/notes/a.md"],
                "b2": ["raw/notes/a.md", "raw/emails/b.md"],
            },
        )

    def test_page_without_callout_yields_no_blocks(self):
        self.assertEqual(callout_block_sources("# Plain\n\nNo callout.\n"), {})

    def test_splits_quoted_bare_filename_from_previous_source(self):
        # A quoted source without a path separator (e.g. "README.md") must not
        # be merged into the preceding source by the comma heuristic.
        page = (
            "# Schema\n\nClaim. ^b1\n\n"
            "> [!provenance]- Provenance\n"
            "> schema: kb-prov-v1\n"
            "> blocks:\n"
            ">   b1:\n"
            '>     sources: ["raw/notes/2026-06-05 AI Knowledge - company wide'
            ' knowledge base.md", "README.md"]\n'
        )
        self.assertEqual(
            callout_block_sources(page),
            {
                "b1": [
                    "raw/notes/2026-06-05 AI Knowledge - company wide knowledge base.md",
                    "README.md",
                ],
            },
        )

    def test_parses_flow_mapping_block_entries(self):
        page = (
            "# LOD\n\nClaim. ^lod-definition-01\n\n"
            "> [!provenance]- Provenance\n"
            "> schema: kb-prov-v1\n"
            "> blocks:\n"
            ">   lod-definition-01: {sources: [raw/notes/2026-07-08 Large Cache"
            " Discovery Results 2026.md], observed: 2026-07-08, checked:"
            " 2026-07-09, status: current, confidence: medium,"
            " provenance_quality: inferred}\n"
        )
        self.assertEqual(
            callout_block_sources(page),
            {
                "lod-definition-01": [
                    "raw/notes/2026-07-08 Large Cache Discovery Results 2026.md"
                ],
            },
        )


class ApplyFootnotesTests(unittest.TestCase):
    def test_inserts_footnote_ref_before_block_anchor(self):
        outcome = apply_footnotes(CURRENT_PAGE, {"b1": ["raw/notes/a.md"]})
        self.assertIn("First claim. [^s1] ^b1", outcome.content)

    def test_multiple_sources_yield_multiple_refs(self):
        outcome = apply_footnotes(CURRENT_PAGE, callout_block_sources(BACKUP_PAGE))
        self.assertIn("Second claim. [^s1][^s2] ^b2", outcome.content)

    def test_appends_missing_source_to_frontmatter_with_next_free_id(self):
        outcome = apply_footnotes(CURRENT_PAGE, callout_block_sources(BACKUP_PAGE))
        parsed = parse_provenance(outcome.content)
        self.assertEqual(
            parsed["sources"],
            [
                {"id": "s1", "resource": "raw/notes/a.md"},
                {"id": "s2", "resource": "raw/emails/b.md"},
            ],
        )
        self.assertEqual(outcome.added_sources, ("raw/emails/b.md",))

    def test_adds_footnote_definitions_for_referenced_ids(self):
        outcome = apply_footnotes(CURRENT_PAGE, callout_block_sources(BACKUP_PAGE))
        self.assertTrue(
            outcome.content.rstrip().endswith(
                "[^s1]: [[raw/notes/a.md]]\n[^s2]: [[raw/emails/b.md]]"
            ),
            outcome.content,
        )

    def test_is_idempotent(self):
        first = apply_footnotes(CURRENT_PAGE, callout_block_sources(BACKUP_PAGE))
        second = apply_footnotes(first.content, callout_block_sources(BACKUP_PAGE))
        self.assertEqual(first.content, second.content)
        self.assertEqual(second.inserted_refs, 0)
        self.assertEqual(second.added_sources, ())

    def test_reports_unmapped_anchors_and_stale_blocks(self):
        outcome = apply_footnotes(
            CURRENT_PAGE,
            {"b1": ["raw/notes/a.md"], "gone": ["raw/notes/a.md"]},
        )
        self.assertEqual(outcome.unmapped_anchors, ("b2",))
        self.assertEqual(outcome.stale_blocks, ("gone",))

    def test_skips_page_without_provenance_frontmatter(self):
        outcome = apply_footnotes(
            "---\ntype: concept\n---\n\n# Bare\n\nClaim. ^b1\n",
            {"b1": ["raw/notes/a.md"]},
        )
        self.assertEqual(outcome.action, "no-provenance")
        self.assertIsNone(outcome.content)


class RestoreFootnotesCliTests(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("wiki/concepts/Topic.md", CURRENT_PAGE)
        self.backup = self.root / "backup"
        (self.backup / "wiki/concepts").mkdir(parents=True)
        (self.backup / "wiki/concepts/Topic.md").write_text(
            BACKUP_PAGE, encoding="utf-8"
        )

    def run_cli(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-restore-source-footnotes.py"),
                "--root", str(self.root),
                "--backup", str(self.backup),
                *extra,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_dry_run_reports_but_does_not_write(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["would-update"], 1)
        self.assertNotIn("[^s1]", self.read("wiki/concepts/Topic.md"))

    def test_apply_writes_footnotes_and_reports(self):
        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["updated"], 1)
        content = self.read("wiki/concepts/Topic.md")
        self.assertIn("First claim. [^s1] ^b1", content)
        self.assertIn("[^s2]: [[raw/emails/b.md]]", content)

    def test_reports_current_page_missing_for_renamed_pages(self):
        (self.backup / "wiki/concepts/Renamed.md").write_text(
            BACKUP_PAGE, encoding="utf-8"
        )
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["missing-current"], 1)


if __name__ == "__main__":
    unittest.main()
