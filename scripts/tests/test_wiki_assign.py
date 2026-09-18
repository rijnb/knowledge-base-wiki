"""Tests for lib.wiki_assign (phase 5 — closed-vocabulary tag assignment)."""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.wiki_assign import (  # noqa: E402
    BUNDLE_SIZE,
    assign_prompt,
    bundles,
    is_target,
    load_vocabulary,
    parse_assignments,
)

VOCAB = ["ai/agents", "map/hd-map", "process/testing", "security/general"]


def rec(path: str, title: str = "T", tags=(), excerpt: str = "body words") -> dict:
    return {"path": path, "title": title, "tags": list(tags),
            "excerpt": excerpt, "words": len(excerpt.split()), "title_only": False}


class VocabularyTest(VaultFixtureMixin, unittest.TestCase):
    def test_harvests_backticked_list_items(self):
        path = self.write("config/tags.md",
                          "# Tags\n\nSome prose.\n\n## ai\n\n"
                          "- `ai/agents`  <!-- 134 notes -->\n"
                          "- `ai/general` *\n\n## map\n\n- `map/hd-map`\n")
        self.assertEqual(load_vocabulary(path),
                         ["ai/agents", "ai/general", "map/hd-map"])

    def test_withholds_every_year_tag_including_ranges(self):
        # Years are computed from each note's own date; a guess would be wrong.
        # The whole namespace is withheld: a strict four-digit rule let
        # `year/2015-2016` stay assignable.
        path = self.write("config/tags.md",
                          "## year\n\n- `year/2022`\n- `year/2015-2016`\n"
                          "\n## ai\n\n- `ai/agents`\n")
        self.assertEqual(load_vocabulary(path), ["ai/agents"])

    def test_a_tag_filed_under_the_wrong_heading_is_skipped(self):
        path = self.write("config/tags.md",
                          "## ai\n\n- `ai/agents`\n- `map/hd-map`\n")
        self.assertEqual(load_vocabulary(path), ["ai/agents"])

    def test_prose_bullets_are_not_harvested_as_tags(self):
        # The generated Rules section contains "- `year/YYYY` is the one exempt
        # pattern." — a bullet whose first backticked span looks like a tag.
        path = self.write("config/tags.md",
                          "## Rules\n\n"
                          "- `year/YYYY` is the one exempt pattern.\n"
                          "- `namespace/term` or `namespace/term/term`. Never 1 segment.\n"
                          "\n## ai\n\n- `ai/agents`\n")
        self.assertEqual(load_vocabulary(path), ["ai/agents"])

    def test_missing_file_is_empty(self):
        self.assertEqual(load_vocabulary(self.root / "nope.md"), [])


class TargetTest(unittest.TestCase):
    def test_untagged_and_thinly_tagged_notes_are_targets(self):
        self.assertTrue(is_target(rec("a.md")))
        self.assertTrue(is_target(rec("b.md", tags=["ai/agents", "map/hd-map"])))

    def test_well_tagged_note_is_not(self):
        self.assertFalse(is_target(
            rec("c.md", tags=["ai/agents", "map/hd-map", "process/testing"])))


class PromptTest(unittest.TestCase):
    def test_carries_vocabulary_numbering_and_the_reply_contract(self):
        prompt = assign_prompt([rec("a.md", "First"), rec("b.md", "Second")], VOCAB)
        self.assertIn("ai/agents", prompt)
        self.assertIn("[1] title: First", prompt)
        self.assertIn("[2] title: Second", prompt)
        self.assertIn("exactly 2 lines", prompt)
        self.assertIn("closed vocabulary", prompt)

    def test_states_the_general_and_year_rules(self):
        # Both are enforced in code too; the prompt stops them being produced.
        prompt = assign_prompt([rec("a.md")], VOCAB)
        self.assertIn("security/general", prompt)
        self.assertIn("Never repeat a namespace as its own term", prompt)
        self.assertIn("Never assign a `year/...` tag", prompt)

    def test_thin_note_is_flagged_for_title_only_tagging(self):
        prompt = assign_prompt([rec("a.md", "Only A Title", excerpt="")], VOCAB)
        self.assertIn("tag from the title alone", prompt)


