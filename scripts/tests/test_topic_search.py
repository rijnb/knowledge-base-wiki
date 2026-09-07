"""Tests for lib.topic_search and the wiki-find.py shim."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.topic_search import (  # noqa: E402
    Hit,
    expand_terms,
    format_markdown,
    parse_index_line,
    search_pages,
    search_indexes,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "wiki-find.py"


CONCEPTS_INDEX = """# Concepts

[[wiki/index|← Index]] · 4 pages · rebuilt 2026-09-06

## Recently updated

- 2026-09-06 · [[wiki/concepts/Agentic Coding|Agentic Coding]]

## A

- [[wiki/concepts/Agentic Coding|Agentic Coding]] — Software development where an AI agent plans and edits code.
- [[wiki/concepts/AutoStream|[[AutoStream]]]] — [[AutoStream]] is TomTom's map streaming system.
- [[wiki/concepts/Claude Code|Claude Code]] — Anthropic's terminal coding agent.
- [[wiki/concepts/Zebra Crossing|Zebra Crossing]]
"""

SYSTEMS_INDEX = """# Systems

- [[wiki/systems/NavSDK|NavSDK]] — Navigation SDK; teams use coding agents to maintain it.
"""


class ParseIndexLineTests(unittest.TestCase):
    def test_standard_line(self):
        hit = parse_index_line(
            "- [[wiki/concepts/Agentic Coding|Agentic Coding]] — Software development where an AI agent edits code."
        )
        self.assertEqual(hit.path, "wiki/concepts/Agentic Coding")
        self.assertEqual(hit.title, "Agentic Coding")
        self.assertEqual(hit.topic_type, "concepts")
        self.assertTrue(hit.description.startswith("Software development"))

    def test_nested_wikilink_title(self):
        hit = parse_index_line(
            "- [[wiki/concepts/AutoStream|[[AutoStream]]]] — [[AutoStream]] is TomTom's map streaming system."
        )
        self.assertEqual(hit.path, "wiki/concepts/AutoStream")
        self.assertEqual(hit.title, "[[AutoStream]]")
        self.assertIn("streaming", hit.description)

    def test_line_without_description(self):
        hit = parse_index_line("- [[wiki/concepts/Zebra Crossing|Zebra Crossing]]")
        self.assertEqual(hit.path, "wiki/concepts/Zebra Crossing")
        self.assertEqual(hit.description, "")

    def test_non_entry_lines_return_none(self):
        self.assertIsNone(parse_index_line("## A"))
        self.assertIsNone(parse_index_line("- 2026-09-06 · [[wiki/concepts/Agentic Coding|Agentic Coding]]"))
        self.assertIsNone(parse_index_line(""))


class ExpandTermsTests(unittest.TestCase):
    def test_splits_commas_and_strips(self):
        self.assertEqual(expand_terms(["agentic coding, claude code ", "cursor"]),
                         ["agentic coding", "claude code", "cursor"])

    def test_dedupes_case_insensitively(self):
        self.assertEqual(expand_terms(["Agentic", "agentic"]), ["Agentic"])


class SearchIndexesTests(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("wiki/concepts/index.md", CONCEPTS_INDEX)
        self.write("wiki/systems/index.md", SYSTEMS_INDEX)
        self.write("wiki/index.md", "# Wiki Index\n")

    def test_title_match_scores_higher_than_description_match(self):
        hits = search_indexes(self.root, ["agentic"])
        paths = [h.path for h in hits]
        self.assertEqual(paths, ["wiki/concepts/Agentic Coding"])
        self.assertEqual(hits[0].matched_in, "title")

    def test_description_match_and_multiple_terms(self):
        hits = search_indexes(self.root, ["coding agent", "claude code"])
        by_path = {h.path: h for h in hits}
        self.assertIn("wiki/concepts/Claude Code", by_path)
        self.assertIn("wiki/systems/NavSDK", by_path)
        # Claude Code matches both title (claude code) and description (coding agent)
        self.assertEqual(by_path["wiki/concepts/Claude Code"].matched_in, "title")
        self.assertEqual(sorted(by_path["wiki/concepts/Claude Code"].terms), ["claude code", "coding agent"])
        self.assertEqual(by_path["wiki/systems/NavSDK"].matched_in, "description")

    def test_case_insensitive_and_dedupes_recently_updated(self):
        hits = search_indexes(self.root, ["AGENTIC CODING"])
        self.assertEqual(len(hits), 1)

    def test_type_filter(self):
        hits = search_indexes(self.root, ["coding"], types=["systems"])
        self.assertEqual([h.path for h in hits], ["wiki/systems/NavSDK"])

    def test_ranking_more_terms_first(self):
        hits = search_indexes(self.root, ["claude code", "coding agent", "streaming"])
        self.assertEqual(hits[0].path, "wiki/concepts/Claude Code")


class SearchPagesTests(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("wiki/concepts/index.md", CONCEPTS_INDEX)
        self.write("wiki/concepts/Zebra Crossing.md",
                   "---\ntags: [pedestrians, safety]\ndescription: Pedestrian crossing.\n---\n# Zebra Crossing\n\nUnrelated to vibe coding tools.\n")
        self.write("wiki/concepts/Agentic Coding.md", "# Agentic Coding\n\nBody mentions vibe coding.\n")
        self.write("wiki/concepts/Claude Code.md",
                   "---\ntags: [ai, agentic-coding, tools]\n---\n# Claude Code\n\nNothing relevant here.\n")
        self.write("wiki/systems/Harness.md",
                   "---\ntags:\n  - agentic-coding\n  - harness\n---\n# Harness\n\nBlock-list tags.\n")

    def test_tag_match_normalises_spaces_to_hyphens(self):
        hits = search_pages(self.root, ["Agentic Coding"], body=False)
        self.assertEqual(sorted(h.path for h in hits), ["wiki/concepts/Claude Code", "wiki/systems/Harness"])
        self.assertTrue(all(h.matched_in == "tags" for h in hits))
        self.assertEqual(hits[0].terms, ["Agentic Coding"])

    def test_body_search_skips_already_found_and_index_files(self):
        hits = search_pages(self.root, ["vibe coding"], body=True, exclude={"wiki/concepts/Agentic Coding"})
        self.assertEqual([h.path for h in hits], ["wiki/concepts/Zebra Crossing"])
        self.assertEqual(hits[0].matched_in, "body")
        self.assertEqual(hits[0].description, "Pedestrian crossing.")

    def test_body_disabled_ignores_body_text(self):
        hits = search_pages(self.root, ["vibe coding"], body=False)
        self.assertEqual(hits, [])

    def test_tags_rank_above_body(self):
        hits = search_pages(self.root, ["agentic-coding", "vibe coding"], body=True)
        self.assertEqual(hits[0].matched_in, "tags")
        self.assertEqual(hits[-1].matched_in, "body")

    def test_type_filter(self):
        hits = search_pages(self.root, ["agentic coding"], body=True, types=["systems"])
        self.assertEqual([h.path for h in hits], ["wiki/systems/Harness"])


class FormatMarkdownTests(unittest.TestCase):
    def test_groups_by_type_and_tags_body_hits(self):
        hits = [
            Hit("wiki/concepts/Agentic Coding", "Agentic Coding", "concepts", "Desc A.", "title", ["agentic"]),
            Hit("wiki/systems/NavSDK", "NavSDK", "systems", "Desc N.", "body", ["coding agent"]),
            Hit("wiki/systems/Harness", "Harness", "systems", "", "tags", ["agentic coding"]),
        ]
        out = format_markdown(hits)
        self.assertIn("## Concepts (1)", out)
        self.assertIn("- [[wiki/concepts/Agentic Coding|Agentic Coding]] — Desc A.", out)
        self.assertIn("(body: coding agent)", out)
        self.assertIn("- [[wiki/systems/Harness|Harness]] (tags: agentic coding)", out)
        self.assertIn("## Systems (2)", out)
        self.assertLess(out.index("## Concepts"), out.index("## Systems"))


class ScriptTests(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("wiki/concepts/index.md", CONCEPTS_INDEX)
        self.write("wiki/systems/index.md", SYSTEMS_INDEX)
        self.write("wiki/concepts/Claude Code.md", "# Claude Code\n\nNothing relevant here.\n")
        self.write("wiki/concepts/Zebra Crossing.md", "# Zebra Crossing\n\nMentions cursor here.\n")

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_json_output(self):
        proc = self.run_script("--format", "json", "agentic coding", "claude code")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["terms"], ["agentic coding", "claude code"])
        paths = [h["path"] for h in data["hits"]]
        self.assertIn("wiki/concepts/Agentic Coding", paths)
        self.assertIn("wiki/concepts/Claude Code", paths)
        self.assertEqual(data["summary"]["index_hits"], 2)
        self.assertEqual(data["summary"]["page_hits"], 0)
        self.assertEqual(data["summary"]["total"], 2)

    def test_body_flag_adds_body_hits(self):
        proc = self.run_script("--format", "json", "--body", "cursor")
        data = json.loads(proc.stdout)
        self.assertEqual([h["path"] for h in data["hits"]], ["wiki/concepts/Zebra Crossing"])
        self.assertEqual(data["summary"]["page_hits"], 1)

    def test_out_writes_file_and_prints_summary_only(self):
        out = self.root / "list.md"
        proc = self.run_script("--out", str(out), "agentic coding", "claude code")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("## Concepts (2)", out.read_text(encoding="utf-8"))
        self.assertNotIn("## Concepts", proc.stdout)
        self.assertIn("2 pages", proc.stdout)
        self.assertIn(str(out), proc.stdout)

    def test_markdown_default_and_no_terms_is_error(self):
        proc = self.run_script("agentic")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("## Concepts (1)", proc.stdout)
        proc = self.run_script()
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
