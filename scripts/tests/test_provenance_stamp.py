"""Tests for minimal provenance status stamping."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.provenance import parse_provenance_callout, validate_provenance  # noqa: E402
from lib.provenance_stamp import StampSpec, load_stamp_specs, stamp_content  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class ProvenanceStampTests(unittest.TestCase):
    def test_stamps_status_section_and_minimal_callout(self):
        content, block_id = stamp_content(
            "# Legacy\n\nOld claim.\n",
            StampSpec(
                page="wiki/concepts/Legacy.md",
                mode="historical",
                reason="Historical bounded source.",
                sources=("raw/notes/source.md",),
                latest_related_raw_date="2015-07-01",
            ),
        )

        self.assertEqual(block_id, "freshness-status")
        self.assertIn("## Freshness Status", content)
        self.assertIn("^freshness-status", content)
        parsed = parse_provenance_callout(content)
        self.assertEqual(parsed["migration_status"], "legacy-inferred-minimal")
        self.assertEqual(parsed["blocks"]["freshness-status"]["status"], "current")
        self.assertEqual(parsed["blocks"]["freshness-status"]["sources"], ["raw/notes/source.md"])
        self.assertEqual(parsed["blocks"]["freshness-status"]["review_mode"], "historical")
        self.assertEqual(validate_provenance(content), [])

    def test_stamps_currentness_review_mode(self):
        content, _ = stamp_content(
            "# Current Topic\n\nClaim.\n",
            StampSpec(
                page="wiki/systems/Current Topic.md",
                mode="needs-currentness-answer",
                reason="Current system state needs owner confirmation.",
                sources=("raw/notes/current.md",),
            ),
        )

        parsed = parse_provenance_callout(content)
        block = parsed["blocks"]["freshness-status"]
        self.assertEqual(block["review_mode"], "needs-currentness-answer")
        self.assertIn("authoritative currentness answer", content)
        self.assertEqual(validate_provenance(content), [])

    def test_refuses_page_that_already_has_provenance(self):
        content = """# Covered

Claim. ^claim

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim:
>     checked: 2026-06-24
>     status: current
"""
        with self.assertRaises(ValueError):
            stamp_content(content, StampSpec(page="wiki/concepts/Covered.md"))


class ProvenanceStampCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_loads_list_manifest(self):
        self.write(
            ".wiki-scratch/list-manifest.json",
            json.dumps([
                {
                    "page": "wiki/concepts/Legacy.md",
                    "mode": "source-specific",
                    "related_raw": ["raw/notes/source.md"],
                },
            ]),
        )

        specs = load_stamp_specs(self.root / ".wiki-scratch/list-manifest.json")

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].page, "wiki/concepts/Legacy.md")
        self.assertEqual(specs[0].mode, "source-specific")
        self.assertEqual(specs[0].sources, ("raw/notes/source.md",))

    def test_cli_stamps_manifest_pages(self):
        self.write("wiki/concepts/Legacy.md", "# Legacy\n\nOld claim.\n")
        self.write(
            ".wiki-scratch/auto-ok.json",
            json.dumps({
                "auto_ok": [
                    {
                        "page": "wiki/concepts/Legacy.md",
                        "stamp_mode": "historical",
                        "reason": "Historical bounded source.",
                        "sources": ["raw/notes/source.md"],
                    },
                ],
            }),
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-provenance-stamp-status.py"),
                "--root",
                str(self.root),
                ".wiki-scratch/auto-ok.json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stamped: 1", result.stdout)
        self.assertIn("legacy-inferred-minimal", self.read("wiki/concepts/Legacy.md"))

    def test_cli_rejects_manifest_page_outside_wiki_root(self):
        outside = self.root.parent / f"{self.root.name}-outside.md"
        outside.write_text("# Outside\n\nShould not be touched.\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        self.write(
            ".wiki-scratch/auto-ok.json",
            json.dumps({
                "auto_ok": [
                    {
                        "page": f"../{outside.name}",
                        "stamp_mode": "historical",
                    },
                ],
            }),
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-provenance-stamp-status.py"),
                "--root",
                str(self.root),
                ".wiki-scratch/auto-ok.json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("invalid-path", result.stdout)
        self.assertNotIn("legacy-inferred-minimal", outside.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
