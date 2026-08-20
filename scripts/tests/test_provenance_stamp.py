"""Tests for minimal frontmatter provenance stamping."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.provenance import parse_provenance, validate_provenance  # noqa: E402
from lib.provenance_stamp import StampSpec, load_stamp_specs, stamp_content  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


class ProvenanceStampTests(unittest.TestCase):
    def test_stamps_frontmatter_provenance_on_page_without_frontmatter(self):
        content = stamp_content(
            "# Legacy\n\nOld claim.\n",
            StampSpec(
                page="wiki/concepts/Legacy.md",
                mode="historical",
                reason="Historical bounded source.",
                sources=("raw/notes/source.md",),
                latest_related_raw_date="2015-07-01",
            ),
            checked="2026-06-24",
        )

        self.assertTrue(content.startswith("---\n"))
        self.assertIn("# Legacy", content)
        parsed = parse_provenance(content)
        self.assertEqual(
            parsed["sources"],
            [{"id": "s1", "resource": "raw/notes/source.md"}],
        )
        self.assertEqual(
            parsed["generated"],
            {"by": "agent:wiki-ingest", "at": "2026-06-24"},
        )
        self.assertEqual(parsed["verified"], [])
        self.assertEqual(validate_provenance(content), [])

    def test_stamps_into_existing_frontmatter(self):
        content = stamp_content(
            "---\ntype: concept\nstate: active\n---\n\n# Topic\n\nClaim.\n",
            StampSpec(
                page="wiki/systems/Topic.md",
                mode="needs-currentness-answer",
                sources=("raw/notes/a.md", "raw/notes/b.md"),
            ),
            checked="2026-06-24",
        )

        self.assertIn("type: concept", content)
        parsed = parse_provenance(content)
        self.assertEqual(
            [entry["id"] for entry in parsed["sources"]],
            ["s1", "s2"],
        )
        self.assertEqual(parsed["generated"]["at"], "2026-06-24")
        self.assertEqual(validate_provenance(content), [])

    def test_optionally_records_a_verified_entry(self):
        content = stamp_content(
            "# Topic\n\nClaim.\n",
            StampSpec(page="wiki/concepts/Topic.md", sources=("raw/notes/a.md",)),
            checked="2026-06-24",
            verified=True,
        )

        parsed = parse_provenance(content)
        self.assertEqual(
            parsed["verified"],
            [{"by": "agent:wiki-freshness", "at": "2026-06-24"}],
        )
        self.assertEqual(validate_provenance(content), [])

    def test_refuses_page_that_already_has_provenance(self):
        for existing in (
            "---\ngenerated:\n  by: \"agent:wiki-ingest\"\n  at: 2026-06-24\n---\n\n# Covered\n",
            "---\nsources:\n  - id: s1\n    resource: \"raw/notes/a.md\"\n---\n\n# Covered\n",
        ):
            with self.assertRaises(ValueError):
                stamp_content(existing, StampSpec(page="wiki/concepts/Covered.md"))


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
                "--checked",
                "2026-06-24",
                ".wiki-scratch/auto-ok.json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stamped: 1", result.stdout)
        stamped = self.read("wiki/concepts/Legacy.md")
        parsed = parse_provenance(stamped)
        self.assertEqual(parsed["generated"], {"by": "agent:wiki-ingest", "at": "2026-06-24"})
        self.assertEqual(parsed["sources"][0]["resource"], "raw/notes/source.md")

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
        self.assertNotIn("generated:", outside.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
