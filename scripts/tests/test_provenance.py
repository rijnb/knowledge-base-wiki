"""Tests for frontmatter provenance parsing and validation (OKF v0.2)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.provenance import (  # noqa: E402
    extract_block_ids,
    parse_provenance,
    provenance_dates,
    validate_provenance,
)


ROOT = Path(__file__).resolve().parents[2]


VALID_PAGE = """---
type: concept
tags: [tomtom, maps]
state: active
sources:
  - id: s1
    resource: "raw/notes/2024-04-04 Foo.md"
  - id: s2
    resource: "raw/notes/2026-06-02 Bar.md"
    title: "Bar meeting"
    last_modified: 2026-06-02
generated:
  by: "agent:wiki-ingest"
  at: 2024-04-04
verified:
  - by: "agent:wiki-freshness"
    at: 2026-06-25
  - by: "human:ribu"
    at: 2026-07-01
stale_after: 2027-01-01
---

# Concept

Current ownership sits with the map enrichment flow. ^claim-owner-01
"""


class BlockIdExtractionTests(unittest.TestCase):
    def test_extracts_block_ids_outside_fenced_code(self):
        content = """A real claim. ^claim-real

```markdown
This example should not count. ^claim-example
```

Another claim. ^claim-second
"""
        self.assertEqual(
            extract_block_ids(content),
            {"claim-real": 1, "claim-second": 1},
        )

    def test_counts_duplicate_block_ids(self):
        content = "First. ^claim-dup\n\nSecond. ^claim-dup\n"
        self.assertEqual(extract_block_ids(content), {"claim-dup": 2})


class ProvenanceParsingTests(unittest.TestCase):
    def test_parses_frontmatter_provenance(self):
        parsed = parse_provenance(VALID_PAGE)

        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["sources"][0],
            {"id": "s1", "resource": "raw/notes/2024-04-04 Foo.md"},
        )
        self.assertEqual(parsed["sources"][1]["title"], "Bar meeting")
        self.assertEqual(parsed["sources"][1]["last_modified"], "2026-06-02")
        self.assertEqual(
            parsed["generated"],
            {"by": "agent:wiki-ingest", "at": "2024-04-04"},
        )
        self.assertEqual(
            parsed["verified"],
            [
                {"by": "agent:wiki-freshness", "at": "2026-06-25"},
                {"by": "human:ribu", "at": "2026-07-01"},
            ],
        )
        self.assertEqual(parsed["stale_after"], "2027-01-01")

    def test_returns_none_without_provenance_keys(self):
        self.assertIsNone(parse_provenance("# No frontmatter\n\nBody\n"))
        self.assertIsNone(parse_provenance("---\ntype: concept\nstate: active\n---\n\n# Page\n"))

    def test_missing_optional_keys_default_to_empty(self):
        content = """---
generated:
  by: "agent:wiki-ingest"
  at: 2024-04-04
---

# Page
"""
        parsed = parse_provenance(content)

        self.assertEqual(parsed["sources"], [])
        self.assertEqual(parsed["verified"], [])
        self.assertIsNone(parsed["stale_after"])

    def test_provenance_dates_returns_generated_and_latest_verified(self):
        parsed = parse_provenance(VALID_PAGE)

        self.assertEqual(provenance_dates(parsed), ("2024-04-04", "2026-07-01"))
        self.assertEqual(provenance_dates(None), (None, None))


class ProvenanceValidationTests(unittest.TestCase):
    def issue_codes(self, content: str) -> set[str]:
        return {issue.code for issue in validate_provenance(content, path="wiki/concepts/x.md")}

    def test_accepts_valid_provenance(self):
        self.assertEqual(validate_provenance(VALID_PAGE), [])

    def test_page_without_provenance_yields_no_issues(self):
        self.assertEqual(validate_provenance("# Page\n\nA claim. ^claim-01\n"), [])

    def test_reports_duplicate_block_ids(self):
        content = VALID_PAGE + "\nDuplicate paragraph. ^claim-owner-01\n"
        self.assertIn("duplicate-block-id", self.issue_codes(content))

    def test_reports_source_without_id(self):
        content = VALID_PAGE.replace("  - id: s1\n    resource:", "  - resource:", 1)
        self.assertIn("missing-source-id", self.issue_codes(content))

    def test_reports_duplicate_source_ids(self):
        content = VALID_PAGE.replace("- id: s2", "- id: s1", 1)
        self.assertIn("duplicate-source-id", self.issue_codes(content))

    def test_reports_source_without_resource(self):
        content = VALID_PAGE.replace('    resource: "raw/notes/2024-04-04 Foo.md"\n', "", 1)
        self.assertIn("missing-source-resource", self.issue_codes(content))

    def test_reports_generated_without_by_or_at(self):
        content = VALID_PAGE.replace('  by: "agent:wiki-ingest"\n', "", 1)
        self.assertIn("missing-generated-by", self.issue_codes(content))
        content = VALID_PAGE.replace("  at: 2024-04-04\n", "", 1)
        self.assertIn("missing-generated-at", self.issue_codes(content))

    def test_reports_verified_entry_without_at(self):
        content = VALID_PAGE.replace("    at: 2026-06-25\n", "", 1)
        self.assertIn("missing-verified-at", self.issue_codes(content))

    def test_reports_malformed_dates(self):
        for broken in (
            VALID_PAGE.replace("at: 2024-04-04", "at: soon", 1),
            VALID_PAGE.replace("at: 2026-06-25", "at: 2026-6-25", 1),
            VALID_PAGE.replace("stale_after: 2027-01-01", "stale_after: someday", 1),
        ):
            self.assertIn("invalid-date", self.issue_codes(broken))

    def test_generated_at_may_be_later_than_verified_at(self):
        # There is deliberately no date-order rule between generated and verified.
        content = VALID_PAGE.replace("at: 2024-04-04", "at: 2026-12-31", 1)
        self.assertEqual(validate_provenance(content), [])

    def test_warns_when_generated_page_lists_no_sources(self):
        content = """---
