"""Tests for kb-prov-v1 block provenance parsing and validation."""

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
    parse_provenance_callout,
    validate_provenance,
)


ROOT = Path(__file__).resolve().parents[2]


VALID_PAGE = """# Concept

Current ownership sits with the map enrichment flow. ^claim-owner-01

Older ownership sat with the prototype team. ^claim-owner-old

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
>     provenance_quality: inferred
>   claim-owner-old:
>     sources: [raw:meeting-2025-12-12#b03]
>     observed: 2025-12-12
>     checked: 2026-06-20
>     status: superseded
>     confidence: high
>     superseded_by: claim-owner-01
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


class ProvenanceCalloutParsingTests(unittest.TestCase):
    def test_parses_page_level_callout(self):
        parsed = parse_provenance_callout(VALID_PAGE)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["schema"], "kb-prov-v1")
        self.assertEqual(parsed["migration_status"], "legacy-inferred")
        self.assertEqual(
            parsed["blocks"]["claim-owner-01"]["sources"],
            ["raw:meeting-2026-06-02#b08"],
        )
        self.assertEqual(parsed["blocks"]["claim-owner-01"]["checked"], "2026-06-20")
        self.assertIsNone(parse_provenance_callout("# No provenance\n\nBody\n"))

    def test_parses_quoted_source_paths_containing_commas(self):
        content = """# Concept

Claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: ["raw/notes/2015 Speed Cam, NDS and Perseus Discussion.md", raw/notes/Other.md]
>     status: current
"""
        parsed = parse_provenance_callout(content)

        self.assertEqual(
            parsed["blocks"]["claim-01"]["sources"],
            [
                "raw/notes/2015 Speed Cam, NDS and Perseus Discussion.md",
                "raw/notes/Other.md",
            ],
        )

    def test_parses_all_quoted_source_paths(self):
        content = """# Concept

Claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: ["raw/notes/First.md", "raw/notes/Second.md"]
>     status: current
"""
        parsed = parse_provenance_callout(content)

        self.assertEqual(
            parsed["blocks"]["claim-01"]["sources"],
            ["raw/notes/First.md", "raw/notes/Second.md"],
        )

    def test_parses_unquoted_source_paths_containing_commas(self):
        content = """# Concept

Claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: [raw/notes/2015 Speed Cam, NDS and Perseus Discussion.md, raw/notes/Other.md]
>     status: current
"""
        parsed = parse_provenance_callout(content)

        self.assertEqual(
            parsed["blocks"]["claim-01"]["sources"],
            [
                "raw/notes/2015 Speed Cam, NDS and Perseus Discussion.md",
                "raw/notes/Other.md",
            ],
        )

    def test_splits_unprefixed_source_identifiers(self):
        # Sources without a recognized path/scheme prefix must still split on
        # the list comma instead of being merged into one mangled element.
        content = """# Concept

Claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: [alpha-note, beta-note]
>     status: current
"""
        parsed = parse_provenance_callout(content)

        self.assertEqual(
            parsed["blocks"]["claim-01"]["sources"],
            ["alpha-note", "beta-note"],
        )

    def test_splits_scheme_prefixed_source_identifiers(self):
        content = """# Concept

Claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     sources: [slack:C0123, confluence:42]
>     status: current
"""
        parsed = parse_provenance_callout(content)

        self.assertEqual(
            parsed["blocks"]["claim-01"]["sources"],
            ["slack:C0123", "confluence:42"],
        )


class ProvenanceValidationTests(unittest.TestCase):
    def issue_codes(self, content: str) -> set[str]:
        return {issue.code for issue in validate_provenance(content, path="wiki/concepts/x.md")}

    def test_accepts_valid_provenance(self):
        self.assertEqual(validate_provenance(VALID_PAGE), [])

    def test_reports_provenance_block_missing_from_page(self):
        content = VALID_PAGE.replace(" ^claim-owner-01", "")
        self.assertIn("missing-block-id", self.issue_codes(content))

    def test_reports_duplicate_block_ids(self):
        content = VALID_PAGE + "\nDuplicate paragraph. ^claim-owner-01\n"
        self.assertIn("duplicate-block-id", self.issue_codes(content))

    def test_reports_invalid_status_and_confidence(self):
        content = VALID_PAGE.replace("status: current", "status: fresh", 1)
        content = content.replace("confidence: medium", "confidence: certain", 1)
        codes = self.issue_codes(content)
        self.assertIn("invalid-status", codes)
        self.assertIn("invalid-confidence", codes)

    def test_superseded_block_requires_target(self):
        content = VALID_PAGE.replace(">     superseded_by: claim-owner-01\n", "")
        self.assertIn("missing-superseded-by", self.issue_codes(content))

    def test_observed_must_not_be_after_checked(self):
        content = VALID_PAGE.replace("observed: 2026-06-02", "observed: 2026-07-02", 1)
        self.assertIn("date-order", self.issue_codes(content))

    def test_reports_malformed_date(self):
        content = VALID_PAGE.replace("checked: 2026-06-20", "checked: soon", 1)
        self.assertIn("invalid-date", self.issue_codes(content))

    def test_warns_when_claim_block_has_no_sources(self):
        content = """# Concept

Current claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     checked: 2026-06-20
>     status: current
>     confidence: medium
"""
        issues = validate_provenance(content, path="wiki/concepts/x.md")
        missing = [issue for issue in issues if issue.code == "missing-sources"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "warning")

    def test_minimal_stamp_is_exempt_from_missing_sources_warning(self):
        content = """# Concept

Freshness only. ^freshness-status

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred-minimal
> blocks:
>   freshness-status:
>     checked: 2026-06-20
>     status: current
>     confidence: medium
"""
        codes = self.issue_codes(content)
        self.assertNotIn("missing-sources", codes)


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

    def test_cli_returns_nonzero_for_invalid_page(self):
        self.write(
            "wiki/concepts/Concept.md",
            VALID_PAGE.replace(" ^claim-owner-01", ""),
        )
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["files_checked"], 1)
        self.assertEqual(payload["summary"]["issues"], 1)
        self.assertEqual(payload["issues"][0]["code"], "missing-block-id")

    def test_cli_returns_zero_when_only_warnings(self):
        self.write(
            "wiki/concepts/Concept.md",
            """# Concept

Current claim. ^claim-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-01:
>     checked: 2026-06-20
>     status: current
>     confidence: medium
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
