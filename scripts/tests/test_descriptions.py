"""Tests for lib.descriptions and the description backfill script."""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.descriptions import (  # noqa: E402
    SUMMARY_MAX_CHARS,
    extract_description,
    yaml_double_quote,
    yaml_unquote,
)

ROOT = Path(__file__).resolve().parents[2]
BACKFILL = ROOT / "scripts" / "system" / "wiki-backfill-descriptions.py"
INDEXER = ROOT / "scripts" / "system" / "wiki-create-index-pages.py"


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class ExtractDescriptionTests(unittest.TestCase):
    def test_plain_paragraph_first_sentence(self):
        content = "# Title\n\nFirst sentence here. Second sentence ignored.\n"
        self.assertEqual(extract_description(content), "First sentence here.")

    def test_frontmatter_skipped(self):
        content = "---\ntype: concept\ndate: 2026-01-01\n---\n\n# T\n\nBody text.\n"
        self.assertEqual(extract_description(content), "Body text.")

    def test_wikilinks_kept_intact(self):
        content = "# T\n\nWorks with [[Real-Time Map]] and [[Orbis Maps]].\n"
        self.assertEqual(
            extract_description(content),
            "Works with [[Real-Time Map]] and [[Orbis Maps]].",
        )

    def test_bold_intro_unwrapped(self):
        content = "# T\n\n**Real-Time Map** is TomTom's live map platform.\n"
        result = extract_description(content)
        self.assertEqual(result, "Real-Time Map is TomTom's live map platform.")
        self.assertFalse(result.startswith(("*", "_")))

    def test_fully_emphasised_line_unwrapped(self):
        content = "# T\n\n*Source: [[raw/notes/x.md]]*\n"
        self.assertEqual(extract_description(content), "Source: [[raw/notes/x.md]]")

    def test_html_comment_stripped(self):
        content = "<!-- machine\nheader -->\n# T\n\n<!-- hint -->Actual text here.\n"
        self.assertEqual(extract_description(content), "Actual text here.")

    def test_long_summary_capped(self):
        sentence = ("word " * 60).strip() + " end."  # one long sentence, no early period
        content = f"# T\n\n{sentence}\n"
        result = extract_description(content)
        self.assertLessEqual(len(result), SUMMARY_MAX_CHARS + 2)
        self.assertTrue(result.endswith("…"))

    def test_cap_never_breaks_wikilink(self):
        head = "x" * 150
        content = f"# T\n\n{head} [[Some Long Page Name That Overflows]] tail\n"
        result = extract_description(content)
        self.assertEqual(result.count("[["), result.count("]]"))

    def test_block_anchor_stripped(self):
        content = "# T\n\nShort line without period ^block-id\n"
        self.assertEqual(extract_description(content), "Short line without period")

    def test_no_body_returns_none(self):
        self.assertIsNone(extract_description("---\ntype: concept\n---\n\n# Only Title\n"))
        self.assertIsNone(extract_description(""))


class YamlQuoteTests(unittest.TestCase):
    def test_round_trip_quotes_and_backslashes(self):
        text = 'He said "hi \\ bye" loudly.'
        self.assertEqual(yaml_unquote(yaml_double_quote(text)), text)

    def test_quoting_escapes(self):
        self.assertEqual(yaml_double_quote('a "b" c\\d'), '"a \\"b\\" c\\\\d"')


class BackfillScriptTests(VaultFixtureMixin, unittest.TestCase):
    def run_backfill(self, *extra: str) -> subprocess.CompletedProcess:
        result = run_script(BACKFILL, "--wiki-dir", str(self.root / "wiki"), *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_inserts_description_after_type_and_tags(self):
        self.write(
            "wiki/concepts/A.md",
            "---\ntype: concept\ntags: [a, b]\nstate: active\ndate: 2026-01-01\n---\n\n"
            "# A\n\nA short summary. More text.\n",
        )
        result = self.run_backfill()
        self.assertIn("1 inserted", result.stdout)
        content = self.read("wiki/concepts/A.md")
        lines = content.splitlines()
        self.assertEqual(lines[3], 'description: "A short summary."')
        self.assertEqual(lines[4], "state: active")  # other keys preserved below

    def test_block_list_tags_handled(self):
        self.write(
            "wiki/projects/B.md",
            "---\ntype: project\ntags:\n  - one\n  - two\nstate: active\n---\n\n"
            "# B\n\nProject summary.\n",
        )
        self.run_backfill()
        lines = self.read("wiki/projects/B.md").splitlines()
        self.assertEqual(lines[5], 'description: "Project summary."')
        self.assertEqual(lines[6], "state: active")

    def test_idempotent_second_run(self):
        self.write(
            "wiki/concepts/A.md",
            "---\ntype: concept\n---\n\n# A\n\nSummary.\n",
        )
        self.run_backfill()
        before = self.read("wiki/concepts/A.md")
        result = self.run_backfill()
        self.assertIn("0 inserted", result.stdout)
        self.assertIn("1 already had description", result.stdout)
        self.assertEqual(self.read("wiki/concepts/A.md"), before)

    def test_quotes_and_backslashes_escaped(self):
        self.write(
            "wiki/concepts/Q.md",
            '---\ntype: concept\n---\n\n# Q\n\nHe said "hi \\ bye" loudly.\n',
        )
        self.run_backfill()
        self.assertIn(
            'description: "He said \\"hi \\\\ bye\\" loudly."',
            self.read("wiki/concepts/Q.md"),
        )

    def test_index_md_skipped(self):
        index_content = "# Concepts\n\nA topic index without frontmatter.\n"
        self.write("wiki/concepts/index.md", index_content)
        self.write("wiki/concepts/A.md", "---\ntype: concept\n---\n\n# A\n\nText.\n")
        result = self.run_backfill()
        self.assertIn("Scanned 1 pages", result.stdout)
        self.assertEqual(self.read("wiki/concepts/index.md"), index_content)

    def test_dry_run_writes_nothing(self):
        page = "---\ntype: concept\n---\n\n# A\n\nText.\n"
        self.write("wiki/concepts/A.md", page)
        result = self.run_backfill("--dry-run")
        self.assertIn("1 would insert", result.stdout)
        self.assertEqual(self.read("wiki/concepts/A.md"), page)


class IndexBuilderDescriptionTests(VaultFixtureMixin, unittest.TestCase):
    def test_frontmatter_description_preferred_over_body(self):
        (self.root / "wiki").mkdir(parents=True, exist_ok=True)
        for topic in (
            "competition", "concepts", "conversations", "decisions",
            "people", "problems", "projects", "systems",
        ):
            (self.root / "wiki" / topic).mkdir(exist_ok=True)
        self.write(
            "wiki/concepts/A.md",
            '---\ntype: concept\ndescription: "Curated one-liner."\n---\n\n'
            "# A\n\nBody first sentence.\n",
        )
        self.write(
            "wiki/concepts/B.md",
            "---\ntype: concept\n---\n\n# B\n\nDerived from body.\n",
        )
        result = run_script(INDEXER, "--wiki-dir", str(self.root / "wiki"))
        self.assertEqual(result.returncode, 0, result.stderr)
        index = self.read("wiki/concepts/index.md")
        self.assertIn("— Curated one-liner.", index)
        self.assertNotIn("Body first sentence", index)
        self.assertIn("— Derived from body.", index)


if __name__ == "__main__":
    unittest.main()