generated:
  by: "agent:wiki-ingest"
  at: 2024-04-04
---

# Page
"""
        issues = validate_provenance(content, path="wiki/concepts/x.md")
        missing = [issue for issue in issues if issue.code == "missing-sources"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "warning")


FOOTNOTE_PAGE = VALID_PAGE.replace(
    "Current ownership sits with the map enrichment flow. ^claim-owner-01",
    "Current ownership sits with the map enrichment flow. [^s1] ^claim-owner-01",
) + "\n[^s1]: [[raw/notes/2024-04-04 Foo.md]]\n"


class FootnoteConsistencyTests(unittest.TestCase):
    def issues(self, content: str) -> dict[str, str]:
        return {
            issue.code: issue.severity
            for issue in validate_provenance(content, path="wiki/concepts/x.md")
        }

    def test_accepts_consistent_footnotes(self):
        self.assertEqual(self.issues(FOOTNOTE_PAGE), {})

    def test_reports_undefined_footnote_ref(self):
        content = FOOTNOTE_PAGE.replace(
            "\n[^s1]: [[raw/notes/2024-04-04 Foo.md]]\n", ""
        )
        self.assertEqual(self.issues(content).get("undefined-footnote-ref"), "error")

    def test_reports_footnote_with_unknown_source_id(self):
        content = FOOTNOTE_PAGE.replace("[^s1]", "[^s9]")
        self.assertEqual(self.issues(content).get("unknown-footnote-id"), "error")

    def test_warns_on_unreferenced_footnote_definition(self):
        content = FOOTNOTE_PAGE + "[^s2]: [[raw/notes/2026-06-02 Bar.md]]\n"
        self.assertEqual(
            self.issues(content).get("unreferenced-footnote-def"), "warning"
        )

    def test_reports_definition_resource_mismatch(self):
        content = FOOTNOTE_PAGE.replace(
            "[^s1]: [[raw/notes/2024-04-04 Foo.md]]",
            "[^s1]: [[raw/notes/2024-04-04 Wrong.md]]",
        )
        self.assertEqual(
            self.issues(content).get("footnote-resource-mismatch"), "error"
        )

    def test_ignores_footnote_examples_in_code(self):
        content = FOOTNOTE_PAGE + (
            "\n```markdown\nExample ref. [^s9]\n```\n\n"
            "Inline example: `[^s8]` stays out of scope.\n"
        )
        self.assertEqual(self.issues(content), {})

    def test_ignores_non_source_footnotes(self):
        content = FOOTNOTE_PAGE + (
            "\nProse footnote. [^note]\n\n[^note]: An ordinary aside.\n"
        )
        self.assertEqual(self.issues(content), {})


class ProvenanceLintCliTests(VaultFixtureMixin, unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-provenance-lint.py"),
                "--root",
                str(self.root),
                "--format",
                "json",
                *args,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_cli_reports_valid_wiki_page(self):
        self.write("wiki/concepts/Concept.md", VALID_PAGE)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["files_checked"], 1)
        self.assertEqual(payload["summary"]["issues"], 0)
        self.assertEqual(payload["issues"], [])

    def test_cli_accepts_page_without_provenance(self):
        self.write("wiki/concepts/Plain.md", "# Plain\n\nNo provenance here.\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["issues"], [])

    def test_cli_returns_nonzero_for_invalid_page(self):
        self.write(
            "wiki/concepts/Concept.md",
            VALID_PAGE.replace("at: 2024-04-04", "at: soon", 1),
        )
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["files_checked"], 1)
        self.assertEqual(payload["summary"]["issues"], 1)
        self.assertEqual(payload["issues"][0]["code"], "invalid-date")

    def test_cli_flags_legacy_callout_residue(self):
        self.write(
            "wiki/concepts/Legacy.md",
            "# Legacy\n\n> [!provenance]- Provenance\n> schema: kb-prov-v1\n",
        )
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["issues"][0]["code"], "legacy-provenance-callout")

    def test_cli_returns_zero_when_only_warnings(self):
        self.write(
            "wiki/concepts/Concept.md",
            """---
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-20
---

# Concept

Current claim. ^claim-01
""",
        )
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["issues"][0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