class ParseTest(unittest.TestCase):
    RECORDS = [rec("a.md"), rec("b.md")]

    def test_parses_numbered_lines(self):
        reply = "1\tai/agents map/hd-map\n2\tprocess/testing\n"
        assigns, rejected = parse_assignments(reply, self.RECORDS, VOCAB)
        self.assertEqual(assigns, {"a.md": ["ai/agents", "map/hd-map"],
                                   "b.md": ["process/testing"]})
        self.assertEqual(rejected, {})

    def test_tolerates_brackets_dots_commas_and_hashes(self):
        reply = "[1] #ai/agents, map/hd-map\n2. process/testing\n"
        assigns, _ = parse_assignments(reply, self.RECORDS, VOCAB)
        self.assertEqual(assigns["a.md"], ["ai/agents", "map/hd-map"])
        self.assertEqual(assigns["b.md"], ["process/testing"])

    def test_off_list_tags_are_reported_never_written(self):
        reply = "1\tai/agents security/security invented/thing\n"
        assigns, rejected = parse_assignments(reply, self.RECORDS, VOCAB)
        self.assertEqual(assigns, {"a.md": ["ai/agents"]})
        self.assertEqual(dict(rejected), {"security/security": 1, "invented/thing": 1})

    def test_year_tags_are_rejected_even_if_listed(self):
        assigns, rejected = parse_assignments(
            "1\tyear/2022 ai/agents\n", self.RECORDS, VOCAB + ["year/2022"])
        self.assertEqual(assigns, {"a.md": ["ai/agents"]})
        self.assertEqual(dict(rejected), {"year/2022": 1})

    def test_dedupes_and_ignores_out_of_range_numbers(self):
        reply = "1\tai/agents ai/agents\n9\tprocess/testing\n"
        assigns, _ = parse_assignments(reply, self.RECORDS, VOCAB)
        self.assertEqual(assigns, {"a.md": ["ai/agents"]})

    def test_junk_reply_yields_nothing_rather_than_raising(self):
        for reply in (None, "", "I cannot help with that."):
            assigns, _ = parse_assignments(reply, self.RECORDS, VOCAB)
            self.assertEqual(assigns, {})

    def test_bundles_split_by_size(self):
        records = [rec(f"{i}.md") for i in range(7)]
        self.assertEqual([len(b) for b in bundles(records, size=3)], [3, 3, 1])
        # Validated by A/B: 50 holds vocabulary adherence, 100 drifts badly
        # (off-list tags 2.6% -> 13%).
        self.assertEqual(BUNDLE_SIZE, 50)


if __name__ == "__main__":
    unittest.main()


