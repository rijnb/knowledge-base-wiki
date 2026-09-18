"""Tests for lib.checks.tags — the wiki-doctor tag lint (phase 7)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.checks.tags import check_tags  # noqa: E402


class CheckTagsTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("config/tags.md",
                   "## ai\n\n- `ai/agents`\n- `ai/general`\n\n## year\n\n- `year/2022`\n")

    def test_approved_tags_are_clean(self):
        self.write("raw/notes/a.md", "---\ntags: [ai/agents, year/2022]\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["tag_issues"], [])
        self.assertEqual(result["summary"]["tag_errors"], 0)

    def test_unapproved_tag_is_flagged(self):
        self.write("raw/notes/a.md", "---\ntags: [ai/agents, map/hd-map]\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual([i["tag"] for i in result["tag_issues"]], ["map/hd-map"])
        self.assertEqual(result["tag_issues"][0]["problem"], "unapproved")

    def test_every_malformed_shape_is_flagged(self):
        # One segment, an Obsidian-illegal colon, uppercase, four segments.
        self.write("raw/notes/a.md", "---\ntags: [megacorp, 1:1, A/B, a/b/c/d]\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["summary"]["malformed"], 4)
        self.assertTrue(all(i["problem"] == "malformed" for i in result["tag_issues"]))

    def test_untagged_notes_are_counted_not_flagged(self):
        # A coverage gap for the assign phase, not a fault in the note.
        self.write("raw/notes/a.md", "---\ntype: note\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["tag_issues"], [])
        self.assertEqual(result["summary"]["untagged_notes"], 1)

    def test_block_and_scalar_tag_shapes_are_read(self):
        self.write("raw/notes/block.md", "---\ntags:\n  - map/hd-map\n---\nx\n")
        self.write("raw/notes/scalar.md", "---\ntags: map/hd-map\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["summary"]["unapproved"], 2)

    def test_structural_files_are_not_checked(self):
        self.write("wiki/systems/index.md", "---\ntags: [not/approved]\n---\nx\n")
        self.write("INBOX/RELEASE-NOTES.md", "---\ntags: [not/approved]\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["tag_issues"], [])

    def test_missing_vocabulary_does_not_condemn_every_tag(self):
        # Without config/tags.md the pipeline is simply not set up; reporting
        # every tag in the vault as unapproved would be useless noise.
        (self.root / "config" / "tags.md").unlink()
        self.write("raw/notes/a.md", "---\ntags: [ai/agents, map/hd-map]\n---\nx\n")
        result = check_tags(self.root)
        self.assertEqual(result["summary"]["unapproved"], 0)
        self.assertEqual(result["summary"]["vocabulary_size"], 0)

    def test_malformed_is_flagged_even_without_a_vocabulary(self):
        (self.root / "config" / "tags.md").unlink()
        self.write("raw/notes/a.md", "---\ntags: [megacorp]\n---\nx\n")
        self.assertEqual(check_tags(self.root)["summary"]["malformed"], 1)


if __name__ == "__main__":
    unittest.main()