class WritePhaseTest(VaultFixtureMixin, unittest.TestCase):
    """The write phase merges assigned tags additively and backs up first."""

    SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wiki-tags.py"

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), "--root", str(self.root), *args],
            capture_output=True, text=True,
        )

    def setUp(self):
        super().setUp()
        self.write("config/tags.md",
                   "## ai\n\n- `ai/agents`\n- `ai/general`\n\n## map\n\n- `map/hd-map`\n")
        self.write("raw/notes/A.md", "---\ntags: [map/hd-map]\n---\nbody\n")
        self.write("raw/notes/B.md", "---\ntype: note\n---\nbody\n")
        self.write(".tags/assigned.jsonl",
                   '{"path": "raw/notes/A.md", "tags": ["ai/agents"]}\n'
                   '{"path": "raw/notes/B.md", "tags": ["ai/general", "not/approved"]}\n')

    def test_dry_run_writes_nothing(self):
        before = self.read("raw/notes/A.md")
        result = self._run("--phase", "write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would write", result.stdout)
        self.assertEqual(self.read("raw/notes/A.md"), before)

    def test_apply_merges_additively_and_drops_off_list_tags(self):
        result = self._run("--phase", "write", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        # An existing tag is kept; the write phase never removes.
        self.assertIn("tags: [ai/agents, map/hd-map]", self.read("raw/notes/A.md"))
        # An off-list tag is discarded even if it reached the checkpoint.
        self.assertIn("tags: [ai/general]", self.read("raw/notes/B.md"))
        self.assertNotIn("not/approved", self.read("raw/notes/B.md"))
        self.assertIn("type: note", self.read("raw/notes/B.md"))

    def test_a_second_apply_appends_rather_than_refusing(self):
        # Tagging new notes is recurring, so the second run must just work.
        self.assertEqual(self._run("--phase", "write", "--apply").returncode, 0)
        self.write("raw/notes/C.md", "---\ntype: note\n---\nbody\n")
        with (self.root / ".tags" / "assigned.jsonl").open("a") as fh:
            fh.write('{"path": "raw/notes/C.md", "tags": ["ai/agents"]}\n')
        second = self._run("--phase", "write", "--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("ai/agents", self.read("raw/notes/C.md"))

    def test_write_revert_restores_the_original_frontmatter(self):
        before = self.read("raw/notes/A.md")
        self._run("--phase", "write", "--apply")
        self.assertNotEqual(self.read("raw/notes/A.md"), before)
        result = self._run("--phase", "write-revert", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("raw/notes/A.md"), before)

    def test_last_assignment_per_path_wins(self):
        self.write(".tags/assigned.jsonl",
                   '{"path": "raw/notes/A.md", "tags": ["ai/agents"]}\n'
                   '{"path": "raw/notes/A.md", "tags": ["ai/general"]}\n')
        self._run("--phase", "write", "--apply")
        content = self.read("raw/notes/A.md")
        self.assertIn("ai/general", content)
        self.assertNotIn("ai/agents", content)

    def test_write_without_assignments_errors(self):
        (self.root / ".tags" / "assigned.jsonl").unlink()
        result = self._run("--phase", "write")
        self.assertEqual(result.returncode, 1)
        self.assertIn("run --phase assign first", result.stderr)


class NamespaceRescueTest(unittest.TestCase):
    """The model's commonest miss is the right term under the wrong namespace."""

    VOCAB = ["automotive/horizon", "system/pu-ivi",
             "ai/strategy", "business/strategy", "map/hd-map"]
    RECORDS = [rec("a.md")]

    def test_unambiguous_term_is_rescued(self):
        assigns, rejected = parse_assignments(
            "1\tnavigation/horizon org/pu-ivi\n", self.RECORDS, self.VOCAB)
        self.assertEqual(assigns["a.md"], ["automotive/horizon", "system/pu-ivi"])
        self.assertEqual(rejected, {})

    def test_ambiguous_term_stays_rejected(self):
        # process/strategy could be ai/strategy or business/strategy; choosing
        # is judgement, so it is reported rather than guessed.
        assigns, rejected = parse_assignments(
            "1\tprocess/strategy map/hd-map\n", self.RECORDS, self.VOCAB)
        self.assertEqual(assigns["a.md"], ["map/hd-map"])
        self.assertEqual(dict(rejected), {"process/strategy": 1})

    def test_genuinely_new_term_stays_rejected(self):
        _a, rejected = parse_assignments(
            "1\tdata/data-consumption\n", self.RECORDS, self.VOCAB)
        self.assertEqual(dict(rejected), {"data/data-consumption": 1})

    def test_rescue_does_not_duplicate_an_already_assigned_tag(self):
        assigns, _ = parse_assignments(
            "1\tautomotive/horizon navigation/horizon\n", self.RECORDS, self.VOCAB)
        self.assertEqual(assigns["a.md"], ["automotive/horizon"])

    def test_rescue_never_resurrects_a_year_tag(self):
        _a, rejected = parse_assignments(
            "1\tyear/2022\n", self.RECORDS, self.VOCAB + ["year/2022"])
        self.assertEqual(dict(rejected), {"year/2022": 1})

    def test_rescue_can_be_switched_off(self):
        assigns, rejected = parse_assignments(
            "1\tnavigation/horizon\n", self.RECORDS, self.VOCAB,
            rescue_namespace=False)
        self.assertEqual(assigns, {})
        self.assertEqual(dict(rejected), {"navigation/horizon": 1})
